"""The work behind ``Stream``'s ``schedule``, ``repeat_elements``,
``timeout_or_else``, ``debounce`` and ``throttle``."""
# pyright: reportPrivateUsage=false

from __future__ import annotations

import math
from collections.abc import Callable, Generator
from typing import Any

from pyfect import _js as js
from pyfect._core import Effect, _FailCause, _FlatMap, _Gen, _Succeed, _Suspend
from pyfect.cause import Cause, Die
from pyfect.cause import die as die_cause
from pyfect.channel import transform_pull
from pyfect.clock import Clock, ClockService, sleep
from pyfect.duration import Input as DurationInput
from pyfect.duration import from_input_unsafe, from_nanos_or_infinite, nanos_or_infinite
from pyfect.latch import Latch
from pyfect.schedule import Schedule
from pyfect.schedule._model import Stop, to_step_with_sleep
from pyfect.scope import CloseableScope
from pyfect.stream._base import AnyStream
from pyfect.stream._mapping import one
from pyfect.stream._stream import Stream

type AnyEffect = Effect[Any, Any, Any]
type Chunk = tuple[Any, ...]
type AnyStream_ = Stream[Any, Any, Any]

_VOID: AnyEffect = _Succeed(None)


def _none(_: object) -> None:
    return None


def schedule(self: AnyStream, policy: Schedule[Any, Any, Any, Any]) -> AnyStream_:
    scheduled = self._channel.flatten_array().schedule(policy).map_done(_none)
    return Stream(scheduled.map(one))


def repeat_elements(self: AnyStream, policy: Schedule[Any, Any, Any, Any]) -> AnyStream_:
    def build(pull_item: AnyEffect, _scope: CloseableScope) -> AnyEffect:
        repeating = _RepeatElements(pull_item, policy)
        pull = _Gen(repeating.first)
        return _Succeed(
            _Suspend(
                lambda: (
                    pull
                    if (decide := repeating.decide) is None
                    else _FlatMap(decide, repeating.decided)
                )
            )
        )

    return Stream(transform_pull(self._channel.flatten_array(), build))


class _RepeatElements:
    """One run of ``repeat_elements``: ``decide`` is the schedule's step for
    the item in ``chunk`` while it repeats."""

    __slots__ = ("chunk", "decide", "policy", "pull_item")

    def __init__(self, pull_item: AnyEffect, policy: Schedule[Any, Any, Any, Any]) -> None:
        self.pull_item = pull_item
        self.policy = policy
        self.chunk: Chunk = ()
        self.decide: AnyEffect | None = None

    def first(self) -> Generator[AnyEffect, Any, Chunk]:
        item = yield self.pull_item
        chunk = (item,)
        step = yield to_step_with_sleep(self.policy)
        self.chunk = chunk
        self.decide = step(item)
        return chunk

    def decided(self, decision: object) -> AnyEffect:
        if isinstance(decision, Stop):
            self.decide = None
            self.chunk = ()
            return _Gen(self.first)
        return _Succeed(self.chunk)


# --- timeouts -----------------------------------------------------------------


class _TimedOut(Exception):
    """Dies the merged watcher when a pull waits past the timeout."""


def timeout_or_else(
    self: AnyStream, duration: DurationInput, or_else: Callable[[], AnyStream] | None
) -> AnyStream_:
    from pyfect.stream._constructors import empty, from_effect_drain, suspend, unwrap

    parsed = from_input_unsafe(duration)
    fallback: Callable[[], AnyStream] = or_else or (lambda: empty)
    if not parsed.is_finite() and parsed.is_positive():
        return Stream(self._channel)
    if not parsed.is_positive():
        return suspend(fallback)
    marker = _TimedOut()
    timeout_ns = nanos_or_infinite(parsed)

    def with_clock(clock: ClockService) -> AnyStream_:
        # When the pull in flight times out (clock nanoseconds); empty while
        # no pull waits.
        deadline: list[int | float] = []
        waiting = Latch()

        def started(pull: AnyEffect) -> AnyEffect:
            def start() -> AnyEffect:
                deadline[:] = [clock.now_nanos_unsafe() + timeout_ns]
                waiting.open_unsafe()
                return pull

            def arrived(chunk: Chunk) -> AnyEffect:
                waiting.close_unsafe()
                deadline.clear()
                return _Succeed(chunk)

            return _FlatMap(_Suspend(start), arrived)

        def watch() -> Generator[AnyEffect, Any]:
            while True:
                yield waiting.wait()
                if not deadline:
                    continue
                yield sleep(from_nanos_or_infinite(deadline[0] - clock.now_nanos_unsafe()))
                if not deadline or deadline[0] - clock.now_nanos_unsafe() > 0:
                    continue
                yield _FailCause(die_cause(marker))

        timed = Stream(transform_pull(self._channel, lambda pull, _: _Succeed(started(pull))))
        return timed.merge(from_effect_drain(_Gen(watch)), halt_strategy="left")

    def recover(cause: Cause[Any]) -> AnyStream_:
        from pyfect.stream._constructors import fail_cause

        timed_out = any(isinstance(r, Die) and r.defect is marker for r in cause.reasons)
        return Stream(fallback()._channel) if timed_out else fail_cause(cause)

    return unwrap(Clock().map(with_clock)).catch_cause(recover)


# --- debouncing ---------------------------------------------------------------


def debounce(self: AnyStream, duration: DurationInput) -> AnyStream_:
    wait_ns = nanos_or_infinite(from_input_unsafe(duration))

    def build(pull: AnyEffect, scope: CloseableScope) -> AnyEffect:
        def body() -> Generator[AnyEffect, Any, AnyEffect]:
            clock: ClockService = yield Clock()
            state = _Debounce(clock, wait_ns)
            pulling = state.pulling
            emitting = state.emitting
            producer = pulling.when_open(pull).flat_map(state.got).forever(disable_yield=True)
            yield producer.on_error(state.failed).fork_in(scope)
            sleep_loop = _Suspend(state.loop)

            def next_pull() -> AnyEffect:
                if state.stopped is not None:
                    last = state.last
                    return state.take_last(last) if last is not None else _FailCause(state.stopped)
                pulling.open_unsafe()
                return emitting.when_open(sleep_loop)

            return _Suspend(next_pull)

        return _Gen(body)

    return Stream(transform_pull(self._channel, build))


class _Debounce:
    """One run of ``debounce``: a loop on a state object, not closures that
    reach each other (that cycle would keep the last chunk alive after the run)."""

    __slots__ = ("clock", "emit_at", "emitting", "ended", "last", "pulling", "stopped", "wait_ns")

    def __init__(self, clock: ClockService, wait_ns: int | float) -> None:
        self.clock = clock
        self.wait_ns = wait_ns
        self.last: Chunk | None = None
        self.stopped: Cause[Any] | None = None
        self.emit_at: int | float = math.inf  # clock nanoseconds
        self.pulling = Latch()
        self.emitting = Latch()
        self.ended = Latch()

    def got(self, chunk: Chunk) -> AnyEffect:
        self.emitting.open_unsafe()
        self.last = chunk
        self.emit_at = self.clock.now_nanos_unsafe() + self.wait_ns
        return _VOID

    def failed(self, cause: Cause[Any]) -> AnyEffect:
        self.stopped = cause
        self.emit_at = self.clock.now_nanos_unsafe()
        self.emitting.open_unsafe()
        self.ended.open_unsafe()
        return _VOID

    def take_last(self, chunk: Chunk) -> AnyEffect:
        self.last = None
        return _Succeed((chunk[-1],))

    def loop(self) -> AnyEffect:
        now = self.clock.now_nanos_unsafe()
        wait_ns = self.wait_ns
        delay = wait_ns if self.emit_at < now else min(wait_ns, self.emit_at - now)
        return _FlatMap(
            sleep(from_nanos_or_infinite(delay)).race_first(self.ended.wait()), self.after
        )

    def after(self, _: object) -> AnyEffect:
        if self.clock.now_nanos_unsafe() < self.emit_at:
            return self.loop()
        if self.last is not None:
            self.emitting.close_unsafe()
            self.pulling.close_unsafe()
            return self.take_last(self.last)
        if self.stopped is not None:
            return _FailCause(self.stopped)
        return self.loop()


# --- throttling ---------------------------------------------------------------


def throttle(
    self: AnyStream,
    cost: Callable[[Chunk], AnyEffect],
    units: float,
    duration: DurationInput,
    *,
    burst: float,
    strategy: str,
) -> AnyStream_:
    seconds = from_input_unsafe(duration)
    period_ns = nanos_or_infinite(seconds)
    cap = math.inf if units + burst < 0 else units + burst
    if strategy == "enforce":
        return _throttle_enforce(self, cost, units, period_ns, cap)
    return _throttle_shape(self, cost, units, period_ns, cap)


def _refilled(tokens: float, elapsed_ns: int, period_ns: float, units: float) -> float:
    """The bucket after ``elapsed_ns``. Times are whole nanoseconds, so
    equal steps refill equally; the division is JavaScript's, as in Effect
    (``x / 0`` is infinite and ``0 / 0`` is NaN), so a zero period never
    raises."""
    if period_ns == 0:
        cycles = math.nan if elapsed_ns == 0 else math.inf
    else:
        cycles = elapsed_ns / period_ns
    return tokens + cycles * units


def _throttle_enforce(
    self: AnyStream, cost: Callable[[Chunk], AnyEffect], units: float, period_ns: float, cap: float
) -> AnyStream_:
    def with_clock(pull: AnyEffect, clock: ClockService) -> AnyEffect:
        state = _ThrottleEnforce(pull, clock, cost, units=units, period_ns=period_ns, cap=cap)
        return _FlatMap(pull, state.loop)

    return Stream(
        transform_pull(self._channel, lambda pull, _: Clock().map(lambda c: with_clock(pull, c)))
    )


class _ThrottleEnforce:
    """One run of ``throttle`` with ``"enforce"``: a loop on a state object, not
    closures that reach each other (that cycle would keep the pull alive after
    the run)."""

    __slots__ = ("cap", "clock", "cost", "period_ns", "pull", "stamp", "tokens", "units")

    def __init__(
        self,
        pull: AnyEffect,
        clock: ClockService,
        cost: Callable[[Chunk], AnyEffect],
        *,
        units: float,
        period_ns: float,
        cap: float,
    ) -> None:
        self.pull = pull
        self.clock = clock
        self.cost = cost
        self.units = units
        self.period_ns = period_ns
        self.cap = cap
        self.tokens = units
        self.stamp = clock.now_nanos_unsafe()

    def loop(self, chunk: Chunk) -> AnyEffect:
        return _FlatMap(self.cost(chunk), lambda weight: self.weighed(chunk, weight))

    def weighed(self, chunk: Chunk, weight: float) -> AnyEffect:
        now = self.clock.now_nanos_unsafe()
        total = _refilled(self.tokens, now - self.stamp, self.period_ns, self.units)
        available = self.cap if total < 0 else min(total, self.cap)
        if weight <= available:
            self.tokens = available - weight
            self.stamp = now
            return _Succeed(chunk)
        return _FlatMap(self.pull, self.loop)


def _throttle_shape(
    self: AnyStream, cost: Callable[[Chunk], AnyEffect], units: float, period_ns: float, cap: float
) -> AnyStream_:
    def with_clock(pull: AnyEffect, clock: ClockService) -> AnyEffect:
        tokens = units
        stamp = clock.monotonic_nanos_unsafe()

        def admit(chunk: Chunk) -> AnyEffect:
            def weighed(weight: float) -> AnyEffect:
                nonlocal tokens, stamp
                now = clock.monotonic_nanos_unsafe()
                remaining = min(_refilled(tokens, now - stamp, period_ns, units), cap) - weight

                def keep(_: object = None) -> AnyEffect:
                    nonlocal tokens, stamp
                    tokens = remaining
                    stamp = now
                    return _Succeed(chunk)

                if remaining >= 0:
                    return keep()
                cycles = math.inf if units == 0 else -remaining / units
                delay = max(0.0, cycles * period_ns)
                if delay <= 0:
                    return keep()
                # Effect sleeps fractional milliseconds rounded to the nanosecond.
                wait = from_nanos_or_infinite(delay if math.isinf(delay) else int(js.round(delay)))
                return _FlatMap(sleep(wait), keep)

            return _FlatMap(cost(chunk), weighed)

        return _FlatMap(pull, admit)

    return Stream(
        transform_pull(self._channel, lambda pull, _: Clock().map(lambda c: with_clock(pull, c)))
    )
