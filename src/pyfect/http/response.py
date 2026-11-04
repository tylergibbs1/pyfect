"""HTTP responses (Effect's ``HttpClientResponse``).

A response has its request, status, headers and cookies at once; the body
is read on demand, as bytes (``bytes_``), text, JSON, form parameters or a
stream. Reading it as a whole once caches it, so ``text`` then ``json``
read the network once::

    todo = yield from response.schema_body_json(Todo)(res)

``make`` builds a response, for tests and for clients that are not backed
by a network.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from functools import cached_property
from typing import Literal, Unpack, cast, final

from pyfect._cached import memoize
from pyfect._digits import parse_digits
from pyfect._effect_args import require_effect
from pyfect._js import text_encode
from pyfect._json_text import PARSE_ERRORS, Json, parse
from pyfect.byte_size import ByteSize
from pyfect.effect import Effect, fail, succeed, suspend, sync
from pyfect.http import url as _url
from pyfect.http.cookies import Cookies, from_set_cookie
from pyfect.http.error import DecodeError, EmptyBodyError, HttpClientError, StatusCodeError
from pyfect.http.headers import Headers
from pyfect.http.headers import Input as HeadersInput
from pyfect.http.headers import from_input as headers_from_input
from pyfect.http.incoming_message import (
    Reviver,
    schema_body_json,
    schema_body_url_params,
    schema_headers,
)
from pyfect.http.request import HttpClientRequest
from pyfect.http.url_params import UrlParams
from pyfect.http.url_params import parse as parse_url_params
from pyfect.schema import (
    Codec,
    SchemaError,
    Unknown,
    decode_effect,
    decode_unknown_effect,
    to_codec_json,
)
from pyfect.schema._options import ParseOptions
from pyfect.stream import Stream, from_effect
from pyfect.stream import fail as fail_stream
from pyfect.stream import succeed as succeed_stream
from pyfect.stream import suspend as suspend_stream

type ResponseBody = bytes | Stream[bytes, object] | None
"""A response body: all of it, a stream of it (read once), or none (a
``HEAD`` response, a 204)."""


def _set_cookie_values(headers: HeadersInput | None) -> tuple[str, ...]:
    if headers is None:
        return ()
    if isinstance(headers, Headers):
        value = headers.get("set-cookie")
        return () if value is None else (value,)
    if isinstance(headers, Mapping):
        record = cast("Mapping[str, str | Sequence[str] | None]", headers)
        found = [v for k, v in record.items() if k.lower() == "set-cookie" and v is not None]
        return tuple(v for value in found for v in ((value,) if isinstance(value, str) else value))
    return tuple(v for k, v in headers if k.lower() == "set-cookie")


class HttpClientResponse:
    """A response to ``request``. Body reads fail with an
    ``HttpClientError`` whose reason is a ``DecodeError`` (or an
    ``EmptyBodyError`` for a stream of no body)."""

    def __init__(
        self,
        request: HttpClientRequest,
        status: int,
        headers: Headers,
        body: ResponseBody,
        *,
        url: str | None = None,
        set_cookie: Sequence[str] = (),
        remote_address: str | None = None,
    ) -> None:
        self.request = request
        self.status = status
        self.headers = headers
        self._body = body
        self._url = url
        self._set_cookie = tuple(set_cookie)
        self._remote_address = remote_address
        self._bytes: Effect[bytes, HttpClientError] | None = None

    def __repr__(self) -> str:
        return f"HttpClientResponse({self.status}, {self.request!r})"

    def to_json(self) -> dict[str, object]:
        return {
            "_id": "HttpClientResponse",
            "request": self.request.to_json(),
            "status": self.status,
            "headers": self.headers.to_json(),
            "remote_address": self.remote_address,
        }

    def _error(self, cause: object, description: str | None = None) -> HttpClientError:
        return HttpClientError(DecodeError(self.request, self, cause, description))

    def _read(self) -> Effect[bytes, HttpClientError]:
        body = self._body
        if body is None:
            return succeed(b"")
        if isinstance(body, bytes):
            return succeed(body)
        return body.map_error(self._error).run_collect().map(b"".join)

    @property
    def url(self) -> str:
        """Where the response came from, without a fragment."""
        if self._url:
            return self._url.split("#")[0]
        url = self.request.to_url()
        return "" if url is None else _url.href(url._replace(fragment=""))

    @property
    def remote_address(self) -> str | None:
        return self._remote_address

    @cached_property
    def cookies(self) -> Cookies:
        return from_set_cookie(self._set_cookie)

    @property
    def bytes_(self) -> Effect[bytes, HttpClientError]:
        """The whole body, read once (Effect's ``arrayBuffer``)."""
        # Made on first use: it refers back to the response, and a response in
        # a reference cycle outlives its last reference, so dropping it unread
        # would not abort its request until the cycle collector runs.
        if self._bytes is None:
            self._bytes = memoize(suspend(self._read))
        return self._bytes

    @property
    def text(self) -> Effect[str, HttpClientError]:
        """The body as UTF-8 (invalid bytes become U+FFFD; a leading BOM is
        dropped)."""
        return self.bytes_.map(lambda data: data.decode("utf-8-sig", "replace"))

    @property
    def json(self) -> Effect[Json, HttpClientError]:
        """The body parsed as JSON; an empty body is ``None``."""

        def decode(text: str) -> Effect[Json, HttpClientError]:
            if text == "":
                return succeed(None)
            try:
                return succeed(parse(text))
            except PARSE_ERRORS as cause:
                return fail(self._error(cause))

        return self.text.flat_map(decode)

    @property
    def url_params_body(self) -> Effect[UrlParams, HttpClientError]:
        return self.text.map(parse_url_params)

    @property
    def stream(self) -> Stream[bytes, HttpClientError]:
        """The body as it arrives. No body fails with an
        ``EmptyBodyError``."""
        body = self._body
        if body is None:
            return fail_stream(
                HttpClientError(
                    EmptyBodyError(
                        self.request, self, None, "can not create stream from empty body"
                    )
                )
            )
        if isinstance(body, bytes):
            return succeed_stream(body)
        return body.map_error(self._error)


@final
class _InterruptibleResponse(HttpClientResponse):
    """A response whose body reads run ``abort`` when interrupted, and whose
    stream runs it when it ends (Effect's ``InterruptibleResponse``)."""

    def __init__(
        self, original: HttpClientResponse, abort: Callable[[], None], release: Callable[[], None]
    ) -> None:
        self.original = original
        self._abort = abort
        self._release = release
        self.request = original.request
        self.status = original.status
        self.headers = original.headers

    def __repr__(self) -> str:
        return repr(self.original)

    def to_json(self) -> dict[str, object]:
        return self.original.to_json()

    def _interruptible[A](
        self, read: Callable[[HttpClientResponse], Effect[A, HttpClientError]]
    ) -> Effect[A, HttpClientError]:
        """``read`` of the original, made only once it runs (see
        ``HttpClientResponse.bytes_``)."""

        def run() -> Effect[A, HttpClientError]:
            self._release()
            return read(self.original).on_interrupt(sync(self._abort))

        return suspend(run)

    @property
    def url(self) -> str:
        return self.original.url

    @property
    def remote_address(self) -> str | None:
        return self.original.remote_address

    @cached_property
    def cookies(self) -> Cookies:
        return self.original.cookies

    @property
    def bytes_(self) -> Effect[bytes, HttpClientError]:
        return self._interruptible(lambda original: original.bytes_)

    @property
    def text(self) -> Effect[str, HttpClientError]:
        return self._interruptible(lambda original: original.text)

    @property
    def json(self) -> Effect[Json, HttpClientError]:
        return self._interruptible(lambda original: original.json)

    @property
    def url_params_body(self) -> Effect[UrlParams, HttpClientError]:
        return self._interruptible(lambda original: original.url_params_body)

    @property
    def stream(self) -> Stream[bytes, HttpClientError]:
        def make() -> Stream[bytes, HttpClientError]:
            self._release()
            return self.original.stream.ensuring(sync(self._abort))

        return suspend_stream(make)


class ResponseTooLargeError(Exception):
    """The cause of the ``DecodeError`` of a body read past its limit."""

    def __init__(self, max_bytes: int) -> None:
        super().__init__(f"Response body exceeds {max_bytes} bytes")
        self.max_bytes = max_bytes


def is_too_large(error: HttpClientError) -> bool:
    """Whether ``error`` is a ``with_body_limit`` read stopping at its limit."""
    return isinstance(error.reason, DecodeError) and isinstance(
        error.reason.cause, ResponseTooLargeError
    )


@final
class _LimitedResponse(HttpClientResponse):
    """``original`` with a body that fails once it passes ``max_bytes``."""

    def __init__(self, original: HttpClientResponse, max_bytes: int) -> None:
        super().__init__(original.request, original.status, original.headers, None)
        self.original = original
        self._max_bytes = max_bytes

    @property
    def stream(self) -> Stream[bytes, HttpClientError]:
        # Made on each use, not kept: a body referring back to the response
        # would put it in a reference cycle (see ``HttpClientResponse.bytes_``).
        max_bytes = self._max_bytes
        return suspend_stream(lambda: self._capped(max_bytes)).map_error(self._error)

    def _read(self) -> Effect[bytes, HttpClientError]:
        return self.stream.run_collect().map(b"".join)

    def _too_large(self, max_bytes: int) -> HttpClientError:
        cause = ResponseTooLargeError(max_bytes)
        return HttpClientError(DecodeError(self.request, self, cause, str(cause)))

    def _capped(self, max_bytes: int) -> Stream[bytes, object]:
        declared = parse_digits(self.headers.get("content-length") or "")
        if declared is not None and declared > max_bytes:
            return fail_stream(self._too_large(max_bytes))
        seen = 0

        def count(chunk: bytes) -> Effect[bytes, HttpClientError]:
            nonlocal seen
            seen += len(chunk)
            return fail(self._too_large(max_bytes)) if seen > max_bytes else succeed(chunk)

        def keep_empty(error: HttpClientError) -> Stream[bytes, HttpClientError]:
            if isinstance(error.reason, EmptyBodyError):
                return succeed_stream(b"")
            return fail_stream(error)

        return self.original.stream.catch_all(keep_empty).map_effect(count)

    def _error(self, cause: object, description: str | None = None) -> HttpClientError:
        if isinstance(cause, HttpClientError):
            return cause
        return super()._error(cause, description)

    def __repr__(self) -> str:
        return repr(self.original)

    def to_json(self) -> dict[str, object]:
        return self.original.to_json()

    @property
    def url(self) -> str:
        return self.original.url

    @property
    def remote_address(self) -> str | None:
        return self.original.remote_address

    @cached_property
    def cookies(self) -> Cookies:
        return self.original.cookies


def with_body_limit(response: HttpClientResponse, max_bytes: ByteSize) -> HttpClientResponse:
    """``response`` with a body that is read only until it passes
    ``max_bytes``: then the read (``bytes_``, ``text``, ``json``,
    ``stream``) stops and fails (``is_too_large``), and a declared
    ``content-length`` over the limit fails before anything is read. Use it
    for a server you do not control; ``response`` itself holds whatever
    the server sends."""
    return _LimitedResponse(response, max_bytes)


def make(
    request: HttpClientRequest,
    body: ResponseBody | str = None,
    *,
    status: int = 200,
    headers: HeadersInput | None = None,
    url: str | None = None,
) -> HttpClientResponse:
    """A response to ``request``. A ``str`` body is sent as UTF-8; repeated
    ``set-cookie`` headers are kept apart when given as pairs or a list."""
    data = text_encode(body) if isinstance(body, str) else body
    return HttpClientResponse(
        request,
        status,
        headers_from_input(headers),
        data,
        url=url,
        set_cookie=_set_cookie_values(headers),
    )


def stream[E, R](effect: Effect[HttpClientResponse, E, R]) -> Stream[bytes, HttpClientError | E, R]:
    """The body stream of the response ``effect`` gives."""
    require_effect(effect, "effect")
    return from_effect(effect).flat_map(lambda response: response.stream)


type StatusRange = Literal["2xx", "3xx", "4xx", "5xx"]


def match_status[T](
    response: HttpClientResponse,
    cases: Mapping[int | StatusRange, Callable[[HttpClientResponse], T]],
    or_else: Callable[[HttpClientResponse], T],
) -> T:
    """The case of the exact status, else of its range (``"2xx"``, ...),
    else ``or_else``."""
    status = response.status
    exact = cases.get(status)
    if exact is not None:
        return exact(response)
    for low, name in ((200, "2xx"), (300, "3xx"), (400, "4xx"), (500, "5xx")):
        handler = cases.get(cast("StatusRange", name))
        if low <= status < low + 100 and handler is not None:
            return handler(response)
    return or_else(response)


def filter_status(
    f: Callable[[int], bool],
) -> Callable[[HttpClientResponse], Effect[HttpClientResponse, HttpClientError]]:
    """Fail with a ``StatusCodeError`` unless ``f(status)``."""

    def check(response: HttpClientResponse) -> Effect[HttpClientResponse, HttpClientError]:
        def run() -> Effect[HttpClientResponse, HttpClientError]:
            if f(response.status):
                return succeed(response)
            return fail(
                HttpClientError(
                    StatusCodeError(response.request, response, None, "invalid status code")
                )
            )

        return suspend(run)

    return check


def filter_status_ok(response: HttpClientResponse) -> Effect[HttpClientResponse, HttpClientError]:
    """Fail with a ``StatusCodeError`` unless the status is 2xx."""
    if 200 <= response.status < 300:
        return succeed(response)
    return fail(
        HttpClientError(StatusCodeError(response.request, response, None, "non 2xx status code"))
    )


def schema_json[T, RD](
    schema: Codec[T, object, RD, object],
    *,
    reviver: Reviver | None = None,
    **options: Unpack[ParseOptions],
) -> Callable[[HttpClientResponse], Effect[T, HttpClientError | SchemaError, RD]]:
    """A decoder of ``{"status", "headers", "body"}`` (the JSON body) by
    ``schema``."""
    decode = decode_unknown_effect(to_codec_json(schema), **options)
    decode_body = schema_body_json(Unknown, reviver=reviver, **options)

    def run(response: HttpClientResponse) -> Effect[T, HttpClientError | SchemaError, RD]:
        return decode_body(response).flat_map(
            lambda body: decode(
                {"status": response.status, "headers": dict(response.headers), "body": body}
            )
        )

    return run


def schema_no_body[T, RD](
    schema: Codec[T, object, RD, object], **options: Unpack[ParseOptions]
) -> Callable[[HttpClientResponse], Effect[T, SchemaError, RD]]:
    """A decoder of ``{"status", "headers"}`` by ``schema``."""
    decode = decode_effect(schema, **options)
    return lambda response: decode({"status": response.status, "headers": dict(response.headers)})


__all__ = [
    "HttpClientError",
    "HttpClientResponse",
    "ResponseBody",
    "ResponseTooLargeError",
    "StatusRange",
    "filter_status",
    "filter_status_ok",
    "is_too_large",
    "make",
    "match_status",
    "schema_body_json",
    "schema_body_url_params",
    "schema_headers",
    "schema_json",
    "schema_no_body",
    "stream",
    "with_body_limit",
]
