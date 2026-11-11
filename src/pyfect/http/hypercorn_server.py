"""An ``HttpServer`` on hypercorn (extra ``pyfect-dev[http2]``), which speaks
HTTP/2 as Effect's ``NodeHttpServer`` does when given ``node:http2``'s server:
cleartext (``h2c``) by default, with ALPN when ``config`` gives ``certfile`` and
``keyfile``::

    main = server.serve(app).pipe(layer.provide(hypercorn_server.layer(port=8080)))

Otherwise as ``uvicorn_server``, on the same request handling and shutdown.
"""

from __future__ import annotations

import asyncio
import socket
import ssl
from collections.abc import Mapping
from typing import Any, NotRequired, Unpack, cast

from pyfect._extras import missing_extra

try:
    from hypercorn.app_wrappers import ASGIWrapper
    from hypercorn.asyncio.run import worker_serve  # pyright: ignore[reportUnknownVariableType]
    from hypercorn.config import Config, Sockets
    from hypercorn.logging import Logger
except ImportError as error:  # pragma: no cover - depends on the environment
    raise missing_extra("pyfect.http.hypercorn_server", "http2", error) from error

from pyfect._core import Effect
from pyfect.file_system import FileSystem
from pyfect.http._asgi_listener import (
    Dispatch,
    ListenOptions,
    engine_backstop_seconds,
    make_listener,
)
from pyfect.http._tls_close import close_without_waiting
from pyfect.http.client import HttpClient
from pyfect.http.etag import Generator
from pyfect.http.httpx_client import layer as httpx_layer
from pyfect.http.live_server import layer_services
from pyfect.http.platform import HttpPlatform
from pyfect.http.server import HttpServer, HttpServerService, layer_test_client
from pyfect.layer import Layer, merge, provide_merge
from pyfect.layer import effect as layer_effect
from pyfect.path import Path
from pyfect.scope import Scope as ScopeTag
from pyfect.socket.server import SocketServerError


class Options(ListenOptions):
    config: NotRequired[Mapping[str, Any]]
    """More ``hypercorn.Config`` attributes (``certfile``, ``keyfile``,
    ``alpn_protocols``, ``h2_max_concurrent_streams``...)."""


class _EngineLogger(Logger):
    """hypercorn's logger without its "Running on" lines: the listen log is
    ``serve``'s (``disable_listen_log``), as Effect's ``NodeHttpServer`` logs
    nothing itself."""

    async def info(self, message: str, *args: Any, **kwargs: Any) -> None:
        if not message.startswith("Running on "):
            await super().info(message, *args, **kwargs)


class _Config(Config):
    def create_ssl_context(self) -> ssl.SSLContext | None:
        context = super().create_ssl_context()
        return None if context is None else close_without_waiting(context)


class _Hypercorn:
    """hypercorn as an ``Engine``: it takes its sockets and a trigger to stop."""

    def __init__(self, dispatch: Dispatch, options: Options) -> None:
        self.dispatch = dispatch
        self.config = _Config()
        self.config.graceful_timeout = engine_backstop_seconds(options)
        self.config.logger_class = _EngineLogger
        for name, value in options.get("config", {}).items():
            setattr(self.config, name, value)
        self.started = False
        self._exit: asyncio.Event | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._should_exit = False

    @property
    def should_exit(self) -> bool:
        return self._should_exit

    @should_exit.setter
    def should_exit(self, value: bool) -> None:
        self._should_exit = value
        if value and self._loop is not None and self._exit is not None:
            self._loop.call_soon_threadsafe(self._exit.set)

    async def serve(self, sockets: list[socket.socket]) -> None:
        self._loop = asyncio.get_running_loop()
        self._exit = asyncio.Event()
        if self._should_exit:
            return
        secure = self.config.ssl_enabled
        bound = Sockets(
            secure_sockets=sockets if secure else [],
            insecure_sockets=[] if secure else sockets,
            quic_sockets=[],
        )
        self.started = True
        await worker_serve(
            ASGIWrapper(cast("Any", self.dispatch)),
            self.config,
            sockets=bound,
            shutdown_trigger=self._exit.wait,
        )


def make(**options: Unpack[Options]) -> Effect[HttpServerService, SocketServerError, ScopeTag]:
    """An ``HttpServer`` on hypercorn, listening on ``host:port`` until the
    scope closes."""
    return make_listener(options, lambda dispatch: _Hypercorn(dispatch, options))


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
    (httpx) sending to it."""
    server = layer(**{"host": "127.0.0.1", **options})
    return layer_test_client.pipe(provide_merge(httpx_layer)).pipe(provide_merge(server))


__all__ = ["Options", "SocketServerError", "layer", "layer_server", "layer_test", "make"]
