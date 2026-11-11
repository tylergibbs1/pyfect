"""Persistent and mutable collections against Python models, as sequences of operations.

Keys are drawn where Effect's ``Equal`` and Python's ``==`` disagree (``True`` and ``1``, NaN,
``1`` and ``1.0``, lists and tuples), plus keys whose hashes collide on purpose, so the
trie's collision nodes are built and taken apart. Each machine also keeps an earlier version
of a persistent collection and checks that later updates never changed it.
"""

from __future__ import annotations

import math
from collections.abc import Hashable
from typing import Any, cast

from hypothesis import given
from hypothesis import strategies as st
from hypothesis.stateful import (
    Bundle,
    RuleBasedStateMachine,
    initialize,
    invariant,
    precondition,
    rule,
)

from pyfect import duration
from pyfect._effect_hash import effect_hash
from pyfect._equal import equal_key, equals
from pyfect.hash_map import HashMap
from pyfect.hash_set import HashSet
from pyfect.mutable_hash_map import MutableHashMap
from pyfect.mutable_hash_set import MutableHashSet
from pyfect.option import Some
from pyfect.trie import Trie


class CollidingKey:
    """A key whose hash is one of a few values, so different keys share hashes."""

    __slots__ = ("hash", "id")

    def __init__(self, id: int, hash: int) -> None:
        self.id = id
        self.hash = hash

    def __eq__(self, other: object) -> bool:
        return isinstance(other, CollidingKey) and self.id == other.id

    def __hash__(self) -> int:
        return self.hash

    def __repr__(self) -> str:
        return f"CollidingKey({self.id}, {self.hash})"


_scalars = st.one_of(
    st.integers(-3, 3),
    st.booleans(),
    st.sampled_from([1.0, 0.5, -0.0, math.nan, math.inf]),
    st.text(max_size=2),
    st.none(),
)
_keys: st.SearchStrategy[object] = st.one_of(
    _scalars,
    st.lists(_scalars, max_size=2),
    st.tuples(_scalars, _scalars),
    st.builds(CollidingKey, st.integers(0, 40), st.sampled_from([0, 1, 2**31, 2**31 + 1])),
)
_values = st.integers(-5, 5)


def _model_entries(model: dict[Hashable, tuple[object, int]]) -> set[tuple[Hashable, int]]:
    return {(ident, value) for ident, (_, value) in model.items()}


def _entries(pairs: Any) -> set[tuple[Hashable, int]]:
    return {(equal_key(k), v) for k, v in pairs}


class HashMapMachine(RuleBasedStateMachine):
    def __init__(self) -> None:
        super().__init__()
        self.map: HashMap[object, int] = HashMap[object, int].empty()
        self.model: dict[Hashable, tuple[object, int]] = {}
        self.saved: list[tuple[HashMap[object, int], set[tuple[Hashable, int]]]] = []

    @rule(key=_keys, value=_values)
    def set(self, key: object, value: int) -> None:
        self.map = self.map.set(key, value)
        ident = equal_key(key)
        # An equal key already there is kept.
        kept = self.model[ident][0] if ident in self.model else key
        self.model[ident] = (kept, value)

    @rule(key=_keys)
    def remove(self, key: object) -> None:
        self.map = self.map.remove(key)
        self.model.pop(equal_key(key), None)

    @rule(entries=st.lists(st.tuples(_keys, _values), max_size=6))
    def set_many(self, entries: list[tuple[object, int]]) -> None:
        self.map = self.map.set_many(entries)
        for key, value in entries:
            ident = equal_key(key)
            self.model[ident] = (self.model.get(ident, (key, 0))[0], value)

    @rule(keys=st.lists(_keys, max_size=6))
    def remove_many(self, keys: list[object]) -> None:
        self.map = self.map.remove_many(keys)
        for key in keys:
            self.model.pop(equal_key(key), None)

    @rule(key=_keys, value=st.one_of(st.none(), _values))
    def modify_at(self, key: object, value: int | None) -> None:
        self.map = self.map.modify_at(key, lambda _: None if value is None else Some(value))
        ident = equal_key(key)
        if value is None:
            self.model.pop(ident, None)
        else:
            self.model[ident] = (self.model.get(ident, (key, 0))[0], value)

    @rule(
        ops=st.lists(st.tuples(st.booleans(), _keys, _values), max_size=8),
    )
    def mutate(self, ops: list[tuple[bool, object, int]]) -> None:
        """A batch on a mutable draft, which must leave the map it came from unchanged."""
        before, before_entries = self.map, _entries(self.map)

        def apply(draft: HashMap[object, int]) -> None:
            for is_set, key, value in ops:
                if is_set:
                    draft.set(key, value)
                else:
                    draft.remove(key)

        self.map = self.map.mutate(apply)
        for is_set, key, value in ops:
            ident = equal_key(key)
            if is_set:
                self.model[ident] = (self.model.get(ident, (key, 0))[0], value)
            else:
                self.model.pop(ident, None)
        assert _entries(before) == before_entries

    @rule(other=st.lists(st.tuples(_keys, _values), max_size=6))
    def union(self, other: list[tuple[object, int]]) -> None:
        self.map = self.map.union(HashMap[object, int].from_iterable(other))
        for key, value in other:
            ident = equal_key(key)
            self.model[ident] = (self.model.get(ident, (key, 0))[0], value)

    @rule()
    def save(self) -> None:
        self.saved.append((self.map, _model_entries(self.model)))

    @invariant()
    def matches_the_model(self) -> None:
        assert len(self.map) == len(self.model)
        assert _entries(self.map) == _model_entries(self.model)
        for ident, (key, value) in self.model.items():
            assert self.map.has(key)
            assert self.map.get(key) == Some(value)
            assert equal_key(self.map.get_unsafe(key)) == equal_key(value)
            assert ident in {equal_key(k) for k, _ in self.map}

    @invariant()
    def saved_versions_never_change(self) -> None:
        for version, entries in self.saved:
            assert _entries(version) == entries

    @invariant()
    def equal_maps_hash_alike(self) -> None:
        rebuilt = HashMap[object, int].from_iterable(reversed(list(self.map)))
        assert rebuilt == self.map
        assert hash(rebuilt) == hash(self.map)


class HashSetMachine(RuleBasedStateMachine):
    def __init__(self) -> None:
        super().__init__()
        self.set: HashSet[object] = HashSet[object].empty()
        self.model: set[Hashable] = set()
        self.saved: list[tuple[HashSet[object], set[Hashable]]] = []

    @rule(value=_keys)
    def add(self, value: object) -> None:
        self.set = self.set.add(value)
        self.model.add(equal_key(value))

    @rule(value=_keys)
    def remove(self, value: object) -> None:
        self.set = self.set.remove(value)
        self.model.discard(equal_key(value))

    @rule(values=st.lists(_keys, max_size=6))
    def union(self, values: list[object]) -> None:
        self.set = self.set.union(HashSet[object].from_iterable(values))
        self.model |= {equal_key(v) for v in values}

    @rule(values=st.lists(_keys, max_size=6))
    def intersection(self, values: list[object]) -> None:
        self.set = self.set.intersection(HashSet[object].from_iterable(values))
        self.model &= {equal_key(v) for v in values}

    @rule(values=st.lists(_keys, max_size=6))
    def difference(self, values: list[object]) -> None:
        self.set = self.set.difference(HashSet[object].from_iterable(values))
        self.model -= {equal_key(v) for v in values}

    @rule(values=st.lists(_keys, max_size=6))
    def is_subset(self, values: list[object]) -> None:
        other = HashSet[object].from_iterable(values)
        assert self.set.is_subset(other) == (self.model <= {equal_key(v) for v in values})

    @rule()
    def save(self) -> None:
        self.saved.append((self.set, set(self.model)))

    @invariant()
    def matches_the_model(self) -> None:
        assert len(self.set) == len(self.model)
        assert {equal_key(v) for v in self.set} == self.model
        assert all(self.set.has(v) for v in self.set)

    @invariant()
    def saved_versions_never_change(self) -> None:
        for version, model in self.saved:
            assert {equal_key(v) for v in version} == model

    @invariant()
    def equal_sets_hash_alike(self) -> None:
        rebuilt = HashSet[object].from_iterable(reversed(list(self.set)))
        assert rebuilt == self.set
        assert hash(rebuilt) == hash(self.set)


class MutableHashMapMachine(RuleBasedStateMachine):
    def __init__(self) -> None:
        super().__init__()
        self.map: MutableHashMap[object, int] = MutableHashMap[object, int].empty()
        self.model: dict[Hashable, int] = {}

    @rule(key=_keys, value=_values)
    def set(self, key: object, value: int) -> None:
        self.map.set(key, value)
        self.model[equal_key(key)] = value

    @rule(key=_keys)
    def remove(self, key: object) -> None:
        self.map.remove(key)
        self.model.pop(equal_key(key), None)

    @rule(key=_keys, value=st.one_of(st.none(), _values))
    def modify_at(self, key: object, value: int | None) -> None:
        self.map.modify_at(key, lambda _: None if value is None else Some(value))
        if value is None:
            self.model.pop(equal_key(key), None)
        else:
            self.model[equal_key(key)] = value

    @precondition(lambda self: len(self.model) > 3)
    @rule()
    def clear(self) -> None:
        self.map.clear()
        self.model.clear()

    @invariant()
    def matches_the_model(self) -> None:
        assert len(self.map) == len(self.model)
        assert {(equal_key(k), v) for k, v in self.map} == set(self.model.items())
        for key, _ in self.map:
            assert self.map.get(key) == Some(self.model[equal_key(key)])


class MutableHashSetMachine(RuleBasedStateMachine):
    def __init__(self) -> None:
        super().__init__()
        self.set: MutableHashSet[object] = MutableHashSet[object].empty()
        self.model: set[Hashable] = set()

    @rule(value=_keys)
    def add(self, value: object) -> None:
        self.set.add(value)
        self.model.add(equal_key(value))

    @rule(value=_keys)
    def remove(self, value: object) -> None:
        self.set.remove(value)
        self.model.discard(equal_key(value))

    @invariant()
    def matches_the_model(self) -> None:
        assert len(self.set) == len(self.model)
        assert {equal_key(v) for v in self.set} == self.model


_trie_keys = st.text(alphabet="abé\U0001f600", max_size=4)


def _utf16(key: str) -> bytes:
    return key.encode("utf-16-be")


class TrieMachine(RuleBasedStateMachine):
    """Keys share prefixes (a small alphabet) and include a character past U+FFFF, which
    JavaScript's order puts below U+E000."""

    keys = Bundle("keys")

    def __init__(self) -> None:
        super().__init__()
        self.trie: Trie[int] = Trie[int].empty()
        self.model: dict[str, int] = {}
        self.saved: list[tuple[Trie[int], dict[str, int]]] = []

    @initialize(target=keys, key=_trie_keys)
    def first_key(self, key: str) -> str:
        return key

    @rule(target=keys, key=_trie_keys, value=_values)
    def insert(self, key: str, value: int) -> str:
        self.trie = self.trie.insert(key, value)
        self.model[key] = value
        return key

    @rule(key=keys)
    def remove(self, key: str) -> None:
        self.trie = self.trie.remove(key)
        self.model.pop(key, None)

    @rule(prefix=keys)
    def with_prefix(self, prefix: str) -> None:
        expected = sorted((k for k in self.model if k.startswith(prefix)), key=_utf16)
        assert list(self.trie.keys_with_prefix(prefix)) == expected

    @rule(text=_trie_keys)
    def longest_prefix_of(self, text: str) -> None:
        candidates = [k for k in self.model if text.startswith(k)]
        found = self.trie.longest_prefix_of(text)
        if candidates:
            best = max(candidates, key=len)
            assert found == Some((best, self.model[best]))
        else:
            assert found is None

    @rule()
    def save(self) -> None:
        self.saved.append((self.trie, dict(self.model)))

    @invariant()
    def matches_the_model_in_key_order(self) -> None:
        assert len(self.trie) == len(self.model)
        assert list(self.trie.entries()) == sorted(self.model.items(), key=lambda kv: _utf16(kv[0]))

    @invariant()
    def saved_versions_never_change(self) -> None:
        for version, model in self.saved:
            assert dict(version.entries()) == model


TestHashMap = HashMapMachine.TestCase
TestHashSet = HashSetMachine.TestCase
TestMutableHashMap = MutableHashMapMachine.TestCase
TestMutableHashSet = MutableHashSetMachine.TestCase
TestTrie = TrieMachine.TestCase


# --- Equal and Hash --------------------------------------------------------------------------

_nested: st.SearchStrategy[object] = st.recursive(
    _scalars,
    lambda inner: st.one_of(
        st.lists(inner, max_size=3),
        st.tuples(inner, inner),
        st.dictionaries(st.text(max_size=2), inner, max_size=3),
        st.frozensets(st.one_of(st.integers(-3, 3), st.text(max_size=2)), max_size=3),
    ),
    max_leaves=8,
)


def _twin(value: object) -> object:  # noqa: PLR0911
    """An equal value built differently: lists as tuples, dicts and sets in another order,
    ints as floats."""
    match value:
        case bool() | None | str():
            return value
        case int():
            return float(value)
        case float() if value.is_integer() and abs(value) < 2**53:
            return int(value)
        case list():
            return tuple(_twin(v) for v in cast("list[object]", value))
        case tuple():
            return [_twin(v) for v in cast("tuple[object, ...]", value)]
        case dict():
            items = list(cast("dict[str, object]", value).items())
            return {k: _twin(v) for k, v in reversed(items)}
        case frozenset():
            return frozenset(reversed(list(cast("frozenset[object]", value))))
        case _:
            return value


@given(_nested)
def test_equal_values_have_equal_keys_and_hashes(value: object):
    twin = _twin(value)
    assert equals(value, twin)
    assert equal_key(value) == equal_key(twin)
    assert effect_hash(equal_key(value)) == effect_hash(equal_key(twin))


@given(_nested, _nested)
def test_equals_agrees_with_equal_key(a: object, b: object):
    assert equals(a, b) == (equal_key(a) == equal_key(b))
    if equals(a, b):
        assert effect_hash(equal_key(a)) == effect_hash(equal_key(b))


@given(st.lists(st.tuples(_keys, _nested), max_size=8), st.randoms())
def test_maps_built_in_any_order_are_equal_and_hash_alike(
    entries: list[tuple[object, object]], random: Any
):
    deduped = list({equal_key(k): (k, v) for k, v in entries}.values())
    shuffled = list(deduped)
    random.shuffle(shuffled)
    a = HashMap[object, object].from_iterable(deduped)
    b = HashMap[object, object].from_iterable((k, _twin(v)) for k, v in shuffled)
    assert a == b
    assert hash(a) == hash(b)
    assert HashSet[object].from_iterable(k for k, _ in deduped) == HashSet[object].from_iterable(
        k for k, _ in shuffled
    )


@given(st.integers(-(2**53), 2**53))
def test_a_duration_is_equal_and_hashes_alike_in_any_unit(ms: int):
    as_millis, as_nanos = duration.millis(ms), duration.nanos(ms * 1_000_000)
    assert as_millis == as_nanos
    assert hash(as_millis) == hash(as_nanos)
