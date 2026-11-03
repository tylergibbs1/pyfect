"""Ports of Effect's ``test/MutableHashMap.test.ts`` and
``MutableHashSet.test.ts``.

Each test's docstring is the Effect test title. Module functions are
methods. Omitted: "retains its entries after it is used as a lookup key"
(a mutable map is unhashable in Python, so it is no key); "toString",
"toJSON" and "inspect" (Python's ``repr``); the garbage-collection half of
"does not retain replaced equal keys after removal and reinsertion" (the
kept key is checked instead).
"""

from __future__ import annotations

from dataclasses import dataclass

from pyfect.mutable_hash_map import MutableHashMap
from pyfect.mutable_hash_set import MutableHashSet
from pyfect.option import Some


@dataclass(frozen=True)
class Key:
    a: int
    b: int


@dataclass(frozen=True)
class Value:
    c: int
    d: int


def test_does_not_retain_replaced_equal_keys_after_removal_and_reinsertion() -> None:
    """does not retain replaced equal keys after removal and reinsertion"""
    m = MutableHashMap.make((Key(0, 0), "value"))
    latest = Key(0, 0)
    for _ in range(10):
        latest = Key(0, 0)
        current = m.get(latest)
        assert isinstance(current, Some)
        m.remove(latest)
        m.set(latest, current.value)
    assert next(m.keys()) is latest
    assert m.get(Key(0, 0)) == Some("value")


def test_is_mutable_hash_map() -> None:
    """isMutableHashMap"""
    assert isinstance(MutableHashMap.make((0, "a"), (1, "b")), MutableHashMap)
    assert not isinstance({0: "a"}, MutableHashMap)


def test_make() -> None:
    """make"""
    m = MutableHashMap.make((Key(0, 0), Value(0, 0)), (Key(1, 1), Value(1, 1)))
    assert len(m) == 2
    assert m.has(Key(0, 0))
    assert m.has(Key(1, 1))


def test_from_iterable() -> None:
    """fromIterable"""
    m = MutableHashMap.from_iterable([(Key(0, 0), Value(0, 0)), (Key(1, 1), Value(1, 1))])
    assert len(m) == 2
    assert m.has(Key(0, 0))
    assert m.has(Key(1, 1))


def test_iterate() -> None:
    """iterate"""

    class Hello:
        def __hash__(self) -> int:
            return 0

        def __eq__(self, other: object) -> bool:
            return self is other

    assert len(list(MutableHashMap.make((Hello(), 0), (Hello(), 0)))) == 2


def test_get_returns_the_latest_value_for_an_equal_key() -> None:
    """get returns the latest value for an equal key"""
    m = MutableHashMap[Key, Value].empty().set(Key(0, 0), Value(0, 0)).set(Key(0, 0), Value(1, 1))
    assert m.get(Key(0, 0)) == Some(Value(1, 1))


def test_has() -> None:
    """has"""
    m = MutableHashMap.make(
        (Key(0, 0), Value(0, 0)),
        (Key(0, 0), Value(1, 1)),
        (Key(1, 1), Value(2, 2)),
        (Key(1, 1), Value(3, 3)),
        (Key(0, 0), Value(4, 4)),
    )
    assert m.has(Key(0, 0))
    assert m.has(Key(1, 1))
    assert not m.has(Key(4, 4))


def test_keys() -> None:
    """keys"""
    m = MutableHashMap[Key, Value].empty().set(Key(0, 0), Value(0, 0)).set(Key(1, 1), Value(1, 1))
    assert list(m.keys()) == [Key(0, 0), Key(1, 1)]


def test_values() -> None:
    """values"""
    m = MutableHashMap[Key, Value].empty().set(Key(0, 0), Value(0, 0)).set(Key(1, 1), Value(1, 1))
    m.modify_at(Key(0, 0), lambda _: Some(Value(0, 1)))
    assert len(m) == 2
    assert m.get(Key(0, 0)) == Some(Value(0, 1))
    m.modify_at(Key(2, 2), lambda o: Some(Value(2, 2)) if o is None else o)
    assert len(m) == 3
    assert m.get(Key(2, 2)) == Some(Value(2, 2))
    m.modify_at(Key(2, 2), lambda _: None)
    assert len(m) == 2


def test_remove_deletes_an_equal_key_in_place() -> None:
    """remove deletes an equal key in place"""
    m = MutableHashMap[Key, Value].empty().set(Key(0, 0), Value(0, 0)).set(Key(1, 1), Value(1, 1))
    assert len(m) == 2
    assert m.has(Key(1, 1))
    m.remove(Key(1, 1))
    assert len(m) == 1
    assert not m.has(Key(1, 1))


def _five_sets() -> MutableHashMap[Key, Value]:
    return (
        MutableHashMap[Key, Value]
        .empty()
        .set(Key(0, 0), Value(0, 0))
        .set(Key(0, 0), Value(1, 1))
        .set(Key(1, 1), Value(2, 2))
        .set(Key(1, 1), Value(3, 3))
        .set(Key(0, 0), Value(4, 4))
    )


def test_set_overwrites_equal_keys_without_changing_size() -> None:
    """set overwrites equal keys without changing size"""
    assert list(_five_sets()) == [(Key(0, 0), Value(4, 4)), (Key(1, 1), Value(3, 3))]


def test_size() -> None:
    """size"""
    assert len(_five_sets()) == 2


def test_modify_updates_existing_keys_and_ignores_missing_keys() -> None:
    """modify updates existing keys and ignores missing keys"""
    m = MutableHashMap[Key, Value].empty().set(Key(0, 0), Value(0, 0)).set(Key(1, 1), Value(1, 1))
    m.modify(Key(0, 0), lambda v: Value(v.c + 1, v.d + 1))
    assert m.get(Key(0, 0)) == Some(Value(1, 1))
    m.modify(Key(1, 1), lambda v: Value(v.c + 1, v.d + 1))
    assert m.remove(Key(0, 0)).get(Key(0, 0)) is None


def test_pipe() -> None:
    """pipe()"""
    assert MutableHashMap[str, str].empty().set("key", "value") == MutableHashMap.make(
        ("key", "value")
    )


def test_is_mutable_hash_set_distinguishes_effect_mutable_hash_sets_from_native_sets() -> None:
    """isMutableHashSet distinguishes Effect mutable hash sets from native sets"""
    assert isinstance(MutableHashSet.make("a", "b"), MutableHashSet)
    assert not isinstance({"a", "b"}, MutableHashSet)
