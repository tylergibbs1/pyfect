"""Aborting a request in flight (the ``AbortController`` / ``AbortSignal``
pair Effect's clients use).

A client backend gets the request's ``AbortSignal`` and listens on it: the
signal fires when the request is interrupted, when an unread response is
garbage collected, when its stream ends or when its ``with_scope`` scope
closes. Listeners run once, on the thread that aborts.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import final


def _noop() -> None:
    return None


@final
class AbortSignal:
    __slots__ = ("_listeners", "_lock", "aborted")

    def __init__(self) -> None:
        self.aborted = False
        self._listeners: list[Callable[[], object]] = []
        self._lock = threading.Lock()

    def add_listener(self, listener: Callable[[], object]) -> Callable[[], object]:
        """Run ``listener`` on abort (now, if aborted already); returns a
        function that removes it."""
        with self._lock:
            if not self.aborted:
                self._listeners.append(listener)
                return lambda: self._remove(listener)
        listener()
        return _noop

    def _remove(self, listener: Callable[[], object]) -> None:
        with self._lock:
            if listener in self._listeners:
                self._listeners.remove(listener)


@final
class AbortController:
    __slots__ = ("signal",)

    def __init__(self) -> None:
        self.signal = AbortSignal()

    def abort(self) -> None:
        """Fire the signal; later calls do nothing."""
        signal = self.signal
        with signal._lock:  # pyright: ignore[reportPrivateUsage]
            if signal.aborted:
                return
            signal.aborted = True
            listeners, signal._listeners = signal._listeners, []  # pyright: ignore[reportPrivateUsage]
        for listener in listeners:
            listener()


__all__ = ["AbortController", "AbortSignal"]
