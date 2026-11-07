"""Time. ``Clock`` is a reference, so effects can sleep without declaring
it, and tests can swap in ``pyfect.testing.TestClock``.

Wall time (``now``) can jump, backwards too; monotonic time never does,
so measure elapsed time with it. Each comes in float seconds and in whole
nanoseconds (Effect's ``currentTimeNanos`` / ``monotonicTimeNanos``)."""
# pyright: reportPrivateUsage=false

from __future__ import annotations

import math
import time
from collections.abc import Callable
from typing import Any, Never, Protocol

from pyfect._core import Effect, _Callback, _Gen, _Succeed, _Sync, _WithFiber, _YieldNow
from pyfect._effect_args import require_effect
from pyfect._fiber import Fiber
from pyfect.context import Reference
from pyfect.duration import Duration, Seconds, from_nanos, to_seconds
from pyfect.effect import never


class ClockService(Protocol):
    def now_unsafe(self) -> float:
        """Wall-clock time, seconds since the epoch."""
        ...

    def monotonic_unsafe(self) -> float:
        """A clock that never goes backwards, in seconds."""
        ...

    def now_nanos_unsafe(self) -> int:
        """Wall-clock time, whole nanoseconds since the epoch."""
        ...

    def monotonic_nanos_unsafe(self) -> int:
        """Monotonic time in whole nanoseconds."""
        ...

    def sleep(self, seconds: Seconds) -> Effect[None]: ...


_NANOS = 1_000_000_000


class LiveClock:
    """The system clock. A sleep of zero or less yields once; an infinite
    sleep never wakes and holds no timer (as Effect's)."""

    def now_unsafe(self) -> float:
        return time.time_ns() / _NANOS

    def monotonic_unsafe(self) -> float:
        return time.monotonic_ns() / _NANOS

    def now_nanos_unsafe(self) -> int:
        return time.time_ns()

    def monotonic_nanos_unsafe(self) -> int:
        return time.monotonic_ns()

    def sleep(self, seconds: Seconds) -> Effect[None]:
        if seconds <= 0:
            return _YieldNow()
        if math.isinf(seconds):
            return never

        def body(fiber: Fiber[Any, Any]) -> Effect[None]:
            def register(resume: Callable[[Effect[None]], None]) -> Effect[None]:
                cancel = fiber._scheduler.call_later(seconds, lambda: resume(_Succeed(None)))
                return _Sync(cancel)

            return _Callback(register)

        return _WithFiber(body)


class Clock(Reference[ClockService]):
    @classmethod
    def default(cls) -> ClockService:
        return LiveClock()


def sleep(duration: Duration) -> Effect[None]:
    seconds = to_seconds(duration)
    return Clock().flat_map(lambda c: c.sleep(seconds))


def now() -> Effect[float]:
    """Wall-clock time, seconds since the epoch."""
    return Clock().map(lambda c: c.now_unsafe())


def monotonic() -> Effect[float]:
    """Monotonic time in seconds."""
    return Clock().map(lambda c: c.monotonic_unsafe())


def now_millis_unsafe(clock: ClockService) -> int:
    """``clock``'s wall-clock time in whole milliseconds since the epoch
    (Effect's ``currentTimeMillisUnsafe``), floored from its nanoseconds:
    ``now_unsafe() * 1000`` floors 1.001 s to 1000 ms."""
    return clock.now_nanos_unsafe() // 1_000_000


def now_nanos() -> Effect[int]:
    """Wall-clock time, whole nanoseconds since the epoch."""
    return Clock().map(lambda c: c.now_nanos_unsafe())


def monotonic_nanos() -> Effect[int]:
    """Monotonic time in whole nanoseconds."""
    return Clock().map(lambda c: c.monotonic_nanos_unsafe())


def clock_with[A, E = Never, R = Never](
    f: Callable[[ClockService], Effect[A, E, R]],
) -> Effect[A, E, R]:
    """Run ``f`` with the current clock."""
    return Clock().flat_map(f)


def timed[A, E, R](eff: Effect[A, E, R]) -> Effect[tuple[Seconds, A], E, R]:
    """Pair ``eff``'s value with how long it took as ``Seconds``, measured in
    whole monotonic nanoseconds."""
    require_effect(eff, "eff")

    def body():
        start = yield from monotonic_nanos()
        value = yield from eff
        end = yield from monotonic_nanos()
        return (from_nanos(end - start), value)

    return _Gen(body)


__all__ = [
    "Clock",
    "ClockService",
    "LiveClock",
    "clock_with",
    "monotonic",
    "monotonic_nanos",
    "now",
    "now_millis_unsafe",
    "now_nanos",
    "sleep",
    "timed",
]
