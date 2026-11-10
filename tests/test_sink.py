"""Sink behaviours beyond ``Sink.test.ts``, each printed by Effect under
Node first: the folds, leftovers through ``map_leftover`` /
``ignore_leftover`` / ``pipe_through`` / ``transduce``, ``or_else`` on the
rest of the input, the channel round trip, services, ``unwrap``, ``make``,
``from_queue``, ``summarized``, ``aggregate`` and ``tap_sink``."""

from collections.abc import Generator
from typing import Any, Never

import pyfect as fx
from pyfect import cause, schedule, sink, stream, testing
from pyfect.cause import Cause
from pyfect.context import Tag
from pyfect.duration import Duration, seconds
from pyfect.option import Option, Some
from pyfect.queue import Done, Queue
from pyfect.sink import End, Sink
from pyfect.stream import Stream

type Gen[A] = Generator[fx.Effect[Any, Any, Any], Any, A]


def _chunks() -> Stream[int]:
    return stream.from_arrays([1, 2], [3, 4, 5], [6])


def _below(limit: int):
    def below(n: int) -> bool:
        return n < limit

    return below


def _above(limit: int):
    def above(n: int) -> bool:
        return n > limit

    return above


def _with_end[A, L](s: Sink[A, int, L]) -> Sink[End[A, L], int]:
    return s.map_end(lambda end: (end, None))


@testing.effect
def test_every_stops_at_the_first_failing_item_and_leaves_the_rest_over():
    assert (yield from _chunks().run(sink.every(_below(3)))) is False
    end = yield from _chunks().run(_with_end(sink.every(_below(4))))
    assert end == (False, (5,))


@testing.effect
def test_some_and_find_stop_at_the_first_match():
    assert (yield from _chunks().run(sink.some(_above(3)))) is True
    assert (yield from _chunks().run(_with_end(sink.find(_above(3))))) == (Some(4), (5,))
    assert (yield from _chunks().run(sink.last())) == Some(6)


@testing.effect
def test_count_and_sum():
    assert (yield from _chunks().run(sink.count)) == 6
    assert (yield from _chunks().run(sink.sum())) == 21


def _count_items(acc: int, chunk: tuple[int, ...]) -> fx.Effect[int]:
    return fx.succeed(acc + len(chunk))


@testing.effect
def test_fold_array_stops_after_the_chunk_that_fails_the_predicate():
    assert (yield from _chunks().run(sink.fold_array(lambda: 0, _below(5), _count_items))) == 5
    transduced = (
        yield from _chunks()
        .transduce(sink.fold_array(lambda: 0, _below(3), _count_items))
        .run_collect()
    )
    assert transduced == [5, 1]
    reduced = sink.reduce_while_array_effect(lambda: 0, _below(5), _count_items)
    assert (yield from _chunks().run(reduced)) == 5


@testing.effect
def test_reduce_effect_and_for_each_while():
    def add(acc: int, n: int) -> fx.Effect[int]:
        return fx.succeed(acc + n)

    assert (yield from _chunks().run(sink.reduce_effect(lambda: 0, add))) == 21
    seen: list[int] = []

    def record(n: int) -> fx.Effect[bool]:
        def go() -> bool:
            seen.append(n)
            return n < 3

        return fx.sync(go)

    yield from _chunks().run(sink.for_each_while(record))
    assert seen == [1, 2, 3]


@testing.effect
def test_map_input_maps_each_item():
    collecting: Sink[list[str], str] = sink.collect()
    assert (yield from _chunks().run(collecting.map_input(str))) == ["1", "2", "3", "4", "5", "6"]


@testing.effect
def test_leftovers_through_map_leftover_ignore_leftover_and_pipe_through():
    taking: Sink[list[int], int, int] = sink.take(3)
    tens = taking.map_leftover(lambda n: n * 10)
    assert (yield from _chunks().run(_with_end(tens))) == ([1, 2, 3], (40, 50))
    assert (yield from _chunks().pipe_through(tens).run_collect()) == [40, 50]
    assert (yield from _chunks().pipe_through(taking.ignore_leftover()).run_collect()) == []


@testing.effect
def test_or_else_goes_on_with_the_rest_of_the_input():
    def recover(error: str) -> Sink[tuple[str, list[int]], int]:
        collecting: Sink[list[int], int] = sink.collect()
        return collecting.map(lambda items: (error, items))

    def failing(_: object) -> Sink[None, int, Any, str]:
        return sink.fail("x")

    first: Sink[list[int], int, int] = sink.take(1)
    result = yield from _chunks().run(first.flat_map(failing).or_else(recover))
    assert result == ("x", [3, 4, 5, 6])
    collecting: Sink[list[int], int, int] = sink.collect()
    after_end = yield from _chunks().run(collecting.flat_map(failing).or_else(recover))
    assert after_end == ("x", [])


@testing.effect
def test_catch_cause_recovers_a_sink_failure():
    def recover(c: Cause[str]) -> fx.Effect[Cause[str]]:
        return fx.succeed(c)

    assert (yield from _chunks().run(sink.fail("x").catch_cause(recover))) == cause.fail("x")


@testing.effect
def test_from_queue_offers_the_input_and_ends_the_queue():
    queue: Queue[int, Done] = yield from Queue[int, Done].unbounded()
    yield from _chunks().run(sink.from_queue(queue))
    assert (yield from queue.collect()) == [1, 2, 3, 4, 5, 6]


@testing.effect
def test_summarized_runs_the_summary_before_and_after():
    ref = yield from fx.Ref.make(0)
    collecting: Sink[list[int], int] = sink.collect()
    summary = ref.update_and_get(lambda n: n + 1)
    result = yield from _chunks().run(collecting.summarized(summary, lambda a, b: (a, b)))
    assert result == ([1, 2, 3, 4, 5, 6], (1, 2))


@testing.effect
def test_a_sink_survives_a_round_trip_through_a_channel():
    taking: Sink[list[int], int, int] = sink.take(4)
    assert (yield from _chunks().run(sink.from_channel(sink.to_channel(taking)))) == [1, 2, 3, 4]


class _Number(Tag[int]):
    pass


@testing.effect
def test_provide_service_and_provide_context():
    needing = sink.from_effect(_Number())
    assert (yield from _chunks().run(needing.pipe(sink.provide_service(_Number, 7)))) == 7
    context = fx.Context.make(_Number, 8)
    assert (yield from _chunks().run(needing.pipe(sink.provide_context(context)))) == 8


@testing.effect
def test_unwrap_and_make():
    taking: Sink[list[int], int, int] = sink.take(2)
    assert (yield from _chunks().run(sink.unwrap(fx.succeed(taking)))) == [1, 2]

    def first_three(source: Stream[int]) -> fx.Effect[list[int]]:
        return source.take(3).run_collect()

    assert (yield from _chunks().run(sink.make(first_three))) == [1, 2, 3]


@testing.effect
def test_transduce_runs_the_sink_until_the_input_ends():
    first: Sink[Option[int], int, int] = sink.head()
    heads = yield from _chunks().transduce(first).run_collect()
    assert heads == [Some(1), Some(2), Some(3), Some(4), Some(5), Some(6), None]
    until_even = yield from _chunks().transduce(sink.take_until(lambda n: n % 2 == 0)).run_collect()
    assert until_even == [[1, 2], [3, 4], [5, 6], []]
    failing: Stream[int, str] = stream.make(1, 2, 3).concat(stream.fail("boom"))
    ex = yield from failing.transduce(sink.take(2)).run_collect().exit()
    testing.assert_exit_failure(ex, cause.fail("boom"))


@testing.effect
def test_flat_map_puts_its_pending_leftovers_after_the_next_sinks():
    taking: Sink[list[int], int, int] = sink.take(2)

    def leave_99(items: list[int]) -> Sink[list[int], object, int]:
        return sink.succeed(items, (99,))

    result = yield from _chunks().transduce(taking.flat_map(leave_99)).take(4).run_collect()
    assert result == [[1, 2], [99, 3], [99, 4], [99, 5]]


@testing.effect
def test_peel_with_a_sink_that_reads_everything_leaves_an_empty_stream():
    collecting: Sink[list[int], int, int] = sink.collect()

    def body() -> Gen[tuple[list[int], list[int]]]:
        peeled, rest = yield stream.make(1, 2).peel(collecting)
        return (peeled, (yield rest.run_collect()))

    assert (yield from fx.scoped(fx.gen(body))) == ([1, 2], [])


@testing.effect
def test_aggregate_runs_the_sink_until_the_input_ends():
    def add(acc: int, n: int) -> fx.Effect[int]:
        return fx.succeed(acc + n)

    pairs = sink.fold_until(lambda: 0, 2, add)
    assert (yield from stream.make(1, 2, 3, 4, 5).aggregate(pairs).run_collect()) == [3, 7, 5]


@testing.effect
def test_aggregate_ends_a_run_at_each_schedule_step_while_the_sink_waits():
    # With `schedule.forever`, a run that has input and waits for more ends
    # at the schedule's next step (under the TestClock, as Effect's tests).
    assert (yield from _chunks().aggregate(sink.collect()).run_collect()) == [
        [1, 2],
        [3, 4, 5],
        [6],
    ]
    taking: Sink[list[int], int, int] = sink.take(2)
    assert (yield from _chunks().aggregate(taking).run_collect()) == [[1, 2], [3, 4], [5], [6]]
    summed = stream.range(1, 10, chunk_size=3).aggregate(sink.sum())
    assert (yield from summed.run_collect()) == [6, 15, 24, 10]


@testing.effect
def test_tap_sink_with_a_sink_that_stops_early_lets_the_stream_go_on():
    taken: list[list[int]] = []
    taking: Sink[list[int], int, int] = sink.take(2)
    recording = taking.map_effect(lambda items: fx.sync(lambda: taken.append(items)))
    assert (yield from _chunks().tap_sink(recording).run_collect()) == [1, 2, 3, 4, 5, 6]
    assert taken == [[1, 2]]


@testing.effect
def test_timed_measures_the_run_in_seconds():
    assert (yield from _chunks().run(sink.timed)) == 0


class _CountedPulls:
    """A stream writing ``(1,)`` and then ending, that counts its pulls."""

    def __init__(self) -> None:
        self.pulls = 0

        def pull() -> fx.Effect[tuple[int, ...], Done]:
            self.pulls += 1
            return fx.succeed((1,)) if self.pulls == 1 else fx.fail(Done())

        self.stream: Stream[int] = stream.from_pull(fx.succeed(fx.suspend(pull)))


def _drain_then_fail() -> Sink[None, int, Never, str]:
    return sink.drain.flat_map(lambda _: sink.fail("x"))


@testing.effect
def test_flat_map_and_or_else_do_not_pull_an_upstream_that_has_ended():
    counted = _CountedPulls()
    first: Sink[list[int], int] = sink.collect()
    second: Sink[list[int], int] = sink.collect()
    both = first.flat_map(lambda a: second.map(lambda b: (a, b)))
    assert (yield from counted.stream.run(both)) == ([1], [])
    assert counted.pulls == 2

    counted = _CountedPulls()
    failing = _drain_then_fail()
    rest: Sink[list[int], int] = sink.collect()
    assert (yield from counted.stream.run(failing.or_else(lambda _: rest))) == []
    assert counted.pulls == 2


@testing.effect
def test_peel_with_an_ended_upstream_does_not_pull_it_again():
    counted = _CountedPulls()

    def body() -> Gen[tuple[list[int], list[int]]]:
        first: Sink[list[int], int, int] = sink.collect()
        value, rest = yield counted.stream.peel(first)
        return (value, (yield rest.run_collect()))

    assert (yield from fx.scoped(fx.gen(body))) == ([1], [])
    assert counted.pulls == 2


@testing.effect
def test_reduce_while_array_effect_reads_nothing_when_the_initial_state_fails():
    calls = 0

    def add(state: int, chunk: tuple[int, ...]) -> fx.Effect[int]:
        nonlocal calls
        calls += 1
        return fx.succeed(state + len(chunk))

    reducing = sink.reduce_while_array_effect(lambda: 0, lambda s: s > 0, add)
    assert (yield from stream.make(1, 2).run(reducing)) == 0
    assert calls == 0


@testing.effect
def test_unwrap_closes_its_resources_when_the_sink_run_ends():
    log: list[str] = []

    def body() -> Gen[None]:
        built = fx.add_finalizer(lambda _: fx.sync(lambda: log.append("fin"))).as_(sink.count)
        counted = yield stream.make(1, 2).run(sink.unwrap(built))
        log.append(f"ran {counted}")

    yield from fx.scoped(fx.gen(body))
    assert log == ["fin", "ran 2"]


@testing.effect
def test_aggregate_within_leaves_the_idle_time_out_of_the_schedule_clock():
    seen: list[Duration] = []

    def record(meta: schedule.Metadata[Any, Any]) -> bool:
        seen.append(meta.elapsed)
        return True

    policy = schedule.spaced("1 second").while_(record)
    later = [stream.from_effect(fx.sleep("10 seconds").as_(n)) for n in (2, 3)]
    source = stream.make(1).concat(later[0]).concat(later[1])
    fiber = (
        yield from source.aggregate_within(sink.collect(), policy)
        .run_collect()
        .fork(start_immediately=True)
    )
    yield from testing.adjust("30 seconds")
    assert (yield from fiber.join()) == [[1], [2], [3]]
    assert seen == [seconds(0), seconds(1), seconds(2)]
