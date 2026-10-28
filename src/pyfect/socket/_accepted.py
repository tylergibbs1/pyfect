"""Connections a server accepted that no ``run`` has taken yet."""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Never, Protocol

from pyfect._core import Effect
from pyfect.socket._connection import Signal
from pyfect.socket._socket import SocketService

type Handler[E, R] = Callable[[SocketService], Effect[object, E, R]]


class Incoming(Protocol):
    """An accepted connection: ``handle`` runs the handler on its socket;
    ``release`` closes it once the handler's fiber is done (gracefully);
    ``abort`` closes it at once."""

    def handle[E, R](self, handler: Handler[E, R]) -> Effect[None, Never, R]: ...

    def release(self) -> None: ...

    def abort(self) -> None: ...


class Accepted:
    """Connections the server accepted that no run has taken yet. Once
    closed (with the server), a connection made late is aborted."""

    __slots__ = ("_closed", "_pending", "lock", "signal")

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.signal = Signal(self.lock)
        self._pending: list[Incoming] = []
        self._closed = False

    def add(self, incoming: Incoming) -> None:
        with self.lock:
            closed = self._closed
            if not closed:
                self._pending.append(incoming)
            waiters = self.signal.notify_locked()
        if closed:
            incoming.abort()
        for wake in waiters:
            wake()

    def has_pending(self) -> bool:
        return bool(self._pending)

    def take(self) -> list[Incoming]:
        with self.lock:
            taken, self._pending = self._pending, []
        return taken

    def close(self) -> None:
        """Abort the pending connections and every later one."""
        with self.lock:
            self._closed = True
            taken, self._pending = self._pending, []
        for incoming in taken:
            incoming.abort()
