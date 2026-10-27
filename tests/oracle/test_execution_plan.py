"""Ports of Effect's ``ExecutionPlan.test.ts``.

Each test's docstring is the Effect test title. Steps are
``execution_plan.Step(provide, attempts=, while_=, schedule=)``;
``Effect.withExecutionPlan`` / ``Stream.withExecutionPlan`` are the curried
``fx.with_execution_plan`` / ``stream.with_execution_plan``; events are
dataclasses matched by class; ``Cause.squash`` is the failure's error or
defect; ``Effect.die("boom")`` dies with an exception; ``Number.MAX_SAFE_INTEGER``
attempts is ``2**53 - 1``.
"""

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Never

import pytest

import pyfect as fx
from pyfect import cause, execution_plan, layer, schedule, stream, testing
from pyfect.cause import Cause, Fail
from pyfect.context import Context
from pyfect.execution_plan import (
    AttemptFailure,
    AttemptStart,
    AttemptSuccess,
    CurrentMetadata,
    Event,
    Metadata,
    Step,
)
from pyfect.stream import Stream


@dataclass(frozen=True)
class ServiceShape:
    stream: Stream[int, str]


class Service(fx.Tag[ServiceShape]):
    pass


SERVICE_A = layer.effect(Service, fx.succeed(ServiceShape(stream.fail("A"))))
SERVICE_B = layer.succeed(Service, ServiceShape(stream.fail("B")))
SERVICE_C = layer.succeed(Service, ServiceShape(stream.make(1, 2, 3)))

PLAN = execution_plan.make(Step(SERVICE_A), Step(SERVICE_B), Step(SERVICE_C))

PLAN_PARTIAL = execution_plan.make(
    Step(layer.succeed(Service, ServiceShape(stream.make(1, 2, 3).concat(stream.fail("Partial"))))),
    Step(SERVICE_C),
)

SERVICE_STREAM: Stream[int, str, Service] = stream.unwrap(Service().map(lambda s: s.stream))


def _push[A](items: list[A]) -> Callable[[A], fx.Effect[None]]:
    def push(item: A) -> fx.Effect[None]:
        return fx.sync(lambda: items.append(item))

    return push


# --- make -----------------------------------------------------------------------


def test_rejects_zero_attempts() -> None:
    """rejects zero attempts"""
    message = "ExecutionPlan.make: step[0].attempts must be greater than 0"
    with pytest.raises(ValueError, match=re.escape(message)):
        execution_plan.make(Step(Context.empty(), attempts=0))


# --- captureRequirements --------------------------------------------------------


@dataclass(frozen=True)
class PolicyShape:
    allow: bool


class Policy(fx.Tag[PolicyShape]):
    pass


def _fail_once() -> fx.Effect[str, str]:
    attempts = 0

    def run() -> fx.Effect[str, str]:
        nonlocal attempts
        attempts += 1
        return fx.fail("busy") if attempts == 1 else fx.succeed("ok")

    return fx.suspend(run)


def _allowed(_: str) -> fx.Effect[bool, Never, Policy]:
    return Policy().map(lambda p: p.allow)


CAPTURE_PLAN = execution_plan.make(Step(Context.empty(), attempts=2, while_=_allowed))


@testing.effect
def test_captures_while_predicate_requirements():
    """captures while predicate requirements"""
    captured = yield from CAPTURE_PLAN.capture_requirements.pipe(
        fx.provide_service(Policy, PolicyShape(allow=True))
    )
    result = yield from _fail_once().pipe(fx.with_execution_plan(captured))
    assert result == "ok"


@testing.effect
def test_prefers_captured_while_predicate_requirements_over_the_ambient_context():
    """prefers captured while predicate requirements over the ambient context"""
    captured = yield from CAPTURE_PLAN.capture_requirements.pipe(
        fx.provide_service(Policy, PolicyShape(allow=True))
    )
    program = _fail_once().pipe(fx.with_execution_plan(captured))
    result = yield from program.pipe(fx.provide_service(Policy, PolicyShape(allow=False)))
    assert result == "ok"


@testing.effect
def test_captures_schedule_requirements():
    """captures schedule requirements"""

    def check(_: object) -> fx.Effect[None, str, Policy]:
        return Policy().flat_map(lambda p: fx.void if p.allow else fx.fail("denied"))

    schedule_plan = execution_plan.make(
        Step(layer.empty, schedule=schedule.recurs(1).map_effect(check))
    )
    captured = yield from schedule_plan.capture_requirements.pipe(
        fx.provide_service(Policy, PolicyShape(allow=True))
    )
    for ambient in (None, PolicyShape(allow=False)):
        program = _fail_once().pipe(fx.with_execution_plan(captured))
        if ambient is not None:
            program = program.pipe(fx.provide_service(Policy, ambient))
        assert (yield from program) == "ok"


# --- Stream.withExecutionPlan ---------------------------------------------------


@testing.effect
def test_limits_attempts_after_partial_stream_failures():
    """limits attempts after partial stream failures"""
    runs = 0

    def run() -> int:
        nonlocal runs
        runs += 1
        return 1

    source = stream.from_effect(fx.sync(run)).concat(stream.fail("boom"))
    plan = execution_plan.make(Step(Context.empty(), attempts=3))
    items: list[int] = []
    ex = yield from (
        source.pipe(stream.with_execution_plan(plan)).run_for_each(_push(items)).exit()
    )
    assert items == [1, 1, 1]
    assert runs == 3
    testing.assert_exit_failure(ex, cause.fail("boom"))


@testing.effect
def test_allows_interruption_between_retries_after_partial_stream_failures():
    """allows interruption between retries after partial stream failures"""
    runs = 0
    retried = yield from fx.Latch.make()

    @fx.gen
    def one():
        nonlocal runs
        runs += 1
        if runs > 1:
            yield from retried.open()
        return 1

    source = stream.from_effect(one).concat(stream.fail("boom"))
    plan = execution_plan.make(Step(Context.empty(), attempts=2**53 - 1))
    fiber = yield from (
        source.pipe(stream.with_execution_plan(plan))
        .run_drain()
        .pipe(fx.provide_service(fx.PreventSchedulerYield, True))
        .fork()
    )
    yield from retried.wait()
    yield from fiber.interrupt()
    ex = yield from fiber.await_exit()
    assert runs > 1
    assert isinstance(ex, fx.Failure)
    assert ex.cause.has_interrupts


@testing.effect
def test_falls_back_through_failing_layers_and_records_stream_attempt_metadata():
    """falls back through failing layers and records stream attempt metadata"""
    items: list[int] = []
    metadata: list[Metadata] = []
    ex = yield from (
        SERVICE_STREAM.on_start(CurrentMetadata().flat_map(_push(metadata)))
        .pipe(stream.with_execution_plan(PLAN))
        .run_for_each(_push(items))
        .exit()
    )
    assert items == [1, 2, 3]
    assert metadata == [Metadata(1, 0), Metadata(2, 1), Metadata(3, 2)]
    assert isinstance(ex, fx.Success)


@testing.effect
def test_falls_back_after_a_stream_emits_partial_items_by_default():
    """falls back after a stream emits partial items by default"""
    items: list[int] = []
    ex = yield from (
        SERVICE_STREAM.pipe(stream.with_execution_plan(PLAN_PARTIAL))
        .run_for_each(_push(items))
        .exit()
    )
    assert items == [1, 2, 3, 1, 2, 3]
    assert isinstance(ex, fx.Success)


@testing.effect
def test_fails_on_a_partial_stream_when_fallback_is_disabled():
    """fails on a partial stream when fallback is disabled"""
    items: list[int] = []
    ex = yield from (
        SERVICE_STREAM.pipe(
            stream.with_execution_plan(PLAN_PARTIAL, prevent_fallback_on_partial_stream=True)
        )
        .run_for_each(_push(items))
        .exit()
    )
    assert items == [1, 2, 3]
    testing.assert_exit_failure(ex, cause.fail("Partial"))


# --- onEvent --------------------------------------------------------------------


class _Collector:
    def __init__(self) -> None:
        self.events: list[Event[Any]] = []

    def on_event(self, event: Event[object]) -> fx.Effect[None]:
        return fx.sync(lambda: self.events.append(event))

    def simplified(self) -> list[dict[str, object]]:
        return [_simplify(event) for event in self.events]


def _squash(c: Cause[Any]) -> object:
    found = c.find_fail()
    return found.error if isinstance(found, Fail) else c.find_defect()


def _simplify(event: Event[Any]) -> dict[str, object]:
    simple: dict[str, object] = {
        "tag": type(event).__name__,
        "attempt": event.attempt,
        "step_attempt": event.step_attempt,
        "step_index": event.step_index,
    }
    if isinstance(event, AttemptFailure):
        simple["error"] = _squash(event.cause)
    return simple


def _event(
    tag: str, attempt: int, step_attempt: int, step_index: int, *error: object
) -> dict[str, object]:
    simple: dict[str, object] = {
        "tag": tag,
        "attempt": attempt,
        "step_attempt": step_attempt,
        "step_index": step_index,
    }
    if error:
        simple["error"] = error[0]
    return simple


def _start(attempt: int, step_attempt: int, step_index: int) -> dict[str, object]:
    return _event("AttemptStart", attempt, step_attempt, step_index)


def _success(attempt: int, step_attempt: int, step_index: int) -> dict[str, object]:
    return _event("AttemptSuccess", attempt, step_attempt, step_index)


def _failure(attempt: int, step_attempt: int, step_index: int, error: object) -> dict[str, object]:
    return _event("AttemptFailure", attempt, step_attempt, step_index, error)


def _fail_until_third() -> fx.Effect[int, str]:
    runs = 0

    def run() -> fx.Effect[int, str]:
        nonlocal runs
        runs += 1
        return fx.fail(f"fail-{runs}") if runs < 3 else fx.succeed(runs)

    return fx.suspend(run)


def _observer_dies(tags: list[str]) -> Callable[[Event[object]], fx.Effect[None]]:
    def on_event(event: Event[object]) -> fx.Effect[None]:
        return fx.sync(lambda: tags.append(type(event).__name__)).and_then(
            fx.die(RuntimeError("observer-defect"))
        )

    return on_event


SINGLE = execution_plan.make(Step(Context.empty()))


@testing.effect
def test_effect_emits_start_and_success_on_first_attempt():
    """emits start and success on first attempt"""
    collector = _Collector()
    result = yield from fx.succeed(1).pipe(
        fx.with_execution_plan(SINGLE, on_event=collector.on_event)
    )
    assert result == 1
    assert collector.simplified() == [_start(1, 1, 0), _success(1, 1, 0)]
    success = collector.events[1]
    assert isinstance(success, AttemptSuccess)
    assert isinstance(success.duration, float)


@testing.effect
def test_effect_observer_defects_do_not_change_the_outcome_or_leave_attempts_unpaired():
    """observer defects do not change the outcome or leave attempts unpaired"""
    tags: list[str] = []
    ex = yield from (
        fx.succeed("source-success")
        .pipe(fx.with_execution_plan(SINGLE, on_event=_observer_dies(tags)))
        .exit()
    )
    assert ex == fx.Success("source-success")
    assert tags == ["AttemptStart", "AttemptSuccess"]


@testing.effect
def test_effect_emits_an_event_pair_per_attempt_within_a_step():
    """emits an event pair per attempt within a step"""
    collector = _Collector()
    plan = execution_plan.make(Step(Context.empty(), attempts=3))
    result = yield from _fail_until_third().pipe(
        fx.with_execution_plan(plan, on_event=collector.on_event)
    )
    assert result == 3
    assert collector.simplified() == [
        _start(1, 1, 0),
        _failure(1, 1, 0, "fail-1"),
        _start(2, 2, 0),
        _failure(2, 2, 0, "fail-2"),
        _start(3, 3, 0),
        _success(3, 3, 0),
    ]


@testing.effect
def test_effect_fails_over_to_the_next_step_without_replaying_events():
    """fails over to the next step without replaying events"""
    collector = _Collector()
    plan = execution_plan.make(Step(Context.empty(), attempts=2), Step(Context.empty(), attempts=2))
    result = yield from _fail_until_third().pipe(
        fx.with_execution_plan(plan, on_event=collector.on_event)
    )
    assert result == 3
    assert collector.simplified() == [
        _start(1, 1, 0),
        _failure(1, 1, 0, "fail-1"),
        _start(2, 2, 0),
        _failure(2, 2, 0, "fail-2"),
        _start(3, 1, 1),
        _success(3, 1, 1),
    ]


@testing.effect
def test_effect_event_attempt_matches_current_metadata_across_a_failover_boundary():
    """event attempt matches CurrentMetadata across a failover boundary"""
    collector = _Collector()
    inside: list[Metadata] = []
    runs = 0

    @fx.gen
    def task():
        nonlocal runs
        inside.append((yield from CurrentMetadata()))
        runs += 1
        if runs < 3:
            return (yield from fx.fail("boom"))
        return runs

    plan = execution_plan.make(Step(Context.empty(), attempts=2), Step(Context.empty(), attempts=2))
    result = yield from task.pipe(fx.with_execution_plan(plan, on_event=collector.on_event))
    assert result == 3
    assert inside == [Metadata(1, 0), Metadata(2, 0), Metadata(3, 1)]
    starts = [
        Metadata(e.attempt, e.step_index) for e in collector.events if isinstance(e, AttemptStart)
    ]
    assert starts == inside


@testing.effect
def test_effect_emits_attempt_failure_when_a_step_layer_fails_to_build():
    """emits AttemptFailure when a step layer fails to build"""
    collector = _Collector()
    plan = execution_plan.make(Step(layer.effect(Service, fx.fail("nope"))), Step(SERVICE_C))
    result = yield from SERVICE_STREAM.run_collect().pipe(
        fx.with_execution_plan(plan, on_event=collector.on_event)
    )
    assert result == [1, 2, 3]
    assert collector.simplified() == [
        _start(1, 1, 0),
        _failure(1, 1, 0, "nope"),
        _start(2, 1, 1),
        _success(2, 1, 1),
    ]


@testing.effect
def test_effect_emits_attempt_failure_when_interrupted_mid_attempt():
    """emits AttemptFailure when interrupted mid-attempt"""
    collector = _Collector()
    started = yield from fx.Latch.make()
    task = started.open().and_then(fx.never)
    plan = execution_plan.make(Step(Context.empty(), attempts=2))
    fiber = yield from task.pipe(fx.with_execution_plan(plan, on_event=collector.on_event)).fork()
    yield from started.wait()
    yield from fiber.interrupt()
    ex = yield from fiber.await_exit()
    _assert_interrupted_attempt(ex, collector.events)


def _assert_interrupted_attempt(ex: fx.Exit[Any, Any], events: list[Event[Any]]) -> None:
    assert isinstance(ex, fx.Failure)
    assert ex.cause.has_interrupts
    assert len(events) == 2
    assert _simplify(events[0]) == _start(1, 1, 0)
    failure = events[1]
    assert isinstance(failure, AttemptFailure)
    assert failure.attempt == 1
    assert failure.cause.has_interrupts


@testing.effect
def test_effect_emits_attempt_failure_for_defects_without_retrying():
    """emits AttemptFailure for defects without retrying"""
    collector = _Collector()
    defect = RuntimeError("boom")
    plan = execution_plan.make(Step(Context.empty(), attempts=2), Step(Context.empty()))
    ex = yield from (
        fx.die(defect).pipe(fx.with_execution_plan(plan, on_event=collector.on_event)).exit()
    )
    testing.assert_exit_failure(ex, cause.die(defect))
    assert collector.simplified() == [_start(1, 1, 0), _failure(1, 1, 0, defect)]


@testing.effect
def test_stream_observer_defects_do_not_change_the_outcome_or_leave_attempts_unpaired():
    """observer defects do not change the outcome or leave attempts unpaired"""
    tags: list[str] = []
    ex = yield from (
        stream.succeed("source-success")
        .pipe(stream.with_execution_plan(SINGLE, on_event=_observer_dies(tags)))
        .run_collect()
        .exit()
    )
    assert ex == fx.Success(["source-success"])
    assert tags == ["AttemptStart", "AttemptSuccess"]


@testing.effect
def test_stream_emits_events_for_each_step_attempt():
    """emits events for each step attempt"""
    collector = _Collector()
    items = yield from SERVICE_STREAM.pipe(
        stream.with_execution_plan(PLAN, on_event=collector.on_event)
    ).run_collect()
    assert items == [1, 2, 3]
    assert collector.simplified() == [
        _start(1, 1, 0),
        _failure(1, 1, 0, "A"),
        _start(2, 1, 1),
        _failure(2, 1, 1, "B"),
        _start(3, 1, 2),
        _success(3, 1, 2),
    ]


@testing.effect
def test_stream_emits_an_event_pair_per_attempt_within_a_step():
    """emits an event pair per attempt within a step"""
    collector = _Collector()
    source = stream.make(1).concat(stream.fail("boom"))
    plan = execution_plan.make(Step(Context.empty(), attempts=3))
    ex = yield from (
        source.pipe(stream.with_execution_plan(plan, on_event=collector.on_event))
        .run_drain()
        .exit()
    )
    testing.assert_exit_failure(ex, cause.fail("boom"))
    assert collector.simplified() == [
        _start(1, 1, 0),
        _failure(1, 1, 0, "boom"),
        _start(2, 2, 0),
        _failure(2, 2, 0, "boom"),
        _start(3, 3, 0),
        _failure(3, 3, 0, "boom"),
    ]


@testing.effect
def test_stream_emits_events_when_falling_back_after_a_partial_stream():
    """emits events when falling back after a partial stream"""
    collector = _Collector()
    items = yield from SERVICE_STREAM.pipe(
        stream.with_execution_plan(PLAN_PARTIAL, on_event=collector.on_event)
    ).run_collect()
    assert items == [1, 2, 3, 1, 2, 3]
    assert collector.simplified() == [
        _start(1, 1, 0),
        _failure(1, 1, 0, "Partial"),
        _start(2, 1, 1),
        _success(2, 1, 1),
    ]


@testing.effect
def test_stream_emits_attempt_failure_when_interrupted_mid_attempt():
    """emits AttemptFailure when interrupted mid-attempt"""
    collector = _Collector()
    started = yield from fx.Latch.make()
    source = stream.from_effect(started.open().and_then(fx.never))
    plan = execution_plan.make(Step(Context.empty(), attempts=2))
    fiber = yield from (
        source.pipe(stream.with_execution_plan(plan, on_event=collector.on_event))
        .run_drain()
        .fork()
    )
    yield from started.wait()
    yield from fiber.interrupt()
    ex = yield from fiber.await_exit()
    _assert_interrupted_attempt(ex, collector.events)


@testing.effect
def test_stream_emits_attempt_failure_for_defects_without_retrying():
    """emits AttemptFailure for defects without retrying"""
    collector = _Collector()
    defect = RuntimeError("boom")
    plan = execution_plan.make(Step(Context.empty(), attempts=2), Step(Context.empty()))
    ex = yield from (
        stream.from_effect(fx.die(defect))
        .pipe(stream.with_execution_plan(plan, on_event=collector.on_event))
        .run_drain()
        .exit()
    )
    testing.assert_exit_failure(ex, cause.die(defect))
    assert collector.simplified() == [_start(1, 1, 0), _failure(1, 1, 0, defect)]


@testing.effect
def test_stream_emits_events_when_a_partial_stream_fails_with_fallback_disabled():
    """emits events when a partial stream fails with fallback disabled"""
    collector = _Collector()
    ex = yield from (
        SERVICE_STREAM.pipe(
            stream.with_execution_plan(
                PLAN_PARTIAL,
                prevent_fallback_on_partial_stream=True,
                on_event=collector.on_event,
            )
        )
        .run_drain()
        .exit()
    )
    testing.assert_exit_failure(ex, cause.fail("Partial"))
    assert collector.simplified() == [_start(1, 1, 0), _failure(1, 1, 0, "Partial")]
