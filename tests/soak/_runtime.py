"""Fiber churn, resource churn and handoffs between fibers, through their error and
interruption paths as much as their happy ones."""

from __future__ import annotations

import random
import threading
from dataclasses import dataclass
from typing import Never

import pyfect as fx
from pyfect import scope

from ._workload import Unexpected, Workload, check, failed_with


@dataclass(eq=False)
class Flaky(fx.TaggedError):
    n: int


class Counts:
    """Resources acquired and released, so an operation can check they balance."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.acquired = 0
        self.released = 0

    def acquire(self) -> None:
        with self._lock:
            self.acquired += 1

    def release(self) -> None:
        with self._lock:
            self.released += 1

    @property
    def live(self) -> int:
        with self._lock:
            return self.acquired - self.released


def _child(rng: random.Random, n: int) -> fx.Effect[int, Flaky]:
    roll = rng.random()
    delay = fx.sleep(f"{rng.randint(0, 5)} millis")
    if roll < 0.1:
        return delay.and_then(fx.fail(Flaky(n)))
    return delay.as_(n)


@fx.fn
def _fibers(rng: random.Random):
    # Many children, some failing, gathered without failing.
    count = rng.randint(5, 30)
    results = yield from fx.all(
        *[_child(rng, n) for n in range(count)],
        concurrency=rng.choice([1, 4, "unbounded"]),
        mode="result",
    )
    yield from check(len(results) == count, f"{len(results)} results for {count} children")

    # A race: the losers are interrupted.
    winner = yield from fx.race_all(
        fx.sleep("30 millis").as_(1), fx.sleep("1 millis").as_(2), fx.never.as_(3)
    )
    yield from check(winner in (1, 2), f"race won by {winner}")

    # A timeout interrupts a sleeping effect.
    timed = yield from fx.sleep("1 second").timeout("1 millis").exit()
    yield from check(
        failed_with(timed, fx.TimeoutException),
        f"timeout gave {timed!r}",
    )

    # An interrupted fiber runs its finalizer; a parent's end stops its children.
    finalized: list[str] = []
    stuck = yield from fx.never.ensuring(fx.sync(lambda: finalized.append("stuck"))).fork()
    yield from fx.sleep(f"{rng.randint(0, 2)} millis")
    yield from stuck.interrupt()

    @fx.fn
    def parent():
        yield from fx.never.ensuring(fx.sync(lambda: finalized.append("orphan"))).fork()
        yield from fx.sleep("1 millis")

    yield from (yield from parent().fork()).join()
    # A daemon that finishes on its own.
    daemon = yield from fx.sleep("2 millis").fork_daemon()
    yield from daemon.join()
    yield from check(sorted(finalized) == ["orphan", "stuck"], f"finalizers ran: {finalized}")

    # A fiber failing with a defect is observed, not propagated.
    died = yield from fx.die(RuntimeError("deliberate")).fork()
    ex = yield from died.await_exit()
    yield from check(isinstance(ex, fx.Failure), f"a dying fiber exited {ex!r}")


def _resource(counts: Counts, rng: random.Random) -> fx.Effect[int, Flaky, fx.Scope]:
    def acquire() -> int:
        counts.acquire()
        return rng.randint(0, 1000)

    acquired = fx.acquire_release(fx.sync(acquire), lambda _r, _ex: fx.sync(counts.release))
    if rng.random() < 0.1:
        return acquired.and_then(fx.fail(Flaky(0)))
    return acquired


@fx.fn
def make_resources():
    """The resource workloads, sharing a pool and two caches that live as long as the
    soak's scope."""
    pool_counts, cache_counts = Counts(), Counts()

    def pooled() -> fx.Effect[int, Never, fx.Scope]:
        return fx.acquire_release(
            fx.sync(lambda: pool_counts.acquire() or 0),
            lambda _r, _ex: fx.sync(pool_counts.release),
        )

    pool = yield from fx.Pool.make_with_ttl(
        pooled(), min=1, max=4, time_to_live="200 millis", time_to_live_strategy="usage"
    )

    def lookup(key: int) -> fx.Effect[str, Flaky]:
        return fx.fail(Flaky(key)) if key % 13 == 0 else fx.succeed(str(key))

    cache = yield from fx.Cache.make(lookup, capacity=100, time_to_live="1 second")

    def scoped_lookup(key: int) -> fx.Effect[int, Never, fx.Scope]:
        return fx.acquire_release(
            fx.sync(lambda: cache_counts.acquire() or key),
            lambda _r, _ex: fx.sync(cache_counts.release),
        )

    scoped_cache = yield from fx.ScopedCache.make(
        scoped_lookup, capacity=50, time_to_live="500 millis"
    )

    @fx.fn
    def scopes(rng: random.Random):
        counts = Counts()
        held = rng.randint(1, 5)
        program = fx.all(*[_resource(counts, rng) for _ in range(held)])
        if rng.random() < 0.1:
            program = program.timeout("0 millis").as_void()
        yield from fx.scoped(program).ignore()
        yield from check(counts.live == 0, f"{counts.live} resources left after their scope")

    @fx.fn
    def pools(rng: random.Random):
        def borrow(item: int) -> fx.Effect[None]:
            return fx.sleep(f"{rng.randint(0, 3)} millis")

        roll = rng.random()
        if roll < 0.1:
            # Interrupted while waiting or while holding the item.
            yield from pool.use(borrow).timeout("1 millis").ignore()
        elif roll < 0.2:
            yield from fx.scoped(pool.get().flat_map(pool.invalidate))
        else:
            yield from pool.use(borrow)
        yield from check(pool_counts.live <= 8, f"{pool_counts.live} pool items alive (max 4)")

    @fx.fn
    def caches(rng: random.Random):
        key = rng.randint(0, 500)
        got = yield from cache.get(key).exit()
        if key % 13 == 0:
            yield from check(isinstance(got, fx.Failure), f"lookup of {key} gave {got!r}")
        else:
            yield from check(got == fx.Success(str(key)), f"lookup of {key} gave {got!r}")
        if rng.random() < 0.05:
            yield from cache.invalidate(rng.randint(0, 500))
        scoped_key = rng.randint(0, 200)
        value = yield from fx.scoped(scoped_cache.get(scoped_key))
        yield from check(value == scoped_key, f"scoped lookup gave {value}")
        if rng.random() < 0.05:
            yield from scoped_cache.invalidate(rng.randint(0, 200))
        size = yield from cache.size()
        yield from check(size <= 100, f"cache holds {size} of capacity 100")
        yield from check(
            cache_counts.live <= 60, f"{cache_counts.live} scoped cache resources alive (cap 50)"
        )

    return [
        Workload("scopes", scopes, loops=2, pace=0.08),
        Workload("pool", pools, loops=4, pace=0.08),
        Workload("caches", caches, loops=2, pace=0.04),
    ]


@fx.fn
def _queue(rng: random.Random):
    queue = yield from fx.Queue[int].bounded(rng.choice([1, 4, 16]))
    count = rng.randint(10, 100)
    producer = yield from fx.for_each(range(count), queue.offer).as_void().fork()
    if rng.random() < 0.1:
        # Shut the queue down with the producer and consumer waiting on it.
        consumer = yield from queue.take().forever().fork()
        yield from fx.sleep("1 millis")
        yield from queue.shutdown()
        yield from producer.await_exit()
        yield from consumer.await_exit()
        return
    taken = yield from fx.for_each(range(count), lambda _: queue.take())
    yield from producer.join()
    yield from check(sum(taken) == count * (count - 1) // 2, f"took {len(taken)} of {count}")


@fx.fn
def _pubsub(rng: random.Random):
    hub = yield from fx.PubSub[int].bounded(rng.choice([2, 8]))
    subscribers = rng.randint(1, 4)
    count = rng.randint(5, 40)
    ready = yield from fx.Queue[None].unbounded()

    @fx.fn
    def subscriber():
        subscription = yield from hub.subscribe()
        yield from ready.offer(None)
        return sum((yield from fx.for_each(range(count), lambda _: subscription.take())))

    fibers = yield from fx.for_each(range(subscribers), lambda _: fx.scoped(subscriber()).fork())
    yield from fx.for_each(range(subscribers), lambda _: ready.take())
    yield from fx.for_each(range(count), hub.publish)
    sums = yield from fx.Fiber.join_all(fibers)
    expected = count * (count - 1) // 2
    yield from check(all(s == expected for s in sums), f"subscribers summed {sums}, not {expected}")
    yield from hub.shutdown()


@fx.fn
def make_semaphore_workload():
    """Tasks contending for a semaphore's three permits, some interrupted while waiting."""
    semaphore = yield from fx.Semaphore.make(3)
    inside = Counts()

    def task(rng: random.Random) -> fx.Effect[None, Unexpected]:
        def held(_: None) -> fx.Effect[None, Unexpected]:
            holders = inside.live
            return check(holders <= 3, f"{holders} holders of 3 permits").and_then(
                fx.sleep(f"{rng.randint(0, 2)} millis")
            )

        return scope.acquire_use_release(
            fx.sync(inside.acquire), held, lambda _a, _ex: fx.sync(inside.release)
        )

    @fx.fn
    def contend(rng: random.Random):
        tasks = [semaphore.with_permits(task(rng)) for _ in range(rng.randint(2, 12))]
        # Some waiters are interrupted while queued for a permit.
        waiting = [t.timeout("1 millis").ignore() if rng.random() < 0.2 else t for t in tasks]
        yield from fx.all(*waiting, concurrency="unbounded", discard=True)
        available = yield from semaphore.available
        yield from check(available == 3, f"{available} permits free after every task ended")

    return Workload("semaphore", contend, loops=1, pace=0.08)


fibers_workload = Workload("fibers", _fibers, loops=2, pace=0.08)
handoff_workloads = [
    Workload("queue", _queue, loops=2, pace=0.08),
    Workload("pubsub", _pubsub, loops=2, pace=0.08),
]
