"""Fibers that outlive the run that started them, as in real handler code.

A threaded server's handler calls ``fx.run_blocking`` (or a ``ManagedRuntime``'s) and
returns; what it started (a lookup other requests wait on, a ``FiberSet`` member, a pool's
refill, an idle timer) must go on running, as on Effect's always-alive scheduler. Each test
is a repro from the dogfood apps (pyfect-39). A test that fails reports the stuck part; it
never hangs the suite, because each wait has a deadline.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import Any, Never

import pytest

import pyfect as fx
from pyfect import layer, scope

DEADLINE = 5.0
"""Seconds before a step counts as stuck."""


def _within[T](seconds: float, f: Callable[[], T]) -> tuple[bool, T | None]:
    """``f()`` on a daemon thread: whether it returned in time, and what it returned."""
    got: list[T] = []
    thread = threading.Thread(target=lambda: got.append(f()), daemon=True)
    thread.start()
    thread.join(seconds)
    return bool(got), (got[0] if got else None)


# --- ManagedRuntime runs on different threads --------------------------------------------


class _Counter(fx.Tag[fx.Ref[int]]): ...


def _runtime() -> fx.ManagedRuntime[_Counter]:
    runtime = fx.ManagedRuntime.make(layer.effect(_Counter, fx.Ref.make(0)))
    runtime.run_blocking(_Counter())  # build the layer
    return runtime


def test_a_quick_runtime_run_returns_while_another_threads_run_is_in_flight():
    runtime = _runtime()
    slow = threading.Thread(target=lambda: runtime.run_blocking(fx.sleep("2 seconds")))
    slow.start()
    time.sleep(0.2)
    started = time.monotonic()
    done, _ = _within(
        DEADLINE, lambda: runtime.run_blocking(_Counter().flat_map(lambda r: r.get()))
    )
    took = time.monotonic() - started
    slow.join()
    runtime.dispose()
    assert done and took < 1.0, f"the quick run took {took:.1f}s"


def test_a_runtime_run_can_wait_for_another_threads_run_of_the_same_runtime():
    runtime = _runtime()
    answered = threading.Event()

    def request() -> None:
        runtime.run_blocking(_Counter().flat_map(lambda r: r.get()))
        answered.set()

    def serve() -> bool:
        threading.Thread(target=request, daemon=True).start()
        return answered.wait(DEADLINE)

    done, got = _within(DEADLINE + 1, lambda: runtime.run_blocking(fx.blocking(serve)))
    assert done and got, "the run waiting on another thread's run deadlocked"
    runtime.dispose()


# --- lookups whose starter's run ended ---------------------------------------------------


def _slow(key: str) -> fx.Effect[str]:
    return fx.sleep("1 second").as_(f"value of {key}")


def _held(key: str) -> fx.Effect[str, Never, fx.Scope]:
    return fx.acquire_release(_slow(key), lambda _v, _e: fx.void)


def _lookups() -> dict[str, Callable[[], fx.Effect[Any, Any]]]:
    held_in = fx.run_blocking(scope.make())
    cache = fx.run_blocking(fx.Cache.make(_slow, capacity=10))
    rc_map = fx.run_blocking(fx.RcMap.make(_held).pipe(scope.provide(held_in)))
    rc_ref = fx.run_blocking(fx.RcRef.make(_held("one")).pipe(scope.provide(held_in)))
    return {
        "Cache": lambda: cache.get("hot"),
        "RcMap": lambda: fx.scoped(rc_map.get("hot")),
        "RcRef": lambda: fx.scoped(rc_ref.get()),
    }


@pytest.mark.parametrize("kind", ["Cache", "RcMap", "RcRef"])
def test_a_timeout_ends_a_wait_on_a_lookup_whose_starters_run_ended(kind: str):
    get = _lookups()[kind]

    def ask(budget: str) -> threading.Thread:
        thread = threading.Thread(
            target=lambda: fx.run_blocking_exit(get().timeout(budget)), daemon=True
        )
        thread.start()
        return thread

    starter = ask("100 millis")
    time.sleep(0.02)
    waiter = ask("300 millis")
    waiter.join(DEADLINE)
    starter.join(DEADLINE)
    assert not waiter.is_alive(), "the waiter with a 300 ms timeout never returned"


def test_one_timed_out_request_on_a_hot_cache_key_leaves_the_next_ones_alone():
    def lookup(key: str) -> fx.Effect[str]:
        return fx.sleep("300 millis").as_(key)

    cache = fx.run_blocking(fx.Cache.make(lookup, capacity=10))
    first = fx.run_blocking_exit(cache.get("hot").timeout("50 millis"))
    assert isinstance(first, fx.Failure)
    outcomes = [fx.run_blocking_exit(cache.get("hot").timeout("2 seconds")) for _ in range(5)]
    assert all(isinstance(ex, fx.Success) for ex in outcomes), outcomes


# --- FiberSet, Pool and RcMap made in a run that ended -----------------------------------


def test_a_fiber_set_runs_tasks_forked_from_handler_runs():
    owner = fx.run_blocking(scope.make())
    fiber_set = fx.run_blocking(fx.FiberSet[None].make().pipe(scope.provide(owner)))
    ran: list[int] = []
    lock = threading.Lock()

    def task(i: int) -> fx.Effect[None]:
        def note() -> None:
            with lock:
                ran.append(i)

        return fx.sleep("20 millis").and_then(fx.sync(note))

    def handle(i: int) -> None:
        fx.run_blocking(fiber_set.run(task(i)))

    handlers = [threading.Thread(target=handle, args=(i,)) for i in range(20)]
    for handler in handlers:
        handler.start()
    for handler in handlers:
        handler.join(DEADLINE)
    emptied = fx.run_blocking_exit(fiber_set.await_empty().timeout("3 seconds"))
    closed, _ = _within(DEADLINE, lambda: fx.run_blocking(owner.close(fx.Success(None))))
    assert sorted(ran) == list(range(20)), f"{len(ran)} of 20 tasks ran"
    assert isinstance(emptied, fx.Success)
    assert closed, "closing the set's scope hung"


def test_a_fixed_pool_made_in_an_ended_run_refills_after_invalidations():
    owner = fx.run_blocking(scope.make())
    made = [0]
    pool = fx.run_blocking(
        fx.Pool.make(fx.sync(lambda: made.__setitem__(0, made[0] + 1) or made[0]), size=2).pipe(
            scope.provide(owner)
        )
    )
    for _ in range(2):
        fx.run_blocking(fx.scoped(pool.get().flat_map(pool.invalidate)))
    both = fx.all(pool.get(), pool.get(), concurrency="unbounded")
    got = fx.run_blocking_exit(fx.scoped(both).timeout("2 seconds"))
    assert isinstance(got, fx.Success), "the pool never refilled"
    closed, _ = _within(DEADLINE, lambda: fx.run_blocking(owner.close(fx.Success(None))))
    assert closed


def test_a_ttl_pool_made_in_an_ended_run_grows_past_its_minimum():
    owner = fx.run_blocking(scope.make())
    pool = fx.run_blocking(
        fx.Pool.make_with_ttl(fx.succeed(1), min=0, max=3, time_to_live="1 minute").pipe(
            scope.provide(owner)
        )
    )
    three = fx.all(pool.get(), pool.get(), pool.get(), concurrency="unbounded")
    got = fx.run_blocking_exit(fx.scoped(three).timeout("2 seconds"))
    assert isinstance(got, fx.Success), "the pool never grew"
    closed, _ = _within(DEADLINE, lambda: fx.run_blocking(owner.close(fx.Success(None))))
    assert closed


def test_an_idle_rc_map_made_in_an_ended_run_releases_and_closes():
    owner = fx.run_blocking(scope.make())
    released = threading.Event()

    def lookup(_: str) -> fx.Effect[int, Never, fx.Scope]:
        return fx.acquire_release(fx.succeed(1), lambda _v, _e: fx.sync(released.set))

    rc_map = fx.run_blocking(
        fx.RcMap.make(lookup, idle_time_to_live="50 millis").pipe(scope.provide(owner))
    )
    fx.run_blocking(fx.scoped(rc_map.get("k")))
    assert released.wait(2), "the idle entry was never released"
    closed, _ = _within(DEADLINE, lambda: fx.run_blocking(owner.close(fx.Success(None))))
    assert closed, "closing the map's scope hung"


# --- interrupts and scope close reach fibers whose run ended -----------------------------


def test_closing_a_scope_interrupts_a_fiber_forked_into_it_from_an_ended_run():
    owner = fx.run_blocking(scope.make())
    finalized = threading.Event()
    forever = fx.never.ensuring(fx.sync(finalized.set))
    fx.run_blocking(forever.fork_in(owner, start_immediately=True))
    closed, _ = _within(DEADLINE, lambda: fx.run_blocking(owner.close(fx.Success(None))))
    assert closed and finalized.is_set()


def test_a_daemon_forked_by_a_run_that_returned_goes_on():
    done = threading.Event()
    fx.run_blocking(fx.sleep("20 millis").and_then(fx.sync(done.set)).fork_daemon())
    assert done.wait(2), "the daemon fiber stopped when its run returned"
