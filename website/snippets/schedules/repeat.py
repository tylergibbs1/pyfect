import pyfect as fx
from pyfect import schedule

ticks: list[int] = []


def tick() -> fx.Effect[None]:
    return fx.sync(lambda: ticks.append(len(ticks)))


# Run once, then repeat every 10ms, three more times.
fx.run_blocking(tick().repeat(schedule.spaced("10 millis").up_to(times=3)))
assert ticks == [0, 1, 2, 3]

# Schedules combine: jittered exponential backoff, at most one second per wait.
backoff = schedule.min(schedule.exponential("100 millis").jittered(), schedule.spaced("1 second"))
assert fx.run_blocking(fx.succeed("first try").retry(backoff)) == "first try"
