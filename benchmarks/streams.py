"""Stream and fiber throughput: ``uv run python benchmarks/streams.py``.

The pipelines of the sluice dogfood app, plus the primitives under them:

- ``group_by_key``: 200k integers in chunks of 256, keyed into 64 groups, every
  group read back through ``flat_map(..., concurrency="unbounded")``;
- ``group_by_key + grouped_within``: the same, each group cut by
  ``grouped_within(100, "1 second")`` (the windows close by count);
- the two ``group_by_key`` cases again on 50k integers in chunks of one, the
  shape a queue fed one item at a time gives;
- ``map + filter``: 1M integers in chunks of 4096 (Effect's default size);
- ``queue offer/take``: a forked producer offers 200k items one at a time to a
  bounded queue of 1024 while the consumer takes them one at a time;
- ``fork-heavy``: 20k fibers forked at once, each yields once.

Prints the best of five runs. Effect's numbers for the same pipelines under
Node are in docs/PARITY.md, next to the result of this script.
"""

import sys
import sysconfig
import time
from collections.abc import Callable

import pyfect as fx
from pyfect import stream
from pyfect.queue import Queue

GROUP_ITEMS = 200_000
GROUP_CHUNK = 256
SMALL_ITEMS = 50_000
KEYS = 64
PLAIN_ITEMS = 1_000_000
QUEUE_ITEMS = 200_000
FORKS = 20_000


def best_of(f: Callable[[], object], reps: int = 5) -> float:
    times: list[float] = []
    for _ in range(reps):
        start = time.perf_counter()
        f()
        times.append(time.perf_counter() - start)
    return min(times)


def source(items: int, chunk: int) -> stream.Stream[int]:
    return stream.range(0, items - 1, chunk_size=chunk)


def group_by_key(items: int, chunk: int) -> int:
    pipeline = source(items, chunk).group_by_key(lambda n: n % KEYS)
    counted = pipeline.flat_map(lambda group: group[1], concurrency="unbounded").run_count()
    return fx.run_blocking(counted)


def group_by_key_grouped_within(items: int, chunk: int) -> int:
    pipeline = source(items, chunk).group_by_key(lambda n: n % KEYS)
    windows = pipeline.flat_map(
        lambda group: group[1].grouped_within(100, "1 second"), concurrency="unbounded"
    )
    return fx.run_blocking(windows.map(len).run_sum())


def map_filter() -> int:
    pipeline = stream.range(0, PLAIN_ITEMS - 1).map(lambda n: n + 1).filter(lambda n: n % 2 == 0)
    return fx.run_blocking(pipeline.run_count())


@fx.gen
def queue_pair():
    queue = yield from Queue[int].bounded(1024)

    @fx.gen
    def produce():
        for i in range(QUEUE_ITEMS):
            yield from queue.offer(i)

    yield from produce.fork()
    total = 0
    for _ in range(QUEUE_ITEMS):
        total += yield from queue.take()
    return total


def fork_heavy() -> object:
    each = fx.for_each(range(FORKS), lambda i: fx.yield_now().as_(i), concurrency="unbounded")
    return fx.run_blocking(each)


def main() -> None:
    gil = "free-threaded" if sysconfig.get_config_var("Py_GIL_DISABLED") else "GIL"
    print(f"python {sys.version.split()[0]} ({gil})")
    cases: tuple[tuple[str, int, Callable[[], object]], ...] = (
        ("group_by_key + flat_map", GROUP_ITEMS, lambda: group_by_key(GROUP_ITEMS, GROUP_CHUNK)),
        (
            "group_by_key + grouped_within",
            GROUP_ITEMS,
            lambda: group_by_key_grouped_within(GROUP_ITEMS, GROUP_CHUNK),
        ),
        (
            "group_by_key + flat_map, 1-item chunks",
            SMALL_ITEMS,
            lambda: group_by_key(SMALL_ITEMS, 1),
        ),
        (
            "group_by_key + grouped_within, 1-item chunks",
            SMALL_ITEMS,
            lambda: group_by_key_grouped_within(SMALL_ITEMS, 1),
        ),
        ("map + filter", PLAIN_ITEMS, map_filter),
        ("queue offer/take", QUEUE_ITEMS, lambda: fx.run_blocking(queue_pair)),
        ("fork-heavy", FORKS, fork_heavy),
    )
    for name, items, run in cases:
        seconds = best_of(run)
        print(f"{name}: {items / seconds / 1e3:,.0f}k items/s")


if __name__ == "__main__":
    main()
