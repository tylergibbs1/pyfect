"""PubSub throughput: ``uv run python benchmarks/pubsub.py``.

One publisher and four subscribers, each draining its subscription in its
own fiber, under each built-in strategy; then ``publish_all`` in batches of
64. Prints messages published per second, the best of three runs.
"""

import sys
import time
from collections.abc import Callable

import pyfect as fx
from pyfect.pubsub import PubSub, Subscription

N = 20_000
TAKERS = 4


def best_of(f: Callable[[], object], reps: int = 3) -> float:
    times: list[float] = []
    for _ in range(reps):
        start = time.perf_counter()
        f()
        times.append(time.perf_counter() - start)
    return min(times)


def fan_out(make: Callable[[], fx.Effect[PubSub[int]]], *, batch: int = 1) -> Callable[[], object]:
    """Each subscriber takes until it sees the last message (a sliding hub
    may drop the ones before it)."""

    def run() -> object:
        @fx.gen
        def program():
            pubsub = yield from make()
            subs = yield from fx.for_each(range(TAKERS), lambda _: pubsub.subscribe())

            def drain(sub: Subscription[int]) -> fx.Effect[None]:
                @fx.gen
                def loop():
                    while (yield from sub.take()) != N - 1:
                        pass

                return loop

            fibers = yield from fx.for_each(subs, lambda sub: drain(sub).fork())
            if batch == 1:
                for i in range(N):
                    yield from pubsub.publish(i)
            else:
                for start in range(0, N, batch):
                    yield from pubsub.publish_all(range(start, min(start + batch, N)))
            for fiber in fibers:
                yield from fiber.join()

        return fx.run_blocking(fx.scoped(program))

    return run


CASES: dict[str, Callable[[], object]] = {
    "bounded(1)": fan_out(lambda: PubSub[int].bounded(1)),
    "bounded(16)": fan_out(lambda: PubSub[int].bounded(16)),
    "sliding(16)": fan_out(lambda: PubSub[int].sliding(16)),
    "unbounded (dropping)": fan_out(PubSub[int].unbounded),
    "bounded(16) publish_all(64)": fan_out(lambda: PubSub[int].bounded(16), batch=64),
}


def main() -> None:
    print(f"python {sys.version.split()[0]}")
    for name, run in CASES.items():
        seconds = best_of(run)
        print(f"{name}: {N / seconds / 1e3:.0f}k messages/s")


if __name__ == "__main__":
    main()
