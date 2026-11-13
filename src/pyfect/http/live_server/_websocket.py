"""A WebSocket upgrade on the live server (Effect's ``NodeHttpServer``
handing ``Upgrade: websocket`` requests to ``ws``'s ``handleUpgrade``).

Acquiring the socket's reader checks the handshake as ``ws`` does (a bad
one is answered with ``ws``'s 400 or 405 and fails the reader as a socket
closed before the upgrade), sends the ``101`` with ``Sec-WebSocket-Accept``
(the client's first subprotocol, and the accepted ``permessage-deflate`` offer
when the server takes them), then speaks RFC 6455: pulls give
the client's messages (text as ``str``), pings are answered, and the
client's close is answered and fails the pull with its code (1006 when the
connection ends without one). As ``ws`` does, the connection is read while
nothing pulls, so pings and the client's close are answered then too; Effect
pauses ``ws`` once 64 KiB of messages wait for a pull, and so does this. The
reader's scope closes the WebSocket with the handler's code (1000, 1001 when
interrupted, 1011 on failure) unless a close was already sent. Writes wait
for the reader to open the socket; a ``CloseEvent`` sends a close frame, and
writes after a close are dropped,
as ``ws`` drops them."""

from __future__ import annotations

import threading
from collections import deque
from collections.abc import Sequence
from typing import Never

from pyfect._core import Effect
from pyfect._js import text_encode
from pyfect.duration import seconds
from pyfect.effect import fail, succeed, suspend, sync, void
from pyfect.exit import Exit
from pyfect.http._field import is_token
from pyfect.http.live_server._exchange import Exchange, encode_fields
from pyfect.http.live_server._timers import timeout_option
from pyfect.http.live_server._ws_deflate import Negotiated, WebSocketConfig, negotiate
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
from pyfect.scope import Scope, acquire_release, fork_scoped
from pyfect.socket._connection import HIGH_WATER_MARK, Signal
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
_CLOSE_TIMEOUT = seconds(30)


class _Refused(Exception):
    def __init__(self, status: int, phrase: str, message: str, *extra: tuple[str, str]) -> None:
        super().__init__(message)
        self.status = status
        self.phrase = phrase
        self.extra = extra

    def response(self) -> bytes:
        body = text_encode(str(self))
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


def _switching_head(
    exchange: Exchange, websocket: WebSocketConfig
) -> tuple[bytes, Negotiated | None]:
    """The ``101`` and the ``permessage-deflate`` parameters it accepted, or ``_Refused``
    for a handshake ``ws`` refuses."""
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
    negotiated = None
    offered = headers.get("sec-websocket-extensions")
    if websocket.per_message_deflate is not None and offered is not None:
        try:
            negotiated = negotiate(
                websocket.per_message_deflate, offered, websocket.max_message_size
            )
        except ValueError:
            raise _Refused(
                400, "Bad Request", "Invalid or unacceptable Sec-WebSocket-Extensions header"
            ) from None
    fields = [
        ("Upgrade", "websocket"),
        ("Connection", "Upgrade"),
        ("Sec-WebSocket-Accept", accept_key(key)),
    ]
    if protocols:
        fields.append(("Sec-WebSocket-Protocol", protocols[0]))
    if negotiated is not None:
        fields.append(("Sec-WebSocket-Extensions", negotiated.header()))
    return encode_fields("HTTP/1.1 101 Switching Protocols", fields), negotiated


def _byte_length(data: Chunk) -> int:
    return len(text_encode(data)) if isinstance(data, str) else len(data)


def _closed_before_upgrade() -> SocketError:
    return open_error(ConnectionError("The socket closed before the upgrade"))


class _Session:
    """One upgraded connection: what ``read`` parsed and has yet to hand
    over or answer, and whether a close frame was sent. ``read`` runs on its
    own fiber for as long as the reader's scope is open; ``pull`` takes what
    it parsed."""

    __slots__ = (
        "_deflater",
        "_end_writing",
        "_error",
        "_incoming",
        "_leftover",
        "_lock",
        "_parser",
        "_pull_error",
        "_ready",
        "_ready_size",
        "_replies",
        "_signal",
        "close_sent",
        "exchange",
    )

    def __init__(
        self, exchange: Exchange, max_message_size: int, negotiated: Negotiated | None
    ) -> None:
        self.exchange = exchange
        inflater = None if negotiated is None else negotiated.inflater()
        self._parser = FrameParser(max_message_size, inflater)
        self._deflater = None if negotiated is None else negotiated.deflater()
        self._leftover = exchange.take_pending()
        self._lock = threading.Lock()
        self._signal = Signal(self._lock)
        self._incoming: list[Chunk] = []
        self._ready: deque[Chunk] = deque()
        self._ready_size = 0
        self._pull_error: SocketError | None = None
        self._replies: list[bytes] = []
        self._end_writing = False
        self._error: SocketError | None = None
        self.close_sent = False

    def claim_close(self) -> bool:
        """Whether this call is the one that sends the close frame."""
        with self._lock:
            return self._claim_close_locked()

    def _claim_close_locked(self) -> bool:
        if self.close_sent:
            return False
        self.close_sent = True
        return True

    # --- reading ------------------------------------------------------------------

    # ``read`` parses into ``_incoming`` and ``_error``, writes the replies
    # (pongs, the close) and only then hands the messages and the error to
    # ``pull``, so a pong goes out before anything sent after the ping is
    # answered, as ``ws`` answers frames in the order they come.

    def _feed(self, chunks: Sequence[bytes]) -> None:
        with self._lock:
            for chunk in chunks:
                if not self._feed_locked(chunk):
                    break

    def _feed_locked(self, chunk: bytes) -> bool:
        """Parse ``chunk``; ``False`` once the connection has failed."""
        try:
            events = self._parser.feed(chunk)
        except ProtocolError as error:
            self._error = read_error(error)
            if self._claim_close_locked():
                # ``ws`` closes with the code alone (``receiverOnError``).
                self._replies.append(encode_close(error.code))
            self._end_writing = True
            return False
        for event in events:
            match event:
                case Message(data):
                    self._incoming.append(data)
                case Ping(payload):
                    if not self.close_sent:
                        self._replies.append(encode_frame(Opcode.PONG, payload))
                case Close(code, reason):
                    self._error = close_error(code, reason)
                    if self._claim_close_locked():
                        self._replies.append(encode_close(None if code == 1005 else code, reason))
                    self._end_writing = True
        return True

    def _lost(self, _: SocketError) -> Effect[None]:
        with self._lock:
            if self._error is None:
                self._error = close_error(1006)
        return void

    def _take_replies(self) -> tuple[bytes, ...]:
        """Called on the loop as the replies are written, so an interrupted
        ``read`` leaves those it did not write to ``flush``."""
        with self._lock:
            replies = tuple(self._replies)
            self._replies.clear()
        return replies

    def flush(self) -> Effect[None]:
        """Write the replies not written yet, and end the writing side after
        a close was answered."""
        conn = self.exchange.conn
        with self._lock:
            pending = bool(self._replies)
            end_writing, self._end_writing = self._end_writing, False
        written = conn.write_with(self._take_replies).catch_all(self._lost) if pending else void
        return written.flat_map(lambda _: sync(conn.end_writing) if end_writing else void)

    def _publish(self) -> bool:
        """Hand what was parsed to ``pull``; whether reading has ended."""
        with self._lock:
            if self._incoming:
                self._ready.extend(self._incoming)
                self._ready_size += sum(map(_byte_length, self._incoming))
                self._incoming.clear()
            self._pull_error = self._error
            ended = self._error is not None
            waiters = self._signal.notify_locked()
        for wake in waiters:
            wake()
        return ended

    def _room(self) -> bool:
        return self._ready_size < HIGH_WATER_MARK

    def read(self) -> Effect[None]:
        """Read and parse the connection, answering pings and the client's
        close, until it ends; paused while ``HIGH_WATER_MARK`` bytes of
        messages wait for ``pull``."""
        conn = self.exchange.conn

        def step() -> Effect[None]:
            if self._leftover:
                leftover, self._leftover = self._leftover, b""
                self._feed((leftover,))
            return self.flush().flat_map(after_flush)

        def after_flush(_: None) -> Effect[None]:
            if self._publish():
                return self._close_connection()
            if not self._room():
                return self._signal.wait(self._room).flat_map(lambda _: suspend(step))
            return (
                conn.pull_into(self._feed).catch_all(self._lost).flat_map(lambda _: suspend(step))
            )

        return suspend(step)

    def _close_connection(self) -> Effect[None]:
        """Once the close is answered (or the connection lost): close the
        connection when the client ends its side, as Node closes a socket
        both sides ended, or after ``ws``'s ``closeTimeout`` if it does not."""
        conn = self.exchange.conn
        ended = timeout_option(conn.read_ended(), _CLOSE_TIMEOUT)
        return ended.flat_map(lambda _: sync(lambda: conn.close(graceful=True)))

    def _readable(self) -> bool:
        return bool(self._ready) or self._pull_error is not None

    def pull(self) -> Effect[tuple[Chunk, ...], SocketError]:
        """The messages ``read`` parsed, waiting for some; the close's error
        once they are taken."""

        def step() -> Effect[tuple[Chunk, ...], SocketError]:
            with self._lock:
                if self._ready:
                    ready = tuple(self._ready)
                    self._ready.clear()
                    self._ready_size = 0
                    waiters = self._signal.notify_locked()
                else:
                    ready, waiters = None, []
                error = self._pull_error
            for wake in waiters:
                wake()
            if ready is not None:
                return succeed(ready)
            if error is not None:
                return fail(error)
            return self._signal.wait(self._readable).flat_map(lambda _: suspend(step))

        return suspend(step)

    # --- writing --------------------------------------------------------------------

    def _send(self, frames: tuple[bytes, ...]) -> Effect[None, SocketError]:
        # As ``ws``: a send on a closed connection is dropped, not raised;
        # the reader sees the connection end.
        return self.exchange.conn.write(frames).catch_all(lambda _: void)

    def _send_messages(self, chunks: Sequence[Chunk]) -> Effect[None, SocketError]:
        deflater = self._deflater
        if deflater is None:
            return self._send(tuple(map(encode_message, chunks)))

        def encode(chunk: Chunk) -> bytes:
            text = isinstance(chunk, str)
            data = text_encode(chunk) if isinstance(chunk, str) else chunk
            opcode = Opcode.TEXT if text else Opcode.BINARY
            compressed = deflater.compress(data)
            if compressed is None:
                return encode_frame(opcode, data)
            return encode_frame(opcode, compressed, compressed=True)

        # Compressed on the loop, in write order, as the shared context requires.
        written = self.exchange.conn.write_with(lambda: tuple(map(encode, chunks)))
        return written.catch_all(lambda _: void)

    def write(self, chunk: Chunk | CloseEvent) -> Effect[None, SocketError]:
        if not isinstance(chunk, CloseEvent):
            return void if self.close_sent else self._send_messages((chunk,))
        reason = chunk.reason or ""
        if not is_valid_close_code(chunk.code):
            return fail(write_error(TypeError("First argument must be a valid error code number")))
        if len(text_encode(reason)) > 123:
            return fail(write_error(ValueError("The message must not be greater than 123 bytes")))
        if not self.claim_close():
            return void
        return self._send((encode_close(chunk.code, reason),))

    def write_all(self, chunks: Sequence[Chunk]) -> Effect[None, SocketError]:
        if self.close_sent:
            return void
        return self._send_messages(chunks)

    def close(self, exit: Exit[object, object]) -> Effect[None]:
        """After ``read`` has stopped: the replies it left, then the
        handler's close unless one was sent."""

        def send_close(_: None) -> Effect[None]:
            if not self.claim_close():
                return void
            return self._send((encode_close(close_code(exit)),)).catch_all(lambda _: void)

        return self.flush().flat_map(send_close)


def web_socket(exchange: Exchange, websocket: WebSocketConfig) -> SocketService:
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
            head, negotiated = _switching_head(exchange, websocket)
        except _Refused as refused:
            written = conn.write((refused.response(),)).catch_all(lambda _: void)
            return written.flat_map(lambda _: sync(conn.end_writing)).flat_map(
                lambda _: fail(_closed_before_upgrade())
            )
        exchange.upgraded = _SWITCHED
        session = _Session(exchange, websocket.max_message_size, negotiated)
        return conn.write((head,)).map_error(lambda _: _closed_before_upgrade()).as_(session)

    def release(session: _Session, exit: Exit[object, object]) -> Effect[None]:
        opened.close_unsafe()
        current.clear()
        return session.close(exit)

    def open_reader(session: _Session) -> Effect[Reader, Never, Scope]:
        current.append(session)
        opened.open_unsafe()
        return fork_scoped(session.read()).as_(Reader(session.pull()))

    reader = acquire_release(suspend(handshake), release).flat_map(open_reader)

    def write(chunk: Chunk | CloseEvent) -> Effect[None, SocketError]:
        return opened.when_open(suspend(lambda: current[0].write(chunk)))

    def write_all(chunks: Sequence[Chunk]) -> Effect[None, SocketError]:
        return opened.when_open(suspend(lambda: current[0].write_all(chunks)))

    writer: Effect[Writer, Never, Scope] = succeed(Writer(write, write_all))
    return make(reader, writer)
