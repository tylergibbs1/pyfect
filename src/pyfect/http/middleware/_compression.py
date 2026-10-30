"""Compressing responses the client accepts compressed (Effect's
``HttpMiddleware.compression``)."""
# pyright: reportPrivateUsage=false

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from pyfect._core import Effect, _WithFiber
from pyfect._fiber import Fiber
from pyfect.effect import succeed
from pyfect.http import body as _body
from pyfect.http._request_state import append_pre_response_handler_unsafe
from pyfect.http._vary import vary_with
from pyfect.http.middleware._types import AppMiddleware
from pyfect.http.platform import Compression, CompressionAlgorithm, HttpPlatform
from pyfect.http.server_error import HttpServerError
from pyfect.http.server_request import HttpServerRequest, ServerRequest
from pyfect.http.server_response import HttpServerResponse, parse_content_length

_DEFAULT_ALGORITHMS: tuple[CompressionAlgorithm, ...] = ("br", "gzip", "deflate")
_DEFAULT_LEVELS: dict[CompressionAlgorithm, int] = {"gzip": 6, "deflate": 6, "br": 4, "zstd": 3}
_NO_TRANSFORM = re.compile(r"(?:^|[\s,])no-transform(?:$|[\s,;])", re.IGNORECASE)
_ACCEPT_MEMBER = re.compile(
    r"^([a-z0-9!#$%&'*+.^_`|~-]+)(?:;q=(0(?:\.[0-9]{0,3})?|1(?:\.0{0,3})?))?$"
)
_COMPRESSIBLE = frozenset(
    {
        "application/json",
        "application/javascript",
        "application/xml",
        "image/svg+xml",
        "application/wasm",
    }
)


def default_compressible(content_type: str) -> bool:
    """Text, JSON, JavaScript, XML, SVG and WebAssembly."""
    kind = content_type.split(";", 1)[0].strip().lower()
    return kind.startswith("text/") or kind in _COMPRESSIBLE or kind.endswith(("+json", "+xml"))


def parse_accept_encoding(header: str) -> dict[str, float] | None:
    """Each coding's quality; ``None`` for an empty or malformed header."""
    trimmed = header.strip()
    if not trimmed:
        return None
    accepted: dict[str, float] = {}
    for part in trimmed.split(","):
        member = ";".join(piece.strip(" \t") for piece in part.strip().lower().split(";"))
        match = _ACCEPT_MEMBER.match(member)
        if match is None:
            return None
        quality = match.group(2)
        accepted[match.group(1)] = 1.0 if quality is None else float(quality)
    return accepted


def negotiate(
    header: str | None,
    preferred: Sequence[CompressionAlgorithm],
    supported: frozenset[CompressionAlgorithm],
) -> CompressionAlgorithm | None:
    """The first of ``preferred`` the platform supports and the client
    accepts (its q-values decide acceptability only)."""
    if header is None:
        return None
    accepted = parse_accept_encoding(header)
    if accepted is None:
        return None
    for algorithm in preferred:
        if algorithm not in supported:
            continue
        quality = accepted.get(algorithm, accepted.get("*"))
        if quality is not None and quality > 0:
            return algorithm
    return None


def _with_vary(response: HttpServerResponse) -> HttpServerResponse:
    return response.set_header("vary", vary_with(response.headers, "Accept-Encoding"))


def _sent_as_is(
    response: HttpServerResponse, compressible: Callable[[str], bool]
) -> HttpServerResponse | None:
    """What to send when ``response`` is not to be compressed (and does not
    vary by encoding): bodyless or partial, already encoded (an
    ``identity`` opt-out is removed), ``no-transform`` or not
    compressible."""
    if response.status < 200 or response.status in (204, 206, 304):
        return response
    encoding = response.headers.get("content-encoding")
    if encoding is not None:
        identity = encoding.strip().lower() == "identity"
        return response.remove_header("content-encoding") if identity else response
    body = response.body
    cache_control = response.headers.get("cache-control", "")
    content_type = response.headers.get("content-type", body.content_type)
    skipped = (
        isinstance(body, _body.Empty | _body.FormData)
        or _NO_TRANSFORM.search(cache_control) is not None
        or content_type is None
        or not compressible(content_type)
    )
    return response if skipped else None


def compression(
    *,
    algorithms: Sequence[CompressionAlgorithm] = _DEFAULT_ALGORITHMS,
    min_size: int = 1024,
    compressible: Callable[[str], bool] = default_compressible,
    levels: Mapping[CompressionAlgorithm, int] | None = None,
) -> AppMiddleware[HttpServerRequest | HttpPlatform]:
    """Middleware compressing compressible responses of at least
    ``min_size`` bytes with the first of ``algorithms`` the client accepts
    and ``HttpPlatform`` supports. Responses that are bodyless, partial,
    already encoded or ``no-transform`` are sent as they are; the others
    vary by ``Accept-Encoding``."""
    level_of = {**_DEFAULT_LEVELS, **(levels or {})}

    def transform(
        platform: Compression, accept: str | None, response: HttpServerResponse
    ) -> Effect[HttpServerResponse]:
        unchanged = _sent_as_is(response, compressible)
        if unchanged is not None:
            return succeed(unchanged)
        algorithm = negotiate(accept, algorithms, platform.algorithms)
        length = response.body.content_length
        if length is None:
            length = parse_content_length(response.headers.get("content-length"))
        if algorithm is None or (length is not None and length < min_size):
            return succeed(_with_vary(response))
        return platform.compress_response(response, algorithm, level_of.get(algorithm))

    def middleware[E, R](
        app: Effect[HttpServerResponse, E, R],
    ) -> Effect[HttpServerResponse, E, R | HttpServerRequest | HttpPlatform]:
        def body(fiber: Fiber[Any, Any]) -> Effect[HttpServerResponse, E, R]:
            platform = fiber._context.get_unsafe(HttpPlatform).compression

            def pre_response(
                request: ServerRequest, response: HttpServerResponse
            ) -> Effect[HttpServerResponse, HttpServerError]:
                return transform(platform, request.headers.get("accept-encoding"), response)

            append_pre_response_handler_unsafe(fiber._context, pre_response)
            return app

        return _WithFiber(body)

    return middleware
