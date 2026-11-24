# pyright: basic
"""Effect's custom test ``Scheduler``: ``makeDispatcher`` holding tasks in a
list for the test to run, and ``shouldYield`` choosing when a fiber pauses."""

from collections.abc import Callable
from typing import Any

import pyfect as fx
from pyfect._fiber import Fiber
from pyfect.scheduler import (
    CurrentScheduler,
    EffectScheduler,
    ExecutionMode,
    MixedScheduler,
    SchedulerDispatcher,
)


class Held:
    """Holds every task in ``tasks``, for the test to run."""

    def __init__(self, tasks: list[Callable[[], None]]) -> None:
        self._tasks = tasks

    def schedule_task(self, task: Callable[[], None], priority: int) -> None:
        self._tasks.append(task)

    def flush(self) -> None:
        pass


class Custom(EffectScheduler):
    """``{ executionMode, makeDispatcher, shouldYield }``."""

    execution_mode: ExecutionMode = "async"

    def __init__(
        self,
        should_yield: Callable[[Fiber[Any, Any]], bool],
        tasks: list[Callable[[], None]] | None = None,
    ) -> None:
        self._should_yield = should_yield
        self._tasks = tasks
        self._mixed = MixedScheduler()

    def should_yield(self, fiber: Fiber[Any, Any]) -> bool:
        return self._should_yield(fiber)

    def make_dispatcher(self) -> SchedulerDispatcher:
        return self._mixed.make_dispatcher() if self._tasks is None else Held(self._tasks)


def on(
    scheduler: EffectScheduler,
) -> Callable[[fx.Effect[Any, Any, Any]], fx.Effect[Any, Any, Any]]:
    return fx.provide_service(CurrentScheduler, scheduler)


def drain(tasks: list[Callable[[], None]]) -> None:
    while tasks:
        tasks.pop(0)()


def never_yields(_: Fiber[Any, Any]) -> bool:
    return False
