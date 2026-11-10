"""Ports of Effect's ``Pool.test.ts``.

Each test's docstring is the Effect test title. ``Scope.provide(scope)`` is
``provide_service(fx.Scope, scope)``, ``forkChild({ startImmediately })``
is ``fork(start_immediately=True)``, ``pollUnsafe`` is ``poll_unsafe`` and
durations are seconds. Effect pins some interleavings with a custom
``Scheduler.shouldYield``; pyfect has no such hook (see PARITY.md), so
those ports hold the fiber's resumes on a ``TaskQueue`` scheduler or sweep
``MaxOpsBeforeYield``, which places a yield at every step.
"""

import gc
import weakref
from collections.abc import Callable
from typing import Any, Never

import pytest

import pyfect as fx
from pyfect import schedule, testing
from pyfect.pool import PoolItem, PoolStats, Strategy

from ._task_queue import TaskQueue


def _in[A, E](scope: fx.CloseableScope, eff: fx.Effect[A, E, fx.Scope]) -> fx.Effect[A, E]:
    return eff.pipe(fx.provide_service(fx.Scope, scope))


def _counted(count: fx.Ref[int]) -> fx.Effect[int, Never, fx.Scope]:
    """Acquires the next number; releasing it counts back down."""
    return fx.acquire_release(
        count.update_and_get(lambda n: n + 1), lambda _a, _e: count.update(lambda n: n - 1)
    )


def _wait_until(predicate: Callable[[], bool]) -> fx.Effect[bool]:
    return fx.yield_now().and_then(fx.sync(predicate)).repeat(until=lambda done: done)


def _until(count: fx.Ref[int], n: int) -> fx.Effect[int]:
    return count.get().repeat(until=lambda v: v == n)


def _interrupted(ex: fx.Exit[Any, Any] | None) -> bool:
    return isinstance(ex, fx.Failure) and ex.cause.has_interrupts


_DONE = fx.Success(None)


@testing.effect
def test_preallocates_pool_items():
    """preallocates pool items"""
    count = yield from fx.Ref.make(0)
    yield from fx.Pool.make(_counted(count), size=10)
    yield from _until(count, 10)
    assert (yield from count.get()) == 10


@testing.effect
def test_cleans_up_items_when_shut_down():
    """cleans up items when shut down"""
    count = yield from fx.Ref.make(0)
    scope = fx.CloseableScope()
    yield from _in(scope, fx.Pool.make(_counted(count), size=10))
    yield from _until(count, 10)
    yield from scope.close(_DONE)
    assert (yield from count.get()) == 0


@testing.effect
def test_shutdown_waits_for_borrowed_items_before_releasing_owner_dependencies():
    """shutdown waits for borrowed items before releasing owner dependencies"""
    events: list[str] = []
    owner = fx.CloseableScope()
    borrower = fx.CloseableScope()
    yield from owner.add_finalizer(lambda _: fx.sync(lambda: events.append("owner-dependency")))
    resource = fx.acquire_release(
        fx.succeed("resource"), lambda _a, _e: fx.sync(lambda: events.append("resource"))
    )
    pool = yield from _in(owner, fx.Pool.make(resource, size=1))
    yield from _in(borrower, pool.get())
    closing = yield from owner.close(_DONE).fork(start_immediately=True)
    yield from fx.yield_now()
    yield from borrower.close(_DONE)
    yield from closing.join()
    assert events == ["resource", "owner-dependency"]


@testing.effect
def test_defects_dont_prevent_cleanup():
    """defects don't prevent cleanup"""
    count = yield from fx.Ref.make(0)
    acquire = fx.acquire_release(
        count.update_and_get(lambda n: n + 1),
        lambda _a, _e: count.update(lambda n: n - 1).and_then(fx.die(RuntimeError("boom"))),
    )
    scope = fx.CloseableScope()
    yield from _in(scope, fx.Pool.make(acquire, size=10))
    yield from _until(count, 10)
    yield from scope.close(_DONE)
    assert (yield from count.get()) == 0


@testing.effect
def test_acquire_one_item():
    """acquire one item"""
    count = yield from fx.Ref.make(0)
    pool = yield from fx.Pool.make(_counted(count), size=10)
    yield from _until(count, 10)
    assert (yield from pool.get()) == 1


@testing.effect
def test_keeps_failed_background_capacity_until_a_borrower_reaches_it():
    """keeps failed background capacity until a borrower reaches it"""
    release_failure = yield from fx.Deferred[None].make()
    failed = yield from fx.Deferred[None].make()
    attempts = 0

    def acquire() -> fx.Effect[int, str]:
        nonlocal attempts
        attempts += 1
        attempt = attempts
        if attempt == 2:
            return (
                release_failure.wait()
                .and_then(failed.succeed(None))
                .and_then(fx.fail("background"))
            )
        return fx.succeed(attempt)

    pool = yield from fx.Pool.make_with_ttl(
        fx.suspend(acquire), min=2, max=3, time_to_live=float("inf")
    )
    yield from _wait_until(
        lambda: (
            pool.state.available_head is not None
            and isinstance(pool.state.available_head.exit, fx.Success)
        )
    )
    yield from release_failure.succeed(None)
    yield from failed.wait()
    yield from _wait_until(lambda: len(pool.state.items) == 2)
    for _ in range(5):
        assert (yield from pool.use(fx.succeed)) == 1
    assert attempts == 2
    assert len(pool.state.items) == 2
    owner = fx.CloseableScope()
    assert (yield from _in(owner, pool.get())) == 1
    assert (yield from pool.use(fx.succeed)) == 3
    assert attempts == 3
    yield from owner.close(_DONE)


@testing.live
def test_blocks_when_item_not_available():
    """blocks when item not available"""
    count = yield from fx.Ref.make(0)
    pool = yield from fx.Pool.make(_counted(count), size=10)
    yield from _until(count, 10)
    yield from fx.all(*[pool.get()] * 10)
    fiber = yield from fx.scoped(pool.get()).fork(start_immediately=True)
    yield from fx.sleep("10 millis")
    assert fiber.poll_unsafe() is None


@testing.effect
def test_reuse_released_items():
    """reuse released items"""
    count = yield from fx.Ref.make(0)
    pool = yield from fx.Pool.make(_counted(count), size=10)
    yield from fx.scoped(pool.get()).replicate_effect(99)
    assert (yield from count.get()) == 10


@testing.effect
def test_invalidate_item():
    """invalidate item"""
    count = yield from fx.Ref.make(0)
    pool = yield from fx.Pool.make(_counted(count), size=10)
    yield from _until(count, 10)
    yield from pool.invalidate(1)
    yield from _until(count, 10)
    result = yield from fx.scoped(pool.get())
    assert result == 2
    assert (yield from count.get()) == 10


@testing.effect
def test_invalidate_all_items_in_pool_and_check_that_pool_get_doesnt_hang_forever():
    """invalidate all items in pool and check that pool.get doesn't hang forever"""
    allocated = yield from fx.Ref.make(0)
    finalized = yield from fx.Ref.make(0)
    acquire = fx.acquire_release(
        allocated.update_and_get(lambda n: n + 1),
        lambda _a, _e: finalized.update(lambda n: n + 1),
    )
    pool = yield from fx.Pool.make(acquire, size=2)
    yield from _until(allocated, 2)
    yield from pool.invalidate(1)
    yield from pool.invalidate(2)
    assert (yield from fx.scoped(pool.get())) == 3
    assert (yield from allocated.get()) == 4
    assert (yield from finalized.get()) == 2


@testing.live
def test_retry_on_failed_acquire_should_not_exhaust_pool():
    """retry on failed acquire should not exhaust pool"""
    acquire: fx.Effect[int, str] = fx.fail("error").as_(1)
    pool = yield from fx.Pool.make_with_ttl(acquire, min=0, max=1, time_to_live=float("inf"))
    result = yield from (
        fx.scoped(pool.get().retry(times=5))
        .timeout_or_else("1 second", lambda: fx.fail("timeout"))
        .flip()
    )
    assert result == "error"


@testing.effect
def test_compositional_retry():
    """compositional retry"""
    count = yield from fx.Ref.make(0)

    def cond(i: int) -> fx.Effect[int, int]:
        return fx.fail(i) if i <= 10 else fx.succeed(i)

    acquire = fx.acquire_release(
        count.update_and_get(lambda n: n + 1).flat_map(cond),
        lambda _a, _e: count.update(lambda n: n - 1),
    )
    pool = yield from fx.Pool.make(acquire, size=10)
    assert (yield from fx.scoped(pool.get()).retry(schedule.forever)) == 11


class _Numbers:
    """Acquires 1, 2, 3, ... and records what it finalizes."""

    def __init__(self) -> None:
        self.acquired = 0
        self.finalized: list[int] = []

    def next(self) -> int:
        self.acquired += 1
        return self.acquired

    def plain(self) -> fx.Effect[int]:
        return fx.sync(self.next)

    def scoped(self) -> fx.Effect[int, Never, fx.Scope]:
        return fx.acquire_release(
            fx.sync(self.next), lambda v, _e: fx.sync(lambda: self.finalized.append(v))
        )


@testing.effect
def test_usage_ttl_shrinks_to_min_in_idle_order_rather_than_acquisition_order():
    """usage TTL idle timeout: shrinks to min in idle order rather than acquisition order"""
    numbers = _Numbers()
    pool = yield from fx.Pool.make_with_ttl(
        numbers.scoped(), min=1, max=3, time_to_live="1 second", time_to_live_strategy="usage"
    )
    scope = yield from fx.Scope()
    first = yield from scope.fork()
    second = yield from scope.fork()
    third = yield from scope.fork()
    assert (yield from _in(first, pool.get())) == 1
    assert (yield from _in(second, pool.get())) == 2
    assert (yield from _in(third, pool.get())) == 3

    yield from testing.adjust("100 millis")
    yield from second.close(_DONE)
    yield from testing.adjust("100 millis")
    yield from first.close(_DONE)
    yield from testing.adjust("100 millis")
    yield from third.close(_DONE)
    yield from testing.adjust("700 millis")
    assert numbers.finalized == []
    yield from testing.adjust("1 second")
    assert numbers.finalized == [2, 1]
    assert len(pool.state.items) == 1
    yield from testing.adjust("2 seconds")
    assert numbers.finalized == [2, 1]
    assert (yield from pool.use(fx.succeed)) == 3
    assert numbers.acquired == 3


@testing.effect
def test_usage_ttl_retains_items_used_every_3_seconds_across_ttl_sweeps():
    """usage TTL idle timeout: retains items used every 3 seconds across TTL sweeps"""
    numbers = _Numbers()
    pool = yield from fx.Pool.make_with_ttl(
        numbers.plain(), min=0, max=10, time_to_live="10 seconds", time_to_live_strategy="usage"
    )
    for _ in range(20):
        yield from fx.scoped(pool.get())
        yield from testing.adjust("3 seconds")
    assert numbers.acquired == 1


class _FrozenClock:
    """A clock that always reads one wall time."""

    def __init__(self, inner: fx.clock.ClockService, now_nanos: int) -> None:
        self._inner = inner
        self._now_nanos = now_nanos

    def current_time_millis_unsafe(self) -> float:
        return self._now_nanos / 1e6

    def monotonic_unsafe(self) -> float:
        return self._inner.monotonic_unsafe()

    def now_nanos_unsafe(self) -> int:
        return self._now_nanos

    def monotonic_nanos_unsafe(self) -> int:
        return self._inner.monotonic_nanos_unsafe()

    def sleep(self, seconds: fx.duration.Seconds) -> fx.Effect[None]:
        return self._inner.sleep(seconds)


@testing.effect
def test_usage_ttl_measures_idle_time_with_the_pool_clock_when_a_release_runs_under_another_clock():
    """usage TTL idle timeout: measures idle time with the pool clock when a release runs under
    another clock"""
    pool = yield from fx.Pool.make_with_ttl(
        fx.succeed("resource"), min=0, max=1, time_to_live="1 second", time_to_live_strategy="usage"
    )
    clock = yield from fx.Clock()
    yield from pool.use(fx.succeed).pipe(
        fx.provide_service(fx.Clock, _FrozenClock(clock, 1_000_000 * 10**6))
    )
    yield from testing.adjust("999 millis")
    assert len(pool.state.items) == 1
    yield from testing.adjust("1 millis")
    assert len(pool.state.items) == 0


def _max_pool_size(concurrency: int, borrowers: int) -> fx.Effect[tuple[int, int]]:
    @fx.gen
    def body():
        deferred = yield from fx.Deferred[None].make()
        count = yield from fx.Ref.make(0)
        pool = yield from fx.Pool.make_with_ttl(
            _counted(count), min=10, max=15, concurrency=concurrency, time_to_live="1 minute"
        )
        for _ in range(borrowers):
            yield from fx.scoped(pool.get().and_then(deferred.wait())).fork()
        yield from _until(count, 15)
        yield from deferred.succeed(None)
        maximum = yield from count.get()
        yield from testing.adjust("1 minute")
        minimum = yield from count.get()
        return minimum, maximum

    return fx.scoped(body)


@testing.effect
def test_max_pool_size():
    """max pool size"""
    assert (yield from _max_pool_size(1, 15)) == (10, 15)


@testing.effect
def test_max_pool_size_with_concurrency_3():
    """max pool size with concurrency: 3"""
    assert (yield from _max_pool_size(3, 14 * 3 + 1)) == (10, 15)


@testing.effect
def test_usage_ttl_retains_shared_items_with_active_borrowers():
    """usage TTL retains shared items with active borrowers"""
    numbers = _Numbers()
    pool = yield from fx.Pool.make_with_ttl(
        numbers.plain(), min=0, max=2, concurrency=2, time_to_live="1 minute"
    )
    scope1 = yield from (yield from fx.Scope()).fork()
    assert (yield from _in(scope1, pool.get())) == 1
    assert (yield from pool.get()) == 1
    assert (yield from fx.scoped(pool.get())) == 2
    yield from testing.adjust("1 minute")
    assert len(pool.state.invalidated) == 0
    assert len(pool.state.items) == 1
    yield from scope1.close(_DONE)
    assert (yield from pool.get()) == 1
    assert (yield from pool.get()) == 3
    assert (yield from pool.get()) == 3
    assert numbers.acquired == 3


@testing.effect
def test_reserve_takes_an_item_out_of_shared_circulation():
    """reserve takes an item out of shared circulation"""
    count = yield from fx.Ref.make(0)
    pool = yield from fx.Pool.make_with_ttl(
        _counted(count), min=0, max=2, concurrency=2, time_to_live="1 minute"
    )
    scope1 = fx.CloseableScope()
    assert (yield from _in(scope1, pool.get())) == 1
    reservation = fx.CloseableScope()
    yield from _in(reservation, pool.reserve(1))
    # The reserved item counts as fully used, so the pool opens a second one
    # and both checkouts share it.
    assert (yield from _in(scope1, pool.get())) == 2
    assert (yield from _in(scope1, pool.get())) == 2
    # Everything is saturated: this checkout waits for the reservation.
    fiber = yield from _in(scope1, pool.get()).fork(start_immediately=True)
    yield from reservation.close(_DONE)
    assert (yield from fiber.join()) == 1
    assert (yield from count.get()) == 2
    yield from scope1.close(_DONE)


def _shared_resource_pool() -> fx.Effect[fx.Pool[str], Never, fx.Scope]:
    return fx.Pool.make(fx.succeed("resource"), size=1, concurrency=2)


@testing.effect
def test_releasing_a_shared_borrower_preserves_an_active_reservation():
    """releasing a shared borrower preserves an active reservation"""
    pool = yield from _shared_resource_pool()
    owner, borrower, reservation = (fx.CloseableScope() for _ in range(3))
    yield from _in(owner, pool.get())
    yield from _in(borrower, pool.get())
    yield from _in(reservation, pool.reserve("resource"))

    yield from borrower.close(_DONE)
    following = yield from pool.use(fx.succeed).fork(start_immediately=True)
    before_release = following.poll_unsafe()
    yield from reservation.close(_DONE)
    result = yield from following.join()
    yield from owner.close(_DONE)

    assert before_release is None
    assert result == "resource"


@testing.effect
def test_overlapping_reservations_keep_an_item_reserved_until_both_close():
    """overlapping reservations keep an item reserved until both close"""
    pool = yield from _shared_resource_pool()
    owner, first, second = (fx.CloseableScope() for _ in range(3))
    yield from _in(owner, pool.get())
    yield from _in(first, pool.reserve("resource"))
    yield from _in(second, pool.reserve("resource"))
    # One lease plus one reservation; the overlap counts no usage again.
    assert pool.state.usage == 2

    yield from first.close(_DONE)
    assert pool.state.usage == 2
    following = yield from pool.use(fx.succeed).fork(start_immediately=True)
    before_release = following.poll_unsafe()
    yield from second.close(_DONE)
    result = yield from following.join()
    yield from owner.close(_DONE)

    assert before_release is None
    assert result == "resource"
    assert pool.state.usage == 0


@testing.effect
def test_releasing_a_reservation_wakes_all_available_slots_after_borrowers_return():
    """releasing a reservation wakes all available slots after borrowers return"""
    pool = yield from _shared_resource_pool()
    owner, reservation, borrowers = (fx.CloseableScope() for _ in range(3))
    yield from _in(owner, pool.get())
    yield from _in(reservation, pool.reserve("resource"))
    yield from owner.close(_DONE)

    first = yield from _in(borrowers, pool.get()).fork(start_immediately=True)
    second = yield from _in(borrowers, pool.get()).fork(start_immediately=True)
    before_release = [first.poll_unsafe(), second.poll_unsafe()]
    yield from reservation.close(_DONE)
    yield from testing.adjust(0)
    after_release = [first.poll_unsafe(), second.poll_unsafe()]
    yield from first.interrupt()
    yield from second.interrupt()
    yield from borrowers.close(_DONE)

    assert before_release == [None, None]
    assert after_release == [fx.Success("resource"), fx.Success("resource")]
    assert pool.state.usage == 0


@testing.effect
def test_usage_ttl_preserves_reservations_and_waits_for_capacity():
    """usage TTL preserves reservations and waits for capacity"""
    numbers = _Numbers()
    pool = yield from fx.Pool.make_with_ttl(
        numbers.plain(), min=0, max=2, concurrency=2, time_to_live="1 second"
    )
    scope = yield from fx.Scope()
    owner = yield from scope.fork()
    reservation = yield from scope.fork()
    yield from _in(owner, pool.get())
    yield from _in(reservation, pool.reserve(1))
    yield from pool.use(fx.succeed)
    yield from testing.adjust("1 second")
    assert len(pool.state.items) == 1
    assert len(pool.state.invalidated) == 0

    first = yield from _in(owner, pool.get())
    second = yield from _in(owner, pool.get())
    following = yield from pool.use(fx.succeed).fork(start_immediately=True)
    assert following.poll_unsafe() is None
    yield from reservation.close(_DONE)
    result = yield from following.join()
    yield from owner.close(_DONE)

    assert [first, second] == [3, 3]
    assert result == 1
    assert numbers.acquired == 3
    assert pool.state.usage == 0


@testing.effect
def test_reserve_is_a_no_op_with_concurrency_one():
    """reserve is a no-op with concurrency one"""
    pool = yield from fx.Pool.make(fx.succeed("resource"), size=1)
    owner = fx.CloseableScope()
    reservation = fx.CloseableScope()
    yield from _in(owner, pool.get())
    yield from _in(reservation, pool.reserve("resource"))
    yield from owner.close(_DONE)

    following = yield from pool.use(fx.succeed).fork(start_immediately=True)
    before_release = following.poll_unsafe()
    yield from reservation.close(_DONE)
    yield from following.interrupt()

    assert before_release == fx.Success("resource")


@pytest.mark.parametrize("shutdown", [False, True])
@testing.effect
def test_reservation_cleanup_does_not_revive_removed_items(shutdown: bool):
    """reservation cleanup does not revive removed items (shutdown: %s)"""
    numbers = _Numbers()
    pool_scope, owner, reservation = (fx.CloseableScope() for _ in range(3))
    pool = yield from _in(pool_scope, fx.Pool.make(numbers.scoped(), size=1, concurrency=2))
    yield from _in(owner, pool.get())
    yield from _in(reservation, pool.reserve(1))
    yield from owner.close(_DONE)
    if shutdown:
        yield from pool_scope.close(_DONE)
    else:
        yield from pool.invalidate(1)
    yield from reservation.close(_DONE)
    following = yield from pool.use(fx.succeed).exit()
    yield from pool_scope.close(_DONE)

    if shutdown:
        assert _interrupted(following)
        assert numbers.finalized == [1]
    else:
        assert following == fx.Success(2)
        assert numbers.finalized == [1, 2]
    assert pool.state.usage == 0


@testing.effect
def test_scale_to_zero():
    """scale to zero"""
    deferred = yield from fx.Deferred[None].make()
    count = yield from fx.Ref.make(0)
    pool = yield from fx.Pool.make_with_ttl(
        _counted(count), min=0, max=10, concurrency=3, time_to_live="1 minute"
    )
    for _ in range(30):
        yield from fx.scoped(pool.get().and_then(deferred.wait())).fork()
    yield from _until(count, 10)
    yield from deferred.succeed(None)
    maximum = yield from count.get()
    # Effect serves every waiter as the items arrive; pyfect wakes them one
    # scheduler task at a time, so let the last borrowers return before time
    # moves on.
    yield from _wait_until(lambda: pool.state.usage == 0)
    yield from testing.adjust("1 minute")
    minimum = yield from count.get()
    assert (minimum, maximum) == (0, 10)


@testing.effect
def test_max_pool_size_creation_strategy():
    """max pool size creation strategy"""
    invalidated = yield from fx.Ref.make(0)
    acquire = fx.acquire_release(
        fx.succeed("resource"), lambda _a, _e: invalidated.update(lambda n: n + 1)
    )
    pool = yield from fx.Pool.make_with_ttl(
        acquire, min=10, max=15, time_to_live="1 minute", time_to_live_strategy="creation"
    )
    scope = fx.CloseableScope()
    yield from _in(scope, pool.get().repeat(times=14))
    one = yield from invalidated.get()
    yield from testing.adjust("1 minute")
    two = yield from invalidated.get()
    yield from scope.close(_DONE)
    three = yield from invalidated.get()
    assert (one, two, three) == (0, 0, 15)


@testing.effect
def test_shutdown_robustness():
    """shutdown robustness"""
    count = yield from fx.Ref.make(0)
    scope = fx.CloseableScope()
    pool = yield from _in(scope, fx.Pool.make(_counted(count), size=10))
    for _ in range(100):
        yield from fx.scoped(pool.get()).fork()
    yield from scope.close(_DONE)
    assert (yield from _until(count, 0)) == 0


@testing.effect
def test_shutdown_with_pending_takers():
    """shutdown with pending takers"""
    count = yield from fx.Ref.make(0)
    scope = fx.CloseableScope()
    pool = yield from _in(scope, fx.Pool.make(_counted(count), size=10))
    for _ in range(100):
        yield from _in(scope, pool.get()).fork()
    yield from scope.close(_DONE)
    assert (yield from _until(count, 0)) == 0


@testing.effect
def test_get_is_interruptible():
    """get is interruptible"""
    count = yield from fx.Ref.make(0)
    me = yield from fx.fiber_id()
    pool = yield from fx.Pool.make(_counted(count), size=10)
    yield from pool.get().repeat(times=9)
    fiber = yield from pool.get().fork()
    yield from fiber.interrupt()
    assert fiber.poll_unsafe() == fx.Failure(fx.cause.interrupt(me))


@testing.effect
def test_get_is_interruptible_with_dynamic_size():
    """get is interruptible with dynamic size"""
    acquire = fx.never.fork_scoped()
    me = yield from fx.fiber_id()
    pool = yield from fx.Pool.make_with_ttl(acquire, min=0, max=10, time_to_live=float("inf"))
    yield from pool.get().repeat(times=9)
    fiber = yield from pool.get().fork()
    yield from fiber.interrupt()
    assert (yield from fiber.await_exit()) == fx.Failure(fx.cause.interrupt(me))


@testing.effect
def test_interrupts_pending_gets_without_leaking_usage():
    """interrupts pending gets without leaking usage"""
    pool = yield from fx.Pool.make(fx.succeed("resource"), size=1)
    scope = fx.CloseableScope()
    yield from _in(scope, pool.get())
    fibers: list[fx.Fiber[str]] = []
    for _ in range(10):
        fibers.append((yield from pool.get().fork(start_immediately=True)))  # noqa: PERF401
    yield from _wait_until(lambda: len(pool.state.waiters) == len(fibers))
    yield from fx.Fiber.interrupt_all(fibers)
    assert len(pool.state.waiters) == 0
    assert pool.state.usage == 1
    yield from scope.close(_DONE)
    assert pool.state.usage == 0


@testing.effect
def test_does_not_re_wake_waiters_registered_during_notification():
    """does not re-wake waiters registered during notification"""
    acquire = yield from fx.Deferred[None].make()
    pool = yield from fx.Pool.make_with_ttl(
        acquire.wait().as_("resource"), min=0, max=1, time_to_live=float("inf")
    )
    fibers: list[fx.Fiber[str]] = []
    for _ in range(10):
        fibers.append((yield from fx.scoped(pool.get()).fork(start_immediately=True)))  # noqa: PERF401
    yield from _wait_until(lambda: len(pool.state.waiters) == len(fibers))
    yield from acquire.succeed(None)
    yield from fx.Fiber.join_all(fibers)
    assert len(pool.state.waiters) == 0
    assert pool.state.usage == 0


@testing.effect
def test_use_borrows_and_returns_an_item():
    """use borrows and returns an item"""
    count = yield from fx.Ref.make(0)
    pool = yield from fx.Pool.make(_counted(count), size=2)
    yield from _until(count, 2)
    results: list[int] = []
    yield from (
        pool.use(fx.succeed).tap(lambda item: fx.sync(lambda: results.append(item))).repeat(times=9)
    )
    # A borrow takes the item used most recently, so a sequence of them
    # stays on one item and leaves the other free to be reclaimed.
    assert results == [1] * 10
    assert (yield from count.get()) == 2


@testing.effect
def test_use_releases_the_item_on_failure():
    """use releases the item on failure"""
    pool = yield from fx.Pool.make(fx.succeed("resource"), size=1)
    assert (yield from pool.use(lambda _: fx.fail("boom")).flip()) == "boom"
    assert (yield from pool.use(fx.succeed)) == "resource"


@testing.effect
def test_use_releases_the_item_on_interruption():
    """use releases the item on interruption"""
    started = yield from fx.Deferred[None].make()
    pool = yield from fx.Pool.make(fx.succeed("resource"), size=1)
    fiber = yield from pool.use(lambda _: started.succeed(None).and_then(fx.never)).fork(
        start_immediately=True
    )
    yield from started.wait()
    yield from fiber.interrupt()
    assert (yield from pool.use(fx.succeed)) == "resource"


@testing.effect
def test_an_interrupted_use_returns_its_lease():
    """an interrupted use returns its lease"""
    for budget in range(1, 11):
        pool = yield from fx.Pool.make(fx.succeed("resource"), size=1)
        fiber = yield from (
            pool.use(lambda _: fx.never)
            .pipe(fx.provide_service(fx.MaxOpsBeforeYield, budget))
            .fork(start_immediately=True)
        )
        yield from fiber.interrupt()
        assert pool.state.usage == 0, f"MaxOpsBeforeYield {budget}"
        following = yield from pool.use(fx.succeed).fork(start_immediately=True)
        assert following.poll_unsafe() is not None, f"MaxOpsBeforeYield {budget}"


@testing.effect
def test_use_waits_for_an_available_item():
    """use waits for an available item"""
    pool = yield from fx.Pool.make(fx.succeed("resource"), size=1)
    scope = fx.CloseableScope()
    yield from _in(scope, pool.get())
    fiber = yield from pool.use(fx.succeed).fork(start_immediately=True)
    assert fiber.poll_unsafe() is None
    yield from scope.close(_DONE)
    assert (yield from fiber.join()) == "resource"
    assert pool.state.usage == 0


@testing.effect
def test_serves_a_waiter_before_a_later_borrower_takes_the_released_item():
    """serves a waiter before a later borrower takes the released item"""
    pool = yield from fx.Pool.make(fx.succeed("resource"), size=1)
    busy_borrows = 0

    @fx.gen
    def busy():
        nonlocal busy_borrows
        for _ in range(100):
            yield from pool.use(lambda _: fx.yield_now())
            busy_borrows += 1

    busy_fiber = yield from busy.fork()
    yield from fx.yield_now()
    waited_borrows = yield from pool.use(lambda _: fx.sync(lambda: busy_borrows))
    yield from busy_fiber.join()
    assert waited_borrows <= 1


def _interrupt_first(fibers: list[fx.Fiber[None]]) -> fx.Effect[None]:
    return fibers[0].interrupt()


@testing.effect
def test_wakes_the_next_waiter_when_a_woken_waiter_interrupts_another():
    """wakes the next waiter when a woken waiter interrupts another"""
    pool = yield from fx.Pool.make(fx.succeed("resource"), size=1, concurrency=3)
    owner = fx.CloseableScope()
    yield from _in(owner, pool.get())
    reservation = fx.CloseableScope()
    yield from _in(reservation, pool.reserve("resource"))
    b: list[fx.Fiber[None]] = []
    a = yield from pool.use(
        lambda _: fx.suspend(lambda: _interrupt_first(b)).and_then(fx.never)
    ).fork(start_immediately=True)
    b.append((yield from pool.use(lambda _: fx.void).fork(start_immediately=True)))
    c = yield from pool.use(fx.succeed).fork(start_immediately=True)
    # Frees two slots: one for `a`, and one for `c` once `a` interrupts `b`.
    yield from reservation.close(_DONE)
    assert (yield from c.join()) == "resource"
    assert _interrupted((yield from b[0].await_exit()))
    yield from a.interrupt()
    yield from owner.close(_DONE)
    assert pool.state.usage == 0


@testing.effect
def test_serves_a_waiter_while_another_acquisition_is_still_pending():
    """serves a waiter while another acquisition is still pending"""
    acquisitions = [fx.Deferred[None]() for _ in range(2)]
    acquired = 0

    def acquire() -> fx.Effect[int]:
        nonlocal acquired
        index = acquired
        acquired += 1
        return acquisitions[index].wait().as_(index)

    pool = yield from fx.Pool.make(fx.suspend(acquire), size=2)
    waiter = yield from pool.use(fx.succeed).fork(start_immediately=True)
    yield from acquisitions[0].succeed(None)
    assert (yield from waiter.join()) == 0
    assert pool.state.usage == 0


@testing.effect
def test_wakes_the_next_waiter_when_a_woken_waiter_is_interrupted_before_it_takes_the_item():
    """wakes the next waiter when a woken waiter is interrupted before it takes the item"""
    pool = yield from fx.Pool.make(fx.succeed("resource"), size=1)
    owner = fx.CloseableScope()
    yield from _in(owner, pool.get())
    # Effect lets `first` yield once as soon as it is woken (a custom
    # ``shouldYield``). Here `first` yields after every step onto its own
    # task queue: run until it parks, then once woken it pauses there.
    held = TaskQueue()
    first = yield from held.provide(_with_budget(pool.use(fx.succeed), 1)).fork(
        start_immediately=True
    )
    yield from held.run_all()
    second = yield from pool.use(fx.succeed).fork(start_immediately=True)
    yield from owner.close(_DONE)
    yield from fx.yield_now()
    assert len(held.tasks) == 1  # `first` is awake
    yield from first.interrupt().pipe(lambda eff: _drain_while(held, eff))
    assert (yield from second.join()) == "resource"
    assert _interrupted((yield from first.await_exit()))
    assert pool.state.usage == 0


def _with_budget[A, E](eff: fx.Effect[A, E], budget: int) -> fx.Effect[A, E]:
    return eff.pipe(fx.provide_service(fx.MaxOpsBeforeYield, budget))


def _drain_while[A](held: TaskQueue, eff: fx.Effect[A]) -> fx.Effect[A]:
    """Run ``eff`` while running the tasks ``held`` collects."""

    @fx.gen
    def body():
        fiber = yield from eff.fork(start_immediately=True)
        while fiber.poll_unsafe() is None:
            yield from held.run_all()
            yield from fx.yield_now()
        return (yield from fiber.join())

    return body


@testing.effect
def test_wakes_the_next_waiter_when_a_woken_waiter_has_yet_to_take_its_item():
    """wakes the next waiter when a woken waiter has yet to take its item"""
    numbers = _Numbers()
    pool = yield from fx.Pool.make(numbers.plain(), size=2)
    owners = [fx.CloseableScope(), fx.CloseableScope()]
    for owner in owners:
        yield from _in(owner, pool.get())
    # `first` runs on its own task queue: once woken, it waits there until
    # the queue runs.
    held = TaskQueue()
    first = yield from held.provide(pool.use(lambda _: fx.never)).fork(start_immediately=True)
    second = yield from pool.use(fx.succeed).fork(start_immediately=True)
    yield from owners[0].close(_DONE)
    yield from fx.yield_now()
    # `first` is awake but has not taken its item, so this wake is `second`'s.
    yield from owners[1].close(_DONE)
    yield from fx.yield_now()
    assert isinstance((yield from second.join()), int)
    yield from held.run_all()
    yield from first.interrupt().pipe(lambda eff: _drain_while(held, eff))
    assert pool.state.usage == 0


@testing.effect
def test_wakes_the_next_waiter_when_a_waiter_is_woken_during_its_interruption():
    """wakes the next waiter when a waiter is woken during its interruption"""
    # Each budget makes the interrupted waiter yield at a different point of
    # its cleanup, so the wake lands while that cleanup is in progress.
    for budget in range(1, 11):
        pool = yield from fx.Pool.make(fx.succeed("resource"), size=1)
        owner = fx.CloseableScope()
        yield from _in(owner, pool.get())
        first = yield from (
            pool.use(fx.succeed)
            .pipe(fx.provide_service(fx.MaxOpsBeforeYield, budget))
            .fork(start_immediately=True)
        )
        yield from _wait_until(lambda pool=pool: len(pool.state.waiters) == 1)
        second = yield from pool.use(fx.succeed).fork(start_immediately=True)
        yield from owner.close(_DONE)
        first.interrupt_as_unsafe(None)
        assert (yield from second.join()) == "resource", f"MaxOpsBeforeYield {budget}"


@testing.effect
def test_use_reports_acquire_failures():
    """use reports acquire failures"""
    pool = yield from fx.Pool.make_with_ttl(
        fx.fail("nope"), min=0, max=1, time_to_live=float("inf")
    )
    assert (yield from pool.use(lambda _: fx.void).flip()) == "nope"
    assert pool.state.usage == 0


@testing.effect
def test_finalizer_is_called_for_failed_allocations():
    """finalizer is called for failed allocations"""
    scope = fx.CloseableScope()
    allocations = yield from fx.Ref.make(0)
    released = yield from fx.Ref.make(0)
    acquire = fx.acquire_release(
        allocations.update_and_get(lambda n: n + 1),
        lambda _a, _e: released.update(lambda n: n + 1),
    ).flat_map(lambda n: fx.fail("boom") if n <= 10 else fx.succeed(n))
    pool = yield from _in(scope, fx.Pool.make(acquire, size=10))
    yield from _until(released, 10)
    assert (yield from fx.scoped(pool.get())) == 11
    assert (yield from allocations.get()) == 11
    assert (yield from released.get()) == 10
    yield from scope.close(_DONE)


def _no_reclaim(_: fx.Pool[Any, Any]) -> fx.Effect[PoolItem[Any, Any] | None]:
    return fx.succeed(None)


def _no_run(_: fx.Pool[Any, Any]) -> fx.Effect[None]:
    return fx.void


@testing.effect
def test_runs_strategy_callbacks_for_a_replacement_before_failed_background_cleanup():
    """runs strategy callbacks for a replacement before failed background cleanup"""
    cleanup_started = yield from fx.Deferred[None].make()
    resume_cleanup = yield from fx.Deferred[None].make()
    replacement_acquired = yield from fx.Deferred[None].make()
    acquired = 0
    callbacks = 0

    @fx.gen
    def acquire():
        nonlocal acquired
        acquired += 1
        if acquired > 1:
            return "replacement"
        yield from fx.add_finalizer(
            lambda _: cleanup_started.succeed(None).and_then(resume_cleanup.wait())
        )
        return (yield from fx.fail("boom"))

    def on_acquire(item: PoolItem[Any, Any]) -> fx.Effect[None]:
        nonlocal callbacks
        callbacks += 1
        if isinstance(item.exit, fx.Success):
            return replacement_acquired.succeed(None).as_void()
        return fx.void

    pool = yield from fx.Pool.make_with_strategy(
        acquire,
        min=1,
        max=2,
        strategy=Strategy(_no_run, lambda item: fx.suspend(lambda: on_acquire(item)), _no_reclaim),
    )
    yield from fx.add_finalizer(lambda _: resume_cleanup.succeed(None))
    yield from cleanup_started.wait()
    assert (yield from fx.scoped(pool.get())) == "replacement"
    yield from fx.yield_now()
    assert (yield from replacement_acquired.is_done()) is True
    assert acquired == 2
    assert callbacks == 1
    yield from resume_cleanup.succeed(None)


@testing.effect
def test_serves_a_waiter_from_capacity_a_strategy_reclaims():
    """serves a waiter from capacity a strategy reclaims"""
    reclaim_gate = yield from fx.Deferred[None].make()

    def reclaim(pool: fx.Pool[str, Never]) -> fx.Effect[PoolItem[str, Never] | None]:
        # Revive an invalidated item instead of acquiring a replacement.
        def body() -> fx.Effect[PoolItem[str, Never] | None]:
            item = next(iter(pool.state.invalidated), None)
            if item is None:
                return fx.succeed(None)

            def revive() -> PoolItem[str, Never]:
                del pool.state.invalidated[item]
                return item

            return reclaim_gate.wait().and_then(fx.sync(revive))

        return fx.suspend(body)

    pool = yield from fx.Pool.make_with_strategy(
        fx.succeed("resource"),
        min=1,
        max=1,
        concurrency=2,
        strategy=Strategy(_no_run, lambda _: fx.void, reclaim),
    )
    owner = fx.CloseableScope()
    borrower = fx.CloseableScope()
    yield from _in(owner, pool.get())
    yield from _in(borrower, pool.get())
    waiter = yield from pool.use(fx.succeed).fork(start_immediately=True)
    yield from pool.invalidate("resource")
    yield from borrower.close(_DONE)
    # Reclaiming the item frees the slot `borrower` returned.
    yield from reclaim_gate.succeed(None)
    assert (yield from waiter.join()) == "resource"
    yield from owner.close(_DONE)
    assert pool.state.usage == 0


@testing.effect
def test_admits_one_waiter_per_released_lease():
    """admits one waiter per released lease"""
    acquired = yield from fx.Ref.make(0)
    pool = yield from fx.Pool.make_with_ttl(
        fx.succeed("item"), min=0, max=1, concurrency=4, time_to_live="1 minute"
    )
    release = yield from fx.Deferred[None].make()
    lease = fx.scoped(
        pool.get().and_then(acquired.update(lambda n: n + 1)).and_then(release.wait())
    )
    # Four leases saturate the only item; four more have to wait.
    fibers: list[fx.Fiber[None]] = []
    for _ in range(8):
        fibers.append((yield from lease.fork(start_immediately=True)))  # noqa: PERF401
    yield from _until(acquired, 4)
    # Releasing all four at once has to admit all four waiters.
    yield from release.succeed(None)
    yield from fx.Fiber.join_all(fibers)
    assert (yield from acquired.get()) == 8
    assert pool.state.usage == 0


class _Resource:
    """A weakly referenceable resource."""


def _collected(references: list[weakref.ref[Any]]) -> fx.Effect[bool]:
    """Whether every referent is gone, collecting across scheduler turns as
    Effect's ``collectGarbage`` collects across jobs: a turn's tasks stay
    referenced until it ends."""

    @fx.gen
    def body():
        for _ in range(8):
            yield from fx.yield_now()
            gc.collect()
        return all(reference() is None for reference in references)

    return body


@testing.effect
def test_usage_ttl_retention_releases_invalidated_resources_while_at_minimum_size():
    """usage TTL retention: releases invalidated resources while at minimum size"""
    references: list[weakref.ref[_Resource]] = []
    finalized = 0

    def finalize() -> None:
        nonlocal finalized
        finalized += 1

    pool = yield from fx.Pool.make_with_ttl(
        fx.acquire_release(fx.sync(_Resource), lambda _a, _e: fx.sync(finalize)),
        min=1,
        max=2,
        time_to_live="1 hour",
    )
    for _ in range(2):

        @fx.gen
        def borrow():
            value = yield from pool.get()
            references.append(weakref.ref(value))
            yield from pool.invalidate(value)

        yield from fx.scoped(borrow)
    assert finalized == 2
    assert (yield from _collected(references))
    assert len(pool.state.items) == 1


@testing.effect
def test_usage_ttl_retention_releases_consumed_acquisition_failures():
    """usage TTL retention: releases consumed acquisition failures"""
    references: list[weakref.ref[_Resource]] = []

    def acquire() -> fx.Effect[Never, _Resource]:
        error = _Resource()
        references.append(weakref.ref(error))
        return fx.fail(error)

    pool = yield from fx.Pool.make_with_ttl(
        fx.suspend(acquire), min=0, max=2, time_to_live="1 hour"
    )
    for _ in range(2):
        assert isinstance((yield from fx.scoped(pool.get()).exit()), fx.Failure)
    assert len(references) == 2
    assert (yield from _collected(references))
    assert len(pool.state.items) == 0


@testing.effect
def test_usage_ttl_retention_retries_background_failures_during_asynchronous_cleanup():
    """usage TTL retention: retries background failures during asynchronous cleanup without
    requeueing them"""
    references: list[weakref.ref[_Resource]] = []
    cleanup_started = yield from fx.Deferred[None].make()
    resume_cleanup = yield from fx.Deferred[None].make()
    acquired = 0
    finalized = 0

    @fx.gen
    def cleanup():
        nonlocal finalized
        yield from cleanup_started.succeed(None)
        yield from resume_cleanup.wait()
        finalized += 1

    @fx.gen
    def acquire():
        nonlocal acquired
        acquired += 1
        if acquired > 1:
            return "replacement"
        yield from fx.add_finalizer(lambda _: cleanup)
        error = _Resource()
        references.append(weakref.ref(error))
        return (yield from fx.fail(error))

    pool = yield from fx.Pool.make_with_ttl(acquire, min=1, max=2, time_to_live="1 hour")
    yield from fx.add_finalizer(lambda _: resume_cleanup.succeed(None))
    yield from cleanup_started.wait()
    assert (yield from fx.scoped(pool.get())) == "replacement"
    assert finalized == 0
    yield from resume_cleanup.succeed(None)
    yield from fx.yield_now()  # Effect resumes the cleanup within ``succeed``
    assert acquired == 2
    assert finalized == 1
    assert len(references) == 1
    assert (yield from _collected(references))
    assert len(pool.state.items) == 1


@testing.effect
def test_usage_ttl_retention_releases_resources_after_shutdown_while_the_pool_remains_reachable():
    """usage TTL retention: releases resources after shutdown while the pool remains reachable"""
    references: list[weakref.ref[_Resource]] = []
    finalized = 0

    def finalize() -> None:
        nonlocal finalized
        finalized += 1

    scope = yield from (yield from fx.Scope()).fork()
    pool = yield from _in(
        scope,
        fx.Pool.make_with_ttl(
            fx.acquire_release(fx.sync(_Resource), lambda _a, _e: fx.sync(finalize)),
            min=1,
            max=2,
            time_to_live="1 hour",
        ),
    )
    yield from pool.use(lambda value: fx.sync(lambda: references.append(weakref.ref(value))))
    yield from scope.close(_DONE)
    assert finalized == 1
    assert len(references) == 1
    assert (yield from _collected(references))
    assert len(pool.state.items) == 0


@testing.effect
def test_invalidating_a_busy_item_waits_for_its_last_lease_and_finalizes_once():
    """invalidating a busy item waits for its last lease and finalizes once"""
    numbers = _Numbers()

    @fx.gen
    def body():
        pool = yield from fx.Pool.make_with_ttl(
            numbers.scoped(), min=1, max=2, concurrency=2, time_to_live="1 hour"
        )
        scope = yield from fx.Scope()
        first = yield from scope.fork()
        second = yield from scope.fork()
        value = yield from _in(first, pool.get())
        assert (yield from _in(second, pool.get())) == value
        yield from pool.invalidate(value)
        assert numbers.finalized == []
        yield from first.close(_DONE)
        assert numbers.finalized == []
        yield from second.close(_DONE)
        assert numbers.finalized == [value]
        assert (yield from fx.scoped(pool.get())) == 2

    yield from fx.scoped(body)
    assert numbers.finalized == [1, 2]


@pytest.mark.parametrize(("removal", "removed"), [("no", None), ("middle", 2), ("tail", 3)])
@testing.effect
def test_usage_ttl_preserves_fifo_retirement_and_minimum_size(removal: str, removed: int | None):
    """usage TTL preserves FIFO retirement and minimum size after ${removal} removal"""
    numbers = _Numbers()
    pool = yield from fx.Pool.make_with_ttl(numbers.scoped(), min=1, max=3, time_to_live="1 second")

    def borrow_three(acquired: int) -> fx.Effect[None]:
        @fx.gen
        def body():
            for _ in range(3):
                yield from pool.get()
            assert numbers.acquired == acquired

        return fx.scoped(body)

    yield from borrow_three(3)
    if removed is not None:
        yield from pool.invalidate(removed)
        assert numbers.finalized == [removed]
        yield from borrow_three(4)
    expected = [1, 2] if removed is None else [removed, *(n for n in (1, 2, 3) if n != removed)]
    yield from testing.adjust("1 second")
    assert numbers.finalized == expected
    yield from testing.adjust("5 seconds")
    assert numbers.finalized == expected
    assert len(pool.state.items) == 1
    assert (yield from fx.scoped(pool.get())) == (3 if removed is None else 4)
    if removed is not None:
        yield from borrow_three(6)
        yield from testing.adjust("1 second")
        assert numbers.finalized == [*expected, 4, 5]
        assert len(pool.state.items) == 1
        assert (yield from fx.scoped(pool.get())) == 6


# --- Effect 4.1.2 ---------------------------------------------------------------


@testing.effect
def test_admits_requests_in_fifo_order_when_a_borrower_immediately_reacquires():
    """admits requests in FIFO order when a borrower immediately reacquires"""
    pool = yield from fx.Pool.make(fx.succeed("connection"), size=1)
    asked = 0
    admitted: list[int] = []

    def body() -> Any:
        nonlocal asked
        ticket = asked
        asked += 1
        yield from pool.get()
        admitted.append(ticket)
        yield from fx.sleep("10 millis")

    use = fx.scoped(fx.gen(body))
    chained = yield from use.repeat(times=2).fork()
    others = yield from fx.for_each((1, 2, 3), lambda at: use.delay(f"{at} millis").fork())
    yield from testing.adjust("100 millis")
    yield from chained.join()
    yield from fx.Fiber.join_all(others)
    assert admitted == [0, 1, 2, 3, 4, 5]


@testing.effect
def test_a_later_finalizer_of_the_pools_scope_can_get_an_item_after_idle_items_expire():
    """a later finalizer of the pool's scope can get an item after idle items expire"""
    acquired = 0

    def acquire() -> int:
        nonlocal acquired
        acquired += 1
        return acquired

    scope = fx.CloseableScope()
    pool = yield from _in(
        scope, fx.Pool.make_with_ttl(fx.sync(acquire), min=0, max=1, time_to_live="1 second")
    )
    result: list[fx.Exit[int, Never]] = []
    yield from scope.add_finalizer(lambda _: fx.scoped(pool.get()).exit().map(result.append))
    yield from fx.scoped(pool.get())
    yield from testing.adjust("2 seconds")
    closing = yield from scope.close(_DONE).fork_daemon()
    for _ in range(100):
        if closing.poll_unsafe() is not None:
            break
        yield from fx.yield_now()
    assert closing.poll_unsafe() is not None, "Scope.close did not return"
    assert result == [fx.Success(2)]


def _stats(idle: int, used: int, pending: int, low: int, high: int) -> PoolStats:
    return PoolStats(idle=idle, used=used, pending=pending, min=low, max=high)


@testing.effect
def test_stats_counts_leased_items_rather_than_borrowers_and_parked_waiters_as_pending():
    """counts leased items rather than borrowers, and parked waiters as pending"""
    acquired = 0

    def acquire() -> int:
        nonlocal acquired
        acquired += 1
        return acquired

    pool = yield from fx.Pool.make(fx.sync(acquire), size=2, concurrency=2)
    yield from _wait_until(lambda: acquired == 2)
    assert (yield from pool.stats()) == _stats(2, 0, 0, 2, 2)
    outer = yield from fx.Scope()
    leases = outer.fork_unsafe()
    yield from _in(leases, pool.get())
    yield from _in(leases, pool.get())
    assert (yield from pool.stats()) == _stats(1, 1, 0, 2, 2)
    yield from _in(leases, pool.get())
    yield from _in(leases, pool.get())
    assert (yield from pool.stats()) == _stats(0, 2, 0, 2, 2)
    waiter = outer.fork_unsafe()
    fiber = yield from _in(waiter, pool.get()).fork(start_immediately=True)
    assert (yield from pool.stats()) == _stats(0, 2, 1, 2, 2)
    yield from leases.close(_DONE)
    yield from fiber.join()
    assert (yield from pool.stats()) == _stats(1, 1, 0, 2, 2)
    yield from waiter.close(_DONE)


@testing.effect
def test_stats_counts_a_reserved_item_as_used_after_its_borrowers_return():
    """counts a reserved item as used after its borrowers return"""
    resource = "resource"
    pool = yield from fx.Pool.make(fx.succeed(resource), size=1, concurrency=2)
    outer = yield from fx.Scope()
    lease = outer.fork_unsafe()
    reservation = outer.fork_unsafe()
    yield from _in(lease, pool.get())
    yield from _in(reservation, pool.reserve(resource))
    yield from lease.close(_DONE)
    assert (yield from pool.stats()) == _stats(0, 1, 0, 1, 1)
    yield from reservation.close(_DONE)
    assert (yield from pool.stats()) == _stats(1, 0, 0, 1, 1)


@testing.effect
def test_stats_counts_an_invalidated_item_as_used_until_its_last_borrower_returns():
    """counts an invalidated item as used until its last borrower returns"""
    acquired = 0

    def acquire() -> int:
        nonlocal acquired
        acquired += 1
        return acquired

    pool = yield from fx.Pool.make(fx.sync(acquire), size=1)
    lease = (yield from fx.Scope()).fork_unsafe()
    item = yield from _in(lease, pool.get())
    yield from pool.invalidate(item)
    yield from _wait_until(lambda: acquired == 2)
    # The invalidated session is still open, so both count against ``max``.
    assert (yield from pool.stats()) == _stats(1, 1, 0, 1, 1)
    yield from lease.close(_DONE)
    assert (yield from pool.stats()) == _stats(1, 0, 0, 1, 1)


@testing.effect
def test_stats_does_not_count_failed_acquisitions():
    """does not count failed acquisitions"""
    attempts = 0

    def attempt() -> fx.Effect[int, str]:
        nonlocal attempts
        attempts += 1
        return fx.fail("boom") if attempts == 2 else fx.succeed(attempts)

    pool = yield from fx.Pool.make(fx.suspend(attempt), size=2)
    yield from _wait_until(lambda: len(pool.state.items) == 2)
    assert (yield from pool.stats()) == _stats(1, 0, 0, 2, 2)
