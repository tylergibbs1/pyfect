"""Another framework's ASGI application (FastAPI, Starlette...) as an HTTP
app: ``from_asgi`` answers each request with it, and ``lifespan`` runs its
startup and shutdown with a scope. Both await the application on the
fiber's asyncio loop, so they need an asyncio run (``run_main``,
``run_async``, the ASGI and uvicorn servers)."""
# pyright: reportPrivateUsage=false

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass
from typing import Any
from urllib.parse import unquote, urlsplit

from pyfect._core import Effect, _WithFiber
from pyfect._fiber import Fiber
from pyfect.effect import fail, from_async, try_async
from pyfect.errors import TaggedError
from pyfect.http.abort import AbortController
from pyfect.http.asgi._types import AsgiApplication, Message
from pyfect.http.server_error import HttpServerError, InternalError
from pyfect.http.server_request import HttpServerRequest, ServerRequest, to_url
from pyfect.http.server_response import HttpServerResponse
from pyfect.http.web import WebResponse
from pyfect.http.web_handler import request_to_web, response_from_web
from pyfect.result import Err, Ok
from pyfect.scope import Scope, acquire_release

_ASGI = {"version": "3.0", "spec_version": "2.4"}
_QUEUED_CHUNKS = 16


class AsgiNoResponseError(RuntimeError):
    """The application returned without starting a response."""


def _root_path(request: ServerRequest) -> tuple[str, str]:
    """The original path, and the part of it a router's prefix removed."""
    original = urlsplit(request.original_url).path or "/"
    path = request.url.split("?", 1)[0] or "/"
    if path == "/":
        return original, original.removesuffix("/")
    if original.endswith(path):
        return original, original[: len(original) - len(path)]
    return original, ""


def _scope(request: ServerRequest, state: Mapping[str, Any] | None) -> dict[str, Any]:
    original, root = _root_path(request)
    query = request.url.split("?", 1)[1] if "?" in request.url else ""
    url = to_url(request)
    scheme = url.scheme if url is not None else "http"
    server = (
        None
        if url is None or url.hostname is None
        else (url.hostname, url.port or (443 if scheme == "https" else 80))
    )
    remote = request.remote_address
    scope: dict[str, Any] = {
        "type": "http",
        "asgi": _ASGI,
        "http_version": "1.1",
        "method": request.method,
        "scheme": scheme,
        "path": unquote(original),
        "raw_path": original.encode("latin-1", "replace"),
        "root_path": unquote(root),
        "query_string": query.encode("latin-1", "replace"),
        "headers": [
            (name.encode("latin-1"), value.encode("latin-1"))
            for name, value in request.headers.items()
        ],
        "client": None if remote is None else (remote, 0),
        "server": server,
        "extensions": {},
    }
    if state is not None:
        scope["state"] = dict(state)
    return scope


class _Exchange:
    """One call of the application: ``receive`` reads the request body,
    ``send`` hands the response over."""

    def __init__(self, body: AsyncIterator[bytes] | None) -> None:
        loop = asyncio.get_running_loop()
        self._body = body
        self._body_done = False
        self.finished = asyncio.Event()
        self.started: asyncio.Future[tuple[int, list[tuple[str, str]]]] = loop.create_future()
        self.chunks: asyncio.Queue[bytes | None] = asyncio.Queue(_QUEUED_CHUNKS)

    async def receive(self) -> Message:
        if not self._body_done:
            if self._body is not None:
                try:
                    chunk = await anext(self._body)
                except StopAsyncIteration:
                    pass
                else:
                    return {"type": "http.request", "body": chunk, "more_body": True}
            self._body_done = True
            return {"type": "http.request", "body": b"", "more_body": False}
        await self.finished.wait()
        return {"type": "http.disconnect"}

    async def send(self, message: Message) -> None:
        if message["type"] == "http.response.start" and not self.started.done():
            headers: list[tuple[bytes, bytes]] = message.get("headers", [])
            self.started.set_result(
                (
                    message["status"],
                    [(name.decode("latin-1"), value.decode("latin-1")) for name, value in headers],
                )
            )
        elif message["type"] == "http.response.body" and not self.finished.is_set():
            chunk: bytes = message.get("body", b"")
            if chunk:
                await self.chunks.put(chunk)
            if not message.get("more_body", False):
                self.finished.set()
                await self.chunks.put(None)


async def _body(exchange: _Exchange, task: asyncio.Task[None]) -> AsyncIterator[bytes]:
    try:
        while True:
            getting = asyncio.ensure_future(exchange.chunks.get())
            await asyncio.wait((getting, task), return_when=asyncio.FIRST_COMPLETED)
            if not getting.done():
                getting.cancel()
                # The application ended (or raised) before ending the body.
                task.result()
                raise AsgiNoResponseError("the ASGI application did not end the response")
            chunk = getting.result()
            if chunk is None:
                return
            yield chunk
    finally:
        exchange.finished.set()
        if not task.done():
            task.cancel()


async def _call(
    app: AsgiApplication, scope: dict[str, Any], body: AsyncIterator[bytes] | None
) -> WebResponse:
    exchange = _Exchange(body)
    task = asyncio.ensure_future(app(scope, exchange.receive, exchange.send))
    try:
        await asyncio.wait((exchange.started, task), return_when=asyncio.FIRST_COMPLETED)
    except asyncio.CancelledError:
        exchange.finished.set()
        task.cancel()
        raise
    if not exchange.started.done():
        task.result()
        raise AsgiNoResponseError("the ASGI application returned without a response")
    status, headers = exchange.started.result()
    return WebResponse(_body(exchange, task), status=status, headers=headers)


def from_asgi(
    app: AsgiApplication, *, state: Mapping[str, Any] | None = None
) -> Effect[HttpServerResponse, HttpServerError, HttpServerRequest]:
    """An app answering with the ASGI application ``app`` (Effect's
    ``fromWebHandler`` for ASGI). Mounted under a router prefix
    (``router.prefix_route``), the prefix is the scope's ``root_path``;
    ``state`` is the scope's ``state`` (what ``lifespan`` gives).
    Interrupting the app cancels the call."""

    def run(fiber: Fiber[Any, Any]) -> Effect[HttpServerResponse, HttpServerError]:
        request = fiber._context.unsafe_get(HttpServerRequest)
        controller = AbortController()
        match request_to_web(request, signal=controller.signal, context=fiber._context):
            case Err(reason):
                return fail(HttpServerError(reason))
            case Ok(web):
                pass
        scope = _scope(request, state)
        body = None if web.body is None else web.chunks()

        async def call() -> WebResponse:
            try:
                return await _call(app, scope, body)
            except asyncio.CancelledError:
                controller.abort()
                raise

        def on_error(cause: Exception) -> HttpServerError:
            return HttpServerError(InternalError(request, "HttpApp.fromAsgi: Error in app", cause))

        return try_async(call, on_error).map(response_from_web)

    return _WithFiber(run)


@dataclass(frozen=True)
class AsgiLifespanError(TaggedError):
    """The application's lifespan startup failed."""

    message: str


class _Lifespan:
    """A running ``lifespan`` scope."""

    def __init__(self, app: AsgiApplication) -> None:
        self.state: dict[str, Any] = {}
        self._inbox: asyncio.Queue[Message] = asyncio.Queue()
        self._outbox: asyncio.Queue[Message] = asyncio.Queue()
        scope = {"type": "lifespan", "asgi": _ASGI, "state": self.state}
        self._task = asyncio.ensure_future(app(scope, self._inbox.get, self._outbox.put))
        self._supported = True

    async def _reply(self) -> Message | None:
        """The application's next message; ``None`` once it has ended."""
        replying = asyncio.ensure_future(self._outbox.get())
        await asyncio.wait((replying, self._task), return_when=asyncio.FIRST_COMPLETED)
        if replying.done():
            return replying.result()
        replying.cancel()
        return None

    async def startup(self) -> None:
        await self._inbox.put({"type": "lifespan.startup"})
        reply = await self._reply()
        if reply is None:
            # An application without lifespan support raises or returns.
            self._supported = False
            if not self._task.cancelled():
                self._task.exception()
            return
        if reply["type"] == "lifespan.startup.failed":
            raise AsgiLifespanError(reply.get("message", ""))

    async def shutdown(self) -> None:
        if self._supported and not self._task.done():
            await self._inbox.put({"type": "lifespan.shutdown"})
            await self._reply()
        if not self._task.done():
            self._task.cancel()


def lifespan(app: AsgiApplication) -> Effect[dict[str, Any], AsgiLifespanError, Scope]:
    """Start ``app``'s lifespan (its startup handlers) and shut it down when
    the scope closes; succeeds with the lifespan ``state`` to pass to
    ``from_asgi``. An application without lifespan support starts at once."""

    async def start() -> _Lifespan:
        running = _Lifespan(app)
        await running.startup()
        return running

    def on_error(cause: Exception) -> AsgiLifespanError:
        return cause if isinstance(cause, AsgiLifespanError) else AsgiLifespanError(str(cause))

    return acquire_release(
        try_async(start, on_error), lambda running, _exit: from_async(running.shutdown)
    ).map(lambda running: running.state)
