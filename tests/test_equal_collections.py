"""``HashMap``, ``HashSet``, ``MutableHashMap`` and ``MutableHashSet`` key by
Effect's ``Equal.equals``, not by ``==`` / ``hash``: what a ``dict`` or
``set`` would get wrong."""

from __future__ import annotations

import math

import pytest

from pyfect.hash_map import HashMap
from pyfect.hash_set import HashSet
from pyfect.mutable_hash_map import MutableHashMap
from pyfect.mutable_hash_set import MutableHashSet
from pyfect.option import Some


def test_true_and_one_are_different_keys() -> None:
    m = HashMap.make((1, "one"), (True, "true"))
    assert len(m) == 2
    assert m.get(1) == Some("one")
    assert m.get(True) == Some("true")
    assert m.get(1.0) == Some("one")  # one JavaScript number
    assert len(HashSet.make(0, False, 0.0)) == 2
    assert len(MutableHashMap.make((1, "a"), (True, "b"))) == 2
    assert len(MutableHashSet.make(1, True)) == 2


def test_nan_finds_nan() -> None:
    m = HashMap.make((math.nan, "nan"))
    assert m.get(float("nan")) == Some("nan")
    assert len(HashSet.make(math.nan, float("nan"))) == 1


def test_containers_are_keys_by_their_items() -> None:
    m = HashMap.make((["a", [1, 2]], "list"), ({"k": [1]}, "dict"))
    assert m.get(["a", [1, 2]]) == Some("list")
    assert m.get(("a", (1, 2))) == Some("list")
    assert m.get({"k": [1]}) == Some("dict")
    assert MutableHashSet.make([1], [1]).has([1])
    assert len(MutableHashSet.make([1], [1])) == 1


def test_maps_compare_values_with_equal() -> None:
    assert HashMap.make(("a", [math.nan])) == HashMap.make(("a", [math.nan]))
    assert HashMap.make(("a", 1)) != HashMap.make(("a", True))


def test_maps_and_sets_are_keys_of_each_other() -> None:
    inner = HashMap.make(("a", 1))
    outer = HashMap.make((inner, "found"))
    assert outer.get(HashMap.make(("a", 1))) == Some("found")
    assert HashSet.make(HashSet.make(1, 2)).has(HashSet.make(2, 1))


def test_mutable_collections_are_unhashable() -> None:
    with pytest.raises(TypeError):
        hash(MutableHashMap[str, int].empty())
    with pytest.raises(TypeError):
        HashMap.make((MutableHashSet[int].empty(), 1))
