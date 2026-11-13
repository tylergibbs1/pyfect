"""A cancelled timer lets go of what it would have run.

The soak (tests/soak) found that every interrupted sleep, and every timeout that did not
fire, left its timer in the run scheduler's heap until the deadline: cancelling only
flagged the timer, so the timer, its task and the closures behind it (nine objects) stayed.
With a 60 second timeout around each operation about 14,000 dead timers were alive at
once; a long timeout on every request of a busy server keeps rate x timeout of them. The
test clock's sleepers did the same. Effect's ``clearTimeout`` frees the callback at once,
and asyncio drops a cancelled handle's callback and sweeps its heap. Every timer heap in
pyfect is now a ``TimerHeap`` (``test_only_the_timer_heap_keeps_a_heap_of_timers``),
which does both.
"""

from __future__ import annotations

import gc
import re
import weakref
from pathlib import Path

from _gc_census import tracked_count

import pyfect as fx
from pyfect import testing
from pyfect._timer_heap import TimerHeap

_SRC = Path(__file__).resolve().parents[1] / "src" / "pyfect"


class Payload:
    """Something a timer holds."""


def _objects_left_by_cancelled_timers(count: int) -> fx.Effect[int]:
    """How many more objects the collector tracks after ``count`` sleeps of an hour
    were interrupted."""

    def sleepers() -> fx.Effect[None]:
        @fx.fn
        def batch():
            fibers = yield from fx.for_each(range(500), lambda _: fx.sleep("1 hour").fork())
            yield from fx.yield_now()  # let them start sleeping
            yield from fx.Fiber.interrupt_all(fibers)

        return fx.for_each(range(count // 500), lambda _: batch()).as_void()

    @fx.fn
    def program():
        yield from sleepers()  # warm up
        gc.collect()
        before = tracked_count()
        yield from sleepers()
        gc.collect()
        return tracked_count() - before

    return program()


def test_interrupted_sleeps_leave_nothing_behind_until_their_deadline() -> None:
    assert fx.run_blocking(_objects_left_by_cancelled_timers(5_000)) < 1_000


def test_interrupted_sleeps_on_the_test_clock_leave_nothing_behind() -> None:
    assert testing.run_test(_objects_left_by_cancelled_timers(5_000)) < 1_000


def test_the_heap_pops_due_entries_in_order_and_skips_cancelled_ones() -> None:
    heap: TimerHeap[str] = TimerHeap()
    late = heap.push(3.0, "late")
    heap.push(1.0, "early")
    gone = heap.push(2.0, "cancelled")
    gone.cancel()
    gone.cancel()  # twice is fine
    assert heap.next_due() == 1.0
    assert heap.pop_due(2.5) == ["early"]
    assert heap.pop_due(10.0) == ["late"]
    late.cancel()  # after it fired: nothing to do
    assert heap.next_due() is None
    assert not heap


def test_a_cancelled_entry_lets_go_of_its_value_at_once() -> None:
    heap: TimerHeap[Payload] = TimerHeap()
    payload = Payload()
    ref = weakref.ref(payload)
    entry = heap.push(3600.0, payload)
    del payload
    entry.cancel()
    gc.collect()
    assert ref() is None


def test_cancelled_entries_do_not_pile_up() -> None:
    heap: TimerHeap[int] = TimerHeap()
    keep = heap.push(1.0, 0)
    for n in range(10_000):
        heap.push(3600.0 + n, n).cancel()
    assert len(heap) == 1
    assert heap.size_with_cancelled() < 200
    assert heap.pop_due(1.0) == [0]
    keep.cancel()


def test_only_the_timer_heap_keeps_a_heap_of_timers() -> None:
    """A heap of cancellable entries elsewhere would keep cancelled ones alive."""
    allowed = {"_timer_heap.py", "graph/_shortest.py", "graph/_enumerate.py"}
    users = {
        path.relative_to(_SRC).as_posix()
        for path in _SRC.rglob("*.py")
        if re.search(r"^\s*(import heapq|from heapq import)", path.read_text(), re.M)
    }
    assert users <= allowed, f"use pyfect._timer_heap.TimerHeap in {sorted(users - allowed)}"
