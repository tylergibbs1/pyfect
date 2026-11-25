import pyfect as fx
from pyfect import schedule, testing

started: list[float] = []


def hanging_call() -> fx.Effect[str]:
    """Never answers; records the virtual time at which each attempt starts."""
    record = fx.clock.monotonic().flat_map(lambda now: fx.sync(lambda: started.append(now)))
    return record.and_then(fx.never)


# Each attempt may take 5 seconds; wait 1, 2, then 4 seconds between them.
policy = schedule.exponential("1 second").up_to(times=3)
call = hanging_call().timeout("5 seconds").retry(policy)


@testing.effect
def test_gives_up_after_four_attempts():
    started.clear()
    fiber = yield from call.exit().fork()

    # adjust moves the TestClock and runs every fiber it wakes: no real waiting.
    yield from testing.adjust("26 seconds")
    assert fiber.poll_unsafe() is None  # the fourth attempt is still running
    yield from testing.adjust("1 second")

    exit = yield from fiber.join()
    assert isinstance(exit, fx.Failure)
    error = exit.cause.find_error()
    assert isinstance(error, fx.Ok) and isinstance(error.value, fx.TimeoutException)
    # Attempts start at 0, 5+1, 11+2 and 18+4 seconds.
    assert [t - started[0] for t in started] == [0, 6, 13, 22]
