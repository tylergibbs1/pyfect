"""Ports of Effect's ``Stream.test.ts``: the ``buffer``, ``debounce``,
``throttle``, ``timeout``, ``haltWhen``, ``repeat`` and ``schedule``
sections.

Each test's docstring is the Effect test title. Durations are seconds,
``Duration.infinity`` is ``math.inf``, ``Option.none()`` errors are
``None`` and Effect's ``chunkCoordination`` test helper is
``_Coordination`` below.

Adapted, with the reason:

- The two ``throttleShape`` clock titles build their altered clock as
  ``_ShiftedClock``, a ``ClockService`` delegating to the test clock,
  where Effect spreads the test clock into an object.
- The first two ``haltWhen`` titles yield once after completing the halt
  deferred: pyfect resumes the fiber waiting on it through the scheduler
  (Effect resumes it at once), and ``halt_when`` checks that fiber before
  each pull.
"""

import asyncio
import math
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from typing import Any, Literal

import pyfect as fx
from pyfect import schedule, stream, testing
from pyfect.clock import Clock, ClockService
from pyfect.duration import Duration
from pyfect.pull import catch_done
from pyfect.queue import Done, Queue
from pyfect.stream import Stream

# --- buffer ---------------------------------------------------------------------


@testing.effect
def test_buffer_maintains_elements_and_ordering():
    """maintains elements and ordering"""
    chunks = [list(range(0, 4)), list(range(2, 6)), list(range(3, 8))]
    result = yield from stream.from_arrays(*chunks).buffer(capacity=2).run_collect()
    assert result == [n for chunk in chunks for n in chunk]


@testing.effect
def test_buffer_stream_with_a_failure():
    """stream with a failure"""
    result = yield from (
        stream.range(0, 9).concat(stream.fail("boom")).buffer(capacity=2).run_collect().exit()
    )
    assert result == fx.exit.fail("boom")


@testing.effect
def test_buffer_fast_producer_progresses_independently():
    """fast producer progresses independently"""
    seen: list[int] = []
    latch = yield from fx.Deferred[None].make()

    def record(n: int) -> fx.Effect[Any]:
        seen.append(n)
        return latch.succeed(None) if n == 4 else fx.void

    buffered = stream.range(1, 4).tap(record).buffer(capacity=2)
    result1 = yield from buffered.take(2).run_collect()
    yield from latch.wait()
    assert result1 == [1, 2]
    assert seen == [1, 2, 3, 4]


# --- bufferArray - suspend -------------------------------------------------------


@testing.effect
def test_buffer_array_suspend_maintains_elements_and_ordering():
    """maintains elements and ordering"""
    chunks = [list(range(0, 4)), list(range(2, 6)), list(range(3, 8))]
    result = yield from stream.from_arrays(*chunks).buffer_array(capacity=2).run_collect()
    assert result == [n for chunk in chunks for n in chunk]


@testing.effect
def test_buffer_array_suspend_stream_with_a_failure():
    """stream with a failure"""
    result = yield from (
        stream.range(0, 9).concat(stream.fail("boom")).buffer_array(capacity=2).run_collect().exit()
    )
    assert result == fx.exit.fail("boom")


@testing.effect
def test_buffer_array_suspend_fast_producer_progresses_independently():
    """fast producer progresses independently"""
    seen: list[int] = []
    latch = yield from fx.Deferred[None].make()

    def record(n: int) -> fx.Effect[Any]:
        seen.append(n)
        return latch.succeed(None) if n == 4 else fx.void

    buffered = stream.range(1, 4).tap(record).buffer_array(capacity=2)
    result1 = yield from buffered.take(2).run_collect()
    yield from latch.wait()
    assert result1 == [1, 2]
    assert seen == [1, 2, 3, 4]


# --- dropping and sliding -------------------------------------------------------


def _failing_then_more(
    strategy: Literal["dropping", "sliding"], *, array: bool
) -> Stream[int, str]:
    source = stream.range(1, 1_000).concat(stream.fail("boom")).concat(stream.range(1_001, 2_000))
    if array:
        return source.buffer_array(capacity=2, strategy=strategy)
    return source.buffer(capacity=2, strategy=strategy)


@testing.effect
def test_buffer_array_dropping_buffers_a_stream_with_a_failure():
    """buffers a stream with a failure"""
    result = yield from _failing_then_more("dropping", array=True).run_collect().exit()
    assert result == fx.exit.fail("boom")


@testing.effect
def test_buffer_dropping_buffers_a_stream_with_a_failure():
    """buffers a stream with a failure"""
    result = yield from _failing_then_more("dropping", array=False).run_collect().exit()
    assert result == fx.exit.fail("boom")


@testing.effect
def test_buffer_array_sliding_buffers_a_stream_with_a_failure():
    """buffers a stream with a failure"""
    result = yield from _failing_then_more("sliding", array=True).run_collect().exit()
    assert result == fx.exit.fail("boom")


@testing.effect
def test_buffer_sliding_buffers_a_stream_with_a_failure():
    """buffers a stream with a failure"""
    result = yield from _failing_then_more("sliding", array=False).run_collect().exit()
    assert result == fx.exit.fail("boom")


type _Latch = fx.Deferred[None]


def _after(latch: _Latch, then: Stream[int]) -> Stream[int]:
    return stream.from_effect(latch.wait()).flat_map(lambda _: then)


def _ones(first: int, last: int, done: _Latch) -> Stream[int]:
    """``first`` to ``last`` one item per chunk, completing ``done`` when
    released."""
    return stream.range(first, last).rechunk(1).ensuring(done.succeed(None))


type _Reads = Literal["eight", "one", "all"]


@fx.fn
def _fast_producer(
    strategy: Literal["dropping", "sliding"],
    *,
    array: bool,
    first_last: int = 16,
    last: int = 24,
    gate_end: bool = False,
    reads: tuple[_Reads, _Reads],
):
    """Effect's "fast producer progress independently": pull 0, let
    1..``first_last`` run into a buffer of 8 and read it, then let
    17..``last`` in and read again (``reads``: eight pulls, one, or to the
    end). With ``gate_end`` the final -1 waits for a latch never opened."""
    latches: list[_Latch] = []
    for _ in range(5):
        latches.append((yield from fx.Deferred[None].make()))  # noqa: PERF401 (no yield in comprehensions)
    stream1 = stream.make(0).concat(_after(latches[0], _ones(1, first_last, latches[1])))
    stream2 = _after(latches[2], _ones(17, last, latches[3]))
    stream3 = _after(latches[4], stream.make(-1)) if gate_end else stream.make(-1)
    whole = stream1.concat(stream2).concat(stream3)
    buffered = (
        whole.buffer_array(capacity=8, strategy=strategy)
        if array
        else whole.buffer(capacity=8, strategy=strategy)
    )
    seen: list[int] = []

    def keep(chunk: tuple[int, ...]) -> fx.Effect[None]:
        return fx.sync(lambda: seen.extend(chunk))

    pull = yield from buffered.to_pull()
    read = pull.flat_map(keep)
    reading: dict[_Reads, fx.Effect[None, Any]] = {
        "eight": read.repeat(times=7),
        "one": read,
        "all": catch_done(read.forever(), lambda _: fx.void),
    }
    result1 = yield from pull
    yield from latches[0].succeed(None)
    yield from latches[1].wait()
    yield from reading[reads[0]]
    result2 = list(seen)
    yield from latches[2].succeed(None)
    yield from latches[3].wait()
    yield from reading[reads[1]]
    return list(result1), result2, list(seen)


@testing.effect
def test_buffer_array_dropping_fast_producer_progress_independently():
    """fast producer progress independently"""
    run = _fast_producer("dropping", array=True, reads=("eight", "eight"))
    assert (yield from run.pipe(fx.scoped)) == (
        [0],
        [1, 2, 3, 4, 5, 6, 7, 8],
        [1, 2, 3, 4, 5, 6, 7, 8, 17, 18, 19, 20, 21, 22, 23, 24],
    )


@testing.effect
def test_buffer_dropping_fast_producer_progress_independently():
    """fast producer progress independently"""
    run = _fast_producer("dropping", array=False, first_last=17, reads=("one", "one"))
    assert (yield from run.pipe(fx.scoped)) == (
        [0],
        [1, 2, 3, 4, 5, 6, 7, 8],
        [1, 2, 3, 4, 5, 6, 7, 8, 17, 18, 19, 20, 21, 22, 23, 24],
    )


@testing.effect
def test_buffer_array_sliding_fast_producer_progress_independently():
    """fast producer progress independently"""
    run = _fast_producer("sliding", array=True, last=25, gate_end=True, reads=("eight", "eight"))
    assert (yield from run.pipe(fx.scoped)) == (
        [0],
        [9, 10, 11, 12, 13, 14, 15, 16],
        [9, 10, 11, 12, 13, 14, 15, 16, 18, 19, 20, 21, 22, 23, 24, 25],
    )


@testing.effect
def test_buffer_sliding_fast_producer_progress_independently():
    """fast producer progress independently"""
    run = _fast_producer("sliding", array=False, reads=("one", "all"))
    assert (yield from run.pipe(fx.scoped)) == (
        [0],
        [9, 10, 11, 12, 13, 14, 15, 16],
        [9, 10, 11, 12, 13, 14, 15, 16, 18, 19, 20, 21, 22, 23, 24, -1],
    )


@testing.effect
def test_buffer_propagates_defects():
    """propagates defects"""
    defect = RuntimeError("boom")
    result = yield from (
        stream.from_effect(fx.die(defect)).buffer(capacity=1, strategy="sliding").run_drain().exit()
    )
    assert result == fx.exit.die(defect)


@testing.effect
def test_buffer_unbounded_buffers_the_stream():
    """buffer - buffers the stream"""
    items = list(range(0, 11))
    result = yield from stream.from_iterable(items).buffer(capacity="unbounded").run_collect()
    assert result == items


@testing.effect
def test_buffer_unbounded_buffers_a_stream_with_a_failure():
    """buffers a stream with a failure"""
    result = yield from (
        stream.range(0, 9)
        .concat(stream.fail("boom"))
        .buffer(capacity="unbounded")
        .run_collect()
        .exit()
    )
    assert result == fx.exit.fail("boom")


@testing.effect
def test_buffer_unbounded_fast_producer_progress_independently():
    """fast producer progress independently"""
    seen: list[int] = []
    latch = yield from fx.Deferred[None].make()

    def record(n: int) -> fx.Effect[Any]:
        seen.append(n)
        return latch.succeed(None) if n == 999 else fx.void

    buffered = stream.range(1, 999).tap(record).rechunk(999).buffer(capacity="unbounded")
    result1 = yield from buffered.take(2).run_collect()
    yield from latch.wait()
    assert result1 == [1, 2]
    assert seen == list(range(1, 1000))


# --- debounce -------------------------------------------------------------------


@dataclass
class _Coordination:
    chunks: list[list[int]]
    queue: Queue[list[int], Done]
    proceeds: Queue[None]
    sent: int = 0

    @property
    def stream(self) -> Stream[int]:
        return stream.from_queue(self.queue).flatten_iterable()

    @property
    def offer(self) -> fx.Effect[None]:
        @fx.fn
        def run():
            if self.sent < len(self.chunks):
                yield from self.queue.offer(self.chunks[self.sent])
                self.sent += 1
            if self.sent >= len(self.chunks):
                yield from self.queue.end()

        return run()

    @property
    def proceed(self) -> fx.Effect[None]:
        return self.proceeds.offer(None).as_void()

    @property
    def await_next(self) -> fx.Effect[None]:
        return self.proceeds.take()


@fx.fn
def _coordinate(*chunks: list[int]):
    queue = yield from Queue[list[int], Done].unbounded()
    proceeds = yield from Queue[None].unbounded()
    return _Coordination(list(chunks), queue, proceeds)


@testing.effect
def test_debounce_should_drop_earlier_chunks_within_wait_time():
    """should drop earlier chunks within waitTime"""
    coordination = yield from _coordinate([1], [3, 4], [5], [6, 7])
    fiber = yield from coordination.stream.chunks().debounce("1 second").run_collect().fork()
    yield from coordination.offer
    yield from fx.sleep("500 millis").and_then(coordination.offer).fork()
    yield from fx.sleep("2 seconds").and_then(coordination.offer).fork()
    yield from fx.sleep("2500 millis").and_then(coordination.offer).fork()
    yield from testing.adjust("3500 millis")
    assert (yield from fiber.join()) == [(3, 4), (6, 7)]


@testing.effect
def test_debounce_should_take_latest_chunk_within_wait_time():
    """should take latest chunk within waitTime"""
    coordination = yield from _coordinate([1, 2], [3, 4], [5, 6])
    fiber = yield from coordination.stream.chunks().debounce("1 second").run_collect().fork()
    yield from coordination.offer.and_then(coordination.offer).and_then(coordination.offer)
    yield from testing.adjust("1 second")
    assert (yield from fiber.join()) == [(5, 6)]


@testing.effect
def test_debounce_should_work_properly_with_parallelization():
    """should work properly with parallelization"""
    coordination = yield from _coordinate([1], [2], [3])
    fiber = yield from coordination.stream.chunks().debounce("1 second").run_collect().fork()
    yield from fx.all(*[coordination.offer] * 3, concurrency=3, discard=True)
    yield from testing.adjust("1 second")
    assert (yield from fiber.join()) == [(3,)]


@testing.effect
def test_debounce_should_handle_empty_chunks_properly():
    """should handle empty chunks properly"""
    fiber = yield from (
        stream.make(1, 2, 3)
        .tap(lambda _: fx.sleep("500 millis"))
        .debounce("1 second")
        .run_collect()
        .fork(start_immediately=True)
    )
    yield from testing.adjust("3 seconds")
    assert (yield from fiber.join()) == [3]


@testing.effect
def test_debounce_should_fail_immediately():
    """should fail immediately"""
    result = yield from stream.from_effect(fx.fail(None)).debounce(math.inf).run_collect().exit()
    assert result == fx.exit.fail(None)


@testing.effect
def test_debounce_should_work_with_empty_streams():
    """should work with empty streams"""
    assert (yield from stream.empty.debounce("5 seconds").run_collect()) == []


@testing.effect
def test_debounce_should_pick_last_element_from_every_chunk():
    """should pick last element from every chunk"""
    fiber = yield from stream.make(1, 2, 3).debounce("1 second").run_collect().fork()
    yield from testing.adjust("1 second")
    assert (yield from fiber.join()) == [3]


@testing.effect
def test_debounce_should_interrupt_fibers_properly():
    """should interrupt fibers properly"""
    coordination = yield from _coordinate([1], [2], [3])
    fiber = yield from (
        coordination.stream.chunks()
        .tap(lambda _: coordination.proceed)
        .flatten_array()
        .debounce("200 millis")
        .take(1)
        .run_collect()
        .fork()
    )
    for _ in range(3):
        yield from coordination.offer
        yield from testing.adjust("100 millis")
        yield from coordination.await_next
    yield from testing.adjust("100 millis")
    assert (yield from fiber.join()) == [3]


@testing.effect
def test_debounce_should_interrupt_children_fiber_on_stream_interruption():
    """should interrupt children fiber on stream interruption"""
    ref = yield from fx.Ref.make(False)
    fiber = yield from (
        stream.from_effect(fx.void)
        .concat(stream.from_effect(fx.never.on_interrupt(ref.set(True))))
        .debounce("800 millis")
        .run_drain()
        .fork()
    )
    yield from testing.adjust("1 minute")
    yield from fiber.interrupt()
    assert (yield from ref.get()) is True


# --- throttle -------------------------------------------------------------------


@testing.effect
def test_throttle_enforce_free_elements():
    """throttleEnforce - free elements"""
    result = yield from (
        stream.make(1, 2, 3, 4)
        .throttle(cost=lambda _: 0, units=0, duration=math.inf, strategy="enforce")
        .run_collect()
    )
    assert result == [1, 2, 3, 4]


@testing.effect
def test_throttle_enforce_no_bandwidth():
    """throttleEnforce - no bandwidth"""
    result = yield from (
        stream.make(1, 2, 3, 4)
        .throttle(cost=lambda _: 1, units=0, duration=math.inf, strategy="enforce")
        .run_collect()
    )
    assert result == []


@testing.effect
def test_throttle_enforce_refill_bucket_tokens():
    """throttleEnforce - refill bucket tokens"""
    fiber = yield from (
        stream.from_schedule(schedule.spaced("100 millis"))
        .take(10)
        .throttle(cost=lambda _: 1, units=1, duration="200 millis", strategy="enforce")
        .run_collect()
        .fork()
    )
    yield from testing.adjust("1 second")
    assert (yield from fiber.join()) == [0, 2, 4, 6, 8]


def _pull_three(burst: float) -> fx.Effect[list[tuple[int, ...]], Any]:
    """Offer 1, 2 and 3 one at a time to a throttled queue stream, pulling
    each; without burst sleep 4 seconds before the third, with burst move
    the clock 2 and then 4 seconds."""

    @fx.fn
    def run():
        queue = yield from Queue[int, Done].unbounded()
        throttled = stream.from_queue(queue).throttle(
            cost=sum, units=1, duration="1 second", burst=burst, strategy="shape"
        )
        pull = yield from throttled.to_pull()
        yield from queue.offer(1)
        result1 = yield from pull
        if burst:
            yield from testing.adjust("2 seconds")
        yield from queue.offer(2)
        result2 = yield from pull
        yield from (testing.adjust("4 seconds") if burst else fx.sleep("4 seconds"))
        yield from queue.offer(3)
        result3 = yield from pull
        return [result1, result2, result3]

    return run().pipe(fx.scoped)


@testing.effect
def test_throttle_shape():
    """throttleShape"""
    fiber = yield from _pull_three(0).fork()
    yield from testing.adjust("8 seconds")
    assert (yield from fiber.join()) == [(1,), (2,), (3,)]


@testing.effect
def test_throttle_shape_infinite_bandwidth():
    """throttleShape - infinite bandwidth"""

    @fx.fn
    def run():
        queue = yield from Queue[int, Done].unbounded()
        throttled = stream.from_queue(queue).throttle(
            cost=lambda _: 100_000, units=1, duration=0, strategy="shape"
        )
        pull = yield from throttled.to_pull()
        yield from queue.offer(1)
        result1 = yield from pull
        yield from queue.offer(2)
        result2 = yield from pull
        return [result1, result2]

    assert (yield from run().pipe(fx.scoped)) == [(1,), (2,)]


@dataclass
class _ShiftedClock:
    """A clock that delegates to ``base``, its monotonic time moved on by
    ``monotonic_offset`` nanoseconds, its wall time by ``wall_offset``
    seconds, and its sleeps cut short by ``early`` seconds (Effect's
    tests spread the test clock into an object with these overrides)."""

    base: ClockService
    monotonic_offset: int = 0
    wall_offset: float = 0
    early: float = 0

    def current_time_millis_unsafe(self) -> float:
        return self.base.current_time_millis_unsafe() + self.wall_offset * 1000

    def monotonic_unsafe(self) -> float:
        return self.monotonic_nanos_unsafe() / 1e9

    def now_nanos_unsafe(self) -> int:
        return self.base.now_nanos_unsafe() + round(self.wall_offset * 1e9)

    def monotonic_nanos_unsafe(self) -> int:
        return self.base.monotonic_nanos_unsafe() + self.monotonic_offset

    def sleep(self, duration: Duration) -> fx.Effect[None]:
        return self.base.sleep(duration - fx.duration.seconds(self.early))


def _millis(clock: ClockService) -> fx.Effect[int]:
    return fx.sync(lambda: round(clock.current_time_millis_unsafe()))


@testing.effect
def test_throttle_shape_keeps_the_rate_when_sleeps_end_early():
    """throttleShape - keeps the rate when sleeps end early"""
    clock = yield from Clock()
    early = _ShiftedClock(clock, monotonic_offset=1 << 80, early=0.001)
    timestamps = (
        stream.range(1, 3)
        .rechunk(1)
        .throttle(cost=len, units=1, duration="1 second", strategy="shape")
        .map_effect(lambda _: _millis(clock))
        .run_collect()
    )
    fiber = yield from timestamps.pipe(fx.provide_service(Clock, early)).fork_scoped()
    yield from testing.adjust("3 seconds")
    assert (yield from fiber.join()) == [0, 999, 1999], "Early wake-ups must not accumulate"


@testing.effect
def test_throttle_shape_is_not_affected_by_wall_clock_changes():
    """throttleShape - is not affected by wall clock changes"""
    clock = yield from Clock()
    shifted = _ShiftedClock(clock)

    def shift(n: int) -> fx.Effect[None]:
        def move() -> None:
            if n == 1:
                shifted.wall_offset = -5

        return fx.sync(move)

    timestamps = (
        stream.range(1, 2)
        .rechunk(1)
        .throttle(cost=len, units=1, duration="1 second", strategy="shape")
        .tap(shift)
        .map_effect(lambda _: _millis(clock))
        .run_collect()
    )
    fiber = yield from timestamps.pipe(fx.provide_service(Clock, shifted)).fork_scoped()
    yield from testing.adjust("6 seconds")
    assert (yield from fiber.join()) == [0, 1000], "Wall clock changes must not affect the rate"


@testing.effect
def test_throttle_shape_with_burst():
    """throttleShape - with burst"""
    fiber = yield from _pull_three(2).fork()
    assert (yield from fiber.join()) == [(1,), (2,), (3,)]


@testing.effect
def test_throttle_shape_free_elements():
    """throttleShape - free elements"""
    result = yield from (
        stream.make(1, 2, 3, 4)
        .throttle(cost=lambda _: 0, units=1, duration=math.inf, strategy="shape")
        .run_collect()
    )
    assert result == [1, 2, 3, 4]


# --- timeout --------------------------------------------------------------------


@testing.effect
def test_timeout_or_else_succeed():
    """timeoutOrElse - succeed"""
    result = yield from (
        stream.succeed(1).timeout_or_else(math.inf, lambda: stream.succeed(-1)).run_collect()
    )
    assert result == [1]


@testing.effect
def test_timeout_or_else_should_switch_streams():
    """timeoutOrElse - should switch streams"""
    result = yield from (
        stream.range(0, 4)
        .tap(lambda _: fx.sleep(math.inf))
        .timeout_or_else(0, lambda: stream.succeed(4))
        .run_collect()
    )
    assert result == [4]


async def _stuck_after_a() -> AsyncGenerator[str]:
    yield "a"
    await asyncio.Event().wait()


def _raised(error: Exception) -> Exception:
    return error


@testing.live(asyncio=True)
def test_timeout_finishes_when_an_async_iterator_pull_never_settles():
    """timeout finishes when an async iterator pull never settles"""
    source = stream.from_async_iterable(_stuck_after_a(), _raised)
    assert (yield from source.timeout("10 millis").run_collect()) == ["a"]


@testing.live(asyncio=True)
def test_timeout_or_else_finishes_when_an_async_iterator_pull_never_settles():
    """timeoutOrElse finishes when an async iterator pull never settles"""
    source = stream.from_async_iterable(_stuck_after_a(), _raised)
    timed = source.timeout_or_else("10 millis", lambda: stream.succeed("fallback"))
    assert (yield from timed.run_collect()) == ["a", "fallback"]


@testing.effect
def test_timeout_or_else_should_not_apply_timeout_after_switch():
    """timeoutOrElse - should not apply timeout after switch"""
    fiber = yield from (
        stream.never.timeout_or_else(
            0, lambda: stream.succeed(1).tap(lambda _: fx.sleep("1 second"))
        )
        .run_collect()
        .fork(start_immediately=True)
    )
    yield from testing.adjust("1 second")
    assert (yield from fiber.join()) == [1]


@testing.effect
def test_timeout_succeed():
    """timeout - succeed"""
    assert (yield from stream.succeed(1).timeout(math.inf).run_collect()) == [1]


@testing.effect
def test_timeout_should_end_the_stream():
    """timeout - should end the stream"""
    result = yield from (
        stream.range(0, 4).tap(lambda _: fx.sleep(math.inf)).timeout(0).run_collect()
    )
    assert result == []


# --- haltWhen -------------------------------------------------------------------


def _halt_now(halt: fx.Deferred[None]) -> fx.Effect[None]:
    """Complete ``halt`` and let its waiter run before the next pull."""
    return halt.succeed(None).and_then(fx.yield_now())


@testing.effect
def test_halt_when_halts_after_the_current_element_in_the_documentation_example():
    """halts after the current element in the documentation example"""
    halt = yield from fx.Deferred[None].make()
    values = yield from (
        stream.from_iterable([1, 2, 3])
        .tap(lambda v: _halt_now(halt) if v == 2 else fx.void)
        .halt_when(halt.wait())
        .run_collect()
    )
    assert values == [1, 2]


@testing.effect
def test_halt_when_halts_a_synchronous_upstream_before_the_next_chunk():
    """halts a synchronous upstream before the next chunk"""
    halt = yield from fx.Deferred[None].make()
    values = yield from (
        stream.from_arrays([1], [2], [3], [4])
        .tap(lambda v: _halt_now(halt) if v == 2 else fx.void)
        .halt_when(halt.wait())
        .run_collect()
    )
    assert values == [1, 2]


@testing.effect
def test_halt_when_halts_after_the_current_element():
    """halts after the current element"""
    ref = yield from fx.Ref.make(False)
    latch = yield from fx.Deferred[None].make()
    halt = yield from fx.Deferred[None].make()
    yield from (
        stream.from_effect(latch.wait().on_interrupt(ref.set(True)))
        .halt_when(halt.wait())
        .run_drain()
        .fork()
    )
    yield from halt.succeed(None)
    yield from latch.succeed(None)
    assert (yield from ref.get()) is False


@testing.effect
def test_halt_when_propagates_errors():
    """propagates errors"""
    halt = yield from fx.Deferred[None, str].make()
    yield from halt.fail("fail")
    result = yield from stream.make(0).forever().halt_when(halt.wait()).run_drain().flip()
    assert result == "fail"


# --- repeat ---------------------------------------------------------------------


@testing.effect
def test_repeat():
    """repeat"""
    result = yield from stream.make(1).repeat(schedule.recurs(4)).run_collect()
    assert result == [1, 1, 1, 1, 1]


@testing.effect
def test_repeat_short_circuits():
    """repeat - short circuits"""
    seen: list[int] = []
    fiber = yield from (
        stream.from_effect(fx.sync(lambda: seen.insert(0, 1)))
        .repeat(schedule.spaced("10 millis"))
        .take(2)
        .run_drain()
        .fork()
    )
    yield from testing.adjust("50 millis")
    yield from fiber.join()
    assert seen == [1, 1]


@testing.effect
def test_repeat_does_not_swallow_errors_on_a_repetition():
    """repeat - does not swallow errors on a repetition"""
    ref = yield from fx.Ref.make(0)
    attempt = ref.get_and_update(lambda n: n + 1).flat_map(
        lambda n: fx.succeed(n) if n <= 2 else fx.fail("boom")
    )
    result = yield from stream.from_effect(attempt).repeat(schedule.recurs(3)).run_drain().exit()
    assert result == fx.exit.fail("boom")


@testing.effect
def test_repeat_elements_simple():
    """repeatElements - simple"""
    result = yield from stream.make("A", "B", "C").repeat_elements(schedule.recurs(1)).run_collect()
    assert result == ["A", "A", "B", "B", "C", "C"]


@testing.effect
def test_repeat_elements_short_circuits_in_a_schedule():
    """repeatElements - short circuits in a schedule"""
    result = yield from (
        stream.make("A", "B", "C").repeat_elements(schedule.recurs(1)).take(4).run_collect()
    )
    assert result == ["A", "A", "B", "B"]


@testing.effect
def test_repeat_elements_short_circuits_after_schedule():
    """repeatElements - short circuits after schedule"""
    result = yield from (
        stream.make("A", "B", "C").repeat_elements(schedule.recurs(1)).take(3).run_collect()
    )
    assert result == ["A", "A", "B"]


# --- schedule -------------------------------------------------------------------


@testing.effect
def test_schedule():
    """schedule"""
    start = yield from fx.clock.current_time_millis()
    fiber = yield from (
        stream.range(1, 8)
        .schedule(schedule.fixed("100 millis"))
        .map_effect(
            lambda n: fx.clock.current_time_millis().map(lambda now: (n, round(now - start)))
        )
        .run_collect()
        .fork()
    )
    yield from testing.adjust("800 millis")
    assert (yield from fiber.join()) == [(n, n * 100) for n in range(1, 9)]
