"""``CircuitBreakerStore``: where a ``CircuitBreaker`` keeps each key's
state."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from pyfect._core import Effect
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


@dataclass(frozen=True, slots=True, kw_only=True)
class CircuitBreakerStoreService:
    """The state of each key.

    - ``admit(key)`` lets a call through, or fails with ``CircuitOpen`` /
      ``CircuitHalfOpen``; a probe holds its slot until the scope closes
      (or its outcome is recorded).
    - ``record(...)`` counts the outcome of an admitted call.
    - ``state(key)`` reads the key's state.
    """

    admit: Callable[[str], Effect[Admission, CircuitBreakerError, Scope]]
    record: Record
    state: Callable[[str], Effect[State, CircuitBreakerError]]


class CircuitBreakerStore(
    Tag[CircuitBreakerStoreService], key="effect/persistence/CircuitBreaker/CircuitBreakerStore"
):
    """Where a ``CircuitBreaker`` keeps each key's state."""
