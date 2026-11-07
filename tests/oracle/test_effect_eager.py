"""Ports of Effect's ``EffectEager.test.ts``.

Each test's docstring is the Effect test title. ``Effect.matchEager({...})`` with no effect is
a call of the method here ("supports curried usage"), since non-type-removing combinators are
methods. ``Effect.promise`` is ``fx.from_async``'s place in "stops at first async effect", and
``_tag`` checks read the ``_Succeed`` / ``_FailCause`` an eager result is.
"""
# pyright: reportPrivateUsage=false

import inspect
from collections.abc import Generator
from typing import Any

import pyfect as fx
from pyfect import _core, testing

MILLI = 0.001


def _deferred_value(value: Any) -> fx.Effect[Any]:
    """An effect with no exit yet, so an eager generator stops at it."""
    return fx.yield_now().as_(value)


def test_computes_sync_effects_immediately():
    """fnUntracedEager computes sync effects immediately"""
    count = [0]

    def body():
        count[0] += 1
        yield from fx.succeed(1)
        yield from fx.succeed(2)
        return count[0]

    effect = fx.fn_untraced_eager(body)()
    assert count == [1]
    assert isinstance(effect, _core._Succeed)
    assert effect.value == 1


def test_computes_failures_immediately():
    """fnUntracedEager computes failures immediately"""

    def body():
        yield from fx.succeed(1)
        yield from fx.fail("error")
        return "unreachable"

    assert isinstance(fx.fn_untraced_eager(body)(), _core._FailCause)


def test_stops_at_first_async_effect():
    """fnUntracedEager stops at first async effect"""
    steps = [0]
    reached = [False]

    def reach() -> int:
        reached[0] = True
        return 2

    def body():
        steps[0] += 1
        yield from fx.succeed(1)
        steps[0] += 1
        yield from fx.sync(reach)
        steps[0] += 1
        return "done"

    effect = fx.fn_untraced_eager(body)()
    assert steps == [2]
    assert reached == [False]
    assert not isinstance(effect, _core._Succeed)


def test_handles_exceptions():
    """fnUntracedEager handles exceptions"""

    def body():
        yield from fx.succeed(1)
        raise RuntimeError("sync error")

    assert isinstance(fx.fn_untraced_eager(body)(), _core._FailCause)


@testing.effect
def test_executes_sync_generators():
    """fnUntracedEager executes sync generators"""

    def body():
        yield from fx.succeed(1)
        yield from fx.succeed(2)
        return "done"

    assert (yield from fx.fn_untraced_eager(body)()) == "done"


@testing.effect
def test_handles_mixed_sync_async_effects():
    """fnUntracedEager handles mixed sync/async effects"""

    def body():
        a = yield from fx.succeed(1)
        b = yield from _deferred_value(2)
        return a + b

    assert (yield from fx.fn_untraced_eager(body)()) == 3


@testing.effect
def test_handles_failures():
    """fnUntracedEager handles failures"""

    def body():
        yield from fx.fail("error")
        return "unreachable"

    assert isinstance((yield from fx.fn_untraced_eager(body)().exit()), fx.Failure)


@testing.effect
def test_works_with_arguments_and_this_context():
    """fnUntracedEager works with arguments and this context"""

    class Holder:
        value = 10

        @fx.fn_untraced_eager
        def add(self, x: int) -> Generator[fx.Effect[int], Any, int]:
            a = yield from fx.succeed(x)
            return a + self.value

    assert (yield from Holder().add(5)) == 15


@testing.effect
def test_works_with_pipeable_operators():
    """fnUntracedEager works with pipeable operators"""

    def body():
        yield from fx.succeed(1)
        return 10

    def double(effect: fx.Effect[int]) -> fx.Effect[int]:
        return effect.map(lambda x: x * 2)

    fn = fx.fn_untraced_eager(body, double)
    assert (yield from fn()) == 20


@testing.effect
def test_forwards_arguments_to_pipeable_operators():
    """fnUntracedEager forwards arguments to pipeable operators"""

    def body(value: str):
        yield from fx.void
        return len(value)

    def label(effect: fx.Effect[int], value: str) -> fx.Effect[str]:
        return effect.map(lambda length: f"{value}:{length}")

    fn = fx.fn_untraced_eager(body, label)
    assert (yield from fn("hello")) == "hello:5"


def test_proxies_body_length():
    """fnUntracedEager proxies body length"""

    def body(a: str, b: int, c: bool):
        yield from fx.void
        return len(a) + b if c else b

    assert len(inspect.signature(fx.fn_untraced_eager(body)).parameters) == 3


@testing.effect
def test_re_execution_creates_fresh_iterators():
    """fnUntracedEager re-execution creates fresh iterators"""
    count = [0]

    def body():
        count[0] += 1
        current = count[0]
        yield from fx.succeed(1)
        yield from _deferred_value(2)
        return current

    effect = fx.fn_untraced_eager(body)()
    assert (yield from effect) == 1
    assert (yield from effect) == 2
    assert count == [2]


@testing.effect
def test_handles_long_sync_chains_efficiently():
    """fnUntracedEager handles long sync chains efficiently"""

    def body():
        total = 0
        for i in range(100):
            total += yield from fx.succeed(i)
        return total

    assert (yield from fx.fn_untraced_eager(body)()) == 4950


@testing.effect
def test_successful_effect():
    """mapEager successful effect"""
    assert (yield from fx.succeed(5).map_eager(lambda n: n * 2)) == 10


@testing.effect
def test_failed_effect_preserves_failure():
    """mapEager failed effect preserves failure"""
    exit = yield from fx.fail("error").map_eager(lambda n: n * 2).exit()
    assert exit == fx.exit.fail("error")


@testing.effect
def test_complex_effect_falls_back_to_regular_map():
    """mapEager complex effect falls back to regular map"""
    fiber = yield from fx.succeed(10).delay(MILLI).map_eager(lambda n: n + 5).fork()
    yield from testing.adjust(MILLI)
    assert (yield from fiber.join()) == 15


@testing.effect
def test_applies_transformation_eagerly_for_success_effects():
    """flatMapEager applies transformation eagerly for success effects"""
    runs = [0]

    def f(n: int) -> fx.Effect[int]:
        runs[0] += 1
        return fx.succeed(n * 2)

    mapped = fx.succeed(5).flat_map_eager(f)
    assert (yield from mapped) == 10
    assert (yield from mapped) == 10
    assert (yield from mapped) == 10
    assert runs == [1]


@testing.effect
def test_preserves_failure_for_failed_effects():
    """flatMapEager preserves failure for failed effects"""
    error = RuntimeError("test error")
    exit = yield from fx.fail(error).flat_map_eager(lambda n: fx.succeed(n * 2)).exit()
    assert exit == fx.exit.fail(error)


@testing.effect
def test_fallback_to_regular_flat_map_for_complex_effects():
    """flatMapEager fallback to regular flatMap for complex effects"""
    fiber = (
        yield from fx.succeed(10).delay(MILLI).flat_map_eager(lambda n: fx.succeed(n * 2)).fork()
    )
    yield from testing.adjust(MILLI)
    assert (yield from fiber.join()) == 20


@testing.effect
def test_preserves_success_for_successful_effects():
    """mapErrorEager preserves success for successful effects"""
    assert (yield from fx.succeed(5).map_error_eager(lambda e: f"mapped: {e}")) == 5


@testing.effect
def test_applies_transformation_eagerly_for_failure_effects():
    """mapErrorEager applies transformation eagerly for failure effects"""
    exit = yield from fx.fail("original error").map_error_eager(lambda e: f"mapped: {e}").exit()
    assert exit == fx.exit.fail("mapped: original error")


@testing.effect
def test_fallback_to_regular_map_error_for_complex_effects():
    """mapErrorEager fallback to regular mapError for complex effects"""
    fiber = (
        yield from fx.fail("error").delay(MILLI).map_error_eager(lambda e: f"mapped: {e}").fork()
    )
    yield from testing.adjust(MILLI)
    assert (yield from fiber.await_exit()) == fx.exit.fail("mapped: error")


@testing.effect
def test_applies_on_success_eagerly_for_success_effects():
    """mapBothEager applies onSuccess eagerly for success effects"""
    mapped = fx.succeed(5).map_both_eager(
        on_failure=lambda e: f"Failed: {e}", on_success=lambda n: n * 2
    )
    assert (yield from mapped) == 10


@testing.effect
def test_applies_on_failure_eagerly_for_failure_effects():
    """mapBothEager applies onFailure eagerly for failure effects"""
    mapped = fx.fail("original error").map_both_eager(
        on_failure=lambda e: f"Failed: {e}", on_success=lambda n: n * 2
    )
    assert (yield from mapped.exit()) == fx.exit.fail("Failed: original error")


@testing.effect
def test_fallback_to_regular_map_both_for_complex_effects():
    """mapBothEager fallback to regular mapBoth for complex effects"""
    mapped = (
        fx.succeed(10)
        .delay(MILLI)
        .map_both_eager(on_failure=lambda e: f"Failed: {e}", on_success=lambda n: n * 2)
    )
    fiber = yield from mapped.fork()
    yield from testing.adjust(MILLI)
    assert (yield from fiber.join()) == 20


@testing.effect
def test_preserves_success_effects_without_applying_catch():
    """catchEager preserves success effects without applying catch"""
    assert (yield from fx.succeed(42).catch_eager(lambda e: fx.succeed(f"recovered: {e}"))) == 42


@testing.effect
def test_applies_catch_function_eagerly_for_failure_effects():
    """catchEager applies catch function eagerly for failure effects"""
    caught = fx.fail("original error").catch_eager(lambda e: fx.succeed(f"recovered: {e}"))
    assert (yield from caught) == "recovered: original error"


@testing.effect
def test_fallback_to_regular_catch_for_complex_effects():
    """catchEager fallback to regular catch for complex effects"""
    caught = fx.fail("error").delay(MILLI).catch_eager(lambda e: fx.succeed(f"recovered: {e}"))
    fiber = yield from caught.fork()
    yield from testing.adjust(MILLI)
    assert (yield from fiber.join()) == "recovered: error"


@testing.effect
def test_applies_on_success_eagerly_in_match():
    """matchEager applies onSuccess eagerly for success effects"""
    matched = fx.succeed(42).match_eager(
        on_failure=lambda e: f"Failed: {e}", on_success=lambda n: f"Success: {n}"
    )
    assert (yield from matched) == "Success: 42"


@testing.effect
def test_applies_on_failure_eagerly_in_match():
    """matchEager applies onFailure eagerly for failure effects"""
    matched = fx.fail("original error").match_eager(
        on_failure=lambda e: f"Failed: {e}", on_success=lambda n: f"Success: {n}"
    )
    assert (yield from matched) == "Failed: original error"


@testing.effect
def test_fallback_to_regular_match_for_complex_effects():
    """matchEager fallback to regular match for complex effects"""
    matched = (
        fx.succeed(10)
        .delay(MILLI)
        .match_eager(on_failure=lambda e: f"Failed: {e}", on_success=lambda n: f"Success: {n}")
    )
    fiber = yield from matched.fork()
    yield from testing.adjust(MILLI)
    assert (yield from fiber.join()) == "Success: 10"


@testing.effect
def test_eagerly_handles_complex_failure_scenarios():
    """matchEager eagerly handles complex failure scenarios"""
    matched = fx.fail(RuntimeError("test error")).match_eager(
        on_failure=lambda e: f"Recovered from: {e}", on_success=lambda n: f"Success: {n}"
    )
    assert (yield from matched) == "Recovered from: test error"


@testing.effect
def test_supports_curried_usage():
    """matchEager supports curried usage"""

    def matcher(effect: fx.Effect[int, str]) -> fx.Effect[str]:
        return effect.match_eager(
            on_failure=lambda e: f"Failed: {e}", on_success=lambda n: f"Success: {n}"
        )

    assert (yield from matcher(fx.succeed(100))) == "Success: 100"
    assert (yield from matcher(fx.fail("error"))) == "Failed: error"


@testing.effect
def test_never_fails_always_produces_a_result():
    """matchEager never fails - always produces a result"""
    handled = fx.fail("test error").match_eager(
        on_failure=lambda e: f"Handled: {e}", on_success=lambda n: f"Value: {n}"
    )
    assert (yield from handled) == "Handled: test error"
    value = fx.succeed(42).match_eager(
        on_failure=lambda e: f"Handled: {e}", on_success=lambda n: f"Value: {n}"
    )
    assert (yield from value) == "Value: 42"


@testing.effect
def test_applies_transformations_immediately_for_resolved_effects():
    """matchEager performance: applies transformations immediately for resolved effects"""
    counts = {"success": 0, "failure": 0}

    def on_success(n: int) -> int:
        counts["success"] += 1
        return n * 2

    def on_failure(error: str) -> str:
        counts["failure"] += 1
        return error.upper()

    success = fx.succeed(10).match_eager(on_failure=on_failure, on_success=on_success)
    failure = fx.fail("error").match_eager(on_failure=on_failure, on_success=on_success)
    assert (yield from success) == 20
    assert (yield from success) == 20
    assert (yield from failure) == "ERROR"
    assert (yield from failure) == "ERROR"
    assert counts == {"success": 1, "failure": 1}


def _counted() -> tuple[dict[str, int], Any, Any]:
    counts = {"success": 0, "failure": 0}

    def on_success(value: Any) -> Any:
        counts["success"] += 1
        return value * 2

    def on_failure(_cause: Any) -> str:
        counts["failure"] += 1
        return "HANDLED"

    return counts, on_failure, on_success


def test_eagerly_matches_success_effects():
    """matchCauseEager eagerly matches success effects"""
    counts, on_failure, on_success = _counted()
    result = fx.succeed(42).match_cause_eager(on_failure=on_failure, on_success=on_success)
    assert isinstance(result, _core._Succeed)
    assert result.value == 84
    assert counts == {"success": 1, "failure": 0}


def test_eagerly_matches_failure_effects():
    """matchCauseEager eagerly matches failure effects"""
    counts, on_failure, on_success = _counted()
    result = fx.fail("test error").match_cause_eager(on_failure=on_failure, on_success=on_success)
    assert isinstance(result, _core._Succeed)
    assert result.value == "HANDLED"
    assert counts == {"success": 0, "failure": 1}


@testing.effect
def test_falls_back_to_regular_match_cause_for_complex_effects():
    """matchCauseEager falls back to regular matchCause for complex effects"""
    counts, on_failure, on_success = _counted()
    result = (
        fx.succeed(10).delay(0.01).match_cause_eager(on_failure=on_failure, on_success=on_success)
    )
    assert not isinstance(result, _core._Succeed | _core._FailCause)
    assert counts == {"success": 0, "failure": 0}
    fiber = yield from result.fork()
    yield from testing.adjust(0.01)
    assert (yield from fiber.join()) == 20
    assert counts == {"success": 1, "failure": 0}


@testing.effect
def test_falls_back_to_regular_match_cause_for_delayed_failure_effects():
    """matchCauseEager falls back to regular matchCause for delayed failure effects"""
    counts, on_failure, on_success = _counted()
    result = (
        fx.fail("delayed error")
        .delay(0.005)
        .match_cause_eager(on_failure=on_failure, on_success=on_success)
    )
    assert not isinstance(result, _core._Succeed | _core._FailCause)
    fiber = yield from result.fork()
    yield from testing.adjust(0.005)
    assert (yield from fiber.join()) == "HANDLED"
    assert counts == {"success": 0, "failure": 1}


def test_handles_cause_information_correctly():
    """matchCauseEager handles cause information correctly"""
    seen: list[Any] = []
    result = fx.fail("boom").match_cause_eager(
        on_failure=lambda cause: seen.append(cause) or "seen", on_success=lambda _v: "no"
    )
    assert isinstance(result, _core._Succeed)
    assert result.value == "seen"
    assert seen[0] == fx.exit.fail("boom").cause


@testing.effect
def test_preserves_effect_execution_behavior_for_non_eager_paths():
    """matchCauseEager preserves effect execution behavior for non-eager paths"""
    runs = [0]

    def double(value: int) -> fx.Effect[int]:
        runs[0] += 1
        return fx.succeed(value * 2)

    result = (
        fx.succeed(42)
        .delay(MILLI)
        .flat_map(double)
        .match_cause_eager(on_failure=lambda _c: "ERROR", on_success=lambda value: value + 100)
    )
    assert not isinstance(result, _core._Succeed)
    assert runs == [0]
    fiber = yield from result.fork()
    yield from testing.adjust(MILLI)
    assert (yield from fiber.join()) == 184
    assert runs == [1]
