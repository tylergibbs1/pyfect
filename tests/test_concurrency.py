"""all / for_each / race / timeout, under the test clock."""

from collections.abc import Callable

import pytest

import pyfect as fx
from pyfect.testing import run_test as run


def logger() -> tuple[list[str], Callable[[str], fx.Effect[None]]]:
    log: list[str] = []
    return log, lambda msg: fx.sync(lambda: log.append(msg))


def test_all_collects_in_order():
    eff = fx.all(fx.succeed(1), fx.succeed("two"), fx.succeed(3.0))
    assert run(eff) == (1, "two", 3.0)


def test_concurrent_all_overlaps_sleeps():
    @fx.gen
    def program():
        work = fx.all(
            fx.sleep(3).as_("a"),
            fx.sleep(3).as_("b"),
            fx.sleep(3).as_("c"),
            concurrency="unbounded",
        )
        fiber = yield from work.timed().fork()
        yield from fx.testing.adjust(3)
        return (yield from fiber.join())

    elapsed, values = run(program)
    assert values == ("a", "b", "c")
    assert elapsed == 3


def test_sequential_all_does_not_overlap():
    @fx.gen
    def program():
        work = fx.all(fx.sleep(3), fx.sleep(3))
        fiber = yield from work.timed().fork()
        yield from fx.testing.adjust(6)
        return (yield from fiber.join())

    elapsed, _ = run(program)
    assert elapsed == 6


def test_for_each_respects_the_concurrency_limit():
    running = 0
    peak = 0

    def task(_: int) -> fx.Effect[None]:
        def enter() -> None:
            nonlocal running, peak
            running += 1
            peak = max(peak, running)

        def leave() -> None:
            nonlocal running
            running -= 1

        return fx.sync(enter).and_then(fx.yield_now()).and_then(fx.sync(leave))

    run(fx.for_each(range(10), task, concurrency=3))
    assert peak == 3


def test_first_failure_interrupts_siblings():
    log, say = logger()

    @fx.gen
    def program():
        work = fx.all(
            fx.never.on_interrupt(say("sibling interrupted")),
            fx.yield_now().and_then(fx.fail("boom")),
            concurrency="unbounded",
        )
        return (yield from work.exit())

    ex = run(program)
    assert log == ["sibling interrupted"]
    assert isinstance(ex, fx.Failure)
    assert ex.cause.failures == ("boom",)
    assert not ex.cause.is_interrupted, "our own interrupts of siblings are not reported"


def test_interrupting_a_concurrent_for_each_interrupts_all_workers():
    log, say = logger()

    @fx.gen
    def program():
        work = fx.for_each(
            range(3), lambda i: fx.never.on_interrupt(say(f"w{i}")), concurrency="unbounded"
        )
        fiber = yield from work.fork()
        yield from fx.yield_now()
        yield from fx.yield_now()
        yield from fiber.interrupt()

    run(program)
    assert sorted(log) == ["w0", "w1", "w2"]


def test_race_takes_the_first_success_and_interrupts_the_loser():
    log, say = logger()

    @fx.gen
    def program():
        fast = fx.sleep(1).as_("fast")
        slow = fx.sleep(5).as_("slow").on_interrupt(say("slow interrupted"))
        fiber = yield from fast.race(slow).fork()
        yield from fx.testing.adjust(1)
        return (yield from fiber.join())

    assert run(program) == "fast"
    assert log == ["slow interrupted"]


def test_race_ignores_a_failure_if_the_other_succeeds():
    @fx.gen
    def program():
        fiber = yield from fx.fail("early").race(fx.sleep(1).as_("late")).fork()
        yield from fx.testing.adjust(1)
        return (yield from fiber.join())

    assert fx.testing.run_test_exit(program) == fx.Success("late")


def test_race_fails_when_both_fail():
    ex = fx.testing.run_test_exit(fx.fail("a").race(fx.fail("b")))
    assert isinstance(ex, fx.Failure)
    assert sorted(ex.cause.failures) == ["a", "b"]


def test_race_first_takes_the_first_failure_too():
    ex = fx.testing.run_test_exit(fx.fail("early").race_first(fx.never))
    assert isinstance(ex, fx.Failure) and ex.cause.failures == ("early",)


def test_timeout():
    @fx.gen
    def program():
        slow = yield from fx.sleep(10).as_("done").timeout(5).exit().fork()
        fast = yield from fx.sleep(1).as_("done").timeout(5).exit().fork()
        yield from fx.testing.adjust(5)
        return (yield from slow.join()), (yield from fast.join())

    slow, fast = run(program)
    assert isinstance(slow, fx.Failure)
    assert isinstance(slow.cause.failures[0], fx.TimeoutException)
    assert fast == fx.Success("done")


def test_race_all():
    @fx.gen
    def program():
        fiber = yield from fx.race_all(
            fx.sleep(3).as_(3), fx.sleep(1).as_(1), fx.sleep(2).as_(2)
        ).fork()
        yield from fx.testing.adjust(3)
        return (yield from fiber.join())

    assert run(program) == 1


def test_invalid_concurrency_is_rejected_when_building():
    with pytest.raises(ValueError, match="concurrency"):
        fx.for_each([1], fx.succeed, concurrency=0)


def test_a_sleep_with_nothing_to_wake_it_is_reported_not_hung():
    with pytest.raises(fx.testing.StalledError):
        fx.testing.run_test(fx.sleep(1), stall_timeout=0.05)


def test_timeout_produces_a_useful_error_message():
    """Effect.test.ts "timeout produces a useful error message"."""

    @fx.gen
    def program():
        fiber = yield from fx.never.timeout(1.5).exit().fork()
        yield from fx.testing.adjust(2)
        return (yield from fiber.join())

    ex = run(program)
    assert isinstance(ex, fx.Failure)
    (error,) = ex.cause.failures
    assert isinstance(error, fx.TimeoutException)
    assert error.duration == 1.5
    assert str(error) == "Operation timed out after '1s 500ms'"
