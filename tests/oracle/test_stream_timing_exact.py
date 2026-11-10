"""Stream timing on the TestClock lands on Effect's exact nanosecond.

Each case was run under Node against Effect v4 (the QA stream-time
repros); the expected times are what Effect prints. A deadline kept in
float seconds (``0.04 + 0.02 > 0.06``) floors to a 0 ns sleep that never
moves time, or lands a nanosecond early or late, so every timer here is
computed in whole nanoseconds (``tests/test_clock_nanos_guard.py``).
"""

import warnings
from collections.abc import Callable

import pyfect as fx
from pyfect import clock, schedule, sink, stream, testing
from pyfect.duration import Duration
from pyfect.testing import BusyFiberWarning

_MS = 1_000_000


def _stamp(times: list[tuple[int, object]]) -> Callable[[object], fx.Effect[None]]:
    def stamp(value: object) -> fx.Effect[None]:
        return clock.now_nanos().map(lambda t: times.append((t, value)))

    return stamp


@testing.effect
def test_debounce_emits_at_the_deadline_without_spinning():
    """One item at 100 ms then silence: debounce(200 ms) emits it at 300 ms
    (``0.1 + 0.2 > 0.3`` in float seconds)."""
    times: list[tuple[int, object]] = []
    s = (
        stream.from_effect(fx.sleep("100 millis").as_(1))
        .concat(stream.never)
        .debounce("200 millis")
        .map_effect(_stamp(times))
    )
    with warnings.catch_warnings():
        warnings.simplefilter("error", BusyFiberWarning)
        fiber = yield from s.run_drain().fork()
        yield from testing.adjust("1 second")
        yield from fiber.interrupt()
    assert times == [(300 * _MS, 1)]


@testing.effect
def test_timeout_ends_the_stream_at_the_deadline():
    """1 at 10 ms then silence: timeout(20 ms) ends the stream at 30 ms."""
    ended: list[int] = []
    s = (
        stream.from_effect(fx.sleep("10 millis").as_(1))
        .concat(stream.never)
        .timeout("20 millis")
        .on_end(clock.now_nanos().map(ended.append))
    )
    with warnings.catch_warnings():
        warnings.simplefilter("error", BusyFiberWarning)
        fiber = yield from s.run_collect().fork()
        yield from testing.adjust("1 second")
        result = yield from fiber.join()
    assert (result, ended) == ([1], [30 * _MS])


@testing.effect
def test_throttle_shape_releases_a_delayed_chunk_when_its_tokens_are_due():
    """2 units per 100 ms, burst 2: 2 passes at 10 ms, the chunk (4, 3, 1) waits to 100 ms."""
    times: list[tuple[int, object]] = []
    s = (
        stream.from_iterable([(0.01, (2,)), (0.0, (4, 3, 1))])
        .map_effect(lambda e: fx.sleep(Duration(e[0])).as_(e[1]))
        .flatten_array()
        .throttle(cost=len, units=2, duration="100 millis", burst=2)
        .map_effect(_stamp(times))
    )
    fiber = yield from s.run_drain().fork()
    yield from testing.adjust("1 second")
    yield from fiber.join()
    assert times == [(10 * _MS, 2), (100 * _MS, 4), (100 * _MS, 3), (100 * _MS, 1)]


@testing.effect
def test_aggregate_within_fixed_fires_on_the_beat():
    """Items every 5 ms, fold_until(sum, 3) within fixed(12 ms)."""
    times: list[tuple[int, object]] = []
    s = (
        stream.from_iterable(range(1, 8))
        .flat_map(lambda v: stream.from_effect(fx.sleep("5 millis").as_(v)))
        .aggregate_within(
            sink.fold_until(lambda: 0, 3, lambda acc, x: fx.succeed(acc + x)),
            schedule.fixed("12 millis"),
        )
        .map_effect(_stamp(times))
    )
    fiber = yield from s.run_drain().fork()
    for _ in range(100):
        yield from fx.yield_now()
    for _ in range(100):
        yield from testing.adjust("1 millis")
    yield from fiber.join()
    assert times == [(15 * _MS, 6), (22 * _MS, 4), (35 * _MS, 18)]
