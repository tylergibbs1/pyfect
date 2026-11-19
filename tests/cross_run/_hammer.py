"""Run the same shared-state operations from several runs on several threads at once.

Each thread makes its own runs (``fx.run_blocking``), as an app that calls into pyfect from a
thread pool does, so no two of them share a scheduler. A ``Case`` returns what went wrong: an
update lost, an item taken twice, a waiter never woken (a thread still running once a hang
is certain), or an exception out of a thread.
"""

from __future__ import annotations

import threading
import traceback
from collections.abc import Callable
from dataclasses import dataclass

from _timing import settled

THREADS = 8
"""Threads per case: more than the cores of a CI runner, so threads are preempted mid-step."""


@dataclass(frozen=True)
class Case:
    """``run()`` does the work and returns the problems it found; ``covers`` are the classes
    whose state it shares across runs (``test_cross_run.py`` checks every shared-state class
    is covered)."""

    name: str
    covers: tuple[type, ...]
    run: Callable[[], list[str]]


_barriers: list[threading.Barrier] = []


def barrier(parties: int = THREADS, action: Callable[[], None] | None = None) -> threading.Barrier:
    """A ``threading.Barrier`` that ``on_threads`` breaks when a thread raises, so the
    threads waiting at it for the one that raised fail at once instead of looking hung."""
    made = threading.Barrier(parties, action=action)
    _barriers.append(made)
    return made


def on_threads(work: Callable[[int], None], threads: int = THREADS) -> list[str]:
    """``work(i)`` on ``threads`` threads released together; the problems: what each raised,
    and the threads still running once a hang is certain (``_timing.settled``)."""
    start = barrier(threads)
    errors: list[str] = []

    def go(i: int) -> None:
        try:
            start.wait()
            work(i)
        except threading.BrokenBarrierError:
            pass  # Another thread raised; its error is the one reported.
        except BaseException:
            errors.append(f"thread {i}: {traceback.format_exc(limit=-6)}")
            for each in _barriers:
                each.abort()

    pool = [
        threading.Thread(target=go, args=(i,), name=f"cross-run-{i}", daemon=True)
        for i in range(threads)
    ]
    for thread in pool:
        thread.start()
    settled(lambda: not any(thread.is_alive() for thread in pool))
    hung = [thread.name for thread in pool if thread.is_alive()]
    _barriers.clear()
    return errors + ([f"hung (a lost wake-up?): {', '.join(hung)}"] if hung else [])


def expect(what: str, got: object, want: object) -> list[str]:
    return [] if got == want else [f"{what}: got {got!r}, want {want!r}"]
