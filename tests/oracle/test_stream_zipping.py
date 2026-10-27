"""Ports of Effect's ``Stream.test.ts``: the ``zipping`` section (its
``zipWithArray`` titles are in ``test_stream_combining.py``).

Each test's docstring is the Effect test title. ``assertExitFailure(exit,
Cause.fail(e))`` is ``exit == fx.exit.fail(e)``; Effect's inclusive
``Stream.range(0, 99)`` is ``range_inclusive(0, 99)``.

Adapted, with the reason:

- "zipWith - equivalence with array operations" is a property test; it
  runs over 200 seeded random pairs of lists, the empty ones included.
- "zipWith - does not copy the unconsumed part of a chunk on every pull"
  counts the items sliced out of a tuple subclass written as the large
  chunk, where Effect counts ``slice`` on an ``Array`` subclass.
- The ``zipLatest`` / ``zipLatestWith`` titles assert what Effect asserts
  (pairs were written, of the right shape). Which pairs two synchronous
  streams give depends on how the merged sides take turns, which differs
  from Effect (``docs/PARITY.md``, Channel merges);
  ``tests/test_stream_transforms.py`` pins exact pairs where the turns are
  fixed.

Not ported:

- The eight "works with pipe syntax" titles: they check Effect's
  data-last call form, and a Python method has one form.
"""

import random
from typing import Any, SupportsIndex

import pyfect as fx
from pyfect import channel, stream, testing
from pyfect.queue import Done, Queue
from pyfect.stream import Stream

# --- zipWith --------------------------------------------------------------------


@testing.effect
def test_zip_with_combines_elements_point_wise():
    """zipWith - combines elements point-wise"""
    zipped = stream.make(1, 2, 3).zip_with(stream.make("a", "b", "c"), lambda n, s: f"{n}-{s}")
    assert (yield from zipped.run_collect()) == ["1-a", "2-b", "3-c"]


@testing.effect
def test_zip_with_stops_when_shortest_stream_ends():
    """zipWith - stops when shortest stream ends"""
    zipped = stream.make(1, 2, 3, 4, 5, 6).zip_with(
        stream.make("a", "b", "c"), lambda n, s: f"{n}-{s}"
    )
    assert (yield from zipped.run_collect()) == ["1-a", "2-b", "3-c"]


@testing.effect
def test_zip_with_does_not_pull_too_much_when_one_stream_ends():
    """zipWith - does not pull too much when one stream ends"""
    left = stream.from_arrays([1, 2], [3, 4], [5]).concat(stream.fail("boom"))
    right = stream.from_arrays(["a", "b"], ["c"])
    result = yield from left.zip_with(right, lambda n, s: (n, s)).run_collect()
    assert result == [(1, "a"), (2, "b"), (3, "c")]


@testing.effect
def test_zip_with_prioritizes_failures():
    """zipWith - prioritizes failures"""
    failing: Stream[int, str] = stream.fail("Ouch")
    zipped = stream.never.zip_with(failing, lambda a, b: (a, b))
    assert (yield from zipped.run_collect().exit()) == fx.exit.fail("Ouch")


@testing.effect
def test_zip_with_handles_exceptions():
    """zipWith - handles exceptions"""
    error = RuntimeError("Ouch")

    def throw() -> int:
        raise error

    zipped = (
        stream.make(1)
        .flat_map(lambda _: stream.sync(throw))
        .zip_with(stream.make(1), lambda a, b: (a, b))
    )
    assert (yield from zipped.run_collect().exit()) == fx.exit.die(error)


@testing.effect
def test_zip_with_handles_empty_streams():
    """zipWith - handles empty streams"""
    empty: Stream[int] = stream.empty
    result1 = yield from empty.zip_with(stream.make(1, 2, 3), lambda a, b: (a, b)).run_collect()
    result2 = yield from stream.make(1, 2, 3).zip_with(empty, lambda a, b: (a, b)).run_collect()
    assert len(result1) == 0
    assert len(result2) == 0


@testing.effect
def test_zip_with_equivalence_with_array_operations():
    """zipWith - equivalence with array operations"""
    rng = random.Random(0)
    for _ in range(200):
        left = [rng.randint(-1000, 1000) for _ in range(rng.randint(0, 12))]
        right = [rng.randint(-1000, 1000) for _ in range(rng.randint(0, 12))]
        chunked = stream.from_iterable(left, chunk_size=rng.randint(1, 4))
        zipped = chunked.zip_with(stream.from_iterable(right), lambda a, b: a + b)
        result = yield from zipped.run_collect()
        assert result == [a + b for a, b in zip(left, right, strict=False)]


class _SliceCounting(tuple[int, ...]):
    """A chunk that counts the items sliced out of it, and of its slices
    (as an ``Array`` subclass's ``slice`` gives the subclass)."""

    copied = 0

    def __getitem__(self, key: "SupportsIndex | slice[Any, Any, Any]") -> Any:
        if isinstance(key, slice):
            part = _SliceCounting(super().__getitem__(key))
            _SliceCounting.copied += len(part)
            return part
        return super().__getitem__(key)


@testing.effect
def test_zip_with_does_not_copy_the_unconsumed_part_of_a_chunk_on_every_pull():
    """zipWith - does not copy the unconsumed part of a chunk on every pull"""
    size = 1_000
    _SliceCounting.copied = 0

    def large() -> Stream[int]:
        return stream.from_channel(channel.succeed(_SliceCounting(range(1, size + 1))))

    def singles() -> Stream[int]:
        return stream.from_iterable(range(1, size + 1), chunk_size=1)

    left_large = yield from large().zip_with(singles(), lambda a, b: a + b).run_count()
    right_large = yield from singles().zip_with(large(), lambda a, b: a + b).run_count()
    assert left_large == size
    assert right_large == size
    assert _SliceCounting.copied <= 2 * size


# --- zip ------------------------------------------------------------------------


@testing.effect
def test_zip_zips_two_streams_into_tuples():
    """zips two streams into tuples"""
    result = yield from stream.make(1, 2, 3).zip(stream.make("a", "b", "c")).run_collect()
    assert result == [(1, "a"), (2, "b"), (3, "c")]


@testing.effect
def test_zip_terminates_when_left_stream_ends_first():
    """terminates when left stream ends first"""
    result = yield from stream.make(1, 2).zip(stream.make("a", "b", "c", "d")).run_collect()
    assert result == [(1, "a"), (2, "b")]


@testing.effect
def test_zip_terminates_when_right_stream_ends_first():
    """terminates when right stream ends first"""
    result = yield from stream.make(1, 2, 3, 4).zip(stream.make("a", "b")).run_collect()
    assert result == [(1, "a"), (2, "b")]


@testing.effect
def test_zip_handles_empty_left_stream():
    """handles empty left stream"""
    result = yield from stream.empty.zip(stream.make("a", "b", "c")).run_collect()
    assert len(result) == 0


@testing.effect
def test_zip_handles_empty_right_stream():
    """handles empty right stream"""
    result = yield from stream.make(1, 2, 3).zip(stream.empty).run_collect()
    assert len(result) == 0


@testing.effect
def test_zip_propagates_errors_from_left_stream():
    """propagates errors from left stream"""
    left = stream.make(1, 2).concat(stream.fail("boom"))
    result = yield from left.zip(stream.make("a", "b", "c")).run_collect().exit()
    assert result == fx.exit.fail("boom")


@testing.effect
def test_zip_propagates_errors_from_right_stream():
    """propagates errors from right stream"""
    right = stream.make("a", "b").concat(stream.fail("ouch"))
    result = yield from stream.make(1, 2, 3).zip(right).run_collect().exit()
    assert result == fx.exit.fail("ouch")


@testing.effect
def test_zip_carries_leftovers_across_uneven_chunks_on_both_sides():
    """carries leftovers across uneven chunks on both sides"""
    numbers = stream.from_arrays([1, 2, 3], [4], [5, 6, 7])
    letters = stream.from_arrays(["a"], ["b", "c", "d", "e"], ["f", "g", "h"])
    result = yield from numbers.zip(letters).chunks().run_collect()
    assert result == [
        ((1, "a"),),
        ((2, "b"), (3, "c")),
        ((4, "d"),),
        ((5, "e"),),
        ((6, "f"), (7, "g")),
    ]


# --- zipLeft --------------------------------------------------------------------


@testing.effect
def test_zip_left_keeps_only_left_values():
    """keeps only left values"""
    result = yield from stream.make(1, 2, 3).zip_left(stream.make("a", "b", "c")).run_collect()
    assert result == [1, 2, 3]


@testing.effect
def test_zip_left_terminates_when_left_stream_ends_first():
    """terminates when left stream ends first"""
    result = yield from stream.make(1, 2).zip_left(stream.make("a", "b", "c", "d")).run_collect()
    assert result == [1, 2]


@testing.effect
def test_zip_left_terminates_when_right_stream_ends_first():
    """terminates when right stream ends first"""
    result = yield from stream.make(1, 2, 3, 4).zip_left(stream.make("a", "b")).run_collect()
    assert result == [1, 2]


@testing.effect
def test_zip_left_handles_empty_left_stream():
    """handles empty left stream"""
    result = yield from stream.empty.zip_left(stream.make("a", "b", "c")).run_collect()
    assert len(result) == 0


@testing.effect
def test_zip_left_handles_empty_right_stream():
    """handles empty right stream"""
    result = yield from stream.make(1, 2, 3).zip_left(stream.empty).run_collect()
    assert len(result) == 0


@testing.effect
def test_zip_left_propagates_errors_from_left_stream():
    """propagates errors from left stream"""
    left = stream.make(1, 2).concat(stream.fail("boom"))
    result = yield from left.zip_left(stream.make("a", "b", "c")).run_collect().exit()
    assert result == fx.exit.fail("boom")


@testing.effect
def test_zip_left_propagates_errors_from_right_stream():
    """propagates errors from right stream"""
    right = stream.make("a", "b").concat(stream.fail("ouch"))
    result = yield from stream.make(1, 2, 3).zip_left(right).run_collect().exit()
    assert result == fx.exit.fail("ouch")


@testing.effect
def test_zip_left_consumes_right_stream_elements():
    """consumes right stream elements"""
    right_pulled = 0

    def count(_: str) -> fx.Effect[None]:
        def bump() -> None:
            nonlocal right_pulled
            right_pulled += 1

        return fx.sync(bump)

    right = stream.make("a", "b", "c").tap(count)
    result = yield from stream.make(1, 2, 3).zip_left(right).run_collect()
    assert result == [1, 2, 3]
    assert right_pulled == 3


# --- zipRight -------------------------------------------------------------------


@testing.effect
def test_zip_right_keeps_only_right_values():
    """keeps only right values"""
    result = yield from stream.make(1, 2, 3).zip_right(stream.make("a", "b", "c")).run_collect()
    assert result == ["a", "b", "c"]


@testing.effect
def test_zip_right_terminates_when_left_stream_ends_first():
    """terminates when left stream ends first"""
    result = yield from stream.make(1, 2).zip_right(stream.make("a", "b", "c", "d")).run_collect()
    assert result == ["a", "b"]


@testing.effect
def test_zip_right_terminates_when_right_stream_ends_first():
    """terminates when right stream ends first"""
    result = yield from stream.make(1, 2, 3, 4).zip_right(stream.make("a", "b")).run_collect()
    assert result == ["a", "b"]


@testing.effect
def test_zip_right_handles_empty_left_stream():
    """handles empty left stream"""
    result = yield from stream.empty.zip_right(stream.make("a", "b", "c")).run_collect()
    assert len(result) == 0


@testing.effect
def test_zip_right_handles_empty_right_stream():
    """handles empty right stream"""
    result = yield from stream.make(1, 2, 3).zip_right(stream.empty).run_collect()
    assert len(result) == 0


@testing.effect
def test_zip_right_propagates_errors_from_left_stream():
    """propagates errors from left stream"""
    left = stream.make(1, 2).concat(stream.fail("boom"))
    result = yield from left.zip_right(stream.make("a", "b", "c")).run_collect().exit()
    assert result == fx.exit.fail("boom")


@testing.effect
def test_zip_right_propagates_errors_from_right_stream():
    """propagates errors from right stream"""
    right = stream.make("a", "b").concat(stream.fail("ouch"))
    result = yield from stream.make(1, 2, 3).zip_right(right).run_collect().exit()
    assert result == fx.exit.fail("ouch")


@testing.effect
def test_zip_right_consumes_left_stream_elements():
    """consumes left stream elements"""
    left_pulled = 0

    def count(_: int) -> fx.Effect[None]:
        def bump() -> None:
            nonlocal left_pulled
            left_pulled += 1

        return fx.sync(bump)

    left = stream.make(1, 2, 3).tap(count)
    result = yield from left.zip_right(stream.make("a", "b", "c")).run_collect()
    assert result == ["a", "b", "c"]
    assert left_pulled == 3


# --- zipFlatten -----------------------------------------------------------------


@testing.effect
def test_zip_flatten_flattens_tuples_when_zipping():
    """flattens tuples when zipping"""
    pairs = stream.make((1, "a"), (2, "b"), (3, "c"))
    result = yield from pairs.zip_flatten(stream.make("x", "y", "z")).run_collect()
    assert result == [(1, "a", "x"), (2, "b", "y"), (3, "c", "z")]


@testing.effect
def test_zip_flatten_works_with_single_element_tuples():
    """works with single element tuples"""
    singles = stream.make((1,), (2,), (3,))
    result = yield from singles.zip_flatten(stream.make("a", "b", "c")).run_collect()
    assert result == [(1, "a"), (2, "b"), (3, "c")]


@testing.effect
def test_zip_flatten_works_with_larger_tuples():
    """works with larger tuples"""
    triples = stream.make((1, 2, 3), (4, 5, 6))
    result = yield from triples.zip_flatten(stream.make("a", "b")).run_collect()
    assert result == [(1, 2, 3, "a"), (4, 5, 6, "b")]


@testing.effect
def test_zip_flatten_terminates_when_left_stream_ends_first():
    """terminates when left stream ends first"""
    pairs = stream.make((1, "a"), (2, "b"))
    result = yield from pairs.zip_flatten(stream.make("x", "y", "z", "w")).run_collect()
    assert result == [(1, "a", "x"), (2, "b", "y")]


@testing.effect
def test_zip_flatten_terminates_when_right_stream_ends_first():
    """terminates when right stream ends first"""
    pairs = stream.make((1, "a"), (2, "b"), (3, "c"), (4, "d"))
    result = yield from pairs.zip_flatten(stream.make("x", "y")).run_collect()
    assert result == [(1, "a", "x"), (2, "b", "y")]


def _no_pairs() -> Stream[tuple[int, str]]:
    return stream.empty


@testing.effect
def test_zip_flatten_handles_empty_left_stream():
    """handles empty left stream"""
    result = yield from _no_pairs().zip_flatten(stream.make("a", "b", "c")).run_collect()
    assert len(result) == 0


@testing.effect
def test_zip_flatten_handles_empty_right_stream():
    """handles empty right stream"""
    pairs: Stream[tuple[int, str]] = stream.make((1, "a"), (2, "b"))
    result = yield from pairs.zip_flatten(stream.empty).run_collect()
    assert len(result) == 0


@testing.effect
def test_zip_flatten_propagates_errors_from_left_stream():
    """propagates errors from left stream"""
    pairs = stream.make((1, "a"), (2, "b")).concat(stream.fail("boom"))
    result = yield from pairs.zip_flatten(stream.make("x", "y", "z")).run_collect().exit()
    assert result == fx.exit.fail("boom")


@testing.effect
def test_zip_flatten_propagates_errors_from_right_stream():
    """propagates errors from right stream"""
    pairs = stream.make((1, "a"), (2, "b"), (3, "c"))
    right = stream.make("x", "y").concat(stream.fail("ouch"))
    result = yield from pairs.zip_flatten(right).run_collect().exit()
    assert result == fx.exit.fail("ouch")


# --- zipWithIndex ---------------------------------------------------------------


@testing.effect
def test_zip_with_index_zips_stream_with_indices_starting_at_0():
    """zips stream with indices starting at 0"""
    result = yield from stream.make("a", "b", "c", "d").zip_with_index().run_collect()
    assert result == [("a", 0), ("b", 1), ("c", 2), ("d", 3)]


@testing.effect
def test_zip_with_index_handles_empty_stream():
    """handles empty stream"""
    assert len((yield from stream.empty.zip_with_index().run_collect())) == 0


@testing.effect
def test_zip_with_index_handles_single_element_stream():
    """handles single element stream"""
    assert (yield from stream.make("a").zip_with_index().run_collect()) == [("a", 0)]


@testing.effect
def test_zip_with_index_preserves_order():
    """preserves order"""
    result = yield from stream.make(5, 4, 3, 2, 1).zip_with_index().run_collect()
    assert result == [(5, 0), (4, 1), (3, 2), (2, 3), (1, 4)]


@testing.effect
def test_zip_with_index_works_with_numbers():
    """works with numbers"""
    result = yield from stream.make(10, 20, 30).zip_with_index().run_collect()
    assert result == [(10, 0), (20, 1), (30, 2)]


@testing.effect
def test_zip_with_index_propagates_errors():
    """propagates errors"""
    failing = stream.make(1, 2, 3).concat(stream.fail("boom"))
    result = yield from failing.zip_with_index().run_collect().exit()
    assert result == fx.exit.fail("boom")


@testing.effect
def test_zip_with_index_index_increments_correctly_for_large_streams():
    """index increments correctly for large streams"""
    result = yield from stream.range_inclusive(0, 99).zip_with_index().run_collect()
    assert len(result) == 100
    assert result[0] == (0, 0)
    assert result[99] == (99, 99)


# --- zipLatest ------------------------------------------------------------------


@testing.effect
def test_zip_latest_completes_with_no_pairs_when_the_left_stream_is_empty():
    """completes with no pairs when the left stream is empty"""
    assert (yield from stream.empty.zip_latest(stream.succeed(1)).run_collect()) == []


@testing.effect
def test_zip_latest_completes_with_no_pairs_when_the_right_stream_is_empty():
    """completes with no pairs when the right stream is empty"""
    assert (yield from stream.succeed(1).zip_latest(stream.empty).run_collect()) == []


def _pairs(result: list[tuple[Any, Any]]) -> bool:
    return len(result) > 0 and all(len(item) == 2 for item in result)


@testing.effect
def test_zip_latest_combines_streams_with_latest_values():
    """combines streams with latest values"""
    zipped = stream.make(1, 2, 3).zip_latest(stream.make("a", "b", "c", "d"))
    assert _pairs((yield from zipped.run_collect()))


@testing.effect
def test_zip_latest_waits_for_both_streams_to_emit_before_producing_output():
    """waits for both streams to emit before producing output"""
    queue1 = yield from Queue[int, Done].unbounded()
    queue2 = yield from Queue[str, Done].unbounded()
    zipped = stream.from_queue(queue1).zip_latest(stream.from_queue(queue2))
    fiber = yield from zipped.take(3).run_collect().fork_scoped()
    yield from queue1.offer(1)
    yield from queue2.offer("a")
    yield from queue1.offer(2)
    yield from queue2.offer("b")
    yield from queue1.offer(3)
    assert len((yield from fiber.join())) > 0


@testing.effect
def test_zip_latest_propagates_errors_from_left_stream():
    """propagates errors from left stream"""
    left = stream.make(1, 2).concat(stream.fail("boom"))
    result = yield from left.zip_latest(stream.make("a", "b", "c")).run_collect().exit()
    assert result == fx.exit.fail("boom")


@testing.effect
def test_zip_latest_propagates_errors_from_right_stream():
    """propagates errors from right stream"""
    right = stream.make("a", "b").concat(stream.fail("ouch"))
    result = yield from stream.make(1, 2, 3).zip_latest(right).run_collect().exit()
    assert result == fx.exit.fail("ouch")


@testing.effect
def test_zip_latest_terminates_when_left_stream_ends():
    """terminates when left stream ends"""
    zipped = stream.make(1, 2).zip_latest(stream.make("a", "b", "c", "d", "e"))
    assert len((yield from zipped.run_collect())) > 0


@testing.effect
def test_zip_latest_terminates_when_right_stream_ends():
    """terminates when right stream ends"""
    zipped = stream.make(1, 2, 3, 4, 5).zip_latest(stream.make("a", "b"))
    assert len((yield from zipped.run_collect())) > 0


@testing.effect
def test_zip_latest_basic_synchronous_example():
    """basic synchronous example"""
    zipped = stream.make(1, 2, 3).zip_latest(stream.make("a", "b", "c"))
    assert _pairs((yield from zipped.run_collect()))


# --- zipLatestWith --------------------------------------------------------------


def _multiply(n: int, m: int) -> int:
    return n * m


def _add(n: int, m: int) -> int:
    return n + m


def _dash(n: int, s: str) -> str:
    return f"{n}-{s}"


@testing.effect
def test_zip_latest_with_transforms_combined_values():
    """transforms combined values"""
    zipped = stream.make(1, 2, 3).zip_latest_with(stream.make(10, 20, 30), _multiply)
    result = yield from zipped.run_collect()
    assert len(result) > 0
    assert all(isinstance(item, int) for item in result)


@testing.effect
def test_zip_latest_with_combines_with_custom_function():
    """combines with custom function"""
    zipped = stream.make(1, 2, 3).zip_latest_with(stream.make("a", "b", "c"), _dash)
    result = yield from zipped.run_collect()
    assert len(result) > 0
    assert all("-" in item for item in result)


@testing.effect
def test_zip_latest_with_propagates_errors_from_left_stream():
    """propagates errors from left stream"""
    left = stream.make(1, 2).concat(stream.fail("boom"))
    zipped = left.zip_latest_with(stream.make("a", "b", "c"), _dash)
    assert (yield from zipped.run_collect().exit()) == fx.exit.fail("boom")


@testing.effect
def test_zip_latest_with_propagates_errors_from_right_stream():
    """propagates errors from right stream"""
    right = stream.make("a", "b").concat(stream.fail("ouch"))
    zipped = stream.make(1, 2, 3).zip_latest_with(right, _dash)
    assert (yield from zipped.run_collect().exit()) == fx.exit.fail("ouch")


@testing.effect
def test_zip_latest_with_terminates_when_left_stream_ends():
    """terminates when left stream ends"""
    zipped = stream.make(1, 2).zip_latest_with(stream.make(10, 20, 30, 40), _add)
    assert len((yield from zipped.run_collect())) > 0


@testing.effect
def test_zip_latest_with_terminates_when_right_stream_ends():
    """terminates when right stream ends"""
    zipped = stream.make(1, 2, 3, 4).zip_latest_with(stream.make(10, 20), _add)
    assert len((yield from zipped.run_collect())) > 0


@testing.effect
def test_zip_latest_with_basic_synchronous_example():
    """basic synchronous example"""
    zipped = stream.make(1, 2, 3).zip_latest_with(stream.make(10, 20, 30), _add)
    result = yield from zipped.run_collect()
    assert len(result) > 0
    assert all(isinstance(item, int) for item in result)


@testing.effect
def test_zip_latest_with_string_concatenation_example():
    """string concatenation example"""
    zipped = stream.make("Alice", "Bob", "Charlie").zip_latest_with(
        stream.make("Smith", "Jones"), lambda first, last: f"{first} {last}"
    )
    result = yield from zipped.run_collect()
    assert len(result) > 0
    assert all(" " in item for item in result)
