"""``to_asgi``: an app as an ASGI 3 application whose services a layer
builds, in a ``ManagedRuntime`` that lives as long as the server's
lifespan."""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from collections.abc import AsyncGenerator, Callable
from contextlib import asynccontextmanager
from typing import Any, Never, overload

from pyfect._context_effects import provide_context
from pyfect._core import Effect, _WithFiber
from pyfect._effect_args import require_effect
from pyfect._fiber import Fiber
from pyfect._layer_core import MemoMap, require_layer
from pyfect.context import Context, Tag
from pyfect.effect import succeed
from pyfect.http.asgi._serve import AsgiHandler
from pyfect.http.asgi._types import Receive, Scope, Send
from pyfect.http.http_effect import HttpMiddleware
from pyfect.http.server_request import HttpServerRequest
from pyfect.http.server_response import HttpServerResponse
from pyfect.layer import Layer, provide_merge
from pyfect.layer import effect as layer_effect
from pyfect.layer import empty as empty_layer
from pyfect.managed_runtime import ManagedRuntime
from pyfect.scope import Scope as ScopeTag


class AsgiApp:
    """An ASGI 3 application (``await app(scope, receive, send)``) serving
    an HTTP app.

    ``runtime`` holds the layer's services: built by the ``lifespan``
    scope's startup, or by the first request when the server sends none,
    and released at its shutdown, which interrupts requests in flight
    (a plain app is uninterruptible, as in Effect, so it is awaited; router
    routes are interruptible). Each request runs on its own fiber, on the
    server's loop."""

    __slots__ = ("_handler", "runtime")

    def __init__(
        self,
        app: Effect[HttpServerResponse, Any, Any],
        runtime: ManagedRuntime[Any, Any],
        middleware: HttpMiddleware | None,
    ) -> None:
        self.runtime = runtime
        self._handler = AsgiHandler(app, middleware, Context.empty(), self._fork)

    def _fork(self, handled: Effect[None, Never, Any], context: Context[Any]) -> Fiber[None, Never]:
        return self.runtime.run_fork(handled.pipe(provide_context(context)))

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "lifespan":
            await self._lifespan(receive, send)
        else:
            await self._handler(scope, receive, send)

    async def _lifespan(self, receive: Receive, send: Send) -> None:
        while True:
            message = await receive()
            if message["type"] == "lifespan.startup":
                try:
                    await self.runtime.context()
                except Exception as error:
                    await send({"type": "lifespan.startup.failed", "message": str(error)})
                    return
                await send({"type": "lifespan.startup.complete"})
            elif message["type"] == "lifespan.shutdown":
                await self.runtime.dispose_async()
                await send({"type": "lifespan.shutdown.complete"})
                return

    @asynccontextmanager
    async def lifespan(self) -> AsyncGenerator[None]:
        """Build the services on enter and release them on exit: the
        lifespan of a host app this one is mounted in (``FastAPI(lifespan=
        lambda _: app.lifespan())``), whose server sends no lifespan to
        mounted apps."""
        await self.runtime.context()
        try:
            yield
        finally:
            await self.runtime.dispose_async()


type _Served = HttpServerRequest | ScopeTag


@overload
def to_asgi[E](
    app: Effect[HttpServerResponse, E, _Served],
    /,
    *,
    middleware: HttpMiddleware | None = None,
) -> AsgiApp: ...
@overload
def to_asgi[E, R, LE](
    app: Effect[HttpServerResponse, E, R | _Served],
    layer: Layer[R, LE],
    /,
    *,
    middleware: HttpMiddleware | None = None,
    memo_map: MemoMap | None = None,
) -> AsgiApp: ...
def to_asgi(
    app: Effect[HttpServerResponse, Any, Any],
    layer: Layer[Any, Any] | None = None,
    /,
    *,
    middleware: HttpMiddleware | None = None,
    memo_map: MemoMap | None = None,
) -> AsgiApp:
    """``app`` (through ``middleware``) as an ASGI 3 application for
    uvicorn, hypercorn, granian or a host framework, with the services of
    ``layer``. ``HEAD`` responses have no body; request bodies are
    streams; streamed responses are sent as they are produced; a client
    disconnect interrupts the request; WebSocket requests are upgraded
    through ``request.upgrade``."""
    require_effect(app, "app")
    if layer is not None:
        require_layer(layer, "layer")
    runtime = ManagedRuntime.make(empty_layer if layer is None else layer, memo_map=memo_map)
    return AsgiApp(app, runtime, middleware)


class _ServedApp(Tag[Effect[HttpServerResponse, Any, Any]], key="pyfect/http/asgi/ServedApp"):
    """The app ``to_asgi_with`` made of the layer's services."""


def _served(fiber: Fiber[Any, Any]) -> Effect[HttpServerResponse, Any, Any]:
    return fiber._context.unsafe_get(_ServedApp)


def to_asgi_with[LE](
    layer: Layer[Any, LE],
    to_app: Callable[[Context[Any]], Effect[HttpServerResponse, Any, Any]],
    *,
    middleware: HttpMiddleware | None = None,
    memo_map: MemoMap | None = None,
) -> AsgiApp:
    """``to_asgi`` for the app ``to_app`` makes of ``layer``'s services once
    they are built (what ``router.to_asgi`` serves routes with)."""
    require_layer(layer, "layer")

    def make(fiber: Fiber[Any, Any]) -> Effect[Effect[HttpServerResponse, Any, Any]]:
        return succeed(to_app(fiber._context))

    served = layer_effect(_ServedApp, _WithFiber(make)).pipe(provide_merge(layer))
    runtime = ManagedRuntime.make(served, memo_map=memo_map)
    app: Effect[HttpServerResponse, Any, Any] = _WithFiber(_served)
    return AsgiApp(app, runtime, middleware)
