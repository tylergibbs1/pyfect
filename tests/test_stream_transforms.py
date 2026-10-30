"""Stream transforms beyond the ``Stream.test.ts`` ports. Each expected
value was printed by Effect's ``Stream`` under Node first; where pyfect
differs on purpose, the test says so."""

from typing import Any

import pyfect as fx
from pyfect import schedule, stream, testing
from pyfect.clock import Clock
from pyfect.queue import Done, Queue
from pyfect.result import Err, Ok


def _chunks(s: stream.Stream[Any, Any, Any]) -> fx.Effect[list[Any], Any, Any]:
    return s.chunks().run_collect()


def _settle() -> fx.Effect[None]:
    """Enough scheduler turns for every woken fiber to run (Effect needs
    fewer, as it resumes some fibers at once)."""
    return fx.yield_now().repeat(times=20)


# --- collecting -----------------------------------------------------------------


@testing.effect
def test_collect_writes_every_item_as_one_list():
    assert (yield from stream.make(1, 2, 3).rechunk(2).collect().run_collect()) == [[1, 2, 3]]
    assert (yield from stream.empty.collect().run_collect()) == [[]]


@testing.effect
def test_accumulate_writes_the_items_so_far_for_each_chunk():
    accumulated = yield from stream.make(1, 2, 3).rechunk(2).accumulate().run_collect()
    assert accumulated == [(1, 2), (1, 2, 3)]
    assert (yield from stream.empty.accumulate().run_collect()) == []


@testing.effect
def test_accumulate_keeps_what_it_wrote_before_a_failure():
    failing = stream.make(1, 2).concat(stream.fail("e")).accumulate()
    result = yield from failing.catch_all(stream.succeed).run_collect()
    assert result == [(1, 2), "e"]


# --- taking and changes -----------------------------------------------------------


@testing.effect
def test_take_until_keeps_or_drops_the_item_that_passes():
    numbers = stream.make(1, 2, 3, 4)
    assert (yield from numbers.take_until(lambda n: n == 3).run_collect()) == [1, 2, 3]
    excluding = numbers.take_until(lambda n: n == 3, exclude_last=True)
    assert (yield from excluding.run_collect()) == [1, 2]
    effectful = numbers.take_until_effect(lambda n: fx.succeed(n == 3), exclude_last=True)
    assert (yield from effectful.run_collect()) == [1, 2]


def _same_parity(a: int, b: int) -> bool:
    return a % 2 == b % 2


@testing.effect
def test_changes_with_uses_the_given_equivalence():
    numbers = stream.make(1, 3, 2, 4, 7, 8)
    assert (yield from numbers.changes_with(_same_parity).run_collect()) == [1, 2, 7, 8]
    effectful = numbers.changes_with_effect(lambda a, b: fx.succeed(_same_parity(a, b)))
    assert (yield from effectful.run_collect()) == [1, 2, 7, 8]


# --- chunks -----------------------------------------------------------------------


@testing.effect
def test_split_writes_no_empty_chunk_for_a_chunk_without_a_whole_run():
    split = stream.make(1, 2, 0, 3).rechunk(1).split(lambda n: n == 0)
    assert (yield from _chunks(split)) == [((1, 2),), ((3,),)]


@testing.effect
def test_flatten_array_skips_empty_tuples():
    """Effect writes an empty chunk for an empty array; pyfect's chunks are
    never empty, so it skips it (``flatten_iterable`` agrees with Effect)."""
    nested = stream.make((1,), (), (2, 3))
    assert (yield from _chunks(nested.flatten_array())) == [(1,), (2, 3)]
    iterables = stream.make([1], [], [2, 3])
    assert (yield from _chunks(iterables.flatten_iterable())) == [(1,), (2, 3)]


# --- interleaving and racing ------------------------------------------------------


@testing.effect
def test_interleave_writes_the_rest_of_the_longer_side():
    result = yield from stream.make(1).interleave(stream.make(2, 3, 4)).run_collect()
    assert result == [1, 2, 3, 4]
    decider = stream.make(True, True, True, False, False)
    picked = stream.make(1).interleave_with(stream.make(2, 3), decider)
    assert (yield from picked.run_collect()) == [1, 2, 3]


@testing.effect
def test_race_closes_the_winner_once_and_never_starts_a_late_loser():
    log: list[str] = []

    def note(entry: str) -> fx.Effect[None]:
        return fx.sync(lambda: log.append(entry))

    first = stream.make(1).ensuring(note("finA"))
    second = stream.make(2).ensuring(note("finB"))
    result = yield from first.race(second).tap(lambda n: note(f"item {n}")).run_collect()
    assert result == [1]
    assert log == ["item 1", "finA"]


# --- zip_latest -------------------------------------------------------------------


@testing.effect
def test_zip_latest_pairs_each_new_item_with_the_other_sides_latest():
    left = yield from Queue[int, Done].unbounded()
    right = yield from Queue[str, Done].unbounded()
    zipped = stream.from_queue(left).zip_latest(stream.from_queue(right))
    fiber = yield from zipped.take(4).run_collect().fork_scoped()
    offers = [left.offer(1), left.offer(2), right.offer("a"), left.offer(3), right.offer("b")]
    for offer in offers:
        yield from offer
        yield from _settle()
    assert (yield from fiber.join()) == [(1, "a"), (2, "a"), (3, "a"), (3, "b")]


@testing.effect
def test_zip_latest_all_waits_for_every_stream_before_writing():
    queues = (
        (yield from Queue[int, Done].unbounded()),
        (yield from Queue[str, Done].unbounded()),
        (yield from Queue[bool, Done].unbounded()),
    )
    zipped = stream.zip_latest_all(*(stream.from_queue(q) for q in queues))
    fiber = yield from zipped.take(2).run_collect().fork_scoped()
    yield from queues[0].offer(1)
    yield from queues[1].offer("a")
    yield from _settle()
    assert fiber.poll_unsafe() is None
    yield from queues[2].offer(True)
    yield from _settle()
    yield from queues[0].offer(2)
    assert (yield from fiber.join()) == [(1, "a", True), (2, "a", True)]


# --- timeouts and throttling ------------------------------------------------------


def _timed(spacing: float) -> fx.Effect[list[int], Any, Any]:
    @fx.fn
    def run():
        spaced = stream.make(1, 2, 3).rechunk(1).schedule(schedule.spaced(spacing))
        fiber = yield from spaced.timeout(1).run_collect().fork_scoped()
        yield from testing.adjust(5)
        return (yield from fiber.join())

    return run()


@testing.effect
def test_timeout_restarts_for_each_pull():
    """Each pull gets its own second: items 0.6 seconds apart never time
    out, though the first deadline passes while the second pull waits."""
    assert (yield from _timed(0.6)) == [1, 2, 3]
    assert (yield from _timed(1.5)) == []


@testing.effect
def test_throttle_shape_caps_the_bucket_at_units_plus_burst():
    queue = yield from Queue[int, Done].unbounded()
    clock = yield from Clock()
    seen: list[tuple[int, float]] = []

    def record(n: int) -> fx.Effect[None]:
        return fx.sync(lambda: seen.append((n, clock.now_unsafe())))

    throttled = stream.from_queue(queue).throttle(
        cost=len, units=1, duration=1, burst=2, strategy="shape"
    )
    yield from throttled.run_for_each(record).fork_scoped()
    yield from testing.adjust(10)
    yield from queue.offer_all(range(1, 7))
    for _ in range(10):
        yield from testing.adjust(1)
    assert seen == [(n, 13) for n in range(1, 7)]


@testing.effect
def test_throttle_enforce_caps_the_bucket_at_units_plus_burst():
    queue = yield from Queue[int, Done].unbounded()
    passed: list[int] = []
    throttled = stream.from_queue(queue).throttle(
        cost=len, units=1, duration=1, burst=2, strategy="enforce"
    )
    yield from throttled.run_for_each(lambda n: fx.sync(lambda: passed.append(n))).fork_scoped()
    yield from testing.adjust(10)
    for n in range(1, 7):
        yield from queue.offer(n)
        yield from _settle()
    assert passed == [1, 2, 3]


# --- errors -----------------------------------------------------------------------


@testing.effect
def test_catch_filter_fails_with_what_the_filter_rejects():
    caught = stream.fail(5).catch_filter(
        lambda e: Ok(e) if e > 10 else Err(f"small {e}"), stream.make
    )
    assert (yield from caught.run_collect().exit()) == fx.exit.fail("small 5")


@testing.effect
def test_race_closes_a_loser_that_also_wrote_at_once():
    log: list[str] = []

    def note(entry: str) -> fx.Effect[None]:
        return fx.sync(lambda: log.append(entry))

    first = (
        stream.from_effect(fx.sleep(1).as_(1))
        .concat(stream.from_effect(fx.sleep(1).as_(11)))
        .ensuring(note("finA"))
    )
    second = stream.from_effect(fx.sleep(1).as_(2)).ensuring(note("finB"))
    raced = first.race(second).tap(lambda n: note(f"item {n}"))
    fiber = yield from raced.run_collect().fork_scoped()
    yield from testing.adjust(1)
    log.append("after 1s")
    yield from testing.adjust(1)
    assert (yield from fiber.join()) == [1, 11]
    assert log == ["finB", "item 1", "after 1s", "item 11", "finA"]


# --- combine ----------------------------------------------------------------------


def _alternate(
    take_left: bool, left: fx.Effect[Any, Any], right: fx.Effect[Any, Any]
) -> fx.Effect[tuple[str, bool], Any]:
    if take_left:
        return left.map(lambda value: (f"L:{value}", False))
    return right.map(lambda value: (f"R:{value}", True))


@testing.effect
def test_combine_threads_its_state_through_pulls_of_either_side():
    letters = stream.make("A", "B", "C")
    combined = letters.combine(stream.make(1, 2, 3), lambda: True, _alternate)
    assert (yield from combined.run_collect()) == ["L:A", "R:1", "L:B", "R:2", "L:C", "R:3"]
    short = letters.combine(stream.make(1), lambda: True, _alternate)
    assert (yield from short.run_collect()) == ["L:A", "R:1", "L:B"]
    failing = stream.make("A").concat(stream.fail("boom"))
    failed = failing.combine(stream.make(1, 2), lambda: True, _alternate)
    assert (yield from failed.run_collect().exit()) == fx.exit.fail("boom")


@testing.effect
def test_combine_array_writes_the_chunks_it_makes():
    def alternate(
        use_left: bool,
        left: fx.Effect[tuple[int, ...], Any],
        right: fx.Effect[tuple[int, ...], Any],
    ) -> fx.Effect[tuple[tuple[int, ...], bool], Any]:
        return (left if use_left else right).map(lambda chunk: (chunk, not use_left))

    pairs = stream.make(1, 2).combine_array(stream.make(10, 20), lambda: True, alternate)
    assert (yield from _chunks(pairs)) == [(1, 2), (10, 20)]
    rechunked = (
        stream.make(1, 2, 3)
        .rechunk(2)
        .combine_array(stream.make(10, 20, 30).rechunk(1), lambda: True, alternate)
    )
    assert (yield from _chunks(rechunked)) == [(1, 2), (10,), (3,), (20,)]
