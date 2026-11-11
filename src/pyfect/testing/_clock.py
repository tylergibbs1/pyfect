"""``TestClock``: time that moves only when a test moves it."""
# pyright: reportPrivateUsage=false

from __future__ import annotations

import contextvars
import heapq
import itertools
import math
import sys
import warnings
from collections.abc import Callable, Generator
from typing import Any, Never

from pyfect._core import Effect, _Callback, _Gen, _Succeed, _Sync, _WithFiber, _YieldNow
from pyfect._effect_args import require_effect
from pyfect._fiber import Fiber
from pyfect._timestamps import millis_to_nanos
from pyfect._wake_tracking import WakeTracker
from pyfect.clock import Clock, ClockService, LiveClock
from pyfect.duration import Duration, from_input_unsafe, nanos_or_infinite
from pyfect.duration import Input as DurationInput
from pyfect.effect import provide_service
from pyfect.layer import Layer
from pyfect.layer import effect as layer_effect
from pyfect.scheduler import Cancel, Scheduler, Task
from pyfect.scope import Scope, add_finalizer
from pyfect.semaphore import Semaphore


class BusyFiberWarning(RuntimeWarning):
    """``TestClock.adjust`` stopped waiting for a fiber that kept running
    without suspending."""


class ClockNotAdvancedWarning(RuntimeWarning):
    """A fiber has been sleeping on the ``TestClock`` for ``warning_delay``
    (real time) and the test has not moved time yet."""


_NOT_ADVANCED_WARNING = (
    "A test is using time, but is not advancing the test clock, which may result "
    "in the test hanging. Use testing.adjust to manually advance the time."
)
_WAKE_WARNING = (
    "A fiber woken by the test clock is still running without suspending, so the "
    "test clock stopped waiting for it. Sleeps it starts later may be scheduled "
    "relative to a later time."
)
_OUTSIDE_WARNING = (
    "Work on another thread (fx.blocking, a SQLite or HTTP call) is still running, "
    "so the test clock stopped waiting for it. Sleeps started after it may be "
    "scheduled relative to a later time."
)
_NANOS = 1_000_000_000
_NANOS_PER_MILLI = 1_000_000


def _timestamp_nanos(millis: float) -> int | float:
    """An epoch timestamp in milliseconds as the clock's nanoseconds: NaN is
    0, an infinity stays one, a count past float range saturates."""
    if math.isnan(millis):
        return 0
    if math.isinf(millis):
        return millis
    return _add_nanos(millis_to_nanos(millis), 0)


_MAX_NANOS = math.floor(sys.float_info.max)


def _in_float_range(nanos: int | float) -> int | float:
    """A count past float range as the infinity it saturates to, as JavaScript's
    millisecond timestamps do."""
    if isinstance(nanos, int) and abs(nanos) > _MAX_NANOS:
        return math.inf if nanos > 0 else -math.inf
    return nanos


def _add_nanos(a: int | float, b: int | float) -> int | float:
    return _in_float_range(_in_float_range(a) + _in_float_range(b))


class _Sleeper:
    __slots__ = ("alive", "wake")

    def __init__(self, wake: Callable[[], None]) -> None:
        self.wake = wake
        self.alive = True


class _NotAdvanced:
    """The "not advancing the test clock" warning: armed by the first
    sleep, disarmed for good once time moves or the test ends."""

    __slots__ = ("_cancel", "_done")

    def __init__(self) -> None:
        self._done = False
        self._cancel: Cancel | None = None

    def arm(self, scheduler: Scheduler, delay: Duration) -> None:
        if self._done or self._cancel is not None:
            return

        # Warn in the context of the fiber whose sleep armed it, as Effect's warning fiber
        # inherits it: without the GIL warning filters are per context.
        context = contextvars.copy_context()

        def warn() -> None:
            self._done = True
            context.run(warnings.warn, _NOT_ADVANCED_WARNING, ClockNotAdvancedWarning, stacklevel=1)

        self._cancel = scheduler.call_later(delay, warn, daemon=True)

    def disarm(self) -> None:
        self._done = True
        if self._cancel is not None:
            self._cancel()


class TestClock:
    """A clock that only moves when told to, with ``adjust`` or
    ``set_time``. Each move wakes due sleepers in order and waits for the
    work each wake-up starts.

    Wall time (``current_time_millis_unsafe``) and monotonic time
    (``monotonic_unsafe``) are kept apart: ``set_time`` may move wall time
    backwards, but monotonic time only ever moves forward. Time is kept in
    whole nanoseconds, so deadlines add up exactly. ``start`` is the
    starting time in milliseconds since the epoch, as ``set_time`` takes.

    ``warning_delay`` is how long (in real time) to wait before warning
    that a test sleeps without moving time (``ClockNotAdvancedWarning``),
    or that a woken fiber keeps running without suspending
    (``BusyFiberWarning``). ``live`` is the clock ``with_live`` uses."""

    __test__ = False  # not a pytest test class

    def __init__(
        self,
        start: float = 0,
        *,
        warning_delay: DurationInput = "1 second",
        live: ClockService | None = None,
    ) -> None:
        if not math.isfinite(start):
            raise ValueError(f"TestClock needs a finite start time, got {start}")
        start_ns = millis_to_nanos(start)
        self._timestamp_ns: float = start_ns
        self._wall_ns = start_ns
        self._monotonic_ns = start_ns
        self._sleepers: list[tuple[float, int, _Sleeper]] = []
        self._seq = itertools.count()
        self._warning_delay = from_input_unsafe(warning_delay)
        self._live = live or LiveClock()
        self._not_advanced = _NotAdvanced()
        self._moving = Semaphore(1)

    @staticmethod
    def layer(*, warning_delay: DurationInput = "1 second") -> Layer[Never]:
        """Provide a fresh ``TestClock`` as the ``Clock``. Its ``with_live``
        uses the clock that was current when the layer was built."""

        def make(live: ClockService) -> Effect[TestClock, Never, Scope]:
            base = live._live if isinstance(live, TestClock) else live
            clock = TestClock(warning_delay=warning_delay, live=base)
            return add_finalizer(lambda _: _Sync(clock.stop_warning)).as_(clock)

        return layer_effect(Clock, Clock().flat_map(make))

    # --- the Clock service ------------------------------------------------------------

    def current_time_millis_unsafe(self) -> float:
        # As Effect's ``currentTimeMillis``: infinite once time is moved to
        # infinity (the nanosecond clocks stay at the last finite time).
        if math.isinf(self._timestamp_ns):
            return self._timestamp_ns
        return self._wall_ns / _NANOS_PER_MILLI

    def monotonic_unsafe(self) -> float:
        return self._monotonic_ns / _NANOS

    def now_nanos_unsafe(self) -> int:
        return self._wall_ns

    def monotonic_nanos_unsafe(self) -> int:
        return self._monotonic_ns

    def sleep(self, duration: Duration) -> Effect[None]:
        def body(fiber: Fiber[Any, Any]) -> Effect[None]:
            def register(resume: Callable[[Effect[None]], None]) -> Effect[None] | None:
                end = _add_nanos(self._timestamp_ns, nanos_or_infinite(duration))
                if end <= self._timestamp_ns:
                    resume(_Succeed(None))
                    return None
                self._not_advanced.arm(fiber._scheduler, self._warning_delay)
                sleeper = _Sleeper(lambda: resume(_Succeed(None)))
                heapq.heappush(self._sleepers, (end, next(self._seq), sleeper))

                def cancel() -> None:
                    sleeper.alive = False

                return _Sync(cancel)

            return _Callback(register)

        return _WithFiber(body)

    # --- moving time ------------------------------------------------------------------

    def adjust(self, duration: DurationInput) -> Effect[None]:
        """Move time forward by ``duration``, waking sleepers in order.
        Before moving, and after each wake-up, wait for the woken fiber and
        the work it starts to suspend, work on other threads included
        (``fx.blocking``, SQLite and HTTP calls)."""
        delta = nanos_or_infinite(from_input_unsafe(duration))
        return self._move(lambda now: _add_nanos(now, delta))

    def set_time(self, timestamp: float) -> Effect[None]:
        """Set wall time to ``timestamp`` (milliseconds since the epoch, as
        Effect's ``setTime``), waking every sleeper due by then. Moving
        backwards leaves monotonic time alone."""
        target = _timestamp_nanos(timestamp)
        return self._move(lambda _: target)

    def with_live[A, E, R](self, eff: Effect[A, E, R]) -> Effect[A, E, R]:
        """Run ``eff`` with the live clock instead of this one."""
        require_effect(eff, "eff")
        return eff.pipe(provide_service(Clock, self._live))

    def stop_warning(self) -> None:
        """Never warn that time is not advancing; runners call it when the
        test ends."""
        self._not_advanced.disarm()

    @property
    def pending_sleeps(self) -> int:
        """How many fibers are sleeping on this clock."""
        return sum(1 for _, _, s in self._sleepers if s.alive)

    def _move(self, step: Callable[[float], float]) -> Effect[None]:
        def body(fiber: Fiber[Any, Any]) -> Effect[None]:
            self._not_advanced.disarm()
            scheduler = fiber._scheduler
            return self._moving.with_permits(_Gen(lambda: self._run(scheduler, step)))

        return _WithFiber(body)

    def _run(self, scheduler: Scheduler, step: Callable[[float], float]) -> Generator[Effect[None]]:
        # As Effect: let the fibers that are ready run once before moving.
        settled = yield from _YieldNow().fork()
        yield from settled.await_exit()
        yield from self._outside_done(scheduler)
        end = step(self._timestamp_ns)
        while self._sleepers and self._sleepers[0][0] <= end:
            when, _, sleeper = heapq.heappop(self._sleepers)
            if not sleeper.alive:
                continue
            self._advance_to(when)
            tracker = WakeTracker()
            scheduler.track(tracker, sleeper.wake)
            if tracker.pending:
                yield from self._wait_or_warn(scheduler, tracker.when_idle, _WAKE_WARNING)
            yield from self._outside_done(scheduler)
            yield from _YieldNow()
        self._advance_to(end)

    def _outside_done(self, scheduler: Scheduler) -> Generator[Effect[None]]:
        """Wait for work fibers handed to other threads, and for the fibers
        it resumes to suspend: thread-backed work takes no virtual time."""
        outside = scheduler.outside_work()
        if outside.pending:
            yield from self._wait_or_warn(scheduler, outside.when_idle, _OUTSIDE_WARNING)

    def _advance_to(self, timestamp: float) -> None:
        delta = timestamp - self._timestamp_ns
        if delta > 0 and math.isfinite(delta):
            self._monotonic_ns += int(delta)
        if math.isfinite(timestamp):
            self._wall_ns = int(timestamp)
        self._timestamp_ns = timestamp

    def _wait_or_warn(
        self, scheduler: Scheduler, arm: Callable[[Task], Cancel], message: str
    ) -> Effect[None]:
        """Wait for the callback given to ``arm``; after ``warning_delay`` of
        real time, warn with ``message`` and stop waiting."""

        def register(resume: Callable[[Effect[None]], None]) -> Effect[None] | None:
            armed: list[Cancel] = []  # the wait, then the warning timer
            finished = False

            def finish() -> None:
                nonlocal finished
                finished = True
                for cancel in armed:
                    cancel()
                resume(_Succeed(None))

            armed.append(arm(finish))  # calls ``finish`` now if the work is already over
            if finished:
                return None

            def give_up() -> None:
                armed[0]()
                # Warn from the fiber, in its context: without the GIL warning filters are
                # per context, and this timer's is not the caller's.
                resume(_Sync(lambda: warnings.warn(message, BusyFiberWarning, stacklevel=1)))

            armed.append(scheduler.call_later(self._warning_delay, give_up))

            def cancel() -> None:
                for cancel_one in armed:
                    cancel_one()

            return _Sync(cancel)

        return _Callback(register)


def test_clock() -> Effect[TestClock]:
    """The ``TestClock`` the effect runs with; dies if the clock is live."""

    def check(clock: ClockService) -> Effect[TestClock]:
        if not isinstance(clock, TestClock):
            raise TypeError(
                "no TestClock in context; run the effect with a pyfect.testing runner "
                "or provide TestClock.layer()"
            )
        return _Succeed(clock)

    return Clock().flat_map(check)


def adjust(duration: DurationInput) -> Effect[None]:
    """Move the test clock forward by ``duration``."""
    return test_clock().flat_map(lambda c: c.adjust(duration))


def set_time(timestamp: float) -> Effect[None]:
    """Set the test clock's wall time to ``timestamp`` (milliseconds since
    the epoch, as Effect's ``TestClock.setTime``)."""
    return test_clock().flat_map(lambda c: c.set_time(timestamp))


def with_live[A, E, R](eff: Effect[A, E, R]) -> Effect[A, E, R]:
    """Run ``eff`` with the live clock. Under a ``TestClock`` that is the
    clock it replaced; otherwise the clock is already live."""
    require_effect(eff, "eff")

    def run(clock: ClockService) -> Effect[A, E, R]:
        return clock.with_live(eff) if isinstance(clock, TestClock) else eff

    return Clock().flat_map(run)
