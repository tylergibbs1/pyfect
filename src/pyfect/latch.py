"""``Latch``: a gate fibers wait at until it opens.

``open()`` lets every waiter through and keeps the gate open; ``release()``
lets the current waiters through but leaves it closed; ``close()`` makes
later ``wait()`` calls park again. ``open`` and ``release`` wake waiters in
one task scheduled on the calling fiber's scheduler, as Effect's latch does,
so several releases before that task runs share it. Waiters of runs on other
threads are woken through their own runs at once.
"""
# pyright: reportPrivateUsage=false

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from pyfect._core import Effect, _Callback, _Succeed, _Sync, _WithFiber
from pyfect._effect_args import require_effect
from pyfect._fiber import current_fiber
from pyfect._waiters import of_this_run

if TYPE_CHECKING:
    from pyfect._fiber import Fiber

type _Resume = Callable[[Effect[None]], None]

_TRUE: Effect[bool] = _Succeed(True)
_FALSE: Effect[bool] = _Succeed(False)
_VOID: Effect[None] = _Succeed(None)


class Latch:
    __slots__ = ("_is_open", "_lock", "_scheduled", "_waiters")

    def __init__(self, open: bool = False) -> None:
        self._is_open = open
        self._waiters: list[_Parked] = []
        # Waiters a scheduled flush will resume; None when no flush is pending.
        self._scheduled: list[_Parked] | None = None
        # Runs on other threads share a latch: its state and lists change
        # holding this; nobody is resumed while it is held.
        self._lock = threading.Lock()

    @classmethod
    def make(cls, open: bool = False) -> Effect[Latch]:
        return _Sync(lambda: cls(open))

    def is_open(self) -> bool:
        return self._is_open

    def open(self) -> Effect[bool]:
        """Open the latch, letting every waiter through. ``False`` if it was
        already open."""

        def run(fiber: Fiber[Any, Any]) -> Effect[bool]:
            with self._lock:
                if self._is_open:
                    return _FALSE
                self._is_open = True
                now = self._schedule_flush(fiber)
            _resume_all(now)
            return _TRUE

        return _WithFiber(run)

    def release(self) -> Effect[bool]:
        """Let the current waiters through, leaving the latch closed.
        ``False`` if it is open."""

        def run(fiber: Fiber[Any, Any]) -> Effect[bool]:
            with self._lock:
                if self._is_open:
                    return _FALSE
                now = self._schedule_flush(fiber)
            _resume_all(now)
            return _TRUE

        return _WithFiber(run)

    def close(self) -> Effect[bool]:
        """Close the latch. ``False`` if it was already closed."""
        return _Sync(self.close_unsafe)

    def wait(self) -> Effect[None]:
        """Wait until the latch is open or released (Effect's ``await``)."""
        return _Callback(self._register)

    def when_open[A, E, R](self, eff: Effect[A, E, R]) -> Effect[A, E, R]:
        """Run ``eff`` once the latch lets this fiber through."""
        require_effect(eff, "eff")
        return self.wait().and_then(eff)

    def open_unsafe(self) -> bool:
        """Open the latch from outside an effect, resuming waiters at once."""
        with self._lock:
            if self._is_open:
                return False
            self._is_open = True
            # Take both lists before resuming anyone: a waiter that closes the
            # latch again and registers new waiters must not be drained here.
            waiters, self._waiters = self._waiters, []
            scheduled, self._scheduled = self._scheduled or [], None
        _resume_all(scheduled)
        _resume_all(waiters)
        return True

    def close_unsafe(self) -> bool:
        with self._lock:
            if not self._is_open:
                return False
            self._is_open = False
            return True

    def _register(self, resume: _Resume) -> Effect[None] | None:
        with self._lock:
            parked = None if self._is_open else _Parked(resume, current_fiber())
            if parked is not None:
                self._waiters.append(parked)
        if parked is None:
            resume(_VOID)
            return None
        return _Sync(lambda: self._unregister(parked))

    def _unregister(self, parked: _Parked) -> None:
        with self._lock:
            if parked in self._waiters:
                self._waiters.remove(parked)
            elif self._scheduled is not None and parked in self._scheduled:
                self._scheduled.remove(parked)

    def _schedule_flush(self, fiber: Fiber[Any, Any]) -> list[_Parked]:
        """Hand the waiters of this run to a flush task on ``fiber``'s
        dispatcher (Effect's latch); the waiters of other runs, returned, are
        resumed now, through their own runs, which do not wait on this one."""
        here = [parked for parked in self._waiters if of_this_run(parked.fiber)]
        now = [parked for parked in self._waiters if not of_this_run(parked.fiber)]
        self._waiters = []
        if here:
            if self._scheduled is None:
                self._scheduled = here
                fiber.dispatcher().schedule(self._flush_scheduled)
            else:
                self._scheduled.extend(here)
        return now

    def _flush_scheduled(self) -> None:
        with self._lock:
            waiters, self._scheduled = self._scheduled or [], None
        _resume_all(waiters)


class _Parked:
    """A waiter's resume and the fiber it parks (``None`` outside a fiber)."""

    __slots__ = ("fiber", "resume")

    def __init__(self, resume: _Resume, fiber: Fiber[Any, Any] | None) -> None:
        self.resume = resume
        self.fiber = fiber


def _resume_all(waiters: list[_Parked]) -> None:
    for parked in waiters:
        parked.resume(_VOID)


__all__ = ["Latch"]
