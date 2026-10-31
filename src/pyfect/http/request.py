"""HTTP requests (Effect's ``HttpClientRequest``): immutable values a client
executes.

Build one with ``get`` / ``post`` / ... and refine it with its methods,
each giving a new request::

    request = (
        post("https://api.example.com/todos", accept_json=True)
        .bearer_token(token)
        .body_json_unsafe({"title": "write docs"})
    )

The URL stays as written; ``url_params`` and ``hash`` are added to it when
the request is sent (``to_url``).
"""

from __future__ import annotations

import base64
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, TypedDict, Unpack, final
from urllib.parse import SplitResult

from pyfect import byte_size
from pyfect._js import text_encode
from pyfect.effect import Effect, succeed
from pyfect.http import body as _body
from pyfect.http import url as _url
from pyfect.http import url_params as _params
from pyfect.http._compression import CompressionAlgorithm, compress_body
from pyfect.http.headers import EMPTY as EMPTY_HEADERS
from pyfect.http.headers import Headers
from pyfect.http.headers import Input as HeadersInput
from pyfect.http.method import HttpMethod
from pyfect.redacted import Redacted
from pyfect.redacted import value as redacted_value
from pyfect.result import Ok
from pyfect.schema import Codec
from pyfect.schema._options import ParseOptions
from pyfect.stream import Stream

if TYPE_CHECKING:
    from pyfect.file_system import FileSystem
    from pyfect.platform_error import PlatformError

type UrlInput = str | SplitResult


class RequestOptions(TypedDict, total=False):
    """What a request is built with, besides its method and URL."""

    url_params: _params.Input
    hash: str
    headers: HeadersInput
    body: _body.HttpBody
    accept: str
    accept_json: bool


class ModifyOptions(RequestOptions, total=False):
    method: HttpMethod
    url: UrlInput


def _plain(value: str | Redacted[str]) -> str:
    return value if isinstance(value, str) else redacted_value(value)


def _join_segments(first: str, second: str) -> str:
    if first.endswith("/") and second.startswith("/"):
        return first + second[1:]
    if not first.endswith("/") and not second.startswith("/"):
        return f"{first}/{second}"
    return first + second


@final
@dataclass(frozen=True, slots=True)
class HttpClientRequest:
    method: HttpMethod
    url: str
    url_params: _params.UrlParams
    hash: str | None
    headers: Headers
    body: _body.HttpBody

    def __repr__(self) -> str:
        return (
            f"HttpClientRequest({self.method} {_params.redact_url(self.url)}, "
            f"url_params={self.url_params!r}, headers={self.headers!r}, body={self.body.tag})"
        )

    def to_json(self) -> dict[str, object]:
        return {
            "_id": "HttpClientRequest",
            "method": self.method,
            "url": _params.redact_url(self.url),
            "url_params": self.url_params.to_json(),
            "hash": self.hash,
            "headers": self.headers.to_json(),
            "body": self.body.to_json(),
        }

    def _with(
        self,
        *,
        method: HttpMethod | None = None,
        url: str | None = None,
        url_params: _params.UrlParams | None = None,
        headers: Headers | None = None,
        body: _body.HttpBody | None = None,
    ) -> HttpClientRequest:
        return HttpClientRequest(
            self.method if method is None else method,
            self.url if url is None else url,
            self.url_params if url_params is None else url_params,
            self.hash,
            self.headers if headers is None else headers,
            self.body if body is None else body,
        )

    def modify(self, **options: Unpack[ModifyOptions]) -> HttpClientRequest:
        result = self
        if "method" in options:
            result = result.set_method(options["method"])
        url = options.get("url")
        if url:
            result = result.set_url(url)
        if "headers" in options:
            result = result.set_headers(options["headers"])
        if "url_params" in options:
            result = result.set_url_params(options["url_params"])
        hash = options.get("hash")
        if hash:
            result = result.set_hash(hash)
        if "body" in options:
            result = result.set_body(options["body"])
        accept = options.get("accept")
        if accept:
            result = result.accept(accept)
        if options.get("accept_json"):
            result = result.accept_json()
        return result

    def set_method(self, method: HttpMethod) -> HttpClientRequest:
        return self._with(method=method)

    def set_header(self, key: str, value: str) -> HttpClientRequest:
        return self._with(headers=self.headers.set(key, value))

    def set_headers(self, input: HeadersInput) -> HttpClientRequest:
        return self._with(headers=self.headers.set_all(input))

    def update_headers(self, f: Callable[[Headers], Headers]) -> HttpClientRequest:
        return self._with(headers=f(self.headers))

    def remove_header(self, key: str) -> HttpClientRequest:
        return self._with(headers=self.headers.remove(key))

    def basic_auth(
        self, username: str | Redacted[str], password: str | Redacted[str]
    ) -> HttpClientRequest:
        credentials = text_encode(f"{_plain(username)}:{_plain(password)}")
        return self.set_header(
            "Authorization", f"Basic {base64.b64encode(credentials).decode('ascii')}"
        )

    def bearer_token(self, token: str | Redacted[str]) -> HttpClientRequest:
        return self.set_header("Authorization", f"Bearer {_plain(token)}")

    def accept(self, media_type: str) -> HttpClientRequest:
        return self.set_header("Accept", media_type)

    def accept_json(self) -> HttpClientRequest:
        return self.accept("application/json")

    def upgrade(self, protocol: str) -> HttpClientRequest:
        return self._with(
            headers=self.headers.set("connection", "Upgrade").set("upgrade", protocol)
        )

    def set_url(self, url: UrlInput) -> HttpClientRequest:
        """A string URL is kept as written; a parsed URL gives its query to
        ``url_params`` and its fragment to ``hash``."""
        if isinstance(url, str):
            return self._with(url=url)
        return HttpClientRequest(
            self.method,
            _url.href(url._replace(query="", fragment="")),
            _params.parse(url.query),
            url.fragment or None,
            self.headers,
            self.body,
        )

    def prepend_url(self, path: str) -> HttpClientRequest:
        return self if path == "" else self._with(url=_join_segments(path, self.url))

    def append_url(self, path: str) -> HttpClientRequest:
        return self if path == "" else self._with(url=_join_segments(self.url, path))

    def update_url(self, f: Callable[[str], str]) -> HttpClientRequest:
        return self._with(url=f(self.url))

    def set_url_param(self, key: str, value: str | Redacted[str]) -> HttpClientRequest:
        return self._with(url_params=self.url_params.set(key, value))

    def set_url_params(self, input: _params.Input) -> HttpClientRequest:
        return self._with(url_params=self.url_params.set_all(input))

    def append_url_param(self, key: str, value: str | Redacted[str]) -> HttpClientRequest:
        return self._with(url_params=self.url_params.append(key, value))

    def append_url_params(self, input: _params.Input) -> HttpClientRequest:
        return self._with(url_params=self.url_params.append_all(input))

    def set_hash(self, hash: str) -> HttpClientRequest:
        return HttpClientRequest(
            self.method, self.url, self.url_params, hash, self.headers, self.body
        )

    def remove_hash(self) -> HttpClientRequest:
        return HttpClientRequest(
            self.method, self.url, self.url_params, None, self.headers, self.body
        )

    def set_body(self, body: _body.HttpBody) -> HttpClientRequest:
        """``body``, with ``content-type`` and ``content-length`` set from it."""
        return HttpClientRequest(
            self.method,
            self.url,
            self.url_params,
            self.hash,
            _body.update_headers(self.headers, body),
            body,
        )

    def compress_body(
        self, algorithm: CompressionAlgorithm, *, min_size: int = 1024
    ) -> Effect[HttpClientRequest]:
        """The body compressed with ``algorithm`` and ``content-encoding``
        set; unchanged when it already has a ``content-encoding``, is too
        short or cannot be compressed."""
        if "content-encoding" in self.headers:
            return succeed(self)
        return compress_body(self.body, algorithm, min_size).map(
            lambda body: (
                self
                if body is self.body
                else self.set_body(body).set_header("content-encoding", algorithm)
            )
        )

    def body_bytes(self, body: bytes, content_type: str | None = None) -> HttpClientRequest:
        return self.set_body(_body.bytes_(body, content_type))

    def body_text(self, body: str, content_type: str | None = None) -> HttpClientRequest:
        return self.set_body(_body.text(body, content_type))

    def body_json(self, body: object) -> Effect[HttpClientRequest, _body.HttpBodyError]:
        return _body.json(body).map(self.set_body)

    def body_json_unsafe(self, body: object) -> HttpClientRequest:
        return self.set_body(_body.json_unsafe(body))

    def body_url_params(self, input: _params.Input) -> HttpClientRequest:
        return self.set_body(_body.url_params(input))

    def body_form_data(self, body: _body.FormData) -> HttpClientRequest:
        return self.set_body(body)

    def body_form_data_record(self, entries: _body.FormDataInput) -> HttpClientRequest:
        return self.set_body(_body.form_data_record(entries))

    def body_stream(
        self,
        body: Stream[bytes, object],
        *,
        content_type: str | None = None,
        content_length: int | None = None,
    ) -> HttpClientRequest:
        streamed = _body.stream(body, content_type, content_length)
        return self.set_body(streamed)

    def body_file(
        self,
        path: str,
        *,
        bytes_to_read: byte_size.Input | None = None,
        chunk_size: int | None = None,
        offset: byte_size.Input | None = None,
        content_type: str | None = None,
    ) -> Effect[HttpClientRequest, PlatformError, FileSystem]:
        return _body.file(
            path,
            bytes_to_read=bytes_to_read,
            chunk_size=chunk_size,
            offset=offset,
            content_type=content_type,
        ).map(self.set_body)

    def to_url(self) -> SplitResult | None:
        """The URL the request is sent to, or ``None`` when it is invalid."""
        match _url.make(self.url, self.url_params, self.hash):
            case Ok(url):
                return url
            case _:
                return None


EMPTY: HttpClientRequest = HttpClientRequest(
    "GET", "", _params.EMPTY, None, EMPTY_HEADERS, _body.EMPTY
)


def make(method: HttpMethod, url: UrlInput, **options: Unpack[RequestOptions]) -> HttpClientRequest:
    return EMPTY.modify(method=method, url=url, **options)


def get(url: UrlInput, **options: Unpack[RequestOptions]) -> HttpClientRequest:
    return make("GET", url, **options)


def post(url: UrlInput, **options: Unpack[RequestOptions]) -> HttpClientRequest:
    return make("POST", url, **options)


def put(url: UrlInput, **options: Unpack[RequestOptions]) -> HttpClientRequest:
    return make("PUT", url, **options)


def patch(url: UrlInput, **options: Unpack[RequestOptions]) -> HttpClientRequest:
    return make("PATCH", url, **options)


def delete(url: UrlInput, **options: Unpack[RequestOptions]) -> HttpClientRequest:
    return make("DELETE", url, **options)


def head(url: UrlInput, **options: Unpack[RequestOptions]) -> HttpClientRequest:
    return make("HEAD", url, **options)


def options(url: UrlInput, **options: Unpack[RequestOptions]) -> HttpClientRequest:
    return make("OPTIONS", url, **options)


def trace(url: UrlInput, **options: Unpack[RequestOptions]) -> HttpClientRequest:
    return make("TRACE", url, **options)


def query(url: UrlInput, **options: Unpack[RequestOptions]) -> HttpClientRequest:
    return make("QUERY", url, **options)


def schema_body_json[T, RE](
    schema: Codec[T, object, object, RE], **parse_options: Unpack[ParseOptions]
) -> Callable[[HttpClientRequest, T], Effect[HttpClientRequest, _body.HttpBodyError, RE]]:
    """A setter of JSON bodies encoded by ``schema``:
    ``schema_body_json(Todo)(request, todo)``."""
    encode = _body.json_schema(schema, **parse_options)
    return lambda request, value: encode(value, None).map(request.set_body)


__all__ = [
    "EMPTY",
    "CompressionAlgorithm",
    "HttpClientRequest",
    "ModifyOptions",
    "RequestOptions",
    "UrlInput",
    "delete",
    "get",
    "head",
    "make",
    "options",
    "patch",
    "post",
    "put",
    "query",
    "schema_body_json",
    "trace",
]
