"""Time. ``Clock`` is a reference, so effects can sleep without declaring
it, and tests can swap in ``pyfect.testing.TestClock``.

Wall time can jump, backwards too; monotonic time never does, so measure
elapsed time with it. Wall time comes in epoch milliseconds
(``current_time_millis``, Effect's ``currentTimeMillis``) and whole
nanoseconds (``now_nanos``, Effect's ``currentTimeNanos``); monotonic time
in float seconds and whole nanoseconds (``monotonic_nanos``, Effect's
``monotonicTimeNanos``)."""
# pyright: reportPrivateUsage=false

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any, Never, Protocol

from pyfect._core import Effect, _Callback, _Gen, _Succeed, _Sync, _WithFiber, _YieldNow
from pyfect._effect_args import require_effect
from pyfect._fiber import Fiber
from pyfect.context import Reference
from pyfect.duration import Duration, from_input_unsafe, nanos
from pyfect.duration import Input as DurationInput
from pyfect.effect import never


class ClockService(Protocol):
    def current_time_millis_unsafe(self) -> float:
        """Wall-clock time, milliseconds since the epoch (Effect's
        ``currentTimeMillisUnsafe``)."""
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

    def sleep(self, duration: Duration, /) -> Effect[None]: ...


_NANOS = 1_000_000_000
_NANOS_PER_MILLI = 1_000_000


class LiveClock:
    """The system clock. A sleep of zero or less yields once; an infinite
    sleep never wakes and holds no timer (as Effect's)."""

    def current_time_millis_unsafe(self) -> float:
        return time.time_ns() // _NANOS_PER_MILLI

    def monotonic_unsafe(self) -> float:
        return time.monotonic_ns() / _NANOS

    def now_nanos_unsafe(self) -> int:
        return time.time_ns()

    def monotonic_nanos_unsafe(self) -> int:
        return time.monotonic_ns()

    def sleep(self, duration: Duration) -> Effect[None]:
        if not duration.is_positive():
            return _YieldNow()
        if not duration.is_finite():
            return never

        def body(fiber: Fiber[Any, Any]) -> Effect[None]:
            def register(resume: Callable[[Effect[None]], None]) -> Effect[None]:
                cancel = fiber._scheduler.call_later(duration, lambda: resume(_Succeed(None)))
                return _Sync(cancel)

            return _Callback(register)

        return _WithFiber(body)


class Clock(Reference[ClockService]):
    @classmethod
    def default(cls) -> ClockService:
        return LiveClock()


def sleep(duration: DurationInput) -> Effect[None]:
    """Wait for ``duration`` on the ``Clock`` (a duration such as ``"5 seconds"``)."""
    parsed = from_input_unsafe(duration)
    return Clock().flat_map(lambda c: c.sleep(parsed))


def current_time_millis() -> Effect[float]:
    """Wall-clock time, milliseconds since the epoch (Effect's
    ``currentTimeMillis``)."""
    return Clock().map(lambda c: c.current_time_millis_unsafe())


def monotonic() -> Effect[float]:
    """Monotonic time in seconds."""
    return Clock().map(lambda c: c.monotonic_unsafe())


def now_millis_unsafe(clock: ClockService) -> int:
    """``clock``'s wall-clock time in whole milliseconds since the epoch,
    floored from its nanoseconds (``current_time_millis_unsafe`` keeps a
    test clock's fraction of a millisecond, as Effect's does)."""
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


def timed[A, E, R](eff: Effect[A, E, R]) -> Effect[tuple[Duration, A], E, R]:
    """Pair ``eff``'s value with how long it took as a ``Duration``, measured in
    whole monotonic nanoseconds."""
    require_effect(eff, "eff")

    def body():
        start = yield from monotonic_nanos()
        value = yield from eff
        end = yield from monotonic_nanos()
        return (nanos(end - start), value)

    return _Gen(body)


__all__ = [
    "Clock",
    "ClockService",
    "LiveClock",
    "clock_with",
    "current_time_millis",
    "monotonic",
    "monotonic_nanos",
    "now_millis_unsafe",
    "now_nanos",
    "sleep",
    "timed",
]
