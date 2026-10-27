"""Time. ``Clock`` is a reference, so effects can sleep without declaring
it, and tests can swap in ``pyfect.testing.TestClock``."""
# pyright: reportPrivateUsage=false

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any, Protocol

from pyfect._core import Effect, _Callback, _Gen, _Succeed, _Sync, _WithFiber
from pyfect._effect_args import require_effect
from pyfect._fiber import Fiber
from pyfect.context import Reference
from pyfect.duration import Duration, Seconds, to_seconds


class ClockService(Protocol):
    def unsafe_now(self) -> float:
        """Wall-clock time, seconds since the epoch."""
        ...

    def unsafe_monotonic(self) -> float:
        """A clock that never goes backwards, in seconds."""
        ...

    def sleep(self, seconds: Seconds) -> Effect[None]: ...


class LiveClock:
    def unsafe_now(self) -> float:
        return time.time()

    def unsafe_monotonic(self) -> float:
        return time.monotonic()

    def sleep(self, seconds: Seconds) -> Effect[None]:
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
    return Clock().map(lambda c: c.unsafe_now())


def monotonic() -> Effect[float]:
    return Clock().map(lambda c: c.unsafe_monotonic())


def timed[A, E, R](eff: Effect[A, E, R]) -> Effect[tuple[float, A], E, R]:
    require_effect(eff, "eff")

    def body():
        start = yield from monotonic()
        value = yield from eff
        end = yield from monotonic()
        return (end - start, value)

    return _Gen(body)
