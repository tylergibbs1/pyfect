import time

import pyfect as fx


def crunch() -> int:
    # Stands in for CPU-heavy work: parsing, hashing, a model, pure-Python loops.
    end = time.perf_counter() + 0.3
    steps = 0
    while time.perf_counter() < end:
        steps += 1
    return steps


@fx.fn
def ticks_while(work: fx.Effect[int]):
    """How often a fiber that wakes every 10 ms got to run while ``work`` ran."""
    ticks: list[float] = []
    heartbeat = fx.sleep("10 millis").tap(
        lambda _: fx.sync(lambda: ticks.append(time.perf_counter()))
    )
    beating = yield from heartbeat.forever().fork()
    yield from fx.sleep("20 millis")
    start = time.perf_counter()
    yield from work
    end = time.perf_counter()
    yield from beating.interrupt()
    return sum(start < tick < end for tick in ticks)


# On the run's thread, nothing else runs until the work returns.
print("inline:", fx.run_blocking(ticks_while(fx.sync(crunch))), "ticks")
# On a worker thread, the run keeps serving its other fibers.
print("fx.blocking: more than 5 ticks:", fx.run_blocking(ticks_while(fx.blocking(crunch))) > 5)
