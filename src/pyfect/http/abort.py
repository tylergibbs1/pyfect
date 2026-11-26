"""Aborting a request in flight (the ``AbortController`` / ``AbortSignal``
pair Effect's clients use).

A client backend gets the request's ``AbortSignal`` and listens on it: the
signal fires when the request is interrupted, when an unread response is
garbage collected, when its stream ends or when its ``with_scope`` scope
closes.

Listeners behave as a WHATWG ``AbortSignal``'s ``"abort"`` listeners: each
runs once, on the thread that aborts, in the order added. One that raises is
logged (on the ``pyfect.http.abort`` logger) and the rest still run; one
removed before its turn, or added once the abort started, does not run. A
backend that may get an aborted signal uses ``on_abort``, which also runs
the listener when the signal has already fired.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from typing import final

_log = logging.getLogger(__name__)


@final
class _Entry:
    __slots__ = ("listener", "removed")

    def __init__(self, listener: Callable[[], object]) -> None:
        self.listener = listener
        self.removed = False


@final
class AbortSignal:
    """Tells whether a request was aborted, and runs listeners when it is."""

    __slots__ = ("_listeners", "_lock", "aborted")

    def __init__(self) -> None:
        self.aborted = False
        self._listeners: list[_Entry] = []
        self._lock = threading.Lock()

    def add_listener(self, listener: Callable[[], object]) -> Callable[[], None]:
        """Run ``listener`` when the signal aborts (WHATWG ``addEventListener("abort",
        listener, {once: true})``): never if it has aborted already, once if the same
        listener is added again. Returns a function that removes it."""
        return self._add(listener) or _noop

    def on_abort(self, listener: Callable[[], object]) -> Callable[[], None]:
        """Run ``listener`` when the signal aborts, or now if it has: Effect's
        ``if (signal.aborted) f() else signal.addEventListener("abort", f)``, with
        no abort lost between the check and the add. Returns a function that
        removes it."""
        remove = self._add(listener)
        if remove is None:
            listener()
            return _noop
        return remove

    def _add(self, listener: Callable[[], object]) -> Callable[[], None] | None:
        with self._lock:
            if self.aborted:
                return None
            entry = next((e for e in self._listeners if e.listener == listener), None)
            if entry is None:
                entry = _Entry(listener)
                self._listeners.append(entry)
        return lambda: self._remove(entry)

    def _remove(self, entry: _Entry) -> None:
        with self._lock:
            entry.removed = True
            if entry in self._listeners:
                self._listeners.remove(entry)

    def _fire(self) -> None:
        with self._lock:
            if self.aborted:
                return
            self.aborted = True
            entries, self._listeners = self._listeners, []
        for entry in entries:
            with self._lock:
                if entry.removed:
                    continue
                entry.removed = True
            try:
                entry.listener()
            except Exception:
                _log.exception("an abort listener raised: %r", entry.listener)


def _noop() -> None:
    return None


@final
class AbortController:
    """Aborts a request in flight through its ``signal``."""

    __slots__ = ("signal",)

    def __init__(self) -> None:
        self.signal = AbortSignal()

    def abort(self) -> None:
        """Fire the signal, running every listener (one that raises is logged);
        later calls do nothing."""
        self.signal._fire()  # pyright: ignore[reportPrivateUsage]


__all__ = ["AbortController", "AbortSignal"]
