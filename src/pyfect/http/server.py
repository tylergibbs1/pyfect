"""HTTP servers (Effect's ``HttpServer``): the ``HttpServer`` service a
backend provides (``live_server.layer``), serving an app as a
layer, and the test client.

::

    app = router.to_http_effect(...)
    main = server.serve(app).pipe(layer.provide(live_server.layer(port=8080)))
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Never, overload

from pyfect._core import Effect
from pyfect._effect_args import require_effect
from pyfect.context import Tag
from pyfect.effect import die, fn
from pyfect.file_system import FileSystem, layer_noop
from pyfect.http.client import HttpClient, HttpClientService
from pyfect.http.etag import Generator
from pyfect.http.etag import layer_weak as etag_layer_weak
from pyfect.http.platform import HttpPlatform
from pyfect.http.platform import layer as platform_layer
from pyfect.http.server_request import HttpServerRequest
from pyfect.http.server_response import HttpServerResponse
from pyfect.layer import Layer, effect_discard, merge, provide_merge
from pyfect.layer import effect as layer_effect
from pyfect.logger import log
from pyfect.net.net_address import (
    SocketAddress,
    UnixPathAddress,
    format_ip,
    format_url_unsafe,
    ipv4_loopback,
    is_unspecified,
    to_url,
)
from pyfect.path import Path
from pyfect.path import layer as path_layer
from pyfect.scope import Scope

type HttpApp = Effect[HttpServerResponse, Any, Any]
type Middleware = Callable[[HttpApp], HttpApp]


@dataclass(frozen=True, slots=True)
class HttpServerService:
    """``serve(app, middleware)`` handles requests with ``app`` until the
    scope closes; ``address`` is where the server listens."""

    serve: Callable[[HttpApp, Middleware | None], Effect[None, Never, Scope]]
    address: SocketAddress


class HttpServer(Tag[HttpServerService], key="effect/http/HttpServer"):
    """The running server."""


def make(
    *,
    serve: Callable[[HttpApp, Middleware | None], Effect[None, Never, Scope]],
    address: SocketAddress,
) -> HttpServerService:
    return HttpServerService(serve, address)


type _Served = HttpServerRequest | Scope
"""What the server provides an app."""

type _AppIn[E, R] = Effect[HttpServerResponse, E, R | _Served]


@overload
def serve_effect[E](app: _AppIn[E, Never], /) -> Effect[None, Never, Scope | HttpServer]: ...
@overload
def serve_effect[E, R](app: _AppIn[E, R], /) -> Effect[None, Never, Scope | HttpServer | R]: ...
@overload
def serve_effect[E, EM](
    app: _AppIn[E, Never], middleware: Callable[[_AppIn[E, Never]], _AppIn[EM, Never]], /
) -> Effect[None, Never, Scope | HttpServer]: ...
@overload
def serve_effect[E, EM, RM](
    app: _AppIn[E, Never], middleware: Callable[[_AppIn[E, Never]], _AppIn[EM, RM]], /
) -> Effect[None, Never, Scope | HttpServer | RM]: ...
@overload
def serve_effect[E, R, EM, RM](
    app: _AppIn[E, R], middleware: Callable[[_AppIn[E, R]], _AppIn[EM, RM]], /
) -> Effect[None, Never, Scope | HttpServer | RM]: ...
def serve_effect(
    app: Effect[HttpServerResponse, Any, Any], middleware: Middleware | None = None, /
) -> Effect[None, Never, Any]:
    """Serve ``app`` (through ``middleware``) until the scope closes."""
    require_effect(app, "app")
    return HttpServer().flat_map(lambda server: server.serve(app, middleware))


@overload
def serve[E](app: _AppIn[E, Never], /) -> Layer[Never, Never, HttpServer]: ...
@overload
def serve[E, R](app: _AppIn[E, R], /) -> Layer[Never, Never, HttpServer | R]: ...
@overload
def serve[E, EM](
    app: _AppIn[E, Never], middleware: Callable[[_AppIn[E, Never]], _AppIn[EM, Never]], /
) -> Layer[Never, Never, HttpServer]: ...
@overload
def serve[E, EM, RM](
    app: _AppIn[E, Never], middleware: Callable[[_AppIn[E, Never]], _AppIn[EM, RM]], /
) -> Layer[Never, Never, HttpServer | RM]: ...
@overload
def serve[E, R, EM, RM](
    app: _AppIn[E, R], middleware: Callable[[_AppIn[E, R]], _AppIn[EM, RM]], /
) -> Layer[Never, Never, HttpServer | RM]: ...
def serve(
    app: Effect[HttpServerResponse, Any, Any], middleware: Middleware | None = None, /
) -> Layer[Never, Never, Any]:
    """A layer serving ``app`` (through ``middleware``) while it is in
    use."""
    require_effect(app, "app")
    return effect_discard(serve_effect(app, middleware) if middleware else serve_effect(app))


def format_address(address: SocketAddress) -> str:
    """``http://host:port``, or ``unix://path``."""
    return format_url_unsafe(address)


def address_formatted_with[A, E, R](
    f: Callable[[str], Effect[A, E, R]],
) -> Effect[A, E, HttpServer | R]:
    return HttpServer().flat_map(lambda server: f(format_address(server.address)))


log_address: Effect[None, Never, HttpServer] = address_formatted_with(
    lambda address: log(f"Listening on {address}")
)


def with_log_address[A, E, R](layer: Layer[A, E, R]) -> Layer[A, E, R | HttpServer]:
    """``layer``, logging the server's address once built."""
    return effect_discard(log_address).pipe(provide_merge(layer))


@fn
def _make_test_client():
    server = yield from HttpServer()
    client = yield from HttpClient()
    address = server.address
    if isinstance(address, UnixPathAddress):
        return (
            yield from die(
                RuntimeError("HttpServer.layerTestClient: UnixPathAddress not supported")
            )
        )
    url = to_url(address).get_or_raise()
    origin = f"{url.scheme}://{url.netloc}"
    if is_unspecified(address.address):
        port = f":{url.port}" if url.port is not None else ""
        origin = f"{url.scheme}://{format_ip(ipv4_loopback)}{port}"
    prefixed: HttpClientService[Any] = client.map_request(
        lambda request: request.prepend_url(origin)
    )
    return prefixed


make_test_client: Effect[HttpClientService[Any], Never, HttpServer | HttpClient] = (
    _make_test_client()
)
"""The ``HttpClient`` with the server's origin prepended to each URL (the
loopback address for a server on an unspecified one)."""

layer_test_client: Layer[HttpClient, Never, HttpServer | HttpClient] = layer_effect(
    HttpClient, make_test_client
)

layer_services: Layer[Path | HttpPlatform | FileSystem | Generator] = merge(
    platform_layer, path_layer, etag_layer_weak
).pipe(provide_merge(layer_noop()))
"""What servers need: ``HttpPlatform``, ``Path``, weak ETags, and a no-op
``FileSystem``."""

__all__ = [
    "HttpServer",
    "HttpServerService",
    "address_formatted_with",
    "format_address",
    "layer_services",
    "layer_test_client",
    "log_address",
    "make",
    "make_test_client",
    "serve",
    "serve_effect",
    "with_log_address",
]
