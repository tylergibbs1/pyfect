"""An ``HttpServer`` on uvicorn (extra ``pyfect-dev[server]``; the counterpart
of Effect's ``NodeHttpServer.layer``)::

    main = server.serve(app).pipe(layer.provide(uvicorn_server.layer(port=8080)))

The socket is bound when the server is made, so ``address`` is known (port
0: any free port). uvicorn runs on the building fiber's asyncio loop under
``run_main`` / ``run_async``, else on a loop thread of its own; each
request runs on its own fiber on that loop, through ``pyfect.http.asgi``
(streamed bodies, client aborts, WebSocket upgrades). Requests that arrive
while no app is served get a 503. When the serving scope closes, uvicorn
stops accepting and gives requests in flight ``graceful_shutdown_timeout``
before cancelling them.
"""
# pyright: reportPrivateUsage=false

from __future__ import annotations

import asyncio
import socket
import threading
from collections.abc import Callable, Coroutine, Mapping
from concurrent.futures import Future
from typing import Any, Never, NotRequired, TypedDict, Unpack

from pyfect._extras import missing_extra

try:
    import uvicorn
except ImportError as error:  # pragma: no cover - depends on the environment
    raise missing_extra("pyfect.http.uvicorn_server", "server") from error

from pyfect._core import Effect, _WithFiber
from pyfect._fiber import Fiber
from pyfect._os_wait import Resume, os_wait
from pyfect._root import run_loop
from pyfect.context import Context
from pyfect.duration import Duration, to_seconds
from pyfect.effect import fail, succeed, suspend, sync
from pyfect.file_system import FileSystem
from pyfect.http.asgi._serve import AsgiHandler
from pyfect.http.asgi._types import Receive, Scope, Send
from pyfect.http.client import HttpClient
from pyfect.http.etag import Generator
from pyfect.http.httpx_client import layer as httpx_layer
from pyfect.http.live_server import layer_services
from pyfect.http.platform import HttpPlatform
from pyfect.http.server import HttpApp, HttpServer, HttpServerService, Middleware, layer_test_client
from pyfect.http.server import make as make_server
from pyfect.layer import Layer, merge, provide_merge
from pyfect.layer import effect as layer_effect
from pyfect.net.net_address import inet_address_from_native_unsafe
from pyfect.path import Path
from pyfect.run import run_fork
from pyfect.scope import CloseableScope, acquire_release
from pyfect.scope import Scope as ScopeTag
from pyfect.socket._web_socket import DEFAULT_MAX_MESSAGE_SIZE
from pyfect.socket.server import SocketServerError, SocketServerOpenError


class Options(TypedDict):
    port: NotRequired[int]
    """0 (the default): any free port."""
    host: NotRequired[str]
    """Every interface by default (IPv6 and IPv4 where the host has both)."""
    graceful_shutdown_timeout: NotRequired[Duration]
    """How long requests in flight may run once the server closes (20s)."""
    config: NotRequired[Mapping[str, Any]]
    """More ``uvicorn.Config`` arguments (``http``, ``ws``, ``ws_max_size``,
    ``proxy_headers``, ``timeout_keep_alive``, ``log_config``...); the app,
    socket and lifespan are the server's."""


def _bind(host: str | None, port: int) -> socket.socket:
    if host is None:
        if socket.has_dualstack_ipv6():
            return socket.create_server(("::", port), family=socket.AF_INET6, dualstack_ipv6=True)
        return socket.create_server(("0.0.0.0", port))
    family, _, _, _, address = socket.getaddrinfo(
        host, port, type=socket.SOCK_STREAM, flags=socket.AI_PASSIVE
    )[0]
    return socket.create_server(address[:2], family=family)


class _Dispatch:
    """The ASGI app uvicorn runs: the served app's handler, or a 503."""

    __slots__ = ("current",)

    def __init__(self) -> None:
        self.current: AsgiHandler | None = None

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        handler = self.current
        if handler is not None:
            await handler(scope, receive, send)
        elif scope["type"] == "http":
            await send({"type": "http.response.start", "status": 503, "headers": []})
            await send({"type": "http.response.body", "body": b""})
        elif scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 1013})


def _loop_thread() -> asyncio.AbstractEventLoop:
    """A new loop, run on a daemon thread until stopped (then closed)."""
    loop = asyncio.new_event_loop()

    def run() -> None:
        loop.run_forever()
        loop.close()

    threading.Thread(target=run, name="pyfect-uvicorn", daemon=True).start()
    return loop


def _wait[A](future: Future[A]) -> Effect[A, BaseException]:
    """Wait for ``future`` (done on any thread) without blocking."""

    def register(resume: Resume[A, BaseException]) -> None:
        def done(finished: Future[A]) -> None:
            if finished.cancelled():
                resume(fail(asyncio.CancelledError()))
                return
            error = finished.exception()
            resume(succeed(finished.result()) if error is None else fail(error))

        future.add_done_callback(done)

    return os_wait(register)


class _Running:
    """uvicorn serving on ``loop`` until ``stop``."""

    def __init__(
        self, server: uvicorn.Server, loop: asyncio.AbstractEventLoop, owned: bool
    ) -> None:
        self.server = server
        self.loop = loop
        self.owned = owned
        self.served: Future[None] | None = None

    def submit[A](self, make: Callable[[], Coroutine[Any, Any, A]]) -> Future[A]:
        return asyncio.run_coroutine_threadsafe(make(), self.loop)

    def start(self, sock: socket.socket) -> Effect[None, BaseException]:
        self.served = self.submit(lambda: self.server.serve(sockets=[sock]))
        served = self.served

        async def started() -> None:
            while not self.server.started and not served.done():
                await asyncio.sleep(0.005)
            if served.done():
                served.result()
                raise RuntimeError("uvicorn stopped while starting")

        return _wait(self.submit(started))

    def stop(self) -> Effect[None]:
        def body() -> Effect[None]:
            self.server.should_exit = True
            assert self.served is not None
            return _wait(self.served).ignore().ensuring(sync(self._release))

        return suspend(body)

    def _release(self) -> None:
        if self.owned and not self.loop.is_closed():
            self.owned = False
            self.loop.call_soon_threadsafe(self.loop.stop)


def _uvicorn(dispatch: _Dispatch, options: Options) -> uvicorn.Server:
    graceful = to_seconds(options.get("graceful_shutdown_timeout", 20))
    config: dict[str, Any] = {
        "log_config": None,
        "server_header": False,
        "ws_max_size": DEFAULT_MAX_MESSAGE_SIZE,
        **options.get("config", {}),
    }
    config.update(app=dispatch, lifespan="off", timeout_graceful_shutdown=graceful)
    return uvicorn.Server(uvicorn.Config(**config))


def _serve(
    dispatch: _Dispatch, running: _Running
) -> Callable[[HttpApp, Middleware | None], Effect[None, Never, ScopeTag]]:
    def serve(app: HttpApp, middleware: Middleware | None) -> Effect[None, Never, ScopeTag]:
        def body(fiber: Fiber[Any, Any]) -> Effect[None, Never, ScopeTag]:
            context: Context[Any] = fiber._context
            serve_scope = context.get_unsafe(ScopeTag)
            requests: CloseableScope = serve_scope._fork_now("parallel")

            def fork(
                handled: Effect[None, Never, Any], request: Context[Any]
            ) -> Fiber[None, Never]:
                return run_fork(handled, context=request).run_in(requests)

            handler = AsgiHandler(app, middleware, context, fork)
            dispatch.current = handler

            def unserve(_exit: object) -> Effect[None]:
                def remove() -> None:
                    if dispatch.current is handler:
                        dispatch.current = None

                return running.stop().ensuring(sync(remove))

            return serve_scope.add_finalizer(unserve)

        return _WithFiber(body)

    return serve


def make(**options: Unpack[Options]) -> Effect[HttpServerService, SocketServerError, ScopeTag]:
    """An ``HttpServer`` on uvicorn, listening on ``host:port`` until the
    scope closes."""

    def bind() -> Effect[socket.socket, SocketServerError]:
        try:
            return succeed(_bind(options.get("host"), options.get("port", 0)))
        except OSError as cause:
            return fail(SocketServerError(SocketServerOpenError(cause)))

    def run(sock: socket.socket) -> Effect[HttpServerService, SocketServerError, ScopeTag]:
        dispatch = _Dispatch()

        def start() -> Effect[_Running, SocketServerError]:
            current = run_loop()
            loop = current or _loop_thread()
            running = _Running(_uvicorn(dispatch, options), loop, owned=current is None)
            return (
                running.start(sock)
                .as_(running)
                .catch_all(
                    lambda cause: running.stop().and_then(
                        fail(SocketServerError(SocketServerOpenError(cause)))
                    )
                )
            )

        def service(running: _Running) -> HttpServerService:
            host, port = sock.getsockname()[:2]
            address = inet_address_from_native_unsafe(host, port)
            return make_server(serve=_serve(dispatch, running), address=address)

        return acquire_release(suspend(start), lambda running, _: running.stop()).map(service)

    def close(sock: socket.socket, _exit: object) -> Effect[None]:
        return sync(sock.close)

    return acquire_release(suspend(bind), close).flat_map(run)


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


__all__ = ["Options", "layer", "layer_server", "layer_test", "make"]
