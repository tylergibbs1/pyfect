from dataclasses import dataclass

import pyfect as fx
from pyfect import schedule, testing


@dataclass
class Flaky(fx.TaggedError):
    pass


calls: list[float] = []


def flaky_call() -> fx.Effect[str, Flaky]:
    """Fails three times, then succeeds; records the virtual time of each call."""

    def call(now: float) -> fx.Effect[str, Flaky]:
        calls.append(now)
        return fx.fail(Flaky()) if len(calls) <= 3 else fx.succeed("ok")

    return fx.clock.monotonic().flat_map(call)


@testing.effect
def test_retry_backs_off():
    calls.clear()
    fiber = yield from flaky_call().retry(schedule.exponential("1 second").up_to(times=3)).fork()
    yield from testing.adjust("7 seconds")  # virtual time: the test takes no real time
    assert (yield from fiber.join()) == "ok"
    assert [t - calls[0] for t in calls] == [0, 1, 3, 7]  # waits of 1, 2 and 4 seconds


@testing.effect
def test_timeout():
    fiber = yield from fx.sleep("10 seconds").timeout("5 seconds").exit().fork()
    yield from testing.adjust("5 seconds")
    assert isinstance((yield from fiber.join()), fx.Failure)
