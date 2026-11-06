"""ErrorReporter and ``with_error_reporting``.

Effect 4.0.6 has no ``ErrorReporter.test.ts``; the expected reports here
were printed by Effect's ``ErrorReporter.ts`` under Node (the same
programs, with a reporter recording each report's error message,
severity and attributes).
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

import pyfect as fx
from pyfect import error_reporter, testing
from pyfect.cause import die, fail, interrupt


def _recorder() -> tuple[list[error_reporter.Report], fx.ErrorReporter]:
    reports: list[error_reporter.Report] = []
    return reports, error_reporter.make(reports.append)


def _messages(reports: Sequence[error_reporter.Report]) -> list[str]:
    return [str(r.error) for r in reports]


def _reporting[A, E](
    eff: fx.Effect[A, E], reporters: Sequence[fx.ErrorReporter]
) -> fx.Effect[fx.Exit[A, E]]:
    return eff.exit().pipe(fx.provide(error_reporter.layer(reporters)))


@dataclass(eq=False)
class Boom(fx.TaggedError):
    message: str


@testing.effect
def test_a_failure_is_reported_once_and_still_fails():
    reports, reporter = _recorder()
    error = Boom("a")
    ex = yield from _reporting(fx.fail(error).with_error_reporting(), [reporter])
    assert ex == fx.Failure(fail(error))
    assert _messages(reports) == ["a"]
    (only,) = reports
    assert only.cause == fail(error)
    assert only.error is error
    assert only.severity == fx.LogLevel.INFO
    assert only.attributes == {}


@testing.effect
def test_nested_reporting_reports_a_cause_once():
    reports, reporter = _recorder()
    eff = fx.fail(Boom("a")).with_error_reporting().with_error_reporting()
    yield from _reporting(eff, [reporter])
    assert _messages(reports) == ["a"]


@testing.effect
def test_a_defect_is_reported():
    reports, reporter = _recorder()
    yield from _reporting(fx.die(ValueError("d")).with_error_reporting(), [reporter])
    assert _messages(reports) == ["d"]


@testing.effect
def test_interruptions_are_not_reported():
    reports, reporter = _recorder()
    ex = yield from _reporting(fx.interrupt().with_error_reporting(), [reporter])
    assert isinstance(ex, fx.Failure) and ex.cause.has_interrupts_only
    cause = fail(Boom("f")) + interrupt(3)
    ex = yield from _reporting(fx.fail_cause(cause).with_error_reporting(), [reporter])
    assert ex == fx.Failure(cause)
    assert _messages(reports) == ["f"]


@testing.effect
def test_defects_only_skips_a_cause_without_a_defect():
    reports, reporter = _recorder()
    yield from _reporting(fx.fail(Boom("a")).with_error_reporting(defects_only=True), [reporter])
    assert reports == []
    mixed = fx.fail_cause(fail(Boom("f")) + die(ValueError("d")))
    yield from _reporting(mixed.with_error_reporting(defects_only=True), [reporter])
    assert _messages(reports) == ["f", "d"]


@testing.effect
def test_the_same_error_object_is_reported_once():
    reports, reporter = _recorder()
    error = Boom("same")
    once = fx.fail(error).with_error_reporting().exit()
    yield from _reporting(once.and_then(once), [reporter])
    assert _messages(reports) == ["same"]


@testing.effect
def test_a_builtin_exception_is_remembered_too():
    """Effect remembers every ``Error``. CPython cannot weakly reference a
    built-in exception (``ValueError``...), the usual defect, so it is
    remembered on the exception itself: a reused defect, and a typed error
    carried into a new cause by ``map_error``, are reported once (printed
    by Effect under Node: ``["d", "f"]``)."""
    reports, reporter = _recorder()
    defect = TypeError("d")

    def once() -> fx.Effect[object]:
        return fx.die(defect).with_error_reporting().exit()

    yield from _reporting(once().and_then(once()), [reporter])
    error = ValueError("f")
    mapped = fx.fail(error).with_error_reporting().map_error(lambda e: e).with_error_reporting()
    yield from _reporting(mapped, [reporter])
    assert _messages(reports) == ["d", "f"]


@testing.effect
def test_each_reporter_remembers_a_builtin_exception_on_its_own():
    first, one = _recorder()
    second, two = _recorder()
    defect = TypeError("d")
    yield from _reporting(fx.die(defect).with_error_reporting(), [one])
    yield from _reporting(fx.die(defect).with_error_reporting(), [one, two])
    assert _messages(first) == ["d"]
    assert _messages(second) == ["d"]


@testing.effect
def test_equal_but_distinct_errors_are_each_reported():
    """Effect remembers errors by identity; ``TaggedError`` compares
    structurally, which must not merge two failures."""
    reports, reporter = _recorder()
    yield from _reporting(
        fx.fail(Boom("x"))
        .with_error_reporting()
        .exit()
        .and_then(fx.fail(Boom("x")).with_error_reporting().exit()),
        [reporter],
    )
    assert _messages(reports) == ["x", "x"]


@testing.effect
def test_a_value_python_cannot_remember_is_reported_every_time():
    """Effect's primitives (a string error) are never remembered; one
    effect run twice fails with the same cause, which is."""
    reports, reporter = _recorder()

    def once() -> fx.Effect[object]:
        return fx.fail("s").with_error_reporting().exit()

    yield from _reporting(once().and_then(once()), [reporter])
    assert len(reports) == 2
    reused = once()
    yield from _reporting(reused.and_then(reused), [reporter])
    assert len(reports) == 3
    assert all(isinstance(r.error, fx.UnhandledError) and r.error.error == "s" for r in reports)


@dataclass(eq=False)
class Quiet(fx.TaggedError):
    report_ignored = True


@dataclass(eq=False)
class Noted(fx.TaggedError):
    report_severity = fx.LogLevel.WARN
    report_attributes: Mapping[str, object] = field(default_factory=lambda: {"k": 1})


@testing.effect
def test_an_error_can_be_ignored_or_set_its_severity_and_attributes():
    reports, reporter = _recorder()
    yield from _reporting(fx.fail(Quiet()).with_error_reporting(), [reporter])
    assert reports == []
    yield from _reporting(fx.fail(Noted()).with_error_reporting(), [reporter])
    (only,) = reports
    assert only.severity == fx.LogLevel.WARN
    assert only.attributes == {"k": 1}


def test_any_object_can_carry_the_report_attributes():
    error = ValueError("plain")
    assert not error_reporter.is_ignored(error)
    assert error_reporter.get_severity(error) == fx.LogLevel.INFO
    assert error_reporter.get_attributes(error) == {}
    error.report_ignored = True  # pyright: ignore[reportAttributeAccessIssue]
    error.report_severity = fx.LogLevel.FATAL  # pyright: ignore[reportAttributeAccessIssue]
    error.report_attributes = {"a": 1}  # pyright: ignore[reportAttributeAccessIssue]
    assert error_reporter.is_ignored(error)
    assert error_reporter.get_severity(error) == fx.LogLevel.FATAL
    assert error_reporter.get_attributes(error) == {"a": 1}


def test_a_severity_that_is_not_one_reads_as_info():
    """Effect gives ``Info`` for an unknown severity."""
    for bad in ("Loud", 30):
        error = ValueError()
        error.report_severity = bad  # pyright: ignore[reportAttributeAccessIssue]
        assert error_reporter.get_severity(error) == fx.LogLevel.INFO


@testing.effect
def test_report_sends_a_cause_to_the_reporters():
    reports, reporter = _recorder()
    yield from error_reporter.report(fail(Boom("rep"))).pipe(
        fx.provide(error_reporter.layer([reporter]))
    )
    assert _messages(reports) == ["rep"]


@testing.effect
def test_without_reporters_nothing_is_reported():
    ex = yield from fx.fail(Boom("a")).with_error_reporting().exit()
    assert isinstance(ex, fx.Failure)
    assert (yield from error_reporter.CurrentErrorReporters()) == ()


@testing.effect
def test_layer_replaces_or_merges_with_the_current_reporters():
    reports: list[tuple[str, str]] = []

    def named(name: str) -> fx.ErrorReporter:
        return error_reporter.make(lambda r: reports.append((name, str(r.error))))

    base = named("base")

    def failing() -> fx.Effect[object]:
        return fx.fail(Boom("m")).with_error_reporting().exit()

    yield from (
        failing()
        .pipe(fx.provide(error_reporter.layer([named("added")], merge_with_existing=True)))
        .pipe(fx.provide(error_reporter.layer([base])))
    )
    assert reports == [("base", "m"), ("added", "m")]
    reports.clear()
    yield from (
        failing()
        .pipe(fx.provide(error_reporter.layer([named("added")])))
        .pipe(fx.provide(error_reporter.layer([base])))
    )
    assert reports == [("added", "m")]


@testing.effect
def test_layer_installs_each_reporter_once_and_runs_effects_making_one():
    calls: list[object] = []

    class Counting:
        def report(self, *, cause: fx.Cause[object], fiber: fx.Fiber[Any, Any], timestamp: int):
            calls.append(cause)

    counting = Counting()
    yield from _reporting(fx.fail(Boom("t")).with_error_reporting(), [counting, counting])
    assert len(calls) == 1
    reports, reporter = _recorder()
    made: fx.Effect[fx.ErrorReporter] = fx.succeed(reporter)
    yield from (
        fx.fail(Boom("u"))
        .with_error_reporting()
        .exit()
        .pipe(fx.provide(error_reporter.layer([made])))
    )
    assert _messages(reports) == ["u"]


@testing.effect
def test_a_failing_finalizer_is_reported_with_the_failure():
    reports, reporter = _recorder()
    eff = fx.fail(Boom("f")).ensuring(fx.die(ValueError("fin")))
    yield from _reporting(eff.with_error_reporting(), [reporter])
    assert _messages(reports) == ["f", "fin"]


@testing.effect
def test_success_is_not_reported_and_the_timestamp_is_the_clock_time():
    reports, reporter = _recorder()
    yield from _reporting(fx.succeed(1).with_error_reporting(), [reporter])
    assert reports == []
    yield from testing.adjust(1.5)
    yield from _reporting(fx.fail(Boom("t")).with_error_reporting(), [reporter])
    (only,) = reports
    assert only.timestamp == 1_500_000_000
    fiber: Any = only.fiber
    assert isinstance(fiber, fx.Fiber)
