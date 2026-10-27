"""What ``FiberSet``, ``FiberMap`` and ``FiberHandle`` share: the id they
interrupt with, which exits their ``join`` reports, and the runtime their
``runtime()`` runners fork root fibers on."""
# pyright: reportPrivateUsage=false

from __future__ import annotations

import asyncio
from collections.abc import Hashable, Iterator
from typing import Any, TypeGuard

from pyfect._core import Effect
from pyfect._fiber import Fiber
from pyfect._root import new_root, start_root
from pyfect.context import Context
from pyfect.exit import Exit, Failure, Success
from pyfect.scheduler import Scheduler

INTERNAL_FIBER_ID = -1
"""The interruptor of fibers a collection interrupts itself (replaced,
removed or cleared fibers), so ``join`` can tell them from interrupts sent
from outside."""


def reports_failure[E](ex: Exit[Any, E], propagate_interruption: bool) -> TypeGuard[Failure[E]]:
    """Whether a member's exit fails the collection's ``join``. Interrupts
    count only with ``propagate_interruption``, and never the collection's
    own."""
    if not isinstance(ex, Failure):
        return False
    if propagate_interruption:
        return INTERNAL_FIBER_ID not in ex.cause.interruptors
    return not ex.cause.has_interrupts_only


def live_items[K: Hashable, V: Hashable](entries: dict[K, V]) -> Iterator[tuple[K, V]]:
    """The items of ``entries`` in order, as Effect's iteration over a live
    ``Set`` or ``Map``: items added while iterating are visited too, and a
    key whose value was replaced after its visit is not visited again.
    ``clear`` interrupts what this yields, and interrupts run finalizers
    that change members. (Items removed meanwhile are done fibers, which
    interrupting leaves alone.)"""
    seen: set[tuple[K, V]] = set()
    while fresh := [item for item in entries.items() if item not in seen]:
        seen.update(fresh)
        yield from fresh


class CapturedRuntime:
    """The run and services of the fiber that called ``runtime()``. Forks
    root fibers there, as Effect's ``runForkWith``."""

    __slots__ = ("context", "run_scheduler")

    def __init__(self, fiber: Fiber[Any, Any]) -> None:
        self.run_scheduler = fiber._run_scheduler
        self.context = fiber._context

    def fork[A, E](
        self,
        eff: Effect[A, E, Any],
        *,
        uninterruptible: bool,
        scheduler: Scheduler | None,
    ) -> Fiber[A, E]:
        """A root fiber running ``eff``. Called from a fiber of the same
        run it runs at once, up to its first wait, before the call returns
        (Effect evaluates it synchronously); from anywhere else it is
        scheduled."""
        fiber: Fiber[A, E] = new_root(
            self.run_scheduler, self.context, scheduler=scheduler, uninterruptible=uninterruptible
        )
        start_root(fiber, eff)
        return fiber

    def interrupted(self) -> Fiber[Any, Any]:
        """A fiber that never runs anything: what a closed collection hands
        back (Effect's ``constInterruptedFiber``)."""
        return interrupted_fiber(self.run_scheduler, self.context)


def interrupted_fiber(run_scheduler: Scheduler, context: Context) -> Fiber[Any, Any]:
    fiber: Fiber[Any, Any] = Fiber(run_scheduler, context, None)
    fiber.unsafe_interrupt_as(fiber.id)
    return fiber


def future_of[A](fiber: Fiber[A, Any]) -> asyncio.Future[A]:
    """A future on the running loop that resolves with the fiber's value, or
    raises its squashed cause (Effect's ``runtimePromise``)."""
    future: asyncio.Future[A] = asyncio.get_running_loop().create_future()

    def settle(ex: Exit[A, Any]) -> None:
        if future.done():
            return
        if isinstance(ex, Success):
            future.set_result(ex.value)
        else:
            future.set_exception(ex.cause.squash())

    fiber.unsafe_add_observer(settle)
    return future
