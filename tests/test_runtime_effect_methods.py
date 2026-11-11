"""The ``Effect`` methods built straight on the runtime's primitives:
``when``, the ``filter_or_*`` family, ``flatten``, ``replicate_effect``,
``forever``, the argument checks of ``zip``/``zip_with``/``and_then``, and
what running something that is not a primitive does."""

from typing import Any

import pytest

import pyfect as fx
from pyfect.errors import NoSuchElementException
from pyfect.option import Some


def _value[A](effect: fx.Effect[A, Any]) -> A:
    return fx.run_sync(effect.or_die())


# --- when ----------------------------------------------------------------------------


def test_when_runs_the_effect_only_if_the_condition_holds():
    ran: list[str] = []
    effect = fx.sync(lambda: ran.append("ran") or 7)
    assert _value(effect.when(fx.succeed(True))) == Some(7)
    assert _value(effect.when(fx.succeed(False))) is None
    assert ran == ["ran"]


def test_when_fails_with_the_condition_and_skips_the_effect():
    ran: list[str] = []
    effect = fx.sync(lambda: ran.append("ran") or 7).when(fx.fail("no condition"))
    assert fx.run_sync_exit(effect) == fx.exit.fail("no condition")
    assert ran == []


def test_when_needs_an_effect_condition():
    with pytest.raises(TypeError, match=r"^condition must be an Effect, got bool: True$"):
        fx.succeed(1).when(True)  # pyright: ignore[reportArgumentType]


# --- filter_or_fail / filter_or_else -------------------------------------------------


def test_filter_or_fail_keeps_a_passing_value():
    assert _value(fx.succeed(4).filter_or_fail(lambda n: n > 3)) == 4
    assert _value(fx.succeed(4).filter_or_fail(lambda n: n > 3, lambda n: f"small {n}")) == 4


def test_filter_or_fail_fails_with_no_such_element_by_default():
    ex = fx.run_sync_exit(fx.succeed(2).filter_or_fail(lambda n: n > 3))
    assert isinstance(ex, fx.Failure)
    assert isinstance(ex.cause.reasons[0], fx.cause.Fail)
    assert isinstance(ex.cause.reasons[0].error, NoSuchElementException)


def test_filter_or_fail_fails_with_the_error_made_from_the_value():
    ex = fx.run_sync_exit(fx.succeed(2).filter_or_fail(lambda n: n > 3, lambda n: f"small {n}"))
    assert ex == fx.exit.fail("small 2")


def test_filter_or_else_continues_with_the_rejected_value():
    effect = fx.succeed(2).filter_or_else(lambda n: n > 3, lambda n: fx.succeed(n * 10))
    assert _value(effect) == 20
    passing = fx.succeed(5).filter_or_else(lambda n: n > 3, lambda n: fx.succeed(n * 10))
    assert _value(passing) == 5


# --- flatten -------------------------------------------------------------------------


def test_flatten_runs_the_inner_effect():
    assert _value(fx.succeed(fx.succeed(3)).flatten()) == 3
    assert fx.run_sync_exit(fx.succeed(fx.fail("inner")).flatten()) == fx.exit.fail("inner")


# --- replicate_effect ----------------------------------------------------------------


def test_replicate_effect_collects_each_run():
    counter = iter(range(10))
    effect = fx.sync(lambda: next(counter))
    assert _value(effect.replicate_effect(3)) == [0, 1, 2]
    assert _value(effect.replicate_effect(2, discard=True)) is None
    assert next(counter) == 5


def test_replicate_effect_runs_up_to_concurrency_at_once():
    def runs_at_once(concurrency: fx.Concurrency) -> int:
        running = [0]
        peak = [0]

        @fx.gen
        def one():
            running[0] += 1
            peak[0] = max(peak[0], running[0])
            yield from fx.yield_now()
            running[0] -= 1

        fx.run_blocking(one.replicate_effect(4, concurrency=concurrency, discard=True))
        return peak[0]

    assert runs_at_once(None) == 1
    assert runs_at_once(2) == 2
    assert runs_at_once("unbounded") == 4


# --- forever -------------------------------------------------------------------------


def test_forever_yields_after_each_run_unless_disabled():
    counted = [0]
    tick = fx.sync(lambda: counted.__setitem__(0, counted[0] + 1))

    def program(loop: fx.Effect[Any]) -> fx.Effect[None]:
        @fx.gen
        def body():
            fiber = yield from loop.fork()
            yield from fx.yield_now()
            yield from fiber.interrupt()

        return body

    fx.run_blocking(program(tick.forever()))
    # The loop ran once, yielded, and the parent went on.
    assert counted[0] == 1

    counted[0] = 0
    fx.run_blocking(program(tick.forever(disable_yield=True)))
    # Without the yields the loop only pauses for the step budget.
    assert counted[0] > 100


# --- argument checks -----------------------------------------------------------------


def test_combinators_name_the_argument_that_is_not_an_effect():
    not_an_effect: Any = 3
    effect = fx.succeed(1)
    message = r"^that must be an Effect, got int: 3$"
    with pytest.raises(TypeError, match=message):
        effect.zip(not_an_effect)
    with pytest.raises(TypeError, match=message):
        effect.zip_with(not_an_effect, lambda a, b: (a, b))
    with pytest.raises(TypeError, match=message):
        effect.and_then(not_an_effect)


def test_zip_with_concurrent_runs_both_sides_at_once():
    order: list[str] = []

    def side(label: str) -> fx.Effect[str]:
        @fx.gen
        def body():
            order.append(f"{label} start")
            yield from fx.yield_now()
            order.append(f"{label} end")
            return label

        return body

    effect = side("a").zip_with(side("b"), lambda a, b: a + b, concurrent=True)
    assert fx.run_blocking(effect) == "ab"
    assert order == ["a start", "b start", "a end", "b end"]


# --- what is not a primitive ---------------------------------------------------------


class _NotAPrimitive(fx.Effect[int]):
    pass


def test_running_an_effect_that_is_not_a_primitive_is_a_defect_naming_its_class():
    ex = fx.run_sync_exit(_NotAPrimitive())
    assert isinstance(ex, fx.Failure)
    defect = ex.cause.reasons[0]
    assert isinstance(defect, fx.cause.Die)
    assert isinstance(defect.defect, NotImplementedError)
    assert str(defect.defect) == "_NotAPrimitive is not a primitive"


def test_gen_names_what_the_factory_returned_instead_of_a_generator():
    not_a_generator: Any = lambda: 3  # noqa: E731
    ex = fx.run_sync_exit(fx.gen(not_a_generator))
    assert isinstance(ex, fx.Failure)
    defect = ex.cause.reasons[0]
    assert isinstance(defect, fx.cause.Die)
    assert str(defect.defect) == "gen expected a generator, got int"


# --- forks, masks and yields ---------------------------------------------------------


def test_a_daemon_fiber_outlives_the_fiber_that_forked_it():
    @fx.gen
    def program():
        gate = yield from fx.Deferred[int].make()

        @fx.gen
        def parent():
            return (yield from gate.wait().fork_daemon())

        parent_fiber = yield from parent.fork()
        daemon = yield from parent_fiber.join()
        yield from gate.succeed(5)
        return (yield from daemon.await_exit())

    assert fx.run_blocking(program) == fx.exit.succeed(5)


def test_restore_inside_an_uninterruptible_region_keeps_the_inner_effect_uninterruptible():
    seen: list[int] = []

    @fx.gen
    def program():
        gate = yield from fx.Deferred[int].make()
        inner = fx.interruptible_mask(
            lambda restore: restore(gate.wait().tap(lambda n: fx.sync(lambda: seen.append(n))))
        )
        fiber = yield from inner.uninterruptible().fork(start_immediately=True)
        fiber.interrupt_as_unsafe(None)
        yield from gate.succeed(5)
        return (yield from fiber.await_exit())

    ex = fx.run_blocking(program)
    # The wait was not cut short: the value reached the code after it.
    assert seen == [5]
    assert isinstance(ex, fx.Failure)


def test_yield_now_resumes_before_a_later_yield_at_priority_zero():
    order: list[str] = []

    def yielding(label: str, effect: fx.Effect[None]) -> fx.Effect[None]:
        return effect.and_then(fx.sync(lambda: order.append(label)))

    program = fx.all(
        yielding("default", fx.yield_now()),
        yielding("zero", fx.yield_now_with(0)),
        yielding("minus one", fx.yield_now_with(-1)),
        concurrency="unbounded",
        discard=True,
    )
    fx.run_blocking(program)
    assert order == ["minus one", "default", "zero"]
