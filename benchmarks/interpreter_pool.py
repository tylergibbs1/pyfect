"""Subinterpreters against threads: ``uv run python benchmarks/interpreter_pool.py``.

Run it on the GIL build and on free-threaded 3.14t. Prints the best of three
wall times for N calls of the same pure-Python function with
``concurrency=N``, inline on the run's thread, through ``fx.blocking`` and
through ``interpreter_pool.call`` (a pool of N, warmed up first), then the
round trip of a call that does nothing, unloaded and with a pure-Python loop
spinning on a thread per core.
"""

import os
import statistics
import sys
import threading
import time
from collections.abc import Callable
from typing import Never

from cpu_work import stamp, work

import pyfect as fx
from pyfect import interpreter_pool

N = int(os.environ.get("POOL_N", "8"))
WORK = int(os.environ.get("POOL_WORK", "3000000"))
SAMPLES = 300
LOADED_SAMPLES = 60


def best_of(f: Callable[[], object], reps: int = 3) -> float:
    times: list[float] = []
    for _ in range(reps):
        start = time.perf_counter()
        f()
        times.append(time.perf_counter() - start)
    return min(times)


def summary(ms: list[float]) -> str:
    q = statistics.quantiles(ms, n=100)
    return f"p50 {q[49]:.3f} ms, p95 {q[94]:.3f} ms, p99 {q[98]:.3f} ms"


def main() -> None:
    gil = getattr(sys, "_is_gil_enabled", lambda: True)()
    print(f"Python {sys.version.split()[0]}{'' if gil else ' free-threaded'}, N={N}")
    pool = interpreter_pool.layer(N)

    def run[A](eff: fx.Effect[A, Never, interpreter_pool.InterpreterPool]) -> A:
        return fx.run_blocking(eff.pipe(fx.provide(pool)))

    one = best_of(lambda: work(WORK))
    print(f"one call alone: {one * 1000:.0f} ms")
    fan_outs: dict[str, Callable[[], fx.Effect[int, Never, interpreter_pool.InterpreterPool]]] = {
        "inline": lambda: fx.sync(lambda: work(WORK)),
        "blocking": lambda: fx.blocking(lambda: work(WORK)),
        "interpreter_pool": lambda: interpreter_pool.call(work, WORK),
    }

    @fx.fn
    def warmed_up(make: Callable[[], fx.Effect[int, Never, interpreter_pool.InterpreterPool]]):
        # Start every interpreter (and import cpu_work in it) before timing.
        yield from fx.all(*[interpreter_pool.call(work, 1) for _ in range(N)], concurrency=N)
        start = time.perf_counter()
        yield from fx.all(*[make() for _ in range(N)], concurrency=N)
        return time.perf_counter() - start

    for name, make in fan_outs.items():
        t = min(run(warmed_up(make)) for _ in range(3))
        print(f"{name:16}: {t * 1000:7.0f} ms ({one * N / t:.2f}x one call's rate)")

    def round_trips(samples: int) -> None:
        kinds: dict[
            str, Callable[[], fx.Effect[float, Never, interpreter_pool.InterpreterPool]]
        ] = {
            "blocking": lambda: fx.blocking(lambda: stamp(0)),
            "interpreter_pool": lambda: interpreter_pool.call(stamp, 0),
        }

        @fx.fn
        def probe(make: Callable[[], fx.Effect[float, Never, interpreter_pool.InterpreterPool]]):
            yield from interpreter_pool.call(stamp, 0)
            trips: list[float] = []
            back: list[float] = []
            for _ in range(samples):
                asked = time.perf_counter()
                ran = yield from make()
                now = time.perf_counter()
                trips.append((now - asked) * 1000)
                back.append((now - ran) * 1000)
            return trips, back

        for name, make in kinds.items():
            trips, back = run(probe(make))
            print(f"  {name:16} round trip:     {summary(trips)}")
            print(f"  {name:16} finish->resume: {summary(back)}")

    print("unloaded:")
    round_trips(SAMPLES)
    stop = threading.Event()

    def burn() -> None:
        while not stop.is_set():
            work(100_000)

    burners = [threading.Thread(target=burn, daemon=True) for _ in range(os.cpu_count() or 4)]
    for t in burners:
        t.start()
    try:
        print("loaded:")
        round_trips(LOADED_SAMPLES)
    finally:
        stop.set()
        for t in burners:
            t.join()


if __name__ == "__main__":
    main()
