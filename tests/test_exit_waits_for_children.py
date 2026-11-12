"""A fiber ending while interrupted waits for its children uninterruptibly
and keeps its exit. Effect 4.1.2 waits interruptibly, so a child that ignores
interrupts makes the fiber's exit the bare interruption and a finalizer's
defect is lost (PARITY section 4, an Effect bug not copied; found by
tests/runtime_diff)."""

import pyfect as fx
from pyfect.cause import Die, Interrupt


def test_a_finalizers_defect_survives_a_child_that_ignores_interrupts():
    finalizer = fx.void.fork(uninterruptible=True).and_then(fx.die("boom")).or_die()

    @fx.gen
    def main():
        fiber = yield from fx.never.ensuring(finalizer).fork()
        yield from fx.yield_now()
        yield from fiber.interrupt()
        return (yield from fiber.await_exit())

    exit_ = fx.run_blocking(main)
    assert isinstance(exit_, fx.Failure)
    reasons = exit_.cause.reasons
    assert [type(r) for r in reasons] == [Interrupt, Die]
    assert isinstance(reasons[1], Die) and reasons[1].defect == "boom"
