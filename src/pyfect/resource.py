"""``Resource[A, E]``: a cached value with resources, refreshed by hand or
on a schedule.

The value is acquired once on creation; ``get`` reads the cached outcome
(a failed acquisition fails every ``get`` until a refresh succeeds).
``refresh`` acquires anew and swaps the new value in, releasing the old
one; a failed refresh keeps the cached value. ``auto`` refreshes on a
schedule until the scope that made it closes.
"""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from typing import Any, Never

from pyfect._core import Effect, _FromExit, _Locally, _WithFiber
from pyfect._effect_args import require_effect
from pyfect._fiber import Fiber
from pyfect.exit import Exit, Success
from pyfect.schedule import Schedule
from pyfect.scope import Scope
from pyfect.scoped_ref import ScopedRef


class Resource[A, E = Never]:
    """Make one with ``Resource.manual`` or ``Resource.auto`` inside a scope."""

    __slots__ = ("_acquire", "_ref")

    def __init__(self, ref: ScopedRef[Exit[A, E]], acquire: Effect[A, E]) -> None:
        self._ref = ref
        self._acquire = acquire

    @staticmethod
    def manual[T, X = Never, R = Never](
        acquire: Effect[T, X, R],
    ) -> Effect[Resource[T, X], Never, Scope | R]:
        """A resource acquired now (with the services in scope now) and
        again on each ``refresh``."""
        require_effect(acquire, "acquire")

        def body(fiber: Fiber[Any, Any]) -> Effect[Resource[T, X], Never, Scope]:
            captured = fiber._context
            provided: Effect[T, X] = _Locally(acquire, captured.merge)
            return ScopedRef.from_acquire(provided.exit()).map(lambda ref: Resource(ref, provided))

        return _WithFiber(body)

    @staticmethod
    def auto[T, X = Never, RR = Never](
        acquire: Effect[T, X, RR], policy: Schedule[object, object, object, RR]
    ) -> Effect[Resource[T, X], Never, Scope | RR]:
        """``manual``, refreshed each time ``policy`` recurs (first after its
        first delay) until the current scope closes. Failed refreshes are
        ignored."""
        require_effect(acquire, "acquire")
        return Resource.manual(acquire).tap(
            lambda resource: resource.refresh().ignore_cause().schedule(policy).fork_scoped()
        )

    def get(self) -> Effect[A, E]:
        """The cached value, or the cached failure."""
        return self._ref.get().flat_map(_FromExit)

    def refresh(self) -> Effect[None, E]:
        """Acquire anew and swap the value in. A failure keeps the cached
        value."""
        return self._ref.set(self._acquire.map(Success))

    def __repr__(self) -> str:
        return "Resource()"


__all__ = ["Resource"]
