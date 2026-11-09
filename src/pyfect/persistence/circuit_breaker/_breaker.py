"""``CircuitBreaker``: stops calling a key that keeps failing."""

from __future__ import annotations

from collections.abc import Callable, Generator
from typing import Any, Literal, Never, overload

from pyfect._core import Effect
from pyfect._effect_args import require_effect
from pyfect._primitives import Restore, uninterruptible_mask
from pyfect.cause import Cause, Fail
from pyfect.clock import ClockService, clock_with
from pyfect.context import Tag
from pyfect.duration import ZERO, Duration, Seconds, to_millis, to_seconds
from pyfect.effect import fail_cause, gen, provide_service, succeed, suspend, void
from pyfect.exit import Exit, Failure, Success
from pyfect.exit import succeed as exit_succeed
from pyfect.layer import Layer
from pyfect.layer import effect as layer_effect
from pyfect.logger._log import log_unhandled
from pyfect.persistence.circuit_breaker._errors import (
    CircuitBreakerError,
    CircuitBreakerStoreError,
)
from pyfect.persistence.circuit_breaker._store import (
    CircuitBreakerStore,
    CircuitBreakerStoreService,
)
from pyfect.persistence.circuit_breaker._types import (
    Admission,
    Consecutive,
    FailureOutcome,
    Outcome,
    State,
    SuccessOutcome,
    Transition,
    TripPolicy,
    failure,
    ignored,
    success,
)
from pyfect.pubsub import PubSub
from pyfect.result import Ok
from pyfect.schedule import Schedule, Stop, to_step
from pyfect.scope import CloseableScope, Scope, add_finalizer, scoped_with
from pyfect.stream import Stream, from_pubsub_take
from pyfect.take import Take

type OnStoreError = Literal["allow", "fail"]
"""When the store cannot admit a call: ``"allow"`` runs it unrecorded
(reporting the cause at the ``UnhandledLogLevel``), ``"fail"`` fails with
the ``CircuitBreakerStoreError``."""

type OpenDuration = Duration | Schedule[object, int]
"""How long an opening lasts: a duration, or a schedule replayed with the
number of consecutive openings (its delays measured from the opening)."""

type Classify[A, E, R = Never] = Callable[[Exit[A, E]], Outcome | Effect[Outcome, Never, R]]
"""How a call's exit counts; without it a success is a ``success`` and a
failure a ``failure()``. An interrupt-only exit is always ``ignored``."""


def recovering(message: str) -> Callable[[Cause[Any]], Effect[None]]:
    """Reports a recoverable failure at the ``UnhandledLogLevel``; a cause
    holding a defect keeps failing."""

    def handle(cause: Cause[Any]) -> Effect[None]:
        found = cause.find_recoverable_error()
        return log_unhandled(message, cause) if isinstance(found, Fail) else fail_cause(found)

    return handle


def _open_duration(open_duration: OpenDuration) -> Callable[[int], Effect[Seconds]]:
    if not isinstance(open_duration, Schedule):
        fixed: Effect[Seconds] = succeed(to_seconds(open_duration))
        return lambda _: fixed
    schedule = open_duration

    # Replays the schedule on a simulated clock, so ``up_to`` measures the
    # time spent open rather than wall time.
    def replay(openings: int) -> Effect[Seconds]:
        def body(clock: ClockService) -> Generator[Effect[Any], Any, Seconds]:
            step = yield from to_step(schedule)
            now = clock.current_time_millis_unsafe()
            delay = ZERO
            for attempt in range(1, openings + 1):
                decision = yield from step(now, attempt)
                if isinstance(decision, Stop):
                    break
                delay = decision.delay
                now += to_millis(delay)
            return delay

        return clock_with(lambda clock: gen(lambda: body(clock)))

    return replay


def _classify[A, E, R](
    exit: Exit[A, E], classify: Classify[A, E, R] | None, restore: Restore
) -> Effect[Exit[Outcome, Never], Never, R]:
    if isinstance(exit, Failure) and exit.cause.has_interrupts_only:
        return succeed(exit_succeed(ignored))
    if classify is None:
        return succeed(exit_succeed(success if isinstance(exit, Success) else failure()))
    run = classify

    def call() -> Effect[Outcome, Never, R]:
        outcome = run(exit)
        return outcome if isinstance(outcome, Effect) else succeed(outcome)

    return restore(suspend(call)).exit()


class CircuitBreakerService:
    """Runs calls per key through a circuit (see ``make``)."""

    __slots__ = ("_max_open", "_on_store_error", "_open_duration", "_policy", "_pubsub", "_store")

    def __init__(  # noqa: PLR0917
        self,
        store: CircuitBreakerStoreService,
        pubsub: PubSub[Take[Transition]],
        policy: TripPolicy,
        open_duration: OpenDuration,
        max_open_duration: Seconds,
        on_store_error: OnStoreError,
    ) -> None:
        self._store = store
        self._pubsub = pubsub
        self._policy = policy
        self._open_duration = _open_duration(open_duration)
        self._max_open = max_open_duration
        self._on_store_error = on_store_error

    @property
    def transitions(self) -> Stream[Transition]:
        """Every transition from now on; it ends when the breaker's scope
        closes. A slow reader loses the oldest past 128."""
        return from_pubsub_take(self._pubsub)

    def state(self, key: str) -> Effect[State, CircuitBreakerError]:
        """``key``'s state now."""
        return self._store.state(key)

    @overload
    def execute[R2 = Never](
        self, effect: None = None, /, *, key: str, classify: Classify[Any, Any, R2] | None = None
    ) -> Executor[R2]: ...
    @overload
    def execute[A, E, R, R2 = Never](
        self,
        effect: Effect[A, E, R],
        /,
        *,
        key: str,
        classify: Classify[A, E, R2] | None = None,
    ) -> Effect[A, E | CircuitBreakerError, R | R2]: ...
    def execute(
        self,
        effect: Effect[Any, Any, Any] | None = None,
        /,
        *,
        key: str,
        classify: Classify[Any, Any, Any] | None = None,
    ) -> Executor[Any] | Effect[Any, Any, Any]:
        """Run ``effect`` through ``key``'s circuit: rejected with
        ``CircuitOpen`` while it is open and ``CircuitHalfOpen`` while its
        probe runs, else run and counted by ``classify``. Without
        ``effect``, the function doing that for ``.pipe``."""
        if effect is None:
            return Executor(self, key, classify)
        require_effect(effect, "effect")
        return self._run(effect, key, classify)

    def _publish(self, transition: Transition | None) -> Effect[None]:
        return void if transition is None else self._pubsub.publish((transition,)).as_void()

    def _open_for(self, outcome: Outcome, admission: Admission) -> Effect[Seconds]:
        # Only an outcome that can open the circuit needs the open time.
        if not isinstance(outcome, FailureOutcome) and (
            not isinstance(outcome, SuccessOutcome)
            or admission.probe
            or isinstance(self._policy, Consecutive)
        ):
            return succeed(ZERO)
        hint = outcome.retry_after if isinstance(outcome, FailureOutcome) else None
        max_open = self._max_open

        def hinted(delay: Seconds) -> Seconds:
            return delay if hint is None else max(delay, min(hint, max_open))

        return self._open_duration(admission.consecutive_openings + 1).map(hinted)

    def _run[A, E, R, R2](
        self, effect: Effect[A, E, R], key: str, classify: Classify[A, E, R2] | None
    ) -> Effect[A, E | CircuitBreakerError, R | R2]:
        store = self._store

        def admitted(
            restore: Restore, scope: CloseableScope
        ) -> Generator[Effect[Any, Any, Any], Any, A]:
            admit = yield from store.admit(key).pipe(provide_service(Scope, scope)).exit()
            if isinstance(admit, Failure):
                error = admit.cause.find_error()
                if (
                    self._on_store_error == "fail"
                    or not isinstance(error, Ok)
                    or not isinstance(error.value.reason, CircuitBreakerStoreError)
                ):
                    return (yield from fail_cause(admit.cause))
                yield from log_unhandled(
                    "CircuitBreaker store unavailable, running the call unrecorded", admit.cause
                )
                return (yield from restore(effect))
            admission = admit.value
            yield from self._publish(admission.transition)
            exit = yield from restore(effect).exit()
            classified = yield from _classify(exit, classify, restore)
            outcome = classified.value if isinstance(classified, Success) else ignored
            open_for = yield from self._open_for(outcome, admission)
            yield from (
                store.record(
                    key=key,
                    generation=admission.generation,
                    outcome=outcome.kind,
                    trip_policy=self._policy,
                    open_for=open_for,
                )
                .flat_map(self._publish)
                .catch_cause(recovering("CircuitBreaker failed to record an outcome"))
            )
            if isinstance(classified, Success):
                if isinstance(exit, Success):
                    return exit.value
                return (yield from fail_cause(exit.cause))
            cause: Cause[Any] = (
                exit.cause + classified.cause if isinstance(exit, Failure) else classified.cause
            )
            return (yield from fail_cause(cause))

        return uninterruptible_mask(
            lambda restore: scoped_with(lambda scope: gen(lambda: admitted(restore, scope)))
        )


class Executor[R2 = Never]:
    """``breaker.execute(key=...)``: runs an effect through the circuit."""

    __slots__ = ("_breaker", "_classify", "_key")

    def __init__(
        self,
        breaker: CircuitBreakerService,
        key: str,
        classify: Classify[Any, Any, R2] | None,
    ) -> None:
        self._breaker = breaker
        self._key = key
        self._classify = classify

    def __call__[A, E, R](
        self, effect: Effect[A, E, R]
    ) -> Effect[A, E | CircuitBreakerError, R | R2]:
        require_effect(effect, "effect")
        return self._breaker.execute(effect, key=self._key, classify=self._classify)


class CircuitBreaker(Tag[CircuitBreakerService], key="~effect/persistence/CircuitBreaker"):
    """Stops calling a key that keeps failing."""


def make(
    *,
    trip_policy: TripPolicy,
    open_duration: OpenDuration,
    max_open_duration: Duration = "1 hour",
    on_store_error: OnStoreError = "allow",
) -> Effect[CircuitBreakerService, Never, CircuitBreakerStore | Scope]:
    """A breaker on the ``CircuitBreakerStore``. A closed key opens when
    ``trip_policy`` says; an opening lasts ``open_duration`` (a schedule
    gives longer ones as openings repeat), or a failure's ``retry_after``
    up to ``max_open_duration`` (default an hour). After it, one probe
    runs: its success closes the key, its failure reopens it. A key closed
    as long as its last opening starts counting openings afresh.
    ``transitions`` ends when the scope closes."""
    max_open = to_seconds(max_open_duration)

    def build() -> Generator[Effect[Any, Never, Any], Any, CircuitBreakerService]:
        store = yield from CircuitBreakerStore()
        pubsub: PubSub[Take[Transition]] = yield from PubSub[Take[Transition]].sliding(128)
        yield from add_finalizer(lambda _: pubsub.end(exit_succeed(None)))
        return CircuitBreakerService(
            store, pubsub, trip_policy, open_duration, max_open, on_store_error
        )

    return gen(build)


def layer(
    *,
    trip_policy: TripPolicy,
    open_duration: OpenDuration,
    max_open_duration: Duration = "1 hour",
    on_store_error: OnStoreError = "allow",
) -> Layer[CircuitBreaker, Never, CircuitBreakerStore]:
    """Provides ``CircuitBreaker`` (see ``make``)."""
    return layer_effect(
        CircuitBreaker,
        make(
            trip_policy=trip_policy,
            open_duration=open_duration,
            max_open_duration=max_open_duration,
            on_store_error=on_store_error,
        ),
    )
