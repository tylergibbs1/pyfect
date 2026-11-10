"""Ports of Effect's ``cluster/Snowflake.test.ts``. Each test's docstring is the Effect test
title."""

from __future__ import annotations

import itertools
import random

import pyfect as fx
from pyfect import testing
from pyfect.cluster import snowflake


def test_make_generator_keeps_ids_unique_after_repeated_sequence_overflow() -> None:
    """makeGenerator keeps ids unique after repeated sequence overflow"""
    now = snowflake.EPOCH_MILLIS + 1000

    @fx.gen
    def body():
        yield from testing.set_time(now)
        generator = yield from snowflake.make_generator()
        return [generator.next_unsafe() for _ in range(8193)]

    ids = testing.run_test(body)
    assert all(earlier < later for earlier, later in itertools.pairwise(ids))
    assert [
        (snowflake.timestamp(ids[i]), snowflake.sequence(ids[i])) for i in (4095, 4096, 8191, 8192)
    ] == [
        (now, 4095),
        (now + 1, 0),
        (now + 1, 4095),
        (now + 2, 0),
    ]


def test_generator_ids_increase_whatever_the_clock_does() -> None:
    """Not an Effect title: the generator's invariant, under a clock that jumps forwards and
    backwards between bursts of every size up to past two overflows. Every id is greater
    than the one before, so none repeats and no sequence wraps."""
    start = snowflake.EPOCH_MILLIS + 10_000
    rng = random.Random(4096)
    moves = [rng.randrange(-3, 4) for _ in range(60)]
    bursts = [rng.choice((1, 7, 4095, 4096, 4097, 9000)) for _ in range(60)]

    @fx.gen
    def body():
        yield from testing.set_time(start)
        generator = yield from snowflake.make_generator()
        ids: list[snowflake.Snowflake] = []
        at = start
        for move, burst in zip(moves, bursts, strict=True):
            at += move
            yield from testing.set_time(at)
            ids.extend(generator.next_unsafe() for _ in range(burst))
        return ids

    ids = testing.run_test(body)
    assert all(earlier < later for earlier, later in itertools.pairwise(ids))
