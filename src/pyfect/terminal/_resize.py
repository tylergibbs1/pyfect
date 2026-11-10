"""Terminal resizes for every subscriber in the process: Node's ``resize``
event on ``process.stdout``.

``SIGWINCH`` (POSIX, installed from the main thread) reports them; the
handler only puts a token in a ``SimpleQueue``, which is safe to call from a
signal handler, and a daemon thread tells the subscribers, so no fiber code
runs inside the handler. Where the signal cannot be installed (Windows, or
a first subscriber off the main thread) the thread polls the size, as
libuv does on Windows."""

from __future__ import annotations

import queue
import signal
import threading
from collections.abc import Callable
from types import FrameType
from typing import Any

_POLL_INTERVAL = 0.25
"""Seconds between size checks where there is no ``SIGWINCH``."""

type Listener = Callable[[], None]


class _Resizes:
    __slots__ = ("_installed", "_listeners", "_lock", "_pending", "_previous", "_thread")

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._listeners: dict[int, Listener] = {}
        self._pending: queue.SimpleQueue[None] = queue.SimpleQueue()
        self._thread: threading.Thread | None = None
        self._installed = False
        self._previous: Any = None

    def subscribe(self, listener: Listener, size: Callable[[], object]) -> Callable[[], None]:
        """Call ``listener`` (from another thread) after each resize, until
        the returned function is called. ``size`` reads the size when the
        resizes have to be found by polling."""
        key = id(listener)
        with self._lock:
            self._listeners[key] = listener
            if len(self._listeners) == 1:
                self._install()
            if self._thread is None:
                self._thread = threading.Thread(
                    target=self._dispatch, args=(size,), name="pyfect-terminal-resize", daemon=True
                )
                self._thread.start()

        def unsubscribe() -> None:
            with self._lock:
                if self._listeners.pop(key, None) is not None and not self._listeners:
                    self._uninstall()

        return unsubscribe

    def _install(self) -> None:
        winch = getattr(signal, "SIGWINCH", None)
        if winch is None or threading.current_thread() is not threading.main_thread():
            return
        self._previous = signal.signal(winch, self._on_signal)
        self._installed = True

    def _uninstall(self) -> None:
        if not self._installed or threading.current_thread() is not threading.main_thread():
            return
        signal.signal(signal.SIGWINCH, self._previous)
        self._installed = False
        self._previous = None

    def _on_signal(self, signum: int, frame: FrameType | None) -> None:
        self._pending.put(None)
        previous = self._previous
        if callable(previous):
            previous(signum, frame)

    def _dispatch(self, size: Callable[[], object]) -> None:
        last = size()
        while True:
            try:
                self._pending.get(timeout=_POLL_INTERVAL)
            except queue.Empty:
                current = size()
                if self._installed or current == last:
                    continue
                last = current
            with self._lock:
                listeners = list(self._listeners.values())
            for listener in listeners:
                listener()


resizes = _Resizes()
"""The process's terminal resizes."""
