"""Ports of Effect's ``Stream.test.ts``: the ``error handling`` and
``retry`` sections.

Each test's docstring is the Effect test title. ``Stream.catch`` is
``catch_all``; ``catchTag`` and refining ``catchIf`` remove errors from the
type, so they are the curried ``stream.catch_tag`` / ``stream.catch_if``
used with ``.pipe``; a ``Filter`` is a function returning ``Ok`` / ``Err``;
tagged errors are classes.

Adapted, with the reason:

- "typed recovery with mixed causes" leaves out ``catchTags``: tags are
  classes, and ``catch_tag`` takes a tuple of them.
- "retry - retries a failing stream according to a schedule" reads the
  test clock in seconds where Effect reads ``new Date(ms).getSeconds()``.

The three sink titles of the section ("run - upstream failures bypass sink
error handlers", "run - sink onExit observes interruption on upstream
failure", "pipeThrough - upstream failures bypass sink error handlers")
are in ``test_stream_sinks.py``, and the ``catchReason`` / ``catchReasons``
titles in ``test_stream_reasons.py``.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Never, TypeIs

import pyfect as fx
from pyfect import cause, schedule, stream, testing
from pyfect.cause import Cause
from pyfect.result import Err, Ok, Result
from pyfect.schedule import Metadata
from pyfect.stream import Stream

# --- error handling -------------------------------------------------------------


@testing.effect
def test_catch():
    """catch"""
    seen: list[str] = []

    def recover(error: str) -> Stream[int]:
        seen.append(error)
        return stream.make(4, 5, 6)

    results = yield from (
        stream.make(1, 2, 3).concat(stream.fail("boom")).catch_all(recover).run_collect()
    )
    assert results == [1, 2, 3, 4, 5, 6]
    assert seen == ["boom"]


@testing.effect
def test_tap_cause_preserves_failures():
    """tapCause preserves failures"""
    ex = yield from stream.fail("boom").tap_cause(lambda _: fx.void).run_collect().exit()
    testing.assert_exit_failure(ex, cause.fail("boom"))


@testing.effect
def test_tap_cause_preserves_defects():
    """tapCause preserves defects"""
    defect = RuntimeError("boom")
    ex = yield from stream.die(defect).tap_cause(lambda _: fx.void).run_collect().exit()
    testing.assert_exit_failure(ex, cause.die(defect))


@testing.effect
def test_catch_defect():
    """catchDefect"""
    defect = RuntimeError("boom")
    recovered = yield from stream.die(defect).catch_defect(stream.succeed).run_collect()
    failed = yield from (
        stream.fail("failure")
        .catch_defect(lambda _: stream.succeed("recovered"))
        .run_collect()
        .exit()
    )
    assert recovered == [defect]
    testing.assert_exit_failure(failed, cause.fail("failure"))


@dataclass(frozen=True)
class ErrorA:
    pass


@dataclass(frozen=True)
class ErrorB:
    pass


def _is_error_a(error: object) -> TypeIs[ErrorA]:
    return isinstance(error, ErrorA)


@testing.effect
def test_catch_if_with_refinement():
    """catchIf with refinement"""
    failing: Stream[Never, ErrorA | ErrorB] = stream.fail(ErrorB())
    recovered = failing.pipe(stream.catch_if(_is_error_a, lambda _: stream.succeed("ok")))
    ex = yield from recovered.run_collect().exit()
    assert ex == fx.exit.fail(ErrorB())


@testing.effect
def test_catch_if_with_refinement_or_else():
    """catchIf with refinement orElse"""
    failing: Stream[Never, ErrorA | ErrorB] = stream.fail(ErrorB())

    def fallback(_: ErrorB) -> Stream[str]:
        return stream.succeed("fallback")

    recovered = failing.pipe(
        stream.catch_if(_is_error_a, lambda _: stream.succeed("caught"), or_else=fallback)
    )
    assert (yield from recovered.run_collect()) == ["fallback"]


def _fail_either(error: str | int) -> Stream[Never, str | int]:
    return stream.fail(error)


@testing.effect
def test_catch_if_with_predicate():
    """catchIf with predicate"""
    failing = _fail_either("boom")
    recovered = failing.catch_if(
        lambda e: isinstance(e, str), lambda e: stream.succeed(f"caught: {e}")
    )
    assert (yield from recovered.run_collect()) == ["caught: boom"]


@testing.effect
def test_catch_if_predicate_no_match():
    """catchIf predicate no match"""
    failing = _fail_either(42)
    recovered = failing.catch_if(lambda e: isinstance(e, str), lambda _: stream.succeed("caught"))
    ex = yield from recovered.run_collect().exit()
    assert ex == fx.exit.fail(42)


def _length_or_fallback(error: str | int) -> Result[int, str]:
    return Ok(len(error)) if isinstance(error, str) else Err(f"fallback: {error}")


@testing.effect
def test_catch_if_with_filter_input():
    """catchIf with filter input"""

    def run(error: str | int) -> fx.Effect[list[str]]:
        return (
            _fail_either(error)
            .catch_filter(
                _length_or_fallback,
                lambda length: stream.succeed(f"caught: {length}"),
                or_else=stream.succeed,
            )
            .run_collect()
        )

    assert (yield from run("boom")) == ["caught: 4"]
    assert (yield from run(42)) == ["fallback: 42"]


@testing.effect
def test_catch_cause_filter():
    """catchCauseFilter"""

    def failures(c: Cause[str]) -> Result[object, Cause[str]]:
        return Ok(c.failures[0]) if c.has_fails else Err(c)

    recovered = yield from (
        stream.fail("boom")
        .catch_cause_filter(failures, lambda failure, _: stream.succeed(f"recovered: {failure}"))
        .run_collect()
    )
    assert recovered == ["recovered: boom"]


class HttpError(fx.TaggedError):
    pass


class ValidationError(fx.TaggedError):
    pass


@testing.effect
def test_catch_tag_or_else():
    """catchTag orElse"""
    failing: Stream[Never, HttpError | ValidationError] = stream.fail(ValidationError())

    def fallback(_: ValidationError) -> Stream[str]:
        return stream.succeed("fallback")

    recovered = failing.pipe(
        stream.catch_tag(HttpError, lambda _: stream.succeed("http"), or_else=fallback)
    )
    assert (yield from recovered.run_collect()) == ["fallback"]


# --- ignore / ignoreCause -------------------------------------------------------


@dataclass(frozen=True)
class _Captured:
    log_level: fx.LogLevel
    cause: Cause[object]


def _run_ignoring(
    ignore: Callable[[Stream[Never, str]], Stream[Never]],
    current_log_level: fx.logger.Severity = fx.LogLevel.INFO,
    unhandled_log_level: fx.logger.Severity | None = fx.LogLevel.ERROR,
) -> list[_Captured]:
    captured: list[_Captured] = []
    capture = fx.Logger.make(lambda o: captured.append(_Captured(o.log_level, o.cause)))
    testing.run_test(
        ignore(stream.fail("boom"))
        .run_drain()
        .pipe(fx.provide(fx.logger.layer([capture])))
        .pipe(fx.provide_service(fx.MinimumLogLevel, fx.LogLevel.TRACE))
        .pipe(fx.provide_service(fx.CurrentLogLevel, current_log_level))
        .pipe(fx.provide_service(fx.UnhandledLogLevel, unhandled_log_level))
    )
    return captured


def _fails_with_boom(c: Cause[object]) -> bool:
    return c.failures == ("boom",)


def test_ignore_does_not_log_when_log_is_omitted() -> None:
    """does not log when log is omitted"""
    assert _run_ignoring(lambda s: s.ignore()) == []


def test_ignore_does_not_log_when_log_is_false() -> None:
    """does not log when log is false"""
    assert _run_ignoring(lambda s: s.ignore(log=False)) == []


def test_ignore_logs_with_the_current_level_when_log_is_true() -> None:
    """logs with the current level when log is true"""
    logs = _run_ignoring(lambda s: s.ignore(log=True), fx.LogLevel.WARN)
    assert len(logs) == 1
    assert logs[0].log_level is fx.LogLevel.WARN
    assert _fails_with_boom(logs[0].cause)


def test_ignore_logs_with_the_provided_level_when_log_is_a_log_level() -> None:
    """logs with the provided level when log is a LogLevel"""
    logs = _run_ignoring(lambda s: s.ignore(log=fx.LogLevel.ERROR), fx.LogLevel.WARN)
    assert len(logs) == 1
    assert logs[0].log_level is fx.LogLevel.ERROR
    assert _fails_with_boom(logs[0].cause)


def test_ignore_logs_with_the_unhandled_level_when_log_is_unhandled() -> None:
    """logs with the unhandled level when log is Unhandled"""
    logs = _run_ignoring(lambda s: s.ignore(log="Unhandled"), fx.LogLevel.INFO, fx.LogLevel.WARN)
    assert len(logs) == 1
    assert logs[0].log_level is fx.LogLevel.WARN
    assert _fails_with_boom(logs[0].cause)


def test_ignore_skips_logging_when_log_is_unhandled_and_the_level_is_none() -> None:
    assert _run_ignoring(lambda s: s.ignore(log="Unhandled"), fx.LogLevel.INFO, None) == []


def test_ignore_cause_logs_with_the_unhandled_level_when_log_is_unhandled() -> None:
    logs = _run_ignoring(
        lambda s: s.ignore_cause(log="Unhandled"), fx.LogLevel.INFO, fx.LogLevel.WARN
    )
    assert [log.log_level for log in logs] == [fx.LogLevel.WARN]


def test_ignore_cause_does_not_log_when_log_is_omitted() -> None:
    """does not log when log is omitted"""
    assert _run_ignoring(lambda s: s.ignore_cause()) == []


def test_ignore_cause_does_not_log_when_log_is_false() -> None:
    """does not log when log is false"""
    assert _run_ignoring(lambda s: s.ignore_cause(log=False)) == []


def test_ignore_cause_logs_with_the_current_level_when_log_is_true() -> None:
    """logs with the current level when log is true"""
    logs = _run_ignoring(lambda s: s.ignore_cause(log=True), fx.LogLevel.WARN)
    assert len(logs) == 1
    assert logs[0].log_level is fx.LogLevel.WARN
    assert _fails_with_boom(logs[0].cause)


def test_ignore_cause_logs_with_the_provided_level_when_log_is_a_log_level() -> None:
    """logs with the provided level when log is a LogLevel"""
    logs = _run_ignoring(lambda s: s.ignore_cause(log=fx.LogLevel.ERROR), fx.LogLevel.WARN)
    assert len(logs) == 1
    assert logs[0].log_level is fx.LogLevel.ERROR
    assert _fails_with_boom(logs[0].cause)


# --- typed recovery with mixed causes -------------------------------------------


class MixedError(fx.TaggedError):
    pass


_mixed = MixedError()
_mixed_defect = RuntimeError("boom")
_recovered = stream.succeed("recovered")

type _Recovery = Callable[[Stream[str, MixedError]], Stream[Any, Any]]


def _fail_once(failing: Stream[str, MixedError]) -> Stream[str, MixedError]:
    attempts = 0

    def pick() -> Stream[str, MixedError]:
        nonlocal attempts
        attempts += 1
        return failing if attempts == 1 else stream.succeed("retried")

    return stream.suspend(pick)


_recoveries: dict[str, _Recovery] = {
    "catch": lambda s: s.catch_all(lambda _: _recovered),
    "catchTag": lambda s: s.pipe(stream.catch_tag(MixedError, lambda _: _recovered)),
    "catchIf": lambda s: s.catch_if(lambda _: True, lambda _: _recovered),
    "catchFilter": lambda s: s.catch_filter(Ok, lambda _: _recovered),
    "orElseSucceed": lambda s: s.or_else_succeed(lambda _: "recovered"),
    "ignore": lambda s: s.ignore(),
    "result": lambda s: s.result(),
    "retry": lambda s: _fail_once(s).retry(schedule.recurs(1)),
}


def _fail_with(*reasons: cause.Reason[MixedError]) -> Stream[str, MixedError]:
    return stream.make("a").concat(stream.fail_cause(cause.from_reasons(reasons)))


def _reasons_of(ex: fx.Exit[Any, Any]) -> list[tuple[str, object]] | fx.Exit[Any, Any]:
    if not isinstance(ex, fx.Failure):
        return ex
    out: list[tuple[str, object]] = []
    for reason in ex.cause.reasons:
        if isinstance(reason, cause.Fail):
            out.append(("Fail", reason.error))
        elif isinstance(reason, cause.Die):
            defect = reason.defect
            out.append(("Die", defect.error if isinstance(defect, fx.UnhandledError) else defect))
        else:
            out.append(("Interrupt", reason.fiber_id))
    return out


@testing.effect
def test_defects_take_precedence_over_typed_errors():
    """defects take precedence over typed errors"""
    with_or_die: dict[str, _Recovery] = {**_recoveries, "orDie": lambda s: s.or_die()}
    for name, recover in with_or_die.items():
        fail_and_die = _fail_with(cause.Fail(_mixed), cause.Die(_mixed_defect))
        ex = yield from recover(fail_and_die).run_collect().exit()
        assert _reasons_of(ex) == [("Die", _mixed), ("Die", _mixed_defect)], name

        fail_interrupt_and_die = _fail_with(
            cause.Fail(_mixed), cause.Interrupt(1), cause.Die(_mixed_defect)
        )
        ex = yield from recover(fail_interrupt_and_die).run_collect().exit()
        expected = [("Die", _mixed), ("Interrupt", 1), ("Die", _mixed_defect)]
        assert _reasons_of(ex) == expected, name


@testing.effect
def test_interrupts_beside_a_typed_error_do_not_block_recovery():
    """interrupts beside a typed error do not block recovery"""
    for name, recover in _recoveries.items():
        failing = _fail_with(cause.Fail(_mixed), cause.Interrupt(1))
        ex = yield from recover(failing).run_collect().exit()
        assert isinstance(ex, fx.Success), name


@testing.effect
def test_error_mapping_keeps_defects_and_interrupts():
    """error mapping keeps defects and interrupts"""
    failing = _fail_with(cause.Fail(_mixed), cause.Interrupt(1), cause.Die(_mixed_defect))
    mappings: dict[str, Stream[Any, Any]] = {
        "mapError": failing.map_error(lambda _: "mapped"),
        "mapBoth": failing.map_both(on_element=lambda a: a, on_error=lambda _: "mapped"),
    }
    for name, mapped in mappings.items():
        ex = yield from mapped.run_collect().exit()
        assert _reasons_of(ex) == [("Fail", "mapped"), ("Interrupt", 1), ("Die", _mixed_defect)], (
            name
        )


# --- retry ----------------------------------------------------------------------


@testing.effect
def test_retry_retries_a_failing_stream():
    """retry - retries a failing stream"""
    ref = yield from fx.Ref.make(0)
    failing = stream.from_effect(ref.get_and_update(lambda n: n + 1)).concat(stream.fail(None))
    result = yield from failing.retry(schedule.forever).take(2).run_collect()
    assert result == [0, 1]


@testing.effect
def test_retry_cleans_up_resources_before_restarting_the_stream():
    """retry - cleans up resources before restarting the stream"""
    ref = yield from fx.Ref.make(0)
    failing: Stream[int, None] = stream.unwrap(
        fx.add_finalizer(lambda _: ref.get_and_update(lambda n: n + 1)).as_(
            stream.from_effect(ref.get()).concat(stream.fail(None))
        )
    )
    result = yield from failing.retry(schedule.forever).take(2).run_collect()
    assert result == [0, 1]


@testing.effect
def test_retry_retries_a_failing_stream_according_to_a_schedule():
    """retry - retries a failing stream according to a schedule"""
    times: list[float] = []
    failing = stream.from_effect(fx.clock.current_time_millis().map(times.append)).flat_map(
        lambda _: stream.fail(None)
    )
    fiber = yield from (failing.retry(schedule.exponential("1 second")).take(3).run_drain().fork())
    yield from testing.adjust("1 second")
    yield from testing.adjust("2 seconds")
    yield from fiber.interrupt()
    assert [round(t) for t in reversed(times)] == [3_000, 1_000, 0]


@testing.effect
def test_retry_reset_the_schedule_after_a_successful_pull():
    """retry - reset the schedule after a successful pull"""
    times: list[float] = []
    ref = yield from fx.Ref.make(0)

    @fx.fn
    def attempt():
        times.insert(0, (yield from fx.clock.current_time_millis()))
        return (yield from ref.update_and_get(lambda n: n + 1))

    def pick(n: int) -> Stream[int, None]:
        return stream.succeed(n) if n in (3, 5) else stream.fail(None)

    retried = stream.from_effect(attempt()).flat_map(pick).forever()
    fiber = yield from retried.retry(schedule.exponential("1 second")).take(2).run_drain().fork()
    yield from testing.adjust("1 second")
    yield from testing.adjust("2 seconds")
    yield from testing.adjust("1 second")
    yield from fiber.join()
    assert [round(t) for t in times] == [4_000, 3_000, 3_000, 1_000, 0]


@testing.effect
def test_retry_schedule_current_metadata():
    """retry - Schedule.CurrentMetadata"""
    seen: list[Metadata[object, object]] = []

    def record(_: int) -> fx.Effect[None]:
        return schedule.CurrentMetadata().map(seen.append)

    fiber = yield from (
        stream.fail(1)
        .tap_error(record)
        .retry(schedule.exponential("1 second"))
        .run_drain()
        .fork(start_immediately=True)
    )
    yield from testing.adjust("7 seconds")
    yield from fiber.interrupt()

    def meta(attempt: int, now: float, since: float, delay: float) -> Metadata[object, object]:
        return Metadata(
            input=None if attempt == 0 else 1,
            output=None if attempt == 0 else delay,
            duration=fx.duration.Seconds(delay),
            attempt=attempt,
            start=0.0,
            now=now * 1000,
            elapsed=fx.duration.Seconds(now),
            elapsed_since_previous=fx.duration.Seconds(since),
        )

    assert seen == [meta(0, 0, 0, 0), meta(1, 0, 0, 1), meta(2, 1, 1, 2), meta(3, 3, 2, 4)]
