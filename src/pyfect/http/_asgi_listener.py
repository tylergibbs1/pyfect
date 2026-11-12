"""What ``uvicorn_server`` and ``hypercorn_server`` share: a socket bound when
the server is made, an ASGI engine on the program's loop (or a loop thread
shared by such servers), and the shutdown as ``NodeHttpServer``'s.
"""
# pyright: reportPrivateUsage=false

from __future__ import annotations

import asyncio
import socket
import threading
from collections.abc import Callable, Coroutine
from concurrent.futures import Future
from typing import Any, Never, NotRequired, Protocol, TypedDict

from pyfect._core import Effect, _WithFiber
from pyfect._fiber import Fiber
from pyfect._loop_thread import LoopThread
from pyfect._os_wait import Resume, WaitsFor, os_wait
from pyfect._root import run_loop
from pyfect.context import Context
from pyfect.duration import Duration, from_input_unsafe, zero
from pyfect.duration import Input as DurationInput
from pyfect.effect import fail, succeed, suspend, sync
from pyfect.exit import Exit
from pyfect.http.asgi._serve import AsgiHandler
from pyfect.http.asgi._types import Receive, Scope, Send
from pyfect.http.live_server._listener import ABORT_GRACE_PERIOD
from pyfect.http.server import HttpApp, HttpServerService, Middleware
from pyfect.http.server import make as make_server
from pyfect.net.net_address import inet_address_from_native_unsafe
from pyfect.run import run_fork
from pyfect.scope import CloseableScope, acquire_release
from pyfect.scope import Scope as ScopeTag
from pyfect.socket.server import SocketServerError, SocketServerOpenError


class ListenOptions(TypedDict):
    port: NotRequired[int]
    """0 (the default): any free port."""
    host: NotRequired[str]
    """Every interface by default (IPv6 and IPv4 where the host has both)."""
    graceful_shutdown_timeout: NotRequired[DurationInput]
    """How long requests in flight may run once the server closes (20s)."""
    disable_preemptive_shutdown: NotRequired[bool]
    """Give requests in flight no time: closing interrupts them at once."""


class Engine(Protocol):
    """An ASGI server that runs until ``should_exit`` is set."""

    @property
    def started(self) -> bool: ...

    @property
    def should_exit(self) -> bool: ...

    @should_exit.setter
    def should_exit(self, value: bool) -> None: ...

    def serve(self, sockets: list[socket.socket]) -> Coroutine[Any, Any, None]: ...


def _bind(host: str | None, port: int) -> socket.socket:
    if host is None:
        if socket.has_dualstack_ipv6():
            return socket.create_server(("::", port), family=socket.AF_INET6, dualstack_ipv6=True)
        return socket.create_server(("0.0.0.0", port))
    family, _, _, _, address = socket.getaddrinfo(
        host, port, type=socket.SOCK_STREAM, flags=socket.AI_PASSIVE
    )[0]
    return socket.create_server(address[:2], family=family)


class Dispatch:
    """The ASGI app the engine runs: the served app's handler. A request that
    arrives while no app is served waits for one, as a request reaching
    ``NodeHttpServer`` before ``serve`` adds its ``request`` listener stays
    pending: the socket is bound before the app's layers are built, so an
    open port does not mean the app is ready."""

    __slots__ = ("_current", "_lock", "_waiting")

    def __init__(self) -> None:
        self._current: AsgiHandler | None = None
        self._lock = threading.Lock()
        self._waiting: set[tuple[asyncio.AbstractEventLoop, asyncio.Future[None]]] = set()

    def install(self, handler: AsgiHandler) -> None:
        """Serve ``handler``, waking the requests waiting for an app."""
        with self._lock:
            self._current = handler
            waiting, self._waiting = self._waiting, set()
        for loop, waiter in waiting:
            loop.call_soon_threadsafe(_wake, waiter)

    def remove(self, handler: AsgiHandler) -> None:
        """Stop serving ``handler``, unless another app replaced it."""
        with self._lock:
            if self._current is handler:
                self._current = None

    async def _handler(self) -> AsgiHandler:
        loop = asyncio.get_running_loop()
        while True:
            with self._lock:
                if self._current is not None:
                    return self._current
                waiter = (loop, loop.create_future())
                self._waiting.add(waiter)
            try:
                await waiter[1]
            finally:
                with self._lock:
                    self._waiting.discard(waiter)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        handler = self._current
        if handler is None:
            if scope["type"] not in ("http", "websocket"):
                return  # hypercorn's lifespan: unsupported, so it goes on
            handler = await self._handler()
        await handler(scope, receive, send)


def _wake(waiter: asyncio.Future[None]) -> None:
    if not waiter.done():
        waiter.set_result(None)


class _Shared:
    lock = threading.Lock()
    loop: asyncio.AbstractEventLoop | None = None


def _loop_thread() -> asyncio.AbstractEventLoop:
    """The loop servers outside an asyncio program run on: one per process,
    on a daemon thread, started on first use and never stopped. Fibers run
    on it, and a fiber forked from a request can outlive its server (held
    by a layer released later), so stopping the loop with the server would
    strand it: interrupting it would wait for ever (DOGFOOD pulse #5)."""
    with _Shared.lock:
        if _Shared.loop is None:
            _Shared.loop = LoopThread("pyfect-asgi").loop
        return _Shared.loop


def _wait[A](future: Future[A], waits_for: WaitsFor) -> Effect[A, BaseException]:
    """Wait for ``future`` (done on any thread) without blocking."""

    def register(resume: Resume[A, BaseException]) -> None:
        def done(finished: Future[A]) -> None:
            if finished.cancelled():
                resume(fail(asyncio.CancelledError()))
                return
            error = finished.exception()
            resume(succeed(finished.result()) if error is None else fail(error))

        future.add_done_callback(done)

    return os_wait(register, waits_for=waits_for)


class Running:
    """The engine serving on ``loop`` until ``stop``."""

    def __init__(
        self,
        server: Engine,
        loop: asyncio.AbstractEventLoop,
        graceful: Duration,
    ) -> None:
        self.server = server
        self.graceful = graceful
        self.loop = loop
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
                raise RuntimeError("the server stopped while starting")

        return _wait(self.submit(started), "work")

    def stop(self) -> Effect[None]:
        """Stop accepting and wait for the engine to exit (its own
        graceful timeout cancels what is still running)."""

        def body() -> Effect[None]:
            self.server.should_exit = True
            assert self.served is not None
            return _wait(self.served, "event").ignore()

        return suspend(body)

    def shut_down(
        self, handler: AsgiHandler, requests: CloseableScope, exit: Exit[Any, Any]
    ) -> Effect[None]:
        """As ``NodeHttpServer``'s preemptive shutdown: stop accepting and
        give requests in flight ``graceful`` seconds, then interrupt the
        request fibers (``requests``) and end the bodies still streaming, so
        the engine exits before its own timeout would cancel them."""

        def end_responses() -> Effect[None]:
            async def end() -> None:
                handler.end_responses()

            return _wait(self.submit(end), "work").ignore()

        def body() -> Effect[None]:
            self.server.should_exit = True
            assert self.served is not None
            served = _wait(self.served, "event").ignore()
            return (
                served.timeout_option(self.graceful)
                .and_then(requests.close(exit))
                .and_then(suspend(end_responses))
                .and_then(self.stop())
            )

        return suspend(body)


def graceful(options: ListenOptions) -> Duration:
    if options.get("disable_preemptive_shutdown", False):
        return zero
    return from_input_unsafe(options.get("graceful_shutdown_timeout", "20 seconds"))


def engine_backstop_seconds(options: ListenOptions) -> float:
    """The engine's own graceful timeout, in seconds as its config takes it: the
    graceful shutdown timeout plus the abort grace period."""
    return (graceful(options) + ABORT_GRACE_PERIOD).to_seconds()


def _serve(
    dispatch: Dispatch, running: Running
) -> Callable[[HttpApp, Middleware | None], Effect[None, Never, ScopeTag]]:
    def serve(app: HttpApp, middleware: Middleware | None) -> Effect[None, Never, ScopeTag]:
        def body(fiber: Fiber[Any, Any]) -> Effect[None, Never, ScopeTag]:
            context: Context[Any] = fiber._context
            serve_scope = context.get_unsafe(ScopeTag)
            requests: CloseableScope = serve_scope.fork_unsafe("parallel")

            def fork(
                handled: Effect[None, Never, Any], request: Context[Any]
            ) -> Fiber[None, Never]:
                return run_fork(handled, context=request).run_in(requests)

            handler = AsgiHandler(app, middleware, context, fork)
            dispatch.install(handler)

            def unserve(exit: Exit[Any, Any]) -> Effect[None]:
                return running.shut_down(handler, requests, exit).ensuring(
                    sync(lambda: dispatch.remove(handler))
                )

            return serve_scope.add_finalizer(unserve)

        return _WithFiber(body)

    return serve


def make_listener(
    options: ListenOptions, engine: Callable[[Dispatch], Engine]
) -> Effect[HttpServerService, SocketServerError, ScopeTag]:
    """An ``HttpServer`` on ``engine``, listening until the scope closes."""

    def bind() -> Effect[socket.socket, SocketServerError]:
        try:
            return succeed(_bind(options.get("host"), options.get("port", 0)))
        except OSError as cause:
            return fail(SocketServerError(SocketServerOpenError(cause)))

    def run(sock: socket.socket) -> Effect[HttpServerService, SocketServerError, ScopeTag]:
        dispatch = Dispatch()

        def start() -> Effect[Running, SocketServerError]:
            current = run_loop()
            loop = current or _loop_thread()
            running = Running(engine(dispatch), loop, graceful=graceful(options))
            return (
                running.start(sock)
                .as_(running)
                .catch_all(
                    lambda cause: running.stop().and_then(
                        fail(SocketServerError(SocketServerOpenError(cause)))
                    )
                )
            )

        def service(running: Running) -> HttpServerService:
            host, port = sock.getsockname()[:2]
            address = inet_address_from_native_unsafe(host, port)
            return make_server(serve=_serve(dispatch, running), address=address)

        return acquire_release(suspend(start), lambda running, _: running.stop()).map(service)

    def close(sock: socket.socket, _exit: object) -> Effect[None]:
        return sync(sock.close)

    return acquire_release(suspend(bind), close).flat_map(run)


__all__ = ["Dispatch", "Engine", "ListenOptions", "Running", "graceful", "make_listener"]
