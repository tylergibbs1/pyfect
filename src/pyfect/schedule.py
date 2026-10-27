"""Schedules: when to repeat or retry.

A ``Schedule[In, Out]`` takes an input at each step (the error, for
``retry``; the value, for ``repeat``) and decides whether to go again and
after how long. It also produces an output (a count, the current delay).

Schedules are immutable values. Every run starts from the schedule's
initial state, so one schedule can be shared freely.

    eff.retry(exponential(0.1).take(5))
    eff.repeat(spaced(1.0))
"""
# pyright: reportPrivateUsage=false

from __future__ import annotations

import random
from collections.abc import Callable
from typing import Any, Generic, TypeVar

from pyfect._core import Effect, _FailCause, _Gen
from pyfect._effect_args import require_effect
from pyfect.cause import Fail, fail
from pyfect.clock import monotonic, sleep
from pyfect.duration import ZERO, Duration, Seconds, to_seconds
from pyfect.exit import Failure

In_contra = TypeVar("In_contra", contravariant=True)
Out_co = TypeVar("Out_co", covariant=True)

type Decision = Seconds | None
"""How long to wait before the next step, or ``None`` to stop."""


class Schedule(Generic[In_contra, Out_co]):
    """Build with the functions in this module; combine with methods."""

    __slots__ = ("_initial", "_step")

    def __init__(
        self,
        initial: object,
        step: Callable[[float, Any, Any], tuple[Any, Any, Decision]],
    ) -> None:
        self._initial = initial
        self._step = step

    def run_step(
        self, now: float, value: In_contra, state: object
    ) -> tuple[object, Out_co, Decision]:
        """Advance one step from ``state``. Returns the new state, the
        output, and the decision."""
        return self._step(now, value, state)

    @property
    def initial(self) -> object:
        return self._initial

    def map[B](self, f: Callable[[Out_co], B]) -> Schedule[In_contra, B]:
        step = self._step

        def mapped(now: float, value: Any, state: Any) -> tuple[Any, B, Decision]:
            s, out, d = step(now, value, state)
            return s, f(out), d

        return Schedule(self._initial, mapped)

    def take(self, n: int) -> Schedule[In_contra, Out_co]:
        """Stop after at most ``n`` recurrences."""
        if n < 0:
            raise ValueError(f"take needs n >= 0, got {n}")
        step = self._step

        def limited(now: float, value: Any, state: Any) -> tuple[Any, Any, Decision]:
            count, inner = state
            s, out, d = step(now, value, inner)
            return (count + 1, s), out, (d if count < n else None)

        return Schedule((0, self._initial), limited)

    def while_input(self, predicate: Callable[[In_contra], bool]) -> Schedule[In_contra, Out_co]:
        """Continue only while ``predicate(input)`` holds. For ``retry``,
        the input is the error: retry only the errors you expect to pass."""
        step = self._step

        def guarded(now: float, value: Any, state: Any) -> tuple[Any, Any, Decision]:
            s, out, d = step(now, value, state)
            return s, out, (d if predicate(value) else None)

        return Schedule(self._initial, guarded)

    def while_output(self, predicate: Callable[[Out_co], bool]) -> Schedule[In_contra, Out_co]:
        step = self._step

        def guarded(now: float, value: Any, state: Any) -> tuple[Any, Any, Decision]:
            s, out, d = step(now, value, state)
            return s, out, (d if predicate(out) else None)

        return Schedule(self._initial, guarded)

    def capped(self, max_delay: Duration) -> Schedule[In_contra, Out_co]:
        """Never wait longer than ``max_delay`` between steps."""
        cap = to_seconds(max_delay)
        step = self._step

        def capping(now: float, value: Any, state: Any) -> tuple[Any, Any, Decision]:
            s, out, d = step(now, value, state)
            return s, out, (None if d is None else min(d, cap))

        return Schedule(self._initial, capping)

    def jittered(self, low: float = 0.8, high: float = 1.2) -> Schedule[In_contra, Out_co]:
        """Scale each delay by a random factor in ``[low, high]``."""
        step = self._step

        def jitter(now: float, value: Any, state: Any) -> tuple[Any, Any, Decision]:
            s, out, d = step(now, value, state)
            return s, out, (None if d is None else Seconds(d * random.uniform(low, high)))

        return Schedule(self._initial, jitter)

    def up_to(self, duration: Duration) -> Schedule[In_contra, Out_co]:
        """Stop once more than ``duration`` has passed since the first step."""
        limit = to_seconds(duration)
        step = self._step

        def bounded(now: float, value: Any, state: Any) -> tuple[Any, Any, Decision]:
            started, inner = state
            started = now if started is None else started
            s, out, d = step(now, value, inner)
            return (started, s), out, (d if now - started <= limit else None)

        return Schedule((None, self._initial), bounded)


def both[I, O1, O2](a: Schedule[I, O1], b: Schedule[I, O2]) -> Schedule[I, tuple[O1, O2]]:
    """Continue while both continue, waiting the longer of the two delays."""

    def step(now: float, value: Any, state: Any) -> tuple[Any, Any, Decision]:
        sa, oa, da = a._step(now, value, state[0])
        sb, ob, db = b._step(now, value, state[1])
        decision = None if da is None or db is None else max(da, db)
        return (sa, sb), (oa, ob), decision

    return Schedule((a._initial, b._initial), step)


def either[I, O1, O2](a: Schedule[I, O1], b: Schedule[I, O2]) -> Schedule[I, tuple[O1, O2]]:
    """Continue while either continues, waiting the shorter delay."""

    def step(now: float, value: Any, state: Any) -> tuple[Any, Any, Decision]:
        sa, oa, da = a._step(now, value, state[0])
        sb, ob, db = b._step(now, value, state[1])
        decisions = [d for d in (da, db) if d is not None]
        return (sa, sb), (oa, ob), (min(decisions) if decisions else None)

    return Schedule((a._initial, b._initial), step)


# --- constructors -------------------------------------------------------------


def forever() -> Schedule[object, int]:
    """Recur immediately, forever. Outputs the recurrence count."""
    return Schedule(0, lambda _now, _v, n: (n + 1, n, ZERO))


def recurs(n: int) -> Schedule[object, int]:
    """Recur ``n`` times, immediately."""
    return forever().take(n)


def spaced(interval: Duration) -> Schedule[object, int]:
    """Wait ``interval`` between recurrences."""
    seconds = to_seconds(interval)
    return Schedule(0, lambda _now, _v, n: (n + 1, n, seconds))


def fixed(interval: Duration) -> Schedule[object, int]:
    """Recur on a fixed beat of ``interval``. If a run takes longer than the
    interval, the next one starts at once; missed beats are not replayed."""
    window = to_seconds(interval)
    if window == 0:
        return forever()

    def step(now: float, _v: object, state: tuple[float, float, int]) -> tuple[Any, int, Decision]:
        start, last_run, n = state
        if n == 0:
            return (now, now + window, 1), 0, window
        running_behind = now > last_run + window
        boundary = window - ((now - start) % window)
        delay = Seconds(0.0 if running_behind else window if boundary == 0 else boundary)
        return (start, now if running_behind else now + delay, n + 1), n, delay

    return Schedule((0.0, 0.0, 0), step)


def exponential(base: Duration, factor: float = 2.0) -> Schedule[object, Seconds]:
    """Delays of ``base``, ``base*factor``, ``base*factor**2``, ...
    Outputs the delay."""
    first = to_seconds(base)

    def step(_now: float, _v: object, n: int) -> tuple[int, Seconds, Decision]:
        delay = Seconds(first * factor**n)
        return n + 1, delay, delay

    return Schedule(0, step)


def fibonacci(one: Duration) -> Schedule[object, Seconds]:
    """Delays of ``one``, ``2*one``, ``3*one``, ``5*one``, ...: each the sum
    of the two before, starting from 0 and ``one``. Outputs the delay."""
    unit = to_seconds(one)

    def step(_now: float, _v: object, state: tuple[float, float]) -> tuple[Any, Seconds, Decision]:
        a, b = state
        nxt = Seconds(a + b)
        return (b, nxt), nxt, nxt

    return Schedule((0.0, unit), step)


# --- driving effects ------------------------------------------------------------


def retry[A, E, R](eff: Effect[A, E, R], schedule: Schedule[E, object]) -> Effect[A, E, R]:
    require_effect(eff, "eff")

    def body():
        state = schedule.initial
        while True:
            result = yield from eff.exit()
            if not isinstance(result, Failure):
                return result.value
            found = result.cause.find_recoverable_error()
            if not isinstance(found, Fail):  # defects and interruptions are not retried
                return (yield from _FailCause(found))
            now = yield from monotonic()
            state, _, decision = schedule.run_step(now, found.error, state)
            if decision is None:
                return (yield from _FailCause(fail(found.error)))
            yield from sleep(decision)

    return _Gen(body)


def repeat[A, B, E, R](eff: Effect[A, E, R], schedule: Schedule[A, B]) -> Effect[B, E, R]:
    require_effect(eff, "eff")

    def body():
        state = schedule.initial
        while True:
            value = yield from eff
            now = yield from monotonic()
            state, out, decision = schedule.run_step(now, value, state)
            if decision is None:
                return out
            yield from sleep(decision)

    return _Gen(body)
