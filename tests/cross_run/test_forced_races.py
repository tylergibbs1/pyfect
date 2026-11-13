"""The cross-run races of ``test_cross_run.py`` forced to happen every time.

- Two runs on two threads inside one ``Ref`` read-modify-write at once (a barrier holds the
  first ``f`` until the second arrives, or for half a second): both read the same value, so one
  update was lost. The ref's lock makes the second wait for the first.
- A fiber parks in one run; a run on another thread wakes it and ends at once. A wake that
  Effect defers to a scheduled task was queued on the waker's run, which never ran it once its
  root fiber ended, so the waiter slept forever. It now goes to the waiter's own run.
"""

from __future__ import annotations

import contextlib
import threading
import time
from collections.abc import Callable
from typing import Any

import pytest

import pyfect as fx
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
