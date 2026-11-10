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
        repeating: AnyEffect | None = None

        def first() -> Generator[AnyEffect, Any, Chunk]:
            nonlocal repeating
            item = yield pull_item
            chunk = (item,)
            step = yield to_step_with_sleep(policy)

            def decided(decision: object) -> AnyEffect:
                nonlocal repeating
                if isinstance(decision, Stop):
                    repeating = None
                    return pull
                return _Succeed(chunk)

            repeating = _FlatMap(step(item), decided)
            return chunk

        pull = _Gen(first)
        return _Succeed(_Suspend(lambda: pull if repeating is None else repeating))

    return Stream(transform_pull(self._channel.flatten_array(), build))


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
            last: Chunk | None = None
            stopped: Cause[Any] | None = None
            emit_at: int | float = math.inf  # clock nanoseconds
            pulling = Latch()
            emitting = Latch()
            ended = Latch()

            def got(chunk: Chunk) -> AnyEffect:
                nonlocal last, emit_at
                emitting.open_unsafe()
                last = chunk
                emit_at = clock.now_nanos_unsafe() + wait_ns
                return _VOID

            def failed(cause: Cause[Any]) -> AnyEffect:
                nonlocal stopped, emit_at
                stopped = cause
                emit_at = clock.now_nanos_unsafe()
                emitting.open_unsafe()
                ended.open_unsafe()
                return _VOID

            producer = pulling.when_open(pull).flat_map(got).forever(disable_yield=True)
            yield producer.on_error(failed).fork_in(scope)

            def take_last(chunk: Chunk) -> AnyEffect:
                nonlocal last
                last = None
                return _Succeed((chunk[-1],))

            def loop() -> AnyEffect:
                now = clock.now_nanos_unsafe()
                delay = wait_ns if emit_at < now else min(wait_ns, emit_at - now)
                return _FlatMap(
                    sleep(from_nanos_or_infinite(delay)).race_first(ended.wait()), after
                )

            def after(_: object) -> AnyEffect:
                if clock.now_nanos_unsafe() < emit_at:
                    return loop()
                if last is not None:
                    emitting.close_unsafe()
                    pulling.close_unsafe()
                    return take_last(last)
                if stopped is not None:
                    return _FailCause(stopped)
                return loop()

            sleep_loop = _Suspend(loop)

            def next_pull() -> AnyEffect:
                if stopped is not None:
                    return take_last(last) if last is not None else _FailCause(stopped)
                pulling.open_unsafe()
                return emitting.when_open(sleep_loop)

            return _Suspend(next_pull)

        return _Gen(body)

    return Stream(transform_pull(self._channel, build))


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
        tokens = units
        stamp = clock.now_nanos_unsafe()

        def loop(chunk: Chunk) -> AnyEffect:
            def weighed(weight: float) -> AnyEffect:
                nonlocal tokens, stamp
                now = clock.now_nanos_unsafe()
                total = _refilled(tokens, now - stamp, period_ns, units)
                available = cap if total < 0 else min(total, cap)
                if weight <= available:
                    tokens = available - weight
                    stamp = now
                    return _Succeed(chunk)
                return _FlatMap(pull, loop)

            return _FlatMap(cost(chunk), weighed)

        return _FlatMap(pull, loop)

    return Stream(
        transform_pull(self._channel, lambda pull, _: Clock().map(lambda c: with_clock(pull, c)))
    )


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
