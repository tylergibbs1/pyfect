"""``ScopedRef[A]``: a reference to a value with resources, swapped safely.

Each value lives in a scope of its own (a generation). ``set`` acquires
the next value in a fresh generation, then releases the previous one; if
acquiring fails, the current value stays. Closing the scope that made the
ref releases the current value. Every generation sits at the ref's place in
its owner's finalizer order, so owner finalizers added after the ref still
see a live value.
"""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Final, Never, overload

from pyfect._core import Effect, _Gen, _Locally, _Sync
from pyfect._effect_args import require_effect
from pyfect._interrupt_reason import interrupt_closed
from pyfect._unsubscripted import Unsubscripted
from pyfect.effect import sync as sync_effect
from pyfect.exit import Exit, Failure, Success
from pyfect.scope import CloseableScope, Scope
from pyfect.semaphore import Semaphore

_DONE: Final[Exit[None, Never]] = Success(None)


def _in_scope[A, E](eff: Effect[A, E, Any], scope: CloseableScope) -> Effect[A, E]:
    return _Locally(eff, lambda ctx: ctx.add(Scope, scope))


class ScopedRef[A = Unsubscripted]:
    """Make one with ``ScopedRef.make`` or ``ScopedRef.from_acquire`` inside
    a scope."""

    __slots__ = ("_current", "_lock", "_scope")

    def __init__(self, scope: CloseableScope, generation: CloseableScope, value: A) -> None:
        self._scope = scope
        self._current = (generation, value)
        self._lock = Semaphore(1)

    @overload
    @classmethod
    def from_acquire[T, X = Never, R = Never](
        cls: type[ScopedRef[Unsubscripted]], acquire: Effect[T, X, R]
    ) -> Effect[ScopedRef[T], X, Scope | R]: ...
    @overload
    @classmethod
    def from_acquire[X = Never, R = Never](
        cls, acquire: Effect[A, X, R]
    ) -> Effect[ScopedRef[A], X, Scope | R]: ...
    @classmethod
    def from_acquire[T, X = Never, R = Never](
        cls,
        acquire: Effect[T, X, R],
    ) -> Effect[ScopedRef[T], X, Scope | R]:
        """A ref holding what ``acquire`` gives, with its resources in the
        ref's first generation."""
        require_effect(acquire, "acquire")

        def body():
            owner = yield from Scope()
            scope = owner.fork_unsafe()
            generation = scope.fork_unsafe()
            value: T = yield from _in_scope(acquire, generation).tap_cause(
                lambda cause: scope.close(Failure(cause))
            )
            if generation._closed is not None:
                return (yield from interrupt_closed("Scope"))
            return ScopedRef(scope, generation, value)

        return _Gen(body).uninterruptible()

    @overload
    @classmethod
    def make[T](
        cls: type[ScopedRef[Unsubscripted]], evaluate: Callable[[], T]
    ) -> Effect[ScopedRef[T], Never, Scope]: ...
    @overload
    @classmethod
    def make(cls, evaluate: Callable[[], A]) -> Effect[ScopedRef[A], Never, Scope]: ...
    @classmethod
    def make[T](cls, evaluate: Callable[[], T]) -> Effect[ScopedRef[T], Never, Scope]:
        """A ref holding ``evaluate()``, which has no resources."""
        return ScopedRef.from_acquire(sync_effect(evaluate))

    def get_unsafe(self) -> A:
        return self._current[1]

    def get(self) -> Effect[A]:
        return _Sync(self.get_unsafe)

    @overload
    def set[X](self, acquire: Effect[A, X, Scope]) -> Effect[None, X]: ...
    @overload
    def set[X = Never, R = Never](self, acquire: Effect[A, X, Scope | R]) -> Effect[None, X, R]: ...
    def set(self, acquire: Effect[A, Any, Any]) -> Effect[None, Any, Any]:
        """Acquire a new value in a new generation, then release the old
        one. Sets run one at a time. If acquiring fails the old value
        stays; if releasing the old value fails, the new one is released
        too and the old one stays current."""
        require_effect(acquire, "acquire")

        def body():
            generation = self._scope.fork_unsafe()

            def discard(cause: Any) -> Effect[None]:
                return generation.close(Failure(cause))

            value = yield from _in_scope(acquire, generation).tap_cause(discard)
            yield from self._current[0].close(_DONE).tap_cause(discard)
            if generation._closed is not None:
                return (yield from interrupt_closed("Scope"))
            self._current = (generation, value)

        return self._lock.with_permits(_Gen(body).uninterruptible())

    def __repr__(self) -> str:
        return f"ScopedRef({self._current[1]!r})"


__all__ = ["ScopedRef"]
