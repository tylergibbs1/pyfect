"""``layer_store_memory``: circuit states in process memory."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Literal

from pyfect._core import Effect
from pyfect.clock import ClockService, clock_with
from pyfect.duration import Duration, Seconds, to_millis
from pyfect.effect import fail, succeed
from pyfect.layer import Layer
from pyfect.layer import sync as layer_sync
from pyfect.persistence._seconds import millis
from pyfect.persistence.circuit_breaker._errors import (
    CircuitBreakerError,
    CircuitHalfOpen,
    CircuitOpen,
)
from pyfect.persistence.circuit_breaker._store import (
    CircuitBreakerStore,
    CircuitBreakerStoreService,
)
from pyfect.persistence.circuit_breaker._types import (
    Admission,
    Closed,
    CloseTransition,
    Consecutive,
    HalfOpen,
    HalfOpenTransition,
    Open,
    OpenTransition,
    OutcomeKind,
    State,
    Transition,
    TripPolicy,
)
from pyfect.persistence.persistence._service import now_millis
from pyfect.scope import Scope

type _Phase = Literal["Closed", "Open", "HalfOpen"]


@dataclass(slots=True)
class _Entry:
    generation: int
    last_activity: float
    state: _Phase = "Closed"
    streak: int = 0
    ring: deque[bool] = field(default_factory=deque[bool])
    ring_failures: int = 0
    open_until: float = 0
    consecutive_openings: int = 0
    last_open_for: float = 0
    reset_at: float = 0
    probing: bool = False

    def reset_counters(self) -> None:
        self.streak = 0
        self.ring.clear()
        self.ring_failures = 0

    def trips(self, policy: TripPolicy) -> bool:
        if isinstance(policy, Consecutive):
            return self.streak >= policy.failure_count
        calls = len(self.ring)
        return (
            calls >= policy.minimum_calls
            and self.ring_failures > 0
            and self.ring_failures / calls >= policy.threshold
        )


class MemoryCircuitBreakerStore:
    """Entries in a dict, read on the ``Clock``; a key idle for
    ``idle_millis`` is dropped (an open one only after its open time)."""

    __slots__ = ("_entries", "_idle_millis", "_last_sweep", "_next_generation")

    def __init__(self, idle_millis: float) -> None:
        self._idle_millis = idle_millis
        self._entries: dict[str, _Entry] = {}
        self._next_generation = 0
        self._last_sweep = 0.0

    def _generation(self) -> int:
        generation = self._next_generation
        self._next_generation += 1
        return generation

    def _expired(self, entry: _Entry, now: float) -> bool:
        match entry.state:
            case "Closed":
                return now - entry.last_activity >= self._idle_millis
            case "Open":
                return now - max(entry.last_activity, entry.open_until) >= self._idle_millis
            case "HalfOpen":
                return not entry.probing and now - entry.last_activity >= self._idle_millis

    def _sweep(self, now: float) -> None:
        if now - self._last_sweep < self._idle_millis:
            return
        self._last_sweep = now
        for key, entry in list(self._entries.items()):
            if self._expired(entry, now):
                del self._entries[key]

    def _lookup(self, key: str, now: float) -> _Entry | None:
        entry = self._entries.get(key)
        return entry if entry is not None and not self._expired(entry, now) else None

    def _open(
        self, key: str, entry: _Entry, from_: Literal["Closed", "HalfOpen"], open_for: Seconds
    ) -> Transition:
        entry.state = "Open"
        entry.generation = self._generation()
        entry.last_open_for = to_millis(open_for)
        entry.open_until = entry.last_activity + entry.last_open_for
        entry.consecutive_openings += 1
        entry.probing = False
        entry.reset_counters()
        return OpenTransition(key, from_, open_for, entry.consecutive_openings)

    def admit(self, key: str) -> Effect[Admission, CircuitBreakerError, Scope]:
        def run(clock: ClockService) -> Effect[Admission, CircuitBreakerError]:
            now = now_millis(clock)
            self._sweep(now)
            entry = self._lookup(key, now)
            if entry is None:
                entry = _Entry(self._generation(), now)
                self._entries[key] = entry
            transition: Transition | None = None
            match entry.state:
                case "Closed":
                    # A call admitted before this reset can still trip the
                    # circuit, with the open time of its older count.
                    if entry.consecutive_openings > 0 and now >= entry.reset_at:
                        entry.consecutive_openings = 0
                case "Open":
                    if now < entry.open_until:
                        retry_after = millis(entry.open_until - now)
                        return fail(
                            CircuitBreakerError(
                                reason=CircuitOpen(key=key, retry_after=retry_after)
                            )
                        )
                    entry.state = "HalfOpen"
                    transition = HalfOpenTransition(key)
                case "HalfOpen":
                    if entry.probing:
                        return fail(CircuitBreakerError(reason=CircuitHalfOpen(key=key)))
            entry.last_activity = now
            probe = entry.state == "HalfOpen"
            if probe:
                entry.probing = True
                entry.generation = self._generation()
            return succeed(
                Admission(entry.generation, probe, entry.consecutive_openings, transition)
            )

        return clock_with(run)

    def record(
        self,
        *,
        key: str,
        generation: int,
        outcome: OutcomeKind,
        trip_policy: TripPolicy,
        open_for: Seconds,
    ) -> Effect[Transition | None, CircuitBreakerError]:
        def run(clock: ClockService) -> Effect[Transition | None]:
            return succeed(
                self._record(now_millis(clock), key, generation, outcome, trip_policy, open_for)
            )

        return clock_with(run)

    def _record(  # noqa: PLR0917
        self,
        now: float,
        key: str,
        generation: int,
        outcome: OutcomeKind,
        trip_policy: TripPolicy,
        open_for: Seconds,
    ) -> Transition | None:
        entry = self._lookup(key, now)
        if entry is None or entry.generation != generation:
            return None
        entry.last_activity = now
        if entry.state == "HalfOpen":
            match outcome:
                case "Ignored":
                    entry.probing = False
                    return None
                case "Failure":
                    return self._open(key, entry, "HalfOpen", open_for)
                case "Success":
                    entry.state = "Closed"
                    entry.generation = self._generation()
                    entry.reset_at = now + entry.last_open_for
                    entry.probing = False
                    entry.reset_counters()
                    return CloseTransition(key)
        if entry.state != "Closed" or outcome == "Ignored":
            return None
        failed = outcome == "Failure"
        entry.streak = entry.streak + 1 if failed else 0
        if not isinstance(trip_policy, Consecutive):
            entry.ring.append(failed)
            entry.ring_failures += failed
            while len(entry.ring) > trip_policy.size:
                entry.ring_failures -= entry.ring.popleft()
        return self._open(key, entry, "Closed", open_for) if entry.trips(trip_policy) else None

    def state(self, key: str) -> Effect[State, CircuitBreakerError]:
        def run(clock: ClockService) -> Effect[State]:
            now = now_millis(clock)
            entry = self._lookup(key, now)
            if entry is None or entry.state == "Closed":
                return succeed(Closed(key))
            if entry.state == "Open":
                retry_after = millis(max(0, entry.open_until - now))
                return succeed(Open(key, retry_after, entry.consecutive_openings))
            return succeed(HalfOpen(key, entry.probing, entry.consecutive_openings))

        return clock_with(run)


def make_store_memory(*, idle_time_to_live: Duration = 3600) -> CircuitBreakerStoreService:
    """A store in memory, dropping keys idle for ``idle_time_to_live``
    (default an hour)."""
    store = MemoryCircuitBreakerStore(to_millis(idle_time_to_live))
    return CircuitBreakerStoreService(admit=store.admit, record=store.record, state=store.state)


def layer_store_memory(*, idle_time_to_live: Duration = 3600) -> Layer[CircuitBreakerStore]:
    """Circuit states in memory, fresh each time the layer is built."""
    return layer_sync(
        CircuitBreakerStore, lambda: make_store_memory(idle_time_to_live=idle_time_to_live)
    )
