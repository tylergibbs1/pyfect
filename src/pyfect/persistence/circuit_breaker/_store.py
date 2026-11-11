"""``CircuitBreakerStore``: where a ``CircuitBreaker`` keeps each key's
state."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol, Self

from pyfect._core import Effect
from pyfect._service_copy import replaced
from pyfect.context import Tag
from pyfect.duration import Duration
from pyfect.persistence.circuit_breaker._errors import CircuitBreakerError
from pyfect.persistence.circuit_breaker._types import (
    Admission,
    OutcomeKind,
    State,
    Transition,
    TripPolicy,
)
from pyfect.scope import Scope


class Record(Protocol):
    """Records the outcome of the call admitted with ``generation``; one
    whose generation is no longer current changes nothing. ``open_for`` is
    how long to open if this opens the circuit. Gives the transition it
    caused."""

    def __call__(
        self,
        *,
        key: str,
        generation: int,
        outcome: OutcomeKind,
        trip_policy: TripPolicy,
        open_for: Duration,
    ) -> Effect[Transition | None, CircuitBreakerError]: ...


class CircuitBreakerStoreService:
    """The state of each key: ``make_store_memory`` keeps it in the process,
    ``make_store_redis`` shares it between processes, and
    ``CircuitBreakerStoreService(admit=..., record=..., state=...)`` makes
    one of three functions (a test double, say)."""

    __slots__ = ("_admit", "_record", "_state")

    def __replace__(self, **changes: Any) -> Self:
        """A copy with ``changes`` to the constructor's arguments (``copy.replace``)."""
        return replaced(self, changes)

    def __init__(
        self,
        *,
        admit: Callable[[str], Effect[Admission, CircuitBreakerError, Scope]],
        record: Record,
        state: Callable[[str], Effect[State, CircuitBreakerError]],
    ) -> None:
        self._admit = admit
        self._record = record
        self._state = state

    def admit(self, key: str) -> Effect[Admission, CircuitBreakerError, Scope]:
        """Lets a call on ``key`` through, giving its ``Admission``: the
        generation to pass back to ``record``, and whether it is the
        half-open probe. An open circuit whose open time has ended turns
        half-open and admits this call as the probe. Fails with
        ``CircuitBreakerError`` whose reason is ``CircuitOpen`` while the
        circuit is open, ``CircuitHalfOpen`` while another probe runs, or
        ``CircuitBreakerStoreError`` when the store cannot be reached. The
        ``Scope`` is the call's: a store may hold the probe's slot with it
        (the Redis store renews the probe's lease until it closes)."""
        return self._admit(key)

    def record(
        self,
        *,
        key: str,
        generation: int,
        outcome: OutcomeKind,
        trip_policy: TripPolicy,
        open_for: Duration,
    ) -> Effect[Transition | None, CircuitBreakerError]:
        """Records the ``outcome`` of the call on ``key`` admitted with
        ``generation``; one whose generation is no longer current changes
        nothing. ``trip_policy`` decides whether a failure opens a closed
        circuit, and ``open_for`` is how long it stays open if this opens
        it. Gives the transition the outcome caused, or ``None``. Fails
        with ``CircuitBreakerError`` (reason ``CircuitBreakerStoreError``)
        when the store cannot be reached."""
        return self._record(
            key=key,
            generation=generation,
            outcome=outcome,
            trip_policy=trip_policy,
            open_for=open_for,
        )

    def state(self, key: str) -> Effect[State, CircuitBreakerError]:
        """``key``'s current state (``Closed`` for a key never seen or long
        idle). Fails with ``CircuitBreakerError`` (reason
        ``CircuitBreakerStoreError``) when the store cannot be reached."""
        return self._state(key)


class CircuitBreakerStore(
    Tag[CircuitBreakerStoreService], key="effect/persistence/CircuitBreaker/CircuitBreakerStore"
):
    """Where a ``CircuitBreaker`` keeps each key's state."""
