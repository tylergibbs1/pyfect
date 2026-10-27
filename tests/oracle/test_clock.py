"""Ports of Effect's ``Clock.test.ts``. Each test's docstring is the Effect
test title. Effect mocks ``Date.now`` and ``process.hrtime.bigint``; the
live clock reads ``time.time_ns`` and ``time.monotonic_ns``, so those are
patched. Every title is ported."""

import time

import pytest

import pyfect as fx
from pyfect import testing


@testing.live
def test_keeps_wall_time_aligned_while_exposing_the_monotonic_source(
    monkeypatch: pytest.MonkeyPatch,
):
    """keeps wall time aligned while exposing the monotonic source"""
    wall = 1_000_000 * 1_000_000
    monotonic = 5_000_000_000
    monkeypatch.setattr(time, "time_ns", lambda: wall)
    monkeypatch.setattr(time, "monotonic_ns", lambda: monotonic)
    clock = yield from fx.Clock()

    assert clock.unsafe_now_nanos() == wall
    assert clock.unsafe_monotonic_nanos() == monotonic

    wall += 250_000_000
    monotonic += 250_000_000
    assert clock.unsafe_now_nanos() == wall

    wall += 5_000_000_000
    before_suspend = clock.unsafe_monotonic_nanos()
    assert clock.unsafe_now_nanos() == wall
    assert clock.unsafe_monotonic_nanos() == before_suspend

    wall -= 3_000_000_000
    monotonic += 100_000_000
    assert clock.unsafe_now_nanos() == wall
    assert clock.unsafe_monotonic_nanos() > before_suspend
    assert clock.unsafe_now() == wall / 1e9
