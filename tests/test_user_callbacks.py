"""User code handed to the runtime: what it returns and what it raises.

A callback that raises, or returns something that is not an effect, is a
defect. Resource and finalizer combinators must still run their cleanup and
keep the original outcome beside that defect.
"""

from collections.abc import Callable
from typing import Any, Never

import pytest

import pyfect as fx
from pyfect.cause import Die, Interrupt
from pyfect.exit import Exit, Failure, Success
from pyfect.testing import run_test_exit


def defects(ex: Exit[Any, Any]) -> list[object]:
    assert isinstance(ex, Failure)
    return [r.defect for r in ex.cause.reasons if isinstance(r, Die)]


def raising(message: str) -> Callable[..., fx.Effect[None]]:
    def f(*_: object) -> fx.Effect[None]:
        raise ValueError(message)

    return f


# --- values that are not effects ----------------------------------------------


def test_yielding_a_non_effect_in_gen_dies_with_type_error():
    """Effect: Fiber.runLoop dies with "Not a valid effect" instead of hanging."""
    closed: list[bool] = []

    def body():
        try:
            yield 5
        finally:
            closed.append(True)

    ex = run_test_exit(fx.gen(body))  # pyright: ignore[reportArgumentType]
    [defect] = defects(ex)
    assert isinstance(defect, TypeError)
    assert "5" in str(defect)
    assert closed == [True]


def test_a_callback_returning_a_non_effect_dies_with_type_error():
    def not_an_effect(_: int) -> fx.Effect[int]:
        return 5  # pyright: ignore[reportReturnType]

    eff = fx.succeed(1).flat_map(not_an_effect)
    [defect] = defects(run_test_exit(eff))
    assert isinstance(defect, TypeError)


# --- acquire_use_release ------------------------------------------------------


def test_acquire_use_release_runs_release_when_use_throws():
    """Effect.test.ts: acquireUseRelease runs release when use throws."""
    resource = object()
    released: list[tuple[object, Exit[Any, Any]]] = []
    boom = ValueError("boom")

    def use(_: object) -> fx.Effect[None]:
        raise boom

    ex = run_test_exit(
        fx.acquire_use_release(
            fx.succeed(resource), use, lambda r, e: fx.sync(lambda: released.append((r, e)))
        )
    )
    assert defects(ex) == [boom]
    assert len(released) == 1
    assert released[0][0] is resource
    assert defects(released[0][1]) == [boom]


# --- finalizers that raise ----------------------------------------------------


def test_on_exit_preserves_the_original_failure_when_the_finalizer_throws():
    """Effect.test.ts: onExit preserves the original failure when the finalizer throws."""
    ex = run_test_exit(fx.fail("body failure").on_exit(raising("finalizer defect")))
    body, fin = defects(ex)
    assert body == "body failure"
    assert str(fin) == "finalizer defect"


def test_on_exit_reports_a_thrown_finalizer_on_success():
    """Effect.test.ts: onExit reports a thrown finalizer on success."""
    ex = run_test_exit(fx.succeed(1).on_exit(raising("finalizer defect")))
    [fin] = defects(ex)
    assert str(fin) == "finalizer defect"


def test_outer_on_interrupt_still_sees_the_interruption_after_an_inner_finalizer_throws():
    """Effect.test.ts: an outer onInterrupt still sees the interruption after an
    inner finalizer throws."""
    finalized: list[bool] = []
    ex = run_test_exit(
        fx.interrupt()
        .on_exit(raising("finalizer defect"))
        .on_interrupt(fx.sync(lambda: finalized.append(True)))
    )
    assert finalized == [True]
    assert isinstance(ex, Failure)
    assert [type(r) for r in ex.cause.reasons] == [Interrupt, Die]


def test_nested_throwing_finalizers_do_not_overflow_the_stack():
    """Effect.test.ts: nested throwing finalizers do not overflow the stack."""
    program: fx.Effect[Any] = fx.succeed(1)
    for _ in range(20_000):
        program = program.exit().on_exit(raising("finalizer defect"))
    [fin] = defects(run_test_exit(program))
    assert str(fin) == "finalizer defect"


# Every combinator that takes a user cleanup callback, with that callback
# raising. Each must keep the body's failure and add the callback's defect.
type Wrap = Callable[[fx.Effect[Never, str], Callable[..., fx.Effect[None]]], fx.Effect[Any, str]]

FINALIZER_COMBINATORS: dict[str, Wrap] = {
    "on_exit": lambda body, cb: body.on_exit(cb),
    "on_error": lambda body, cb: body.on_error(cb),
    "acquire_use_release": lambda body, cb: fx.acquire_use_release(
        fx.succeed(None), lambda _: body, cb
    ),
    "acquire_release": lambda body, cb: fx.scoped(
        fx.acquire_release(fx.succeed(None), cb).and_then(body)
    ),
    "add_finalizer": lambda body, cb: fx.scoped(fx.add_finalizer(cb).and_then(body)),
}


@pytest.mark.parametrize("wrap", FINALIZER_COMBINATORS.values(), ids=FINALIZER_COMBINATORS.keys())
def test_a_raising_cleanup_callback_keeps_the_original_cause(wrap: Wrap):
    ex = run_test_exit(wrap(fx.fail("body"), raising("cleanup")))
    body, cleanup = defects(ex)
    assert body == "body"
    assert str(cleanup) == "cleanup"


def test_success_is_kept_when_cleanup_succeeds():
    ex = run_test_exit(fx.succeed(1).on_exit(lambda _: fx.void))
    assert ex == Success(1)
