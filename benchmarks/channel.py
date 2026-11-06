"""Channel pull-loop throughput: ``uv run python benchmarks/channel.py``.

Runs 1M items through a source, two ``map`` steps and a ``pipe_to`` into an
identity channel, then collects them, item by item and in chunks of 4096
(the way streams carry items). Prints the best of three runs.
"""

import sys
import time
from collections.abc import Callable

import pyfect as fx
from pyfect import channel

N = 1_000_000


def best_of(f: Callable[[], object], reps: int = 3) -> float:
    times: list[float] = []
    for _ in range(reps):
        start = time.perf_counter()
        f()
        times.append(time.perf_counter() - start)
    return min(times)


def per_item() -> object:
    pipeline = (
        channel.from_iterable(range(N))
        .map(lambda n: n + 1)
        .map(lambda n: n * 2)
        .pipe_to(channel.identity())
    )
    return fx.run_blocking(pipeline.run_drain())


def chunked() -> object:
    pipeline = (
        channel.from_iterable_array(range(N))
        .map(lambda chunk: tuple(n + 1 for n in chunk))
        .map(lambda chunk: tuple(n * 2 for n in chunk))
        .pipe_to(channel.identity())
    )
    return fx.run_blocking(pipeline.run_drain())


def main() -> None:
    print(f"python {sys.version.split()[0]}")
    for name, run in (("per item", per_item), ("chunked", chunked)):
        seconds = best_of(run)
        print(f"{name}: {N:,} items in {seconds:.2f}s ({N / seconds / 1e6:.2f}M items/s)")


if __name__ == "__main__":
    main()
