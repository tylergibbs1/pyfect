"""Ports of Effect's ``test/Trie.test.ts``.

Each test's docstring is the Effect test title. Module functions are
methods. Omitted: "equality rejects tries with different numbers of entries
after a hash collision" (it forges a ``Hash.symbol`` collision; Python's
``==`` never consults hashes), "toString renders entries in iteration
order", "toJSON renders tagged entries", "inspect renders the JSON
representation" (Python's ``repr``).
"""

from __future__ import annotations

import pytest

from pyfect.option import Some
from pyfect.result import Err, Ok
from pyfect.trie import Trie


def call_me_mind_mid() -> Trie[int]:
    return Trie[int].empty().insert("call", 0).insert("me", 1).insert("mind", 2).insert("mid", 3)


def shells_sells_she() -> Trie[int]:
    return Trie[int].empty().insert("shells", 0).insert("sells", 1).insert("she", 2)


def test_iterates_no_entries_for_an_empty_trie() -> None:
    """iterates no entries for an empty trie"""
    trie = Trie[str].empty()
    assert len(trie) == 0
    assert list(trie) == []


def test_insert_returns_new_tries_and_orders_entries_by_key() -> None:
    """insert returns new tries and orders entries by key"""
    trie1 = Trie[int].empty().insert("call", 0)
    trie2 = trie1.insert("me", 1)
    trie3 = trie2.insert("mind", 2)
    trie4 = trie3.insert("mid", 3)
    assert list(trie1) == [("call", 0)]
    assert list(trie2) == [("call", 0), ("me", 1)]
    assert list(trie3) == [("call", 0), ("me", 1), ("mind", 2)]
    assert list(trie4) == [("call", 0), ("me", 1), ("mid", 3), ("mind", 2)]


def test_insert_replaces_a_key_without_mutating_or_growing_the_original() -> None:
    """insert replaces a key without mutating or growing the original"""
    before = Trie.make(("a", 1))
    after = before.insert("a", 2)
    assert [list(before), len(before), list(after), len(after)] == [[("a", 1)], 1, [("a", 2)], 1]


def test_from_iterable_preserves_an_empty_iterable() -> None:
    """fromIterable preserves an empty iterable"""
    entries: list[tuple[str, int]] = []
    assert list(Trie.from_iterable(entries)) == entries


def test_make_builds_a_trie_from_entry_pairs() -> None:
    """make builds a trie from entry pairs"""
    trie = Trie.make(("ca", 0), ("me", 1))
    assert list(trie) == [("ca", 0), ("me", 1)]
    assert Trie.from_iterable([("ca", 0), ("me", 1)]) == trie


def test_from_iterable_builds_the_same_trie_as_make() -> None:
    """fromIterable builds the same trie as make"""
    entries = [("ca", 0), ("me", 1)]
    trie = Trie.from_iterable(entries)
    assert list(trie) == entries
    assert Trie.make(("ca", 0), ("me", 1)) == trie


def test_from_iterable_orders_entries_by_key() -> None:
    """fromIterable orders entries by key"""
    trie = Trie.from_iterable([("call", 0), ("me", 1), ("mind", 2), ("mid", 3)])
    assert list(trie) == [("call", 0), ("me", 1), ("mid", 3), ("mind", 2)]


def test_from_iterable_preserves_already_sorted_entries() -> None:
    """fromIterable preserves already sorted entries"""
    assert list(Trie.from_iterable([("a", 0), ("b", 1)])) == [("a", 0), ("b", 1)]


def test_from_iterable_accepts_a_single_entry() -> None:
    """fromIterable accepts a single entry"""
    assert list(Trie.from_iterable([("a", 0)])) == [("a", 0)]


def test_from_iterable_orders_keys_when_one_key_is_a_prefix() -> None:
    """fromIterable orders keys when one key is a prefix"""
    assert list(Trie.from_iterable([("shells", 0), ("she", 1)])) == [("she", 1), ("shells", 0)]


def test_size_counts_stored_keys() -> None:
    """size counts stored keys"""
    assert len(Trie[int].empty().insert("a", 0).insert("b", 1)) == 2


def test_is_empty_distinguishes_empty_and_populated_tries() -> None:
    """isEmpty distinguishes empty and populated tries"""
    trie = Trie[int].empty()
    assert trie.is_empty()
    assert not trie.insert("ma", 0).is_empty()


def test_get_returns_some_only_for_exact_keys() -> None:
    """get returns Some only for exact keys"""
    trie = call_me_mind_mid()
    assert [trie.get(k) for k in ("call", "me", "mind", "mid")] == [
        Some(0),
        Some(1),
        Some(2),
        Some(3),
    ]
    assert all(trie.get(k) is None for k in ("cale", "ma", "midn", "mea"))


def test_stores_undefined_values() -> None:
    """stores undefined values"""
    trie = Trie.make(("a", None))
    assert len(trie) == 1
    assert trie.get("a") == Some(None)
    assert list(trie) == [("a", None)]


def test_get_distinguishes_complete_keys_from_prefixes() -> None:
    """get distinguishes complete keys from prefixes"""
    trie = Trie[int].empty().insert("shells", 0).insert("sells", 1).insert("she", 2)
    assert trie.get("sell") is None
    assert trie.get("sells") == Some(1)
    assert trie.get("shell") is None
    assert trie.get("she") == Some(2)


def test_has_returns_true_only_for_exact_keys() -> None:
    """has returns true only for exact keys"""
    trie = call_me_mind_mid()
    assert all(trie.has(k) for k in ("call", "me", "mind", "mid"))
    assert not any(trie.has(k) for k in ("cale", "ma", "midn", "mea"))


def test_get_unsafe_returns_the_value_or_throws_when_the_key_is_missing() -> None:
    """getUnsafe returns the value or throws when the key is missing"""
    trie = Trie[int].empty().insert("call", 0).insert("me", 1)
    assert trie.get_unsafe("call") == 0
    with pytest.raises(KeyError):
        trie.get_unsafe("mae")


def test_remove_deletes_a_key_without_mutating_the_original_trie() -> None:
    """remove deletes a key without mutating the original trie"""
    trie = call_me_mind_mid()
    trie1 = trie.remove("call")
    trie2 = trie1.remove("mea")
    assert trie.get("call") == Some(0)
    assert trie1.get("call") is None
    assert trie2.get("call") is None
    assert list(trie) == [("call", 0), ("me", 1), ("mid", 3), ("mind", 2)]
    assert list(trie1) == [("me", 1), ("mid", 3), ("mind", 2)]
    assert list(trie2) == [("me", 1), ("mid", 3), ("mind", 2)]


def test_remove_preserves_a_valued_prefix() -> None:
    """remove preserves a valued prefix"""
    assert list(Trie.make(("ab", 1), ("abc", 2)).remove("abc")) == [("ab", 1)]


def test_keys_returns_keys_in_sorted_order() -> None:
    """keys returns keys in sorted order"""
    trie = Trie[int].empty().insert("cab", 0).insert("abc", 1).insert("bca", 2)
    assert list(trie.keys()) == ["abc", "bca", "cab"]


def test_entries_stays_exhausted_while_the_trie_remains_reusable() -> None:
    """entries stays exhausted while the trie remains reusable"""
    trie = Trie.make(("app", 1))
    iterator = trie.entries()
    assert list(iterator) == [("app", 1)]
    assert list(iterator) == []
    assert list(trie) == [("app", 1)]
    assert list(trie) == [("app", 1)]


def test_keys_orders_nested_prefixes_alphabetically() -> None:
    """keys orders nested prefixes alphabetically"""
    words = [
        "abc",
        "bac",
        "b",
        "ca",
        "cac",
        "c",
        "abb",
        "ba",
        "a",
        "bca",
        "cab",
        "dca",
        "ab",
        "adc",
    ]
    trie = Trie.make(*((w, 0) for w in words))
    assert list(trie.keys()) == [
        "a", "ab", "abb", "abc", "adc", "b", "ba", "bac", "bca", "c", "ca", "cab", "cac", "dca",
    ]  # fmt: skip


def test_values_follow_key_iteration_order() -> None:
    """values follow key iteration order"""
    trie = Trie[int].empty().insert("call", 0).insert("me", 1).insert("and", 2)
    assert list(trie.values()) == [2, 0, 1]


def test_entries_iterates_key_value_pairs_in_sorted_order() -> None:
    """entries iterates key-value pairs in sorted order"""
    trie = Trie[int].empty().insert("call", 0).insert("me", 1)
    assert list(trie.entries()) == [("call", 0), ("me", 1)]


def test_to_entries_returns_a_sorted_entry_array() -> None:
    """toEntries returns a sorted entry array"""
    assert Trie[int].empty().insert("me", 1).insert("call", 0).to_entries() == [
        ("call", 0),
        ("me", 1),
    ]


def test_keys_with_prefix_returns_matching_keys_in_sorted_order() -> None:
    """keysWithPrefix returns matching keys in sorted order"""
    trie = Trie.make(
        ("she", 0), ("shells", 1), ("sea", 2), ("sells", 3),
        ("by", 4), ("the", 5), ("sea", 6), ("shore", 7),
    )  # fmt: skip
    assert list(trie.keys_with_prefix("she")) == ["she", "shells"]


def _shells_sells_sea_she() -> Trie[int]:
    return (
        Trie[int].empty().insert("shells", 0).insert("sells", 1).insert("sea", 2).insert("she", 3)
    )


def test_values_with_prefix_returns_matching_values_in_key_order() -> None:
    """valuesWithPrefix returns matching values in key order"""
    assert list(_shells_sells_sea_she().values_with_prefix("she")) == [3, 0]


def test_values_with_prefix_resumes_iteration_with_matching_values() -> None:
    """valuesWithPrefix resumes iteration with matching values"""
    iterator = Trie.make(("app", 1), ("apple", 2), ("banana", 3)).values_with_prefix("app")
    assert next(iterator) == 1
    assert list(iterator) == [2]
    assert list(iterator) == []


def test_entries_with_prefix_returns_matching_entries_in_key_order() -> None:
    """entriesWithPrefix returns matching entries in key order"""
    assert list(_shells_sells_sea_she().entries_with_prefix("she")) == [("she", 3), ("shells", 0)]


def test_to_entries_with_prefix_returns_matching_entries_as_an_array() -> None:
    """toEntriesWithPrefix returns matching entries as an array"""
    assert _shells_sells_sea_she().to_entries_with_prefix("she") == [("she", 3), ("shells", 0)]


def test_longest_prefix_of_returns_the_longest_stored_key_that_prefixes_the_input() -> None:
    """longestPrefixOf returns the longest stored key that prefixes the input"""
    trie = shells_sells_she()
    assert trie.longest_prefix_of("sell") is None
    assert trie.longest_prefix_of("sells") == Some(("sells", 1))
    assert trie.longest_prefix_of("shell") == Some(("she", 2))
    assert trie.longest_prefix_of("shellsort") == Some(("shells", 0))


def test_longest_prefix_of_ignores_valued_sibling_nodes_that_do_not_match_the_input() -> None:
    """longestPrefixOf ignores valued sibling nodes that do not match the input"""
    assert Trie.make(("a", 1), ("b", 2)).longest_prefix_of("c") is None


def test_map_transforms_values_and_can_use_keys() -> None:
    """map transforms values and can use keys"""
    trie = shells_sells_she()
    assert trie.map(lambda v, _k: v + 1) == Trie.make(("shells", 1), ("sells", 2), ("she", 3))
    assert trie.map(lambda _v, k: len(k)) == Trie.make(("shells", 6), ("sells", 5), ("she", 3))


def test_filter_keeps_entries_by_value_or_key() -> None:
    """filter keeps entries by value or key"""
    trie = shells_sells_she()
    assert trie.filter(lambda v, _k: v > 1) == Trie.make(("she", 2))
    assert trie.filter(lambda _v, k: len(k) > 3) == Trie.make(("shells", 0), ("sells", 1))


def test_filter_map_keeps_result_successes_and_can_use_keys() -> None:
    """filterMap keeps Result successes and can use keys"""
    trie = shells_sells_she()
    assert trie.filter_map(lambda v, _k: Ok(v) if v > 1 else Err(None)) == Trie.make(("she", 2))
    assert trie.filter_map(lambda v, k: Ok(v) if len(k) > 3 else Err(None)) == Trie.make(
        ("shells", 0), ("sells", 1)
    )


def test_compact_keeps_some_values() -> None:
    """compact keeps Some values"""
    trie = Trie.make(("shells", Some(0)), ("sells", None), ("she", Some(2)))
    assert trie.compact() == Trie.make(("shells", 0), ("she", 2))


def test_modify_updates_an_existing_key_and_ignores_a_missing_key() -> None:
    """modify updates an existing key and ignores a missing key"""
    trie = shells_sells_she()
    assert trie.modify("she", lambda v: v + 10).get("she") == Some(12)
    assert trie.modify("me", lambda v: v) == trie


def test_remove_many_deletes_all_matching_keys() -> None:
    """removeMany deletes all matching keys"""
    assert shells_sells_she().remove_many(["she", "sells"]) == Trie.make(("shells", 0))


def test_insert_many_inserts_all_entries() -> None:
    """insertMany inserts all entries"""
    inserted = Trie[int].empty().insert("shells", 0).insert_many([("sells", 1), ("she", 2)])
    assert shells_sells_she() == inserted


def test_reduce_visits_entries_in_key_order() -> None:
    """reduce visits entries in key order"""
    trie = shells_sells_she()
    assert trie.reduce(0, lambda acc, n, _k: acc + n) == 3
    assert trie.reduce(10, lambda acc, n, _k: acc + n) == 13
    assert trie.reduce("", lambda acc, _n, key: acc + key) == "sellssheshells"


def test_for_each() -> None:
    """forEach"""
    total = 0

    def add(n: int, key: str) -> None:
        nonlocal total
        total += n + len(key)

    shells_sells_she().for_each(add)
    assert total == 17


def test_equal_compares_tries_by_entries() -> None:
    """Equal compares tries by entries"""
    assert Trie[int].empty() == Trie[int].empty()
    assert Trie.make(("call", 0), ("me", 1)) == Trie.make(("call", 0), ("me", 1))
