"""Fiber runtime throughput: ``uv run python benchmarks/runtime.py``.

Prints the best of five runs for a long ``map`` chain, generator steps and
fork + join. Compare against the numbers in docs/PARITY.md before and after
a change to the fiber loop, the drain or the scheduler.
"""

import time
from collections.abc import Callable

import pyfect as fx

STEPS = 200_000
FORKS = 50_000


def best_of(f: Callable[[], object], reps: int = 5) -> float:
    times: list[float] = []
    for _ in range(reps):
        start = time.perf_counter()
        f()
        times.append(time.perf_counter() - start)
    return min(times)


def map_chain() -> float:
    eff = fx.succeed(0)
    for _ in range(STEPS):
        eff = eff.map(lambda x: x + 1)
    return best_of(lambda: fx.run_blocking(eff))


@fx.gen
def gen_steps():
    total = 0
    for i in range(STEPS):
        total += yield from fx.succeed(i)
    return total


@fx.gen
def fork_join():
    for i in range(FORKS):
        fiber = yield from fx.succeed(i).fork()
        yield from fiber.join()


def main() -> None:
    print(f"map chain: {STEPS / map_chain() / 1e6:.2f}M steps/s")
    print(f"gen steps: {STEPS / best_of(lambda: fx.run_blocking(gen_steps)) / 1e6:.2f}M steps/s")
    print(f"fork+join: {FORKS / best_of(lambda: fx.run_blocking(fork_join)) / 1e3:.0f}k/s")


if __name__ == "__main__":
    main()
