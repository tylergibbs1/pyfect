"""CPU-bound fan-out across threads: ``uv run python benchmarks/parallel.py``.

Run it on the GIL build and on free-threaded 3.14t and compare. Prints, for N
tasks of the same pure-Python work run with ``concurrency=N``, the best of
three wall times for:

- ``inline``: ``fx.sync(work)``, every task on the run's thread (the default);
- ``blocking``: ``fx.blocking(work)``, each task on the blocking pool;
- ``on_thread``: ``fx.on_thread(fx.sync(work))``, each task a fiber of a run
  of its own on a thread of its own;

then the same for effect-heavy tasks (a generator of many small steps),
where only ``inline`` and ``on_thread`` apply, and the handoff latency of an
empty task (asked to started, finished to the caller resumed), unloaded and
with a pure-Python loop spinning on a thread per core.
"""

import os
import statistics
import sys
import threading
import time
from collections.abc import Callable

import pyfect as fx

N = int(os.environ.get("PARALLEL_N", "8"))
WORK = int(os.environ.get("PARALLEL_WORK", "300000"))
STEPS = int(os.environ.get("PARALLEL_STEPS", "20000"))
SAMPLES = 300
BURNERS = os.cpu_count() or 4
LOADED_SAMPLES = 60


def work() -> int:
    total = 0
    for i in range(WORK):
        total += i * i % 7
    return total


@fx.gen
def effect_heavy():
    total = 0
    for i in range(STEPS):
        total += yield from fx.sync(lambda i=i: i * i % 7)
    return total


def best_of(f: Callable[[], object], reps: int = 3) -> float:
    times: list[float] = []
    for _ in range(reps):
        start = time.perf_counter()
        f()
        times.append(time.perf_counter() - start)
    return min(times)


def fan_out(make: Callable[[], fx.Effect[int]]) -> float:
    eff = fx.all(*[make() for _ in range(N)], concurrency=N)
    return best_of(lambda: fx.run_blocking(eff))


def latencies(make: Callable[[Callable[[], float]], fx.Effect[float]], samples: int) -> list[float]:
    """Milliseconds from the far side finishing to the caller resuming."""

    @fx.gen
    def probe():
        out: list[float] = []
        for _ in range(samples):
            sent = yield from make(time.perf_counter)
            out.append((time.perf_counter() - sent) * 1000)
        return out

    return fx.run_blocking(probe)


def start_latencies(
    make: Callable[[Callable[[], float]], fx.Effect[float]], samples: int
) -> list[float]:
    """Milliseconds from asking for the far side to it starting."""

    @fx.gen
    def probe():
        out: list[float] = []
        for _ in range(samples):
            asked = time.perf_counter()
            started = yield from make(time.perf_counter)
            out.append((started - asked) * 1000)
        return out

    return fx.run_blocking(probe)


def summary(ms: list[float]) -> str:
    q = statistics.quantiles(ms, n=100)
    return f"p50 {q[49]:.3f} ms, p95 {q[94]:.3f} ms, p99 {q[98]:.3f} ms"


def burners(stop: threading.Event) -> list[threading.Thread]:
    def burn() -> None:
        while not stop.is_set():
            work()

    threads = [threading.Thread(target=burn, daemon=True) for _ in range(BURNERS)]
    for t in threads:
        t.start()
    return threads


def handoffs(label: str, samples: int) -> None:
    kinds: dict[str, Callable[[Callable[[], float]], fx.Effect[float]]] = {
        "blocking": fx.blocking,
        "on_thread": lambda f: fx.on_thread(fx.sync(f)),
    }
    for name, make in kinds.items():
        print(f"  {label} {name} finish->resume: {summary(latencies(make, samples))}")
        print(f"  {label} {name} ask->start:     {summary(start_latencies(make, samples))}")


def main() -> None:
    gil = getattr(sys, "_is_gil_enabled", lambda: True)()
    print(f"Python {sys.version.split()[0]}{'' if gil else ' free-threaded'}, N={N}")
    one = best_of(work)
    print(f"one task alone: {one * 1000:.0f} ms")
    for name, make in {
        "inline": lambda: fx.sync(work),
        "blocking": lambda: fx.blocking(work),
        "on_thread": lambda: fx.on_thread(fx.sync(work)),
    }.items():
        t = fan_out(make)
        print(f"pure  {name:9}: {t * 1000:7.0f} ms ({one * N / t:.2f}x one task's rate)")
    one_heavy = best_of(lambda: fx.run_blocking(effect_heavy))
    print(f"one effect-heavy task alone: {one_heavy * 1000:.0f} ms")
    for name, make in {
        "inline": lambda: effect_heavy,
        "on_thread": lambda: fx.on_thread(effect_heavy),
    }.items():
        t = fan_out(make)
        print(f"steps {name:9}: {t * 1000:7.0f} ms ({one_heavy * N / t:.2f}x one task's rate)")
    print("handoff latency:")
    handoffs("unloaded", SAMPLES)
    stop = threading.Event()
    threads = burners(stop)
    try:
        handoffs("loaded  ", LOADED_SAMPLES)
    finally:
        stop.set()
        for t in threads:
            t.join()


if __name__ == "__main__":
    main()
