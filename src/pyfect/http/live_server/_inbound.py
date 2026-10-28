"""The bytes a connection receives, read by one fiber at a time: request
heads, then body bytes, with what was read too far kept for the next
read."""

from __future__ import annotations

from collections.abc import Callable

from pyfect._core import Effect
from pyfect.effect import fail, succeed, suspend
from pyfect.socket._connection import Connection
from pyfect.socket._errors import SocketError, is_clean_close, read_error


class HeadTooLarge(Exception):
    """The head did not end within the limit."""


class Inbound:
    """``read`` gives ``b""`` once the peer ended the stream cleanly; a
    connection that failed fails the read."""

    __slots__ = ("_conn", "_ended", "_pending")

    def __init__(self, conn: Connection) -> None:
        self._conn = conn
        self._pending = bytearray()
        self._ended = False

    @property
    def has_pending(self) -> bool:
        return bool(self._pending)

    def take_pending(self) -> bytes:
        """What was received and not read yet (handed to an upgrade)."""
        data = bytes(self._pending)
        self._pending.clear()
        return data

    def _fill(self) -> Effect[bool, SocketError]:
        """Wait for more bytes; ``False`` at the end of the stream."""
        if self._ended:
            return succeed(False)

        def received(chunks: tuple[bytes, ...]) -> bool:
            for chunk in chunks:
                self._pending += chunk
            return True

        def ended(error: SocketError) -> Effect[bool, SocketError]:
            if not is_clean_close(error):
                return fail(error)
            self._ended = True
            return succeed(False)

        return self._conn.pull_into(received).catch_all(ended)

    def wait_data(self) -> Effect[None, SocketError]:
        """Wait until some bytes are received (or the stream ends)."""
        if self._pending or self._ended:
            return succeed(None)
        return self._fill().as_void()

    def read_head(self, limit: int) -> Effect[bytes | None, SocketError | HeadTooLarge]:
        """The next head without its blank line; ``None`` at a clean end
        before any of it. Blank lines before a head are skipped (RFC 9112
        §2.2)."""

        def step() -> Effect[bytes | None, SocketError | HeadTooLarge]:
            while self._pending.startswith(b"\r\n"):
                del self._pending[:2]
            end = self._pending.find(b"\r\n\r\n")
            if end != -1:
                if end > limit:
                    return fail(HeadTooLarge())
                head = bytes(self._pending[:end])
                del self._pending[: end + 4]
                return succeed(head)
            if len(self._pending) > limit:
                return fail(HeadTooLarge())
            return self._fill().flat_map(lambda more: suspend(step) if more else self._ended_head())

        return suspend(step)

    def _ended_head(self) -> Effect[bytes | None, SocketError]:
        if self._pending:
            return fail(read_error(ConnectionError("the connection ended within a head")))
        return succeed(None)

    def read[A, E](
        self, maximum: int, take: Callable[[bytes], Effect[A, E]]
    ) -> Effect[A, SocketError | E]:
        """``take`` of up to ``maximum`` bytes, waiting for some (``b""`` at
        the end); the bytes are taken and handed over in one step."""

        def step() -> Effect[A, SocketError | E]:
            if self._pending or self._ended:
                data = bytes(self._pending[:maximum])
                del self._pending[:maximum]
                return take(data)
            return self._fill().flat_map(lambda _: suspend(step))

        return suspend(step)

    def read_line[A, E](
        self, limit: int, take: Callable[[bytes | None], Effect[A, E]]
    ) -> Effect[A, SocketError | E]:
        """``take`` of the next line without its CRLF (``None`` at the end
        or past ``limit``), taken and handed over in one step."""

        def step() -> Effect[A, SocketError | E]:
            end = self._pending.find(b"\r\n")
            if end != -1:
                line = bytes(self._pending[:end])
                del self._pending[: end + 2]
                return take(line)
            if len(self._pending) > limit or self._ended:
                return take(None)
            return self._fill().flat_map(lambda _: suspend(step))

        return suspend(step)
