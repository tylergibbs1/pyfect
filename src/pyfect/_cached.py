"""``Effect.cached`` and its TTL variants.

A cache runs its source on a fiber of its own (with the context of the
caller that started it), so callers can leave without killing a run others
still wait on. Each caller waiting on a run is counted; when the last one
leaves before the run is done, the run is interrupted and detached, so the
next caller starts afresh. An interrupted run is never cached.

Runs on other threads share a cache: its fields change holding its lock,
and a run starts only once the lock is let go (starting runs the source).
"""
# pyright: reportPrivateUsage=false

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any, Final

from pyfect._core import (
    Effect,
    Frame,
    Step,
    _FlatMap,
    _FromExit,
    _SetInterruptible,
    _Sync,
    _WithFiber,
)
from pyfect._fiber import Fiber
from pyfect.cause import Cause
from pyfect.clock import Clock, ClockService
from pyfect.duration import Duration, from_input_unsafe, infinity, nanos_or_infinite
from pyfect.duration import Input as DurationInput
from pyfect.exit import Exit, Failure, Success

type TimeToLive[A, E] = DurationInput | Callable[[Exit[A, E]], DurationInput]

_FOREVER: Final = infinity


def cached[A, E, R](source: Effect[A, E, R]) -> Effect[Effect[A, E, R]]:
    return _Sync(lambda: memoize(source))


def memoize[A, E, R](source: Effect[A, E, R]) -> Effect[A, E, R]:
    """``cached`` made now: an effect that runs ``source`` once, the first
    time it runs, and then gives back its exit."""
    return _Cache(source, lambda _: _FOREVER).get


def cached_invalidate_with_ttl[A, E, R](
    source: Effect[A, E, R], time_to_live: TimeToLive[A, E]
) -> Effect[tuple[Effect[A, E, R], Effect[None]]]:
    if callable(time_to_live):
        pick = time_to_live

        def ttl(ex: Exit[A, E]) -> Duration:
            return from_input_unsafe(pick(ex))
    else:
        fixed = from_input_unsafe(time_to_live)

        def ttl(ex: Exit[A, E]) -> Duration:
            return fixed

    def make() -> tuple[Effect[A, E, R], Effect[None]]:
        cache = _Cache(source, ttl)
        return cache.get, cache.invalidate

    return _Sync(make)


class _Run:
    """One evaluation of the source, and how many callers wait on it."""

    __slots__ = ("awaiters", "done", "fiber")

    def __init__(self, fiber: Fiber[Any, Any]) -> None:
        self.fiber = fiber
        self.awaiters = 0
        self.done = False


class _Cache[A, E, R]:
    __slots__ = ("current", "exit", "expires_at", "get", "invalidate", "lock", "source", "ttl")

    def __init__(self, source: Effect[A, E, R], ttl: Callable[[Exit[A, E]], Duration]) -> None:
        self.source = source
        self.ttl = ttl
        self.exit: Exit[A, E] | None = None
        self.expires_at: int | float = 0  # monotonic nanoseconds
        self.current: _Run | None = None
        self.lock = threading.Lock()
        self.get: Effect[A, E, R] = _WithFiber(self._get)
        self.invalidate: Effect[None] = _Sync(self._invalidate)

    def _get(self, fiber: Fiber[Any, Any]) -> Effect[A, E, R]:
        clock: ClockService = fiber._context.lookup(Clock)[1]
        with self.lock:
            run = self.current
            if run is not None:
                # A run reading its own cache is not an awaiter: counting it
                # would keep the run alive after every real caller left.
                return run.fiber.join() if run.fiber is fiber else self._join(fiber, run)
            if self.exit is not None and (clock.monotonic_nanos_unsafe() < self.expires_at):
                return _FromExit(self.exit)
            self.exit = None
            run = _Run(Fiber(fiber._run_scheduler, fiber._context, None))
            self.current = run
            joined = self._join(fiber, run)
        # Started at once, as in Effect: it runs right after this fiber parks.
        run.fiber._drive_first(
            self.source.on_exit(lambda ex: _Sync(lambda: self._publish(run, ex, clock)))
        )
        return joined

    def _join(self, fiber: Fiber[Any, Any], run: _Run) -> Effect[A, E, R]:
        """Call holding the lock."""
        run.awaiters += 1
        fiber._push(_LeaveRun(self, run))
        return run.fiber.join()

    def _publish(self, run: _Run, ex: Exit[A, E], clock: ClockService) -> None:
        with self.lock:
            run.done = True
            if self.current is not run:
                return  # invalidated: callers already on it get its exit, nobody else
            self.current = None
            if isinstance(ex, Failure) and ex.cause.has_interrupts:
                return  # abandoned, not a result
            ttl = self.ttl(ex)
            self.expires_at = clock.monotonic_nanos_unsafe() + nanos_or_infinite(ttl)
            self.exit = ex

    def leave(self, run: _Run) -> Effect[None] | None:
        """A caller stopped waiting on ``run``. Gives the effect that
        abandons the run if that caller was the last one."""
        with self.lock:
            run.awaiters -= 1
            if run.awaiters > 0 or run.done:
                return None
            if self.current is run:
                self.current = None
        return run.fiber.interrupt()

    def _invalidate(self) -> None:
        with self.lock:
            self.current = None
            self.exit = None


class _LeaveRun(Frame):
    """Pushed by a caller joining a run, so leaving is counted however the
    join ends. Abandoning the run happens uninterruptibly, then the caller
    ends as its join did."""

    __slots__ = ("cache", "run")

    def __init__(self, cache: _Cache[Any, Any, Any], run: _Run) -> None:
        self.cache = cache
        self.run = run

    def _on_success(self, value: Any, fiber: Fiber[Any, Any]) -> Step:
        return self._leave(Success(value), fiber)

    def _on_failure(self, cause: Cause[Any], fiber: Fiber[Any, Any]) -> Step:
        return self._leave(Failure(cause), fiber)

    def _leave(self, ex: Exit[Any, Any], fiber: Fiber[Any, Any]) -> Step:
        abandon = self.cache.leave(self.run)
        if abandon is None:
            return ex
        # Stepped here, not returned: an interrupted fiber would turn a
        # returned effect into a failure before it could run.
        return _SetInterruptible(_FlatMap(abandon, lambda _: _FromExit(ex)), False)._step(fiber)
