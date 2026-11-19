"""Overhead of ``fiber_profiler``: ``uv run python benchmarks/fiber_profiler.py``.

Prints the best of five runs of three workloads, first before the profiler
module is imported, then imported but off, then inside ``profile()``:

- ``steps``: one fiber, 200k ``map`` steps, so few turns (the step budget is
  2048 steps a turn);
- ``fork+join``: 20k forked fibers, a turn or two each;
- ``ping-pong``: two fibers handing a value back and forth through queues,
  200k turns of one step or two each: the profiler's worst case.
"""

import sys
import time
from collections.abc import Callable

import pyfect as fx

STEPS = 200_000
FORKS = 20_000
HOPS = 100_000


def best_of(f: Callable[[], object], reps: int = 5) -> float:
    times: list[float] = []
    for _ in range(reps):
        start = time.perf_counter()
        f()
        times.append(time.perf_counter() - start)
    return min(times)


def steps() -> None:
    eff = fx.succeed(0)
    for _ in range(STEPS):
        eff = eff.map(lambda x: x + 1)
    fx.run_blocking(eff)


@fx.gen
def fork_join_program():
    for i in range(FORKS):
        fiber = yield from fx.succeed(i).fork()
        yield from fiber.join()


def fork_join() -> None:
    fx.run_blocking(fork_join_program)


@fx.gen
def ping_pong_program():
    ping = yield from fx.Queue[int].unbounded()
    pong = yield from fx.Queue[int].unbounded()

    @fx.gen
    def echo():
        for _ in range(HOPS):
            n = yield from ping.take()
            yield from pong.offer(n)

    echoing = yield from echo.fork()
    for i in range(HOPS):
        yield from ping.offer(i)
        yield from pong.take()
    yield from echoing.join()


def ping_pong() -> None:
    fx.run_blocking(ping_pong_program)


WORKLOADS = {"steps": steps, "fork+join": fork_join, "ping-pong": ping_pong}


def measure() -> dict[str, float]:
    return {name: best_of(f) for name, f in WORKLOADS.items()}


def main() -> None:
    gil = getattr(sys, "_is_gil_enabled", lambda: True)()
    print(f"Python {sys.version.split()[0]}{'' if gil else ' free-threaded'}")
    before = measure()
    from pyfect import fiber_profiler

    off = measure()
    on: dict[str, float] = {}
    turns: dict[str, int] = {}
    for name, f in WORKLOADS.items():
        with fiber_profiler.profile() as report:
            on[name] = best_of(f)
        turns[name] = sum(t.turns for t in report.fibers.values()) // 5
    for name in WORKLOADS:
        b, o, p = before[name] * 1000, off[name] * 1000, on[name] * 1000
        per_turn = (on[name] - off[name]) / turns[name] * 1e9
        print(
            f"{name:9}: not imported {b:7.1f} ms, off {o:7.1f} ms ({o / b - 1:+.1%}), "
            f"on {p:7.1f} ms ({p / o - 1:+.1%}), {turns[name]} turns, "
            f"{per_turn:.0f} ns a turn"
        )


if __name__ == "__main__":
    main()
