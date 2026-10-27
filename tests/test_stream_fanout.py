"""Stream grouping, partitioning, broadcasting and the queue, pubsub and
``async for`` bridges: the cases Effect's tests leave out, with results
checked under Node where Effect defines them (its doc examples, the
``idleTimeToLive`` and failure cases of ``groupByKey``)."""

import contextlib

import pyfect as fx
from pyfect import stream, testing


def _collect_groups[K, V](
    groups: stream.Stream[tuple[K, stream.Stream[V]], str],
) -> fx.Effect[list[tuple[K, list[V]]], str]:
    return groups.map_effect(
        lambda group: group[1].run_collect().map(lambda values: (group[0], values)),
        concurrency="unbounded",
    ).run_collect()


@testing.effect
def test_an_idle_group_ends_and_its_key_starts_a_new_one():
    source = (
        stream.make("a1", "b1")
        .concat(stream.from_effect_drain(fx.sleep(2)))
        .concat(stream.make("a2"))
    )
    grouped = source.group_by_key(lambda s: s[0], idle_time_to_live=1)
    fiber = yield from _collect_groups(grouped).fork()
    yield from testing.adjust(3)
    assert (yield from fiber.join()) == [("a", ["a1"]), ("b", ["b1"]), ("a", ["a2"])]


@testing.effect
def test_an_upstream_failure_fails_the_grouped_stream():
    source = stream.make(1, 2, 3).concat(stream.fail("boom"))
    grouped = source.group_by_key(lambda n: n % 2).map_effect(
        lambda group: group[1].run_collect().exit(), concurrency="unbounded"
    )
    assert (yield from grouped.run_collect().exit()) == fx.exit.fail("boom")


@testing.effect
def test_a_failing_key_function_fails_the_grouped_stream():
    grouped = stream.make(1, 2).group_by(
        lambda n: fx.fail("bad key") if n == 2 else fx.succeed((n, n))
    )
    result = yield from grouped.map(lambda group: group[0]).run_collect().exit()
    assert result == fx.exit.fail("bad key")


@testing.effect
def test_group_adjacent_by_keeps_an_upstream_failure():
    source = stream.make(1, 1, 2).concat(stream.fail("boom"))
    result = yield from source.group_adjacent_by(lambda n: n).run_collect().exit()
    assert result == fx.exit.fail("boom")


@testing.effect
def test_partition_offers_both_sides_at_once_so_readers_waiting_on_each_other_progress():
    # One chunk overflowing both queues: zip reads an odd only after an
    # even, so offering the evens before the odds would deadlock.
    evens, odds = yield from stream.range_inclusive(0, 5).partition(
        lambda n: fx.Ok(n) if n % 2 == 0 else fx.Err(n), capacity=1
    )
    assert (yield from evens.zip(odds).run_collect()) == [(0, 1), (2, 3), (4, 5)]


@testing.effect
def test_a_broadcast_n_stream_that_stops_unsubscribes_so_the_others_keep_reading():
    first, second = yield from (stream.range_inclusive(1, 6).rechunk(1).broadcast_n(2, capacity=1))
    taken = yield from first.take(1).run_collect()
    rest = yield from second.run_collect()
    assert (taken, rest) == ([1], [1, 2, 3, 4, 5, 6])


@testing.effect
def test_share_with_unbounded_capacity_and_replay():
    shared = yield from stream.make(1, 2, 3).share(capacity="unbounded", replay=3)
    left, right = yield from fx.all(
        shared.run_collect(), shared.run_collect(), concurrency="unbounded"
    )
    assert (left, right) == ([1, 2, 3], [1, 2, 3])


# --- queues and pubsubs (Effect's doc examples) ----------------------------------


@testing.effect
def test_to_queue_feeds_a_queue_that_ends_with_the_stream():
    queue = yield from stream.from_iterable([1, 2, 3]).to_queue(capacity=8)
    assert (yield from queue.take_between(1, 3)) == [1, 2, 3]
    assert isinstance((yield from queue.take().flip()), fx.Done)


@testing.effect
def test_to_queue_fails_the_queue_with_the_stream():
    queue = yield from stream.fail("boom").to_queue(capacity="unbounded")
    assert (yield from queue.take().flip()) == "boom"


@testing.effect
def test_run_into_queue_offers_every_item_then_ends_the_queue():
    queue = yield from fx.Queue[int, fx.Done].bounded(4)
    yield from stream.from_iterable([1, 2, 3]).run_into_queue(queue).fork()
    values = yield from fx.all(queue.take(), queue.take(), queue.take())
    assert values == (1, 2, 3)
    assert isinstance((yield from queue.take().flip()), fx.Done)


@testing.effect
def test_run_into_pubsub_publishes_every_item():
    pubsub = yield from fx.PubSub[int].unbounded()
    subscription = yield from pubsub.subscribe()
    yield from stream.from_iterable([1, 2]).run_into_pubsub(pubsub)
    assert [(yield from subscription.take()), (yield from subscription.take())] == [1, 2]
    assert not (yield from pubsub.is_shutdown())


@testing.effect
def test_run_into_pubsub_can_shut_the_pubsub_down_at_the_end():
    pubsub = yield from fx.PubSub[int].unbounded()
    yield from stream.make(1).run_into_pubsub(pubsub, shutdown_on_end=True)
    assert (yield from pubsub.is_shutdown())


@testing.effect
def test_to_pubsub_publishes_to_a_new_pubsub():
    pubsub = yield from stream.make(1, 2).to_pubsub(capacity=8)
    subscription = yield from pubsub.subscribe()
    assert (yield from subscription.take()) == 1


@testing.effect
def test_to_pubsub_take_publishes_chunks_then_the_exit():
    pubsub = yield from stream.make(1, 2, 3).to_pubsub_take(capacity=8)
    subscription = yield from pubsub.subscribe()
    assert (yield from subscription.take()) == (1, 2, 3)
    assert (yield from subscription.take()) == fx.exit.succeed(None)


# --- async iteration -------------------------------------------------------------


class Database(fx.Tag[str]):
    pass


@testing.effect(asyncio=True)
def test_to_async_iterable_with_runs_with_the_given_services():
    names = stream.service(Database).concat(stream.make("b"))
    iterable = names.to_async_iterable_with(fx.Context.make(Database, "a"))

    async def collect() -> list[str]:
        return [name async for name in iterable]

    assert (yield from fx.from_async(collect)) == ["a", "b"]


@testing.effect(asyncio=True)
def test_each_async_for_runs_the_stream_afresh():
    runs = 0

    def count() -> int:
        nonlocal runs
        runs += 1
        return runs

    iterable = stream.sync(count).to_async_iterable()

    async def twice() -> list[int]:
        return [n async for n in iterable] + [n async for n in iterable]

    assert (yield from fx.from_async(twice)) == [1, 2]


@testing.effect(asyncio=True)
def test_a_stream_failure_raises_from_async_for():
    error = ValueError("boom")

    async def consume() -> list[int]:
        seen: list[int] = []
        with contextlib.suppress(ValueError):
            async for n in stream.make(1).concat(stream.fail(error)).to_async_iterable():
                seen.append(n)  # noqa: PERF401 (the failure interrupts the loop)
        return seen

    assert (yield from fx.from_async(consume)) == [1]
