"""What a running plan reports: ``CurrentMetadata`` inside each attempt and
the ``Event``\\ s an ``on_event`` observer receives around it."""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Generic, Never, TypeVar

from pyfect._core import Effect, _Suspend
from pyfect.cause import Cause
from pyfect.clock import Clock, ClockService
from pyfect.context import Reference
from pyfect.duration import Duration
from pyfect.exit import Exit, Failure

E_co = TypeVar("E_co", covariant=True)


@dataclass(frozen=True, slots=True)
class Metadata:
    """``attempt`` counts the plan's attempts from 1, across steps;
    ``step_index`` is the step running it, from 0."""

    attempt: int
    step_index: int


class CurrentMetadata(Reference[Metadata]):
    """The plan metadata of the running attempt (``attempt`` 0 outside a plan)."""

    @classmethod
    def default(cls) -> Metadata:
        return Metadata(attempt=0, step_index=0)


@dataclass(frozen=True, slots=True)
class AttemptStart:
    """An attempt is about to run. ``step_attempt`` counts attempts within
    the step, from 1; ``attempt`` matches ``CurrentMetadata.attempt``."""

    attempt: int
    step_attempt: int
    step_index: int


@dataclass(frozen=True, slots=True)
class AttemptSuccess:
    """The attempt started by the last ``AttemptStart`` succeeded after ``duration``."""

    attempt: int
    step_attempt: int
    step_index: int
    duration: Duration


@dataclass(frozen=True, slots=True)
class AttemptFailure(Generic[E_co]):
    """The attempt started by the last ``AttemptStart`` failed (or was
    interrupted) with ``cause`` after ``duration``."""

    attempt: int
    step_attempt: int
    step_index: int
    duration: Duration
    cause: Cause[E_co]


type Event[E] = AttemptStart | AttemptSuccess | AttemptFailure[E]
"""Every ``AttemptStart`` is followed by exactly one ``AttemptSuccess`` or
``AttemptFailure``."""

type OnEvent[E, R] = Callable[[Event[E]], Effect[object, Never, R]]


@dataclass(frozen=True, slots=True)
class AttemptState:
    attempt: int
    step_attempt: int
    step_index: int
    start_nanos: int


class EventEmitter:
    """Effect's ``makeEventEmitter``: numbers the attempts of one run of a
    plan and sends their events to ``on_event``, whose failures and defects
    are dropped so observing never changes the outcome."""

    __slots__ = ("current", "last_step_index", "on_event", "step_attempt")

    def __init__(self, on_event: OnEvent[Any, Any], current: Callable[[], Metadata]) -> None:
        self.on_event = on_event
        self.current = current
        self.last_step_index = -1
        self.step_attempt = 0

    def _emit(self, event: Event[Any]) -> Effect[None, Never, Any]:
        return _Suspend(lambda: self.on_event(event)).ignore_cause()

    def begin(self) -> Effect[AttemptState, Never, Any]:
        def start(clock: ClockService) -> Effect[AttemptState, Never, Any]:
            meta = self.current()
            if meta.step_index != self.last_step_index:
                self.last_step_index = meta.step_index
                self.step_attempt = 0
            self.step_attempt += 1
            state = AttemptState(
                meta.attempt, self.step_attempt, meta.step_index, clock.monotonic_nanos_unsafe()
            )
            event = AttemptStart(state.attempt, state.step_attempt, state.step_index)
            return self._emit(event).as_(state)

        return Clock().flat_map(start)

    def end(self, state: AttemptState, ex: Exit[Any, Any]) -> Effect[None, Never, Any]:
        def finish(clock: ClockService) -> Effect[None, Never, Any]:
            duration = Duration(
                (clock.monotonic_nanos_unsafe() - state.start_nanos) / 1_000_000_000
            )
            event: Event[Any] = (
                AttemptFailure(
                    state.attempt, state.step_attempt, state.step_index, duration, ex.cause
                )
                if isinstance(ex, Failure)
                else AttemptSuccess(state.attempt, state.step_attempt, state.step_index, duration)
            )
            return self._emit(event)

        return Clock().flat_map(finish)
