"""Sequencing, generators, typed errors, defects."""

import copy
import pickle
from dataclasses import dataclass

import pytest

import pyfect as fx
from pyfect.cause import Die, Fail


@dataclass
class NotFound(fx.TaggedError):
    key: str


@dataclass(frozen=True, eq=False)
class FrozenNotFound(fx.TaggedError):
    key: str


@dataclass
class Invalid(fx.TaggedError):
    reason: str


def test_map_and_flat_map():
    eff = fx.succeed(2).map(lambda n: n * 10).flat_map(lambda n: fx.succeed(n + 1))
    assert fx.run_blocking(eff) == 21


def test_effects_are_lazy_and_rerunnable():
    calls: list[int] = []
    eff = fx.sync(lambda: calls.append(1))
    assert calls == []
    fx.run_blocking(eff)
    fx.run_blocking(eff)
    assert calls == [1, 1]


def test_gen_decorator_builds_an_effect():
    @fx.gen
    def program():
        a = yield from fx.succeed(1)
        b = yield from fx.succeed(2)
        return a + b

    assert fx.run_blocking(program) == 3


def test_fn_passes_arguments():
    @fx.fn
    def add(a: int, b: int):
        x = yield from fx.succeed(a)
        return x + b

    assert fx.run_blocking(add(2, 3)) == 5


def test_yielding_a_tagged_error_fails_the_generator():
    @fx.fn
    def find(key: str):
        yield from fx.void
        if key != "a":
            return (yield from NotFound(key))
        return "found"

    assert fx.run_blocking_exit(find("a")) == fx.Success("found")
    ex = fx.run_blocking_exit(find("b"))
    assert isinstance(ex, fx.Failure)
    assert ex.cause.failures == (NotFound("b"),)


def test_catch_tag_handles_only_its_class():
    def risky(n: int) -> fx.Effect[str, NotFound | Invalid]:
        if n == 0:
            return fx.fail(NotFound("zero"))
        if n < 0:
            return fx.fail(Invalid("negative"))
        return fx.succeed("ok")

    def handled(n: int) -> fx.Exit[str, Invalid]:
        return fx.run_blocking_exit(
            risky(n).pipe(fx.catch_tag(NotFound, lambda e: fx.succeed(f"missing {e.key}")))
        )

    assert handled(1) == fx.Success("ok")
    assert handled(0) == fx.Success("missing zero")
    ex = handled(-1)
    assert isinstance(ex, fx.Failure) and ex.cause.failures == (Invalid("negative"),)


def test_catch_all_does_not_catch_defects():
    boom = RuntimeError("boom")
    eff = fx.die(boom).catch_all(lambda _: fx.succeed("recovered"))
    ex = fx.run_blocking_exit(eff)
    assert isinstance(ex, fx.Failure) and ex.cause.defects == (boom,)


def test_exceptions_in_effect_code_are_defects():
    def explode() -> int:
        raise ValueError("bad")

    ex = fx.run_blocking_exit(fx.sync(explode))
    assert isinstance(ex, fx.Failure)
    assert isinstance(ex.cause.reasons[0], Die)


def test_try_maps_exceptions_to_typed_errors():
    eff = fx.try_(lambda: int("x"), lambda e: Invalid(str(e)))
    ex = fx.run_blocking_exit(eff)
    assert isinstance(ex, fx.Failure) and isinstance(ex.cause.reasons[0], Fail)


def test_catch_defect_recovers_from_defects():
    eff = fx.die(RuntimeError("x")).catch_defect(lambda d: fx.succeed(str(d)))
    assert fx.run_blocking(eff) == "x"


def test_map_error_or_die_and_result():
    failing = fx.fail(NotFound("k"))
    assert fx.run_blocking_exit(failing.map_error(lambda e: e.key)) == fx.Failure(
        fx.Cause((Fail("k"),))
    )
    assert fx.run_blocking(failing.result()) == fx.Err(NotFound("k"))
    assert fx.run_blocking(fx.succeed(1).result()) == fx.Ok(1)
    ex = fx.run_blocking_exit(failing.or_die())
    assert isinstance(ex, fx.Failure) and ex.cause.defects == (NotFound("k"),)


def test_match():
    eff = fx.fail(NotFound("k")).match(on_failure=lambda e: e.key, on_success=lambda _: "?")
    assert fx.run_blocking(eff) == "k"


def test_tap_and_tap_error_keep_the_outcome():
    seen: list[object] = []
    ok = fx.succeed(1).tap(lambda v: fx.sync(lambda: seen.append(v)))
    bad = fx.fail(Invalid("r")).tap_error(lambda e: fx.sync(lambda: seen.append(e)))
    assert fx.run_blocking(ok) == 1
    assert isinstance(fx.run_blocking_exit(bad), fx.Failure)
    assert seen == [1, Invalid("r")]


def test_generator_finally_runs_when_a_step_fails():
    cleaned: list[str] = []

    @fx.gen
    def program():
        try:
            yield from fx.fail(Invalid("x"))
        finally:
            cleaned.append("finally")

    fx.run_blocking_exit(program)
    assert cleaned == ["finally"]


def test_deep_chains_are_stack_safe():
    eff: fx.Effect[int] = fx.succeed(0)
    for _ in range(100_000):
        eff = eff.map(lambda n: n + 1)
    assert fx.run_blocking(eff) == 100_000


def test_recursive_effects_are_stack_safe():
    def count_down(n: int) -> fx.Effect[int]:
        if n == 0:
            return fx.succeed(0)
        return fx.suspend(lambda: count_down(n - 1))

    assert fx.run_blocking(count_down(200_000)) == 0


def test_run_blocking_raises_the_original_exception():
    with pytest.raises(ValueError, match="nope"):
        fx.run_blocking(fx.die(ValueError("nope")))


def test_ensuring_runs_on_success_and_failure():
    log: list[str] = []
    fin = fx.sync(lambda: log.append("fin"))
    fx.run_blocking(fx.succeed(1).ensuring(fin))
    fx.run_blocking_exit(fx.fail(Invalid("x")).ensuring(fin))
    assert log == ["fin", "fin"]


def test_a_failing_finalizer_adds_to_the_cause():
    eff = fx.fail(Invalid("first")).ensuring(fx.die(RuntimeError("second")))
    ex = fx.run_blocking_exit(eff)
    assert isinstance(ex, fx.Failure)
    # The finalizer's defect elects the typed error to a defect too
    # (Effect.test.ts "finalizer errors merged").
    assert ex.cause.failures == ()
    assert ex.cause.defects == (Invalid("first"), ex.cause.defects[1])
    assert str(ex.cause.defects[1]) == "second"


def test_an_error_in_generator_cleanup_is_added_as_a_defect():
    @fx.gen
    def program():
        try:
            yield from fx.fail(Invalid("first"))
        finally:
            raise RuntimeError("cleanup failed")

    ex = fx.run_blocking_exit(program)
    assert isinstance(ex, fx.Failure)
    assert ex.cause.failures == ()
    assert ex.cause.defects[0] == Invalid("first")
    assert [str(d) for d in ex.cause.defects[1:]] == ["cleanup failed"]


@pytest.mark.parametrize(
    "error",
    [
        NotFound("k"),
        NotFound(key="k"),
        FrozenNotFound("k"),
        fx.TimeoutException(fx.duration.to_seconds("1500 millis")),
    ],
    ids=["positional", "keyword", "frozen", "TimeoutException"],
)
def test_dataclass_tagged_errors_survive_copy_and_pickle(error: fx.TaggedError):
    """Exceptions are copied (``copy``) and pickled (process pools, logging);
    a dataclass error has no ``args``, so it must rebuild from its fields."""
    for clone in (copy.copy(error), pickle.loads(pickle.dumps(error))):
        assert type(clone) is type(error)
        assert clone == error
        assert str(clone) == str(error)
