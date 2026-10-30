"""Waiting for work done outside the scheduler (a thread, another loop)
without blocking a fiber.

The fiber suspends in ``os_wait`` and the outside work resumes it through
the scheduler, from any thread. While it waits, a timer stays pending on
the fiber's scheduler, so a synchronous run (a test's stall detection
included) knows the wait is outside work, not a deadlock. Every wait on
another thread goes through here (``tests/test_os_wait_guard.py``).
"""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from collections.abc import Callable

from pyfect._core import Effect, _Callback, _Sync
from pyfect.duration import Seconds
from pyfect.scheduler import CurrentScheduler, Scheduler

type Resume[A, E] = Callable[[Effect[A, E]], None]
type Cancel = Callable[[], object]
type Register[A, E] = Callable[[Resume[A, E]], Cancel | None]

_KEEPALIVE = Seconds(0.25)
"""How often a waiting fiber's timer fires; below the test runtime's
one-second stall timeout."""


class _Waiting:
    __slots__ = ("active",)

    def __init__(self) -> None:
        self.active = True


def os_wait[A, E](register: Register[A, E]) -> Effect[A, E]:
    """Suspend until ``register``'s ``resume`` is called, from any thread.
    ``register`` runs on the fiber's thread and may resume at once; the
    cancel function it returns runs if the fiber is interrupted first."""
    return CurrentScheduler().flat_map(
        lambda scheduler: _Callback(_registered(scheduler, register))
    )


def _registered[A, E](
    scheduler: Scheduler, register: Register[A, E]
) -> Callable[[Resume[A, E]], Effect[None] | None]:
    def start(resume: Resume[A, E]) -> Effect[None] | None:
        waiting = _Waiting()

        def beat() -> None:
            if waiting.active:
                scheduler.call_later(_KEEPALIVE, beat)

        def finish(effect: Effect[A, E]) -> None:
            waiting.active = False
            resume(effect)

        cancel = register(finish)
        if not waiting.active:
            return None
        scheduler.call_later(_KEEPALIVE, beat)

        def interrupted() -> None:
            waiting.active = False
            if cancel is not None:
                cancel()

        return _Sync(interrupted)

    return start
