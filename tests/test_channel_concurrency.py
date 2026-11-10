"""Channels on fibers beyond ``Channel.test.ts``: concurrent ``map_effect``,
merging, buffering, ``halt_when`` and ``embed_input``.

Expected values were printed by Effect's ``Channel.ts`` under Node (see
docs/PARITY.md).
"""

from typing import Never

import pyfect as fx
from pyfect import channel, testing
from pyfect.duration import seconds


@testing.live
def test_map_effect_keeps_upstreams_order_unless_unordered():
    def slow(n: int) -> fx.Effect[int]:
        return fx.sleep(seconds(n * 0.005)).as_(n)

    ordered = channel.from_iterable([3, 1, 2]).map_effect(slow, concurrency=3)
    assert (yield from ordered.run_collect()) == [3, 1, 2]
    unordered = channel.from_iterable([3, 1, 2]).map_effect(slow, concurrency=3, unordered=True)
    assert (yield from unordered.run_collect()) == [1, 2, 3]


@testing.effect
def test_concurrent_map_effect_fails_with_the_first_failure():
    def check(n: int) -> fx.Effect[int, str]:
        return fx.fail("bad") if n == 2 else fx.succeed(n)

    mapped = channel.from_iterable([1, 2, 3]).map_effect(check, concurrency=2)
    assert (yield from mapped.run_collect().exit()) == fx.exit.fail("bad")


@testing.effect
def test_concurrent_map_effect_ends_with_upstreams_end_value():
    source = channel.from_iterable([1, 2]).concat(channel.end("D"))
    assert (yield from source.map_effect(fx.succeed, concurrency=2).run_drain()) == "D"
    unordered = source.map_effect(fx.succeed, concurrency=2, unordered=True)
    assert (yield from unordered.run_drain()) == "D"


@testing.effect
def test_merge_all_writes_every_inner_channels_items():
    inner = channel.from_iterable([1, 2, 3]).map(lambda n: channel.from_iterable([n, n * 10]))
    merged = yield from inner.merge_all(concurrency="unbounded").run_collect()
    assert merged == [1, 2, 3, 10, 20, 30]


@testing.effect
def test_concurrent_flat_map_interleaves_up_to_its_concurrency():
    flat = channel.from_iterable([1, 2, 3]).flat_map(
        lambda n: channel.from_iterable([n, n * 10]), concurrency=2
    )
    assert (yield from flat.run_collect()) == [1, 2, 10, 20, 3, 30]


@testing.effect
def test_switch_map_drops_the_interrupted_channels_items():
    switched = channel.from_iterable([1, 2]).switch_map(lambda n: channel.from_iterable([n, n]))
    assert (yield from switched.run_collect()) == [2, 2]


@testing.effect
def test_merge_ends_with_the_last_side_to_end():
    assert (yield from channel.end(1).merge(channel.end(2)).run_drain()) == 2


@testing.effect
def test_merge_effect_runs_the_effect_alongside():
    seen: list[str] = []
    merged = channel.from_iterable([1, 2]).merge_effect(fx.sync(lambda: seen.append("x")))
    assert (yield from merged.run_collect()) == [1, 2]
    assert seen == ["x"]


@testing.effect
def test_halt_when_ends_with_the_effects_value():
    assert (yield from channel.never.halt_when(fx.succeed("h")).run_drain()) == "h"


@testing.effect
def test_embed_input_runs_the_channel_without_upstream():
    seen: list[str] = []

    def read(_: fx.Pull[int, Never, None]) -> fx.Effect[None]:
        return fx.sync(lambda: seen.append("got"))

    embedded = channel.from_effect(fx.succeed("x")).embed_input(read)
    assert (yield from channel.from_iterable([1, 2]).pipe_to(embedded).run_collect()) == ["x"]
    assert seen == []


@testing.effect
def test_buffer_keeps_items_and_failures():
    assert (yield from channel.from_iterable([1, 2, 3]).buffer(capacity=1).run_collect()) == [
        1,
        2,
        3,
    ]
    chunks = channel.from_iterable([(1, 2), (3,)])
    assert (yield from chunks.buffer_array(capacity=4).run_collect()) == [(1, 2, 3)]
    failing = chunks.concat(channel.fail("x")).buffer_array(capacity=4)
    assert (yield from failing.run_collect().exit()) == fx.exit.fail("x")


@testing.effect
def test_merge_fails_with_a_defect_from_a_finished_sides_finalizer():
    boom = RuntimeError("fin")
    left = channel.from_iterable([1]).ensuring(fx.die(boom))
    for halt in ("both", "right"):
        merged = left.merge(channel.from_iterable([2]), halt_strategy=halt)
        assert (yield from merged.run_collect().exit()) == fx.exit.die(boom)
