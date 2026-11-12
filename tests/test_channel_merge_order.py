"""How far merged channels run ahead of their reader, and the order their
items and finalizers interleave in.

Expected values were printed by Effect's ``Channel.ts`` under Node (bun,
Effect's own source).
"""

from collections.abc import Callable, Iterator
from typing import Any

import pyfect as fx
from pyfect import channel, testing

type AnyChannel = channel.Channel[Any, Any, Any, Any, Any, Any, Any]


def _produced_by_first_read(make: Callable[[AnyChannel], AnyChannel]) -> fx.Effect[list[int], Any]:
    """Read one item of ``make(source)``, let every fiber settle, and give the
    items ``source`` produced by then."""
    log: list[int] = []

    def numbers() -> Iterator[int]:
        for i in range(10):
            log.append(i)
            yield i

    def body():
        pull = yield from make(channel.from_iterable(numbers())).to_pull()
        assert (yield from pull) == 0
        for _ in range(20):
            yield from fx.yield_now()
        return list(log)

    return fx.scoped(fx.gen(body))


@testing.effect
def test_merge_lets_each_side_run_one_item_ahead_of_the_reader():
    produced = yield from _produced_by_first_read(lambda source: source.merge(channel.empty))
    assert produced == [0, 1]


@testing.effect
def test_concurrent_flat_map_buffers_up_to_buffer_size_items():
    def flattened(buffer_size: int) -> Callable[[AnyChannel], AnyChannel]:
        return lambda source: channel.from_iterable([source]).flat_map(
            lambda c: c, concurrency=2, buffer_size=buffer_size
        )

    assert (yield from _produced_by_first_read(flattened(1))) == [0, 1, 2]
    assert (yield from _produced_by_first_read(flattened(4))) == [0, 1, 2, 3, 4, 5]


@testing.effect
def test_concurrent_flat_map_of_an_empty_channel_ends():
    assert (yield from channel.empty.flat_map(lambda c: c, concurrency=2).run_collect()) == []


def _merged(shapes: list[list[int]], concurrency: int) -> fx.Effect[tuple[list[int], list[str]]]:
    """``merge_all`` of one channel per shape, unbuffered, with the order items
    were produced and inner channels ended in."""
    log: list[str] = []

    def produce(x: int) -> int:
        log.append(f"p{x}")
        return x

    def inner(xs: list[int]) -> channel.Channel[int]:
        ended = fx.sync(lambda: log.append(f"end{xs[0]}"))
        return channel.from_iterable(xs).map(produce).ensuring(ended)

    merged = channel.from_iterable(shapes).map(inner)
    run = merged.merge_all(concurrency=concurrency, buffer_size=0).run_collect()
    return run.map(lambda items: (items, log))


@testing.effect
def test_merge_all_runs_one_inner_channel_at_a_time_with_concurrency_one():
    items, log = yield from _merged([[1], [2, 2], [3, 3, 3], [4], [5, 5, 5, 5]], 1)
    assert items == [1, 2, 2, 3, 3, 3, 4, 5, 5, 5, 5]
    assert log == [
        *("p1", "end1", "p2", "p2", "end2", "p3", "p3", "p3", "end3"),
        *("p4", "end4", "p5", "p5", "p5", "p5", "end5"),
    ]


@testing.effect
def test_merge_all_interleaves_items_and_endings_as_effect_does():
    items, log = yield from _merged([[1], [2, 2], [3, 3, 3], [4], [5, 5, 5, 5]], 2)
    assert items == [1, 2, 2, 3, 3, 4, 3, 5, 5, 5, 5]
    assert log == [
        *("p1", "p2", "end1", "p2", "end2", "p3", "p3", "p4", "p3", "end4"),
        *("end3", "p5", "p5", "p5", "p5", "end5"),
    ]
    items, log = yield from _merged([[1, 1, 1], [2], [3, 3], [4, 4, 4, 4], [5]], 2)
    assert items == [1, 2, 1, 1, 3, 3, 4, 4, 4, 5, 4]
    assert log == [
        *("p1", "p2", "p1", "end2", "p1", "end1", "p3", "p3", "p4", "end3"),
        *("p4", "p4", "p5", "p4", "end5", "end4"),
    ]
