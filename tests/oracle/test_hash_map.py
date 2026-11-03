"""Ports of Effect's ``test/HashMap.test.ts``.

Each test's docstring is the Effect test title. Module functions are
methods (``HashMap.set(m, k, v)`` is ``m.set(k, v)``). ``Equal`` / ``Hash``
objects are classes with ``__eq__`` / ``__hash__``; "preserves traversal
order across every node kind" gives its keys the hashes Effect's test passes
to ``modifyHash`` (which pyfect ignores: keys are found by value) that way.
"""

from __future__ import annotations

import math
import random
import uuid

import pytest

from pyfect.hash_map import HashMap
from pyfect.option import Some
from pyfect.result import Err, Ok


def test_empty() -> None:
    """empty"""
    m = HashMap[str, int].empty()
    assert m.is_empty()
    assert len(m) == 0


def test_make() -> None:
    """make"""
    m = HashMap.make(("a", 1), ("b", 2), ("c", 3))
    assert len(m) == 3
    assert m.get("a") == Some(1)
    assert m.get("b") == Some(2)
    assert m.get("c") == Some(3)


def test_from_iterable() -> None:
    """fromIterable"""
    m = HashMap.from_iterable([("a", 1), ("b", 2), ("c", 3)])
    assert len(m) == 3
    assert m.get("a") == Some(1)
    assert m.get("b") == Some(2)
    assert m.get("c") == Some(3)


def test_modify_hash_stores_a_new_key_under_the_supplied_hash() -> None:
    """modifyHash stores a new key under the supplied hash"""
    key = object()
    m = HashMap[object, str].empty().modify_hash(key, 12345, lambda _: Some("value"))
    assert m.get_hash(key, 12345) == Some("value")


def test_modify_hash_removes_a_key_using_the_supplied_hash() -> None:
    """modifyHash removes a key using the supplied hash"""
    key = object()
    m = HashMap[object, str].empty().modify_hash(key, 12345, lambda _: Some("value"))
    removed = m.modify_hash(key, 12345, lambda _: None)
    assert removed.get_hash(key, 12345) is None


def test_get_existing_key() -> None:
    """get - existing key"""
    m = HashMap.make(("a", 1), ("b", 2))
    assert m.get("a") == Some(1)
    assert m.get("b") == Some(2)


def test_get_non_existing_key() -> None:
    """get - non-existing key"""
    assert HashMap.make(("a", 1), ("b", 2)).get("c") is None


def test_has_existing_key() -> None:
    """has - existing key"""
    m = HashMap.make(("a", 1), ("b", 2))
    assert m.has("a")
    assert m.has("b")


def test_has_non_existing_key() -> None:
    """has - non-existing key"""
    assert not HashMap.make(("a", 1), ("b", 2)).has("c")


def test_set_new_key() -> None:
    """set - new key"""
    map1 = HashMap.make(("a", 1))
    map2 = map1.set("b", 2)
    assert len(map2) == 2
    assert map2.get("a") == Some(1)
    assert map2.get("b") == Some(2)
    assert len(map1) == 1
    assert not map1.has("b")


def test_set_existing_key() -> None:
    """set - existing key"""
    map1 = HashMap.make(("a", 1), ("b", 2))
    map2 = map1.set("a", 10)
    assert len(map2) == 2
    assert map2.get("a") == Some(10)
    assert map2.get("b") == Some(2)
    assert map1.get("a") == Some(1)


def test_remove_existing_key() -> None:
    """remove - existing key"""
    map1 = HashMap.make(("a", 1), ("b", 2), ("c", 3))
    map2 = map1.remove("b")
    assert len(map2) == 2
    assert map2.has("a")
    assert not map2.has("b")
    assert map2.has("c")
    assert len(map1) == 3
    assert map1.has("b")


def test_remove_non_existing_key() -> None:
    """remove - non-existing key"""
    map1 = HashMap.make(("a", 1), ("b", 2))
    map2 = map1.remove("c")
    assert map2 is map1
    assert len(map2) == 2


def test_get_unsafe_existing_key() -> None:
    """getUnsafe - existing key"""
    m = HashMap.make(("a", 1), ("b", 2))
    assert m.get_unsafe("a") == 1
    assert m.get_unsafe("b") == 2


def test_get_unsafe_non_existing_key() -> None:
    """getUnsafe - non-existing key"""
    with pytest.raises(KeyError, match=r"HashMap\.getUnsafe: key not found"):
        HashMap.make(("a", 1)).get_unsafe("b")


def test_keys() -> None:
    """keys"""
    assert sorted(HashMap.make(("a", 1), ("b", 2), ("c", 3)).keys()) == ["a", "b", "c"]


def test_values() -> None:
    """values"""
    assert sorted(HashMap.make(("a", 1), ("b", 2), ("c", 3)).values()) == [1, 2, 3]


def test_to_values() -> None:
    """toValues"""
    assert sorted(HashMap.make(("a", 1), ("b", 2), ("c", 3)).to_values()) == [1, 2, 3]


def test_entries() -> None:
    """entries"""
    assert sorted(HashMap.make(("a", 1), ("b", 2)).entries()) == [("a", 1), ("b", 2)]


def test_to_entries() -> None:
    """toEntries"""
    assert sorted(HashMap.make(("a", 1), ("b", 2)).to_entries()) == [("a", 1), ("b", 2)]


def test_symbol_iterator() -> None:
    """Symbol.iterator"""
    assert sorted(HashMap.make(("a", 1), ("b", 2))) == [("a", 1), ("b", 2)]


def test_does_not_expose_mutable_collision_entries() -> None:
    """does not expose mutable collision entries"""
    m = HashMap.make(("fF", 1), ("AA", 2))
    entries = m.to_entries()
    entries[0] = ("fF", 99)
    assert m.get_unsafe("fF") == 1


def test_remove_many() -> None:
    """removeMany"""
    map2 = HashMap.make(("a", 1), ("b", 2), ("c", 3), ("d", 4)).remove_many(["b", "d"])
    assert len(map2) == 2
    assert map2.has("a")
    assert not map2.has("b")
    assert map2.has("c")
    assert not map2.has("d")


def test_set_many() -> None:
    """setMany"""
    map1 = HashMap.make(("a", 1), ("b", 2))
    map2 = map1.set_many([("c", 3), ("d", 4), ("a", 10)])
    assert len(map2) == 4
    assert map2.get("a") == Some(10)
    assert map2.get("b") == Some(2)
    assert map2.get("c") == Some(3)
    assert map2.get("d") == Some(4)


def test_set_many_pipe_syntax() -> None:
    """setMany - pipe syntax"""
    map2 = HashMap[str, int].empty().set_many([("x", 100), ("y", 200)])
    assert len(map2) == 2
    assert map2.get("x") == Some(100)
    assert map2.get("y") == Some(200)


def test_set_many_different_iterables() -> None:
    """setMany - different iterables"""
    map1 = HashMap.make(("existing", 1))
    map2 = map1.set_many({"from-map": 2, "another": 3}.items())
    assert len(map2) == 3
    assert map2.get("existing") == Some(1)
    assert map2.get("from-map") == Some(2)
    assert map2.get("another") == Some(3)
    map3 = map2.set_many({("from-set", 4)})
    assert len(map3) == 4
    assert map3.get("from-set") == Some(4)


def test_union() -> None:
    """union"""
    map3 = HashMap.make(("a", 1), ("b", 2)).union(HashMap.make(("b", 20), ("c", 3)))
    assert len(map3) == 3
    assert map3.get("a") == Some(1)
    assert map3.get("b") == Some(20)
    assert map3.get("c") == Some(3)


def test_map() -> None:
    """map"""
    map2 = HashMap.make(("a", 1), ("b", 2), ("c", 3)).map(lambda value, _key: value * 2)
    assert len(map2) == 3
    assert map2.get("a") == Some(2)
    assert map2.get("b") == Some(4)
    assert map2.get("c") == Some(6)


def test_flat_map() -> None:
    """flatMap"""
    map2 = HashMap.make(("a", 1), ("b", 2)).flat_map(
        lambda value, key: HashMap.make((key + "1", value), (key + "2", value * 2))
    )
    assert len(map2) == 4
    assert map2.get("a1") == Some(1)
    assert map2.get("a2") == Some(2)
    assert map2.get("b1") == Some(2)
    assert map2.get("b2") == Some(4)


def test_filter() -> None:
    """filter"""
    map2 = HashMap.make(("a", 1), ("b", 2), ("c", 3), ("d", 4)).filter(
        lambda value, _key: value % 2 == 0
    )
    assert len(map2) == 2
    assert [map2.has(k) for k in "abcd"] == [False, True, False, True]


def test_compact() -> None:
    """compact"""
    map1 = HashMap.make(("a", Some(1)), ("b", None), ("c", Some(3)))
    map2 = map1.compact()
    assert len(map2) == 2
    assert map2.get("a") == Some(1)
    assert not map2.has("b")
    assert map2.get("c") == Some(3)


def test_filter_map() -> None:
    """filterMap"""
    map2 = HashMap.make(("a", 1), ("b", 2), ("c", 3), ("d", 4)).filter_map(
        lambda value, _key: Ok(value * 2) if value % 2 == 0 else Err(None)
    )
    assert len(map2) == 2
    assert map2.get("b") == Some(4)
    assert map2.get("d") == Some(8)
    assert not map2.has("a")
    assert not map2.has("c")


def test_filter_map_key_argument() -> None:
    """filterMap - key argument"""
    map2 = HashMap.make(("a", 1), ("b", 2), ("c", 3), ("d", 4)).filter_map(
        lambda value, key: Ok(f"{key}:{value}") if key < "c" else Err(None)
    )
    assert len(map2) == 2
    assert map2.get("a") == Some("a:1")
    assert map2.get("b") == Some("b:2")
    assert not map2.has("c")
    assert not map2.has("d")


def test_find_first_returns_an_entry_matching_both_key_and_value() -> None:
    """findFirst returns an entry matching both key and value"""
    found = HashMap.make(("a", 1), ("b", 2), ("c", 3)).find_first(lambda v, k: v > 1 and k == "c")
    assert found == Some(("c", 3))


def test_find_first_not_found() -> None:
    """findFirst - not found"""
    assert HashMap.make(("a", 1), ("b", 2)).find_first(lambda v, _k: v > 5) is None


def test_some() -> None:
    """some"""
    m = HashMap.make(("a", 1), ("b", 2), ("c", 3))
    assert m.some(lambda v, _k: v > 2)
    assert not m.some(lambda v, _k: v > 5)


def test_every() -> None:
    """every"""
    m = HashMap.make(("a", 1), ("b", 2), ("c", 3))
    assert m.every(lambda v, _k: v > 0)
    assert not m.every(lambda v, _k: v > 1)


def test_has_by() -> None:
    """hasBy"""
    m = HashMap.make(("a", 1), ("b", 2), ("c", 3))
    assert m.has_by(lambda v, k: k == "b" and v == 2)
    assert not m.has_by(lambda v, k: k == "b" and v == 5)


def test_modify_at_existing_key() -> None:
    """modifyAt - existing key"""
    map2 = HashMap.make(("a", 1), ("b", 2)).modify_at(
        "a", lambda o: Some(o.value * 2) if o is not None else None
    )
    assert map2.get("a") == Some(2)


def test_modify_at_non_existing_key() -> None:
    """modifyAt - non-existing key"""
    map2 = HashMap.make(("a", 1)).modify_at("b", lambda o: o if o is not None else Some(10))
    assert map2.get("b") == Some(10)


def test_modify_at_remove_via_none() -> None:
    """modifyAt - remove via None"""
    map2 = HashMap.make(("a", 1), ("b", 2)).modify_at("a", lambda _: None)
    assert not map2.has("a")
    assert map2.has("b")


def test_modify() -> None:
    """modify"""
    map2 = HashMap.make(("a", 1), ("b", 2)).modify("a", lambda v: v * 3)
    assert map2.get("a") == Some(3)
    assert map2.get("b") == Some(2)


def test_reduce() -> None:
    """reduce"""
    assert HashMap.make(("a", 1), ("b", 2), ("c", 3)).reduce(0, lambda acc, v, _k: acc + v) == 6


def test_for_each_visits_each_key_and_value() -> None:
    """forEach visits each key and value"""
    collected: list[tuple[str, int]] = []
    HashMap.make(("a", 1), ("b", 2)).for_each(lambda v, k: collected.append((k, v)))
    assert sorted(collected) == [("a", 1), ("b", 2)]


def test_mutate_allows_in_place_modifications() -> None:
    """mutate allows in-place modifications"""
    map1 = HashMap.make(("a", 1))

    def update(m: HashMap[str, int]) -> None:
        m.set("b", 2)
        m.set("c", 3)

    map2 = map1.mutate(update)
    assert len(map1) == 1
    assert len(map2) == 3
    assert map2.get("a") == Some(1)
    assert map2.get("b") == Some(2)
    assert map2.get("c") == Some(3)


def test_begin_mutation_creates_distinct_mutable_instance() -> None:
    """beginMutation creates distinct mutable instance"""
    map1 = HashMap.make(("a", 1))
    mutable = map1.begin_mutation()
    assert mutable is not map1
    mutable.set("b", 2)
    assert len(map1) == 1
    assert len(mutable) == 2
    assert mutable.end_mutation() is mutable


def test_mutations_are_isolated_from_original() -> None:
    """mutations are isolated from original"""
    original = HashMap.make(("a", 1), ("b", 2))

    def update(m: HashMap[str, int]) -> None:
        m.set("a", 100)
        m.remove("b")
        m.set("c", 3)

    mutated = original.mutate(update)
    assert original.get("a") == Some(1)
    assert original.get("b") == Some(2)
    assert not original.has("c")
    assert mutated.get("a") == Some(100)
    assert not mutated.has("b")
    assert mutated.get("c") == Some(3)


def test_equal_equals() -> None:
    """Equal.equals"""
    map1 = HashMap.make(("a", 1), ("b", 2))
    assert map1 == HashMap.make(("b", 2), ("a", 1))
    assert map1 != HashMap.make(("a", 1), ("b", 3))


def test_hash_hash() -> None:
    """Hash.hash"""
    assert hash(HashMap.make(("a", 1), ("b", 2))) == hash(HashMap.make(("b", 2), ("a", 1)))


class Person:
    def __init__(self, name: str, age: int) -> None:
        self.name, self.age = name, age

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Person) and (self.name, self.age) == (other.name, other.age)

    def __hash__(self) -> int:
        return hash(self.name) ^ hash(self.age)


def test_should_work_with_equal_objects_as_keys() -> None:
    """should work with Equal objects as keys"""
    person1, person2, person3 = Person("Alice", 25), Person("Alice", 25), Person("Bob", 30)
    m = HashMap.make((person1, "value1"), (person3, "value3"))
    assert m.get(person2) == Some("value1")
    assert m.has(person2)
    map2 = m.set(person2, "updated")
    assert map2.get(person1) == Some("updated")
    assert len(map2) == 2


class FixedHashKey:
    def __init__(self, id: str, hash: int) -> None:
        self.id, self.hash = id, hash

    def __eq__(self, other: object) -> bool:
        return isinstance(other, FixedHashKey) and self.id == other.id

    def __hash__(self) -> int:
        return self.hash


def test_keeps_entries_addressable_when_bit_31_is_present_in_indexed_leaf_insert() -> None:
    """keeps entries addressable when bit 31 is present in indexed leaf insert"""
    bit31, bit30 = FixedHashKey("bit31", 31), FixedHashKey("bit30", 30)
    m = HashMap[FixedHashKey, str].empty().set(bit31, "session1").set(bit30, "session2")
    assert len(m) == 2
    assert m.get(bit31) == Some("session1")
    assert m.get(bit30) == Some("session2")


def test_keeps_entries_addressable_when_merge_leaves_sees_bit_31() -> None:
    """keeps entries addressable when mergeLeaves sees bit 31"""
    a, b, c = FixedHashKey("collisionA", 31), FixedHashKey("collisionB", 31), FixedHashKey("c", 30)
    m = HashMap[FixedHashKey, str].empty().set(a, "a").set(b, "b").set(c, "c")
    assert len(m) == 3
    assert (m.get(a), m.get(b), m.get(c)) == (Some("a"), Some("b"), Some("c"))


def test_keeps_all_inserted_entries_addressable_across_random_bit_31_heavy_shapes() -> None:
    """keeps all inserted entries addressable across random bit-31-heavy shapes"""
    rng = random.Random(0)
    for _ in range(200):
        hashes = [31, 31, 30, *(rng.randint(0, 31) for _ in range(rng.randint(0, 80)))]
        m = HashMap[FixedHashKey, str].empty()
        inserted: list[tuple[FixedHashKey, str]] = []
        for h in hashes:
            key = FixedHashKey(str(uuid.UUID(int=rng.getrandbits(128))), h)
            m = m.set(key, f"value-{key.id}")
            inserted.append((key, f"value-{key.id}"))
        assert len(m) == len(inserted)
        for key, value in inserted:
            assert m.has(key)
            assert m.get(key) == Some(value)


def test_set_stores_a_new_value_that_is_equal_to_the_current_one() -> None:
    """set stores a new value that is equal to the current one"""
    operations = 0

    class Versioned:
        def __init__(self, id: str, version: int) -> None:
            self.id, self.version = id, version

        def __eq__(self, other: object) -> bool:
            nonlocal operations
            operations += 1
            return isinstance(other, Versioned) and self.id == other.id

        def __hash__(self) -> int:
            nonlocal operations
            operations += 1
            return hash(self.id)

    a, b = FixedHashKey("collisionA", 7), FixedHashKey("collisionB", 7)
    leaf = HashMap.make(("a", Versioned("a", 0)))
    collisions = HashMap.make((a, Versioned("a", 0)), (b, Versioned("b", 0)))
    operations = 0
    new = Versioned("a", 1)
    assert leaf.set("a", new).get_unsafe("a") is new
    assert collisions.set(a, new).get_unsafe(a) is new
    assert operations == 0


def test_set_uses_object_is_to_decide_whether_to_preserve_map_identity() -> None:
    """set uses Object.is to decide whether to preserve map identity"""
    a, b = FixedHashKey("collisionA", 7), FixedHashKey("collisionB", 7)
    for stored in ({"x": 1}, math.nan, 0.0):
        for m in (HashMap.make((a, stored)), HashMap.make((a, stored), (b, stored))):
            assert m.set(a, stored) is m
            if stored == 0.0:
                updated = m.set(a, -0.0)
                assert updated is not m
                assert math.copysign(1, updated.get_unsafe(a)) == -1  # pyright: ignore[reportArgumentType]


def test_is_hash_map() -> None:
    """isHashMap"""
    assert isinstance(HashMap.make(("a", 1)), HashMap)
    assert not isinstance({"a": 1}, HashMap)
    assert not isinstance(None, HashMap)


def test_handles_many_inserts_lookups_and_removals() -> None:
    """handles many inserts, lookups, and removals"""
    m = HashMap[int, str].empty()
    for i in range(1000):
        m = m.set(i, f"value{i}")
    assert len(m) == 1000
    for _ in range(100):
        key = random.randrange(1000)
        assert m.get(key) == Some(f"value{key}")
    for i in range(500):
        m = m.remove(i)
    assert len(m) == 500
    assert not any(m.has(i) for i in range(500))
    assert all(m.has(i) for i in range(500, 1000))


def test_should_handle_hash_collisions() -> None:
    """should handle hash collisions"""

    class CollidingKey:
        def __init__(self, id: int) -> None:
            self.id = id

        def __eq__(self, other: object) -> bool:
            return isinstance(other, CollidingKey) and self.id == other.id

        def __hash__(self) -> int:
            return 42

    key1, key2, key3 = CollidingKey(1), CollidingKey(2), CollidingKey(3)
    m = HashMap[CollidingKey, str].empty().set(key1, "value1").set(key2, "value2")
    m = m.set(key3, "value3")
    assert len(m) == 3
    assert (m.get(key1), m.get(key2), m.get(key3)) == (
        Some("value1"),
        Some("value2"),
        Some("value3"),
    )
    m = m.remove(key2)
    assert len(m) == 2
    assert m.has(key1)
    assert not m.has(key2)
    assert m.has(key3)


class _Hashed:
    """A key with the hash Effect's test hands ``modifyHash``."""

    def __init__(self, name: str, hash: int) -> None:
        self.name = name
        self.hash = hash

    def __eq__(self, other: object) -> bool:
        return isinstance(other, _Hashed) and other.name == self.name

    def __hash__(self) -> int:
        return self.hash


def test_preserves_traversal_order_across_every_node_kind() -> None:
    """preserves traversal order across every node kind"""
    empty = HashMap[_Hashed, int].empty()
    assert list(empty) == []
    assert list(empty.keys()) == []
    assert list(empty.values()) == []
    inputs = [
        *((f"leaf-{17 - i}", 17 - i, 17 - i) for i in range(16)),
        ("nested-2", 65, 102),
        ("collision-first", 0, 1),
        ("nested-0", 1, 100),
        ("collision-second", 0, 2),
        ("nested-1", 33, 101),
    ]
    m = empty
    for name, hash, value in inputs:
        m = m.modify_hash(_Hashed(name, hash), hash, lambda _, v=value: Some(v))
    expected = [
        ("collision-first", 1),
        ("collision-second", 2),
        ("nested-0", 100),
        ("nested-1", 101),
        ("nested-2", 102),
        *((f"leaf-{i + 2}", i + 2) for i in range(16)),
    ]
    assert [(k.name, v) for k, v in m] == expected
    assert [(k.name, v) for k, v in m.entries()] == expected
    keys = list(m.keys())
    assert [k.name for k in keys] == [k for k, _ in expected]
    assert list(m.values()) == [v for _, v in expected]
