"""``run_blocking`` called from a coroutine blocks that thread's asyncio loop
until it returns, so an effect that needs the loop must fail at once with
a clear error rather than wait for a loop that cannot run."""

import asyncio

import pytest

import pyfect as fx
from pyfect.effect import AsyncioRequiredError


async def _value() -> str:
    await asyncio.sleep(0)
    return "data"


@pytest.mark.parametrize(
    "effect",
    [fx.from_async(_value), fx.try_async(_value)],
    ids=["from_async", "try_async"],
)
def test_run_blocking_of_an_async_effect_inside_a_running_loop_dies_naming_run_async(
    effect: fx.Effect[str, object],
):
    async def main() -> fx.Exit[str, object]:
        return fx.run_blocking_exit(effect)

    exit = asyncio.run(main())
    match exit:
        case fx.Failure(cause=cause):
            defect = cause.squash()
            assert isinstance(defect, AsyncioRequiredError)
            assert "run_blocking" in str(defect)
            assert "run_async" in str(defect)
        case _:
            pytest.fail(f"expected a defect, got {exit!r}")


def test_run_blocking_inside_a_running_loop_still_runs_effects_that_need_no_loop():
    async def main() -> int:
        return fx.run_blocking(fx.sleep("1 millis").as_(1))

    assert asyncio.run(main()) == 1


def test_run_async_still_awaits_an_async_effect():
    assert asyncio.run(fx.run_async(fx.from_async(_value))) == "data"
