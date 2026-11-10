"""How typed recovery reads a Cause: defect election, interruption, combining.

Ported from Effect's Effect.test.ts, Scope.test.ts and Cause.test.ts; each test
names the Effect test it follows.
"""

import math
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Never, TypeIs

import pytest

import pyfect as fx
from pyfect import schedule, testing
from pyfect.cause import (
    Cause,
    Die,
    EmptyCauseError,
    Fail,
    Interrupt,
    die,
    fail,
    interrupt,
    merge,
)


@dataclass
class MixedError(fx.TaggedError):
    pass


ERROR = MixedError()
DEFECT = RuntimeError("boom")


def _fail_once(eff: fx.Effect[Any, MixedError]) -> fx.Effect[Any, MixedError]:
    attempts = 0

    def body() -> fx.Effect[Any, MixedError]:
        nonlocal attempts
        attempts += 1
        return eff if attempts == 1 else fx.succeed("retried")

    return fx.suspend(body)


def _is_mixed(e: object) -> TypeIs[MixedError]:
    return isinstance(e, MixedError)


RECOVERIES: dict[str, Callable[[fx.Effect[Any, MixedError]], fx.Effect[Any, Any]]] = {
    "catch_all": lambda e: e.catch_all(lambda _: fx.succeed("recovered")),
    "catch_tag": lambda e: e.pipe(fx.catch_tag(MixedError, lambda _: fx.succeed("recovered"))),
    "catch_tag tuple": lambda e: e.pipe(
        fx.catch_tag((MixedError, ValueError), lambda _: fx.succeed("recovered"))
    ),
    "catch_if": lambda e: e.catch_if(lambda _: True, lambda _: fx.succeed("recovered")),
    "catch_if refinement": lambda e: e.pipe(
        fx.catch_if(_is_mixed, lambda _: fx.succeed("recovered"))
    ),
    "catch_filter": lambda e: e.catch_filter(fx.Ok, lambda _: fx.succeed("recovered")),
    "match_effect": lambda e: e.match_effect(
        on_failure=lambda _: fx.succeed("recovered"), on_success=fx.succeed
    ),
    "match": lambda e: e.match(on_failure=lambda _: "recovered", on_success=lambda a: a),
    "ignore": lambda e: e.ignore(),
    "or_else_succeed": lambda e: e.or_else_succeed(lambda _: "recovered"),
    "option": lambda e: e.option(),
    "result": lambda e: e.result(),
    "retry": lambda e: _fail_once(e).retry(schedule.recurs(1)),
    "eventually": lambda e: _fail_once(e).eventually(),
}


def _reasons(ex: fx.Exit[Any, Any]) -> list[tuple[str, object]]:
    assert isinstance(ex, fx.Failure)
    out: list[tuple[str, object]] = []
    for r in ex.cause.reasons:
        match r:
            case Fail(error=e):
                out.append(("Fail", e))
            case Die(defect=d):
                out.append(("Die", d))
            case Interrupt(fiber_id=fid):
                out.append(("Interrupt", fid))
    return out


@pytest.mark.parametrize("name", [*RECOVERIES, "or_die"])
def test_defects_take_precedence_over_typed_errors(name: str):
    """Effect.test.ts 'typed recovery with mixed causes' >
    'defects take precedence over typed errors'."""
    recover = RECOVERIES.get(name, lambda e: e.or_die())
    fail_and_die = fx.fail_cause(Cause((Fail(ERROR), Die(DEFECT))))
    assert _reasons(testing.run_test_exit(recover(fail_and_die))) == [
        ("Die", ERROR),
        ("Die", DEFECT),
    ]
    with_interrupt = fx.fail_cause(Cause((Fail(ERROR), Interrupt(1), Die(DEFECT))))
    assert _reasons(testing.run_test_exit(recover(with_interrupt))) == [
        ("Die", ERROR),
        ("Interrupt", 1),
        ("Die", DEFECT),
    ]


@pytest.mark.parametrize("name", list(RECOVERIES))
def test_interrupts_beside_a_typed_error_do_not_block_recovery(name: str):
    """Effect.test.ts 'interrupts beside a typed error do not block recovery'."""
    eff = fx.fail_cause(Cause((Fail(ERROR), Interrupt(1))))
    assert isinstance(testing.run_test_exit(RECOVERIES[name](eff)), fx.Success)


def test_error_mapping_keeps_defects_and_interrupts():
    """Effect.test.ts 'typed recovery with mixed causes' >
    'error mapping keeps defects and interrupts': mapping is not recovery,
    so nothing is elected."""
    eff = fx.fail_cause(Cause((Fail(ERROR), Interrupt(1), Die(DEFECT))))
    for self in (eff, fx.suspend(lambda: eff)):
        for mapped in (
            self.map_error(lambda _: "mapped"),
            self.map_both(on_failure=lambda _: "mapped", on_success=lambda a: a),
        ):
            ex = testing.run_test_exit(mapped)
            assert _reasons(ex) == [("Fail", "mapped"), ("Interrupt", 1), ("Die", DEFECT)]


def test_elected_non_exception_errors_die_as_themselves():
    ex = testing.run_test_exit(
        fx.fail_cause(fail("e") + die(DEFECT)).catch_all(lambda _: fx.succeed(1))
    )
    assert isinstance(ex, fx.Failure)
    first = ex.cause.reasons[0]
    assert first == Die("e")


def test_finalizer_errors_merged():
    """Effect.test.ts 'finalizer errors merged'."""
    e2, e3 = RuntimeError("e2"), RuntimeError("e3")
    eff = fx.fail(ERROR).ensuring(fx.die(e2)).ensuring(fx.die(e3))
    assert _reasons(testing.run_test_exit(eff)) == [("Die", ERROR), ("Die", e2), ("Die", e3)]


def test_a_dying_finalizer_cannot_be_recovered_from():
    eff = fx.fail(ERROR).ensuring(fx.die(DEFECT)).catch_all(lambda _: fx.succeed("recovered"))
    assert _reasons(testing.run_test_exit(eff)) == [("Die", ERROR), ("Die", DEFECT)]


def test_scoped_combines_usage_and_finalizer_failures():
    """Effect.test.ts 'scoped combines usage and finalizer failures' and
    Scope.test.ts 'a sole throwing finalizer keeps the scoped effect's failure'."""

    @fx.gen
    def body():
        yield from fx.add_finalizer(lambda _: fx.die(DEFECT))
        return (yield from fx.fail(ERROR))

    assert _reasons(testing.run_test_exit(fx.scoped(body))) == [("Die", ERROR), ("Die", DEFECT)]


def test_elects_typed_failures_when_a_concurrent_sibling_finalizer_dies():
    """Effect.test.ts 'elects typed failures when a concurrent sibling finalizer dies'."""
    eff = fx.all(fx.never.ensuring(fx.die(DEFECT)), fx.fail(ERROR), concurrency="unbounded")
    assert _reasons(testing.run_test_exit(eff)) == [("Die", ERROR), ("Die", DEFECT)]


def test_race_elects_defects_across_losers():
    eff = fx.race_all(fx.fail(ERROR), fx.die(DEFECT))
    assert _reasons(testing.run_test_exit(eff)) == [("Die", ERROR), ("Die", DEFECT)]


def test_retry_skips_typed_failures_accompanied_by_finalizer_defects():
    """Effect.test.ts 'does not retry typed failures accompanied by finalizer defects'."""
    attempts = 0

    def source() -> fx.Effect[Never, MixedError]:
        nonlocal attempts
        attempts += 1
        return fx.fail(ERROR).ensuring(fx.die(DEFECT))

    ex = testing.run_test_exit(fx.suspend(source).retry(schedule.recurs(1)))
    assert attempts == 1
    assert _reasons(ex) == [("Die", ERROR), ("Die", DEFECT)]


def test_retry_exhausted_fails_with_the_last_error_only():
    """Effect retry = retryOrElse(self, schedule, Effect.fail): the cause holds
    only the last typed error."""
    errors = iter(["a", "b"])
    eff = fx.suspend(lambda: fx.fail_cause(fail(next(errors)) + interrupt(1)))
    ex = testing.run_test_exit(eff.retry(schedule.recurs(1)))
    assert _reasons(ex) == [("Fail", "b")]


def test_or_die_dies_once_with_the_first_error():
    """Effect orDie = catch_(self, die): one Die, holding the first error.
    The other errors and any interruption beside them are dropped."""
    first, second = ValueError("first"), ValueError("second")
    ex = testing.run_test_exit(fx.fail_cause(fail(first) + interrupt(1) + fail(second)).or_die())
    assert _reasons(ex) == [("Die", first)]


def test_skipped_handlers_drop_failures_and_keep_defects_when_interrupted():
    """Effect.test.ts 'skipped handlers drop failures and keep defects when interrupted'."""

    @fx.gen
    def program():
        gate = fx.Deferred[None]()
        body = gate.wait().and_then(fx.fail_cause(fail("error") + die(DEFECT))).uninterruptible()
        fiber = yield from body.catch_cause(lambda _: fx.void).fork()
        yield from fx.yield_now()
        fiber.interrupt_as_unsafe(123)
        yield from fx.yield_now()
        yield from gate.succeed(None)
        return (yield from fiber.await_exit())

    assert _reasons(testing.run_test(program)) == [("Die", DEFECT), ("Interrupt", 123)]


def test_interrupting_a_fiber_inside_spans_records_the_interruption_once():
    """Effect.test.ts 'interrupting a fiber inside spans records the interruption once'."""

    class Value(fx.Reference[float]):
        @classmethod
        def default(cls) -> float:
            return 0

    @fx.fn("inner")
    def inner():
        return (yield from fx.never)

    @fx.fn("outer")
    def outer():
        return (yield from inner())

    @fx.gen
    def program():
        counts: list[int] = []
        for effect in (fx.never.with_span("a").with_span("b"), outer()):
            fiber = yield from effect.fork()
            yield from fx.yield_now()
            yield from fiber.interrupt()
            exit_ = yield from fiber.await_exit()
            assert isinstance(exit_, fx.Failure)
            counts.append(len(exit_.cause.reasons))
        fiber = yield from fx.never.with_span("a").with_span("b").fork()
        yield from fx.yield_now()
        yield from fiber.interrupt_as(123, fx.Context.make(Value, math.nan))
        exit_ = yield from fiber.await_exit()
        assert isinstance(exit_, fx.Failure)
        counts.append(len(exit_.cause.reasons))
        # The given annotations reach the interruption.
        assert math.isnan(exit_.cause.annotations.get(Value))
        return counts

    assert testing.run_test(program) == [1, 1, 1]


def test_uninterruptible_handlers_observe_the_interruption_after_skipped_handlers():
    """Effect.test.ts 'uninterruptible handlers observe the interruption after skipped handlers'."""
    seen: list[fx.Exit[Any, Any]] = []

    @fx.gen
    def program():
        gate = fx.Deferred[None]()
        inner = (
            gate.wait()
            .and_then(fx.fail("error"))
            .uninterruptible()
            .catch_all(lambda _: fx.void)
            .interruptible()
            .exit()
            .map(seen.append)
            .uninterruptible()
        )
        fiber = yield from inner.fork()
        yield from fx.yield_now()
        fiber.interrupt_as_unsafe(123)
        yield from fx.yield_now()
        yield from gate.succeed(None)
        yield from fiber.await_exit()

    testing.run_test(program)
    [ex] = seen
    assert isinstance(ex, fx.Failure) and ex.cause.has_interrupts_only


def test_interrupted_recovery_raises_interrupted_at_the_run_boundary():
    @fx.gen
    def program():
        inner = (
            fx.sleep("200 millis")
            .and_then(fx.fail("boom"))
            .uninterruptible()
            .catch_all(lambda _: fx.succeed("recovered"))
        )
        fiber = yield from inner.fork()
        yield from fx.sleep("50 millis")
        yield from fiber.interrupt()
        return (yield from fiber.join())

    with pytest.raises(fx.Interrupted):
        fx.run_blocking(program)


def test_every_interruptor_is_recorded():
    """Effect interruptUnsafe accumulates interruptors with causeAddInterrupts."""

    @fx.gen
    def program():
        fiber = yield from fx.sleep("50 millis").uninterruptible().fork()
        yield from fx.yield_now()
        fiber.interrupt_as_unsafe(111)
        fiber.interrupt_as_unsafe(222)
        fiber.interrupt_as_unsafe(111)
        return (yield from fiber.await_exit())

    assert _reasons(fx.run_blocking(program)) == [("Interrupt", 111), ("Interrupt", 222)]


def test_an_interruptor_is_added_to_a_cause_that_already_holds_another():
    """Effect exitFailCause evaluate: causeAddInterrupts(cause, fiber._interruptedCause)."""

    @fx.gen
    def program():
        gate = fx.Deferred[None]()
        body = gate.wait().and_then(fx.fail_cause(interrupt(5))).uninterruptible()
        fiber = yield from body.fork()
        yield from fx.yield_now()
        fiber.interrupt_as_unsafe(111)
        yield from fx.yield_now()
        yield from gate.succeed(None)
        return (yield from fiber.await_exit())

    assert _reasons(testing.run_test(program)) == [("Interrupt", 5), ("Interrupt", 111)]


# --- Cause ------------------------------------------------------------------


def test_combining_dedupes_equal_reasons_in_order():
    """Effect core.ts causeCombine/dedupeReasons."""
    assert fail("x") + fail("x") == fail("x")
    assert (fail("a") + fail("b")) + (fail("a") + fail("c")) == Cause(
        (Fail("a"), Fail("b"), Fail("c"))
    )


def test_combining_dedupes_unhashable_errors():
    assert fail(["x"]) + fail(["x"]) == fail(["x"])


def test_combining_buckets_hashable_errors_by_hash():
    """Effect dedupeReasons buckets reasons by hash, so growing a cause one
    reason at a time compares only reasons whose hashes collide. A linear
    equality scan made 400 adds take seconds."""
    comparisons = [0]

    @dataclass(frozen=True, eq=False)
    class Counted:
        n: int

        def __eq__(self, other: object) -> bool:
            comparisons[0] += 1
            return isinstance(other, Counted) and other.n == self.n

        def __hash__(self) -> int:
            return self.n

    combined: Cause[Counted] = Cause(())
    for i in range(200):
        combined = combined + fail(Counted(i))
    assert len(combined.reasons) == 200
    assert comparisons[0] == 0


def test_combining_dedupes_a_hashable_and_an_unhashable_equal_error():
    assert fail(frozenset({1})) + fail({1}) == fail(frozenset({1}))
    assert fail({1}) + fail(frozenset({1})) == fail({1})


def test_combining_with_empty_returns_the_other_cause():
    c = fail("x")
    assert c + Cause(()) is c
    assert Cause(()) + c is c


def test_add_interrupts_dedupes_by_fiber_id():
    """Effect core.ts causeAddInterrupts."""
    c = fail("x").add_interrupts(interrupt(1) + interrupt(2)).add_interrupts(interrupt(1))
    assert c == Cause((Fail("x"), Interrupt(1), Interrupt(2)))


def test_find_recoverable_error():
    assert fail("x").find_recoverable_error() == Fail("x")
    assert (interrupt(1) + fail("x")).find_recoverable_error() == Fail("x")
    assert interrupt(1).find_recoverable_error() == interrupt(1)
    elected = (fail(ERROR) + die(DEFECT)).find_recoverable_error()
    assert elected == die(ERROR) + die(DEFECT)


def test_merge_elects_defects():
    assert merge(fail(ERROR), die(DEFECT)) == die(ERROR) + die(DEFECT)
    assert merge(fail("a"), fail("b")) == fail("a") + fail("b")


def test_squash_of_an_empty_cause():
    """Cause.test.ts 'reports an empty cause'."""
    err = Cause(()).squash()
    assert isinstance(err, EmptyCauseError)
    assert str(err) == "Empty cause"
    assert isinstance(interrupt(1).squash(), fx.Interrupted)


def test_recovery_reads_causes_only_through_find_recoverable_error():
    """``first_failure`` let combinators recover past a defect. Nothing in
    src/ may bring it back, nor pick a typed error out of ``.failures``:
    combinators go through ``find_recoverable_error`` (or ``find_fail``
    to observe)."""
    src = Path(__file__).parent.parent / "src" / "pyfect"
    offenders = [
        f"{p.name}:{n}"
        for p in src.rglob("*.py")
        if p.name != "cause.py"
        for n, line in enumerate(p.read_text().splitlines(), 1)
        if re.search(r"\bfirst_failure\b|\.failures\b", line)
    ]
    assert offenders == []


def test_tap_error_taps_the_first_error_even_beside_a_defect():
    """Effect tapError = tapCauseFilter(self, findError, f): it observes the
    first Fail without electing, and re-fails with the original cause."""
    tapped: list[object] = []
    cause = fail("a") + die(DEFECT) + fail("b")
    eff = fx.fail_cause(cause).tap_error(lambda e: fx.sync(lambda: tapped.append(e)))
    ex = testing.run_test_exit(eff)
    assert tapped == ["a"]
    assert isinstance(ex, fx.Failure) and ex.cause == cause


def test_find_fail():
    assert (die(DEFECT) + fail("x")).find_fail() == Fail("x")
    assert (die(DEFECT) + interrupt(1)).find_fail() == die(DEFECT) + interrupt(1)


def test_electing_defects_keeps_a_done_signal():
    """Effect's ``causeElectDefects`` leaves ``Fail(Done)`` alone: a
    producer's end beside a defect is still an end, which ``filter_done``
    strips (``acquireUseRelease`` with a failing release relies on it)."""
    done = fx.Done("leftover")
    cause = fail(done) + fail(ERROR) + die(DEFECT)
    assert cause.elect_defects().reasons == (Fail(done), Die(ERROR), Die(DEFECT))
    assert merge(fail(done), die(DEFECT)).reasons == (Fail(done), Die(DEFECT))
    recoverable = cause.find_recoverable_error()
    assert isinstance(recoverable, Cause)
    assert recoverable.reasons == (Fail(done), Die(ERROR), Die(DEFECT))
