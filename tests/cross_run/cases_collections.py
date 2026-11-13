"""Cross-run cases for the transactional structures, PartitionedSemaphore, metrics,
MutableHashMap and Reference defaults."""

from __future__ import annotations

import itertools
import threading
from collections import Counter
from collections.abc import Callable
from typing import Any

import pyfect as fx
from pyfect import metric
from pyfect.cluster import snowflake
from pyfect.mutable_hash_map import MutableHashMap
from pyfect.option import Some
from pyfect.persistence.rate_limiter import MemoryRateLimiterStore

from ._hammer import THREADS, Case, expect, on_threads

N = 500
"""Operations per thread, each in a run of its own."""

ROUNDS = 100


def _per_thread(work: Callable[[int, int], None], n: int = N) -> list[str]:
    """``work(thread, k)`` for ``k`` in ``range(n)`` on every thread."""

    def run(i: int) -> None:
        for k in range(n):
            work(i, k)

    return on_threads(run)


def _stock() -> list[str]:
    """The dogfood app's oversold stock: buyers decrement a TxHashMap's stock only while some
    is left; every unit sells once and the stock never goes below 0."""
    units = THREADS * N // 2
    stock = fx.run_blocking(fx.TxHashMap[str, int].make(("widget", units)))
    sold = [0] * THREADS
    lowest: list[int] = []

    def buy() -> fx.Effect[bool]:
        def decide(left: int) -> fx.Effect[bool]:
            if left <= 0:
                return fx.succeed(False)
            return stock.set("widget", left - 1).as_(True)

        return fx.tx(
            stock.get("widget").flat_map(lambda found: decide(found.value if found else 0))
        )

    def work(i: int, _: int) -> None:
        if fx.run_blocking(buy()):
            sold[i] += 1

    problems = _per_thread(work)
    left = fx.run_blocking(stock.get("widget"))
    lowest.append(left.value if left else 0)
    return problems + expect("units sold", sum(sold), units) + expect("stock left", lowest, [0])


def _tx_hash_set() -> list[str]:
    values = fx.run_blocking(fx.TxHashSet[int].empty())
    problems = _per_thread(lambda i, k: fx.run_blocking(values.add(i * N + k)))
    return problems + expect("TxHashSet size", fx.run_blocking(values.size()), THREADS * N)


def _tx_chunk() -> list[str]:
    chunk = fx.run_blocking(fx.TxChunk[int].empty())
    # Each append copies the chunk, so fewer of them.
    n = N // 2
    problems = _per_thread(lambda i, k: fx.run_blocking(chunk.append(i * n + k)), n)
    items = fx.run_blocking(chunk.get())
    return problems + expect("TxChunk items", sorted(items), list(range(THREADS * n)))


def _tx_priority_queue() -> list[str]:
    queue = fx.run_blocking(fx.TxPriorityQueue[int].empty())
    producers = THREADS // 2
    taken: list[list[int]] = [[] for _ in range(THREADS)]

    def work(i: int, k: int) -> None:
        if i < producers:
            fx.run_blocking(queue.offer(i * N + k))
        else:
            taken[i].append(fx.run_blocking(queue.take()))

    problems = _per_thread(work)
    got = Counter(v for values in taken for v in values)
    return (
        problems
        + expect("items taken", sum(got.values()), producers * N)
        + expect("items taken twice", [v for v, n in got.items() if n > 1], [])
    )


def _tx_queue(make: Callable[[], fx.Effect[fx.TxQueue[int]]]) -> Callable[[], list[str]]:
    """Half the threads offer distinct items, half take them (parking in ``tx_retry`` and
    woken by commits in other runs): every item is taken once."""

    def run() -> list[str]:
        queue = fx.run_blocking(make())
        producers = THREADS // 2
        taken: list[list[int]] = [[] for _ in range(THREADS)]

        def work(i: int, k: int) -> None:
            if i < producers:
                fx.run_blocking(queue.offer(i * N + k))
            else:
                taken[i].append(fx.run_blocking(queue.take()))

        problems = _per_thread(work)
        got = Counter(v for values in taken for v in values)
        return (
            problems
            + expect("items taken", sum(got.values()), producers * N)
            + expect("items taken twice", [v for v, n in got.items() if n > 1], [])
        )

    return run


type _Guard = Callable[[fx.Effect[None], int], fx.Effect[None]]


def _exclusive(what: str, make: Callable[[], _Guard]) -> Callable[[], list[str]]:
    """``make()``'s ``guard(critical, thread)`` lets one fiber in at a time, across runs."""

    def run() -> list[str]:
        guard = make()
        box = [0]
        inside = [0]
        overlaps = [0]

        def critical() -> None:
            inside[0] += 1
            if inside[0] != 1:
                overlaps[0] += 1
            value = box[0]
            box[0] = value + 1
            inside[0] -= 1

        effect = fx.sync(critical)
        # Contended transactions rerun a lot with the GIL's switch interval cut.
        n = N // 4
        problems = _per_thread(lambda i, _: fx.run_blocking(guard(effect, i)), n)
        return (
            problems
            + expect(f"{what} entries", box[0], THREADS * n)
            + expect(f"{what} overlapping entries", overlaps[0], 0)
        )

    return run


def _tx_semaphore() -> _Guard:
    semaphore = fx.run_blocking(fx.TxSemaphore.make(1))
    return lambda eff, _: semaphore.with_permit(eff)


def _tx_lock() -> _Guard:
    lock = fx.run_blocking(fx.TxReentrantLock.make())
    return lambda eff, _: lock.with_write_lock(eff)


def _partitioned() -> _Guard:
    semaphore = fx.run_blocking(fx.PartitionedSemaphore[int].make(1))
    return lambda eff, i: semaphore.with_permits(i % 3, eff)


def _partitioned_permits() -> list[str]:
    """Permits taken and given back across runs all come back."""
    semaphore = fx.run_blocking(fx.PartitionedSemaphore[int].make(3))
    problems = _per_thread(
        lambda i, _: fx.run_blocking(semaphore.with_permits(i % 4, fx.void, (i % 3) + 1))
    )
    return problems + expect("permits free at the end", fx.run_blocking(semaphore.available), 3)


def _rounds(
    setup: Callable[[], Any],
    waiter: Callable[[Any], fx.Effect[Any]],
    waker: Callable[[Any], fx.Effect[Any]],
    check: Callable[[list[Any], list[Any]], list[str]],
    wakers: int = 1,
) -> Callable[[], list[str]]:
    """As cases_core's rounds: ``wakers`` threads wake, the others wait, one run each."""

    def run() -> list[str]:
        shared: list[Any] = [None]
        gate = threading.Barrier(THREADS, action=lambda: shared.__setitem__(0, setup()))
        waited: list[list[Any]] = [[] for _ in range(ROUNDS)]
        woke: list[list[Any]] = [[] for _ in range(ROUNDS)]

        def work(i: int) -> None:
            for r in range(ROUNDS):
                gate.wait()
                if i < wakers:
                    woke[r].append(fx.run_blocking(waker(shared[0])))
                else:
                    waited[r].append(fx.run_blocking(waiter(shared[0])))

        problems = on_threads(work)
        if not problems:
            for r in range(ROUNDS):
                problems += check(waited[r], woke[r])
        return problems

    return run


def _deferred_check(waited: list[int], woke: list[bool]) -> list[str]:
    return expect("completions that won", woke.count(True), 1) + expect(
        "values waiters saw", len(set(waited)), 1
    )


def _tx_pubsub() -> list[str]:
    """Publishers in runs of their own reach a subscriber in a long run."""
    hub = fx.run_blocking(fx.TxPubSub[int].unbounded())
    publishers = THREADS - 1
    ready = threading.Event()
    got: list[int] = []

    @fx.gen
    def subscriber():
        queue = yield from hub.subscribe()
        ready.set()
        for _ in range(publishers * N):
            item = yield from queue.take()
            got.append(item)

    def work(i: int) -> None:
        if i == 0:
            fx.run_blocking(fx.scoped(subscriber))
            return
        ready.wait()
        for k in range(N):
            fx.run_blocking(hub.publish(i * N + k))

    problems = on_threads(work)
    return problems + expect(
        "values received",
        sorted(got),
        sorted(i * N + k for i in range(1, THREADS) for k in range(N)),
    )


def _tx_subscription_ref() -> list[str]:
    ref = fx.run_blocking(fx.TxSubscriptionRef[int].make(0))
    problems = _per_thread(lambda i, k: fx.run_blocking(ref.update(lambda v: v + 1)))
    return problems + expect("TxSubscriptionRef", fx.run_blocking(ref.get()), THREADS * N)


_names = itertools.count()


def _metric_case() -> list[str]:
    """Counters, gauges, frequencies, histograms and summaries updated from many runs count
    every update."""
    n = next(_names)
    counter = metric.counter(f"cross_run_counter_{n}")
    gauge = metric.gauge(f"cross_run_gauge_{n}")
    words = metric.frequency(f"cross_run_frequency_{n}")
    histogram = metric.histogram(
        f"cross_run_histogram_{n}", boundaries=metric.linear_boundaries(start=0, width=1, count=4)
    )
    summary = metric.summary(
        f"cross_run_summary_{n}", max_age="1 hour", max_size=10, quantiles=[0.5]
    )
    each = fx.all(
        counter.update(1),
        gauge.modify(1),
        words.update("w"),
        histogram.update(1.0),
        summary.update(1.0),
        discard=True,
    )
    problems = _per_thread(lambda i, k: fx.run_blocking(each))
    total = THREADS * N
    return (
        problems
        + expect("counter", fx.run_blocking(counter.value()).count, total)
        + expect("gauge", fx.run_blocking(gauge.value()).value, total)
        + expect("frequency", fx.run_blocking(words.value()).occurrences.get("w"), total)
        + expect("histogram count", fx.run_blocking(histogram.value()).count, total)
        + expect("summary count", fx.run_blocking(summary.value()).count, total)
    )


def _mutable_hash_map() -> list[str]:
    """``modify`` of one key and ``set`` / ``remove`` of disjoint keys from many threads."""
    shared = MutableHashMap[object, int].make(("hits", 0))

    def work(i: int, k: int) -> None:
        shared.modify("hits", lambda v: v + 1)
        shared.set((i, k), k)
        if k % 2:
            shared.remove((i, k))
        shared.modify_at("other", lambda found: Some((found.value if found else 0) + 1))

    problems = _per_thread(work)
    return (
        problems
        + expect("modified key", shared.get("hits"), Some(THREADS * N))
        + expect("modify_at key", shared.get("other"), Some(THREADS * N))
        + expect("size", len(shared), 2 + THREADS * N // 2)
    )


def _reference_default() -> Callable[[], list[str]]:
    """A Reference read for the first time by many runs at once has one default."""

    def setup() -> type[fx.Reference[object]]:
        class Fresh(fx.Reference[object]):
            @classmethod
            def default(cls) -> object:
                return object()

        return Fresh

    def read(tag: type[fx.Reference[object]]) -> fx.Effect[object]:
        return tag()

    def check(waited: list[object], _: list[object]) -> list[str]:
        return expect("defaults seen", len({id(v) for v in waited}), 1)

    return _rounds(setup, read, lambda _: fx.void, check)


def _snowflakes() -> list[str]:
    """One generator shared by every thread hands out each snowflake once."""
    generator = fx.run_blocking(snowflake.make_generator())
    made: list[list[int]] = [[] for _ in range(THREADS)]
    _per_thread(lambda i, _: made[i].append(fx.run_blocking(fx.sync(generator.next_unsafe))))
    counts = Counter(v for values in made for v in values)
    twice = [v for v, n in counts.items() if n > 1]
    return [f"{len(twice)} snowflakes handed out twice"] if twice else []


def _rate_limiter_store() -> list[str]:
    """A fixed window counts every token consumed from every run."""
    store = MemoryRateLimiterStore()

    def consume() -> fx.Effect[float]:
        hit = store.fixed_window(key="k", tokens=1, refill_rate_millis=60_000, limit=None)
        return hit.map(lambda pair: pair[0]).catch_all(lambda _: fx.succeed(-1.0))

    problems = _per_thread(lambda _i, _k: fx.run_blocking(consume().as_(None)))
    return problems + expect("tokens counted", fx.run_blocking(consume()), THREADS * N + 1)


CASES = [
    Case("TxHashMap stock never oversold", (fx.TxHashMap,), _stock),
    Case("TxHashSet.add", (fx.TxHashSet,), _tx_hash_set),
    Case("TxChunk.append", (fx.TxChunk,), _tx_chunk),
    Case("TxPriorityQueue offer and take", (fx.TxPriorityQueue,), _tx_priority_queue),
    Case("TxQueue.unbounded", (fx.TxQueue,), _tx_queue(fx.TxQueue[int].unbounded)),
    Case("TxQueue.bounded(2)", (fx.TxQueue,), _tx_queue(lambda: fx.TxQueue[int].bounded(2))),
    Case("TxSemaphore exclusion", (fx.TxSemaphore,), _exclusive("TxSemaphore", _tx_semaphore)),
    Case(
        "TxReentrantLock write lock", (fx.TxReentrantLock,), _exclusive("TxReentrantLock", _tx_lock)
    ),
    Case(
        "TxDeferred completed from several runs",
        (fx.TxDeferred,),
        _rounds(
            lambda: fx.run_blocking(fx.TxDeferred[int].make()),
            lambda d: d.wait(),
            lambda d: d.succeed(threading.get_ident()),
            _deferred_check,
            wakers=THREADS // 2,
        ),
    ),
    Case("TxPubSub publish to a subscriber in another run", (fx.TxPubSub,), _tx_pubsub),
    Case("TxSubscriptionRef.update", (fx.TxSubscriptionRef,), _tx_subscription_ref),
    Case(
        "PartitionedSemaphore exclusion",
        (fx.PartitionedSemaphore,),
        _exclusive("PartitionedSemaphore", _partitioned),
    ),
    Case("PartitionedSemaphore permits", (fx.PartitionedSemaphore,), _partitioned_permits),
    Case("Metric updates", (metric.Metric,), _metric_case),
    Case("MutableHashMap", (MutableHashMap,), _mutable_hash_map),
    Case("Reference default", (fx.Reference,), _reference_default()),
    Case("SnowflakeGenerator", (snowflake.SnowflakeGenerator,), _snowflakes),
    Case("MemoryRateLimiterStore.fixed_window", (MemoryRateLimiterStore,), _rate_limiter_store),
]
