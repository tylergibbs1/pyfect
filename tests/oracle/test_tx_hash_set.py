"""Ports of Effect's ``TxHashSet.test.ts``, every title.

Each test's docstring is the Effect test title. Module functions are methods
(``TxHashSet.add(s, "c")`` is ``s.add("c")``); a ``HashSet`` is a
``pyfect.hash_set.HashSet``; ``isTxHashSet`` is ``isinstance``; a custom ``Equal`` value
is a class with ``__eq__`` and ``__hash__``.
"""

import pyfect as fx
from pyfect import testing
from pyfect.hash_set import HashSet

from ._tx import in_tx


class TestValue:
    __test__ = False

    def __init__(self, value: str) -> None:
        self.value = value

    def __eq__(self, other: object) -> bool:
        return isinstance(other, TestValue) and self.value == other.value

    def __hash__(self) -> int:
        return hash(self.value)


# --- constructors -------------------------------------------------------------


@testing.effect
def test_from_iterable_preserves_a_one_shot_iterable_across_transaction_retries():
    """fromIterable preserves a one-shot iterable across transaction retries"""
    gate = fx.TxRef(False)
    operation = fx.TxHashSet.from_iterable(value for value in ["a", "b", "a"])

    @fx.fn
    def body():
        tx_set = yield from operation
        if not (yield from gate.get()):
            return (yield from fx.tx_retry)
        return tx_set

    fiber = yield from fx.tx(body()).fork(start_immediately=True)
    yield from gate.set(True)
    tx_set = yield from fiber.join()
    assert sorted((yield from tx_set.to_hash_set())) == ["a", "b"]


@testing.effect
@in_tx
def test_empty_creates_an_empty_tx_hash_set():
    """empty creates an empty TxHashSet"""
    tx_set = yield from fx.TxHashSet[str].empty()
    assert (yield from tx_set.size()) == 0
    assert (yield from tx_set.is_empty()) is True


@testing.effect
@in_tx
def test_make_creates_tx_hash_set_from_values():
    """make creates TxHashSet from values"""
    tx_set = yield from fx.TxHashSet.make("a", "b", "c")
    assert (yield from tx_set.size()) == 3
    assert (yield from tx_set.has("a")) is True
    assert (yield from tx_set.has("b")) is True
    assert (yield from tx_set.has("c")) is True
    assert (yield from tx_set.has("d")) is False


@testing.effect
@in_tx
def test_make_removes_duplicates():
    """make removes duplicates"""
    tx_set = yield from fx.TxHashSet.make("a", "b", "a", "c", "b")
    assert (yield from tx_set.size()) == 3


@testing.effect
@in_tx
def test_from_iterable_creates_tx_hash_set_from_iterable():
    """fromIterable creates TxHashSet from iterable"""
    tx_set = yield from fx.TxHashSet.from_iterable(["x", "y", "z", "x", "y"])
    assert (yield from tx_set.size()) == 3
    assert (yield from tx_set.has("x")) is True
    assert (yield from tx_set.has("y")) is True
    assert (yield from tx_set.has("z")) is True


@testing.effect
def test_from_iterable_creates_independent_sets_on_each_execution():
    """fromIterable creates independent sets on each execution"""
    make = fx.TxHashSet.from_iterable(value for value in ["a"])
    first = yield from fx.tx(make)
    yield from fx.tx(first.clear())
    second = yield from fx.tx(make)

    assert (yield from fx.tx(second.size())) == 1
    assert (yield from fx.tx(second.has("a"))) is True
    assert (yield from fx.tx(first.size())) == 0


@testing.effect
@in_tx
def test_from_hash_set_creates_tx_hash_set_from_hash_set():
    """fromHashSet creates TxHashSet from HashSet"""
    tx_set = yield from fx.TxHashSet.from_hash_set(HashSet.make("foo", "bar", "baz"))
    assert (yield from tx_set.size()) == 3
    assert (yield from tx_set.has("foo")) is True
    assert (yield from tx_set.has("bar")) is True
    assert (yield from tx_set.has("baz")) is True


# --- type guards --------------------------------------------------------------


@testing.effect
@in_tx
def test_is_tx_hash_set_identifies_tx_hash_set_instances():
    """isTxHashSet identifies TxHashSet instances"""
    tx_set = yield from fx.TxHashSet.make(1, 2, 3)
    others: list[object] = [frozenset({1, 2, 3}), [1, 2, 3], None]
    assert isinstance(tx_set, fx.TxHashSet)
    assert not any(isinstance(other, fx.TxHashSet) for other in others)


# --- basic operations ---------------------------------------------------------


@testing.effect
@in_tx
def test_add_adds_values_to_tx_hash_set():
    """add adds values to TxHashSet"""
    tx_set = yield from fx.TxHashSet.make("a", "b")

    yield from tx_set.add("c")
    assert (yield from tx_set.size()) == 3
    assert (yield from tx_set.has("c")) is True

    yield from tx_set.add("a")
    assert (yield from tx_set.size()) == 3


@testing.effect
@in_tx
def test_remove_removes_values_from_tx_hash_set():
    """remove removes values from TxHashSet"""
    tx_set = yield from fx.TxHashSet.make("a", "b", "c")

    assert (yield from tx_set.remove("b")) is True
    assert (yield from tx_set.size()) == 2
    assert (yield from tx_set.has("b")) is False

    assert (yield from tx_set.remove("d")) is False
    assert (yield from tx_set.size()) == 2


@testing.effect
@in_tx
def test_has_checks_for_value_existence():
    """has checks for value existence"""
    tx_set = yield from fx.TxHashSet.make("apple", "banana", "cherry")
    assert (yield from tx_set.has("apple")) is True
    assert (yield from tx_set.has("grape")) is False


@testing.effect
@in_tx
def test_size_returns_correct_count():
    """size returns correct count"""
    empty = yield from fx.TxHashSet[str].empty()
    assert (yield from empty.size()) == 0

    small = yield from fx.TxHashSet.make("a", "b")
    assert (yield from small.size()) == 2

    from_iterable = yield from fx.TxHashSet.from_iterable(["x", "y", "z", "x", "y"])
    assert (yield from from_iterable.size()) == 3


@testing.effect
@in_tx
def test_is_empty_and_is_non_empty_check_the_set():
    """isEmpty and isNonEmpty check the set"""
    empty = yield from fx.TxHashSet[str].empty()
    assert (yield from empty.is_empty()) is True
    assert (yield from empty.is_non_empty()) is False

    non_empty = yield from fx.TxHashSet.make("a")
    assert (yield from non_empty.is_empty()) is False
    assert (yield from non_empty.is_non_empty()) is True


@testing.effect
@in_tx
def test_clear_removes_all_values():
    """clear removes all values"""
    tx_set = yield from fx.TxHashSet.make("a", "b", "c")
    assert (yield from tx_set.size()) == 3

    yield from tx_set.clear()
    assert (yield from tx_set.size()) == 0
    assert (yield from tx_set.is_empty()) is True


# --- set operations -----------------------------------------------------------


@testing.effect
@in_tx
def test_union_combines_two_sets():
    """union combines two sets"""
    first = yield from fx.TxHashSet.make("a", "b")
    second = yield from fx.TxHashSet.make("b", "c")
    combined = yield from first.union(second)

    assert sorted((yield from combined.to_hash_set())) == ["a", "b", "c"]
    assert (yield from combined.size()) == 3


@testing.effect
@in_tx
def test_intersection_finds_common_elements():
    """intersection finds common elements"""
    first = yield from fx.TxHashSet.make("a", "b", "c")
    second = yield from fx.TxHashSet.make("b", "c", "d")
    common = yield from first.intersection(second)

    assert sorted((yield from common.to_hash_set())) == ["b", "c"]
    assert (yield from common.size()) == 2


@testing.effect
@in_tx
def test_difference_finds_elements_only_in_first_set():
    """difference finds elements only in first set"""
    first = yield from fx.TxHashSet.make("a", "b", "c")
    second = yield from fx.TxHashSet.make("b", "d")
    diff = yield from first.difference(second)

    assert sorted((yield from diff.to_hash_set())) == ["a", "c"]
    assert (yield from diff.size()) == 2


@testing.effect
@in_tx
def test_is_subset_checks_subset_relationship():
    """isSubset checks subset relationship"""
    small = yield from fx.TxHashSet.make("a", "b")
    large = yield from fx.TxHashSet.make("a", "b", "c", "d")
    other = yield from fx.TxHashSet.make("x", "y")

    assert (yield from small.is_subset(large)) is True
    assert (yield from large.is_subset(small)) is False
    assert (yield from small.is_subset(other)) is False
    assert (yield from small.is_subset(small)) is True


# --- query operations ---------------------------------------------------------


@testing.effect
@in_tx
def test_some_tests_if_any_element_satisfies_predicate():
    """some tests if any element satisfies predicate"""
    numbers = yield from fx.TxHashSet.make(1, 2, 3, 4, 5)
    assert (yield from numbers.some(lambda n: n > 3)) is True
    assert (yield from numbers.some(lambda n: n > 10)) is False

    empty = yield from fx.TxHashSet[int].empty()
    assert (yield from empty.some(lambda n: n > 0)) is False


@testing.effect
@in_tx
def test_every_tests_if_all_elements_satisfy_predicate():
    """every tests if all elements satisfy predicate"""
    numbers = yield from fx.TxHashSet.make(2, 4, 6, 8)
    assert (yield from numbers.every(lambda n: n % 2 == 0)) is True
    assert (yield from numbers.every(lambda n: n > 5)) is False

    empty = yield from fx.TxHashSet[int].empty()
    assert (yield from empty.every(lambda n: n > 0)) is True


# --- functional operations ----------------------------------------------------


@testing.effect
@in_tx
def test_map_transforms_values():
    """map transforms values"""
    numbers = yield from fx.TxHashSet.make(1, 2, 3)
    doubled = yield from numbers.map(lambda n: n * 2)

    assert sorted((yield from doubled.to_hash_set())) == [2, 4, 6]
    assert (yield from doubled.size()) == 3


@testing.effect
@in_tx
def test_map_can_reduce_size_with_duplicate_results():
    """map can reduce size with duplicate results"""
    strings = yield from fx.TxHashSet.make("apple", "banana", "cherry")
    lengths = yield from strings.map(len)

    assert sorted((yield from lengths.to_hash_set())) == [5, 6]


@testing.effect
@in_tx
def test_filter_keeps_only_matching_values():
    """filter keeps only matching values"""
    numbers = yield from fx.TxHashSet.make(1, 2, 3, 4, 5, 6)
    evens = yield from numbers.filter(lambda n: n % 2 == 0)

    assert sorted((yield from evens.to_hash_set())) == [2, 4, 6]
    assert (yield from evens.size()) == 3


@testing.effect
@in_tx
def test_reduce_accumulates_values():
    """reduce accumulates values"""
    numbers = yield from fx.TxHashSet.make(1, 2, 3, 4, 5)
    assert (yield from numbers.reduce(0, lambda acc, n: acc + n)) == 15

    strings = yield from fx.TxHashSet.make("a", "b", "c")
    concatenated = yield from strings.reduce("", lambda acc, s: acc + s)
    assert sorted(concatenated) == ["a", "b", "c"]


# --- conversions --------------------------------------------------------------


@testing.effect
@in_tx
def test_to_hash_set_creates_immutable_snapshot():
    """toHashSet creates immutable snapshot"""
    tx_set = yield from fx.TxHashSet.make("x", "y", "z")
    snapshot = yield from tx_set.to_hash_set()

    assert len(snapshot) == 3
    assert "y" in snapshot

    yield from tx_set.add("w")
    assert len(snapshot) == 3
    assert (yield from tx_set.size()) == 4


# --- custom Equal objects -----------------------------------------------------


@testing.effect
@in_tx
def test_works_with_custom_equal_implementations():
    """works with custom Equal implementations"""
    tx_set = yield from fx.TxHashSet.make(
        TestValue("alice"), TestValue("bob"), TestValue("charlie")
    )

    assert (yield from tx_set.size()) == 3
    assert (yield from tx_set.has(TestValue("alice"))) is True
    assert (yield from tx_set.has(TestValue("dave"))) is False

    yield from tx_set.add(TestValue("alice"))
    assert (yield from tx_set.size()) == 3

    assert (yield from tx_set.remove(TestValue("bob"))) is True
    assert (yield from tx_set.size()) == 2
    assert (yield from tx_set.has(TestValue("bob"))) is False


# --- transactional behavior ---------------------------------------------------


@testing.effect
@in_tx
def test_operations_are_atomic_within_transactions():
    """operations are atomic within transactions"""
    tx_set = yield from fx.TxHashSet.make("a", "b", "c")

    if (yield from tx_set.has("c")):
        yield from tx_set.remove("c")
        yield from tx_set.add("orange")
    yield from tx_set.add("grape")

    assert (yield from tx_set.size()) == 4
    assert (yield from tx_set.has("c")) is False
    assert (yield from tx_set.has("orange")) is True
    assert (yield from tx_set.has("grape")) is True


@testing.effect
@in_tx
def test_multiple_set_operations_work_together():
    """multiple set operations work together"""
    first = yield from fx.TxHashSet.make("a", "b", "c")
    second = yield from fx.TxHashSet.make("c", "d", "e")

    yield from first.add("f")
    yield from second.remove("d")

    common = yield from first.intersection(second)
    if (yield from common.size()) > 0:
        yield from first.add("shared")
        yield from second.add("shared")

    assert (yield from first.has("f")) is True
    assert (yield from first.has("shared")) is True
    assert (yield from second.has("d")) is False
    assert (yield from second.has("shared")) is True


# --- stress testing -----------------------------------------------------------


@testing.effect
@in_tx
def test_handles_large_number_of_operations():
    """handles large number of operations"""
    tx_set = yield from fx.TxHashSet[int].empty()

    for i in range(1000):
        yield from tx_set.add(i)

    assert (yield from tx_set.size()) == 1000
    assert (yield from tx_set.has(500)) is True
    assert (yield from tx_set.has(999)) is True
    assert (yield from tx_set.has(1000)) is False

    for i in range(500):
        yield from tx_set.remove(i)

    assert (yield from tx_set.size()) == 500
    assert (yield from tx_set.has(250)) is False
    assert (yield from tx_set.has(750)) is True


@testing.effect
@in_tx
def test_functional_operations_work_with_large_sets():
    """functional operations work with large sets"""
    numbers = yield from fx.TxHashSet.from_iterable(range(100))

    evens = yield from numbers.filter(lambda n: n % 2 == 0)
    assert (yield from evens.size()) == 50

    doubled = yield from evens.map(lambda n: n * 2)
    assert (yield from doubled.size()) == 50

    assert (yield from evens.reduce(0, lambda acc, n: acc + n)) == 2450


# --- edge cases ---------------------------------------------------------------


@testing.effect
@in_tx
def test_handles_empty_set_operations_correctly():
    """handles empty set operations correctly"""
    empty1 = yield from fx.TxHashSet[str].empty()
    empty2 = yield from fx.TxHashSet[str].empty()
    non_empty = yield from fx.TxHashSet.make("a", "b")

    assert (yield from (yield from empty1.union(empty2)).size()) == 0
    assert (yield from (yield from empty1.union(non_empty)).size()) == 2
    assert (yield from (yield from empty1.intersection(non_empty)).size()) == 0
    assert (yield from empty1.is_subset(non_empty)) is True
    assert (yield from non_empty.is_subset(empty1)) is False


@testing.effect
@in_tx
def test_handles_single_element_sets():
    """handles single element sets"""
    single = yield from fx.TxHashSet.make("only")

    assert (yield from single.size()) == 1
    assert (yield from single.has("only")) is True
    assert (yield from single.is_empty()) is False

    yield from single.clear()
    assert (yield from single.size()) == 0
    assert (yield from single.is_empty()) is True
