import time

import pyfect as fx


@fx.fn
def worst_lag(load: fx.Effect[None]):
    """The latest a 50 ms timer fired, over ten wakes, while ``load`` runs."""
    lags: list[float] = []

    @fx.gen
    def probe():
        for _ in range(10):
            start = time.perf_counter()
            yield from fx.sleep("50 millis")
            lags.append(time.perf_counter() - start - 0.05)

    loading = yield from load.forever().fork()
    yield from probe
    yield from loading.interrupt()
    return max(lags)


def busy() -> None:
    # 200 ms of CPU on the run's thread between yields.
    end = time.perf_counter() + 0.2
    while time.perf_counter() < end:
        pass


idle = fx.run_blocking(worst_lag(fx.yield_now()))
saturated = fx.run_blocking(worst_lag(fx.sync(busy).and_then(fx.yield_now())))
print("idle: under 50 ms late:", idle < 0.05)
print("saturated: over 100 ms late:", saturated > 0.1)
