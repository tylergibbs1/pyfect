"""Effect's ``test/persistence/CircuitBreakerTest.ts``: the suite each
``CircuitBreakerStore`` runs, as bodies taking the store's ``advance``
(``testing.adjust`` for the memory store, a live sleep for stores reading
wall time). ``SUITE`` lists them with their Effect titles; ``IDLE_SUITE``
runs on a store with a 400 millisecond ``idle_time_to_live``.

Durations are seconds (Effect's ``"200 millis"`` is ``0.2``).
"""

from __future__ import annotations

from collections.abc import Callable, Generator
from dataclasses import dataclass
from typing import Any

import pyfect as fx
from pyfect.duration import ZERO, to_millis
from pyfect.exit import Failure, Success
from pyfect.persistence import circuit_breaker as cb
from pyfect.result import Err, Ok

type Advance = Callable[[float], fx.Effect[None]]
type Body = Callable[[Advance], Generator[Any, Any]]


def rejection(
    effect: fx.Effect[Any, Any, Any],
) -> fx.Effect[cb.CircuitBreakerErrorReason, Any, Any]:
    def reason(error: object) -> cb.CircuitBreakerErrorReason:
        assert isinstance(error, cb.CircuitBreakerError), "Expected CircuitBreakerError"
        return error.reason

    def admitted(_: object) -> fx.Effect[Any]:
        raise AssertionError("Expected a rejection, but the call was admitted")

    return effect.flip().map(reason).catch_all(admitted)


@dataclass(frozen=True)
class Held:
    fiber: fx.Fiber[None, Any]
    release: fx.Effect[fx.Exit[None, Any]]


def held(
    breaker: cb.CircuitBreakerService,
    key: str,
    result: fx.Effect[None, Any],
    classify: cb.Classify[None, Any] | None = None,
) -> fx.Effect[Held]:
    """Starts a call that is admitted and then waits for a gate before
    completing with ``result``."""

    def body():
        started = yield from fx.Deferred[None].make()
        gate = yield from fx.Deferred[None].make()
        fiber = yield from (
            started.succeed(None)
            .and_then(gate.wait())
            .and_then(result)
            .pipe(breaker.execute(key=key, classify=classify))
            .fork()
        )
        yield from started.wait()
        return Held(fiber, gate.succeed(None).and_then(fiber.await_exit()))

    return fx.gen(body)


def fail(breaker: cb.CircuitBreakerService, key: str) -> fx.Effect[None]:
    return fx.fail("boom").pipe(breaker.execute(key=key)).ignore()


def run_void(breaker: cb.CircuitBreakerService, key: str) -> fx.Effect[None, Any]:
    return fx.void.pipe(breaker.execute(key=key))


def openings(breaker: cb.CircuitBreakerService, take: int) -> fx.Effect[fx.Fiber[list[Any]]]:
    """The ``retry_after`` millis and ``consecutive_openings`` of the next
    ``take`` openings."""

    def opening(transition: cb.Transition) -> fx.Result[tuple[float, int], None]:
        if isinstance(transition, cb.OpenTransition):
            return Ok((to_millis(transition.retry_after), transition.consecutive_openings))
        return Err(None)

    return (
        breaker.transitions.filter_map(opening)
        .take(take)
        .run_collect()
        .fork(start_immediately=True)
    )


def consecutive(advance: Advance):
    key = "consecutive"
    breaker = yield from cb.make(trip_policy=cb.consecutive(3), open_duration="1 minute")
    yield from fail(breaker, key)
    yield from fail(breaker, key)
    yield from run_void(breaker, key)
    yield from fail(breaker, key)
    yield from fail(breaker, key)
    yield from (
        fx.fail("boom").pipe(breaker.execute(key=key, classify=lambda _: cb.ignored)).ignore()
    )
    assert isinstance((yield from breaker.state(key)), cb.Closed)

    yield from fail(breaker, key)
    ran: list[bool] = []
    reason = yield from rejection(fx.sync(lambda: ran.append(True)).pipe(breaker.execute(key=key)))
    assert not ran
    assert isinstance(reason, cb.CircuitOpen)
    assert reason.key == key


def rate(advance: Advance):
    key = "rate"
    breaker = yield from cb.make(
        trip_policy=cb.rate(threshold=0.5, size=3, minimum_calls=3), open_duration="1 minute"
    )
    yield from fail(breaker, key)
    yield from (
        fx.fail("boom").pipe(breaker.execute(key=key, classify=lambda _: cb.ignored)).ignore()
    )
    yield from fail(breaker, key)
    assert isinstance((yield from breaker.state(key)), cb.Closed)

    # 2 failures in 3 calls. The opening lasts open_duration, so the next
    # call is rejected rather than admitted as a probe.
    yield from run_void(breaker, key)
    assert isinstance((yield from rejection(run_void(breaker, key))), cb.CircuitOpen)


def half_open(advance: Advance):
    key = "half-open"
    breaker = yield from cb.make(trip_policy=cb.consecutive(1), open_duration="200 millis")
    transitions = yield from breaker.transitions.take(3).run_collect().fork(start_immediately=True)
    yield from fail(breaker, key)
    yield from advance(0.3)
    lazy = yield from breaker.state(key)
    assert isinstance(lazy, cb.Open)
    assert lazy.retry_after == ZERO

    probe = yield from held(breaker, key, fx.void)
    assert isinstance((yield from rejection(run_void(breaker, key))), cb.CircuitHalfOpen)
    assert (yield from breaker.state(key)) == cb.HalfOpen(key, True, 1)

    assert isinstance((yield from probe.release), Success)
    assert (yield from breaker.state(key)) == cb.Closed(key)
    opened, *rest = yield from transitions.join()
    assert isinstance(opened, cb.OpenTransition)
    assert opened.from_ == "Closed"
    assert opened.consecutive_openings == 1
    assert rest == [cb.HalfOpenTransition(key), cb.CloseTransition(key)]


def schedule_replays(advance: Advance):
    key = "schedule"
    breaker = yield from cb.make(
        trip_policy=cb.consecutive(2), open_duration=fx.schedule.exponential("200 millis")
    )
    collected = yield from openings(breaker, 4)
    yield from fail(breaker, key)
    yield from fail(breaker, key)
    yield from advance(0.3)
    # A failed probe reopens without consulting the trip policy.
    yield from fail(breaker, key)
    reopened = yield from breaker.state(key)
    assert isinstance(reopened, cb.Open)
    assert reopened.consecutive_openings == 2

    yield from advance(0.3)
    assert isinstance((yield from rejection(run_void(breaker, key))), cb.CircuitOpen)
    yield from advance(0.2)
    yield from run_void(breaker, key)
    assert isinstance((yield from breaker.state(key)), cb.Closed)

    # Closed for less than the last 400 millis opening.
    yield from fail(breaker, key)
    yield from fail(breaker, key)
    yield from advance(0.9)
    yield from run_void(breaker, key)
    # Closed for the whole of the last 800 millis opening.
    yield from advance(0.8)
    yield from fail(breaker, key)
    yield from fail(breaker, key)

    assert (yield from collected.join()) == [(200, 1), (400, 2), (800, 3), (200, 1)]


def reset_race(advance: Advance):
    key = "reset-race"
    breaker = yield from cb.make(
        trip_policy=cb.consecutive(1), open_duration=fx.schedule.exponential("200 millis")
    )
    collected = yield from openings(breaker, 2)
    yield from fail(breaker, key)
    yield from advance(0.3)
    yield from run_void(breaker, key)
    stale = yield from held(breaker, key, fx.fail("boom"))
    yield from advance(0.3)
    yield from run_void(breaker, key)
    yield from stale.release

    # The stale call computed its open time from a count of 2, while the
    # store restarted its count at 1.
    assert (yield from collected.join())[1] == (400, 1)


def schedule_from_recording_time(advance: Advance):
    key = "schedule-elapsed"
    breaker = yield from cb.make(
        trip_policy=cb.consecutive(1),
        open_duration=fx.schedule.exponential("100 millis").up_to(duration="250 millis"),
    )
    collected = yield from openings(breaker, 4)
    yield from fail(breaker, key)
    # Each gap exceeds the 250 millis cap, so a replay that saw wall time
    # would end the schedule at step 2 and repeat 100 millis.
    for _ in range(3):
        yield from advance(0.4)
        yield from fail(breaker, key)

    assert [m for m, _ in (yield from collected.join())] == [100, 200, 200, 200]


def retry_after_hint(advance: Advance):
    key = "hint"
    breaker = yield from cb.make(
        trip_policy=cb.consecutive(1), open_duration="200 millis", max_open_duration="600 millis"
    )
    yield from (
        fx.fail("boom")
        .pipe(breaker.execute(key=key, classify=lambda _: cb.failure(retry_after="1 hour")))
        .ignore()
    )
    yield from advance(0.3)
    assert isinstance((yield from rejection(run_void(breaker, key))), cb.CircuitOpen)
    yield from advance(0.4)
    yield from run_void(breaker, key)

    # Closed past open_duration, but not for the 600 millis the hinted
    # opening lasted, so the count carries over.
    yield from advance(0.3)
    yield from fail(breaker, key)
    reopened = yield from breaker.state(key)
    assert isinstance(reopened, cb.Open)
    assert reopened.consecutive_openings == 2

    # Without a hint, the opening lasts open_duration.
    yield from advance(0.3)
    yield from run_void(breaker, key)
    assert isinstance((yield from breaker.state(key)), cb.Closed)


def interrupts(advance: Advance):
    key = "interrupt"
    breaker = yield from cb.make(trip_policy=cb.consecutive(1), open_duration="200 millis")

    def classify(_: object) -> cb.Outcome:
        return cb.failure()

    interrupted = fx.fail_cause(fx.cause.interrupt())
    yield from interrupted.pipe(breaker.execute(key=key, classify=classify)).exit()
    assert isinstance((yield from breaker.state(key)), cb.Closed)

    yield from fail(breaker, key)
    yield from advance(0.3)
    probe = yield from held(breaker, key, fx.void, classify)
    yield from probe.fiber.interrupt()
    assert (yield from breaker.state(key)) == cb.HalfOpen(key, False, 1)

    # Interrupting the probe while it classifies also frees the slot.
    classifying = yield from fx.Deferred[None].make()
    classifying_probe = yield from (
        fx.void.pipe(
            breaker.execute(
                key=key, classify=lambda _: classifying.succeed(None).and_then(fx.never)
            )
        ).fork()
    )
    yield from classifying.wait()
    yield from classifying_probe.interrupt()
    released = yield from breaker.state(key)
    assert isinstance(released, cb.HalfOpen)
    assert not released.probing

    yield from run_void(breaker, key)
    assert isinstance((yield from breaker.state(key)), cb.Closed)


def stale_outcome(advance: Advance):
    a = "stale-a"
    b = "stale-b"
    breaker = yield from cb.make(trip_policy=cb.consecutive(1), open_duration="200 millis")
    stale_a = yield from held(breaker, a, fx.void)
    current_b = yield from held(breaker, b, fx.fail("boom"))

    yield from fail(breaker, a)
    yield from advance(0.3)
    probe = yield from held(breaker, a, fx.fail("boom"))

    assert isinstance((yield from stale_a.release), Success)
    assert isinstance((yield from current_b.release), Failure)
    half_open = yield from breaker.state(a)
    assert isinstance(half_open, cb.HalfOpen)
    assert half_open.probing
    assert isinstance((yield from breaker.state(b)), cb.Open)

    yield from probe.release
    reopened = yield from breaker.state(a)
    assert isinstance(reopened, cb.Open)
    assert reopened.consecutive_openings == 2


def idle_reset(advance: Advance):
    key = "idle-reset"
    breaker = yield from cb.make(trip_policy=cb.consecutive(1), open_duration="200 millis")
    yield from (
        fx.fail("boom")
        .pipe(breaker.execute(key=key, classify=lambda _: cb.failure(retry_after="1 second")))
        .ignore()
    )
    yield from advance(1.1)
    yield from run_void(breaker, key)
    yield from advance(0.5)
    yield from fail(breaker, key)

    state = yield from breaker.state(key)
    assert isinstance(state, cb.Open)
    assert state.consecutive_openings == 1


def idle_open(advance: Advance):
    key = "idle-open"
    breaker = yield from cb.make(trip_policy=cb.consecutive(1), open_duration="800 millis")
    yield from fail(breaker, key)
    yield from advance(0.6)
    opened = yield from breaker.state(key)
    assert isinstance(opened, cb.Open)
    assert opened.consecutive_openings == 1

    # Past the open time, so the failed probe is the second opening.
    yield from advance(0.3)
    yield from fail(breaker, key)
    reopened = yield from breaker.state(key)
    assert isinstance(reopened, cb.Open)
    assert reopened.consecutive_openings == 2


SUITE: list[tuple[str, Body]] = [
    (
        "consecutive: only a Success resets the streak, and the n-th failure opens without "
        "running the call",
        consecutive,
    ),
    (
        "rate: Ignored outcomes never count, and a Success can trip once minimumCalls are recorded",
        rate,
    ),
    ("half-open admits one probe, rejects the rest, and a success closes", half_open),
    (
        "a Schedule openDuration replays across openings, carries over a close shorter than the "
        "last opening, and resets once the circuit has stayed closed that long",
        schedule_replays,
    ),
    (
        "a call admitted before the reset deadline opens with its older count after a later "
        "admit resets it",
        reset_race,
    ),
    (
        "a Schedule openDuration replays from the recording time and repeats its last delay once "
        "it ends",
        schedule_from_recording_time,
    ),
    (
        "a Retry-After hint lengthens only the opening it causes and its reset window, capped at "
        "maxOpenDuration",
        retry_after_hint,
    ),
    ("an interrupt-only exit records Ignored and an interrupted probe frees its slot", interrupts),
    (
        "a stale outcome changes nothing, while another key's current permit still counts",
        stale_outcome,
    ),
]

IDLE_SUITE: list[tuple[str, Body]] = [
    (
        "idle expiry drops a key before a longer reset window ends and its next admit starts at "
        "count 0",
        idle_reset,
    ),
    (
        "an Open key outlives idleTimeToLive until its open time ends, so the backoff count "
        "survives",
        idle_open,
    ),
]

ALL = [*SUITE, *IDLE_SUITE]
IDS = [body.__name__ for _, body in ALL]
IDLE = {body.__name__ for _, body in IDLE_SUITE}
