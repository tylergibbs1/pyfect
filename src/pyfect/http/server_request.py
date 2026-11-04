"""The request a server handles (Effect's ``HttpServerRequest``).

A ``ServerRequest`` is its method, URL (``url``, as the router sees it,
and ``original_url``, as received), headers, cookies, addresses, and its
body, read as ``bytes_``, ``text``, ``json``, ``url_params_body``,
``stream``, or as multipart parts (``multipart_stream``) and a persisted
form (``multipart``). A body is read once: every read after the first
gives the same bytes, and ``MaxBodySize`` bounds it (``BodyTooLarge``,
413). Handlers get the current request from the ``HttpServerRequest``
service::

    request = yield from HttpServerRequest()
"""

# pyright: reportPrivateUsage=false

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable, Mapping
from functools import cached_property
from typing import TYPE_CHECKING, Any, Literal, Unpack, cast, final
from urllib.parse import SplitResult

from pyfect._cached import memoize
from pyfect._core import Effect, _WithFiber
from pyfect._js import text_encode
from pyfect._json_text import PARSE_ERRORS, Json, parse
from pyfect.context import Tag
from pyfect.effect import fail, succeed, suspend
from pyfect.file_system import FileSystem
from pyfect.http import _form_data, incoming_message
from pyfect.http import body as _body
from pyfect.http import url as _url
from pyfect.http._authority import ROOT, absolute_url, parse_authority, parse_origin_form
from pyfect.http.cookies import parse_header as parse_cookie_header
from pyfect.http.headers import Headers
from pyfect.http.headers import Input as HeadersInput
from pyfect.http.incoming_message import MaxBodySize, Reviver
from pyfect.http.method import HttpMethod, has_body
from pyfect.http.request import HttpClientRequest
from pyfect.http.server_error import HttpServerError, RequestParseError, request_parse_error
from pyfect.http.server_response import parse_content_length
from pyfect.http.url_params import EMPTY as EMPTY_URL_PARAMS
from pyfect.http.url_params import UrlParams
from pyfect.http.url_params import parse as parse_url_params
from pyfect.http.url_params import to_string as url_params_to_string
from pyfect.path import Path
from pyfect.result import Err, Ok, Result
from pyfect.schema import Codec, SchemaError, decode_unknown_effect
from pyfect.schema._options import ParseOptions
from pyfect.scope import Scope
from pyfect.socket import SocketService
from pyfect.stream import Stream, from_effect
from pyfect.stream import empty as empty_stream
from pyfect.stream import fail as fail_stream
from pyfect.stream import succeed as succeed_stream
from pyfect.stream._base import require_stream

if TYPE_CHECKING:
    from pyfect.http.multipart import Part, Persisted


type RequestProtocol = Literal["http", "https"]


class _Unset:
    __slots__ = ()


_UNSET = _Unset()


class ServerRequest(ABC):
    """A request the server is handling."""

    def __init__(
        self,
        url: str | None = None,
        headers: Headers | None = None,
        remote_address: str | None = None,
        peer_address: str | None = None,
        protocol: RequestProtocol | None = None,
    ) -> None:
        self._url: str | None = url
        self._headers: Headers | None = headers
        self._remote_address: str | None = remote_address
        self._peer_address: str | None = peer_address
        self._protocol: RequestProtocol | None = protocol

    # --- what a source gives ---------------------------------------------------

    @property
    @abstractmethod
    def source(self) -> object:
        """What the request was made from (an ``HttpClientRequest``, the
        live server's connection state, an ASGI scope)."""

    @property
    @abstractmethod
    def original_url(self) -> str:
        """The URL as received."""

    @property
    @abstractmethod
    def method(self) -> HttpMethod: ...

    @abstractmethod
    def _source_headers(self) -> Headers: ...

    @property
    @abstractmethod
    def stream(self) -> Stream[bytes, HttpServerError]:
        """The body as it arrives."""

    @property
    @abstractmethod
    def bytes_(self) -> Effect[bytes, HttpServerError]:
        """The whole body, read once (Effect's ``arrayBuffer``)."""

    @abstractmethod
    def _copy(self) -> ServerRequest:
        """A request on the same source and body, to be modified."""

    def upgrade_with(
        self, *, headers: HeadersInput | None = None
    ) -> Effect[SocketService, HttpServerError]:
        """Upgrade the connection to a WebSocket, answering with ``headers``
        too; a request that cannot be upgraded fails."""
        del headers
        return fail(request_parse_error(self, "Not an upgradeable ServerRequest"))

    # --- derived ---------------------------------------------------------------

    @property
    def url(self) -> str:
        """The path and query (the router may have removed a prefix)."""
        return remove_host(self.original_url) if self._url is None else self._url

    @property
    def headers(self) -> Headers:
        if self._headers is None:
            self._headers = self._source_headers()
        return self._headers

    @property
    def remote_address(self) -> str | None:
        """The client's address (behind proxies, as they report it)."""
        return self._remote_address

    @property
    def peer_address(self) -> str | None:
        """The address of the connection's other end."""
        return self._remote_address if self._peer_address is None else self._peer_address

    @property
    def protocol(self) -> RequestProtocol | None:
        return self._protocol

    @cached_property
    def cookies(self) -> Mapping[str, str]:
        return parse_cookie_header(self.headers.get("cookie", ""))

    @property
    def upgrade(self) -> Effect[SocketService, HttpServerError]:
        return self.upgrade_with()

    @property
    def text(self) -> Effect[str, HttpServerError]:
        """The body as UTF-8 (invalid bytes become U+FFFD)."""
        return self.bytes_.map(lambda data: data.decode("utf-8-sig", "replace"))

    def _parse_json(self, text: str) -> Effect[Json, HttpServerError]:
        try:
            return succeed(parse(text))
        except PARSE_ERRORS as cause:
            return fail(request_parse_error(self, None, cause))

    @property
    def json(self) -> Effect[Json, HttpServerError]:
        """The body parsed as JSON."""
        return self.text.flat_map(self._parse_json)

    @property
    def url_params_body(self) -> Effect[UrlParams, HttpServerError]:
        return self.text.map(parse_url_params)

    @property
    def multipart_stream(self) -> Stream[Part, Any]:
        """The body's multipart parts, as they arrive."""
        from pyfect.http.multipart import MultipartError, make_channel

        chunks = self.stream.map_error(
            lambda cause: MultipartError.from_reason("InternalError", cause)
        )
        return chunks.pipe_through_channel(make_channel(self.headers))

    @cached_property
    def multipart(self) -> Effect[Persisted, Any, Scope | FileSystem | Path]:
        """The body's multipart form, its files written to a scoped
        temporary directory (once)."""
        from pyfect.http.multipart import to_persisted

        return memoize(to_persisted(self.multipart_stream))

    def modify(
        self,
        *,
        url: str | None = None,
        headers: Headers | None = None,
        remote_address: str | _Unset | None = _UNSET,
        peer_address: str | None = None,
        protocol: RequestProtocol | None = None,
    ) -> ServerRequest:
        """The request with these parts replaced (``remote_address=None``
        removes it); its body is this request's."""
        copy = self._copy()
        copy._url = self.url if url is None else url
        copy._headers = self._headers if headers is None else headers
        copy._remote_address = (
            self._remote_address if isinstance(remote_address, _Unset) else remote_address
        )
        copy._peer_address = self._peer_address if peer_address is None else peer_address
        copy._protocol = self._protocol if protocol is None else protocol
        return copy

    def __repr__(self) -> str:
        return f"ServerRequest({self.method} {self.url})"

    def to_json(self) -> dict[str, object]:
        from pyfect.http.url_params import redact_url

        return {
            "_id": "HttpServerRequest",
            "method": self.method,
            "url": redact_url(self.original_url),
            "headers": self.headers.to_json(),
            "remoteAddress": self.remote_address,
        }


class HttpServerRequest(Tag[ServerRequest], key="effect/http/HttpServerRequest"):
    """The request being handled."""


class ParsedSearchParams(Tag[Mapping[str, str | list[str]]], key="effect/http/ParsedSearchParams"):
    """The request's query parameters: each name's value, or values when
    repeated."""


def remove_host(url: str) -> str:
    """The path and query of a URL that may be absolute."""
    if url.startswith("/"):
        return url
    start = url.find("//")
    index = url.find("/", start + 2)
    return "/" if index == -1 else url[index:]


def search_params_from_url(url: SplitResult) -> dict[str, str | list[str]]:
    """The query of ``url``: each name's value, or values when repeated."""
    return parse_url_params(url.query).to_record()


def to_url(request: ServerRequest) -> _url.Url | None:
    """The request's full URL, from its ``host`` header (``localhost``
    without one) and protocol; ``None`` when that is no valid URL, or the
    host is no authority (so it cannot change the path or query)."""
    authority = parse_authority(request.headers.get("host") or "localhost")
    if authority is None:
        return None
    protocol = request.protocol or (
        "https" if request.original_url[:6].lower() == "https:" else "http"
    )
    url = request.url
    origin = parse_origin_form(url)
    try:
        if origin is not None:
            return _url.parse(absolute_url(protocol, authority, origin))
        return _url.parse(url, absolute_url(protocol, authority, ROOT))
    except ValueError:
        return None


def to_url_result(request: ServerRequest) -> Result[_url.Url, RequestParseError]:
    url = to_url(request)
    if url is None:
        return Err(RequestParseError(request, "Invalid URL"))
    return Ok(url)


# --- reading a body with a limit ----------------------------------------------


class BodyTooLargeError(Exception):
    def __init__(self, max_bytes: int) -> None:
        super().__init__(f"Request body exceeds {max_bytes} bytes")


def read_limited[E](
    chunks: Stream[bytes, E], content_length: int | None, max_bytes: int | None
) -> Effect[bytes, E | BodyTooLargeError | ValueError]:
    """The bytes of ``chunks``; past ``max_bytes`` (or the declared
    ``content_length``) the read stops and fails."""
    require_stream(chunks, "chunks")
    if max_bytes is not None and content_length is not None and content_length > max_bytes:
        return fail(BodyTooLargeError(max_bytes))
    limit = content_length if content_length is not None else max_bytes
    out = bytearray()

    def add(chunk: bytes) -> Effect[None, BodyTooLargeError | ValueError]:
        out.extend(chunk)
        if limit is not None and len(out) > limit:
            if max_bytes is not None and len(out) > max_bytes:
                return fail(BodyTooLargeError(max_bytes))
            return fail(
                ValueError(f"Request body is longer than its content-length of {content_length}")
            )
        return succeed(None)

    return chunks.run_for_each(add).map(lambda _: bytes(out))


class _SharedBody:
    """A body read once and shared by a request and its modified copies."""

    __slots__ = ("_bytes", "_open", "_open_read", "_read")

    def __init__(
        self,
        open: Callable[[], Stream[bytes, object]] | None,
        open_read: Callable[[], Stream[bytes, object]] | None = None,
    ) -> None:
        self._open = open
        self._open_read = open_read or open
        self._read = False
        self._bytes: Effect[bytes, HttpServerError] | None = None

    def stream(self, request: ServerRequest) -> Stream[bytes, HttpServerError]:
        if self._bytes is not None:
            return _stream_of(self._bytes)
        if self._open is None:
            return fail_stream(
                request_parse_error(request, "can not create stream from empty body")
            )
        opened = self._open
        return opened().map_error(lambda cause: request_parse_error(request, None, cause))

    def bytes_(self, request: ServerRequest) -> Effect[bytes, HttpServerError]:
        if self._bytes is None:
            self._bytes = memoize(
                _WithFiber(lambda fiber: self._read_all(request, fiber.get_ref(MaxBodySize)))
            )
        return self._bytes

    def _read_all(
        self, request: ServerRequest, max_bytes: int | None
    ) -> Effect[bytes, HttpServerError]:
        if self._open_read is None:
            return succeed(b"")
        content_length = parse_content_length(request.headers.get("content-length"))

        def on_error(cause: object) -> HttpServerError:
            if isinstance(cause, BodyTooLargeError):
                return request_parse_error(request, None, cause, "BodyTooLarge")
            return request_parse_error(request, None, cause)

        return read_limited(self._open_read(), content_length, max_bytes).map_error(on_error)


def _stream_of(data: Effect[bytes, HttpServerError]) -> Stream[bytes, HttpServerError]:
    """The bytes of a body already read, as a stream (none when empty)."""
    return from_effect(data).filter(lambda chunk: len(chunk) > 0)


@final
class SourceRequest(ServerRequest):
    """A request a server received: its method, URL as sent, headers, and a
    body that can be opened once (``None``: no body)."""

    def __init__(
        self,
        method: str,
        url: str,
        headers: Headers,
        body: Callable[[], Stream[bytes, object]] | None,
        *,
        source: object = None,
        remote_address: str | None = None,
        protocol: RequestProtocol | None = None,
        upgrade: Callable[[Headers], Effect[SocketService, object]] | None = None,
        read_body: Callable[[], Stream[bytes, object]] | None = None,
    ) -> None:
        """``read_body`` opens the body for reading it whole, when that
        differs from streaming it."""
        super().__init__(None, headers, remote_address, None, protocol)
        self._method = method.upper()
        self._original_url = url
        self._body = _SharedBody(body, read_body)
        self._source = source
        self._upgrade = upgrade

    @property
    def source(self) -> object:
        return self._source

    @property
    def original_url(self) -> str:
        return self._original_url

    @property
    def method(self) -> HttpMethod:
        return cast("HttpMethod", self._method)

    def _source_headers(self) -> Headers:
        raise AssertionError("a SourceRequest always has headers")

    @property
    def stream(self) -> Stream[bytes, HttpServerError]:
        return self._body.stream(self)

    @property
    def bytes_(self) -> Effect[bytes, HttpServerError]:
        return self._body.bytes_(self)

    def upgrade_with(
        self, *, headers: HeadersInput | None = None
    ) -> Effect[SocketService, HttpServerError]:
        if self._upgrade is None:
            return super().upgrade_with(headers=headers)
        from pyfect.http.headers import from_input
        from pyfect.http.origin import require_allowed_origin

        upgrade = self._upgrade
        upgraded = upgrade(from_input(headers)).map_error(
            lambda cause: (
                cause
                if isinstance(cause, HttpServerError)
                else request_parse_error(self, None, cause)
            )
        )
        return require_allowed_origin(self).and_then(upgraded)

    def _copy(self) -> ServerRequest:
        copy = SourceRequest.__new__(SourceRequest)
        vars(copy).update(
            {k: v for k, v in vars(self).items() if k not in ("cookies", "multipart")}
        )
        return copy


@final
class ClientRequest(ServerRequest):
    """A server request made from an ``HttpClientRequest`` (Effect's
    ``fromClientRequest``), as test clients send."""

    def __init__(self, source: HttpClientRequest, original_url: str) -> None:
        super().__init__()
        self._source = source
        self._original_url = original_url
        self._bytes: Effect[bytes, HttpServerError] | None = None

    @property
    def source(self) -> HttpClientRequest:
        return self._source

    @property
    def original_url(self) -> str:
        return self._original_url

    @property
    def method(self) -> HttpMethod:
        return self._source.method

    def _source_headers(self) -> Headers:
        return self._source.headers

    @property
    def stream(self) -> Stream[bytes, HttpServerError]:
        body = self._source.body
        match body:
            case _body.Empty():
                return empty_stream
            case _body.Bytes():
                return succeed_stream(body.body)
            case _body.Stream():
                return body.stream.map_error(lambda cause: request_parse_error(self, None, cause))
            case _body.FormData():
                return succeed_stream(_form_data.encode(body)[0])
            case _body.Raw():
                data = _raw_bytes(body.body)
                if data is None:
                    return fail_stream(request_parse_error(self, "Unsupported body type"))
                return succeed_stream(data)

    @property
    def bytes_(self) -> Effect[bytes, HttpServerError]:
        if self._bytes is None:
            self._bytes = memoize(suspend(self._read))
        return self._bytes

    def _read(self) -> Effect[bytes, HttpServerError]:
        body = self._source.body
        if isinstance(body, _body.Raw):
            data = _raw_bytes(body.body)
            if data is None:
                return fail(request_parse_error(self, "Unsupported body type"))
            return succeed(data)
        return self.stream.run_collect().map(b"".join)

    @property
    def json(self) -> Effect[Json, HttpServerError]:
        return self.text.flat_map(
            lambda text: succeed(None) if text == "" else self._parse_json(text)
        )

    @property
    def multipart_stream(self) -> Stream[Part, Any]:
        form = form_data_body(self)
        if form is None:
            return super().multipart_stream
        from pyfect.http.multipart import Field, File
        from pyfect.stream import from_iterable

        parts: list[Part] = [
            Field(key, "text/plain", value)
            if isinstance(value, str)
            else File(key, value.name, value.content_type, succeed_stream(value.content))
            for key, value in form.entries
        ]
        return from_iterable(parts)

    def _copy(self) -> ServerRequest:
        copy = ClientRequest.__new__(ClientRequest)
        vars(copy).update(
            {k: v for k, v in vars(self).items() if k not in ("cookies", "multipart")}
        )
        return copy


def _raw_bytes(value: object) -> bytes | None:
    if isinstance(value, bytes):
        return value
    if isinstance(value, bytearray):
        return bytes(value)
    if isinstance(value, str):
        return text_encode(value)
    if isinstance(value, UrlParams):
        return text_encode(url_params_to_string(value))
    return None


def form_data_body(request: ServerRequest) -> _body.FormData | None:
    """The form of a request made from a client request with a form body."""
    source = request.source
    if not isinstance(source, HttpClientRequest):
        return None
    body = source.body
    if isinstance(body, _body.FormData):
        return body
    if isinstance(body, _body.Raw) and isinstance(body.body, _body.FormData):
        return body.body
    return None


def from_client_request(request: HttpClientRequest) -> ServerRequest:
    """A server request made from ``request`` (its full URL as received)."""
    url = request.to_url()
    return ClientRequest(request, request.url if url is None else _url.href(url))


def _client_body(request: ServerRequest) -> _body.HttpBody:
    if not has_body(request.method):
        return _body.EMPTY
    form = form_data_body(request)
    if form is not None:
        return form
    return _body.stream(
        cast("Stream[bytes, object]", request.stream),
        request.headers.get("content-type"),
        parse_content_length(request.headers.get("content-length")),
    )


def to_client_request(request: ServerRequest) -> HttpClientRequest:
    """``request`` as an ``HttpClientRequest`` to its full URL, streaming
    its body."""
    body = _client_body(request)
    headers = request.headers
    if not isinstance(body, _body.Empty) and body.content_length is None:
        headers = headers.remove("content-length")
    url = to_url(request)
    client = HttpClientRequest(request.method, "", EMPTY_URL_PARAMS, None, headers, body)
    # A parsed URL gives its query to ``url_params`` and its fragment to ``hash``.
    return client.set_url(request.url if url is None else url)


def is_multipart(request: ServerRequest) -> bool:
    content_type = request.headers.get("content-type", "")
    return "multipart/form-data" in content_type.lower() or form_data_body(request) is not None


# --- schema helpers ------------------------------------------------------------


def schema_cookies[T, RD](
    schema: Codec[T, Any, RD, Any], **options: Unpack[ParseOptions]
) -> Effect[T, SchemaError, RD | HttpServerRequest]:
    """The request's cookies decoded by ``schema``."""
    decode = decode_unknown_effect(schema, **options)
    return HttpServerRequest().flat_map(lambda request: decode(dict(request.cookies)))


def schema_headers[T, RD](
    schema: Codec[T, Any, RD, Any], **options: Unpack[ParseOptions]
) -> Effect[T, SchemaError, RD | HttpServerRequest]:
    """The request's headers (lowercased names) decoded by ``schema``."""
    decode = decode_unknown_effect(schema, **options)
    return HttpServerRequest().flat_map(lambda request: decode(dict(request.headers)))


def schema_search_params[T, RD](
    schema: Codec[T, Any, RD, Any], **options: Unpack[ParseOptions]
) -> Effect[T, SchemaError, RD | ParsedSearchParams]:
    """The query parameters decoded by ``schema``."""
    decode = decode_unknown_effect(schema, **options)
    return ParsedSearchParams().flat_map(lambda params: decode(dict(params)))


def schema_body_json[T, RD](
    schema: Codec[T, Any, RD, Any],
    *,
    reviver: Reviver | None = None,
    **options: Unpack[ParseOptions],
) -> Effect[T, HttpServerError | SchemaError, RD | HttpServerRequest]:
    """The JSON body decoded by ``schema``."""
    decode = incoming_message.schema_body_json(schema, reviver=reviver, **options)
    return HttpServerRequest().flat_map(decode)


def schema_body_url_params[T, RD](
    schema: Codec[T, Any, RD, Any], **options: Unpack[ParseOptions]
) -> Effect[T, HttpServerError | SchemaError, RD | HttpServerRequest]:
    """The form-encoded body decoded by ``schema``."""
    decode = incoming_message.schema_body_url_params(schema, **options)
    return HttpServerRequest().flat_map(decode)


def schema_body_multipart[T, RD](
    schema: Codec[T, Any, RD, Any], **options: Unpack[ParseOptions]
) -> Effect[T, Any, RD | HttpServerRequest | Scope | FileSystem | Path]:
    """The multipart form decoded by ``schema`` (its files persisted)."""
    decode = decode_unknown_effect(schema, **options)
    return HttpServerRequest().flat_map(
        lambda request: request.multipart.flat_map(lambda persisted: decode(dict(persisted)))
    )


def schema_body_form[T, RD](
    schema: Codec[T, Any, RD, Any], **options: Unpack[ParseOptions]
) -> Effect[T, Any, RD | HttpServerRequest | Scope | FileSystem | Path]:
    """A multipart or form-encoded body decoded by ``schema``."""
    decode = decode_unknown_effect(schema, **options)
    url_params = incoming_message.schema_body_url_params(schema, **options)

    def read(request: ServerRequest) -> Effect[T, Any, Any]:
        if is_multipart(request):
            return request.multipart.flat_map(lambda persisted: decode(dict(persisted)))
        return url_params(request)

    return HttpServerRequest().flat_map(read)


def schema_body_form_json[T, RD](
    schema: Codec[T, Any, RD, Any],
    *,
    reviver: Reviver | None = None,
    **options: Unpack[ParseOptions],
) -> Callable[[str], Effect[T, Any, RD | HttpServerRequest | Scope | FileSystem | Path]]:
    """A decoder of the JSON text in a form field (multipart or
    form-encoded) by ``schema``, parsed with ``reviver``."""
    from pyfect.http.multipart import schema_json

    from_multipart = schema_json(schema, reviver=reviver, **options)

    def field(name: str) -> Effect[T, Any, Any]:
        def read(request: ServerRequest) -> Effect[T, Any, Any]:
            if is_multipart(request):
                return request.multipart.map_error(
                    lambda cause: HttpServerError(RequestParseError(request, None, cause))
                ).flat_map(lambda persisted: from_multipart(persisted, name))
            return request.url_params_body.flat_map(
                lambda params: from_multipart(cast("Persisted", params.to_record()), name)
            )

        return HttpServerRequest().flat_map(read)

    return field


__all__ = [
    "BodyTooLargeError",
    "ClientRequest",
    "HttpServerError",
    "HttpServerRequest",
    "MaxBodySize",
    "ParsedSearchParams",
    "RequestProtocol",
    "SchemaError",
    "ServerRequest",
    "SourceRequest",
    "form_data_body",
    "from_client_request",
    "is_multipart",
    "read_limited",
    "remove_host",
    "schema_body_form",
    "schema_body_form_json",
    "schema_body_json",
    "schema_body_multipart",
    "schema_body_url_params",
    "schema_cookies",
    "schema_headers",
    "schema_search_params",
    "search_params_from_url",
    "to_client_request",
    "to_url",
    "to_url_result",
]
