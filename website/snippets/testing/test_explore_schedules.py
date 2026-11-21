from collections.abc import Callable
from typing import Any

import pytest

import pyfect as fx
from pyfect.testing import explore


def read_then_write(balance: fx.Ref[int]) -> fx.Effect[None]:
    """A check-then-act across a yield."""

    @fx.gen
    def body():
        seen = yield from balance.get()
        yield from fx.yield_now()
        yield from balance.set(seen + 50)

    return body


def atomic(balance: fx.Ref[int]) -> fx.Effect[None]:
    return fx.yield_now().and_then(balance.update(lambda seen: seen + 50))


def deposit_twice(deposit: Callable[[fx.Ref[int]], fx.Effect[None]]) -> fx.Effect[int]:
    """Two deposits of 50 into one balance; the second starts a little later."""

    @fx.gen
    def body():
        balance = yield from fx.Ref.make(0)
        later = fx.yield_now().and_then(fx.yield_now()).and_then(deposit(balance))
        yield from fx.all([deposit(balance), later], concurrency="unbounded")
        return (yield from balance.get())

    return body


def is_100(ex: fx.Exit[int, Any]) -> str | None:
    return None if ex == fx.Success(100) else f"balance is {ex}"


def test_explore_finds_the_lost_deposit():
    # The first-come order happens to give 100; another order loses a deposit.
    with pytest.raises(explore.ScheduleFailure) as found:
        explore.schedules(deposit_twice(read_then_write), is_100)
    assert found.value.problems == ("balance is Success(value=50)",)
    # The failure prints its schedule; replay= runs exactly that one again.
    with pytest.raises(explore.ScheduleFailure):
        explore.schedules(deposit_twice(read_then_write), is_100, replay=found.value.schedule)


def test_an_atomic_update_passes_every_schedule():
    report = explore.schedules(deposit_twice(atomic), is_100)
    assert report.exhaustive


def leaky_lock() -> explore.Case[None, Any]:
    """A fresh lock and run each time; the check reads the lock afterwards."""
    lock = fx.Semaphore(1)
    effect = lock.take().and_then(fx.yield_now()).and_then(lock.release()).as_void()

    def check(_: fx.Exit[None, Any]) -> str | None:
        free = fx.run_sync(lock.available)
        return None if free == 1 else "the lock was never released"

    return effect, check


def test_an_interrupt_at_the_wrong_step_leaks_the_lock():
    explore.schedules(leaky_lock)  # passes: nothing interrupts it
    with pytest.raises(explore.ScheduleFailure) as found:
        explore.schedules(leaky_lock, interrupts=True)
    assert found.value.interrupted_at is not None  # use lock.with_permits(...) instead
