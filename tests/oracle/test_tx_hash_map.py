"""Ports of Effect's ``TxHashMap.test.ts``, every title.

Each test's docstring is the Effect test title. Module functions are methods
(``TxHashMap.get(m, "a")`` is ``m.get("a")``), so the data-first and
data-last halves of a test are the same call; ``union`` takes and
``snapshot`` gives a ``pyfect.hash_map.HashMap``, iterating in Effect's hash
order (so ``findFirst`` finds the entry Effect's does); ``get`` gives an
``Option`` (``Some`` or ``None``), ``find_first`` a pair or ``None``;
``isTxHashMap`` is ``isinstance``; ``Hash.string`` is ``hash``; Effect's
records are dataclasses.
"""

from dataclasses import dataclass, replace

import pyfect as fx
from pyfect import testing
from pyfect.hash_map import HashMap
from pyfect.option import Some
from pyfect.result import Err, Ok

from ._tx import in_tx

# --- constructors -------------------------------------------------------------


@testing.effect
def test_from_iterable_preserves_a_one_shot_iterable_across_transaction_retries():
    """fromIterable preserves a one-shot iterable across transaction retries"""
    gate = fx.TxRef(False)
    operation = fx.TxHashMap.from_iterable(entry for entry in [("a", 1), ("b", 2)])

    @fx.fn
    def body():
        tx_map = yield from operation
        if not (yield from gate.get()):
            return (yield from fx.tx_retry)
        return tx_map

    fiber = yield from fx.tx(body()).fork(start_immediately=True)
    yield from gate.set(True)
    tx_map = yield from fiber.join()
    assert sorted((yield from tx_map.to_entries())) == [("a", 1), ("b", 2)]


@testing.effect
@in_tx
def test_empty():
    """empty"""
    tx_map = yield from fx.TxHashMap[str, int].empty()
    assert (yield from tx_map.is_empty()) is True
    assert (yield from tx_map.size()) == 0


@testing.effect
@in_tx
def test_make():
    """make"""
    tx_map = yield from fx.TxHashMap.make(("a", 1), ("b", 2), ("c", 3))
    assert (yield from tx_map.size()) == 3
    assert (yield from tx_map.get("a")) == Some(1)
    assert (yield from tx_map.get("b")) == Some(2)
    assert (yield from tx_map.get("c")) == Some(3)


@testing.effect
def test_from_iterable_creates_independent_maps_on_each_execution():
    """fromIterable creates independent maps on each execution"""
    make = fx.TxHashMap.from_iterable(entry for entry in [("a", 1)])
    first = yield from fx.tx(make)
    yield from fx.tx(first.clear())
    second = yield from fx.tx(make)

    assert (yield from fx.tx(second.size())) == 1
    assert (yield from fx.tx(second.get("a"))) == Some(1)
    assert (yield from fx.tx(first.size())) == 0


@testing.effect
@in_tx
def test_from_iterable():
    """fromIterable"""
    tx_map = yield from fx.TxHashMap.from_iterable([("a", 1), ("b", 2), ("c", 3)])
    assert (yield from tx_map.size()) == 3
    assert (yield from tx_map.get("a")) == Some(1)
    assert (yield from tx_map.get("b")) == Some(2)
    assert (yield from tx_map.get("c")) == Some(3)


# --- basic operations ---------------------------------------------------------


@testing.effect
@in_tx
def test_get_existing_key():
    """get - existing key"""
    tx_map = yield from fx.TxHashMap.make(("a", 1), ("b", 2))
    assert (yield from tx_map.get("a")) == Some(1)
    assert (yield from tx_map.get("b")) == Some(2)


@testing.effect
@in_tx
def test_get_non_existing_key():
    """get - non-existing key"""
    tx_map = yield from fx.TxHashMap.make(("a", 1), ("b", 2))
    assert (yield from tx_map.get("c")) is None


@testing.effect
@in_tx
def test_has_existing_key():
    """has - existing key"""
    tx_map = yield from fx.TxHashMap.make(("a", 1), ("b", 2))
    assert (yield from tx_map.has("a")) is True
    assert (yield from tx_map.has("b")) is True


@testing.effect
@in_tx
def test_has_non_existing_key():
    """has - non-existing key"""
    tx_map = yield from fx.TxHashMap.make(("a", 1), ("b", 2))
    assert (yield from tx_map.has("c")) is False


@testing.effect
@in_tx
def test_set_new_key():
    """set - new key"""
    tx_map = yield from fx.TxHashMap.make(("a", 1), ("b", 2))
    yield from tx_map.set("c", 3)
    assert (yield from tx_map.size()) == 3
    assert (yield from tx_map.get("c")) == Some(3)


@testing.effect
@in_tx
def test_set_existing_key():
    """set - existing key"""
    tx_map = yield from fx.TxHashMap.make(("a", 1), ("b", 2))
    yield from tx_map.set("a", 10)
    assert (yield from tx_map.size()) == 2
    assert (yield from tx_map.get("a")) == Some(10)


@testing.effect
@in_tx
def test_remove_existing_key():
    """remove - existing key"""
    tx_map = yield from fx.TxHashMap.make(("a", 1), ("b", 2), ("c", 3))
    assert (yield from tx_map.remove("b")) is True
    assert (yield from tx_map.size()) == 2
    assert (yield from tx_map.has("b")) is False


@testing.effect
@in_tx
def test_remove_non_existing_key():
    """remove - non-existing key"""
    tx_map = yield from fx.TxHashMap.make(("a", 1), ("b", 2))
    assert (yield from tx_map.remove("c")) is False
    assert (yield from tx_map.size()) == 2


@testing.effect
@in_tx
def test_clear():
    """clear"""
    tx_map = yield from fx.TxHashMap.make(("a", 1), ("b", 2), ("c", 3))
    yield from tx_map.clear()
    assert (yield from tx_map.size()) == 0
    assert (yield from tx_map.is_empty()) is True


# --- query operations ---------------------------------------------------------


@testing.effect
@in_tx
def test_size():
    """size"""
    empty = yield from fx.TxHashMap[str, int].empty()
    small = yield from fx.TxHashMap.make(("a", 1))
    large = yield from fx.TxHashMap.make(("a", 1), ("b", 2), ("c", 3), ("d", 4))
    assert (yield from empty.size()) == 0
    assert (yield from small.size()) == 1
    assert (yield from large.size()) == 4


@testing.effect
@in_tx
def test_is_empty():
    """isEmpty"""
    empty = yield from fx.TxHashMap[str, int].empty()
    non_empty = yield from fx.TxHashMap.make(("a", 1))
    assert (yield from empty.is_empty()) is True
    assert (yield from non_empty.is_empty()) is False


@testing.effect
@in_tx
def test_is_non_empty():
    """isNonEmpty"""
    empty = yield from fx.TxHashMap[str, int].empty()
    non_empty = yield from fx.TxHashMap.make(("a", 1))
    assert (yield from empty.is_non_empty()) is False
    assert (yield from non_empty.is_non_empty()) is True


# --- advanced operations ------------------------------------------------------


@testing.effect
@in_tx
def test_modify_existing_key():
    """modify - existing key"""
    tx_map = yield from fx.TxHashMap.make(("counter", 5))
    assert (yield from tx_map.modify("counter", lambda n: n * 2)) == Some(5)
    assert (yield from tx_map.get("counter")) == Some(10)


@testing.effect
@in_tx
def test_modify_non_existing_key():
    """modify - non-existing key"""
    tx_map = yield from fx.TxHashMap[str, int].empty()
    assert (yield from tx_map.modify("counter", lambda n: n * 2)) is None
    assert (yield from tx_map.size()) == 0


@testing.effect
@in_tx
def test_modify_at_insert_new_value():
    """modifyAt - insert new value"""
    tx_map = yield from fx.TxHashMap.make(("a", 1))
    yield from tx_map.modify_at("b", lambda _: Some(2))
    assert (yield from tx_map.size()) == 2
    assert (yield from tx_map.get("b")) == Some(2)


@testing.effect
@in_tx
def test_modify_at_remove_existing_value():
    """modifyAt - remove existing value"""
    tx_map = yield from fx.TxHashMap.make(("a", 1), ("b", 2))
    yield from tx_map.modify_at("a", lambda _: None)
    assert (yield from tx_map.size()) == 1
    assert (yield from tx_map.has("a")) is False


@testing.effect
@in_tx
def test_keys():
    """keys"""
    tx_map = yield from fx.TxHashMap.make(("a", 1), ("b", 2), ("c", 3))
    assert sorted((yield from tx_map.keys())) == ["a", "b", "c"]


@testing.effect
@in_tx
def test_values():
    """values"""
    tx_map = yield from fx.TxHashMap.make(("a", 1), ("b", 2), ("c", 3))
    assert sorted((yield from tx_map.values())) == [1, 2, 3]


@testing.effect
@in_tx
def test_entries():
    """entries"""
    tx_map = yield from fx.TxHashMap.make(("a", 1), ("b", 2))
    assert sorted((yield from tx_map.entries())) == [("a", 1), ("b", 2)]


@testing.effect
@in_tx
def test_snapshot():
    """snapshot"""
    tx_map = yield from fx.TxHashMap.make(("a", 1), ("b", 2))
    snapshot = yield from tx_map.snapshot()

    yield from tx_map.set("c", 3)

    assert len(snapshot) == 2
    assert snapshot.get("a") == Some(1)
    assert snapshot.get("b") == Some(2)
    assert snapshot.get("c") is None
    assert (yield from tx_map.size()) == 3


# --- bulk operations ----------------------------------------------------------


@testing.effect
@in_tx
def test_union():
    """union"""
    tx_map = yield from fx.TxHashMap.make(("a", 1), ("b", 2))
    other = HashMap.make(("b", 20), ("c", 3))  # "b" should be overwritten
    yield from tx_map.union(other)
    assert (yield from tx_map.size()) == 3
    assert (yield from tx_map.get("a")) == Some(1)
    assert (yield from tx_map.get("b")) == Some(20)
    assert (yield from tx_map.get("c")) == Some(3)


@testing.effect
def test_remove_many_preserves_a_one_shot_iterable_across_transaction_retries():
    """removeMany preserves a one-shot iterable across transaction retries"""
    tx_map = yield from fx.TxHashMap.make(("a", 1), ("b", 2), ("c", 3))
    gate = fx.TxRef(False)
    operation = tx_map.remove_many(key for key in ["a", "b"])

    @fx.fn
    def body():
        yield from operation
        if not (yield from gate.get()):
            return (yield from fx.tx_retry)

    fiber = yield from fx.tx(body()).fork(start_immediately=True)
    yield from gate.set(True)
    yield from fiber.join()
    assert (yield from tx_map.to_entries()) == [("c", 3)]


@testing.effect
@in_tx
def test_remove_many():
    """removeMany"""
    tx_map = yield from fx.TxHashMap.make(("a", 1), ("b", 2), ("c", 3), ("d", 4))
    yield from tx_map.remove_many(["b", "d"])
    assert (yield from tx_map.size()) == 2
    assert (yield from tx_map.has("a")) is True
    assert (yield from tx_map.has("b")) is False
    assert (yield from tx_map.has("c")) is True
    assert (yield from tx_map.has("d")) is False


@testing.effect
def test_set_many_preserves_a_one_shot_iterable_across_transaction_retries():
    """setMany preserves a one-shot iterable across transaction retries"""
    tx_map = yield from fx.TxHashMap.make(("a", 0), ("c", 3))
    gate = fx.TxRef(False)
    operation = tx_map.set_many(entry for entry in [("a", 1), ("b", 2)])

    @fx.fn
    def body():
        yield from operation
        if not (yield from gate.get()):
            return (yield from fx.tx_retry)

    fiber = yield from fx.tx(body()).fork(start_immediately=True)
    yield from gate.set(True)
    yield from fiber.join()
    assert sorted((yield from tx_map.to_entries())) == [("a", 1), ("b", 2), ("c", 3)]


@testing.effect
@in_tx
def test_set_many():
    """setMany"""
    tx_map = yield from fx.TxHashMap.make(("a", 1), ("b", 2))
    yield from tx_map.set_many([("c", 3), ("d", 4), ("a", 10)])
    assert (yield from tx_map.size()) == 4
    assert (yield from tx_map.get("a")) == Some(10)
    assert (yield from tx_map.get("b")) == Some(2)
    assert (yield from tx_map.get("c")) == Some(3)
    assert (yield from tx_map.get("d")) == Some(4)


# --- transactional semantics --------------------------------------------------


@testing.effect
@in_tx
def test_single_operations_are_automatically_transactional():
    """single operations are automatically transactional"""
    tx_map = yield from fx.TxHashMap.make(("counter", 0))
    yield from tx_map.set("counter", 1)
    yield from tx_map.modify("counter", lambda n: n + 1)
    assert (yield from tx_map.get("counter")) == Some(2)


@testing.effect
@in_tx
def test_multi_step_operations_commit_together():
    """multi-step operations commit together"""
    tx_map = yield from fx.TxHashMap.make(("a", 1), ("b", 2))
    match (yield from tx_map.get("a")):
        case Some(current):
            yield from tx_map.set("a", current * 10)
            yield from tx_map.remove("b")
            yield from tx_map.set("c", 3)
        case None:
            pass
    assert (yield from tx_map.get("a")) == Some(10)
    assert (yield from tx_map.has("b")) is False
    assert (yield from tx_map.get("c")) == Some(3)
    assert (yield from tx_map.size()) == 2


# --- pipe syntax --------------------------------------------------------------


@testing.effect
@in_tx
def test_supports_data_last_operations():
    """supports data-last operations"""
    tx_map = yield from fx.TxHashMap[str, int].empty()
    yield from tx_map.set("a", 1).flat_map(lambda _: fx.void)
    yield from tx_map.set("b", 2).flat_map(lambda _: fx.void)
    assert (yield from tx_map.get("a")) == Some(1)
    assert (yield from tx_map.size()) == 2


# --- Phase 1: essential functions ---------------------------------------------


@dataclass(frozen=True)
class User:
    name: str
    role: str


@testing.effect
@in_tx
def test_is_tx_hash_map_should_correctly_identify_tx_hash_map_instances():
    """isTxHashMap should correctly identify TxHashMap instances"""
    tx_map = yield from fx.TxHashMap.make(("key", "value"))
    assert isinstance(tx_map, fx.TxHashMap)
    others: list[object] = [{}, None, "string", 42, [], dict[str, int]()]
    assert not any(isinstance(other, fx.TxHashMap) for other in others)


@testing.effect
@in_tx
def test_get_hash_should_lookup_values_using_custom_hash():
    """getHash should lookup values using custom hash"""
    tx_map = yield from fx.TxHashMap.make(
        ("user123", User("Alice", "admin")), ("user456", User("Bob", "user"))
    )
    user_id = "user123"
    key_hash = hash(user_id)

    assert (yield from tx_map.get_hash(user_id, key_hash)) == Some(User("Alice", "admin"))
    assert (yield from tx_map.get_hash("user999", hash("user999"))) is None
    assert (yield from tx_map.get_hash(user_id, hash("different"))) is None


@testing.effect
@in_tx
def test_has_hash_should_check_existence_using_custom_hash():
    """hasHash should check existence using custom hash"""
    tx_map = yield from fx.TxHashMap.make(("admin", (True, True)), ("user", (True, False)))
    role = "admin"
    key_hash = hash(role)

    assert (yield from tx_map.has_hash(role, key_hash)) is True
    assert (yield from tx_map.has_hash("guest", hash("guest"))) is False

    empty = yield from fx.TxHashMap[str, tuple[bool, bool]].empty()
    assert (yield from empty.has_hash("admin", key_hash)) is False


@testing.effect
@in_tx
def test_get_hash_and_has_hash_should_work_together():
    """getHash and hasHash should work together"""
    tx_map = yield from fx.TxHashMap.make(
        ("session_abc", ("user1", True)), ("session_def", ("user2", False))
    )
    session_id = "session_abc"
    key_hash = hash(session_id)

    assert (yield from tx_map.has_hash(session_id, key_hash)) is True
    assert (yield from tx_map.get_hash(session_id, key_hash)) == Some(("user1", True))

    invalid = "session_xyz"
    assert (yield from tx_map.has_hash(invalid, hash(invalid))) is False
    assert (yield from tx_map.get_hash(invalid, hash(invalid))) is None


@testing.effect
@in_tx
def test_hash_functions_should_work_correctly():
    """hash functions should work correctly"""
    tx_map = yield from fx.TxHashMap.make(("key1", "value1"))
    key_hash = hash("key2")

    yield from tx_map.set("key2", "value2")

    assert (yield from tx_map.has_hash("key2", key_hash)) is True
    assert (yield from tx_map.get_hash("key2", key_hash)) == Some("value2")
    assert (yield from tx_map.has_hash("key2", key_hash)) is True


# --- Phase 2: functional programming operations -------------------------------


@dataclass(frozen=True)
class Person:
    name: str
    age: int
    key: str = ""


@dataclass(frozen=True)
class Item:
    price: float
    category: str


@testing.effect
@in_tx
def test_map_should_transform_values_while_preserving_keys():
    """map should transform values while preserving keys"""
    tx_map = yield from fx.TxHashMap.make(
        ("user1", Person("Alice", 25)),
        ("user2", Person("Bob", 30)),
        ("user3", Person("Charlie", 35)),
    )

    names = yield from tx_map.map(lambda user, _: user.name)
    assert (yield from names.get("user1")) == Some("Alice")
    assert (yield from names.get("user2")) == Some("Bob")
    assert (yield from names.get("user3")) == Some("Charlie")

    ages = yield from tx_map.map(lambda user, key: replace(user, age=user.age + 1, key=key))
    assert (yield from ages.get("user1")) == Some(Person("Alice", 26, "user1"))


@testing.effect
@in_tx
def test_filter_should_keep_only_matching_entries():
    """filter should keep only matching entries"""
    tx_map = yield from fx.TxHashMap.make(
        ("apple", Item(1.50, "fruit")),
        ("carrot", Item(0.80, "vegetable")),
        ("banana", Item(2.00, "fruit")),
        ("lettuce", Item(1.20, "vegetable")),
    )

    fruit = yield from tx_map.filter(lambda item, _: item.category == "fruit")
    assert (yield from fruit.size()) == 2
    assert (yield from fruit.has("apple")) is True
    assert (yield from fruit.has("banana")) is True
    assert (yield from fruit.has("carrot")) is False

    expensive = yield from tx_map.filter(lambda item, _: item.price > 1.50)
    assert (yield from expensive.size()) == 1


@testing.effect
@in_tx
def test_reduce_should_fold_over_all_entries():
    """reduce should fold over all entries"""
    tx_map = yield from fx.TxHashMap.make(("item1", 10), ("item2", 20), ("item3", 30))

    assert (yield from tx_map.reduce(0, lambda acc, value, _: acc + value)) == 60

    def count_keys(acc: tuple[int, list[str]], _: int, key: str) -> tuple[int, list[str]]:
        return acc[0] + 1, [*acc[1], key]

    count, keys = yield from tx_map.reduce((0, []), count_keys)
    assert count == 3
    assert sorted(keys) == ["item1", "item2", "item3"]

    empty = yield from fx.TxHashMap[str, int].empty()
    assert (yield from empty.reduce(0, lambda acc, value, _: acc + value)) == 0


def _parse_int(text: str) -> Ok[int] | Err[None]:
    try:
        return Ok(int(text))
    except ValueError:
        return Err(None)


@testing.effect
@in_tx
def test_filter_map_should_filter_and_transform_in_one_operation():
    """filterMap should filter and transform in one operation"""
    tx_map = yield from fx.TxHashMap.make(
        ("valid1", "10"),
        ("invalid", "not-a-number"),
        ("valid2", "20"),
        ("empty", ""),
        ("valid3", "30"),
    )

    numbers = yield from tx_map.filter_map(lambda value, _: _parse_int(value))
    assert (yield from numbers.size()) == 3
    assert (yield from numbers.get("valid1")) == Some(10)
    assert (yield from numbers.get("valid2")) == Some(20)
    assert (yield from numbers.get("valid3")) == Some(30)
    assert (yield from numbers.get("invalid")) is None

    users = yield from fx.TxHashMap.make(
        ("user1", {"name": "Alice", "email": "alice@example.com"}),
        ("user2", {"name": "Bob"}),
        ("user3", {"name": "Charlie", "email": "charlie@example.com"}),
    )
    emails = yield from users.filter_map(
        lambda user, key: Ok(f"{key}:{user['email']}") if "email" in user else Err(None)
    )
    assert (yield from emails.size()) == 2
    assert (yield from emails.get("user1")) == Some("user1:alice@example.com")
    assert (yield from emails.get("user2")) is None
    assert (yield from emails.get("user3")) == Some("user3:charlie@example.com")


@testing.effect
@in_tx
def test_has_by_should_check_if_any_entry_matches_predicate():
    """hasBy should check if any entry matches predicate"""
    tx_map = yield from fx.TxHashMap.make(
        ("admin", ("admin", True)), ("user1", ("user", True)), ("user2", ("user", False))
    )

    assert (yield from tx_map.has_by(lambda user, _: user[0] == "admin")) is True
    assert (yield from tx_map.has_by(lambda user, _: user[0] == "guest")) is False
    assert (yield from tx_map.has_by(lambda user, _: not user[1])) is True

    empty = yield from fx.TxHashMap[str, str].empty()
    assert (yield from empty.has_by(lambda _value, _key: True)) is False


@testing.effect
@in_tx
def test_find_first_should_return_first_matching_entry():
    """findFirst should return first matching entry"""
    tx_map = yield from fx.TxHashMap.make(
        ("session1", ("user1", "09:00")),
        ("session2", ("user2", "10:00")),
        ("session3", ("user1", "11:00")),
    )

    found = yield from tx_map.find_first(lambda session, _: session[0] == "user1")
    assert found == ("session3", ("user1", "11:00"))

    other = yield from tx_map.find_first(lambda session, _: session[0] not in ("user1", "user2"))
    assert other is None

    empty = yield from fx.TxHashMap[str, str].empty()
    assert (yield from empty.find_first(lambda _value, _key: True)) is None


@testing.effect
@in_tx
def test_some_should_check_if_any_entry_matches_predicate():
    """some should check if any entry matches predicate"""
    tx_map = yield from fx.TxHashMap.make(
        ("order1", ("pending", 100)), ("order2", ("completed", 250)), ("order3", ("pending", 50))
    )

    assert (yield from tx_map.some(lambda order, _: order[0] == "completed")) is True
    assert (yield from tx_map.some(lambda order, _: order[0] == "cancelled")) is False
    assert (yield from tx_map.some(lambda order, _: order[1] > 200)) is True
    assert (yield from tx_map.some(lambda order, _: order[1] > 1000)) is False

    empty = yield from fx.TxHashMap[str, str].empty()
    assert (yield from empty.some(lambda _value, _key: True)) is False


@testing.effect
@in_tx
def test_every_should_check_if_all_entries_match_predicate():
    """every should check if all entries match predicate"""
    tx_map = yield from fx.TxHashMap.make(
        ("task1", (True, "high")), ("task2", (True, "medium")), ("task3", (True, "low"))
    )

    assert (yield from tx_map.every(lambda task, _: task[0])) is True
    assert (yield from tx_map.every(lambda task, _: task[1] == "high")) is False

    yield from tx_map.set("task4", (False, "high"))

    assert (yield from tx_map.every(lambda task, _: task[0])) is False
    assert (yield from tx_map.every(lambda task, _: bool(task[1]))) is True

    empty = yield from fx.TxHashMap[str, bool].empty()
    assert (yield from empty.every(lambda _value, _key: False)) is True


@dataclass(frozen=True)
class Priced:
    price: float
    discount: float
    discounted_price: float = 0.0


@testing.effect
@in_tx
def test_functional_operations_should_work_correctly():
    """functional operations should work correctly"""
    tx_map = yield from fx.TxHashMap.make(
        ("item1", Priced(10, 0)), ("item2", Priced(20, 0)), ("item3", Priced(30, 0))
    )

    discounted = yield from tx_map.map(
        lambda item, _: replace(item, discount=0.1, discounted_price=item.price * 0.9)
    )
    expensive = yield from discounted.filter(lambda item, _: item.price > 15)
    savings = yield from expensive.reduce(
        0.0, lambda acc, item, _: acc + (item.price - item.discounted_price)
    )

    assert (yield from expensive.size()) == 2
    assert savings == 5
    assert (yield from expensive.every(lambda item, _: item.discount > 0)) is True


# --- Phase 3: specialized operations ------------------------------------------


@testing.effect
@in_tx
def test_for_each_should_execute_side_effects_for_each_entry():
    """forEach should execute side effects for each entry"""
    tx_map = yield from fx.TxHashMap.make(
        ("user1", ("Alice", "active")),
        ("user2", ("Bob", "inactive")),
        ("user3", ("Charlie", "active")),
    )

    processed: list[tuple[str, str, str]] = []
    yield from tx_map.for_each(
        lambda data, user_id: fx.sync(lambda: processed.append((user_id, *data)))
    )
    assert len(processed) == 3
    assert len([p for p in processed if p[2] == "active"]) == 2

    active: list[str] = []
    yield from tx_map.for_each(
        lambda data, user_id: (
            fx.sync(lambda: active.append(user_id)) if data[1] == "active" else fx.void
        )
    )
    assert sorted(active) == ["user1", "user3"]


@testing.effect
@in_tx
def test_flat_map_should_transform_and_flatten_tx_hash_maps():
    """flatMap should transform and flatten TxHashMaps"""
    departments = yield from fx.TxHashMap.make(("eng", ("alice", "bob")), ("sales", ("charlie",)))

    @fx.fn
    def employees_of(members: tuple[str, ...], department: str):
        employees = yield from fx.TxHashMap[str, tuple[str, str]].empty()
        for i, member in enumerate(members):
            yield from employees.set(member, (department, "lead" if i == 0 else "member"))
        return employees

    employees = yield from departments.flat_map(employees_of)

    assert (yield from employees.size()) == 3
    assert (yield from employees.get("alice")) == Some(("eng", "lead"))
    assert (yield from employees.get("bob")) == Some(("eng", "member"))
    assert (yield from employees.get("charlie")) == Some(("sales", "lead"))


@testing.effect
@in_tx
def test_compact_should_remove_none_values_and_unwrap_some_values():
    """compact should remove None values and unwrap Some values"""
    optional = yield from fx.TxHashMap[str, fx.option.Option[int]].empty()
    yield from optional.set_many(
        [
            ("valid1", Some(10)),
            ("invalid1", None),
            ("valid2", Some(20)),
            ("invalid2", None),
            ("valid3", Some(30)),
        ]
    )

    compacted = yield from optional.compact()

    assert (yield from compacted.size()) == 3
    assert (yield from compacted.get("valid1")) == Some(10)
    assert (yield from compacted.get("valid2")) == Some(20)
    assert (yield from compacted.get("valid3")) == Some(30)
    assert (yield from compacted.get("invalid1")) is None
    assert (yield from compacted.get("invalid2")) is None


@testing.effect
@in_tx
def test_to_entries_should_return_all_entries_as_array():
    """toEntries should return all entries as array"""
    tx_map = yield from fx.TxHashMap.make(("a", 1), ("b", 2), ("c", 3))

    entries = yield from tx_map.to_entries()
    assert len(entries) == 3
    assert sorted(entries) == [("a", 1), ("b", 2), ("c", 3)]
    assert sorted(entries) == sorted((yield from tx_map.entries()))


@testing.effect
@in_tx
def test_to_values_should_return_all_values_as_array():
    """toValues should return all values as array"""
    tx_map = yield from fx.TxHashMap.make(("x", 100), ("y", 200), ("z", 300))

    values = yield from tx_map.to_values()
    assert len(values) == 3
    assert sorted(values) == [100, 200, 300]
    assert sorted(values) == sorted((yield from tx_map.values()))


@testing.effect
@in_tx
def test_specialized_operations_should_work_correctly():
    """specialized operations should work correctly"""
    tx_map = yield from fx.TxHashMap[str, fx.option.Option[int]].empty()
    yield from tx_map.set_many([("a", Some(1)), ("b", None), ("c", Some(3))])

    yield from tx_map.set("d", Some(4))
    yield from tx_map.set("e", None)

    compacted = yield from tx_map.compact()
    assert (yield from compacted.size()) == 3

    total = [0]

    def add(value: int) -> None:
        total[0] += value

    yield from compacted.for_each(lambda value, _: fx.sync(lambda: add(value)))
    assert total[0] == 8

    assert len((yield from compacted.to_values())) == 3
    assert len((yield from compacted.to_entries())) == 3
