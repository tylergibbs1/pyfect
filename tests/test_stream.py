"""Stream core, constructors, sources and run functions, beyond the
``Stream.test.ts`` ports. Each expected value was printed by Effect's
``Stream`` under Node first (Python's exclusive ``range`` aside)."""

import asyncio
from collections.abc import AsyncGenerator, Generator
from dataclasses import replace
from typing import Any

import pytest

import pyfect as fx
from pyfect import schedule, stream, testing


def _chunks(s: stream.Stream[Any, Any, Any]) -> fx.Effect[list[Any], Any, Any]:
    return s.channel.run_collect()


def _first[A, E, R](s: stream.Stream[A, E, R], n: int) -> fx.Effect[list[A], E, R]:
    """The first ``n`` items (``Stream.take(n)`` and ``runCollect``)."""
    items: list[A] = []
    return s.run_for_each_while(lambda a: fx.sync(lambda: items.append(a) or len(items) < n)).as_(
        items
    )


# --- ranges and iterables ------------------------------------------------------------


@testing.effect
def test_range_leaves_its_end_out_as_python_does():
    assert (yield from stream.range(1, 3).run_collect()) == [1, 2, 3]
    assert (yield from stream.range(3, 2).run_collect()) == []
    assert (yield from _chunks(stream.range(0, 4, chunk_size=2))) == [(0, 1), (2, 3), (4,)]


@testing.effect
def test_run_count_and_run_sum_read_every_chunk():
    numbers = stream.range(1, 10, chunk_size=3)
    assert (yield from numbers.run_count()) == 10
    assert (yield from numbers.run_sum()) == 55
    assert (yield from stream.empty.run_sum()) == 0


@testing.effect
def test_a_list_is_read_when_the_stream_is_built():
    items = [1, 2]
    numbers = stream.from_iterable(items)
    items.append(3)
    assert (yield from numbers.run_collect()) == [1, 2]
    assert (yield from stream.from_iterable([]).run_collect()) == []


@testing.effect
def test_a_generator_is_read_once():
    def numbers() -> Generator[int]:
        yield from (1, 2, 3)

    once = stream.from_iterable(numbers())
    assert (yield from once.run_collect()) == [1, 2, 3]
    assert (yield from once.run_collect()) == []
    assert (yield from stream.from_iterable(numbers()).channel.run_drain()) is None


@testing.effect
def test_a_tuple_is_one_chunk_as_a_list_is():
    many = tuple(range(stream.DEFAULT_CHUNK_SIZE + 1))
    assert (yield from _chunks(stream.from_iterable(many))) == [many]
    assert (yield from _chunks(stream.from_iterable(iter((1, 2, 3)), chunk_size=2))) == [
        (1, 2),
        (3,),
    ]


@testing.effect
def test_from_arrays_skips_empty_arrays():
    assert (yield from _chunks(stream.from_arrays([1, 2], [], (3,)))) == [(1, 2), (3,)]


@testing.effect
def test_from_iterable_effect_writes_a_list_as_one_chunk():
    assert (yield from _chunks(stream.from_iterable_effect(fx.succeed([1, 2, 3])))) == [(1, 2, 3)]


@testing.effect
def test_from_iterable_effect_repeat_skips_empty_iterables():
    calls = 0

    def next_items() -> list[int]:
        nonlocal calls
        calls += 1
        return [calls, calls] if calls % 2 else []

    items = stream.from_iterable_effect_repeat(fx.sync(next_items))
    assert (yield from _first(items, 5)) == [1, 1, 3, 3, 5]


# --- unfolding -----------------------------------------------------------------------


@testing.effect
def test_unfold_ends_when_f_returns_none():
    def step(s: int) -> fx.Effect[tuple[int, int] | None]:
        return fx.succeed((s, s + 1) if s < 3 else None)

    assert (yield from stream.unfold(0, step).run_collect()) == [0, 1, 2]


@testing.effect
def test_iterate_is_endless():
    doubling = stream.iterate(1, lambda x: x * 2)
    assert (yield from _first(doubling, 5)) == [1, 2, 4, 8, 16]


@testing.effect
def test_paginate_writes_no_empty_chunks():
    def page(s: int) -> fx.Effect[tuple[list[int], fx.Option[int]]]:
        items = [] if s % 2 == 0 else [s, s]
        return fx.succeed((items, fx.Some(s + 1) if s < 5 else None))

    assert (yield from _chunks(stream.paginate(0, page))) == [(1, 1), (3, 3), (5, 5)]


@testing.effect
def test_paginate_keeps_a_state_that_is_none():
    def page(s: int | None) -> fx.Effect[tuple[list[int | None], fx.Option[int | None]]]:
        return fx.succeed(([s], fx.Some(None) if s == 0 else None))

    assert (yield from stream.paginate(0, page).run_collect()) == [0, None]


# --- effects and schedules ---------------------------------------------------------


@testing.effect
def test_from_effect_repeat_ends_when_the_effect_fails_with_done():
    calls = 0

    def pull() -> fx.Effect[int, fx.Done]:
        nonlocal calls
        calls += 1
        return fx.succeed(calls) if calls <= 3 else fx.fail(fx.Done())

    assert (yield from stream.from_effect_repeat(fx.suspend(pull)).run_collect()) == [1, 2, 3]


@testing.effect
def test_from_effect_drain_runs_the_effect_and_writes_nothing():
    out: list[int] = []
    assert (yield from stream.from_effect_drain(fx.sync(lambda: out.append(1))).run_collect()) == []
    assert out == [1]


@testing.effect
def test_from_schedule_writes_each_output_and_ends_when_the_schedule_stops():
    assert (yield from stream.from_schedule(schedule.recurs(3)).run_collect()) == [0, 1, 2]


@testing.effect
def test_from_effect_schedule_runs_the_effect_once_more_per_recurrence():
    calls = 0

    def count() -> int:
        nonlocal calls
        calls += 1
        return calls - 1

    assert (
        yield from stream.from_effect_schedule(fx.sync(count), schedule.recurs(2)).run_collect()
    ) == [0, 1, 2]


@testing.effect
def test_from_effect_schedule_gives_each_run_the_step_metadata():
    attempt = schedule.CurrentMetadata().map(lambda meta: meta.attempt)
    assert (yield from stream.from_effect_schedule(attempt, schedule.recurs(2)).run_collect()) == [
        0,
        1,
        2,
    ]


@testing.effect
def test_from_effect_schedule_steps_the_schedule_with_the_latest_value():
    calls = 0

    def count() -> int:
        nonlocal calls
        calls += 1
        return calls - 1

    numbers = schedule.forever.pipe(schedule.set_input_type(int)).passthrough()
    below_three = numbers.while_(lambda meta: meta.input < 3)
    items = stream.from_effect_schedule(fx.sync(count), below_three)
    assert (yield from _first(items, 10)) == [0, 1, 2, 3]


@testing.effect
def test_from_effect_schedule_gives_the_first_run_fresh_metadata():
    attempt = schedule.CurrentMetadata().map(lambda meta: meta.attempt)
    outer = replace(schedule.CurrentMetadata.default(), attempt=7)
    attempts = stream.from_effect_schedule(attempt, schedule.recurs(1)).run_collect()
    assert (yield from attempts.pipe(fx.provide_service(schedule.CurrentMetadata, outer))) == [0, 1]


@testing.effect
def test_from_effect_schedule_fails_with_the_first_failure():
    failing = stream.from_effect_schedule(fx.fail("e"), schedule.recurs(2))
    assert (yield from failing.run_collect().exit()) == fx.exit.fail("e")


@testing.effect
def test_tick_writes_at_once_then_after_each_interval():
    fiber = yield from _first(stream.tick(1), 3).fork()
    yield from testing.adjust(2)
    assert (yield from fiber.join()) == [None, None, None]


# --- queues, pubsubs and async iterables ------------------------------------------


@testing.effect
def test_from_queue_writes_everything_waiting_as_one_chunk():
    queue = yield from fx.Queue[int, fx.Done].unbounded()
    yield from queue.offer_all([1, 2, 3])
    yield from queue.end()
    assert (yield from _chunks(stream.from_queue(queue))) == [(1, 2, 3)]


@testing.effect
def test_from_pubsub_reads_what_was_published_before_a_shutdown():
    """Effect under Node gives ``[1, 2]``: the reader, woken by the publish,
    takes both messages before the shutdown goes on."""
    pubsub = yield from fx.PubSub[int].unbounded()
    reader = yield from stream.from_pubsub(pubsub).run_collect().fork()
    yield from fx.yield_now()
    yield from pubsub.publish_all([1, 2])
    yield from pubsub.shutdown()
    assert (yield from reader.join()) == [1, 2]


@testing.effect
def test_from_pubsub_take_replays_chunks_then_the_failure():
    pubsub = yield from fx.PubSub[fx.Take[int, str]].unbounded(replay=3)
    yield from pubsub.publish((1, 2))
    yield from pubsub.publish((3,))
    yield from pubsub.publish(fx.exit.fail("boom"))
    assert (yield from stream.from_pubsub_take(pubsub).run_collect().exit()) == fx.exit.fail("boom")


@testing.effect
def test_subscription_ref_changes_starts_with_the_current_value():
    ref = yield from fx.SubscriptionRef.make(5)
    assert (yield from _first(ref.changes(), 1)) == [5]


@testing.effect(asyncio=True)
def test_from_async_iterable_writes_each_item_as_a_chunk():
    async def numbers() -> AsyncGenerator[int]:
        for n in (1, 2, 3):
            await asyncio.sleep(0)
            yield n

    assert (yield from _chunks(stream.from_async_iterable(numbers(), repr))) == [(1,), (2,), (3,)]


# --- running -------------------------------------------------------------------------


def _two_chunks(log: list[str]) -> stream.Stream[int]:
    def make() -> fx.Effect[tuple[int, ...], fx.Done]:
        pulls = 0

        def pull() -> fx.Effect[tuple[int, ...], fx.Done]:
            nonlocal pulls
            pulls += 1
            log.append(f"pull{pulls}")
            return fx.succeed((pulls, pulls * 10)) if pulls <= 2 else fx.fail(fx.Done())

        return fx.suspend(pull)

    return stream.from_pull(fx.sync(make))


@testing.effect
def test_run_head_pulls_one_chunk():
    log: list[str] = []
    assert (yield from _two_chunks(log).run_head()) == fx.Some(1)
    assert log == ["pull1"]
    assert (yield from stream.empty.run_head()) is None


@testing.effect
def test_run_last_reads_to_the_end():
    assert (yield from _two_chunks([]).run_last()) == fx.Some(20)
    assert (yield from stream.empty.run_last()) is None


@testing.effect
def test_run_for_each_array_sees_each_chunk():
    seen: list[tuple[int, ...]] = []
    yield from stream.from_arrays([1, 2], [3]).run_for_each_array(
        lambda chunk: fx.sync(lambda: seen.append(chunk))
    )
    assert seen == [(1, 2), (3,)]


@testing.effect
def test_run_for_each_and_run_fold_effect_go_item_by_item():
    seen: list[int] = []
    numbers = stream.from_arrays([1, 2], [3])
    yield from numbers.run_for_each(lambda n: fx.sync(lambda: seen.append(n)))
    assert seen == [1, 2, 3]
    total = yield from numbers.run_fold_effect(lambda: 0, lambda acc, n: fx.succeed(acc * 10 + n))
    assert total == 123
    assert (yield from numbers.run_fold(lambda: "", lambda acc, n: acc + str(n))) == "123"


@testing.effect
def test_run_string_joins_the_strings():
    assert (yield from stream.make("a", "b", "c").run_string()) == "abc"


@testing.effect
def test_a_raising_fold_function_is_a_defect():
    error = ValueError("boom")

    def fold(_acc: int, _n: int) -> int:
        raise error

    assert (yield from stream.make(1).run_fold(lambda: 0, fold).exit()) == fx.exit.die(error)


@testing.effect
def test_to_pull_ends_with_done():
    pull = yield from stream.from_arrays([1], [2]).to_pull()
    assert (yield from pull) == (1,)
    assert (yield from pull) == (2,)
    assert isinstance((yield from pull.flip()), fx.Done)


# --- deferred and scoped streams -----------------------------------------------------


@testing.effect
def test_unwrap_releases_the_effect_resources_when_the_stream_ends():
    order: list[str] = []
    made = fx.acquire_release(
        fx.sync(lambda: order.append("acquire") or stream.make(1, 2)),
        lambda _s, _ex: fx.sync(lambda: order.append("release")),
    )
    assert (yield from stream.unwrap(made).run_collect()) == [1, 2]
    assert order == ["acquire", "release"]


@testing.effect
def test_suspend_builds_the_stream_each_run():
    builds = 0

    def build() -> stream.Stream[int]:
        nonlocal builds
        builds += 1
        return stream.succeed(builds)

    lazy = stream.suspend(build)
    assert builds == 0
    assert (yield from lazy.run_collect()) == [1]
    assert (yield from lazy.run_collect()) == [2]


@testing.effect
def test_failures_and_defects():
    error = ValueError("boom")
    assert (yield from stream.fail("e").run_collect().exit()) == fx.exit.fail("e")
    assert (yield from stream.fail_sync(lambda: "e").run_drain().exit()) == fx.exit.fail("e")
    assert (yield from stream.die(error).run_collect().exit()) == fx.exit.die(error)
    cause = fx.cause.fail("e")
    assert (yield from stream.fail_cause(cause).run_collect().exit()) == fx.exit.fail("e")
    assert (yield from stream.fail_cause_sync(lambda: cause).run_drain().exit()) == fx.exit.fail(
        "e"
    )


@testing.effect
def test_transform_pull_bracket_closes_its_scope_when_the_stream_ends():
    closed: list[fx.Exit[Any, Any]] = []

    def build(pull: Any, _scope: fx.CloseableScope, forked: fx.CloseableScope) -> Any:
        return forked.add_finalizer(lambda ex: fx.sync(lambda: closed.append(ex))).as_(pull)

    numbers = stream.transform_pull_bracket(stream.make(1, 2), build)
    assert (yield from numbers.run_collect()) == [1, 2]
    assert len(closed) == 1


def test_from_channel_and_to_channel_check_their_arguments():
    with pytest.raises(TypeError, match=r"^channel must be a Channel"):
        stream.from_channel(stream.empty)  # pyright: ignore[reportArgumentType]
    with pytest.raises(TypeError, match=r"^stream must be a Stream"):
        stream.to_channel(fx.channel.empty)  # pyright: ignore[reportArgumentType]
    assert stream.to_channel(stream.empty) is stream.empty.channel
