"""HTTP apps as asyncio handlers, and asyncio handlers as apps (Effect's
``HttpEffect.toWebHandler`` family, ``fromWebHandler`` and the Web
conversions of ``HttpServerRequest`` / ``HttpServerResponse``).

A handler is ``async (WebRequest, context=None) -> WebResponse``. Each
request runs the app on its own fiber (``http_effect.to_handled``); the
request's signal interrupts it as a client abort (499). A streamed body
owns the request's scope: it closes when the body ends, when the reader
stops, or when the signal fires.
"""
# pyright: reportPrivateUsage=false

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterable, AsyncIterator, Awaitable, Callable
from contextlib import aclosing
from dataclasses import dataclass
from typing import Any, Never, Protocol

from pyfect import _background as background
from pyfect._core import Effect, _WithFiber
from pyfect._effect_args import require_effect
from pyfect._fiber import Fiber
from pyfect._layer_core import MemoMap, require_layer
from pyfect.context import Context
from pyfect.effect import fail, succeed, try_async, void
from pyfect.exit import Exit, Success
from pyfect.http import _request_state
from pyfect.http import body as _body
from pyfect.http._foreign_path import has_dot_segment
from pyfect.http._url_text import split_url
from pyfect.http.abort import AbortController, AbortSignal
from pyfect.http.http_effect import HttpMiddleware, to_handled
from pyfect.http.server_error import (
    CLIENT_ABORT_ANNOTATION,
    HttpServerError,
    InternalError,
    RequestParseError,
)
from pyfect.http.server_request import (
    HttpServerRequest,
    ServerRequest,
    SourceRequest,
    to_url,
)
from pyfect.http.server_response import HttpServerResponse, omits_body
from pyfect.http.web import WebRequest, WebResponse
from pyfect.http.wire import WireResponse, from_wire, to_wire
from pyfect.layer import Layer
from pyfect.result import Err, Ok, Result
from pyfect.run import await_fiber, run_async_exit, run_fork
from pyfect.scope import CloseableScope, Scope
from pyfect.stream import Stream, from_async_iterable
from pyfect.stream import succeed as stream_succeed

type Fork = Callable[[Effect[None, Never, Any], Context[Any]], Fiber[None, Never]]
"""Starts a request's fiber: the handled app and the request's services."""


def _run_fork(handled: Effect[None, Never, Any], context: Context[Any]) -> Fiber[None, Never]:
    return run_fork(handled, context=context)


class WebHandler(Protocol):
    """Answers one request; ``context`` adds services for this request."""

    def __call__(
        self, request: WebRequest, context: Context[Any] | None = None, /
    ) -> Awaitable[WebResponse]: ...


# --- requests ---------------------------------------------------------------


def request_from_web(request: WebRequest) -> ServerRequest:
    """A server request reading ``request`` (Effect's
    ``HttpServerRequest.fromWeb``); its ``source`` is ``request``."""
    body = request.body

    def open_body() -> Stream[bytes, object]:
        chunks = request.chunks()
        if isinstance(body, bytes):
            return stream_succeed(body)
        return from_async_iterable(chunks, lambda error: error)

    def read_body() -> Stream[bytes, object]:
        # A whole read stops at the size limit without waiting for the
        # body's cleanup, which may never settle (as Effect's).
        if isinstance(body, bytes):
            return stream_succeed(body)
        return from_async_iterable(_DetachedClose(request.chunks()), lambda error: error)

    return SourceRequest(
        request.method,
        request.url,
        request.headers,
        None if body is None else open_body,
        source=request,
        remote_address=request.remote_address,
        read_body=None if body is None else read_body,
    )


class _DetachedClose:
    """Chunks whose ``aclose`` closes the source in the background."""

    __slots__ = ("_chunks",)

    def __init__(self, chunks: AsyncIterator[bytes]) -> None:
        self._chunks = chunks

    def __aiter__(self) -> AsyncIterator[bytes]:
        return self

    async def __anext__(self) -> bytes:
        return await anext(self._chunks)

    async def aclose(self) -> None:
        close = getattr(self._chunks, "aclose", None)
        if close is not None:
            background.start(close(), asyncio.get_running_loop())


def request_to_web(
    request: ServerRequest,
    *,
    signal: AbortSignal | None = None,
    context: Context[Any] | None = None,
) -> Result[WebRequest, RequestParseError]:
    """``request`` as a ``WebRequest`` (its source, if it is one); the body
    is read when the Web body is read. A path with a dot segment fails: the
    router matched it literally, and the handler may resolve it."""
    parts = split_url(request.original_url)
    if parts is None:
        return Err(RequestParseError(request, "Invalid URL"))
    if has_dot_segment(parts.path):
        return Err(RequestParseError(request, "Dot segment in the request path"))
    if isinstance(request.source, WebRequest):
        return Ok(request.source)
    url = to_url(request)
    if url is None:
        return Err(RequestParseError(request, "Invalid URL"))
    body: AsyncIterable[bytes] | None = None
    if request.method not in ("GET", "HEAD", "OPTIONS", "TRACE"):
        body = _StreamBody(request.stream, context or Context.empty(), None, signal)
    return Ok(
        WebRequest(
            url.href,
            method=request.method,
            headers=request.headers,
            body=body,
            signal=signal,
            remote_address=request.remote_address,
        )
    )


# --- responses --------------------------------------------------------------


class _StreamBody:
    """A streamed body, read once in asyncio. When ``scope`` is given it
    closes when the read stops, or when ``signal`` fires (read or not)."""

    __slots__ = ("_closing", "_context", "_scope", "_started", "_stream")

    def __init__(
        self,
        stream: Stream[bytes, Any, Any],
        context: Context[Any],
        scope: CloseableScope | None,
        signal: AbortSignal | None,
    ) -> None:
        self._stream = stream
        self._context = context
        self._scope = scope
        self._started: AsyncIterator[bytes] | None = None
        self._closing: list[asyncio.Task[None]] = []
        if signal is not None:
            signal.add_listener(self._abort)

    def _abort(self) -> None:
        started = self._started
        if started is not None:
            self._closing.append(asyncio.ensure_future(_aclose(started)))
        elif self._scope is not None:
            run_fork(self._scope.close(Success(None)))

    def __aiter__(self) -> AsyncIterator[bytes]:
        if self._started is not None:
            raise RuntimeError("body already read")
        source = self._stream.to_async_iterable_with(self._context).__aiter__()
        self._started = source
        return self._read(source)

    async def _read(self, source: AsyncIterator[bytes]) -> AsyncIterator[bytes]:
        async with aclosing(source):  # pyright: ignore[reportArgumentType]
            async for chunk in source:
                yield chunk


async def _aclose(iterator: AsyncIterator[bytes]) -> None:
    close = getattr(iterator, "aclose", None)
    if close is not None:
        await close()


def response_to_web(
    response: HttpServerResponse,
    *,
    without_body: bool = False,
    context: Context[Any] | None = None,
    signal: AbortSignal | None = None,
    scope: CloseableScope | None = None,
) -> WebResponse:
    """``response`` as a ``WebResponse`` (Effect's
    ``HttpServerResponse.toWeb``): a streamed body runs with ``context``
    when read, and stops when ``signal`` fires; ``scope`` closes with it."""
    raw = response.body.body if isinstance(response.body, _body.Raw) else None
    if (
        isinstance(raw, WebResponse)
        and not without_body
        and not omits_body(response)
        and not response.headers
        and response.cookies.is_empty()
        and not (raw.status in (204, 205) and raw.has("content-length"))
    ):
        return raw
    wire = to_wire(response, without_body=without_body)
    body: bytes | AsyncIterable[bytes] | None
    match wire.body:
        case None | bytes():
            body = wire.body
        case stream:
            closing = stream if scope is None else stream.on_exit(scope.close)
            body = _StreamBody(closing, context or Context.empty(), scope, signal)
    return WebResponse(body, status=wire.status, status_text=wire.status_text, headers=wire.headers)


def response_from_web(response: WebResponse) -> HttpServerResponse:
    """A server response sending ``response`` (Effect's
    ``HttpServerResponse.fromWeb``): its cookies parsed from
    ``set-cookie``, its body streamed."""
    body = response.body
    wire_body: bytes | Stream[bytes, object] | None
    if body is None or isinstance(body, bytes):
        wire_body = body
    else:
        wire_body = from_async_iterable(response.chunks(), lambda error: error)
    return from_wire(
        WireResponse(response.status, response.status_text, response.header_lines, wire_body)
    )


# --- handlers ---------------------------------------------------------------


def _handle(
    app: Effect[HttpServerResponse, Any, Any],
    middleware: HttpMiddleware | None,
    static: Context[Any],
    request: WebRequest,
    extra: Context[Any] | None,
    *,
    fork: Fork,
) -> Awaitable[WebResponse]:
    loop = asyncio.get_running_loop()
    result: asyncio.Future[WebResponse] = loop.create_future()
    signal = request.signal

    def handle_response(
        server_request: ServerRequest, response: HttpServerResponse
    ) -> Effect[None]:
        without_body = server_request.method == "HEAD"
        fiber = Fiber.get_current()
        scope: CloseableScope | None = None
        if fiber is not None and not omits_body(response, without_body):
            state = _request_state.get(fiber._context)
            found, current = fiber._context.lookup(Scope)
            if state is not None and found and isinstance(response.body, _body.Stream):
                # The body closes the request's scope, even if it is never read.
                state.scope_ejected = True
                scope = current
        context = static if fiber is None else fiber._context
        web = response_to_web(
            response, without_body=without_body, context=context, signal=signal, scope=scope
        )
        if not result.done():
            result.set_result(web)
        return void

    handled = to_handled(app, handle_response, middleware)
    context = static if extra is None else static.merge(extra)
    context = context.add(HttpServerRequest, request_from_web(request))
    fiber = fork(handled, context)

    def on_exit(exit: Exit[Any, Any]) -> None:
        if not result.done():
            error = exit.cause.raisable() if not isinstance(exit, Success) else None
            result.set_exception(error or RuntimeError("the app sent no response"))

    fiber.add_observer_unsafe(on_exit)
    if fiber.poll_unsafe() is None and signal is not None:

        def abort() -> None:
            fiber.interrupt_as_unsafe(None, CLIENT_ABORT_ANNOTATION)

        remove = signal.add_listener(abort)

        def stop_listening(_exit: Exit[Any, Any]) -> None:
            remove()

        fiber.add_observer_unsafe(stop_listening)
    return result


def to_web_handler_with(
    context: Context[Any], *, fork: Fork = _run_fork
) -> Callable[[Effect[HttpServerResponse, Any, Any], HttpMiddleware | None], WebHandler]:
    """``to_web_handler`` for an app needing the services of ``context``
    (each request may add more). ``fork`` starts each request's fiber (a
    root fiber by default)."""

    def make(
        app: Effect[HttpServerResponse, Any, Any], middleware: HttpMiddleware | None = None
    ) -> WebHandler:
        def handler(
            request: WebRequest, extra: Context[Any] | None = None
        ) -> Awaitable[WebResponse]:
            return _handle(app, middleware, context, request, extra, fork=fork)

        return handler

    return make


def to_web_handler[E](
    app: Effect[HttpServerResponse, E, HttpServerRequest | Scope],
    middleware: HttpMiddleware | None = None,
) -> WebHandler:
    """``app`` as an asyncio handler. ``HEAD`` responses have no body; a
    streamed body closes the request's scope when it ends."""
    require_effect(app, "app")
    return to_web_handler_with(Context.empty())(app, middleware)


@dataclass(frozen=True, slots=True)
class WebHandlerLayer:
    """A handler whose services a layer built, and ``dispose`` releasing
    them."""

    handler: WebHandler
    dispose: Callable[[], asyncio.Future[None]]
    """Release the services; calls while releasing share one future."""


async def _settled(closing: Awaitable[Exit[None, Never]]) -> None:
    await closing


def to_web_handler_layer_with[E, LE](
    layer: Layer[Any, LE],
    to_handler: Callable[[Context[Any]], Effect[Effect[HttpServerResponse, E, Any], LE]],
    middleware: HttpMiddleware | None = None,
    *,
    memo_map: MemoMap | None = None,
) -> WebHandlerLayer:
    """Build ``layer`` now (on the running loop), then handle requests with
    the app ``to_handler`` makes of its services. If the build fails, every
    request raises its error. Handlers built with one ``memo_map`` share
    the layers they have in common."""
    require_layer(layer, "layer")
    scope = CloseableScope()

    def build(context: Context[Any]) -> Effect[WebHandler, LE]:
        return to_handler(context).map(lambda app: to_web_handler_with(context)(app, middleware))

    # Started now, as Effect's runPromise: the build runs up to its first wait.
    building_layer = (
        layer.build_with_scope(scope)
        if memo_map is None
        else layer.build_with_memo_map(memo_map, scope)
    )
    built = run_fork(building_layer.flat_map(build))
    building = asyncio.ensure_future(await_fiber(built))
    disposing: list[asyncio.Future[None]] = []

    async def handler(request: WebRequest, extra: Context[Any] | None = None) -> WebResponse:
        exit = await asyncio.shield(building)
        if not isinstance(exit, Success):
            raise exit.cause.raisable()
        return await exit.value(request, extra)

    def dispose() -> asyncio.Future[None]:
        if not disposing:
            closing = asyncio.ensure_future(run_async_exit(scope.close(Success(None))))
            disposing.append(asyncio.ensure_future(_settled(closing)))
        return disposing[0]

    return WebHandlerLayer(handler, dispose)


def to_web_handler_layer[E, LE](
    app: Effect[HttpServerResponse, E, Any],
    layer: Layer[Any, LE],
    middleware: HttpMiddleware | None = None,
    *,
    memo_map: MemoMap | None = None,
) -> WebHandlerLayer:
    """``to_web_handler`` for an app needing the services ``layer``
    builds."""
    require_effect(app, "app")
    require_layer(layer, "layer")
    return to_web_handler_layer_with(
        layer, lambda _context: succeed(app), middleware, memo_map=memo_map
    )


def from_web_handler(
    handler: Callable[[WebRequest], Awaitable[WebResponse]],
) -> Effect[HttpServerResponse, HttpServerError, HttpServerRequest]:
    """An app answering with ``handler`` (Effect's ``fromWebHandler``);
    interrupting it fires the Web request's signal. Needs an asyncio run."""

    def run(fiber: Fiber[Any, Any]) -> Effect[HttpServerResponse, HttpServerError]:
        request = fiber._context.get_unsafe(HttpServerRequest)
        controller = AbortController()
        match request_to_web(request, signal=controller.signal, context=fiber._context):
            case Err(reason):
                return fail(HttpServerError(reason))
            case Ok(web):
                pass

        async def call() -> WebResponse:
            try:
                return await handler(web)
            except asyncio.CancelledError:
                controller.abort()
                raise

        def on_error(cause: Exception) -> HttpServerError:
            return HttpServerError(
                InternalError(request, "HttpApp.fromWebHandler: Error in handler", cause)
            )

        return try_async(call, on_error).map(response_from_web)

    return _WithFiber(run)


__all__ = [
    "Fork",
    "HttpServerError",
    "WebHandler",
    "WebHandlerLayer",
    "from_web_handler",
    "request_from_web",
    "request_to_web",
    "response_from_web",
    "response_to_web",
    "to_web_handler",
    "to_web_handler_layer",
    "to_web_handler_layer_with",
    "to_web_handler_with",
]
