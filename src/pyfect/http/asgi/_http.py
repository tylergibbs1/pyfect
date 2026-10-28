"""An HTTP request over ASGI: the scope and ``http.request`` messages as a
``WebRequest``, the handler's ``WebResponse`` as ``http.response.*``
messages.

One task reads ``receive`` for the whole request. It buffers body chunks
until ``HIGH_WATER_MARK`` bytes wait unread, and an ``http.disconnect``
before the response is complete fires the request's signal, which
interrupts the app (a client abort) and stops a streamed body. While the
buffer is full nothing is read, so a disconnect is seen once the app reads
on.
"""

from __future__ import annotations

import asyncio
import re
from collections import deque
from collections.abc import AsyncIterator
from typing import Any

from pyfect.http.abort import AbortController
from pyfect.http.asgi import _scope
from pyfect.http.asgi._types import Message, Receive, Scope, Send
from pyfect.http.web import WebRequest, WebResponse
from pyfect.http.web_handler import WebHandler

HIGH_WATER_MARK = 64 * 1024


class ClientDisconnectedError(ConnectionError):
    """The client went away before the request body ended."""


class _Inbound:
    __slots__ = (
        "_changed",
        "_chunks",
        "_controller",
        "_ended",
        "_receive",
        "_room",
        "_size",
        "_task",
        "disconnected",
        "responded",
    )

    def __init__(self, receive: Receive, controller: AbortController) -> None:
        self._receive = receive
        self._controller = controller
        self._chunks: deque[bytes] = deque()
        self._size = 0
        self._ended = False
        self._changed = asyncio.Event()
        self._room = asyncio.Event()
        self._room.set()
        self.disconnected = False
        self.responded = False
        self._task = asyncio.get_running_loop().create_task(self._pump())

    async def _pump(self) -> None:
        while True:
            await self._room.wait()
            message = await self._receive()
            if message["type"] == "http.disconnect":
                self.disconnected = True
                self._changed.set()
                if not self.responded:
                    self._controller.abort()
                return
            if message["type"] != "http.request" or self._ended:
                continue
            chunk: bytes = message.get("body", b"")
            if chunk:
                self._chunks.append(chunk)
                self._size += len(chunk)
                if self._size >= HIGH_WATER_MARK:
                    self._room.clear()
            if not message.get("more_body", False):
                self._ended = True
            self._changed.set()

    async def chunks(self) -> AsyncIterator[bytes]:
        while True:
            if self._chunks:
                chunk = self._chunks.popleft()
                self._size -= len(chunk)
                if self._size < HIGH_WATER_MARK:
                    self._room.set()
                yield chunk
            elif self._ended:
                return
            elif self.disconnected:
                raise ClientDisconnectedError("the client disconnected")
            else:
                self._changed.clear()
                await self._changed.wait()

    def close(self) -> None:
        self._task.cancel()


def request_of(
    scope: Scope, body: AsyncIterator[bytes] | None, controller: AbortController
) -> WebRequest:
    lines = _scope.header_lines(scope)
    return WebRequest(
        _scope.url(scope, lines),
        method=scope.get("method", "GET"),
        headers=lines,
        body=body if _scope.has_body(scope, lines) else None,
        signal=controller.signal,
        remote_address=_scope.remote_address(scope),
    )


_TOKEN = re.compile(r"[!#$%&'*+\-.^_`|~0-9A-Za-z]+")
_FIELD_VALUE = re.compile(r"[^\x00\r\n]*")


class InvalidResponseHeaderError(ValueError):
    """A response header that cannot be sent (Node's ``writeHead`` throws)."""


def encode_headers(lines: tuple[tuple[str, str], ...]) -> list[tuple[bytes, bytes]]:
    """The header lines as ASGI sends them; an invalid one raises
    ``InvalidResponseHeaderError``."""
    encoded: list[tuple[bytes, bytes]] = []
    for name, value in lines:
        if not _TOKEN.fullmatch(name) or not _FIELD_VALUE.fullmatch(value):
            raise InvalidResponseHeaderError(f"Invalid response header: {name}")
        try:
            encoded.append((name.encode("latin-1"), value.encode("latin-1")))
        except UnicodeEncodeError as cause:
            raise InvalidResponseHeaderError(f"Invalid response header: {name}") from cause
    return encoded


async def _aclose(chunks: AsyncIterator[bytes]) -> None:
    close: Any = getattr(chunks, "aclose", None)
    if close is not None:
        await close()


async def send_response(send: Send, response: WebResponse, inbound: _Inbound) -> None:
    try:
        headers = encode_headers(response.header_lines)
    except InvalidResponseHeaderError:
        # Answered with a 500, then reported by the server.
        await send({"type": "http.response.start", "status": 500, "headers": []})
        inbound.responded = True
        await send({"type": "http.response.body", "body": b""})
        await _aclose(response.chunks())
        raise
    start: Message = {"type": "http.response.start", "status": response.status, "headers": headers}
    body = response.body
    if body is None or isinstance(body, bytes):
        await send(start)
        inbound.responded = True
        await send({"type": "http.response.body", "body": body or b""})
        return
    chunks = response.chunks()
    try:
        await send(start)
        async for chunk in chunks:
            if inbound.disconnected:
                return
            if chunk:
                await send({"type": "http.response.body", "body": chunk, "more_body": True})
        inbound.responded = True
        await send({"type": "http.response.body", "body": b""})
    finally:
        await _aclose(chunks)


async def serve_http(handler: WebHandler, scope: Scope, receive: Receive, send: Send) -> None:
    """Answer one ``http`` scope with ``handler``."""
    controller = AbortController()
    inbound = _Inbound(receive, controller)
    try:
        response = await handler(request_of(scope, inbound.chunks(), controller))
        await send_response(send, response, inbound)
    except asyncio.CancelledError:
        controller.abort()
        raise
    except OSError:
        # The server could not send: the client is gone.
        controller.abort()
    except Exception:
        # A body stopped because the client went away ends quietly.
        if not controller.signal.aborted:
            raise
    finally:
        inbound.close()
