"""Decoding compressed request bodies (Effect's
``HttpMiddleware.decompression`` and its ``DecompressedRequest``)."""
# pyright: reportPrivateUsage=false

from __future__ import annotations

import zlib
from collections.abc import Callable
from functools import cached_property
from typing import Any, Literal

from pyfect._cached import memoize
from pyfect._core import Effect, _WithFiber
from pyfect._fiber import Fiber
from pyfect._primitives import _Locally
from pyfect.byte_size import Input as ByteSizeInput
from pyfect.byte_size import from_input_unsafe, mebibytes
from pyfect.effect import fail, succeed
from pyfect.http.headers import Headers
from pyfect.http.headers import Input as HeadersInput
from pyfect.http.incoming_message import MaxBodySize
from pyfect.http.method import HttpMethod, has_body
from pyfect.http.middleware._types import AppMiddleware
from pyfect.http.server_error import HttpServerError, RequestParseError, request_parse_error
from pyfect.http.server_request import HttpServerRequest, RequestProtocol, ServerRequest
from pyfect.http.server_response import HttpServerResponse, empty
from pyfect.socket import SocketService
from pyfect.stream import Stream, from_effect, unwrap

type Coding = Literal["gzip", "deflate"]

_DEFAULT_MAX = mebibytes(10)
_WBITS: dict[Coding, int] = {"gzip": 31, "deflate": 15}
MAX_CODINGS = 2
"""How many codings may be stacked on one body."""
_PIECE = 64 * 1024


def parse_content_encoding(header: str) -> tuple[Coding, ...] | None:
    """The codings of a ``content-encoding`` header in the order applied
    (``identity`` dropped); ``None`` when one is not supported or more than
    ``MAX_CODINGS`` are stacked."""
    codings: list[Coding] = []
    for member in header.split(","):
        coding = member.strip().lower()
        if coding in ("", "identity"):
            continue
        if coding not in ("gzip", "deflate"):
            return None
        codings.append("gzip" if coding == "gzip" else "deflate")
    return tuple(codings) if len(codings) <= MAX_CODINGS else None


class _TooLarge(Exception):
    pass


class _Decoders:
    """Stacked decoders that inflate at most ``_PIECE`` bytes per call, each
    coding's total output counted against ``limit``: a bomb fails before
    more than about ``limit`` bytes exist."""

    def __init__(self, codings: tuple[Coding, ...], limit: int) -> None:
        # The coding applied last is decoded first.
        self._decoders = [zlib.decompressobj(_WBITS[coding]) for coding in reversed(codings)]
        self._produced = [0] * len(self._decoders)
        self._limit = limit

    def feed(self, data: bytes) -> bytes:
        output: list[bytes] = []
        self._run(0, data, output)
        return b"".join(output)

    def finish(self) -> bytes | None:
        """The rest of the body; ``None`` when a coding is truncated."""
        output: list[bytes] = []
        for level, decoder in enumerate(self._decoders):
            self._emit(level, decoder.flush(), output)
            if not decoder.eof:
                return None
        return b"".join(output)

    def _run(self, level: int, data: bytes, output: list[bytes]) -> None:
        decoder = self._decoders[level]
        while True:
            piece = decoder.decompress(data, _PIECE)
            data = decoder.unconsumed_tail
            self._emit(level, piece, output)
            if not data and len(piece) < _PIECE:
                return

    def _emit(self, level: int, piece: bytes, output: list[bytes]) -> None:
        self._produced[level] += len(piece)
        if self._produced[level] > self._limit:
            raise _TooLarge
        if level + 1 < len(self._decoders):
            self._run(level + 1, piece, output)
        elif piece:
            output.append(piece)


class DecompressedRequest(ServerRequest):
    """``inner`` with its body decoded, without its ``content-encoding``
    and ``content-length``. The decoded body may be at most
    ``max_decompressed_size`` (else ``MaxBodySize``, else 10 MiB) bytes."""

    def __init__(
        self, inner: ServerRequest, codings: tuple[Coding, ...], max_decompressed_size: int | None
    ) -> None:
        super().__init__(None, inner.headers.remove_many(("content-encoding", "content-length")))
        self.inner = inner
        self.codings = codings
        self.max_decompressed_size = max_decompressed_size

    @property
    def source(self) -> object:
        return self.inner.source

    @property
    def original_url(self) -> str:
        return self.inner.original_url

    @property
    def url(self) -> str:
        return self.inner.url

    @property
    def method(self) -> HttpMethod:
        return self.inner.method

    @property
    def remote_address(self) -> str | None:
        return self.inner.remote_address

    @property
    def peer_address(self) -> str | None:
        return self.inner.peer_address

    @property
    def protocol(self) -> RequestProtocol | None:
        return self.inner.protocol

    def _source_headers(self) -> Headers:
        return self.inner.headers

    def _copy(self) -> ServerRequest:
        return DecompressedRequest(self.inner, self.codings, self.max_decompressed_size)

    def modify(
        self,
        *,
        url: str | None = None,
        headers: Headers | None = None,
        remote_address: Any = ...,
        peer_address: str | None = None,
        protocol: RequestProtocol | None = None,
    ) -> ServerRequest:
        options: dict[str, Any] = {
            "url": url,
            "headers": headers,
            "peer_address": peer_address,
            "protocol": protocol,
        }
        if remote_address is not ...:
            options["remote_address"] = remote_address
        return DecompressedRequest(
            self.inner.modify(**options), self.codings, self.max_decompressed_size
        )

    def upgrade_with(
        self, *, headers: HeadersInput | None = None
    ) -> Effect[SocketService, HttpServerError]:
        return self.inner.upgrade_with(headers=headers)

    def _error(
        self,
        cause: object,
        description: str | None = None,
        kind: Literal["Parse", "BodyTooLarge"] = "Parse",
    ) -> HttpServerError:
        return request_parse_error(self, description, cause, kind)

    @property
    def stream(self) -> Stream[bytes, HttpServerError]:
        """Read from the inner body only once pulled."""

        def make(fiber: Fiber[Any, Any]) -> Effect[Stream[bytes, HttpServerError]]:
            limit = self.max_decompressed_size
            if limit is None:
                limit = fiber.get_ref(MaxBodySize)
            if limit is None:
                limit = _DEFAULT_MAX
            decoders = _Decoders(self.codings, limit)

            def decode(step: Callable[[], bytes | None]) -> Effect[bytes, HttpServerError]:
                try:
                    data = step()
                except zlib.error as cause:
                    return fail(self._error(cause))
                except _TooLarge:
                    description = f"Decompressed request body exceeds {limit} bytes"
                    return fail(self._error(None, description, "BodyTooLarge"))
                if data is None:
                    return fail(self._error(None, "Truncated compressed body"))
                return succeed(data)

            def feed(chunk: bytes) -> Effect[bytes, HttpServerError]:
                return decode(lambda: decoders.feed(chunk))

            def finish() -> Effect[bytes, HttpServerError]:
                return decode(decoders.finish)

            decoded = self.inner.stream.map_effect(feed).concat(
                from_effect(_WithFiber(lambda _: finish()))
            )
            return succeed(decoded.filter(lambda chunk: len(chunk) > 0))

        return unwrap(_WithFiber(make))

    @cached_property
    def _bytes(self) -> Effect[bytes, HttpServerError]:
        return memoize(self.stream.run_collect().map(b"".join))

    @property
    def bytes_(self) -> Effect[bytes, HttpServerError]:
        return self._bytes

    @property
    def json(self) -> Effect[Any, HttpServerError]:
        return self.text.flat_map(
            lambda text: succeed(None) if text == "" else self._parse_json(text)
        )

    @property
    def multipart_stream(self) -> Stream[Any, Any]:
        from pyfect.http.multipart import MultipartError, make_channel

        def convert(cause: HttpServerError) -> MultipartError:
            # Failures of this request come from the client's data; those of
            # the inner request are transport errors.
            reason = cause.reason
            if isinstance(reason, RequestParseError) and reason.request is self:
                return MultipartError.from_reason(reason.kind, cause)
            return MultipartError.from_reason("InternalError", cause)

        return self.stream.map_error(convert).pipe_through_channel(make_channel(self.headers))


def decompression(
    *, max_decompressed_size: ByteSizeInput | None = None
) -> AppMiddleware[HttpServerRequest]:
    """Middleware decoding gzip and deflate request bodies; an unsupported
    coding is answered with 415 before the app runs."""
    limit = None if max_decompressed_size is None else from_input_unsafe(max_decompressed_size)

    def middleware[E, R](
        app: Effect[HttpServerResponse, E, R],
    ) -> Effect[HttpServerResponse, E, R | HttpServerRequest]:
        def body(fiber: Fiber[Any, Any]) -> Effect[HttpServerResponse, E, R]:
            request = fiber._context.unsafe_get(HttpServerRequest)
            encoding = request.headers.get("content-encoding")
            if encoding is None or not has_body(request.method):
                return app
            codings = parse_content_encoding(encoding)
            if codings is None:
                return succeed(empty(status=415, headers={"accept-encoding": "gzip, deflate"}))
            if not codings:
                return app
            decompressed = DecompressedRequest(request, codings, limit)
            return _Locally(app, lambda ctx: ctx.add(HttpServerRequest, decompressed))

        return _WithFiber(body)

    return middleware
