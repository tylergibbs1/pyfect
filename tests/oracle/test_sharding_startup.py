"""Port of the "Sharding startup" case of Effect's
``test/cluster/Sharding.test.ts``. The docstring is the Effect test title.

Effect provides a ``Scheduler`` whose ``shouldYield`` pauses only the fiber
building ``Sharding.layer``, every four operations, so each time it pauses
the fibers it forked run to their first suspension. pyfect's step budget
(``MaxOpsBeforeYield``) is read from the context, so the forked fibers inherit
it; ``_StartupLast`` puts the build fiber's resumes behind every other task of
the build, which gives the same order. A budget sweep alone does not: the
forked fibers then advance one slice per slice of the build fiber and never
reach the singletons before they exist."""

from __future__ import annotations

from collections import deque
from collections.abc import Callable
from dataclasses import replace
from typing import Any

import pyfect as fx
from pyfect import exit as Exit
from pyfect import testing
from pyfect._wake_tracking import WakeTracker
from pyfect.cluster import (
    message_storage,
    runner_health,
    runner_storage,
    runners,
    sharding,
    sharding_config,
)
from pyfect.cluster.runner_address import RunnerAddress
from pyfect.duration import Seconds
from pyfect.logger import Options
from pyfect.scheduler import Cancel, Scheduler, Task
from pyfect.scope import CloseableScope

_layer = (
    sharding.layer.pipe(fx.layer.provide(runner_storage.layer_memory))
    .pipe(fx.layer.provide(runner_health.layer_noop))
    .pipe(fx.layer.provide(runners.layer_noop))
    .pipe(fx.layer.provide(message_storage.layer_memory))
    .pipe(
        fx.layer.provide(
            sharding_config.layer(
                replace(
                    sharding_config.DEFAULTS,
                    runner_address=RunnerAddress(host="localhost", port=1234),
                    shards_per_group=1,
                )
            )
        )
    )
)


class _StartupLast:
    """Runs tasks on ``inner``, but holds the tasks ``startup`` schedules
    (its resumes after a budget pause) until no other task scheduled here
    is pending."""

    def __init__(self, inner: Scheduler, startup: fx.Fiber[Any, Any]) -> None:
        self._inner = inner
        self._startup = startup
        self._pending = 0
        self._held: deque[Task] = deque()
        self.held_total = 0

    def schedule(self, task: Task, priority: int = 0) -> None:
        if fx.Fiber.get_current() is self._startup and self._pending > 0:
            self.held_total += 1
            self._held.append(task)
            return
        self._pending += 1

        def run() -> None:
            try:
                task()
            finally:
                self._pending -= 1
                while self._pending == 0 and self._held:
                    self._inner.schedule(self._held.popleft())

        self._inner.schedule(run)

    def call_later(self, delay: Seconds, task: Task, *, daemon: bool = False) -> Cancel:
        return self._inner.call_later(delay, task, daemon=daemon)

    def track(self, tracker: WakeTracker, f: Callable[[], None]) -> None:
        self._inner.track(tracker, f)

    def outside_work(self) -> WakeTracker:
        return self._inner.outside_work()


def _cause_logger(causes: list[str]) -> fx.Logger[None]:
    def log(options: Options) -> None:
        if options.cause.reasons:
            causes.append(options.cause.pretty())

    return fx.Logger.make(log)


@testing.effect
def test_initializes_singleton_synchronization_before_startup_fibers_run():
    """initializes singleton synchronization before startup fibers run"""
    causes: list[str] = []
    scope = CloseableScope()
    startup = yield from fx.current_fiber()
    scheduler = _StartupLast((yield from fx.CurrentScheduler()), startup)
    # Let startup fibers run to their first suspension whenever construction
    # yields.
    yield from (
        _layer.build_with_scope(scope)
        .pipe(fx.provide(fx.logger.layer([_cause_logger(causes)])))
        .pipe(fx.provide_service(fx.MaxOpsBeforeYield, 4))
        .pipe(fx.provide_service(fx.CurrentScheduler, scheduler))
    )
    assert scheduler.held_total > 0
    closing = yield from scope.close(Exit.succeed(None)).fork()
    # Drain the retry/handoff delay too, so a regression fails without
    # leaking a scope.
    yield from testing.adjust(10)
    yield from closing.join()
    assert causes == []
