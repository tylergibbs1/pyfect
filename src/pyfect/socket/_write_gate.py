"""Where a socket's writes wait while it has no connection (Effect's
``latch`` and ``terminalError`` in ``fromWebSocket`` and ``fromDuplex``)."""

from __future__ import annotations

from typing import Any

from pyfect._core import Effect
from pyfect.effect import fail, suspend, sync
from pyfect.latch import Latch
from pyfect.socket._errors import SocketError


class WriteGate:
    """Writes wait for the next reader's connection. A socket that cannot
    reconnect (``reconnects=False``: a connection a server accepted) ends
    for good with its first reader: from then on, writes and readers fail
    with that reader's error."""

    __slots__ = ("_latch", "_reconnects", "terminal")

    def __init__(self, *, reconnects: bool) -> None:
        self._latch = Latch(False)
        self._reconnects = reconnects
        self.terminal: SocketError | None = None

    def connected(self) -> None:
        self._latch.open_unsafe()

    def disconnected(self, error: SocketError) -> None:
        """The reader's connection is gone (its scope closed, or it failed)."""
        if self._reconnects:
            self._latch.close_unsafe()
            return
        if self.terminal is None:
            self.terminal = error
        self._latch.open_unsafe()

    def when_connected[A](self, retry: Effect[A, SocketError]) -> Effect[A, SocketError]:
        """``retry`` once a reader connects; the error a socket that cannot
        reconnect ended with."""
        terminal = self.terminal
        if terminal is not None:
            return fail(terminal)
        return self._latch.when_open(retry)

    def reader[A](self, connect: Effect[A, SocketError, Any]) -> Effect[A, SocketError, Any]:
        """``connect`` as the socket's reader: for a socket that cannot
        reconnect, its failure ends the socket, and a later reader fails
        with the error it ended with."""
        if self._reconnects:
            return connect

        def ended(error: SocketError) -> Effect[None]:
            return sync(lambda: self.disconnected(error))

        def start() -> Effect[A, SocketError, Any]:
            terminal = self.terminal
            if terminal is not None:
                return fail(terminal)
            return connect.tap_error(ended)

        return suspend(start)
