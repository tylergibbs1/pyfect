"""The listeners of a WebSocket whose events come from another thread.

A browser dispatches a WebSocket's events in tasks after the one that made
it, so listeners attached in that task hear every event. Here the socket
loop runs beside the code that attaches them, so an ``EventTarget`` keeps
what it dispatches until the first listeners are added, then delivers it
in order. ``add_event_listeners`` adds several at once, so no event falls
between them. Events are delivered one at a time, in dispatch order, on
whichever thread dispatched or added while none was being delivered.
"""

from __future__ import annotations

import threading
from collections import deque
from collections.abc import Callable, Iterable

from pyfect.socket._web_socket import Listener, WebSocketEvent, WebSocketEventType

type ListenerEntry = tuple[WebSocketEventType, Listener, bool]
"""A listener for one event type, and whether it is removed after one call."""


class EventTarget:
    """``add_event_listener`` and ``remove_event_listener`` of a
    ``WebSocketLike``; its owner calls ``dispatch``. ``report`` gets what a
    listener raises."""

    __slots__ = ("_delivering", "_heard", "_listeners", "_lock", "_queue", "_report")

    def __init__(self, report: Callable[[Exception], None]) -> None:
        self._report = report
        self._lock = threading.Lock()
        self._listeners: dict[WebSocketEventType, list[tuple[Listener, bool]]] = {}
        self._queue: deque[tuple[WebSocketEventType, WebSocketEvent]] = deque()
        self._heard = False
        self._delivering = False

    def add_event_listener(
        self, type: WebSocketEventType, listener: Listener, *, once: bool = False
    ) -> None:
        self.add_event_listeners(((type, listener, once),))

    def add_event_listeners(self, entries: Iterable[ListenerEntry]) -> None:
        """Add every listener before any of them hears an event."""
        with self._lock:
            for type, listener, once in entries:
                listeners = self._listeners.setdefault(type, [])
                if all(entry is not listener for entry, _ in listeners):
                    listeners.append((listener, once))
            self._heard = True
        self._deliver()

    def remove_event_listener(self, type: WebSocketEventType, listener: Listener) -> None:
        with self._lock:
            listeners = self._listeners.get(type, [])
            listeners[:] = [(entry, once) for entry, once in listeners if entry is not listener]

    def dispatch(self, type: WebSocketEventType, event: WebSocketEvent) -> None:
        with self._lock:
            self._queue.append((type, event))
        self._deliver()

    def _deliver(self) -> None:
        # One deliverer at a time keeps the order; the others leave their
        # events to it, as does a listener that dispatches.
        while True:
            with self._lock:
                if self._delivering or not self._heard or not self._queue:
                    return
                type, event = self._queue.popleft()
                listeners = self._listeners.get(type, [])
                called = [listener for listener, _ in listeners]
                listeners[:] = [(listener, once) for listener, once in listeners if not once]
                self._delivering = True
            try:
                for listener in called:
                    try:
                        listener(event)
                    except Exception as error:
                        self._report(error)
            finally:
                with self._lock:
                    self._delivering = False
