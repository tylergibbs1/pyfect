"""TxChunk, TxHashMap and TxHashSet behaviours beyond Effect's test files.
Expected values were printed by Effect v4.0.6 under Node first."""

from collections.abc import Callable
from typing import Any

import pytest

import pyfect as fx
from pyfect import testing
from pyfect.option import Some


def _yield_times(n: int) -> fx.Effect[None]:
    return fx.yield_now().repeat(times=n).as_void()


def _chunk_after(op: Callable[[fx.TxChunk[int]], fx.Effect[None]]) -> tuple[int, ...]:
    @fx.fn
    def body():
        chunk = yield from fx.TxChunk.make([1, 2, 3, 4, 5])
        yield from op(chunk)
        return (yield from chunk.get())

    return fx.run_sync(body())


@pytest.mark.parametrize(
    ("start", "end", "expected"),
    [
        (-1, 2, (1, 2, 3)),
        (2, 1, ()),
        (-3, -1, (1, 2)),
        (1, 10, (2, 3, 4, 5)),
        (0, 0, ()),
        (3, 5, (4, 5)),
    ],
)
def test_slice_is_drop_then_take(start: int, end: int, expected: tuple[int, ...]):
    assert _chunk_after(lambda c: c.slice(start, end)) == expected


@pytest.mark.parametrize(
    ("n", "taken", "dropped"),
    [
        (-1, (), (1, 2, 3, 4, 5)),
        (0, (), (1, 2, 3, 4, 5)),
        (2, (1, 2), (3, 4, 5)),
        (9, (1, 2, 3, 4, 5), ()),
    ],
)
def test_take_and_drop_clamp_counts(n: int, taken: tuple[int, ...], dropped: tuple[int, ...]):
    assert _chunk_after(lambda c: c.take(n)) == taken
    assert _chunk_after(lambda c: c.drop(n)) == dropped


def _wakes(op: Callable[[fx.TxHashMap[str, int]], fx.Effect[Any]]) -> int:
    """How many times a transaction parked in ``tx_retry`` on a map runs
    after ``op`` (1: not woken)."""

    @fx.fn
    def body():
        tx_map = yield from fx.TxHashMap.make(("a", 1))
        runs = 0

        @fx.fn
        def waiting():
            nonlocal runs
            runs += 1
            yield from tx_map.size()
            return (yield from fx.tx_retry)

        fiber = yield from fx.tx(waiting()).fork(start_immediately=True)
        yield from fx.yield_now()
        yield from op(tx_map)
        yield from _yield_times(5)
        yield from fiber.interrupt()
        return runs

    return fx.run_sync(body())


def test_writes_that_change_nothing_do_not_wake_waiters():
    assert _wakes(lambda m: m.remove("zz")) == 1
    assert _wakes(lambda m: m.modify("zz", lambda x: x)) == 1
    assert _wakes(lambda m: m.modify_at("zz", lambda x: x)) == 1
    assert _wakes(lambda m: m.size()) == 1
    assert _wakes(lambda m: m.remove("a")) == 2
    assert _wakes(lambda m: m.set("a", 1)) == 2


@testing.effect
def test_set_remove_of_a_missing_value_does_not_wake_waiters():
    tx_set = yield from fx.TxHashSet.make("a")
    runs = 0

    @fx.fn
    def waiting():
        nonlocal runs
        runs += 1
        if not (yield from tx_set.has("b")):
            return (yield from fx.tx_retry)

    fiber = yield from fx.tx(waiting()).fork(start_immediately=True)
    yield from tx_set.remove("zz")
    yield from _yield_times(5)
    assert runs == 1
    yield from tx_set.add("b")
    yield from fiber.join()
    assert runs == 2


@testing.effect
def test_a_chunk_retry_wakes_when_another_chunk_is_concatenated_into_it():
    source = yield from fx.TxChunk.make([3, 4])
    target = yield from fx.TxChunk.make([1, 2])

    @fx.fn
    def wait_for_four():
        items = yield from target.get()
        if len(items) < 4:
            return (yield from fx.tx_retry)
        return items

    fiber = yield from fx.tx(wait_for_four()).fork(start_immediately=True)
    yield from target.concat(source)
    assert (yield from fiber.join()) == (1, 2, 3, 4)


@testing.effect
def test_failed_transaction_leaves_collections_unchanged():
    tx_map = yield from fx.TxHashMap.make(("a", 1))
    tx_set = yield from fx.TxHashSet.make("a")
    chunk = yield from fx.TxChunk.make([1])

    @fx.fn
    def body():
        yield from tx_map.set("b", 2)
        yield from tx_set.remove("a")
        yield from chunk.append(2)
        return (yield from fx.fail("boom"))

    assert (yield from fx.tx(body()).flip()) == "boom"
    assert (yield from tx_map.entries()) == [("a", 1)]
    assert (yield from tx_set.to_hash_set()) == frozenset({"a"})
    assert (yield from chunk.get()) == (1,)


@testing.effect
def test_snapshot_is_read_only_and_survives_writes_outside_a_transaction():
    tx_map = yield from fx.TxHashMap.make(("a", 1))
    snapshot = yield from tx_map.snapshot()
    yield from tx_map.set("a", 2)
    yield from tx_map.remove_many(["a"])
    assert dict(snapshot) == {"a": 1}
    with pytest.raises(TypeError):
        snapshot["a"] = 3  # pyright: ignore[reportIndexIssue]


@testing.effect
def test_get_keeps_a_present_none_apart_from_absence():
    tx_map = yield from fx.TxHashMap.make(("a", None))
    assert (yield from tx_map.get("a")) == Some(None)
    assert (yield from tx_map.get("b")) is None


@testing.effect
def test_flat_map_failure_creates_nothing_and_rolls_back():
    tx_map = yield from fx.TxHashMap.make(("a", 1), ("b", 2))

    def explode(value: int, _: str) -> fx.Effect[fx.TxHashMap[str, int], str]:
        if value == 2:
            return fx.fail("bad")
        return tx_map.set("touched", 0).and_then(fx.TxHashMap.make(("x", value)))

    assert (yield from tx_map.flat_map(explode).flip()) == "bad"
    assert sorted((yield from tx_map.keys())) == ["a", "b"]


@testing.effect
def test_union_and_set_many_replace_values_at_shared_keys():
    tx_map = yield from fx.TxHashMap.make(("a", 1), ("b", 2))
    yield from tx_map.union({"b": 3})
    yield from tx_map.set_many([("a", 4), ("a", 5)])
    assert (yield from tx_map.entries()) == [("a", 5), ("b", 3)]


def test_repr_names_the_collection_and_its_ref():
    assert repr(fx.TxChunk(fx.TxRef((1,)))) == "TxChunk(TxRef((1,)))"
    assert repr(fx.TxHashMap(fx.TxRef({"a": 1}))) == "TxHashMap(TxRef({'a': 1}))"
    assert repr(fx.TxHashSet(fx.TxRef(frozenset({1})))) == "TxHashSet(TxRef(frozenset({1})))"


_MAP_WRITES: dict[str, Callable[[fx.TxHashMap[str, int]], fx.Effect[Any]]] = {
    "clear": lambda m: m.clear(),
    "set_same": lambda m: m.set("a", 1),
    "set_new": lambda m: m.set("z", 1),
    "set_many_same": lambda m: m.set_many([("a", 1)]),
    "set_many_empty": lambda m: m.set_many([]),
    "set_many_away_and_back": lambda m: m.set_many([("a", 5), ("a", 1)]),
    "union_empty": lambda m: m.union({}),
    "union_same": lambda m: m.union({"a": 1}),
    "remove_many_missing": lambda m: m.remove_many(["zz"]),
    "remove_many_empty": lambda m: m.remove_many([]),
    "remove_many_present": lambda m: m.remove_many(["a"]),
    "modify_same": lambda m: m.modify("a", lambda x: x),
    "modify_at_same": lambda m: m.modify_at("a", lambda x: x),
    "modify_at_missing": lambda m: m.modify_at("zz", lambda x: x),
}

# ``ref.version`` after each write, on an empty map and on ``{"a": 1}``.
_MAP_VERSIONS_IN_EFFECT = {
    "clear": (1, 1),
    "set_same": (1, 0),
    "set_new": (1, 1),
    "set_many_same": (1, 0),
    "set_many_empty": (0, 0),
    "set_many_away_and_back": (1, 1),
    "union_empty": (0, 0),
    "union_same": (1, 0),
    "remove_many_missing": (0, 0),
    "remove_many_empty": (0, 0),
    "remove_many_present": (0, 1),
    "modify_same": (0, 0),
    "modify_at_same": (0, 0),
    "modify_at_missing": (0, 0),
}


@pytest.mark.parametrize("name", list(_MAP_WRITES))
def test_map_writes_that_change_nothing_keep_the_version(name: str):
    """A write that leaves every value the same (``Object.is``) keeps the
    map, so a concurrent reader is not rerun for it."""

    def version_after(entries: list[tuple[str, int]]) -> int:
        @fx.fn
        def body():
            tx_map = yield from fx.TxHashMap.from_iterable(entries)
            yield from _MAP_WRITES[name](tx_map)
            return tx_map.ref.version

        return fx.run_sync(body())

    assert (version_after([]), version_after([("a", 1)])) == _MAP_VERSIONS_IN_EFFECT[name]


def test_writes_to_a_present_key_wake_waiters_even_when_nothing_changes():
    assert _wakes(lambda m: m.modify("a", lambda x: x)) == 2
    assert _wakes(lambda m: m.modify_at("a", lambda x: x)) == 2
    assert _wakes(lambda m: m.set_many([])) == 2
    assert _wakes(lambda m: m.remove_many(["zz"])) == 2
