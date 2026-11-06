"""Ports of Effect's ``Stream.test.ts``: the ``filtering``, ``taking``,
``dropping``, ``scanning``, ``sliding``, ``split``, ``intersperse``,
``when`` and ``zipWithNext`` sections and the two ``rechunk`` titles.

Each test's docstring is the Effect test title. Effect's inclusive
``Stream.range(a, b)`` is ``stream.range(a, b)``, chunks and
windows are tuples, ``Option.some(x)`` is ``Some(x)`` and ``Option.none()``
is ``None``, and a ``Filter`` is a function returning ``Ok`` / ``Err``.

Adapted, with the reason:

- Counts and sizes are ``int``s, so the normalization titles pass ``-1``,
  ``0``, ``1`` and ``2`` where Effect passes ``NaN``, ``0.5``, ``1.9`` and
  ``2.9`` (pyright rejects ``NaN`` and fractions; below zero is zero for a
  count and one for a size, as Effect's ``Count.normalize``).
- ``limitBytes`` takes a byte count (Effect's ``ByteSize.Input`` is ``"5 B"``
  or ``ByteSize.bytes(5)``).
- Defects are exceptions, so "when - dies if the condition throws an
  exception" raises ``ValueError("boom")`` where Effect throws a string.
- The two fast-check properties of ``zipWithPrevious`` /
  ``zipWithPreviousAndNext`` run over 200 seeded random chunk layouts (no
  property-testing dependency).
"""

import itertools
import random
from typing import Any

import pyfect as fx
from pyfect import stream, testing
from pyfect.option import Some
from pyfect.result import Err, Ok

# --- filtering ------------------------------------------------------------------


@testing.effect
def test_filter_map():
    """filterMap"""
    result = yield from (
        stream.make(1, 2, 3, 4)
        .filter_map(lambda n: Ok(n + 10) if n % 2 == 0 else Err(None))
        .run_collect()
    )
    assert result == [12, 14]


@testing.effect
def test_filter_map_effect():
    """filterMapEffect"""
    result = yield from (
        stream.make(1, 2, 3, 4)
        .filter_map_effect(lambda n: fx.succeed(Ok(n + 1) if n % 2 == 0 else Err(None)))
        .run_collect()
    )
    assert result == [3, 5]


# --- taking ---------------------------------------------------------------------


def _limit_fallback(evaluated: list[bool]) -> stream.Stream[bytes]:
    evaluated.append(True)
    return stream.empty


@testing.effect
def test_limit_bytes_does_not_evaluate_the_fallback_below_the_limit():
    """limitBytes - does not evaluate the fallback below the limit"""
    evaluated: list[bool] = []
    chunks = [bytes([1, 2]), bytes([3, 4])]
    result = yield from (
        stream.from_iterable(chunks)
        .limit_bytes(5, lambda: _limit_fallback(evaluated))
        .run_collect()
    )
    assert result == chunks
    assert not evaluated


@testing.effect
def test_limit_bytes_does_not_evaluate_the_fallback_at_the_limit():
    """limitBytes - does not evaluate the fallback at the limit"""
    evaluated: list[bool] = []
    chunks = [bytes([1, 2]), bytes([3, 4])]
    result = yield from (
        stream.from_iterable(chunks)
        .limit_bytes(4, lambda: _limit_fallback(evaluated))
        .run_collect()
    )
    assert result == chunks
    assert not evaluated


@testing.effect
def test_limit_bytes_drops_the_crossing_chunk_and_switches_to_the_fallback():
    """limitBytes - drops the crossing chunk and switches to the fallback"""
    first, crossing, after, fallback = bytes([1, 2]), bytes([3, 4, 5, 6]), bytes([7]), b"\x08\x09"
    result = yield from (
        stream.make(first, crossing, after)
        .limit_bytes(5, lambda: stream.succeed(fallback))
        .run_collect()
    )
    assert result == [first, fallback]


@testing.effect
def test_take_pulls_the_first_n_values_from_a_stream():
    """take - pulls the first `n` values from a stream"""
    result = yield from stream.range(1, 5).take(3).run_collect()
    assert result == [1, 2, 3]


@testing.effect
def test_take_rounds_positive_fractional_counts_down():
    """take - rounds positive fractional counts down"""
    results = yield from fx.for_each(
        [0, 1, 2], lambda n: stream.make(1, 2, 3).take(n).run_collect()
    )
    assert results == [[], [1], [1, 2]]


@testing.effect
def test_take_short_circuits_stream_evaluation():
    """take - short-circuits stream evaluation"""
    result = yield from stream.succeed(1).concat(stream.never).take(1).run_collect()
    assert result == [1]


@testing.effect
def test_take_taking_0_short_circuits_stream_evaluation():
    """take - taking 0 short-circuits stream evaluation"""
    result = yield from stream.never.take(0).run_collect()
    assert result == []


@testing.effect
def test_take_treating_nan_as_a_non_positive_count():
    """take - treating NaN as a non-positive count"""
    result = yield from stream.make(1, 2, 3).take(-1).run_collect()
    assert result == []


@testing.effect
def test_take_nan_short_circuits_stream_evaluation():
    """take - NaN short-circuits stream evaluation"""
    result = yield from stream.never.take(-1).run_collect()
    assert result == []


@testing.effect
def test_take_until_takes_elements_until_a_predicate_is_satisfied():
    """takeUntil - takes elements until a predicate is satisfied"""
    result = yield from stream.range(1, 5).take_until(lambda n: n % 3 == 0).run_collect()
    assert result == [1, 2, 3]


@testing.effect
def test_take_while_takes_elements_while_a_predicate_is_satisfied():
    """takeWhile - takes elements while a predicate is satisfied"""
    result = yield from stream.range(1, 5).take_while(lambda n: n % 3 != 0).run_collect()
    assert result == [1, 2]


@testing.effect
def test_take_while_filter_takes_elements_while_a_filter_succeeds():
    """takeWhileFilter - takes elements while a filter succeeds"""
    result = yield from (
        stream.range(1, 5)
        .take_while_filter(lambda n: Ok(n + 10) if n < 3 else Err(None))
        .run_collect()
    )
    assert result == [11, 12]


@testing.effect
def test_take_until_effect_takes_elements_until_an_effectful_predicate_is_satisfied():
    """takeUntilEffect - takes elements until an effectful predicate is satisfied"""
    result = yield from (
        stream.range(1, 5).take_until_effect(lambda n: fx.succeed(n % 3 == 0)).run_collect()
    )
    assert result == [1, 2, 3]


@testing.effect
def test_take_while_effect_takes_elements_while_an_effectful_predicate_is_satisfied():
    """takeWhileEffect - takes elements while an effectful predicate is satisfied"""
    result = yield from (
        stream.range(1, 5).take_while_effect(lambda n: fx.succeed(n % 3 != 0)).run_collect()
    )
    assert result == [1, 2]


@testing.effect
def test_take_right():
    """takeRight"""
    numbers = stream.range(1, 5)
    result1 = yield from numbers.take_right(3).run_collect()
    result2 = yield from numbers.run_collect()
    assert result1 == result2[-3:]


@testing.effect
def test_take_right_normalizes_the_element_count():
    """takeRight - normalizes the element count"""
    results = yield from fx.for_each(
        [-1, -1, 0, 1, 2], lambda n: stream.make(1, 2, 3).take_right(n).run_collect()
    )
    assert results == [[], [], [], [3], [2, 3]]


@testing.effect
def test_take_right_zero_normalized_counts_do_not_evaluate_the_upstream():
    """takeRight - zero normalized counts do not evaluate the upstream"""
    upstream = stream.from_effect(fx.die(RuntimeError("upstream evaluated")))
    result = yield from upstream.take_right(-1).run_collect()
    assert result == []


# --- dropping -------------------------------------------------------------------


@testing.effect
def test_drop_simple_example():
    """drop - simple example"""
    numbers = stream.make(1, 2, 3, 4, 5)
    result1 = yield from numbers.drop(2).run_collect()
    result2 = yield from numbers.run_collect()
    assert result1 == result2[2:]


@testing.effect
def test_drop_normalizes_the_count_independently_of_upstream_chunking():
    """drop - normalizes the count independently of upstream chunking"""
    sources = [stream.make(1, 2, 3), stream.from_arrays([1], [2], [3])]
    results = yield from fx.for_each(
        sources, lambda s: fx.for_each([-1, 0, 1, 2], lambda n: s.drop(n).run_collect())
    )
    assert results == [[[1, 2, 3], [1, 2, 3], [2, 3], [3]]] * 2


@testing.effect
def test_drop_does_not_swallow_errors():
    """drop - does not swallow errors"""
    result = yield from stream.fail("Ouch").concat(stream.make(1)).drop(1).run_drain().result()
    testing.assert_failure(result, "Ouch")


@testing.effect
def test_drop_right_simple_example():
    """dropRight - simple example"""
    numbers = stream.make(1, 2, 3, 4, 5)
    result1 = yield from numbers.drop_right(2).run_collect()
    result2 = yield from numbers.run_collect()
    assert result1 == result2[:-2]


@testing.effect
def test_drop_right_normalizes_the_element_count():
    """dropRight - normalizes the element count"""
    results = yield from fx.for_each(
        [-1, 0, 1, 2], lambda n: stream.make(1, 2, 3).drop_right(n).run_collect()
    )
    assert results == [[1, 2, 3], [1, 2, 3], [1, 2], [1]]


@testing.effect
def test_drop_right_does_not_swallow_errors():
    """dropRight - does not swallow errors"""
    result = (
        yield from stream.make(1).concat(stream.fail("Ouch")).drop_right(1).run_drain().result()
    )
    testing.assert_failure(result, "Ouch")


@testing.effect
def test_drop_until():
    """dropUntil"""
    numbers = stream.make(1, 2, 3, 4, 5)
    result1 = yield from numbers.drop_until(lambda n: n < 3).run_collect()
    items = yield from numbers.run_collect()
    assert result1 == list(itertools.dropwhile(lambda n: not n < 3, items))[1:]


@testing.effect
def test_drop_while():
    """dropWhile"""
    result = yield from stream.make(1, 2, 3, 4, 5).drop_while(lambda n: n < 3).run_collect()
    assert result == [3, 4, 5]


@testing.effect
def test_drop_while_filter():
    """dropWhileFilter"""
    result = yield from (
        stream.make(1, 2, 3, 4, 5)
        .drop_while_filter(lambda n: Ok(n) if n < 3 else Err(None))
        .run_collect()
    )
    assert result == [3, 4, 5]


@testing.effect
def test_drop_while_short_circuits():
    """dropWhile - short circuits"""
    result = yield from (
        stream.make(1)
        .concat(stream.fail("Ouch"))
        .take(1)
        .drop_while(lambda _: True)
        .run_drain()
        .result()
    )
    testing.assert_success(result, None)


# --- scanning -------------------------------------------------------------------


def _scan(items: list[int]) -> list[int]:
    out = [0]
    for item in items:
        out.append(out[-1] + item)
    return out


@testing.effect
def test_scan_emits_the_initial_state_for_stream_empty():
    """scan emits the initial state for Stream.empty"""
    empty: stream.Stream[int] = stream.empty
    result = yield from empty.scan(lambda: 0, lambda acc, n: acc + n).run_collect()
    assert result == [0]


@testing.effect
def test_scan():
    """scan"""
    numbers = stream.make(1, 2, 3, 4, 5)
    result = yield from numbers.scan(lambda: 0, lambda acc, n: acc + n).run_collect()
    assert result == _scan((yield from numbers.run_collect()))


@testing.effect
def test_scan_effect():
    """scanEffect"""
    result = yield from (
        stream.make(1, 2, 3, 4, 5)
        .scan_effect(lambda: 0, lambda acc, n: fx.succeed(acc + n))
        .run_collect()
    )
    assert result == _scan([1, 2, 3, 4, 5])


@testing.effect
def test_map_accum_preserves_large_callback_results_in_order():
    """mapAccum preserves large callback results in order"""
    values = list(range(200_000))
    result = yield from stream.make(1).map_accum(lambda: 0, lambda s, _: (s, values)).run_collect()
    assert result == values


@testing.effect
def test_map_accum_array_effect_data_first():
    """mapAccumArrayEffect data-first"""
    result = yield from (
        stream.make(1, 2, 3)
        .map_accum_array_effect(
            lambda: 0, lambda total, chunk: fx.succeed((total + len(chunk), chunk))
        )
        .run_collect()
    )
    assert result == [1, 2, 3]


# --- rechunk --------------------------------------------------------------------


@testing.effect
def test_rechunk_preserves_large_input_split_across_source_chunks():
    """rechunk preserves large input split across source chunks"""
    values = list(range(200_001))
    actual = yield from (
        stream.from_arrays(values[:1], values[1:]).rechunk(200_002).chunks().run_collect()
    )
    assert [len(chunk) for chunk in actual] == [200_001]
    assert [item for chunk in actual for item in chunk] == values


@testing.effect
def test_rechunk_and_grouped_normalize_their_chunk_size():
    """rechunk and grouped normalize their chunk size"""
    sizes = [-1, 0, 1, 2]
    rechunked = yield from fx.for_each(
        sizes, lambda n: stream.make(1, 2, 3).rechunk(n).chunks().run_collect()
    )
    grouped = yield from fx.for_each(sizes, lambda n: stream.make(1, 2, 3).grouped(n).run_collect())
    expected = [[(1,), (2,), (3,)]] * 3 + [[(1, 2), (3,)]]
    assert rechunked == expected
    assert grouped == expected


# --- sliding --------------------------------------------------------------------


@testing.effect
def test_sliding_and_sliding_size_normalize_window_and_step_sizes():
    """sliding and slidingSize normalize window and step sizes"""
    sizes = [-1, 0, 1, 2]
    windows = yield from fx.for_each(sizes, lambda n: stream.make(1, 2, 3).sliding(n).run_collect())
    steps = yield from fx.for_each(
        sizes, lambda n: stream.make(1, 2, 3).sliding_size(2, n).run_collect()
    )
    assert windows == [[(1,), (2,), (3,)]] * 3 + [[(1, 2), (2, 3)]]
    assert steps == [[(1, 2), (2, 3)]] * 3 + [[(1, 2), (3,)]]


@testing.effect
def test_sliding_returns_a_sliding_window():
    """sliding - returns a sliding window"""
    empty: stream.Stream[int] = stream.empty
    sources = [
        stream.make(1, 2, 3, 4, 5),
        stream.from_arrays([], [1], [], [2, 3, 4, 5]),
        empty.concat(stream.make(1))
        .concat(stream.empty)
        .concat(stream.make(2))
        .concat(stream.make(3, 4, 5)),
        stream.make(1)
        .concat(stream.empty)
        .concat(stream.make(2))
        .concat(stream.empty)
        .concat(stream.make(3, 4, 5)),
        stream.make(1).concat(stream.make(2)).concat(stream.make(3, 4, 5)),
    ]
    for source in sources:
        result = yield from source.sliding(2).run_collect()
        assert result == [(1, 2), (2, 3), (3, 4), (4, 5)]


@testing.effect
def test_sliding_returns_all_elements_if_chunk_size_is_greater_than_the_size_of_the_stream():
    """sliding - returns all elements if chunkSize is greater than the size of the stream"""
    result = yield from stream.range(1, 5).sliding(6).run_collect()
    assert result == [(1, 2, 3, 4, 5)]


@testing.effect
def test_sliding_is_mostly_equivalent_to_zstream_grouped_when_step_size_and_chunk_size_are_equal():
    """sliding - is mostly equivalent to ZStream#grouped when stepSize and chunkSize are equal"""
    numbers = stream.range(1, 5)
    result1 = yield from numbers.sliding_size(3, 3).run_collect()
    result2 = yield from numbers.grouped(3).run_collect()
    assert result1 == result2


@testing.effect
def test_sliding_size_is_independent_of_upstream_chunk_boundaries():
    """slidingSize is independent of upstream chunk boundaries"""
    sources = [
        stream.make(1, 2, 3, 4, 5),
        stream.from_arrays([1, 2], [3, 4, 5]),
        stream.from_arrays([1], [2], [3], [4], [5]),
        stream.from_arrays([1], [2], [3], [4]),
    ]
    results = yield from fx.for_each(sources, lambda s: s.sliding_size(2, 3).run_collect())
    assert results == [[(1, 2), (4, 5)]] * 3 + [[(1, 2), (4,)]]


@testing.effect
def test_sliding_size_keeps_all_elements_of_the_final_partial_window():
    """slidingSize keeps all elements of the final partial window"""
    result = yield from stream.make(1, 2, 3, 4, 5, 6).sliding_size(3, 2).run_collect()
    assert result == [(1, 2, 3), (3, 4, 5), (5, 6)]


@testing.effect
def test_sliding_fails_if_upstream_produces_an_error():
    """sliding - fails if upstream produces an error"""
    result = yield from (
        stream.make(1, 2, 3)
        .concat(stream.fail("Ouch"))
        .concat(stream.make(4, 5))
        .sliding(2)
        .run_collect()
        .flip()
    )
    assert result == "Ouch"


@testing.effect
def test_sliding_should_return_an_empty_chunk_when_the_stream_is_empty():
    """sliding - should return an empty chunk when the stream is empty"""
    result = yield from stream.empty.sliding(2).run_collect()
    assert result == []


@testing.effect
def test_sliding_emits_elements_properly_when_a_failure_occurs():
    """sliding - emits elements properly when a failure occurs"""
    seen: list[tuple[int, ...]] = []
    windows = (
        stream.from_arrays([1, 2, 3, 4], [5, 6, 7], [8])
        .concat(stream.fail("Ouch"))
        .sliding_size(3, 3)
    )
    error = (
        yield from windows.map_effect(lambda w: fx.sync(lambda: seen.append(w)))
        .run_collect()
        .flip()
    )
    assert error == "Ouch"
    assert seen == [(1, 2, 3), (4, 5, 6), (7, 8)]


# --- split ----------------------------------------------------------------------


@testing.effect
def test_split_should_split_properly():
    """split - should split properly"""
    result1 = yield from stream.range(0, 9).split(lambda n: n % 4 == 0).run_collect()
    result2 = yield from (
        stream.from_arrays([1, 2], [3, 4], [5, 6], [7, 8, 9], [10])
        .split(lambda n: n % 3 == 0)
        .run_collect()
    )
    assert result1 == [(1, 2, 3), (5, 6, 7), (9,)]
    assert result2 == [(1, 2), (4, 5), (7, 8), (10,)]


@testing.effect
def test_split_is_equivalent_to_identity_when_the_predicate_is_not_satisfied():
    """split - is equivalent to identity when the predicate is not satisfied"""
    result = yield from stream.range(1, 10).split(lambda n: n % 11 == 0).run_collect()
    assert result == [tuple(range(1, 11))]


@testing.effect
def test_split_should_output_empty_chunk_when_stream_is_empty():
    """split - should output empty chunk when stream is empty"""
    empty: stream.Stream[int] = stream.empty
    result = yield from empty.split(lambda n: n % 11 == 0).run_collect()
    assert result == []


# --- intersperse ----------------------------------------------------------------


@testing.effect
def test_intersperse_several_values():
    """intersperse - several values"""
    result = yield from stream.make(1, 2, 3, 4).map(str).intersperse(".").run_collect()
    assert result == ["1", ".", "2", ".", "3", ".", "4"]


@testing.effect
def test_intersperse_affixes_several_values():
    """intersperseAffixes - several values"""
    result = yield from (
        stream.make(1, 2, 3, 4).map(str).intersperse_affixes(start="[", middle=".", end="]")
    ).run_collect()
    assert result == ["[", "1", ".", "2", ".", "3", ".", "4", "]"]


@testing.effect
def test_intersperse_single_value():
    """intersperse - single value"""
    result = yield from stream.make(1).map(str).intersperse(".").run_collect()
    assert result == ["1"]


@testing.effect
def test_intersperse_affixes_single_value():
    """intersperseAffixes - single value"""
    result = yield from (
        stream.make(1).map(str).intersperse_affixes(start="[", middle=".", end="]").run_collect()
    )
    assert result == ["[", "1", "]"]


@testing.effect
def test_intersperse_several_from_repeat_effect_zio_3729():
    """intersperse - several from repeat effect (ZIO #3729)"""
    result = yield from (
        stream.from_effect_repeat(fx.succeed(42)).map(str).take(4).intersperse(".").run_collect()
    )
    assert result == ["42", ".", "42", ".", "42", ".", "42"]


@testing.effect
def test_intersperse_several_from_repeat_effect_chunk_single_element_zio_3729():
    """intersperse - several from repeat effect chunk single element (ZIO #3729)"""
    result = yield from (
        stream.from_iterable_effect_repeat(fx.succeed([42]))
        .map(str)
        .intersperse(".")
        .take(4)
        .run_collect()
    )
    assert result == ["42", ".", "42", "."]


# --- when -----------------------------------------------------------------------


@testing.effect
def test_when_returns_the_stream_if_the_condition_is_satisfied():
    """when - returns the stream if the condition is satisfied"""
    numbers = stream.make(1, 2, 3, 4, 5)
    result1 = yield from numbers.when(fx.succeed(True)).run_collect()
    assert result1 == (yield from numbers.run_collect())


@testing.effect
def test_when_returns_an_empty_stream_if_the_condition_is_not_satisfied():
    """when - returns an empty stream if the condition is not satisfied"""
    result = yield from stream.make(1, 2, 3, 4, 5).when(fx.succeed(False)).run_collect()
    assert result == []


@testing.effect
def test_when_dies_if_the_condition_throws_an_exception():
    """when - dies if the condition throws an exception"""
    error = ValueError("boom")

    def boom() -> bool:
        raise error

    result = yield from stream.make(1, 2, 3).when(fx.sync(boom)).run_drain().exit()
    assert result == fx.exit.die(error)


@testing.effect
def test_when_returns_the_stream_if_the_effectful_condition_is_satisfied():
    """when - returns the stream if the effectful condition is satisfied"""
    result = yield from stream.make(1, 2, 3, 4, 5).when(fx.succeed(True)).run_collect()
    assert result == [1, 2, 3, 4, 5]


@testing.effect
def test_when_returns_an_empty_stream_if_the_effectful_condition_is_not_satisfied():
    """when - returns an empty stream if the effectful condition is not satisfied"""
    result = yield from stream.make(1, 2, 3, 4, 5).when(fx.succeed(False)).run_collect()
    assert result == []


@testing.effect
def test_when_fails_if_the_effectful_condition_fails():
    """when - fails if the effectful condition fails"""
    result = yield from stream.make(1, 2, 3).when(fx.fail("boom")).run_drain().exit()
    assert result == fx.exit.fail("boom")


# --- zipWithNext ----------------------------------------------------------------


@testing.effect
def test_zip_with_next():
    """zipWithNext"""
    result = yield from stream.make(1, 2, 3).zip_with_next().run_collect()
    assert result == [(1, Some(2)), (2, Some(3)), (3, None)]


@testing.effect
def test_zip_with_next_should_work_with_multiple_chunks():
    """zipWithNext - should work with multiple chunks"""
    result = yield from stream.from_arrays([1], [2], [3]).zip_with_next().run_collect()
    assert result == [(1, Some(2)), (2, Some(3)), (3, None)]


@testing.effect
def test_zip_with_next_should_work_with_an_empty_stream():
    """zipWithNext - should work with an empty stream"""
    result = yield from stream.empty.zip_with_next().run_collect()
    assert result == []


@testing.effect
def test_zip_with_previous_should_zip_with_previous_element_for_a_single_chunk():
    """zipWithPrevious - should zip with previous element for a single chunk"""
    result = yield from stream.make(1, 2, 3).zip_with_previous().run_collect()
    assert result == [(None, 1), (Some(1), 2), (Some(2), 3)]


@testing.effect
def test_zip_with_previous_should_work_with_multiple_chunks():
    """zipWithPrevious - should work with multiple chunks"""
    result = yield from stream.from_arrays([1], [2], [3]).zip_with_previous().run_collect()
    assert result == [(None, 1), (Some(1), 2), (Some(2), 3)]


@testing.effect
def test_zip_with_previous_should_work_with_an_empty_stream():
    """zipWithPrevious - should work with an empty stream"""
    result = yield from stream.empty.zip_with_previous().run_collect()
    assert result == []


def _random_layouts(max_chunks: int) -> list[list[list[int]]]:
    rng = random.Random(0)
    return [
        [
            [rng.randint(-100, 100) for _ in range(rng.randint(0, 4))]
            for _ in range(rng.randint(0, max_chunks))
        ]
        for _ in range(200)
    ]


def _some(value: Any) -> Any:
    return Some(value)


@testing.effect
def test_zip_with_previous_should_output_same_values_as_first_element_plus_zipping_with_init():
    """zipWithPrevious - should output same values as first element plus zipping with init"""
    for chunks in _random_layouts(6):
        source = stream.from_arrays(*chunks)
        result1 = yield from source.zip_with_previous().run_collect()
        previous: stream.Stream[Any] = stream.make(None).concat(source.map(_some))
        result2 = yield from previous.zip(source).run_collect()
        assert result1 == result2


@testing.effect
def test_zip_with_previous_and_next():
    """zipWithPreviousAndNext"""
    result = yield from stream.make(1, 2, 3).zip_with_previous_and_next().run_collect()
    assert result == [(None, 1, Some(2)), (Some(1), 2, Some(3)), (Some(2), 3, None)]


@testing.effect
def test_zip_with_previous_and_next_matches_zipping_with_previous_and_next():
    """zipWithPreviousAndNext - should output same values as zipping with both previous and next element"""  # noqa: E501
    for chunks in _random_layouts(5):
        source = stream.from_arrays(*chunks)
        previous: stream.Stream[Any] = stream.make(None).concat(source.map(_some))
        following: stream.Stream[Any] = source.drop(1).map(_some).concat(stream.make(None))
        result1 = yield from source.zip_with_previous_and_next().run_collect()
        result2 = yield from previous.zip(source).zip_flatten(following).run_collect()
        assert result1 == result2
