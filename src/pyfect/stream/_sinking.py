"""The work behind ``Stream``'s sink methods: ``run``, ``transduce``,
``pipe_through``, ``tap_sink``, ``peel`` and ``aggregate_within``.

A stream's own failures reach a sink as hidden defects and are restored
once the sink has exited (``run_sink``), so no sink error handler sees
them.
"""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from collections.abc import Generator
from typing import Any

from pyfect import channel
from pyfect._core import Effect, _FailCause, _Gen, _Succeed, _Suspend
from pyfect.cause import Cause, fail
from pyfect.channel._upstream import restore_upstream_failure, upstream_failure_to_defect
from pyfect.clock import Clock, ClockService, sleep
from pyfect.effect import never
from pyfect.exit import Exit, Failure
from pyfect.latch import Latch
from pyfect.option import Option, Some
from pyfect.pull import catch_done
from pyfect.queue import Queue
from pyfect.queue import _state as queue_state
from pyfect.schedule import Schedule
from pyfect.schedule._model import Continue, to_step
from pyfect.scope import CloseableScope, fork_in, scoped_with
from pyfect.sink._sink import AnySink, End
from pyfect.sink._steps import ENDED
from pyfect.stream._base import AnyStream
from pyfect.stream._stream import Stream, transform_pull, transform_pull_bracket

type AnyEffect = Effect[Any, Any, Any]
type Chunk = tuple[Any, ...]
type AnyStream_ = Stream[Any, Any, Any]
type AnyEnd = End[Any, Any]
type Channel_ = channel.Channel[Any, Any, Any, Any, Any, Any, Any]


def run_sink(sink: AnySink, upstream: AnyEffect, scope: CloseableScope) -> AnyEffect:
    """Run ``sink`` on ``upstream``; upstream failures bypass the sink's
    error handlers and are restored once the sink has exited."""
    return restore_upstream_failure(sink._transform(upstream_failure_to_defect(upstream), scope))


def run(self: AnyStream, sink: AnySink) -> AnyEffect:
    def consume(scope: CloseableScope) -> AnyEffect:
        built = self._channel.to_pull_scoped(scope)
        return built.flat_map(lambda pull: run_sink(sink, pull, scope)).map(_value)

    return scoped_with(consume)


def _value(end: AnyEnd) -> Any:
    return end[0]


def transduce(self: AnyStream, sink: AnySink) -> AnyStream_:
    def build(upstream: AnyEffect, scope: CloseableScope) -> AnyEffect:
        stopped: AnyEffect | None = None
        leftover: Chunk | None = None

        def next_chunk() -> AnyEffect:
            nonlocal leftover
            if leftover is not None:
                chunk, leftover = leftover, None
                return _Succeed(chunk)
            return upstream

        def stop(error: object) -> AnyEffect:
            nonlocal stopped
            stopped = _FailCause(fail(error))
            return ENDED

        fed = _Suspend(next_chunk).catch_all(stop)

        def emit(end: AnyEnd) -> Chunk:
            nonlocal leftover
            leftover = end[1]
            return (end[0],)

        pull = _Suspend(lambda: sink._transform(fed, scope)).map(emit)
        return _Succeed(_Suspend(lambda: pull if stopped is None else stopped))

    return transform_pull(self, build)


def pipe_through(self: AnyStream, sink: AnySink) -> AnyStream_:
    from pyfect.sink import to_channel

    def leftovers(end: AnyEnd) -> Any:
        return channel.empty if end[1] is None else channel.succeed(end[1])

    piped: Any = self._channel.pipe_to_or_fail(to_channel(sink)).concat_with(leftovers)
    return Stream(piped)


def tap_sink(self: AnyStream, sink: AnySink) -> AnyStream_:
    def build(pull: AnyEffect, _scope: CloseableScope, forked: CloseableScope) -> AnyEffect:
        upstream_latch = Latch()
        sink_latch = Latch()
        chunk: Chunk | None = None
        sink_cause: Cause[Any] | None = None
        sink_done = False
        stream_done = False

        def hand_over() -> AnyEffect:
            nonlocal chunk
            if chunk is None:
                return ENDED
            taken, chunk = chunk, None
            if not stream_done:
                upstream_latch.close_unsafe()
            return sink_latch.open().as_(taken)

        sink_upstream = upstream_latch.when_open(_Suspend(hand_over))

        def sink_exited(ex: Exit[Any, Any]) -> AnyEffect:
            nonlocal sink_done, sink_cause
            sink_done = True
            if isinstance(ex, Failure):
                sink_cause = ex.cause
            return sink_latch.open()

        running = _Suspend(lambda: sink._transform(sink_upstream, forked)).on_exit(sink_exited)

        def offer(next_chunk: Chunk) -> AnyEffect:
            nonlocal chunk
            if sink_cause is not None:
                return _FailCause(sink_cause)
            if sink_done:
                return _Succeed(next_chunk)
            chunk = next_chunk
            sink_latch.close_unsafe()
            upstream_latch.open_unsafe()
            return sink_latch.wait().as_(next_chunk)

        def stream_ended(_: object) -> AnyEffect:
            nonlocal stream_done
            if sink_cause is not None:
                return _FailCause(sink_cause)
            if sink_done:
                return ENDED
            stream_done = True
            sink_latch.close_unsafe()
            upstream_latch.open_unsafe()
            return sink_latch.wait().and_then(
                _Suspend(lambda: ENDED if sink_cause is None else _FailCause(sink_cause))
            )

        pull_and_offer = catch_done(pull.flat_map(offer), stream_ended)

        def next_pull() -> AnyEffect:
            if sink_cause is not None:
                return _FailCause(sink_cause)
            return pull if sink_done else pull_and_offer

        return fork_in(running, forked).as_(_Suspend(next_pull))

    return transform_pull_bracket(self, build)


def peel(self: AnyStream, sink: AnySink) -> AnyEffect:
    from pyfect.stream._constructors import empty, from_iterable
    from pyfect.stream._stream import from_pull

    def body() -> Generator[AnyEffect, Any, tuple[Any, AnyStream_]]:
        failed = False
        original = yield self._channel.to_pull()

        def mark(cause: Cause[Any]) -> AnyEffect:
            nonlocal failed
            failed = True
            return _FailCause(cause)

        pull = original.catch_cause(mark)
        value, leftover = yield scoped_with(lambda scope: run_sink(sink, pull, scope))
        rest: AnyStream_ = empty if failed else from_pull(_Succeed(original))
        if leftover is not None:
            rest = from_iterable(leftover).concat(rest)
        return (value, rest)

    return _Gen(body)


_SCHEDULE_STEP = object()
"""What the schedule puts in the buffer to end the current aggregation."""


def aggregate_within(
    self: AnyStream, sink: AnySink, policy: Schedule[Any, Any, Any, Any]
) -> AnyStream_:
    def transform(_upstream: Any, scope: CloseableScope, forked: CloseableScope) -> AnyEffect:
        def body() -> Generator[AnyEffect, Any, AnyEffect]:
            pull = yield self._channel.to_pull_scoped(scope)
            pull_latch = Latch()
            buffer: Queue[Any, Any] = Queue(0)

            def offer(chunk: Chunk) -> AnyEffect:
                pull_latch.close_unsafe()
                return buffer.offer(chunk)

            producer = pull_latch.when_open(pull).flat_map(offer).forever()
            yield fork_in(producer.catch_cause(buffer.fail_cause), forked)

            # The schedule's clock leaves out the time between aggregations.
            clock: ClockService = yield Clock()
            step = yield to_step(policy)
            has_input = Latch()
            schedule_time = clock.now_nanos_unsafe()
            opened_at = 0
            last_output: Option[Any] = None
            leftover: Chunk | None = None

            def on_input(chunk: Chunk) -> AnyEffect:
                nonlocal opened_at
                if has_input.open_unsafe():
                    opened_at = clock.now_nanos_unsafe()
                return _Succeed(chunk)

            def decided(decision: object) -> AnyEffect:
                if isinstance(decision, Continue):
                    return sleep(decision.delay).and_then(buffer.offer(_SCHEDULE_STEP))
                # End input so the sink drains its leftovers without pulling
                # more upstream.
                return buffer.end()

            step_to_buffer = (
                has_input.wait()
                .flat_map(lambda _: step(schedule_time / 1_000_000, last_output))
                .flat_map(decided)
                .and_then(never)
            )

            def take_input(item: Any) -> AnyEffect:
                return ENDED if item is _SCHEDULE_STEP else on_input(item)

            def next_input() -> AnyEffect:
                nonlocal leftover
                if leftover is not None:
                    chunk, leftover = leftover, None
                    return on_input(chunk)
                if isinstance(buffer._state, queue_state.Open):
                    pull_latch.open_unsafe()
                return buffer.take().flat_map(take_input)

            sink_upstream = _Suspend(next_input)

            def emit(end: AnyEnd) -> AnyEffect:
                nonlocal schedule_time, last_output, leftover
                if has_input.is_open():
                    schedule_time += clock.now_nanos_unsafe() - opened_at
                elif isinstance(buffer._state, queue_state.Done):
                    return ENDED
                last_output = Some(end[0])
                leftover = end[1]
                return _Succeed((end[0],))

            def next_pull() -> AnyEffect:
                state = buffer._state
                if isinstance(state, queue_state.Done) and leftover is None:
                    return _FailCause(state.cause)
                has_input.close_unsafe()
                aggregated = _Suspend(lambda: run_sink(sink, sink_upstream, scope)).flat_map(emit)
                if isinstance(state, queue_state.Open):
                    return aggregated.race_first(step_to_buffer)
                return aggregated

            return _Suspend(next_pull)

        return _Gen(body)

    built: Channel_ = channel.from_transform_bracket(transform)
    return Stream(built)
