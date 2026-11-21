"""The cross-run races of ``test_cross_run.py`` forced to happen every time.

- Two runs on two threads inside one ``Ref`` read-modify-write at once (a barrier holds the
  first ``f`` until the second arrives, or for half a second): both read the same value, so one
  update was lost. The ref's lock makes the second wait for the first.
- A fiber parks in one run; a run on another thread wakes it and ends at once. A wake that
  Effect defers to a scheduled task was queued on the waker's run, which never ran it once its
  root fiber ended, so the waiter slept forever. It now goes to the waiter's own run.
- A pool borrower is woken, but its run is busy, and a second item comes back meanwhile: no
  wake for it, as nobody is asleep. A newcomer queues behind the woken one and sleeps. The
  woken one takes an item and left the line without waking the newcomer, who slept forever
  next to a free item (a TTL pool made in an ended run hung growing on free-threaded CI).
"""

from __future__ import annotations

import contextlib
import threading
import time
from collections.abc import Callable
from typing import Any

import pytest
from _timing import wait_until

import pyfect as fx
from pyfect import scope
from pyfect.option import Some

type Rmw = Callable[[fx.Ref[int], Callable[[int], int]], fx.Effect[Any]]

READ_MODIFY_WRITES: dict[str, Rmw] = {
    "update": lambda ref, f: ref.update(f),
    "update_and_get": lambda ref, f: ref.update_and_get(f),
    "get_and_update": lambda ref, f: ref.get_and_update(f),
    "modify": lambda ref, f: ref.modify(lambda v: (None, f(v))),
    "update_some": lambda ref, f: ref.update_some(lambda v: Some(f(v))),
    "update_some_and_get": lambda ref, f: ref.update_some_and_get(lambda v: Some(f(v))),
    "get_and_update_some": lambda ref, f: ref.get_and_update_some(lambda v: Some(f(v))),
    "modify_some": lambda ref, f: ref.modify_some(lambda v: (None, Some(f(v)))),
}


@pytest.mark.parametrize("op", READ_MODIFY_WRITES.values(), ids=READ_MODIFY_WRITES.keys())
def test_two_runs_inside_one_ref_update_lose_nothing(op: Rmw):
    ref = fx.Ref(0)
    both_inside = threading.Barrier(2, timeout=0.5)

    def add_one(value: int) -> int:
        with contextlib.suppress(threading.BrokenBarrierError):
            both_inside.wait()
        return value + 1

    threads = [threading.Thread(target=fx.run_blocking, args=(op(ref, add_one),)) for _ in "ab"]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert ref.get_unsafe() == 2


def _wait_and_wake[T](
    make: Callable[[], T],
    wait: Callable[[T], fx.Effect[Any]],
    wake: Callable[[T], fx.Effect[Any]],
) -> None:
    shared = make()
    about_to_wait = threading.Event()
    woke = threading.Event()

    def waiter() -> None:
        fx.run_blocking(fx.sync(about_to_wait.set).and_then(wait(shared)))
        woke.set()

    thread = threading.Thread(target=waiter, daemon=True)
    thread.start()
    assert about_to_wait.wait(5)
    time.sleep(0.05)  # it parks within a step of setting the event
    fx.run_blocking(wake(shared))  # this run ends right after the wake
    assert woke.wait(5), "the waiter was never woken"
    thread.join()


def _tx_waiter(ref: fx.TxRef[int]) -> fx.Effect[int]:
    return fx.tx(ref.get().flat_map(lambda v: fx.tx_retry if v == 0 else fx.succeed(v)))


def _full_queue() -> fx.Queue[int]:
    queue = fx.Queue[int](1)
    assert queue.offer_unsafe(0)
    return queue


WAKES: dict[str, Callable[[], None]] = {
    "Queue.take, woken by offer": lambda: _wait_and_wake(
        fx.Queue[int], lambda q: q.take(), lambda q: q.offer(1)
    ),
    "Queue.offer to a full queue, woken by take": lambda: _wait_and_wake(
        _full_queue, lambda q: q.offer(1), lambda q: q.take()
    ),
    "Semaphore.take, woken by release": lambda: _wait_and_wake(
        lambda: fx.Semaphore(0), lambda s: s.take(), lambda s: s.release()
    ),
    "Latch.wait, woken by open": lambda: _wait_and_wake(
        fx.Latch, lambda latch: latch.wait(), lambda latch: latch.open()
    ),
    "Latch.wait, woken by release": lambda: _wait_and_wake(
        fx.Latch, lambda latch: latch.wait(), lambda latch: latch.release()
    ),
    "tx_retry, woken by a commit": lambda: _wait_and_wake(
        lambda: fx.TxRef[int](0), _tx_waiter, lambda ref: ref.set(1)
    ),
    "Deferred.wait, woken by succeed": lambda: _wait_and_wake(
        fx.Deferred[int], lambda d: d.wait(), lambda d: d.succeed(1)
    ),
}


@pytest.mark.parametrize("case", WAKES.values(), ids=WAKES.keys())
def test_a_wake_from_a_run_that_ends_at_once_reaches_the_waiter(case: Callable[[], None]):
    case()


def test_a_borrower_that_takes_an_item_wakes_the_one_asleep_behind_it():
    owner = fx.run_blocking(scope.make())
    pool = fx.run_blocking(fx.Pool.make(fx.succeed(1), size=2).pipe(scope.provide(owner)))

    def pending() -> int:
        return fx.run_blocking(pool.stats()).pending

    def in_thread(eff: fx.Effect[Any, Any]) -> threading.Thread:
        thread = threading.Thread(target=fx.run_blocking_exit, args=(eff,), daemon=True)
        thread.start()
        return thread

    both_out, give_back = threading.Event(), fx.Deferred[None]()
    # The yield runs the wakes the releases left queued before the holder's run ends, so
    # none of them is still to come once the newcomer parks.
    holder = in_thread(
        fx.scoped(
            fx.all(pool.get(), pool.get())
            .and_then(fx.sync(both_out.set))
            .and_then(give_back.wait())
        ).and_then(fx.yield_now())
    )
    assert both_out.wait(5), "the holder never got both items"

    # The first borrower parks, then its run's thread blocks: once woken, it cannot retry.
    run_busy, run_free = threading.Event(), threading.Event()
    first_got, first_keeps = threading.Event(), fx.Deferred[None]()
    first = fx.scoped(pool.get().and_then(fx.sync(first_got.set)).and_then(first_keeps.wait()))
    parked = fx.yield_now().and_then(pool.stats()).repeat(until=lambda s: s.pending == 1)
    busy = parked.and_then(fx.sync(run_busy.set)).and_then(fx.sync(lambda: run_free.wait(5)))
    first_run = in_thread(first.fork().flat_map(lambda f: busy.and_then(f.join())))
    assert run_busy.wait(5), "the first borrower never parked"

    fx.run_blocking(give_back.succeed(None))  # both items come back; the first is woken
    holder.join(5)
    newcomer_got = threading.Event()
    newcomer = in_thread(fx.scoped(pool.get().and_then(fx.sync(newcomer_got.set))))
    wait_until(lambda: pending() == 1, what="the newcomer to park")

    run_free.set()  # the first borrower retries and takes one item
    try:
        assert first_got.wait(5), "the woken borrower never took an item"
        assert newcomer_got.wait(5), "the newcomer slept next to a free item"
    finally:
        fx.run_blocking(first_keeps.succeed(None))
        first_run.join(5)
        fx.run_blocking(owner.close(fx.Success(None)))
        newcomer.join(5)
