"""Transaction throughput under contention: ``uv run python benchmarks/transaction.py``.

Prints the best of five runs for:

- uncontended: one fiber committing ``TxRef.update`` transactions in a row
- contended: many fibers each committing increments to one ``TxRef``, every
  transaction yielding between its read and its write, so concurrent
  transactions conflict and rerun

and the reruns per commit in the contended case. Compare against the numbers
in docs/PARITY.md (M9) before and after a change to ``pyfect.transaction``.
"""

import time
from collections.abc import Callable

import pyfect as fx

COMMITS = 50_000
FIBERS = 100
PER_FIBER = 100


def best_of(f: Callable[[], object], reps: int = 5) -> float:
    times: list[float] = []
    for _ in range(reps):
        start = time.perf_counter()
        f()
        times.append(time.perf_counter() - start)
    return min(times)


def commits(eff: fx.Effect[None], n: int) -> fx.Effect[None]:
    @fx.gen
    def loop():
        for _ in range(n):
            yield from eff

    return loop


def uncontended() -> fx.Effect[None]:
    ref = fx.TxRef(0)
    return commits(fx.tx(ref.update(lambda n: n + 1)), COMMITS)


def contended(attempts: list[int]) -> fx.Effect[int]:
    ref = fx.TxRef(0)

    @fx.fn
    def increment():
        attempts[0] += 1
        value = yield from ref.get()
        yield from fx.yield_now()
        yield from ref.set(value + 1)

    worker = commits(fx.tx(increment()), PER_FIBER)
    return fx.for_each(range(FIBERS), lambda _: worker, concurrency="unbounded").and_then(ref.get())


def main() -> None:
    print(f"uncontended: {COMMITS / best_of(lambda: fx.run_sync(uncontended())) / 1e3:.0f}k tx/s")
    attempts = [0]
    total = FIBERS * PER_FIBER
    elapsed = best_of(lambda: fx.run_sync(contended(attempts)))
    assert fx.run_sync(contended([0])) == total
    reruns = attempts[0] / (5 * total) - 1
    print(
        f"contended ({FIBERS} fibers x {PER_FIBER}): {total / elapsed / 1e3:.1f}k commits/s, "
        f"{reruns:.1f} reruns per commit"
    )


if __name__ == "__main__":
    main()
