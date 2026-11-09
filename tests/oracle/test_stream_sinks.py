"""Ports of Effect's ``Stream.test.ts``: the sink titles of ``error
handling``, and the ``transduce``, ``aggregateWithin``, ``tapSink`` and
``peel`` sections.

Each test's docstring is the Effect test title. Effect's inclusive
``Stream.range(a, b)`` is ``stream.range(a, b)``,
``Stream.catch`` / ``Sink.catch`` are ``catch_all``, durations are
seconds and the test clock's times are seconds.

Adapted, with the reason:

- "groupedWithin normalizes the chunk size" passes ``-1``, ``0``, ``1``
  and ``2`` where Effect passes ``NaN`` and fractions: ``chunk_size`` is an
  ``int``.
- "groupedWithin starts each window at its first element" reads the clock
  in seconds and compares milliseconds.

Not ported:

- The commented-out "leftover handling" title: it needs
  ``Sink.foldWeighted``, which v4 does not have.
"""

from collections.abc import Generator
from typing import Any, Never

import pyfect as fx
from pyfect import cause, schedule, sink, stream, testing
from pyfect.cause import Cause
from pyfect.clock import current_time_millis
from pyfect.duration import Seconds
from pyfect.exit import Exit
from pyfect.option import Some
from pyfect.queue import Queue
from pyfect.sink import Sink
from pyfect.stream import Stream

type Gen[A] = Generator[fx.Effect[Any, Any, Any], Any, A]


def _stream_error() -> Stream[int, str]:
    return stream.make(1, 2).concat(stream.fail("StreamError"))


def _sink_error(n: int) -> fx.Effect[None, str]:
    return fx.fail("SinkError") if n > 10 else fx.void


# --- error handling -------------------------------------------------------------------


@testing.effect
def test_run_upstream_failures_bypass_sink_error_handlers():
    """run - upstream failures bypass sink error handlers"""
    failing = sink.for_each(_sink_error)
    sinks: list[Sink[object, int, object, object]] = [
        failing.map_error(lambda error: {"mapped": error}),
        failing.catch_all(lambda error: fx.succeed({"recovered": error})),
        failing.catch_cause(lambda c: fx.succeed({"recovered": c})),
        failing.or_else(lambda error: sink.succeed({"fallback": error})),
    ]
    exits = yield from fx.for_each(sinks, lambda s: _stream_error().run(s).exit())
    assert exits == [fx.exit.fail("StreamError")] * len(sinks)


@testing.effect
def test_run_sink_on_exit_observes_interruption_on_upstream_failure():
    """run - sink onExit observes interruption on upstream failure"""
    events: list[object] = []

    def record(event: object) -> fx.Effect[None]:
        return fx.sync(lambda: events.append(event))

    observed = sink.drain.ensuring(record("ensuring")).on_exit(record)
    ex = yield from _stream_error().run(observed).exit()
    testing.assert_exit_failure(ex, cause.fail("StreamError"))
    assert events == ["ensuring", fx.exit.interrupt()]


@testing.effect
def test_pipe_through_upstream_failures_bypass_sink_error_handlers():
    """pipeThrough - upstream failures bypass sink error handlers"""

    def recover(c: Cause[str]) -> fx.Effect[dict[str, Cause[str]]]:
        return fx.succeed({"recovered": c})

    piped = _stream_error().pipe_through(sink.for_each(_sink_error).catch_cause(recover))
    ex = yield from piped.run_collect().exit()
    testing.assert_exit_failure(ex, cause.fail("StreamError"))


# --- transduce ------------------------------------------------------------------------


def _add(acc: int, n: int) -> int:
    return acc + n


@testing.effect
def test_transduce_no_remainder():
    """no remainder"""
    reducer = sink.reduce_while(lambda: 100, lambda n: n % 2 == 0, _add)
    assert (yield from stream.make(1, 2, 3, 4).transduce(reducer).run_collect()) == [101, 105, 104]


@testing.effect
def test_transduce_with_a_sink_that_always_signals_more():
    """with a sink that always signals more"""
    reducer = sink.reduce_while(lambda: 0, lambda _: True, _add)
    assert (yield from stream.make(1, 2, 3).transduce(reducer).run_collect()) == [6]


@testing.effect
def test_transduce_propagates_scope_error():
    """propagates scope error"""
    result = yield from stream.make(1, 2, 3).transduce(sink.fail("Woops")).run_collect().result()
    testing.assert_failure(result, "Woops")


# --- aggregateWithin --------------------------------------------------------------------


@testing.effect
def test_aggregate_upstream_failures_bypass_sink_error_handlers():
    """upstream failures bypass sink error handlers"""
    mapped = sink.for_each(_sink_error).map_error(lambda error: {"mapped": error})
    ex = yield from _stream_error().aggregate(mapped).run_collect().exit()
    testing.assert_exit_failure(ex, cause.fail("StreamError"))


@testing.effect
def test_aggregate_within_does_not_step_the_schedule_while_upstream_is_idle():
    """does not step the schedule while upstream is idle"""
    steps = 0

    def count_step(_: object) -> fx.Effect[None]:
        def bump() -> None:
            nonlocal steps
            steps += 1

        return fx.sync(bump)

    policy = schedule.spaced("10 millis").tap(count_step)
    idle: Stream[int] = stream.never
    fiber = yield from (
        idle.aggregate_within(sink.take(25), policy).run_drain().fork(start_immediately=True)
    )
    yield from testing.adjust("1 second")
    assert steps == 0
    yield from fiber.interrupt()


@testing.effect
def test_aggregate_within_schedule_exhaustion_drains_sink_leftovers_without_pulling_more():
    """schedule exhaustion drains sink leftovers without pulling more upstream"""
    pulls = 0

    def pull_more() -> int:
        nonlocal pulls
        pulls += 1
        return pulls

    def yield_batch(batch: list[int]) -> fx.Effect[list[int]]:
        return fx.yield_now().as_(batch)

    taking: Sink[list[int], int, int] = sink.take(2)
    result = yield from (
        stream.make(1, 2, 3, 4, 5)
        .concat(stream.from_effect(fx.sync(pull_more)))
        .aggregate_within(taking.map_effect(yield_batch), schedule.forever.up_to(times=0))
        .run_collect()
    )
    assert pulls == 0
    assert result == [[1, 2], [3, 4], [5]]


@testing.effect
def test_grouped_within_starts_each_window_at_its_first_element():
    """groupedWithin starts each window at its first element"""
    queue: Queue[int, Never] = yield from Queue[int].unbounded()
    batches: list[tuple[float, list[int]]] = []

    def record(batch: list[int]) -> fx.Effect[None]:
        return current_time_millis().map(lambda at: batches.append((round(at), batch)))

    yield from (
        stream.from_queue(queue)
        .grouped_within(10, "100 millis")
        .run_for_each(record)
        .fork(start_immediately=True)
    )
    yield from testing.adjust("1030 millis")
    yield from queue.offer(1)
    yield from testing.adjust("50 millis")
    yield from queue.offer(2)
    yield from testing.adjust("1 second")
    yield from queue.offer(3)
    yield from testing.adjust("100 millis")
    assert batches == [(1130, [1, 2]), (2180, [3])]


@testing.effect
def test_grouped_within_does_not_emit_empty_arrays_when_upstream_is_idle():
    """groupedWithin does not emit empty arrays when upstream is idle"""
    idle: Stream[int] = stream.never
    fiber = yield from (
        idle.grouped_within(25, "50 millis").take(5).run_collect().fork(start_immediately=True)
    )
    yield from testing.adjust("1 second")
    assert fiber.poll_unsafe() is None


@testing.effect
def test_grouped_within_normalizes_the_chunk_size():
    """groupedWithin normalizes the chunk size"""
    results = yield from fx.for_each(
        [-1, 0, 1, 2], lambda n: stream.make(1, 2, 3).grouped_within(n, "1 hour").run_collect()
    )
    assert results == [
        [[1], [2], [3]],
        [[1], [2], [3]],
        [[1], [2], [3]],
        [[1, 2], [3]],
    ]


@testing.effect
def test_grouped_within_flushes_final_partial_batch_on_upstream_end():
    """groupedWithin flushes final partial batch on upstream end without waiting for the schedule"""
    result = yield from stream.make(1, 2, 3, 4, 5).grouped_within(3, "1 second").run_collect()
    assert result == [[1, 2, 3], [4, 5]]


@testing.effect
def test_grouped_within_flushes_partial_batch_when_the_schedule_elapses_while_idle():
    """groupedWithin flushes partial batch when the schedule elapses while upstream is idle"""
    fiber = yield from (
        stream.make(1, 2, 3, 4, 5)
        .concat(stream.never)
        .grouped_within(3, "1 second")
        .take(2)
        .run_collect()
        .fork(start_immediately=True)
    )
    yield from testing.adjust("1 second")
    assert (yield from fiber.join()) == [[1, 2, 3], [4, 5]]


@testing.effect
def test_aggregate_within_simple_example():
    """simple example"""

    def step(state: tuple[list[int], bool], curr: int) -> fx.Effect[tuple[list[int], bool]]:
        return fx.succeed(([curr, *state[0]], curr == 1))

    def start() -> tuple[list[int], bool]:
        return ([], True)

    folding = sink.fold(start, lambda state: state[1], step)
    result = yield from (
        stream.make(1, 1, 1, 1, 2, 2)
        .aggregate_within(folding.map(lambda state: state[0]), schedule.spaced(Seconds(30 * 60)))
        .run_collect()
    )
    assert result == [[2, 1, 1, 1, 1], [2]]


@testing.effect
def test_aggregate_within_fails_fast():
    """fails fast"""
    queue: Queue[int, Never] = yield from Queue[int].unbounded()

    def offer(n: int) -> fx.Effect[bool, str]:
        failing: fx.Effect[None, str] = fx.fail("Boom") if n == 6 else fx.void
        return failing.and_then(queue.offer(n))

    def ignore(_: None, _n: int) -> fx.Effect[None]:
        return fx.void

    yield from (
        stream.range(1, 9)
        .tap(offer)
        .aggregate_within(sink.fold_until(lambda: None, 5, ignore), schedule.forever)
        .run_drain()
        .catch_all(lambda _: fx.void)
    )
    result = yield from queue.take_all()
    yield from queue.shutdown()
    assert result == [1, 2, 3, 4, 5]


@testing.effect
def test_aggregate_within_error_propagation_1():
    """error propagation #1"""
    error = RuntimeError("Boom")
    ex = yield from (
        stream.make(1, 1, 1, 1)
        .aggregate_within(sink.die(error), schedule.spaced(Seconds(30 * 60)))
        .run_collect()
        .exit()
    )
    assert ex == fx.exit.die(error)


@testing.effect
def test_aggregate_within_error_propagation_2():
    """error propagation #2"""
    error = RuntimeError("Boom")

    def step(_: list[int], _n: int) -> fx.Effect[list[int]]:
        return fx.die(error)

    folding = sink.fold(list[int], lambda _: True, step)
    ex = yield from (
        stream.make(1, 1)
        .aggregate_within(folding, schedule.spaced(Seconds(30 * 60)))
        .run_collect()
        .exit()
    )
    assert ex == fx.exit.die(error)


@testing.effect
def test_aggregate_within_interruption_propagation_1():
    """interruption propagation #1"""
    latch = yield from fx.Deferred[None].make()
    interrupted = yield from fx.Ref.make(False)

    def step(acc: list[int], curr: int) -> fx.Effect[list[int]]:
        if curr == 1:
            acc.append(curr)
            return fx.succeed(acc)
        return latch.succeed(None).and_then(fx.never).on_interrupt(interrupted.set(True))

    folding = sink.fold(list[int], lambda _: True, step)
    fiber = yield from (
        stream.make(1, 1, 2)
        .aggregate_within(folding, schedule.spaced(Seconds(30 * 60)))
        .run_collect()
        .fork_scoped()
    )
    yield from latch.wait()
    yield from fiber.interrupt()
    assert (yield from interrupted.get()) is True


@testing.effect
def test_aggregate_within_interruption_propagation_2():
    """interruption propagation #2"""
    interrupted = yield from fx.Ref.make(False)
    waiting: Sink[Never] = sink.from_effect(fx.never.on_interrupt(interrupted.set(True)))
    fiber = yield from (
        stream.make(1, 1, 2)
        .aggregate_within(waiting, schedule.spaced(Seconds(30 * 60)))
        .run_collect()
        .fork_scoped(start_immediately=True)
    )
    yield from fiber.interrupt()
    assert (yield from interrupted.get()) is True


# --- tapSink -----------------------------------------------------------------------------


@testing.effect
def test_tap_sink_sink_that_is_done_after_stream():
    """sink that is done after stream"""
    ref = yield from fx.Ref.make(0)

    def add(i: int) -> fx.Effect[None]:
        return ref.update(lambda n: i + n)

    adding = sink.for_each(add)
    result = yield from stream.make(1, 1, 2, 3, 5, 8).tap_sink(adding).run_collect()
    assert (yield from ref.get()) == 20
    assert result == [1, 1, 2, 3, 5, 8]


@testing.effect
def test_tap_sink_sink_that_is_done_before_stream():
    """sink that is done before stream"""
    ref = yield from fx.Ref.make(0)
    taking: Sink[list[int], int, int] = sink.take(3)
    summing = taking.map(sum).map_effect(lambda i: ref.update(lambda n: n + i))
    result = yield from stream.make(1, 1, 2, 3, 5, 8).rechunk(1).tap_sink(summing).run_collect()
    assert (yield from ref.get()) == 4
    assert result == [1, 1, 2, 3, 5, 8]


@testing.live
def test_tap_sink_sink_finishing_during_an_upstream_pull_still_lets_the_stream_complete():
    """sink finishing during an upstream pull still lets the stream complete"""
    started = yield from fx.Deferred[None].make()
    finished = yield from fx.Deferred[None].make()

    def source_body() -> Gen[int]:
        yield started.succeed(None)
        yield finished.wait()
        # Let the sink finish before the suspended upstream pull returns.
        yield fx.yield_now()
        return 1

    source = stream.from_effect(fx.gen(source_body))
    finishing = sink.from_effect(started.wait().and_then(finished.succeed(None)))
    result = yield from source.tap_sink(finishing).run_collect().timeout_option("1 second")
    assert result == Some([1])


@testing.effect
def test_tap_sink_sink_that_fails_before_stream():
    """sink that fails before stream"""
    result = yield from stream.make(1, 2, 3).tap_sink(sink.fail("error")).run_collect().flip()
    assert result == "error"


@testing.effect
def test_tap_sink_sink_that_fails_after_end_of_stream():
    """sink that fails after end-of-stream"""
    collecting: Sink[list[int], int] = sink.collect()
    failing = collecting.map_effect(lambda _: fx.fail("sink-end-failure"))
    ex = yield from stream.make(1).tap_sink(failing).run_collect().exit()
    assert ex == fx.exit.fail("sink-end-failure")


@testing.effect
def test_tap_sink_does_not_read_ahead():
    """does not read ahead"""
    ref = yield from fx.Ref.make(0)

    def add(i: int) -> fx.Effect[None]:
        return ref.update(lambda n: i + n)

    adding = sink.for_each(add)
    yield from (
        stream.make(1, 2, 3, 4, 5).rechunk(1).forever().tap_sink(adding).take(3).run_drain()
    )
    assert (yield from ref.get()) == 6


# --- peel --------------------------------------------------------------------------------


@testing.effect
def test_peel():
    """peel"""
    taking: Sink[list[int], int, int] = sink.take(3)

    def body() -> Gen[tuple[list[int], list[int]]]:
        peeled, rest = yield stream.from_arrays([1, 2, 3], [4, 5, 6]).peel(taking)
        return (peeled, (yield rest.run_collect()))

    peeled, rest = yield from fx.scoped(fx.gen(body))
    assert peeled == [1, 2, 3]
    assert rest == [4, 5, 6]


@testing.effect
def test_peel_keeps_the_sinks_leftovers_in_the_remaining_stream():
    """keeps the sink's leftovers in the remaining stream"""
    taking: Sink[list[int], int, int] = sink.take(2)

    def body() -> Gen[None]:
        peeled, rest = yield stream.make(1, 2, 3, 4).peel(taking)
        assert peeled == [1, 2]
        assert (yield rest.run_collect()) == [3, 4]

    yield from fx.scoped(fx.gen(body))


@testing.effect
def test_peel_propagates_errors():
    """peel - propagates errors"""

    def append(acc: tuple[int, ...], n: int) -> fx.Effect[tuple[int, ...]]:
        return fx.succeed((*acc, n))

    failing: Stream[int, str] = stream.from_effect_repeat(fx.fail("fail"))
    folding = sink.fold(tuple[int, ...], lambda _: True, append)
    ex: Exit[Any, str] = yield from fx.scoped(failing.peel(folding).exit())
    assert ex == fx.exit.fail("fail")


@testing.effect
def test_peel_upstream_failures_bypass_sink_error_handlers():
    """peel - upstream failures bypass sink error handlers"""
    mapped = sink.for_each(_sink_error).map_error(lambda error: {"mapped": error})
    ex = yield from fx.scoped(_stream_error().peel(mapped).exit())
    testing.assert_exit_failure(ex, cause.fail("StreamError"))
