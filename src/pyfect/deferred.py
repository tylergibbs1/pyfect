"""``Deferred[A, E]``: a result that will be set exactly once.

Fibers that ``wait()`` park until it is completed. Completing an
already-completed deferred does nothing and returns ``False``.

Completion, named as in Effect:

- ``done(exit)``: complete with an exit (``succeed``/``fail``/``fail_cause``
  are shorthands).
- ``complete(eff)``: run ``eff`` once and complete with its outcome, even if
  the completing fiber is interrupted. Every waiter sees the same result.
- ``complete_with(eff)``: store ``eff`` itself; each ``wait()`` runs it.
"""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Never

from pyfect._core import (
    Effect,
    _Callback,
    _FromExit,
    _Succeed,
    _Suspend,
    _Sync,
    uninterruptible_mask,
)
from pyfect.cause import Cause
from pyfect.exit import Exit, Failure, Success
from pyfect.exit import fail as fail_exit


class Deferred[A, E = Never]:
    __slots__ = ("_effect", "_waiters")

    def __init__(self) -> None:
        self._effect: Effect[A, E] | None = None
        self._waiters: list[Callable[[Effect[A, E]], None]] = []

    @classmethod
    def make(cls) -> Effect[Deferred[A, E]]:
        """``Deferred[int, MyError].make()``"""
        return _Sync(cls)

    def wait(self) -> Effect[A, E]:
        """Wait for the result and take it on."""

        def register(resume: Callable[[Effect[A, E]], None]) -> Effect[None] | None:
            if self._effect is not None:
                resume(self._effect)
                return None
            self._waiters.append(resume)
            return _Sync(lambda: self._waiters.remove(resume) if resume in self._waiters else None)

        return _Callback(register)

    def done(self, ex: Exit[A, E]) -> Effect[bool]:
        return _Sync(lambda: self.unsafe_done(ex))

    def succeed(self, value: A) -> Effect[bool]:
        return self.done(Success(value))

    def fail(self, error: E) -> Effect[bool]:
        return self.done(fail_exit(error))

    def fail_cause(self, cause: Cause[E]) -> Effect[bool]:
        return self.done(Failure(cause))

    def complete[R](self, eff: Effect[A, E, R]) -> Effect[bool, Never, R]:
        """Run ``eff`` and complete with its outcome. Does not run it if
        already completed; an interrupt while it runs completes with that
        interrupt."""

        def run() -> Effect[bool, Never, R]:
            if self._effect is not None:
                return _Succeed(False)
            return uninterruptible_mask(lambda restore: restore(eff).exit().flat_map(self.done))

        return _Suspend(run)

    def complete_with(self, eff: Effect[A, E]) -> Effect[bool]:
        """Complete with ``eff`` itself, unrun: every ``wait()`` runs it."""
        return _Sync(lambda: self._settle(eff))

    def poll(self) -> Effect[Effect[A, E] | None]:
        """The effect waiters will run, or ``None`` if not completed yet."""
        return _Suspend(lambda: _Succeed(self._effect))

    def unsafe_done(self, ex: Exit[A, E]) -> bool:
        """Complete from outside an effect. Call on the fiber's scheduler
        thread (e.g. inside ``sync``)."""
        return self._settle(_FromExit(ex))

    def _settle(self, effect: Effect[A, E, Any]) -> bool:
        if self._effect is not None:
            return False
        self._effect = effect
        waiters, self._waiters = self._waiters, []
        for resume in waiters:
            resume(effect)
        return True
