import pyfect as fx
from pyfect import schedule

ticks: list[int] = []


def tick() -> fx.Effect[None]:
    return fx.sync(lambda: ticks.append(len(ticks)))


# Run once, then repeat every 10ms, three more times.
fx.run_sync(tick().repeat(schedule.spaced(0.01).up_to(times=3)))
assert ticks == [0, 1, 2, 3]

# Schedules combine: jittered exponential backoff, at most one second per wait.
backoff = schedule.min(schedule.exponential(0.1).jittered(), schedule.spaced(1))
assert fx.run_sync(fx.succeed("first try").retry(backoff)) == "first try"
