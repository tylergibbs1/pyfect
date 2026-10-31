"""A WebSocket upgrade on the live server (Effect's ``NodeHttpServer``
handing ``Upgrade: websocket`` requests to ``ws``'s ``handleUpgrade``).

Acquiring the socket's reader checks the handshake as ``ws`` does (a bad
one is answered with ``ws``'s 400 or 405 and fails the reader as a socket
closed before the upgrade), sends the ``101`` with ``Sec-WebSocket-Accept``
(and the client's first subprotocol), then speaks RFC 6455: pulls give
the client's messages (text as ``str``), pings are answered, and the
client's close is answered and fails the pull with its code (1006 when the
connection ends without one). The reader's scope closes the WebSocket with
the handler's code (1000, 1001 when interrupted, 1011 on failure) unless a
close was already sent. Writes wait for the reader to open the socket; a
``CloseEvent`` sends a close frame, and writes after a close are dropped,
as ``ws`` drops them."""

from __future__ import annotations

import threading
from collections import deque
from collections.abc import Sequence
from typing import Never

from pyfect._core import Effect
from pyfect.effect import fail, succeed, suspend, sync, void
from pyfect.exit import Exit
from pyfect.http._field import is_token
from pyfect.http.live_server._exchange import Exchange, encode_fields
from pyfect.http.live_server._ws_frames import (
    Close,
    FrameParser,
    Message,
    Opcode,
    Ping,
    ProtocolError,
    accept_key,
    encode_close,
    encode_frame,
    encode_message,
    is_valid_close_code,
    is_valid_key,
)
from pyfect.http.server_response import empty
from pyfect.latch import Latch
from pyfect.scope import Scope, acquire_release
from pyfect.socket._errors import (
    CloseEvent,
    SocketError,
    close_error,
    open_error,
    read_error,
    write_error,
)
from pyfect.socket._socket import Chunk, Reader, SocketService, Writer, make
from pyfect.socket._web_socket import close_code

_SWITCHED = empty(status=101)


class _Refused(Exception):
    def __init__(self, status: int, phrase: str, message: str, *extra: tuple[str, str]) -> None:
        super().__init__(message)
        self.status = status
        self.phrase = phrase
        self.extra = extra

    def response(self) -> bytes:
        body = str(self).encode()
        fields = [
            ("Connection", "close"),
            ("Content-Type", "text/html"),
            ("Content-Length", str(len(body))),
            *self.extra,
        ]
        return encode_fields(f"HTTP/1.1 {self.status} {self.phrase}", fields) + body


def _subprotocols(value: str | None) -> list[str]:
    if value is None:
        return []
    protocols = [part.strip(" \t") for part in value.split(",")]
    if not all(map(is_token, protocols)) or any(
        p in protocols[:i] for i, p in enumerate(protocols)
    ):
        raise _Refused(400, "Bad Request", "Invalid Sec-WebSocket-Protocol header")
    return protocols


def _switching_head(exchange: Exchange) -> bytes:
    """The ``101``, or ``_Refused`` for a handshake ``ws`` refuses."""
    head = exchange.head
    headers = head.headers
    if head.method != "GET":
        raise _Refused(405, "Method Not Allowed", "Invalid HTTP method")
    key = headers.get("sec-websocket-key")
    if key is None or not is_valid_key(key):
        raise _Refused(400, "Bad Request", "Missing or invalid Sec-WebSocket-Key header")
    if headers.get("sec-websocket-version") not in ("13", "8"):
        raise _Refused(
            400,
            "Bad Request",
            "Missing or invalid Sec-WebSocket-Version header",
            ("Sec-WebSocket-Version", "13, 8"),
        )
    protocols = _subprotocols(headers.get("sec-websocket-protocol"))
    fields = [
        ("Upgrade", "websocket"),
        ("Connection", "Upgrade"),
        ("Sec-WebSocket-Accept", accept_key(key)),
    ]
    if protocols:
        fields.append(("Sec-WebSocket-Protocol", protocols[0]))
    return encode_fields("HTTP/1.1 101 Switching Protocols", fields)


def _closed_before_upgrade() -> SocketError:
    return open_error(ConnectionError("The socket closed before the upgrade"))


class _Session:
    """One upgraded connection: what the reader parsed and has yet to hand
    over or answer, and whether a close frame was sent."""

    __slots__ = (
        "_end_writing",
        "_error",
        "_leftover",
        "_lock",
        "_parser",
        "_ready",
        "_replies",
        "close_sent",
        "exchange",
    )

    def __init__(self, exchange: Exchange, max_message_size: int) -> None:
        self.exchange = exchange
        self._parser = FrameParser(max_message_size)
        self._leftover = exchange.take_pending()
        self._lock = threading.Lock()
        self._ready: deque[Chunk] = deque()
        self._replies: list[bytes] = []
        self._end_writing = False
        self._error: SocketError | None = None
        self.close_sent = False

    def claim_close(self) -> bool:
        """Whether this call is the one that sends the close frame."""
        with self._lock:
            if self.close_sent:
                return False
            self.close_sent = True
            return True

    # --- reading ------------------------------------------------------------------

    def _feed(self, chunks: Sequence[bytes]) -> None:
        for chunk in chunks:
            try:
                events = self._parser.feed(chunk)
            except ProtocolError as error:
                self._error = read_error(error)
                if self.claim_close():
                    # ``ws`` closes with the code alone (``receiverOnError``).
                    self._replies.append(encode_close(error.code))
                self._end_writing = True
                return
            for event in events:
                match event:
                    case Message(data):
                        self._ready.append(data)
                    case Ping(payload):
                        if not self.close_sent:
                            self._replies.append(encode_frame(Opcode.PONG, payload))
                    case Close(code, reason):
                        self._error = close_error(code, reason)
                        if self.claim_close():
                            self._replies.append(
                                encode_close(None if code == 1005 else code, reason)
                            )
                        self._end_writing = True

    def _lost(self, _: SocketError) -> Effect[None]:
        if self._error is None:
            self._error = close_error(1006)
        return void

    def pull(self) -> Effect[tuple[Chunk, ...], SocketError]:
        conn = self.exchange.conn

        def step() -> Effect[tuple[Chunk, ...], SocketError]:
            if self._replies:
                replies = tuple(self._replies)
                self._replies.clear()
                return conn.write(replies).catch_all(self._lost).flat_map(lambda _: suspend(step))
            if self._end_writing:
                self._end_writing = False
                conn.end_writing()
            if self._ready:
                ready = tuple(self._ready)
                self._ready.clear()
                return succeed(ready)
            if self._error is not None:
                return fail(self._error)
            if self._leftover:
                leftover, self._leftover = self._leftover, b""
                self._feed((leftover,))
                return suspend(step)
            return (
                conn.pull_into(self._feed).catch_all(self._lost).flat_map(lambda _: suspend(step))
            )

        return suspend(step)

    # --- writing --------------------------------------------------------------------

    def _send(self, frames: tuple[bytes, ...]) -> Effect[None, SocketError]:
        # As ``ws``: a send on a closed connection is dropped, not raised;
        # the reader sees the connection end.
        return self.exchange.conn.write(frames).catch_all(lambda _: void)

    def write(self, chunk: Chunk | CloseEvent) -> Effect[None, SocketError]:
        if not isinstance(chunk, CloseEvent):
            return void if self.close_sent else self._send((encode_message(chunk),))
        reason = chunk.reason or ""
        if not is_valid_close_code(chunk.code):
            return fail(write_error(TypeError("First argument must be a valid error code number")))
        if len(reason.encode()) > 123:
            return fail(write_error(ValueError("The message must not be greater than 123 bytes")))
        if not self.claim_close():
            return void
        return self._send((encode_close(chunk.code, reason),))

    def write_all(self, chunks: Sequence[Chunk]) -> Effect[None, SocketError]:
        if self.close_sent:
            return void
        return self._send(tuple(map(encode_message, chunks)))

    def close(self, exit: Exit[object, object]) -> Effect[None]:
        if not self.claim_close():
            return void
        return self._send((encode_close(close_code(exit)),)).catch_all(lambda _: void)


def web_socket(exchange: Exchange, max_message_size: int) -> SocketService:
    """The socket of a WebSocket upgrade request."""
    opened = Latch(False)
    current: list[_Session] = []

    def handshake() -> Effect[_Session, SocketError]:
        conn = exchange.conn
        if exchange.upgraded is not None or exchange.headers_sent:
            return fail(_closed_before_upgrade())
        exchange.headers_sent = True
        exchange.close_after = True
        try:
            head = _switching_head(exchange)
        except _Refused as refused:
            written = conn.write((refused.response(),)).catch_all(lambda _: void)
            return written.flat_map(lambda _: sync(conn.end_writing)).flat_map(
                lambda _: fail(_closed_before_upgrade())
            )
        exchange.upgraded = _SWITCHED
        session = _Session(exchange, max_message_size)
        return conn.write((head,)).map_error(lambda _: _closed_before_upgrade()).as_(session)

    def release(session: _Session, exit: Exit[object, object]) -> Effect[None]:
        opened.close_unsafe()
        current.clear()
        return session.close(exit)

    def open_reader(session: _Session) -> Reader:
        current.append(session)
        opened.open_unsafe()
        return Reader(session.pull())

    reader = acquire_release(suspend(handshake), release).map(open_reader)

    def write(chunk: Chunk | CloseEvent) -> Effect[None, SocketError]:
        return opened.when_open(suspend(lambda: current[0].write(chunk)))

    def write_all(chunks: Sequence[Chunk]) -> Effect[None, SocketError]:
        return opened.when_open(suspend(lambda: current[0].write_all(chunks)))

    writer: Effect[Writer, Never, Scope] = succeed(Writer(write, write_all))
    return make(reader, writer)
