"""An ``HttpServer`` on uvicorn (extra ``pyfect-dev[server]``; the counterpart
of Effect's ``NodeHttpServer.layer``)::

    main = server.serve(app).pipe(layer.provide(uvicorn_server.layer(port=8080)))

The socket is bound when the server is made, so ``address`` is known (port
0: any free port). uvicorn runs on the building fiber's asyncio loop under
``run_main`` / ``run_async``, else on a loop thread shared by such servers
and never stopped (a fiber a request forks into a longer-lived set runs on
it, and must still be able to finish once the server is gone); each
request runs on its own fiber on that loop, through ``pyfect.http.asgi``
(streamed bodies, client aborts, WebSocket upgrades). Requests that arrive
while no app is served get a 503. When the serving scope closes, uvicorn
stops accepting and gives requests in flight ``graceful_shutdown_timeout``;
then their fibers are interrupted and streamed bodies end where they are
(ASGI cannot abort a started response quietly, so it ends complete).
"""
# pyright: reportPrivateUsage=false

from __future__ import annotations

import collections.abc
import contextlib
from collections.abc import Mapping
from typing import Any, NotRequired, Unpack

from pyfect._extras import missing_extra

try:
    import uvicorn
except ImportError as error:  # pragma: no cover - depends on the environment
    raise missing_extra("pyfect.http.uvicorn_server", "server") from error

from pyfect._core import Effect
from pyfect.file_system import FileSystem
from pyfect.http._asgi_listener import Dispatch, ListenOptions, graceful, make_listener
from pyfect.http.client import HttpClient
from pyfect.http.etag import Generator
from pyfect.http.httpx_client import layer as httpx_layer
from pyfect.http.live_server import layer_services
from pyfect.http.live_server._listener import ABORT_GRACE_PERIOD
from pyfect.http.platform import HttpPlatform
from pyfect.http.server import HttpServer, HttpServerService, layer_test_client
from pyfect.layer import Layer, merge, provide_merge
from pyfect.layer import effect as layer_effect
from pyfect.path import Path
from pyfect.scope import Scope as ScopeTag
from pyfect.socket._web_socket import DEFAULT_MAX_MESSAGE_SIZE
from pyfect.socket.server import SocketServerError


class Options(ListenOptions):
    config: NotRequired[Mapping[str, Any]]
    """More ``uvicorn.Config`` arguments (``http``, ``ws``, ``ws_max_size``,
    ``proxy_headers``, ``timeout_keep_alive``, ``log_config``...); the app,
    socket and lifespan are the server's."""


class _Server(uvicorn.Server):
    """uvicorn without its signal handlers: the program owns SIGINT and
    SIGTERM (``run_main`` interrupts it, which closes the server's scope and
    runs ``_Running.shut_down``). uvicorn's would shut it down on its own,
    cancelling streamed responses at its timeout."""

    @contextlib.contextmanager
    def capture_signals(self) -> collections.abc.Generator[None]:
        yield


def _uvicorn(dispatch: Dispatch, options: Options) -> uvicorn.Server:
    config: dict[str, Any] = {
        "log_config": None,
        "server_header": False,
        "ws_max_size": DEFAULT_MAX_MESSAGE_SIZE,
        **options.get("config", {}),
    }
    # uvicorn's own timeout only backs up ``_Running.shut_down``, which ends
    # the requests first: its cancel is logged with a traceback.
    backstop = graceful(options) + ABORT_GRACE_PERIOD
    config.update(app=dispatch, lifespan="off", timeout_graceful_shutdown=backstop)
    return _Server(uvicorn.Config(**config))


def make(**options: Unpack[Options]) -> Effect[HttpServerService, SocketServerError, ScopeTag]:
    """An ``HttpServer`` on uvicorn, listening on ``host:port`` until the
    scope closes."""
    return make_listener(options, lambda dispatch: _uvicorn(dispatch, options))


def layer_server(**options: Unpack[Options]) -> Layer[HttpServer, SocketServerError]:
    return layer_effect(HttpServer, make(**options))


def layer(
    **options: Unpack[Options],
) -> Layer[HttpServer | Path | HttpPlatform | FileSystem | Generator, SocketServerError]:
    """The server and the services its apps use (``live_server.layer_services``)."""
    return merge(layer_server(**options), layer_services)


def layer_test(
    **options: Unpack[Options],
) -> Layer[
    HttpServer | Path | HttpPlatform | FileSystem | Generator | HttpClient, SocketServerError
]:
    """A server on a free loopback port, its services, and an ``HttpClient``
    (httpx) sending to it (Effect's ``NodeHttpServer.layerTest``)."""
    server = layer(**{"host": "127.0.0.1", **options})
    return layer_test_client.pipe(provide_merge(httpx_layer)).pipe(provide_merge(server))


__all__ = [
    "Options",
    "SocketServerError",
    "layer",
    "layer_server",
    "layer_test",
    "make",
]
