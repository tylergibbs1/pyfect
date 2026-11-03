"""Ports of Effect's ``test/HashSet.test.ts``.

Each test's docstring is the Effect test title. Module functions are
methods; ``Equal`` / ``Hash`` objects are classes with ``__eq__`` /
``__hash__``; ``isHashSet`` is ``isinstance``.
"""

from __future__ import annotations

from pyfect.hash_set import HashSet


def test_empty_creates_an_empty_set() -> None:
    """empty creates an empty set"""
    s = HashSet[str].empty()
    assert len(s) == 0
    assert s.is_empty()


def test_make_creates_a_set_from_distinct_values() -> None:
    """make creates a set from distinct values"""
    s = HashSet.make("a", "b", "c")
    assert len(s) == 3
    assert [s.has(v) for v in "abcd"] == [True, True, True, False]


def test_make_removes_duplicate_values() -> None:
    """make removes duplicate values"""
    s = HashSet.make("a", "b", "a", "c", "b")
    assert len(s) == 3
    assert all(s.has(v) for v in "abc")


def test_from_iterable_removes_duplicate_values_from_an_iterable() -> None:
    """fromIterable removes duplicate values from an iterable"""
    s = HashSet.from_iterable(["a", "b", "c", "b", "a"])
    assert len(s) == 3
    assert all(s.has(v) for v in "abc")


def test_add_returns_a_new_set_without_mutating_the_original() -> None:
    """add returns a new set without mutating the original"""
    original = HashSet.make("a", "b")
    updated = original.add("c")
    assert len(original) == 2
    assert not original.has("c")
    assert len(updated) == 3
    assert all(updated.has(v) for v in "abc")


def test_add_returns_the_same_set_when_the_value_already_exists() -> None:
    """add returns the same set when the value already exists"""
    original = HashSet.make("a", "b")
    same = original.add("a")
    assert len(same) == 2
    assert same is original


def test_remove_returns_a_new_set_without_mutating_the_original() -> None:
    """remove returns a new set without mutating the original"""
    original = HashSet.make("a", "b", "c")
    updated = original.remove("b")
    assert len(original) == 3
    assert original.has("b")
    assert len(updated) == 2
    assert not updated.has("b")
    assert updated.has("a")
    assert updated.has("c")


def test_remove_returns_the_same_set_when_the_value_is_absent() -> None:
    """remove returns the same set when the value is absent"""
    original = HashSet.make("a", "b")
    same = original.remove("c")
    assert len(same) == 2
    assert same is original


def test_has_checks_membership_for_present_and_absent_values() -> None:
    """has checks membership for present and absent values"""
    s = HashSet.make("a", "b", "c")
    assert [s.has(v) for v in "abcd"] == [True, True, True, False]


def test_size_and_is_empty_reflect_set_cardinality() -> None:
    """size and isEmpty reflect set cardinality"""
    empty = HashSet[str].empty()
    assert (len(empty), empty.is_empty()) == (0, True)
    single = HashSet.make("a")
    assert (len(single), single.is_empty()) == (1, False)
    multiple = HashSet.make("a", "b", "c")
    assert (len(multiple), multiple.is_empty()) == (3, False)


def test_union_keeps_values_from_both_sets() -> None:
    """union keeps values from both sets"""
    result = HashSet.make("a", "b").union(HashSet.make("b", "c"))
    assert len(result) == 3
    assert all(result.has(v) for v in "abc")


def test_intersection_keeps_only_values_present_in_both_sets() -> None:
    """intersection keeps only values present in both sets"""
    result = HashSet.make("a", "b", "c").intersection(HashSet.make("b", "c", "d"))
    assert len(result) == 2
    assert [result.has(v) for v in "abcd"] == [False, True, True, False]


def test_difference_removes_values_found_in_the_second_set() -> None:
    """difference removes values found in the second set"""
    result = HashSet.make("a", "b", "c").difference(HashSet.make("b", "d"))
    assert len(result) == 2
    assert [result.has(v) for v in "abc"] == [True, False, True]


def test_is_subset_checks_whether_all_values_exist_in_another_set() -> None:
    """isSubset checks whether all values exist in another set"""
    small, large = HashSet.make("a", "b"), HashSet.make("a", "b", "c", "d")
    other = HashSet.make("x", "y")
    assert small.is_subset(large)
    assert not large.is_subset(small)
    assert not small.is_subset(other)
    assert small.is_subset(small)


def test_map_transforms_every_value() -> None:
    """map transforms every value"""
    doubled = HashSet.make(1, 2, 3).map(lambda n: n * 2)
    assert len(doubled) == 3
    assert all(doubled.has(v) for v in (2, 4, 6))


def test_map_removes_duplicate_transformed_values() -> None:
    """map removes duplicate transformed values"""
    lengths = HashSet.make("apple", "banana", "cherry").map(len)
    assert len(lengths) == 2
    assert lengths.has(5)
    assert lengths.has(6)


def test_filter_keeps_values_that_satisfy_the_predicate() -> None:
    """filter keeps values that satisfy the predicate"""
    evens = HashSet.make(1, 2, 3, 4, 5, 6).filter(lambda n: n % 2 == 0)
    assert len(evens) == 3
    assert all(evens.has(v) for v in (2, 4, 6))
    assert not evens.has(1)


def test_some_returns_true_when_any_value_satisfies_the_predicate() -> None:
    """some returns true when any value satisfies the predicate"""
    numbers = HashSet.make(1, 2, 3, 4, 5)
    assert numbers.some(lambda n: n > 3)
    assert not numbers.some(lambda n: n > 10)
    assert not HashSet[int].empty().some(lambda n: n > 0)


def test_every_returns_true_when_all_values_satisfy_the_predicate() -> None:
    """every returns true when all values satisfy the predicate"""
    evens = HashSet.make(2, 4, 6, 8)
    assert evens.every(lambda n: n % 2 == 0)
    assert not evens.every(lambda n: n > 5)
    assert HashSet[int].empty().every(lambda n: n > 0)


def test_reduce_folds_every_value_into_an_accumulator() -> None:
    """reduce folds every value into an accumulator"""
    assert HashSet.make(1, 2, 3, 4, 5).reduce(0, lambda acc, n: acc + n) == 15
    assert HashSet[int].empty().reduce(0, lambda acc, n: acc + n) == 0


def test_symbol_iterator_iterates_over_the_set_values() -> None:
    """Symbol.iterator iterates over the set values"""
    assert sorted(HashSet.make("a", "b", "c")) == ["a", "b", "c"]


def test_supports_for_of_iteration() -> None:
    """supports for...of iteration"""
    collected = [value for value in HashSet.make("x", "y", "z")]
    assert sorted(collected) == ["x", "y", "z"]


def test_structural_equality_ignores_insertion_order() -> None:
    """structural equality ignores insertion order"""
    set1 = HashSet.make("a", "b", "c")
    assert set1 == HashSet.make("c", "b", "a")
    assert set1 != HashSet.make("a", "b", "d")


def test_hash_is_consistent_for_sets_with_the_same_values() -> None:
    """hash is consistent for sets with the same values"""
    assert hash(HashSet.make("a", "b", "c")) == hash(HashSet.make("c", "b", "a"))


class Person:
    def __init__(self, id: str, name: str) -> None:
        self.id, self.name = id, name

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Person) and self.id == other.id

    def __hash__(self) -> int:
        return hash(self.id)


def test_uses_equal_and_hash_implementations_for_membership_and_uniqueness() -> None:
    """uses Equal and Hash implementations for membership and uniqueness"""
    alice1, alice2, bob = Person("1", "Alice"), Person("1", "Alice"), Person("2", "Bob")
    people = HashSet.make(alice1, bob)
    assert people.has(alice2)
    assert len(people) == 2
    assert len(people.add(alice2)) == 2


def test_is_hash_set_identifies_hash_set_values() -> None:
    """isHashSet identifies HashSet values"""
    assert isinstance(HashSet.make("a", "b", "c"), HashSet)
    for value in (["a", "b", "c"], {"a": 1, "b": 2}, None):
        assert not isinstance(value, HashSet)
