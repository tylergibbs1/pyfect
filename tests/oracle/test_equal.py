"""Ports of Effect's ``Equal.test.ts``.

Effect's ``Equal`` is Python's ``==`` (docs/PARITY.md section 4), except
where pyfect compares values the way Effect does (``Stream.changes``,
unique checks, set and map codecs, cause dedupe): those go through
``pyfect._equal.equals``, which these ports exercise. A plain object is a
``dict``, an array a ``list``, a ``Map`` a ``dict``, a ``Set`` a
``frozenset`` (whose items must be hashable, so object and array items are
tuples), ``null`` / ``undefined`` is ``None`` and a ``Date`` a ``datetime``.
A class with an ``Equal`` implementation is one with ``__eq__``.

Omitted, with the reason:

- the "symbol properties", "non-enumerable properties" and "hash
  consistency with symbol properties" titles: Python has no symbol keys or
  property enumerability.
- "should compare invalid dates without throwing": there is no invalid
  ``datetime``.
- the "ArrayBuffer objects" and "DataView objects" titles: Python's
  ``bytes``, ``bytearray`` and ``memoryview`` compare by content across
  kinds, and pyfect keeps that (``bytes`` is ported as "should handle
  Uint8Array").
- "should work with HashMap (implements Equal interface)" and "HashMap
  should not equal plain objects": Python's ``dict`` is both HashMap and
  plain object.
- the "byReference" and "byReferenceUnsafe" titles: a class without
  ``__eq__`` compares by identity (section 4); a ``dict`` or ``list`` cannot
  be marked.
- the "Error objects" titles: a Python exception compares by identity;
  ``errors.TaggedError`` compares by its fields (``test_data.py``).
- the "objects with different constructors" titles: instances of a class
  without ``__eq__`` compare by identity, never with a ``dict`` of the same
  shape.
- "should handle hashing objects with circular references without infinite
  recursion", "should handle hashing arrays with circular references
  without infinite recursion" and "should produce different hashes for
  objects with different circular structures": a ``dict`` or ``list`` has
  no hash in Python.
"""

from __future__ import annotations

import itertools
import math
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import pytest

from pyfect._equal import equals
from pyfect.option import Some

INF = math.inf
NAN = math.nan


class Key:
    """Effect's ``Key``: equal by group, every key hashing alike."""

    def __init__(self, group: str) -> None:
        self.group = group

    def __eq__(self, that: object) -> bool:
        return isinstance(that, Key) and self.group == that.group

    def __hash__(self) -> int:
        return 0


def node(v: int) -> list[Any]:
    """A graph node ``[v, a, b]``: a list compared structurally, as Effect
    compares a class instance without ``Equal``."""
    return [v, None, None]


type Spec = list[tuple[int, int, int]]


def graph(spec: Spec) -> list[list[Any]]:
    nodes = [node(v) for v, _, _ in spec]
    for i, (_, a, b) in enumerate(spec):
        nodes[i][1] = nodes[a]
        nodes[i][2] = nodes[b]
    return nodes


def test_does_not_cache_an_equality_found_through_a_provisional_circular_pair() -> None:
    """does not cache an equality found through a provisional circular pair"""
    p: dict[str, Any] = {}
    q: dict[str, Any] = {}
    a = {"child": p, "x": 1, "y": 2}
    b = {"child": q, "x": 2, "y": 1}
    p["parent"] = a
    q["parent"] = b
    assert not equals(a, b)
    assert not equals(p, q)


def test_does_not_let_an_earlier_comparison_change_a_later_result() -> None:
    """does not let an earlier comparison change a later result"""
    _, n2 = graph([(1, 1, 0), (1, 0, 0)])
    m0, m1 = graph([(1, 1, 1), (1, 1, 0)])
    equals(n2, m1)
    assert equals({"w": n2, "k": 1}, {"w": m0, "k": 1})


def test_assumes_cycles_equal_pair_by_pair() -> None:
    """assumes cycles equal pair by pair"""
    [loop] = graph([(0, 0, 0)])
    _, entry = graph([(0, 0, 0), (0, 0, 0)])
    assert equals(loop, entry)
    _, p1 = graph([(1, 0, 0), (0, 0, 0)])
    _, q1 = graph([(1, 1, 0), (0, 0, 0)])
    assert not equals(p1, q1)


def test_agrees_with_bisimilarity_on_random_cyclic_graphs() -> None:
    """agrees with bisimilarity on random cyclic graphs"""

    def bisimilar(left: Spec, right: Spec) -> list[list[bool]]:
        related = [[lv == rv for rv, _, _ in right] for lv, _, _ in left]
        changed = True
        while changed:
            changed = False
            for i, (_, la, lb) in enumerate(left):
                for j, (_, ra, rb) in enumerate(right):
                    if related[i][j] and not (related[la][ra] and related[lb][rb]):
                        related[i][j] = False
                        changed = True
        return related

    seed = 1

    def random(n: int) -> int:
        nonlocal seed
        seed = (seed * 1103515245 + 12345) & 0xFFFFFFFF
        return (seed >> 16) % n

    def random_spec() -> Spec:
        size = 1 + random(4)
        return [(random(2), random(size), random(size)) for _ in range(size)]

    disagreements: list[str] = []
    for _ in range(500):
        left = random_spec()
        right = random_spec()
        expected = bisimilar(left, right)
        for x, y in itertools.product(range(len(left)), range(len(right))):
            if equals(graph(left)[x], graph(right)[y]) != expected[x][y]:
                disagreements.append(f"{left}[{x}] vs {right}[{y}]")
    assert disagreements == []


def test_plain_objects_structurally_identical() -> None:
    """should return true for structurally identical objects (structural equality)"""
    assert equals({"a": 1, "b": 2}, {"a": 1, "b": 2})


def test_plain_objects_same_reference() -> None:
    """plain objects: should return true for same reference"""
    obj = {"a": 1, "b": 2}
    assert equals(obj, obj)


def test_plain_objects_empty() -> None:
    """should return true for empty objects"""
    assert equals({}, {})


def test_plain_objects_different_values() -> None:
    """should return false for objects with different values"""
    assert not equals({"a": 1, "b": 2}, {"a": 1, "b": 3})


def test_plain_objects_different_keys() -> None:
    """should return false for objects with different keys"""
    assert not equals({"a": 1, "b": 2}, {"a": 1, "c": 2})


def test_plain_arrays_structurally_identical() -> None:
    """should return true for structurally identical arrays (structural equality)"""
    assert equals([1, 2, 3], [1, 2, 3])


def test_plain_arrays_same_reference() -> None:
    """plain arrays: should return true for same reference"""
    arr = [1, 2, 3]
    assert equals(arr, arr)


def test_plain_arrays_empty() -> None:
    """should return true for empty arrays"""
    assert equals([], [])


def test_plain_arrays_different_elements() -> None:
    """should return false for arrays with different elements"""
    assert not equals([1, 2, 3], [1, 2, 4])


def test_plain_arrays_different_lengths() -> None:
    """should return false for arrays with different lengths"""
    assert not equals([1, 2, 3], [1, 2])


def test_primitives_numbers() -> None:
    """should work correctly for numbers"""
    assert equals(42, 42)
    assert not equals(42, 43)


def test_primitives_strings() -> None:
    """should work correctly for strings"""
    assert equals("hello", "hello")
    assert not equals("hello", "world")


def test_primitives_booleans() -> None:
    """should work correctly for booleans"""
    assert equals(True, True)
    assert equals(False, False)
    assert not equals(True, False)


def test_primitives_null_and_undefined() -> None:
    """should work correctly for null and undefined (Python has one ``None``)"""
    assert equals(None, None)
    assert not equals(None, 0)


def test_dates_compare_by_instant() -> None:
    """should compare dates by ISO string"""
    assert equals(datetime(2023, 1, 1, tzinfo=UTC), datetime(2023, 1, 1, tzinfo=UTC))


def test_different_dates() -> None:
    """should return false for different dates"""
    assert not equals(datetime(2023, 1, 1, tzinfo=UTC), datetime(2023, 1, 2, tzinfo=UTC))


def test_option_implements_equal() -> None:
    """should work with Option (implements Equal interface)"""
    assert equals(Some(42), Some(42))


@dataclass(frozen=True)
class CustomPoint:
    x: float
    y: float


def test_custom_equal_implementation() -> None:
    """should work with custom Equal implementation"""
    assert equals(CustomPoint(1, 2), CustomPoint(1, 2))


def test_clears_visited_state_when_a_custom_equal_throws() -> None:
    """clears visited state when a custom Equal throws"""
    throws = True

    class Flaky:
        def __init__(self, id: int) -> None:
            self.id = id

        def __eq__(self, that: object) -> bool:
            if throws:
                raise ValueError("boom")
            return isinstance(that, Flaky) and self.id == that.id

        def __hash__(self) -> int:
            return 0

    x = {"k": Flaky(1)}
    y = {"k": Flaky(2)}
    with pytest.raises(ValueError, match="boom"):
        equals(x, y)
    throws = False
    assert not equals(x, y)
    assert equals(x, {"k": Flaky(1)})


def test_nested_objects() -> None:
    """should return true for nested objects (deep structural equality)"""
    assert equals({"a": {"b": 1}, "c": [1, 2]}, {"a": {"b": 1}, "c": [1, 2]})


def test_nested_arrays() -> None:
    """should return true for nested arrays (deep structural equality)"""
    assert equals([[1, 2], [3, 4]], [[1, 2], [3, 4]])


def test_nested_objects_different_values() -> None:
    """should return false for nested objects with different values"""
    assert not equals({"a": {"b": 1}, "c": [1, 2]}, {"a": {"b": 2}, "c": [1, 2]})


def test_nested_arrays_different_values() -> None:
    """should return false for nested arrays with different values"""
    assert not equals([[1, 2], [3, 4]], [[1, 3], [3, 4]])


def test_nan_equals_nan() -> None:
    """should handle NaN correctly (structural equality - NaN equals NaN)"""
    assert equals(NAN, float("nan"))


def test_nan_against_regular_numbers() -> None:
    """should return false when comparing NaN with regular numbers"""
    assert not equals(NAN, 0)
    assert not equals(NAN, 42)
    assert not equals(42, NAN)


def test_nan_against_infinity() -> None:
    """should return false when comparing NaN with Infinity"""
    assert not equals(NAN, INF)
    assert not equals(NAN, -INF)
    assert not equals(INF, NAN)
    assert not equals(-INF, NAN)


def test_nan_in_arrays() -> None:
    """should handle NaN in arrays"""
    assert equals([NAN], [float("nan")])
    assert equals([NAN, 1], [float("nan"), 1])
    assert not equals([NAN, 1], [NAN, 2])
    assert not equals([NAN], [INF])


def test_nan_in_objects() -> None:
    """should handle NaN in objects"""
    assert equals({"a": NAN}, {"a": float("nan")})
    assert equals({"a": NAN, "b": 1}, {"a": float("nan"), "b": 1})
    assert not equals({"a": NAN}, {"a": INF})
    assert not equals({"a": NAN}, {"a": 42})


def test_nan_in_nested_structures() -> None:
    """should handle NaN in nested structures"""
    assert equals({"arr": [NAN]}, {"arr": [float("nan")]})
    assert equals([{"val": NAN}], [{"val": float("nan")}])
    assert equals({"nested": {"deep": NAN}}, {"nested": {"deep": float("nan")}})
    assert not equals({"arr": [NAN]}, {"arr": [INF]})


@pytest.mark.parametrize("inf", [INF, -INF])
def test_infinity_equals_itself(inf: float) -> None:
    """should handle Infinity correctly (structural equality); should handle
    -Infinity correctly (structural equality)"""
    assert equals(inf, float(inf))


def test_infinity_against_regular_numbers() -> None:
    """should return false when comparing Infinity with regular numbers"""
    assert not equals(INF, 0)
    assert not equals(INF, 42)
    assert not equals(42, INF)
    assert not equals(INF, 1.7976931348623157e308)


def test_infinity_against_negative_infinity() -> None:
    """should return false when comparing Infinity with -Infinity"""
    assert not equals(INF, -INF)
    assert not equals(-INF, INF)


def test_negative_infinity_against_regular_numbers() -> None:
    """should return false when comparing -Infinity with regular numbers"""
    assert not equals(-INF, 0)
    assert not equals(-INF, -42)
    assert not equals(-42, -INF)
    assert not equals(-INF, 5e-324)


@pytest.mark.parametrize("inf", [INF, -INF])
def test_infinity_in_arrays(inf: float) -> None:
    """should handle Infinity in arrays; should handle -Infinity in arrays"""
    assert equals([inf], [inf])
    assert equals([inf, 1], [inf, 1])
    assert not equals([inf, 1], [inf, 2])
    assert not equals([inf], [-inf])


@pytest.mark.parametrize("inf", [INF, -INF])
def test_infinity_in_objects(inf: float) -> None:
    """should handle Infinity in objects; should handle -Infinity in objects"""
    assert equals({"a": inf}, {"a": inf})
    assert equals({"a": inf, "b": 1}, {"a": inf, "b": 1})
    assert not equals({"a": inf}, {"a": -inf})
    assert not equals({"a": inf}, {"a": 42})


@pytest.mark.parametrize("inf", [INF, -INF])
def test_infinity_in_nested_structures(inf: float) -> None:
    """should handle Infinity in nested structures; should handle -Infinity in
    nested structures"""
    assert equals({"arr": [inf]}, {"arr": [inf]})
    assert equals([{"val": inf}], [{"val": inf}])
    assert equals({"nested": {"deep": inf}}, {"nested": {"deep": inf}})
    assert not equals({"arr": [inf]}, {"arr": [-inf]})


def test_arrays_with_multiple_special_values() -> None:
    """should handle arrays with multiple special values"""
    assert equals([NAN, INF, -INF], [float("nan"), INF, -INF])
    assert not equals([NAN, INF], [INF, NAN])
    assert equals([NAN, INF, 0], [float("nan"), INF, 0])


def test_objects_with_multiple_special_values() -> None:
    """should handle objects with multiple special values"""
    assert equals(
        {"nan": NAN, "inf": INF, "negInf": -INF},
        {"nan": float("nan"), "inf": INF, "negInf": -INF},
    )
    assert not equals({"nan": NAN, "inf": INF}, {"nan": NAN, "inf": -INF})


def test_complex_nested_structures_with_special_values() -> None:
    """should handle complex nested structures with special values"""

    def make(second: float, third: float) -> dict[str, object]:
        return {
            "data": [
                {"value": float("nan"), "meta": {"type": "special"}},
                {"value": second, "meta": {"type": "infinite"}},
                {"value": third, "meta": {"type": "negative-infinite"}},
            ]
        }

    assert equals(make(INF, -INF), make(INF, -INF))
    assert not equals(make(INF, -INF), make(-INF, INF))


def test_negative_and_positive_zero() -> None:
    """should handle -0 and +0 correctly"""
    assert equals(-0.0, 0.0)
    assert equals(0, -0.0)
    assert equals(0.0, -0.0)


def test_zero_values_in_arrays() -> None:
    """should handle zero values in arrays"""
    assert equals([-0.0], [0.0])
    assert equals([0], [-0.0])
    assert equals([-0.0, 1], [0.0, 1])


def test_zero_values_in_objects() -> None:
    """should handle zero values in objects"""
    assert equals({"a": -0.0}, {"a": 0.0})
    assert equals({"a": 0}, {"a": -0.0})


def test_maps_structurally_identical() -> None:
    """should return true for structurally identical maps"""
    assert equals({"a": 1, "b": 2}, {"a": 1, "b": 2})
    assert equals({"a": 1, "b": 2}, {"b": 2, "a": 1})


def test_maps_same_reference() -> None:
    """JavaScript Map: should return true for same reference"""
    m = {"a": 1}
    assert equals(m, m)


def test_maps_empty() -> None:
    """should return true for empty maps"""
    assert equals(dict[str, int](), dict[str, int]())


def test_maps_different_values() -> None:
    """should return false for maps with different values"""
    assert not equals({"a": 1, "b": 2}, {"a": 1, "b": 3})


def test_maps_different_keys() -> None:
    """should return false for maps with different keys"""
    assert not equals({"a": 1, "b": 2}, {"a": 1, "c": 2})


def test_maps_different_sizes() -> None:
    """should return false for maps with different sizes"""
    assert not equals({"a": 1, "b": 2}, {"a": 1})


def test_maps_with_object_keys() -> None:
    """should handle maps with object keys (hashable tuples)"""
    m1 = {("id", 1): "value1", ("nested", ("x", 1)): "value2"}
    m2 = {("id", 1): "value1", ("nested", ("x", 1)): "value2"}
    assert equals(m1, m2)


def test_maps_with_object_values() -> None:
    """should handle maps with object values"""
    assert equals({"a": {"x": 1}, "b": {"y": [1, 2]}}, {"a": {"x": 1}, "b": {"y": [1, 2]}})


def test_nested_maps() -> None:
    """should handle nested maps"""
    assert equals({"nested": {"x": 1}}, {"nested": {"x": 1}})


def test_maps_with_special_values() -> None:
    """should handle maps with special values"""
    m1 = {float("nan"): "nan", INF: "inf", -INF: "neginf"}
    m2 = {float("nan"): "nan", INF: "inf", -INF: "neginf"}
    assert equals(m1, m2)


def test_sets_structurally_identical() -> None:
    """should return true for structurally identical sets"""
    assert equals(frozenset([1, 2, 3]), frozenset([1, 2, 3]))


def test_sets_same_reference() -> None:
    """JavaScript Set: should return true for same reference"""
    s = frozenset([1, 2, 3])
    assert equals(s, s)


def test_sets_empty() -> None:
    """should return true for empty sets"""
    assert equals(frozenset[int](), frozenset[int]())


def test_sets_different_elements() -> None:
    """should return false for sets with different elements"""
    assert not equals(frozenset([1, 2, 3]), frozenset([1, 2, 4]))


def test_sets_different_sizes() -> None:
    """should return false for sets with different sizes"""
    assert not equals(frozenset([1, 2, 3]), frozenset([1, 2]))


def test_sets_in_different_insertion_order() -> None:
    """should return true for sets with same elements in different insertion order"""
    assert equals({1, 2, 3}, {3, 1, 2})


def test_sets_with_object_elements() -> None:
    """should handle sets with object elements (frozen dataclasses)"""
    assert equals(
        frozenset([CustomPoint(1, 0), CustomPoint(0, 2)]),
        frozenset([CustomPoint(1, 0), CustomPoint(0, 2)]),
    )


def test_nested_sets() -> None:
    """should handle nested sets"""
    assert equals(frozenset([frozenset([1, 2]), "other"]), frozenset([frozenset([1, 2]), "other"]))


def test_sets_with_special_values() -> None:
    """should handle sets with special values"""
    assert equals(frozenset([float("nan"), INF, -INF]), frozenset([float("nan"), INF, -INF]))


def test_sets_with_array_elements() -> None:
    """should handle sets with array elements (tuples)"""
    assert equals(frozenset([(1, 2), (3, 4)]), frozenset([(1, 2), (3, 4)]))


def test_matches_map_and_set_entries_one_to_one() -> None:
    """matches Map and Set entries one-to-one"""
    set_result = equals({Key("x"), Key("x")}, {Key("x"), Key("y")})
    map_result = equals({Key("x"): 1}, {Key("x"): 1, Key("y"): 1})
    assert [set_result, map_result] == [False, False]


def test_matches_colliding_map_and_set_entries_independent_of_insertion_order() -> None:
    """matches colliding Map and Set entries independent of insertion order"""
    assert equals({Key("x"), Key("y")}, {Key("y"), Key("x")})
    assert equals({Key("x"): 1, Key("y"): 2}, {Key("y"): 2, Key("x"): 1})


def test_matches_cyclic_values_in_colliding_map_entries() -> None:
    """matches cyclic values in colliding Map entries"""
    left: dict[str, object] = {}
    right: dict[str, object] = {}
    left["self"] = left
    right["self"] = right
    assert equals({Key("x"): left, Key("y"): 1}, {Key("y"): 1, Key("x"): right})


def test_objects_containing_maps_and_sets() -> None:
    """should handle objects containing maps and sets"""

    def make() -> dict[str, object]:
        return {
            "map": {"a": 1, "b": 2},
            "set": frozenset([1, 2, 3]),
            "array": [{"x": 1}, frozenset([4, 5])],
        }

    assert equals(make(), make())


def test_map_or_set_differing_in_nested_structures() -> None:
    """should return false when Map/Set differ in nested structures"""
    assert not equals(
        {"map": {"a": 1, "b": 2}, "set": frozenset([1, 2, 3])},
        {"map": {"a": 1, "b": 3}, "set": frozenset([1, 2, 3])},
    )


class CircularEqualTest:
    def __init__(self, value: str) -> None:
        self.value = value
        self.child: CircularEqualTest | None = None

    def __eq__(self, that: object) -> bool:
        if not isinstance(that, CircularEqualTest):
            return False
        return self.value == that.value and equals(self.child, that.child)

    def __hash__(self) -> int:
        return hash(self.value)


def test_circular_references_in_equal_implementations() -> None:
    """should handle circular references in Equal implementations without infinite recursion"""
    obj1 = CircularEqualTest("test")
    obj1.child = obj1
    obj2 = CircularEqualTest("test")
    obj2.child = obj2
    assert equals(obj1, obj2)
    obj3 = CircularEqualTest("different")
    obj3.child = obj3
    assert not equals(obj1, obj3)


def test_complex_circular_references_in_equal_implementations() -> None:
    """should handle complex circular references in Equal implementations"""

    class ComplexEqualTest:
        def __init__(self, id: int) -> None:
            self.id = id
            self.ref: ComplexEqualTest | None = None

        def __eq__(self, that: object) -> bool:
            if not isinstance(that, ComplexEqualTest):
                return False
            return self.id == that.id and equals(self.ref, that.ref)

        def __hash__(self) -> int:
            return hash(self.id)

    obj1, obj2, obj3, obj4 = (ComplexEqualTest(i) for i in (1, 2, 1, 2))
    obj1.ref, obj2.ref = obj2, obj1
    obj3.ref, obj4.ref = obj4, obj3
    assert equals(obj1, obj3)
    assert equals(obj2, obj4)


def test_expose_visited_sets_for_advanced_use_cases() -> None:
    """should expose visited sets for advanced use cases (no manual tracking needed)"""

    @dataclass(eq=False)
    class SimpleContainer:
        name: str
        items: list[SimpleContainer] = field(default_factory=list["SimpleContainer"])

        def __eq__(self, that: object) -> bool:
            if not isinstance(that, SimpleContainer):
                return False
            return (
                self.name == that.name
                and len(self.items) == len(that.items)
                and all(equals(a, b) for a, b in zip(self.items, that.items, strict=True))
            )

        def __hash__(self) -> int:
            return hash(self.name)

    container1 = SimpleContainer("A")
    container1.items.append(container1)
    container2 = SimpleContainer("A")
    container2.items.append(container2)
    assert equals(container1, container2)


def test_objects_with_circular_references() -> None:
    """should handle objects with circular references without infinite recursion"""
    obj1: dict[str, object] = {"a": 1, "b": 2}
    obj1["self"] = obj1
    obj2: dict[str, object] = {"a": 1, "b": 2}
    obj2["self"] = obj2
    assert equals(obj1, obj2)


def test_arrays_with_circular_references() -> None:
    """should handle arrays with circular references without infinite recursion"""
    arr1: list[object] = [1, 2, 3]
    arr1.append(arr1)
    arr2: list[object] = [1, 2, 3]
    arr2.append(arr2)
    assert equals(arr1, arr2)


def test_uint8_array() -> None:
    """should handle Uint8Array (``bytes``)"""
    assert equals(bytes([1, 2, 3]), bytes([1, 2, 3]))
    assert equals(bytearray([1, 2, 3]), bytearray([1, 2, 3]))


def test_mixed_circular_references_between_objects_and_arrays() -> None:
    """should handle mixed circular references between objects and arrays"""

    def make() -> dict[str, object]:
        obj: dict[str, object] = {"type": "object", "items": []}
        obj["items"] = [1, 2, obj]
        return obj

    assert equals(make(), make())


def test_objects_with_different_circular_reference_patterns() -> None:
    """should return false for objects with different circular reference patterns"""
    obj1: dict[str, object] = {"a": 1, "b": 2}
    obj1["self"] = obj1
    obj2: dict[str, object] = {"a": 1, "b": 2}
    obj2["self"] = {"a": 1, "b": 2}
    assert not equals(obj1, obj2)
