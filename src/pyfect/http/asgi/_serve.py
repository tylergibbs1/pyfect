"""Requests of an ASGI connection (``http`` and ``websocket`` scopes)
answered by an app, each on its own fiber."""

from __future__ import annotations

from typing import Any

from pyfect._core import Effect
from pyfect.context import Context
from pyfect.http.abort import AbortController
from pyfect.http.asgi._http import serve_http
from pyfect.http.asgi._types import Receive, Scope, Send
from pyfect.http.asgi._web_socket import serve_websocket
from pyfect.http.http_effect import HttpMiddleware
from pyfect.http.server_response import HttpServerResponse
from pyfect.http.web_handler import Fork, to_web_handler_with


class UnsupportedScopeError(RuntimeError):
    """An ASGI scope type the app does not serve."""


class AsgiHandler:
    """An ASGI app answering ``http`` and ``websocket`` scopes with
    ``app``: ``fork`` starts each request's fiber with ``context`` and the
    request."""

    __slots__ = ("_app", "_context", "_fork", "_middleware", "_open", "_web")

    def __init__(
        self,
        app: Effect[HttpServerResponse, Any, Any],
        middleware: HttpMiddleware | None,
        context: Context[Any],
        fork: Fork,
    ) -> None:
        self._app = app
        self._middleware = middleware
        self._context = context
        self._fork = fork
        self._web = to_web_handler_with(context, fork=fork)(app, middleware)
        self._open: set[AbortController] = set()

    def end_responses(self) -> None:
        """Abort every ``http`` request in flight, on the server's loop: a
        handler still running is interrupted, and a streamed body ends where
        it is. A server calls it once ``graceful_shutdown_timeout`` has
        passed, so an endless body (SSE) cannot hold its shutdown open."""
        for controller in tuple(self._open):
            controller.abort()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        match scope["type"]:
            case "http":
                controller = AbortController()
                self._open.add(controller)
                try:
                    await serve_http(self._web, scope, receive, send, controller)
                finally:
                    self._open.discard(controller)
            case "websocket":
                await serve_websocket(
                    scope,
                    receive,
                    send,
                    app=self._app,
                    middleware=self._middleware,
                    context=self._context,
                    fork=self._fork,
                )
            case other:
                raise UnsupportedScopeError(f"unsupported ASGI scope type: {other!r}")
