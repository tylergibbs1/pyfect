"""TxQueue, TxSemaphore and TxReentrantLock behavior beyond Effect's tests:
claims that survive an interrupt at any step, and queue operations as parts
of larger transactions."""

from collections.abc import Callable
from typing import Any

import pytest

import pyfect as fx
from pyfect import testing


def _with_budget[A, E](eff: fx.Effect[A, E], budget: int) -> fx.Effect[A, E]:
    return eff.pipe(fx.provide_service(fx.MaxOpsBeforeYield, budget))


_HOLDERS: list[tuple[str, Callable[[fx.TxSemaphore], fx.Effect[Any]]]] = [
    ("with_permit", lambda semaphore: semaphore.with_permit(fx.never)),
    ("with_permits", lambda semaphore: semaphore.with_permits(fx.never, 1)),
    ("with_permit_scoped", lambda s: fx.scoped(s.with_permit_scoped().and_then(fx.never))),
]


@pytest.mark.parametrize(("name", "hold"), _HOLDERS, ids=[h[0] for h in _HOLDERS])
@testing.effect
def test_an_interrupt_at_any_step_of_taking_a_permit_gives_it_back(
    name: str, hold: Callable[[fx.TxSemaphore], fx.Effect[Any]]
):
    # The budgets pause the holder at every step, including the one right
    # after its transaction commits the permit and before the release is
    # guarded; an interrupt landing there must not keep the permit.
    for budget in range(1, 80):
        semaphore = yield from fx.TxSemaphore.make(1)
        holder = yield from _with_budget(hold(semaphore), budget).fork(start_immediately=True)
        yield from holder.interrupt()
        assert (yield from semaphore.available()) == 1, (name, budget)


_LOCKERS: list[tuple[str, Callable[[fx.TxReentrantLock], fx.Effect[Any]]]] = [
    ("with_read_lock", lambda lock: lock.with_read_lock(fx.never)),
    ("with_write_lock", lambda lock: lock.with_write_lock(fx.never)),
    ("read_lock", lambda lock: fx.scoped(lock.read_lock().and_then(fx.never))),
    ("write_lock", lambda lock: fx.scoped(lock.write_lock().and_then(fx.never))),
]


@pytest.mark.parametrize(("name", "hold"), _LOCKERS, ids=[h[0] for h in _LOCKERS])
@testing.effect
def test_an_interrupt_at_any_step_of_taking_a_lock_releases_it(
    name: str, hold: Callable[[fx.TxReentrantLock], fx.Effect[Any]]
):
    for budget in range(1, 80):
        lock = yield from fx.TxReentrantLock.make()
        holder = yield from _with_budget(hold(lock), budget).fork(start_immediately=True)
        yield from holder.interrupt()
        assert (yield from lock.locked()) is False, (name, budget)


@testing.effect
def test_with_permit_inside_a_transaction_commits_nothing_net():
    semaphore = yield from fx.TxSemaphore.make(1)
    seen = yield from fx.tx(semaphore.with_permit(semaphore.available()))
    assert seen == 0
    assert (yield from semaphore.available()) == 1


@testing.effect
def test_offer_all_to_a_bounded_queue_adds_all_or_waits():
    queue = yield from fx.TxQueue[int].bounded(2)
    yield from queue.offer(0)
    offer = yield from queue.offer_all([1, 2]).fork(start_immediately=True)
    # Only one of the two fits, so none is added until there is room.
    assert (yield from queue.size()) == 1
    assert (yield from queue.take()) == 0
    assert (yield from offer.join()) == []
    assert (yield from queue.take_all()) == [1, 2]


@testing.effect
def test_a_take_that_waits_rolls_back_the_rest_of_its_transaction():
    queue = yield from fx.TxQueue[int].unbounded()
    taken = yield from fx.TxRef.make(0)

    @fx.fn
    def take_and_count():
        yield from taken.update(lambda n: n + 1)
        return (yield from queue.take())

    fiber = yield from fx.tx(take_and_count()).fork(start_immediately=True)
    assert (yield from taken.get()) == 0
    yield from queue.offer(7)
    assert (yield from fiber.join()) == 7
    assert (yield from taken.get()) == 1


@testing.effect
def test_an_ended_queue_fails_takers_with_done_after_draining():
    queue = yield from fx.TxQueue[int, fx.Done].unbounded()
    taker = yield from queue.take_n(3).fork(start_immediately=True)
    yield from queue.offer_all([1, 2])
    yield from queue.end()
    assert (yield from taker.join()) == [1, 2]
    assert (yield from queue.take().flip()) == fx.Done()


@testing.effect
def test_fail_drops_the_items_at_once():
    queue = yield from fx.TxQueue[int, str].bounded(4)
    yield from queue.offer_all([1, 2])
    assert (yield from queue.fail("boom")) is True
    assert (yield from queue.size()) == 0
    assert (yield from queue.is_done()) is True


_EXCLUDED: list[tuple[str, str, str]] = [
    # (holder, waiter, label): the waiter must not enter while the holder holds.
    ("write", "read", "a writer keeps out readers"),
    ("read", "write", "a reader keeps out writers"),
    ("write", "write", "a writer keeps out writers"),
]


@pytest.mark.parametrize(("held", "wanted", "label"), _EXCLUDED, ids=[e[2] for e in _EXCLUDED])
@testing.effect
def test_a_lock_held_by_another_fiber_keeps_the_waiter_out(held: str, wanted: str, label: str):
    # Effect's "blocks" titles fork the waiter without starting it, so they
    # pass even if acquiring ignores the other fiber's lock; this one starts
    # it first and checks it has not entered.
    lock = yield from fx.TxReentrantLock.make()
    yield from (lock.acquire_write() if held == "write" else lock.acquire_read())
    entered: list[str] = []
    body = fx.sync(lambda: entered.append(wanted))
    guarded = lock.with_write_lock(body) if wanted == "write" else lock.with_read_lock(body)
    waiter = yield from guarded.fork(start_immediately=True)
    yield from fx.yield_now()
    assert entered == [], label
    yield from (lock.release_write() if held == "write" else lock.release_read())
    yield from waiter.join()
    assert entered == [wanted]
    assert (yield from lock.locked()) is False


@testing.effect
def test_closing_an_inner_scope_releases_one_reentrant_read_lock():
    lock = yield from fx.TxReentrantLock.make()

    @fx.fn
    def nested():
        yield from lock.read_lock()
        yield from fx.scoped(lock.read_lock())
        return (yield from lock.read_locks())

    assert (yield from fx.scoped(nested())) == 1
    assert (yield from lock.read_locks()) == 0


@testing.effect
def test_acquire_n_waits_until_that_many_permits_are_free():
    semaphore = yield from fx.TxSemaphore.make(2)
    yield from semaphore.acquire()
    waiter = yield from semaphore.acquire_n(2).fork(start_immediately=True)
    assert waiter.poll_unsafe() is None
    assert (yield from semaphore.available()) == 1
    yield from semaphore.release()
    yield from waiter.join()
    assert (yield from semaphore.available()) == 0


@testing.effect
def test_priority_queue_items_with_equal_keys_leave_in_the_order_they_came():
    # Printed by Effect under Node with an Order on the first element.
    def first(pair: tuple[int, str]) -> int:
        return pair[0]

    pq = yield from fx.TxPriorityQueue.from_iterable(
        [(1, "a"), (2, "b"), (1, "c"), (2, "d"), (3, "e")], key=first
    )
    yield from pq.offer((1, "x"))
    yield from pq.offer_all([(2, "y"), (1, "z"), (2, "w")])
    assert [s for _, s in (yield from pq.to_list())] == list("acxzbdywe")


@testing.effect
def test_priority_queue_take_up_to_a_negative_count_takes_nothing():
    # Effect's Chunk.take / drop with -1, printed under Node.
    pq = yield from fx.TxPriorityQueue.make(1, 2, 3)
    assert (yield from pq.take_up_to(-1)) == []
    assert (yield from pq.to_list()) == [1, 2, 3]


@pytest.mark.parametrize("release", ["release_read", "release_write"])
@testing.effect
def test_releasing_a_lock_this_fiber_does_not_hold_wakes_no_waiter(release: str):
    # Effect returns 0 without writing the lock's state.
    lock = yield from fx.TxReentrantLock.make()
    runs = 0

    @fx.fn
    def waiting():
        nonlocal runs
        runs += 1
        if not (yield from lock.locked()):
            return (yield from fx.tx_retry)

    fiber = yield from fx.tx(waiting()).fork(start_immediately=True)
    assert (yield from getattr(lock, release)()) == 0
    for _ in range(5):
        yield from fx.yield_now()
    assert runs == 1
    yield from fiber.interrupt()
