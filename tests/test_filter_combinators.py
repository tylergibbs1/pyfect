"""Effect's Filter-based combinators: ``catch_filter``, ``catch_cause_filter``,
``tap_cause_filter``, ``filter_map`` and ``filter_map_effect``. Every expected
value here was printed by Effect v4 under Node."""

from collections.abc import Iterator
from typing import Never

import pyfect as fx
from pyfect import testing
from pyfect.cause import Cause, Die, Fail
from pyfect.duration import Seconds


def _tagged(e: str) -> fx.Result[str, str]:
    return fx.Err(f"x:{e}")


def test_catch_filter_without_or_else_refails_with_the_original_error() -> None:
    eff = fx.fail("e1").catch_filter(_tagged, fx.succeed)
    assert testing.run_test(eff.exit()) == fx.exit.fail("e1")


def test_catch_filter_sends_the_rejected_rest_to_or_else() -> None:
    eff = fx.fail("e1").catch_filter(_tagged, fx.succeed, or_else=lambda x: fx.succeed(f"else {x}"))
    assert testing.run_test(eff) == "else x:e1"


def test_catch_filter_passes_the_mapped_value_to_the_handler() -> None:
    eff = fx.fail("e1").catch_filter(lambda e: fx.Ok(f"v:{e}"), fx.succeed)
    assert testing.run_test_exit(eff) == fx.Success("v:e1")


def test_catch_filter_lets_a_defect_win_without_calling_the_filter() -> None:
    called: list[object] = []

    def spy(e: str) -> fx.Result[str, str]:
        called.append(e)
        return fx.Ok(e)

    mixed: Cause[str] = fx.cause.fail("e1") + fx.cause.die(RuntimeError("boom"))
    ex = testing.run_test(fx.fail_cause(mixed).catch_filter(spy, fx.succeed).exit())
    assert isinstance(ex, fx.Failure)
    assert [type(r) for r in ex.cause.reasons] == [Die, Die]
    assert called == []


def test_catch_cause_filter_fails_with_the_residual_cause() -> None:
    rest: Cause[str] = fx.cause.fail("rest")
    eff = fx.fail("e1").catch_cause_filter(lambda _: fx.Err(rest), lambda _v, _c: fx.succeed("no"))
    assert testing.run_test(eff.exit()) == fx.exit.fail("rest")


def test_catch_cause_filter_sees_defects_and_the_whole_cause() -> None:
    def every(_: Cause[Never]) -> fx.Result[str, Cause[str]]:
        return fx.Ok("got")

    eff = fx.die(RuntimeError("boom")).catch_cause_filter(
        every, lambda v, c: fx.succeed((v, c.has_dies))
    )
    assert testing.run_test_exit(eff) == fx.Success(("got", True))


def test_tap_cause_filter_failing_tap_replaces_the_failure() -> None:
    eff = fx.fail("e1").tap_cause_filter(fx.Ok, lambda _v, _c: fx.fail("tap"))
    assert testing.run_test(eff.exit()) == fx.exit.fail("tap")


def test_tap_cause_filter_keeps_a_defect_after_tapping() -> None:
    boom = RuntimeError("boom")
    eff = fx.die(boom).tap_cause_filter(fx.Ok, lambda _v, _c: fx.void)
    ex = testing.run_test(eff.exit())
    assert isinstance(ex, fx.Failure)
    assert [r.defect for r in ex.cause.reasons if isinstance(r, Die)] == [boom]
    assert not any(isinstance(r, Fail) for r in ex.cause.reasons)


def test_filter_map_effect_keeps_the_ok_values() -> None:
    def tens(n: int) -> fx.Effect[fx.Result[int, int]]:
        return fx.succeed(fx.Ok(n * 10) if n % 2 == 0 else fx.Err(n))

    assert testing.run_test(fx.filter_map_effect([1, 2, 3, 4], tens)) == [20, 40]


def test_filter_map_effect_fails_with_the_filters_error() -> None:
    def check(n: int) -> fx.Effect[fx.Result[int, int], str]:
        return fx.fail("bad") if n == 3 else fx.succeed(fx.Ok(n))

    assert testing.run_test(fx.filter_map_effect([1, 2, 3, 4], check).exit()) == fx.exit.fail("bad")


def test_filter_map_effect_collects_in_completion_order_when_concurrent() -> None:
    def after(n: int) -> fx.Effect[fx.Result[int, Never]]:
        return fx.sleep(Seconds(n / 1000)).as_(fx.Ok(n))

    @fx.gen
    def program():
        fiber = yield from fx.filter_map_effect([30, 10, 20], after, concurrency=None).fork()
        yield from testing.adjust("100 millis")
        sequential = yield from fiber.join()
        fiber = yield from fx.filter_map_effect([30, 10, 20], after, concurrency="unbounded").fork()
        yield from testing.adjust("100 millis")
        return sequential, (yield from fiber.join())

    assert testing.run_test(program) == ([30, 10, 20], [10, 20, 30])


def test_filter_map_reads_its_iterable_each_run() -> None:
    reads = 0

    class Twice:
        def __iter__(self) -> Iterator[int]:
            nonlocal reads
            reads += 1
            yield from (1, 2)

    eff = fx.filter_map(Twice(), fx.Ok)
    assert (fx.run_blocking(eff), fx.run_blocking(eff), reads) == ([1, 2], [1, 2], 2)
