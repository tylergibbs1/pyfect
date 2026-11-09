"""``interruptUnsafe`` from the thread that runs the fiber, but from code
outside the fiber's run, checked against Effect 4.0.6 under Node: Effect
interrupts at once, so the interrupt can neither be lost nor wait a turn.
"""

import asyncio
from typing import Any

import pyfect as fx


def test_an_interrupt_from_a_nested_run_on_the_same_thread_is_not_lost():
    """N8: ``runSync`` inside the fiber interrupts it; Effect gives
    ``Failure[Interrupt]`` and the next step never runs."""
    log: list[str] = []

    @fx.gen
    def prog():
        me = yield from fx.current_fiber()
        yield from fx.sync(lambda: fx.run_blocking(fx.sync(lambda: me.interrupt_as_unsafe(None))))
        yield from fx.sync(lambda: log.append("after interrupt"))

    ex = fx.run_blocking_exit(prog)
    assert isinstance(ex, fx.Failure)
    assert ex.cause.has_interrupts_only
    assert log == []


def test_an_interrupt_from_loop_code_unwinds_the_fiber_at_once():
    """N10: ``runFork`` then ``interruptUnsafe`` from plain code; Effect has
    run the finalizer and finished the fiber when the call returns."""
    log: list[str] = []

    async def main() -> fx.Exit[Any, Any] | None:
        fiber = fx.run_fork(fx.sleep("1 second").ensuring(fx.sync(lambda: log.append("fin"))))
        fiber.interrupt_as_unsafe(None)
        return fiber.poll_unsafe()

    ex = asyncio.run(main())
    assert isinstance(ex, fx.Failure)
    assert ex.cause.has_interrupts_only
    assert log == ["fin"]
