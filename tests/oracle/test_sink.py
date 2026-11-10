"""Ports of Effect's ``Sink.test.ts``.

Each test's docstring is the Effect test title. Effect's inclusive
``Stream.range(a, b)`` is ``stream.range(a, b)``, ``fromArray``
is ``from_iterable``, a ``Filter`` is a function returning ``Ok`` / ``Err``
and durations are seconds.

Adapted, with the reason:

- "normalizes the maximum element count" (``foldUntil``) and "normalizes
  the element count" (``take``) pass ``-1``, ``0``, ``1`` and ``2`` where
  Effect passes ``NaN`` and fractions: counts are ``int``, so pyright
  rejects ``NaN`` and fractions. "zero normalized counts do not evaluate
  the upstream" passes ``0`` for the same reason.

Not ported:

- The three ``fromWritableStream`` titles: Web Streams have no Python
  counterpart (PARITY.md); ``sink.from_queue``, ``from_pubsub`` and
  ``for_each`` are how a sink writes elsewhere.
"""

from collections.abc import Generator
from typing import Any

import pyfect as fx
from pyfect import cause, sink, stream, testing
from pyfect.duration import seconds, to_millis
from pyfect.option import Option, Some
from pyfect.result import Err, Ok, Result
from pyfect.stream import Stream

# --- constructors ----------------------------------------------------------------


@testing.effect
def test_make_uses_the_pipeline_success_value_as_the_sink_result():
    """make uses the pipeline success value as the sink result"""

    def pipeline(source: Stream[int]) -> fx.Effect[int]:
        return source.run_sum()

    ex = yield from stream.make(1, 2, 3).run(sink.make(pipeline)).exit()
    testing.assert_exit_success(ex, 6)


# --- reduceWhile -------------------------------------------------------------------


def _add(x: int, y: int) -> int:
    return x + y


@testing.effect
def test_reduce_while_empty():
    """empty"""
    reducer = sink.reduce_while(lambda: 0, lambda _: True, _add)
    empty: Stream[int] = stream.empty
    result = yield from empty.transduce(reducer).run_collect()
    assert result == [0]


@testing.effect
def test_reduce_while_termination_in_the_middle():
    """termination in the middle"""
    reducer = sink.reduce_while(lambda: 0, lambda n: n <= 5, _add)
    assert (yield from stream.range(1, 9).run(reducer)) == 6


@testing.effect
def test_reduce_while_immediate_termination():
    """immediate termination"""
    reducer = sink.reduce_while(lambda: 0, lambda n: n <= -1, _add)
    assert (yield from stream.range(1, 9).run(reducer)) == 0


@testing.effect
def test_reduce_while_no_termination():
    """no termination"""
    reducer = sink.reduce_while(lambda: 0, lambda n: n <= 500, _add)
    assert (yield from stream.range(1, 9).run(reducer)) == 45


# --- reduceWhileArray --------------------------------------------------------------


@testing.effect
def test_reduce_while_array_applies_the_reducer_once_per_non_empty_input_array():
    """applies the reducer once per non-empty input array"""

    def count_arrays(count: int, _chunk: tuple[int, ...]) -> int:
        return count + 1

    result = yield from stream.from_arrays([1, 2, 3]).run(
        sink.reduce_while_array(lambda: 0, lambda _: True, count_arrays)
    )
    assert result == 1, "the reducer must run once for each input array"


# --- reduceWhileEffect -------------------------------------------------------------


@testing.effect
def test_reduce_while_effect_short_circuits():
    """short circuits"""

    def run(
        source: Stream[int, str],
    ) -> fx.Effect[fx.Exit[tuple[list[int], list[int]], str]]:
        def body() -> Generator[fx.Effect[Any, Any], Any, tuple[list[int], list[int]]]:
            ref = yield fx.Ref.make(list[int]())

            def step(_: int, y: int) -> fx.Effect[int]:
                def append(items: list[int]) -> list[int]:
                    return [*items, y]

                return ref.update(append).as_(30)

            result = yield source.transduce(
                sink.reduce_while_effect(lambda: 0, lambda _: True, step)
            ).run_collect()
            return (result, (yield ref.get()))

        return fx.gen(body).exit()

    empty: Stream[int, str] = stream.empty
    testing.assert_exit_success((yield from run(empty)), ([0], []))
    testing.assert_exit_success((yield from run(stream.make(1))), ([30], [1]))
    testing.assert_exit_success((yield from run(stream.make(1, 2))), ([30], [1, 2]))
    testing.assert_exit_failure((yield from run(stream.fail("Ouch"))), cause.fail("Ouch"))


# --- reduce ------------------------------------------------------------------------


@testing.effect
def test_reduce_equivalence_with_array_reduce():
    """equivalence with Array.reduce"""
    source = stream.range(1, 9)
    result1 = yield from source.run(sink.reduce(lambda: "", lambda s, n: s + f"{n}"))
    collected = yield from source.run_collect()
    assert result1 == "".join(f"{n}" for n in collected)


# --- foldUntil ---------------------------------------------------------------------


def _count_up(count: int, _: int) -> fx.Effect[int]:
    return fx.succeed(count + 1)


@testing.effect
def test_fold_until_normalizes_the_maximum_element_count():
    """normalizes the maximum element count"""
    results: list[int] = []
    for max_count in [-1, 0, 1, 2]:
        result = yield from stream.make(1, 2, 3).run(
            sink.fold_until(lambda: 0, max_count, _count_up)
        )
        results.append(result)
    assert results == [0, 0, 1, 2]


@testing.effect
def test_fold_until_zero_normalized_counts_do_not_evaluate_the_upstream():
    """zero normalized counts do not evaluate the upstream"""
    initializations = 0

    def initial() -> int:
        nonlocal initializations
        initializations += 1
        return 42

    folder = sink.fold_until(initial, 0, _count_up)
    assert initializations == 0
    upstream: Stream[int] = stream.from_effect(fx.die(RuntimeError("upstream evaluated")))
    assert (yield from upstream.run(folder)) == 42
    assert initializations == 1


# --- collect -----------------------------------------------------------------------


@testing.effect
def test_collect_collects_a_large_input_chunk():
    """collects a large input chunk"""
    values = list(range(200_000))
    assert (yield from stream.from_iterable(values).run(sink.collect())) == values


# --- take --------------------------------------------------------------------------


@testing.effect
def test_take_collects_a_large_input_chunk():
    """collects a large input chunk"""
    values = list(range(200_000))
    assert (yield from stream.from_iterable(values).run(sink.take(len(values)))) == values


@testing.effect
def test_take_normalizes_the_element_count():
    """normalizes the element count"""
    results = yield from fx.for_each([-1, 0, 1], lambda n: stream.make(1, 2, 3).run(sink.take(n)))
    assert results == [[], [], [1]]


@testing.effect
def test_take_respects_the_given_limit():
    """respects the given limit"""
    result = yield from stream.make(1, 2, 3, 4).transduce(sink.take(3)).run_collect()
    assert result == [[1, 2, 3], [4]]


@testing.effect
def test_take_produces_empty_trailing_chunks():
    """produces empty trailing chunks"""
    result = yield from stream.make(1, 2, 3, 4).transduce(sink.take(4)).run_collect()
    assert result == [[1, 2, 3, 4], []]


@testing.effect
def test_take_produces_an_empty_chunk_for_empty_input():
    """produces an empty chunk for empty input"""
    empty: Stream[int] = stream.empty
    assert (yield from empty.transduce(sink.take(3)).run_collect()) == [[]]


# --- takeWhile ---------------------------------------------------------------------


def _below_3_doubled(n: int) -> Result[int, None]:
    return Ok(n * 2) if n < 3 else Err(None)


def _below_3(n: int) -> Result[int, None]:
    return Ok(n) if n < 3 else Err(None)


def _less_than_3(n: int) -> bool:
    return n < 3


@testing.effect
def test_take_while():
    """takeWhile"""
    assert (yield from stream.make(1, 2, 3, 4).run(sink.take_while(_less_than_3))) == [1, 2]


@testing.effect
def test_take_while_filter():
    """takeWhileFilter"""
    result = yield from stream.make(1, 2, 3, 4).run(sink.take_while_filter(_below_3_doubled))
    assert result == [2, 4]


@testing.effect
def test_take_while_filter_consumes_the_first_failing_input():
    """takeWhileFilter consumes the first failing input"""
    result = (
        yield from stream.make(1, 2, 3, 4).transduce(sink.take_while_filter(_below_3)).run_collect()
    )
    assert result == [[1, 2], [], []]


@testing.effect
def test_take_while_effect():
    """takeWhileEffect"""

    def less_than_3(n: int) -> fx.Effect[bool]:
        return fx.succeed(n < 3)

    taker = sink.take_while_effect(less_than_3)
    assert (yield from stream.make(1, 2, 3, 4).run(taker)) == [1, 2]


@testing.effect
def test_take_while_filter_effect():
    """takeWhileFilterEffect"""

    def plus_one(n: int) -> fx.Effect[Result[int, None]]:
        return fx.succeed(Ok(n + 1) if n < 3 else Err(None))

    result = yield from stream.make(1, 2, 3, 4).run(sink.take_while_filter_effect(plus_one))
    assert result == [2, 3]


@testing.effect
def test_take_while_filter_effect_consumes_the_first_failing_input():
    """takeWhileFilterEffect consumes the first failing input"""

    def keep(n: int) -> fx.Effect[Result[int, None]]:
        return fx.succeed(_below_3(n))

    taker = sink.take_while_filter_effect(keep)
    result = yield from stream.make(1, 2, 3, 4).transduce(taker).run_collect()
    assert result == [[1, 2], [], []]


# --- takeUntil ---------------------------------------------------------------------


@testing.effect
def test_take_until_preserves_leftovers_and_stops_at_the_match():
    """takeUntil preserves leftovers and stops at the match"""
    source: Stream[int, str] = stream.make(1, 2, 3, 4).concat(stream.fail("pulled past the match"))
    result = (
        yield from source.transduce(sink.take_until(lambda n: n % 2 == 0)).take(2).run_collect()
    )
    assert result == [[1, 2], [3, 4]]


@testing.effect
def test_take_until_effect_preserves_leftovers_and_stops_at_the_match():
    """takeUntilEffect preserves leftovers and stops at the match"""
    for chunk_size in [1, 4]:
        inputs: list[int] = []

        def matches(n: int, inputs: list[int] = inputs) -> fx.Effect[bool]:
            def record() -> bool:
                inputs.append(n)
                return n % 2 == 0

            return fx.sync(record)

        source: Stream[int, str] = (
            stream.make(1, 2, 3, 4).rechunk(chunk_size).concat(stream.fail("pulled past the match"))
        )
        result = yield from source.transduce(sink.take_until_effect(matches)).take(2).run_collect()
        assert result == [[1, 2], [3, 4]]
        assert inputs == [1, 2, 3, 4]


# --- withDuration ------------------------------------------------------------------


@testing.effect
def test_with_duration_uses_monotonic_time_when_wall_time_moves_backward():
    """uses monotonic time when wall time moves backward"""
    yield from testing.set_time(1_000)

    def body() -> Generator[fx.Effect[None]]:
        yield testing.adjust("100 millis")
        yield testing.set_time(0)

    empty: Stream[int] = stream.empty
    _, duration = yield from empty.run(sink.from_effect(fx.gen(body)).with_duration())
    assert to_millis(seconds(duration)) == 100


# --- flatMap -----------------------------------------------------------------------


@testing.effect
def test_flat_map_preserves_leftovers_when_the_next_sink_consumes_no_input():
    """preserves leftovers when the next sink consumes no input"""
    first: sink.Sink[list[int], int, int] = sink.take(1)
    then_nothing = first.flat_map(lambda _: sink.take(0))
    collecting = then_nothing.flat_map(lambda _: sink.collect())
    result = yield from stream.from_arrays([1, 2, 3], [4, 5]).run(collecting)
    assert result == [2, 3, 4, 5], "pending leftovers should be preserved"


@testing.effect
def test_flat_map_empty_input():
    """flatMap - empty input"""
    first: sink.Sink[Option[int], int, int] = sink.head()
    empty: Stream[int] = stream.empty
    assert (yield from empty.run(first.flat_map(sink.succeed))) is None


@testing.effect
def test_flat_map_non_empty_input():
    """flatMap - non-empty input"""
    first: sink.Sink[Option[int], int, int] = sink.head()
    assert (yield from stream.make(1, 2, 3).run(first.flat_map(sink.succeed))) == Some(1)


@testing.effect
def test_flat_map_with_leftovers():
    """flatMap - with leftovers"""
    chunks: list[list[int]] = [[1, 2], [3, 4, 5], [], [7, 8, 9, 10]]
    first: sink.Sink[Option[int], int, int] = sink.head()

    def then_count(head: Option[int]) -> sink.Sink[tuple[Option[int], int]]:
        return sink.count.map(lambda count: (head, count))

    option, count = yield from stream.from_arrays(*chunks).run(first.flat_map(then_count))
    flat = [n for chunk in chunks for n in chunk]
    assert option == Some(flat[0])
    assert count + (0 if option is None else 1) == len(flat)
