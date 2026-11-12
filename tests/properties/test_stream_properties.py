"""Stream operators against a list model.

Every source is drawn as a list of chunks; the model is the flattened list. An operator's
output must equal the model's whatever the chunk boundaries of the source, merges must keep
each side's items (as multisets, each side in order), and an interrupted stream must run each
finalizer exactly once. Timing operators run on the ``TestClock``.
"""

from __future__ import annotations

import functools
import itertools
import operator
import re
from collections import Counter
from collections.abc import Callable, Generator
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

import pyfect as fx
from pyfect import stream, testing
from pyfect.option import Some
from pyfect.result import Err, Ok, Result

type Op = Callable[[stream.Stream[int]], stream.Stream[Any]]
type Model = Callable[[list[int]], list[Any]]

_items = st.lists(st.integers(-20, 20), max_size=12)
_counts = st.integers(0, 14)
_sizes = st.integers(1, 5)


@st.composite
def _chunked[T](draw: st.DrawFn, items: list[T]) -> list[list[T]]:
    """``items`` cut into chunks at drawn boundaries (empty chunks included)."""
    cuts = sorted(draw(st.lists(st.integers(0, len(items)), max_size=6)))
    bounds = [0, *cuts, len(items)]
    return [items[a:b] for a, b in itertools.pairwise(bounds)]


def _run[A](eff: fx.Effect[A, Any, Any]) -> A:
    return testing.run_test(eff.or_die())


def _collect(source: stream.Stream[Any]) -> list[Any]:
    return _run(source.run_collect())


def _scan_model(items: list[int]) -> list[int]:
    return [0, *itertools.accumulate(items)]


def _sliding_model(items: list[int], size: int) -> list[tuple[int, ...]]:
    if len(items) <= size:
        return [tuple(items)] if items else []
    return [tuple(items[i : i + size]) for i in range(len(items) - size + 1)]


def _changes_model(items: list[int]) -> list[int]:
    return [x for i, x in enumerate(items) if i == 0 or items[i - 1] != x]


def _previous_model(items: list[int]) -> list[tuple[object, int]]:
    return [(None if i == 0 else Some(items[i - 1]), x) for i, x in enumerate(items)]


def _intersperse_model(items: list[int]) -> list[int]:
    return [y for i, x in enumerate(items) for y in ([x] if i == 0 else [0, x])]


def _grouped_model(items: list[int], size: int) -> list[tuple[int, ...]]:
    return [tuple(items[i : i + size]) for i in range(0, len(items), size)]


def _take_until_model(items: list[int], *, exclude_last: bool) -> list[int]:
    for i, x in enumerate(items):
        if x > 5:
            return items[: i if exclude_last else i + 1]
    return items


def _drop_until_model(items: list[int]) -> list[int]:
    for i, x in enumerate(items):
        if x > 5:
            return items[i + 1 :]
    return []


def _split_model(items: list[int]) -> list[tuple[int, ...]]:
    runs: list[tuple[int, ...]] = []
    run: list[int] = []
    for x in items:
        if x % 3 == 0:
            if run:
                runs.append(tuple(run))
            run = []
        else:
            run.append(x)
    return [*runs, tuple(run)] if run else runs


def _next_model(items: list[int]) -> list[tuple[int, object]]:
    return [(x, Some(items[i + 1]) if i + 1 < len(items) else None) for i, x in enumerate(items)]


def _interleave_model(items: list[int]) -> list[int]:
    other = [100, 101, 102]
    pairs = itertools.zip_longest(items, other)
    return [x for pair in pairs for x in pair if x is not None]


def _halve(x: int) -> Result[int, str]:
    return Ok(x // 2) if x % 2 == 0 else Err("odd")


def _running(total: int, x: int) -> tuple[int, list[int]]:
    return total + x, [total]


def _operators(n: int, size: int) -> dict[str, tuple[Op, Model]]:
    """Each operator with its model, for a drawn count ``n`` and chunk size ``size``."""
    return {
        "map": (lambda s: s.map(lambda x: x * 3 + 1), lambda xs: [x * 3 + 1 for x in xs]),
        "filter": (
            lambda s: s.filter(lambda x: x % 2 == 0),
            lambda xs: [x for x in xs if x % 2 == 0],
        ),
        "take": (lambda s: s.take(n), lambda xs: xs[:n]),
        "drop": (lambda s: s.drop(n), lambda xs: xs[n:]),
        "take_right": (lambda s: s.take_right(n), lambda xs: xs[max(len(xs) - n, 0) :]),
        "drop_right": (lambda s: s.drop_right(n), lambda xs: xs[: max(len(xs) - n, 0)]),
        "take_while": (
            lambda s: s.take_while(lambda x: x < 10),
            lambda xs: list(itertools.takewhile(lambda x: x < 10, xs)),
        ),
        "drop_while": (
            lambda s: s.drop_while(lambda x: x < 10),
            lambda xs: list(itertools.dropwhile(lambda x: x < 10, xs)),
        ),
        "scan": (lambda s: s.scan(lambda: 0, lambda acc, x: acc + x), _scan_model),
        "rechunk": (lambda s: s.rechunk(size), lambda xs: xs),
        "grouped": (lambda s: s.grouped(size), lambda xs: _grouped_model(xs, size)),
        "sliding": (lambda s: s.sliding(size), lambda xs: _sliding_model(xs, size)),
        "zip_with_index": (
            lambda s: s.zip_with_index(),
            lambda xs: [(x, i) for i, x in enumerate(xs)],
        ),
        "zip_with_previous": (lambda s: s.zip_with_previous(), _previous_model),
        "changes": (lambda s: s.changes(), _changes_model),
        "intersperse": (lambda s: s.intersperse(0), _intersperse_model),
        "flat_map": (
            lambda s: s.flat_map(lambda x: stream.make(x, -x)),
            lambda xs: [y for x in xs for y in (x, -x)],
        ),
        "concat": (lambda s: s.concat(stream.make(99, 98)), lambda xs: [*xs, 99, 98]),
        "prepend": (lambda s: s.prepend([7, 8]), lambda xs: [7, 8, *xs]),
        "take_until": (
            lambda s: s.take_until(lambda x: x > 5),
            lambda xs: _take_until_model(xs, exclude_last=False),
        ),
        "take_until exclude_last": (
            lambda s: s.take_until(lambda x: x > 5, exclude_last=True),
            lambda xs: _take_until_model(xs, exclude_last=True),
        ),
        "drop_until": (lambda s: s.drop_until(lambda x: x > 5), _drop_until_model),
        "split": (lambda s: s.split(lambda x: x % 3 == 0), _split_model),
        "group_adjacent_by": (
            lambda s: s.group_adjacent_by(lambda x: x % 2),
            lambda xs: [(k, tuple(g)) for k, g in itertools.groupby(xs, lambda x: x % 2)],
        ),
        "filter_map": (
            lambda s: s.filter_map(_halve),
            lambda xs: [x // 2 for x in xs if x % 2 == 0],
        ),
        "zip_with_next": (lambda s: s.zip_with_next(), _next_model),
        "map_accum": (lambda s: s.map_accum(lambda: 0, _running), lambda xs: _scan_model(xs)[:-1]),
        "buffer": (lambda s: s.buffer(capacity=size), lambda xs: xs),
        "interleave": (lambda s: s.interleave(stream.make(100, 101, 102)), _interleave_model),
        "map_effect concurrency": (
            lambda s: s.map_effect(lambda x: fx.succeed(x * 2), concurrency=size),
            lambda xs: [x * 2 for x in xs],
        ),
    }


_OPERATORS = sorted(_operators(0, 1))


@pytest.mark.parametrize("name", _OPERATORS)
@given(data=st.data(), items=_items, n=_counts, size=_sizes)
def test_an_operator_matches_its_list_model_whatever_the_chunking(
    name: str, data: st.DataObject, items: list[int], n: int, size: int
):
    op, model = _operators(n, size)[name]
    chunks = data.draw(_chunked(items))
    assert _collect(op(stream.from_arrays(*chunks))) == model(items)
    assert _collect(op(stream.from_iterable(items))) == model(items)


@given(data=st.data(), items=_items, size=_sizes)
def test_rechunk_writes_full_chunks_and_one_shorter_last(
    data: st.DataObject, items: list[int], size: int
):
    chunks = data.draw(_chunked(items))
    written = _collect(stream.from_arrays(*chunks).rechunk(size).chunks())
    assert [x for chunk in written for x in chunk] == items
    assert all(len(chunk) == size for chunk in written[:-1])
    assert all(0 < len(chunk) <= size for chunk in written[-1:])


@given(data=st.data(), left=_items, right=_items)
def test_zip_pairs_items_in_order_whatever_the_chunking(
    data: st.DataObject, left: list[int], right: list[int]
):
    a = stream.from_arrays(*data.draw(_chunked(left)))
    b = stream.from_arrays(*data.draw(_chunked(right)))
    assert _collect(a.zip(b)) == list(zip(left, right, strict=False))


def _is_subsequence(part: list[int], whole: list[int]) -> bool:
    remaining = iter(whole)
    return all(any(x == y for y in remaining) for x in part)


@given(data=st.data(), left=_items, right=_items)
def test_merge_keeps_every_item_and_each_sides_order(
    data: st.DataObject, left: list[int], right: list[int]
):
    tagged_left = stream.from_arrays(*data.draw(_chunked(left))).map(lambda x: ("l", x))
    tagged_right = stream.from_arrays(*data.draw(_chunked(right))).map(lambda x: ("r", x))
    merged: list[tuple[str, int]] = _collect(tagged_left.merge(tagged_right))
    assert Counter(merged) == Counter([("l", x) for x in left] + [("r", x) for x in right])
    assert [x for side, x in merged if side == "l"] == left
    assert [x for side, x in merged if side == "r"] == right


@given(data=st.data(), items=_items, concurrency=st.integers(1, 4))
def test_concurrent_flat_map_writes_the_same_multiset_with_each_inner_in_order(
    data: st.DataObject, items: list[int], concurrency: int
):
    source = stream.from_arrays(*data.draw(_chunked(items)))
    out: list[tuple[int, int]] = _collect(
        source.zip_with_index().flat_map(
            lambda pair: stream.make((pair[1], pair[0]), (pair[1], -pair[0])),
            concurrency=concurrency,
        )
    )
    expected = [(i, y) for i, x in enumerate(items) for y in (x, -x)]
    assert Counter(out) == Counter(expected)
    for i in range(len(items)):
        assert [y for j, y in out if j == i] == [y for j, y in expected if j == i]


@given(data=st.data(), items=_items, keys=st.integers(1, 4))
def test_group_by_key_keeps_each_keys_order(data: st.DataObject, items: list[int], keys: int):
    source = stream.from_arrays(*data.draw(_chunked(items)))
    grouped = source.group_by_key(lambda x: x % keys).flat_map(
        lambda group: group[1].map(lambda x: (group[0], x)), concurrency="unbounded"
    )
    out: list[tuple[int, int]] = _collect(grouped)
    assert Counter(x for _, x in out) == Counter(items)
    for key in range(keys):
        assert [x for k, x in out if k == key] == [x for x in items if x % keys == key]


# --- text ------------------------------------------------------------------------------------

_text = st.text(alphabet="a\r\n\u00e9\U0001f600\ufeff", max_size=12)


@st.composite
def _pieces[T: (str, bytes)](draw: st.DrawFn, whole: T) -> list[T]:
    """``whole`` cut at drawn points, empty pieces included."""
    cuts = sorted(draw(st.lists(st.integers(0, len(whole)), max_size=6)))
    return [whole[a:b] for a, b in itertools.pairwise([0, *cuts, len(whole)])]


@given(st.data(), _text)
def test_decode_text_keeps_characters_split_across_byte_strings(data: st.DataObject, text: str):
    pieces = data.draw(_pieces(text.encode()))
    source = stream.from_arrays(*data.draw(_chunked(pieces)))
    assert "".join(_collect(source.decode_text())) == text.removeprefix("\ufeff")


@given(st.data(), _text)
def test_split_lines_splits_wherever_the_chunks_break(data: st.DataObject, text: str):
    pieces = data.draw(_pieces(text))
    source = stream.from_arrays(*data.draw(_chunked(pieces)))
    lines = re.split(r"\r\n|\r|\n", text)
    if lines[-1] == "":
        lines.pop()
    assert _collect(source.split_lines()) == lines


@given(st.data(), _text)
def test_encoding_then_decoding_text_gives_it_back(data: st.DataObject, text: str):
    pieces = data.draw(_pieces(text))
    source = stream.from_arrays(*data.draw(_chunked(pieces)))
    assert "".join(_collect(source.encode_text().decode_text())) == text.removeprefix("\ufeff")


# --- timing ----------------------------------------------------------------------------------

_gaps = st.lists(st.tuples(st.integers(0, 6), st.integers(-9, 9)), max_size=8)
"""Items each written after a gap of that many 100 ms steps."""

_WAIT_MS = 250
"""Not a multiple of the 100 ms step, so no item lands exactly when the wait ends."""


def _timed(items: list[tuple[int, int]]) -> stream.Stream[int]:
    return stream.from_iterable(items).map_effect(
        lambda item: fx.sleep(f"{item[0] * 100} millis").as_(item[1])
    )


_STEP_MS = 50
_LATE_STEPS = 200
"""Steps past ``total_ms`` allowed for sleeps that registered late; a stream still running
after them stalls the run and fails the test."""


def _run_timed[A](eff: fx.Effect[list[A], Any, Any], total_ms: int) -> list[A]:
    """Run ``eff`` moving the clock ``total_ms`` in 50 ms steps. One jump could pass a sleep
    a forked fiber has not registered yet (a merge's side after a zero sleep), which then
    waits from the later time; Effect's ``TestClock.adjust`` behaves the same."""

    @fx.gen
    def program() -> Generator[fx.Effect[Any, Any, Any], Any, list[A]]:
        fiber = yield from eff.fork()
        for _ in range(-(-total_ms // _STEP_MS)):
            yield from testing.adjust(f"{_STEP_MS} millis")
        for _ in range(_LATE_STEPS):
            if fiber.poll_unsafe() is not None:
                break
            yield from testing.adjust(f"{_STEP_MS} millis")
        return (yield from fiber.join())

    return _run(program)


@given(_gaps)
def test_debounce_writes_each_item_not_followed_within_the_wait(items: list[tuple[int, int]]):
    total = sum(gap for gap, _ in items) * 100 + _WAIT_MS * 2
    out = _run_timed(_timed(items).debounce(f"{_WAIT_MS} millis").run_collect(), total)
    following = [*(gap * 100 for gap, _ in items[1:]), *([None] if items else [])]
    expected = [
        value
        for (_, value), after in zip(items, following, strict=True)
        if after is None or after > _WAIT_MS
    ]
    assert out == expected


@given(_gaps, _gaps)
def test_merging_timed_streams_keeps_every_item_and_each_sides_order(
    left: list[tuple[int, int]], right: list[tuple[int, int]]
):
    """Both sides sleep between items, so the merge interleaves them by time."""
    total = (sum(g for g, _ in left) + sum(g for g, _ in right)) * 100 + 100
    merged = _timed(left).map(lambda x: ("l", x)).merge(_timed(right).map(lambda x: ("r", x)))
    out = _run_timed(merged.run_collect(), total)
    assert [x for side, x in out if side == "l"] == [v for _, v in left]
    assert [x for side, x in out if side == "r"] == [v for _, v in right]


@given(_gaps)
def test_throttle_shape_delays_but_keeps_every_item(items: list[tuple[int, int]]):
    total = sum(gap for gap, _ in items) * 100 + len(items) * 1_000
    throttled = _timed(items).throttle(cost=len, units=1, duration="1 second")
    assert _run_timed(throttled.run_collect(), total) == [value for _, value in items]


@given(_gaps)
def test_throttle_enforce_drops_but_never_reorders(items: list[tuple[int, int]]):
    total = sum(gap for gap, _ in items) * 100 + 1_000
    throttled = _timed(items).throttle(cost=len, units=1, duration="1 second", strategy="enforce")
    out = _run_timed(throttled.run_collect(), total)
    assert _is_subsequence(out, [value for _, value in items])
    if items:
        assert out[:1] == [items[0][1]]


@given(st.integers(1, 6))
def test_throttle_shape_spaces_single_items_by_the_duration(count: int):
    """``count`` items at once, one token a second: the last waits ``count - 1`` seconds."""

    @fx.gen
    def program() -> Generator[fx.Effect[Any, Any, Any], Any]:
        throttled = stream.range(1, count, chunk_size=1).throttle(
            cost=len, units=1, duration="1 second"
        )
        fiber = yield from throttled.run_collect().fork()
        yield from testing.adjust(f"{(count - 1) * 1_000 - 1} millis")
        assert fiber.poll_unsafe() is None or count == 1
        yield from testing.adjust("1 millis")
        assert (yield from fiber.join()) == list(range(1, count + 1))

    _run(program)


# --- interruption ----------------------------------------------------------------------------


type Shape = Callable[[list[stream.Stream[int]]], stream.Stream[int]]


def _merged(inners: list[stream.Stream[int]]) -> stream.Stream[int]:
    return functools.reduce(lambda a, b: a.merge(b), inners)


def _zipped(inners: list[stream.Stream[int]]) -> stream.Stream[int]:
    return functools.reduce(lambda a, b: a.zip_with(b, operator.add), inners)


_SHAPES: dict[str, Shape] = {
    "flat_map": lambda inners: stream.from_iterable(inners).flat_map(lambda s: s),
    "flat_map concurrency 2": lambda inners: stream.from_iterable(inners).flat_map(
        lambda s: s, concurrency=2
    ),
    "flat_map unbounded": lambda inners: stream.from_iterable(inners).flat_map(
        lambda s: s, concurrency="unbounded"
    ),
    "switch_map": lambda inners: (
        stream.from_iterable(inners)
        .map_effect(lambda s: fx.sleep("150 millis").as_(s))
        .switch_map(lambda s: s)
    ),
    "merge": _merged,
    "zip": _zipped,
    "concat": lambda inners: functools.reduce(lambda a, b: a.concat(b), inners),
    "take 2": lambda inners: stream.from_iterable(inners).flat_map(lambda s: s).take(2),
    "group_by_key": lambda inners: (
        stream.from_iterable(inners)
        .flat_map(lambda s: s)
        .group_by_key(lambda x: x % 2)
        .flat_map(lambda group: group[1], concurrency="unbounded")
    ),
}


@pytest.mark.parametrize("shape", sorted(_SHAPES))
@given(
    lengths=st.lists(st.integers(0, 3), min_size=1, max_size=4),
    stop_ms=st.integers(0, 1_000),
)
def test_interrupting_at_any_point_runs_each_finalizer_exactly_once(
    shape: str, lengths: list[int], stop_ms: int
):
    """Each inner stream sleeps 100 ms per item and has its own finalizer, the whole stream
    too; interrupting after ``stop_ms`` (or letting it end first) runs each finalizer at most
    once, and the finalizer of every stream that wrote anything. (A stream started but
    stopped before its first pull, as ``zip``'s right side when the left one is empty, runs
    its finalizer without having opened.)"""
    opened: list[str] = []
    closed: list[str] = []

    def inner(index: int, length: int) -> stream.Stream[int]:
        name = f"inner-{index}"
        return (
            stream.from_effect(fx.sync(lambda: opened.append(name)))
            .flat_map(lambda _: stream.range(1, length, chunk_size=1))
            .map_effect(lambda x: fx.sleep("100 millis").as_(x))
            .ensuring(fx.sync(lambda: closed.append(name)))
        )

    whole = _SHAPES[shape]([inner(i, n) for i, n in enumerate(lengths)])
    source = whole.ensuring(fx.sync(lambda: closed.append("outer")))

    @fx.gen
    def program() -> Generator[fx.Effect[Any, Any, Any], Any]:
        fiber = yield from source.run_drain().fork(start_immediately=True)
        yield from testing.adjust(f"{stop_ms} millis")
        yield from fiber.interrupt()

    _run(program)
    assert Counter(closed) == Counter(set(closed))
    assert set(opened) | {"outer"} <= set(closed)
