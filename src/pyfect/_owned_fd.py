"""A descriptor (or a socket) that several threads use and one of them closes.

Once closed, a descriptor's number goes to the next ``open`` or ``socket``. Work
that took the number before the close and calls the system after it would reach
whatever took it. So work reaches the descriptor only inside ``use`` (or
``using``), and ``close_when_unused`` closes it at once when nothing uses it, or
else when the last use ends, on that use's thread. A use that begins after
``close_when_unused`` raises ``Closed`` (``EBADF``), as a call on a closed
descriptor does.

Nothing waits for the uses: as in Effect, closing a file does not wait for
the operations it abandoned. The descriptor's number just stays taken until
they end.
"""

from __future__ import annotations

import errno
import os
import threading
from collections.abc import Callable, Generator
from contextlib import contextmanager, suppress


class Closed(OSError):
    """The descriptor was closed, or is closing, before the use began."""

    def __init__(self) -> None:
        super().__init__(errno.EBADF, os.strerror(errno.EBADF))


class OwnedFd[R]:
    """``resource`` (a descriptor, a socket) closed by ``close`` once unused."""

    __slots__ = ("_close", "_closing", "_lock", "_resource", "_users")

    def __init__(self, resource: R, close: Callable[[R], object]) -> None:
        self._resource = resource
        self._close = close
        self._lock = threading.Lock()
        self._users = 0
        self._closing = False

    @property
    def closing(self) -> bool:
        """``close_when_unused`` was called."""
        with self._lock:
            return self._closing

    def use[A](self, work: Callable[[R], A]) -> A:
        """``work(resource)``, with the resource kept open until it returns."""
        with self.using() as resource:
            return work(resource)

    @contextmanager
    def using(self) -> Generator[R]:
        """The resource, kept open until the block ends."""
        with self._lock:
            if self._closing:
                raise Closed
            self._users += 1
        try:
            yield self._resource
        finally:
            with self._lock:
                self._users -= 1
                last = self._closing and self._users == 0
            if last:
                self._close_late()

    def close_when_unused(self) -> None:
        """Close now if nothing uses the resource, else once the last use
        ends. A close made now raises what ``close`` raises."""
        with self._lock:
            if self._closing:
                return
            self._closing = True
            unused = self._users == 0
        if unused:
            self._close(self._resource)

    def _close_late(self) -> None:
        # The close was asked for, and answered, before: nobody is left to
        # hear how it went, and the use's own result stands.
        with suppress(OSError):
            self._close(self._resource)
