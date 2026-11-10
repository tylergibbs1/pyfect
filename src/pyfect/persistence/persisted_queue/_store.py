"""``PersistedQueueStore``: where a ``PersistedQueue`` keeps its elements,
and what every store shares."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Final, Protocol

from pyfect._core import Effect
from pyfect.context import Tag
from pyfect.duration import Duration, from_input_unsafe, millis
from pyfect.duration import Input as DurationInput
from pyfect.latch import Latch
from pyfect.persistence.persisted_queue._error import PersistedQueueError
from pyfect.schedule import Schedule, exponential, min, spaced
from pyfect.scope import Scope


@dataclass(frozen=True, slots=True)
class TakenElement:
    """An element a store claimed: its ``attempts`` count this claim (from
    1), and ``element`` is its stored JSON value."""

    id: str
    attempts: int
    element: object


@dataclass(frozen=True, slots=True, kw_only=True)
class TakeOptions:
    """What a store's ``take`` needs from the queue: an element failing on
    attempt ``max_attempts`` is marked failed; before that it is retried
    after ``retry_delay(attempts)``."""

    name: str
    max_attempts: int
    retry_delay: Callable[[int], Effect[Duration]]


class Offer(Protocol):
    """Store ``element`` under ``id`` unless the queue has that id. A
    ``delay`` is finite and positive: the element is not taken before it
    elapses."""

    def __call__(
        self,
        *,
        name: str,
        id: str,
        element: object,
        is_custom_id: bool,
        delay: Duration | None = None,
    ) -> Effect[None, PersistedQueueError]: ...


class Cleanup(Protocol):
    """Remove completed elements older than ``time_to_live`` with their
    de-duplication records; failed ones only with ``failed_time_to_live``."""

    def __call__(
        self, *, time_to_live: Duration, failed_time_to_live: Duration | None
    ) -> Effect[None, PersistedQueueError]: ...


@dataclass(frozen=True, slots=True, kw_only=True)
class PersistedQueueStoreService:
    """The elements of every queue.

    - ``offer``: store an element (see ``Offer``).
    - ``take(options)``: claim the next visible element, counting an
      attempt, waiting while there is none. When the scope closes, a
      success marks it completed, an interruption releases it without the
      attempt, a ``DeadLetter`` failure marks it failed, and any other
      failure retries it or, after ``max_attempts``, marks it failed.
    - ``cleanup``: see ``Cleanup``.
    """

    offer: Offer
    take: Callable[[TakeOptions], Effect[TakenElement, PersistedQueueError, Scope]]
    cleanup: Cleanup


class PersistedQueueStore(
    Tag[PersistedQueueStoreService], key="effect/persistence/PersistedQueue/PersistedQueueStore"
):
    """Where persisted queues keep their elements."""


@dataclass(slots=True)
class QueueState:
    """A queue's state in one store, shared by its offers and takes:
    ``take`` records ``max_attempts`` before the store's mailbox reads it,
    and ``offer`` opens ``nudge`` so local pollers skip the poll interval."""

    max_attempts: int
    nudge: Latch


_PLACEHOLDER_MAX_ATTEMPTS: Final = 2_147_483_647
"""Overwritten by ``take`` before any mailbox reads it; int32-safe for SQL
parameters."""


class QueueStates:
    __slots__ = ("_states",)

    def __init__(self) -> None:
        self._states: dict[str, QueueState] = {}

    def peek(self, name: str) -> QueueState | None:
        return self._states.get(name)

    def get(self, name: str) -> QueueState:
        state = self._states.get(name)
        if state is None:
            state = QueueState(_PLACEHOLDER_MAX_ATTEMPTS, Latch())
            self._states[name] = state
        return state


def ack_retry_schedule(lock_expiration: Duration) -> Schedule[object, object]:
    """How a store retries settling an element: backing off from 200 ms to
    5 s, for as long as the element's lock lasts."""
    return min(exponential("200 millis", 1.5), spaced("5 seconds")).up_to(duration=lock_expiration)


def store_interval(duration: DurationInput, default: Duration) -> Duration:
    """A store's interval option as Effect reads it (``options.x ? x :
    default``): zero means ``default``; anything else is at least a
    millisecond."""
    parsed = from_input_unsafe(duration)
    if parsed.is_zero():
        return default
    return max(parsed, millis(1))


def positive_delay(delay: DurationInput | None) -> Duration | None:
    """A delay a store sees: ``None`` for none, zero or negative."""
    if delay is None:
        return None
    parsed = from_input_unsafe(delay)
    return parsed if parsed.is_positive() else None


def is_infinite(delay: Duration | None) -> bool:
    return delay is not None and not delay.is_finite()
