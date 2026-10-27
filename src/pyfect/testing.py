"""Deterministic tests.

``run_test`` runs an effect on a synchronous scheduler with a ``TestClock``.
Time only moves when the test says so, with ``adjust``; each step lets
every fiber settle before time moves again, so timing tests are exact and
take no real time::

    def test_timeout():
        @fx.gen
        def program():
            fiber = yield from fx.sleep(10).timeout(5).exit().fork()
            yield from testing.adjust(5)
            return (yield from fiber.join())

        assert isinstance(testing.run_test(program), fx.Failure)

If every fiber ends up waiting with nothing to wake them (for example, a
sleep nobody ``adjust``s past), ``run_test`` raises ``StalledError``
instead of hanging. If a fiber keeps running without ever suspending,
``adjust`` stops waiting for it after ``warning_delay`` (real time) and
warns with ``BusyFiberWarning``.
"""
# pyright: reportPrivateUsage=false

from __future__ import annotations

import heapq
import itertools
import math
import warnings
from collections.abc import Callable, Generator
from typing import Any, Never

from pyfect._core import Effect, _Callback, _Gen, _Succeed, _Sync, _WithFiber, _YieldNow
from pyfect._fiber import Fiber
from pyfect._wake_tracking import TrackingScheduler, WakeTracker
from pyfect.clock import Clock
from pyfect.context import Context
from pyfect.duration import Duration, Seconds, to_seconds
from pyfect.exit import Exit
from pyfect.run import _unwrap
from pyfect.scheduler import Cancel, StalledError, SyncScheduler, Task

__all__ = [
    "BusyFiberWarning",
    "StalledError",
    "TestClock",
    "adjust",
    "run_test",
    "run_test_exit",
    "set_time",
]


class BusyFiberWarning(RuntimeWarning):
    """``TestClock.adjust`` stopped waiting for a fiber that kept running
    without suspending."""


_WAKE_WARNING = (
    "A fiber woken by the test clock is still running without suspending, so the "
    "test clock stopped waiting for it. Sleeps it starts later may be scheduled "
    "relative to a later time."
)
_SETTLE_WARNING = (
    "A fiber is still running without suspending, so TestClock.adjust stopped "
    "waiting for every fiber to settle before moving time. Sleeps it starts later "
    "may be scheduled relative to a later time."
)


class _Sleeper:
    __slots__ = ("alive", "wake")

    def __init__(self, wake: Callable[[], None]) -> None:
        self.wake = wake
        self.alive = True


class TestClock:
    """A clock that only moves when told to.

    Time is kept in whole nanoseconds, so deadlines add up exactly
    (``0.05 + 0.001`` is reached by moving ``0.051``).

    ``warning_delay`` is how long (in real time) ``adjust`` waits for a
    woken fiber to suspend before warning with ``BusyFiberWarning`` and
    moving on."""

    __test__ = False  # not a pytest test class

    def __init__(self, start: float = 0.0, *, warning_delay: Duration = 1.0) -> None:
        self._now_ns = _nanos(Seconds(start))
        self._sleepers: list[tuple[float, int, _Sleeper]] = []
        self._seq = itertools.count()
        self._warning_delay = to_seconds(warning_delay)

    def unsafe_now(self) -> float:
        return self._now_ns / _NANOS

    def unsafe_monotonic(self) -> float:
        return self._now_ns / _NANOS

    def sleep(self, seconds: Seconds) -> Effect[None]:
        def register(resume: Callable[[Effect[None]], None]) -> Effect[None] | None:
            if seconds <= 0:
                resume(_Succeed(None))
                return None
            sleeper = _Sleeper(lambda: resume(_Succeed(None)))
            heapq.heappush(
                self._sleepers, (self._now_ns + _nanos(seconds), next(self._seq), sleeper)
            )

            def cancel() -> None:
                sleeper.alive = False

            return _Sync(cancel)

        return _Callback(register)

    def adjust(self, duration: Duration) -> Effect[None]:
        """Move time forward, waking sleepers in order. After each wake-up,
        wait for the woken fiber and the work it starts to suspend."""
        seconds = to_seconds(duration)

        def body(fiber: Fiber[Any, Any]) -> Effect[None]:
            scheduler = fiber._scheduler
            if not isinstance(scheduler, TrackingScheduler):
                raise TypeError("TestClock.adjust needs pyfect.testing.run_test")
            return _Gen(lambda: self._run(scheduler, seconds))

        return _WithFiber(body)

    def _run(self, scheduler: TrackingScheduler, seconds: Seconds) -> Generator[Effect[None]]:
        yield from self._wait_or_warn(scheduler, scheduler.inner.when_idle, _SETTLE_WARNING)
        target = self._now_ns + _nanos(seconds)
        while self._sleepers and self._sleepers[0][0] <= target:
            when, _, sleeper = heapq.heappop(self._sleepers)
            if not sleeper.alive:
                continue
            self._now_ns = when
            tracker = WakeTracker()
            scheduler.track(tracker, sleeper.wake)
            if tracker.pending:
                yield from self._wait_or_warn(scheduler, tracker.when_idle, _WAKE_WARNING)
            yield from _YieldNow()
        self._now_ns = target

    def _wait_or_warn(
        self, scheduler: TrackingScheduler, arm: Callable[[Task], Cancel], message: str
    ) -> Effect[None]:
        """Wait for the callback given to ``arm``; after ``warning_delay`` of
        real time, warn with ``message`` and stop waiting."""

        def register(resume: Callable[[Effect[None]], None]) -> Effect[None]:
            def finish() -> None:
                disarm()
                cancel_timer()
                resume(_Succeed(None))

            def give_up() -> None:
                disarm()
                warnings.warn(message, BusyFiberWarning, stacklevel=1)
                resume(_Succeed(None))

            cancel_timer = scheduler.call_later(self._warning_delay, give_up)
            disarm = arm(finish)

            def cancel() -> None:
                disarm()
                cancel_timer()

            return _Sync(cancel)

        return _Callback(register)


_NANOS = 1_000_000_000


def _nanos(seconds: Seconds) -> float:
    """Whole nanoseconds; infinities stay infinite (a sleep that never wakes)."""
    return seconds if math.isinf(seconds) else round(seconds * _NANOS)


def _test_clock() -> Effect[TestClock]:
    def check(clock: object) -> Effect[TestClock]:
        if not isinstance(clock, TestClock):
            raise TypeError("no TestClock in context; run the effect with pyfect.testing.run_test")
        return _Succeed(clock)

    return Clock().flat_map(check)


def adjust(duration: Duration) -> Effect[None]:
    """Move the test clock forward by ``duration``."""
    return _test_clock().flat_map(lambda c: c.adjust(duration))


def set_time(at: float) -> Effect[None]:
    """Move the test clock forward to ``at``. Time never goes backwards."""
    return _test_clock().flat_map(lambda c: c.adjust(max(at - c.unsafe_now(), 0.0)))


def run_test_exit[A, E](
    eff: Effect[A, E, Never], *, stall_timeout: float = 1.0, warning_delay: Duration = 1.0
) -> Exit[A, E]:
    scheduler = SyncScheduler()
    clock = TestClock(warning_delay=warning_delay)
    fiber: Fiber[A, E] = Fiber(
        TrackingScheduler(scheduler), Context.empty().add(Clock, clock), None
    )
    fiber._start(eff)
    try:
        scheduler.run_until(lambda: fiber._exit is not None, stall_timeout=stall_timeout)
    except StalledError as err:
        err.add_note("Is a fiber sleeping on the TestClock? Move time with testing.adjust(...).")
        raise
    ex = fiber._exit
    assert ex is not None
    return ex


def run_test[A](
    eff: Effect[A, Never, Never], *, stall_timeout: float = 1.0, warning_delay: Duration = 1.0
) -> A:
    return _unwrap(run_test_exit(eff, stall_timeout=stall_timeout, warning_delay=warning_delay))
