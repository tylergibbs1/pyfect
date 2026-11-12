"""``Latch``: a gate fibers wait at until it opens.

``open()`` lets every waiter through and keeps the gate open; ``release()``
lets the current waiters through but leaves it closed; ``close()`` makes
later ``wait()`` calls park again. ``open`` and ``release`` wake waiters in
one task scheduled on the calling fiber's scheduler, as Effect's latch does,
so several releases before that task runs share it.
"""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from pyfect._core import Effect, _Callback, _Succeed, _Sync, _WithFiber
from pyfect._effect_args import require_effect

if TYPE_CHECKING:
    from pyfect._fiber import Fiber

type _Resume = Callable[[Effect[None]], None]

_TRUE: Effect[bool] = _Succeed(True)
_FALSE: Effect[bool] = _Succeed(False)
_VOID: Effect[None] = _Succeed(None)


class Latch:
    __slots__ = ("_is_open", "_scheduled", "_waiters")

    def __init__(self, open: bool = False) -> None:
        self._is_open = open
        self._waiters: list[_Resume] = []
        # Waiters a scheduled flush will resume; None when no flush is pending.
        self._scheduled: list[_Resume] | None = None

    @classmethod
    def make(cls, open: bool = False) -> Effect[Latch]:
        return _Sync(lambda: cls(open))

    def is_open(self) -> bool:
        return self._is_open

    def open(self) -> Effect[bool]:
        """Open the latch, letting every waiter through. ``False`` if it was
        already open."""

        def run(fiber: Fiber[Any, Any]) -> Effect[bool]:
            if self._is_open:
                return _FALSE
            self._is_open = True
            return self._schedule_flush(fiber)

        return _WithFiber(run)

    def release(self) -> Effect[bool]:
        """Let the current waiters through, leaving the latch closed.
        ``False`` if it is open."""
        return _WithFiber(lambda fiber: _FALSE if self._is_open else self._schedule_flush(fiber))

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
        """Open the latch from outside an effect, resuming waiters at once.
        Call on the fibers' scheduler thread."""
        if self._is_open:
            return False
        self._is_open = True
        # Take both lists before resuming anyone: a waiter that closes the
        # latch again and registers new waiters must not be drained here.
        waiters, self._waiters = self._waiters, []
        self._flush_scheduled()
        for resume in waiters:
            resume(_VOID)
        return True

    def close_unsafe(self) -> bool:
        if not self._is_open:
            return False
        self._is_open = False
        return True

    def _register(self, resume: _Resume) -> Effect[None] | None:
        if self._is_open:
            resume(_VOID)
            return None
        self._waiters.append(resume)
        return _Sync(lambda: self._unregister(resume))

    def _unregister(self, resume: _Resume) -> None:
        if resume in self._waiters:
            self._waiters.remove(resume)
        elif self._scheduled is not None and resume in self._scheduled:
            self._scheduled.remove(resume)

    def _schedule_flush(self, fiber: Fiber[Any, Any]) -> Effect[bool]:
        if not self._waiters:
            return _TRUE
        if self._scheduled is None:
            self._scheduled = self._waiters
            fiber.dispatcher().schedule(self._flush_scheduled)
        else:
            self._scheduled.extend(self._waiters)
        self._waiters = []
        return _TRUE

    def _flush_scheduled(self) -> None:
        if self._scheduled is None:
            return
        waiters, self._scheduled = self._scheduled, None
        for resume in waiters:
            resume(_VOID)


__all__ = ["Latch"]
