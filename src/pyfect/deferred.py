"""``Deferred[A, E]``: a result that will be set exactly once.

Fibers that ``wait()`` park until it is completed. Completing an
already-completed deferred does nothing and returns ``False``.

Completion, named as in Effect:

- ``done(exit)``: complete with an exit (``succeed``/``fail``/``fail_cause``
  are shorthands).
- ``complete(eff)``: run ``eff`` once and complete with its outcome, even if
  the completing fiber is interrupted. Every waiter sees the same result.
- ``complete_with(eff)``: store ``eff`` itself; each ``wait()`` runs it.
- ``into(eff)``: run ``eff`` and complete with its outcome, whether or not
  already completed (``eff.pipe(deferred.into)``).
"""
# pyright: reportPrivateUsage=false

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any, Never

from pyfect._core import (
    Effect,
    _Callback,
    _FromExit,
    _Succeed,
    _Suspend,
    _Sync,
    _WithFiber,
    uninterruptible_mask,
)
from pyfect._effect_args import require_effect
from pyfect.cause import Cause
from pyfect.exit import Exit, Failure, Success
from pyfect.exit import die as die_exit
from pyfect.exit import fail as fail_exit
from pyfect.exit import interrupt as interrupt_exit


class Deferred[A, E = Never]:
    __slots__ = ("_effect", "_lock", "_waiters")

    def __init__(self) -> None:
        self._effect: Effect[A, E] | None = None
        self._waiters: list[Callable[[Effect[A, E]], None]] = []
        # Runs on other threads share a deferred: completing it and
        # registering a waiter hold this, so no waiter misses the result.
        self._lock = threading.Lock()

    @classmethod
    def make(cls) -> Effect[Deferred[A, E]]:
        """``Deferred[int, MyError].make()``"""
        return _Sync(cls)

    def wait(self) -> Effect[A, E]:
        """Wait for the result and take it on."""

        def register(resume: Callable[[Effect[A, E]], None]) -> Effect[None] | None:
            with self._lock:
                effect = self._effect
                if effect is None:
                    self._waiters.append(resume)
            if effect is not None:
                resume(effect)
                return None
            return _Sync(lambda: self._leave(resume))

        return _Callback(register)

    def _leave(self, resume: Callable[[Effect[A, E]], None]) -> None:
        with self._lock:
            if resume in self._waiters:
                self._waiters.remove(resume)

    def done(self, ex: Exit[A, E]) -> Effect[bool]:
        return _Sync(lambda: self.done_unsafe(ex))

    def succeed(self, value: A) -> Effect[bool]:
        return self.done(Success(value))

    def fail(self, error: E) -> Effect[bool]:
        return self.done(fail_exit(error))

    def fail_cause(self, cause: Cause[E]) -> Effect[bool]:
        return self.done(Failure(cause))

    def sync(self, evaluate: Callable[[], A]) -> Effect[bool]:
        """Succeed with ``evaluate()``, computed when this runs."""
        return _Suspend(lambda: self.succeed(evaluate()))

    def fail_sync(self, evaluate: Callable[[], E]) -> Effect[bool]:
        return _Suspend(lambda: self.fail(evaluate()))

    def fail_cause_sync(self, evaluate: Callable[[], Cause[E]]) -> Effect[bool]:
        return _Suspend(lambda: self.fail_cause(evaluate()))

    def die(self, defect: BaseException) -> Effect[bool]:
        return self.done(die_exit(defect))

    def die_sync(self, evaluate: Callable[[], BaseException]) -> Effect[bool]:
        return _Suspend(lambda: self.die(evaluate()))

    def interrupt(self) -> Effect[bool]:
        """Complete with an interrupt by the current fiber."""
        return _WithFiber(lambda fiber: self.interrupt_with(fiber.id))

    def interrupt_with(self, fiber_id: int) -> Effect[bool]:
        """Complete with an interrupt by the fiber with id ``fiber_id``."""
        return self.done(interrupt_exit(fiber_id))

    def complete[R](self, eff: Effect[A, E, R]) -> Effect[bool, Never, R]:
        """Run ``eff`` and complete with its outcome. Does not run it if
        already completed; an interrupt while it runs completes with that
        interrupt."""
        require_effect(eff, "eff")
        return _Suspend(lambda: _Succeed(False) if self._effect is not None else self.into(eff))

    def into[R](self, eff: Effect[A, E, R]) -> Effect[bool, Never, R]:
        """Run ``eff`` and complete with its outcome, even if the running
        fiber is interrupted (then with that interrupt). Runs ``eff`` even
        when already completed; ``complete`` does not."""
        require_effect(eff, "eff")
        return uninterruptible_mask(lambda restore: restore(eff).exit().flat_map(self.done))

    def complete_with(self, eff: Effect[A, E]) -> Effect[bool]:
        """Complete with ``eff`` itself, unrun: every ``wait()`` runs it."""
        require_effect(eff, "eff")
        return _Sync(lambda: self._settle(eff))

    def is_done(self) -> Effect[bool]:
        return _Sync(self.is_done_unsafe)

    def is_done_unsafe(self) -> bool:
        return self._effect is not None

    def poll(self) -> Effect[Effect[A, E] | None]:
        """The effect waiters will run, or ``None`` if not completed yet."""
        return _Suspend(lambda: _Succeed(self._effect))

    def done_unsafe(self, ex: Exit[A, E]) -> bool:
        """Complete from outside an effect, from any thread."""
        return self._settle(_FromExit(ex))

    def _settle(self, effect: Effect[A, E, Any]) -> bool:
        with self._lock:
            if self._effect is not None:
                return False
            self._effect = effect
            waiters, self._waiters = self._waiters, []
        for resume in waiters:
            resume(effect)
        return True


__all__ = ["Deferred"]
