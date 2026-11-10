"""Effect's ``test/persistence/BackingPersistenceTest.ts``: the suite each
``BackingPersistence`` runs (its ``suite(name, layer)``), as bodies for the
test modules to run on their backends. ``SUITE`` lists them with their
Effect titles. A missing value is ``None``."""

from __future__ import annotations

from collections.abc import Callable, Generator
from typing import Any

import pyfect as fx
from pyfect.persistence.persistence import BackingPersistence

type Body = Callable[[], Generator[Any, Any]]


def clear_only_removes_its_store():
    backing = yield from BackingPersistence()
    # ids that extend "cache" by concatenation, a colon, or a glob
    store_ids = ["cache", "cacheusers", "cache:users", "c*"]
    stores = yield from fx.for_each(store_ids, backing.make)
    for store, store_id in zip(stores, store_ids, strict=True):
        yield from store.set("1", {"storeId": store_id}, None)

    yield from stores[0].clear
    assert (yield from fx.for_each(stores, lambda store: store.get("1"))) == [
        None,
        {"storeId": "cacheusers"},
        {"storeId": "cache:users"},
        {"storeId": "c*"},
    ]

    yield from stores[3].clear
    assert (yield from fx.for_each(stores, lambda store: store.get("1"))) == [
        None,
        {"storeId": "cacheusers"},
        {"storeId": "cache:users"},
        None,
    ]


def distinct_pairs_do_not_alias():
    backing = yield from BackingPersistence()
    pairs = [("a", "bc"), ("ab", "c"), ("a", "b:c"), ("a:b", "c"), ("a%3Ab", "c")]
    stores = yield from fx.for_each(pairs, lambda pair: backing.make(pair[0]))
    for store, pair in zip(stores, pairs, strict=True):
        yield from store.set(pair[1], {"pair": list(pair)}, None)

    found = yield from fx.for_each(
        list(zip(stores, pairs, strict=True)), lambda entry: entry[0].get(entry[1][1])
    )
    assert found == [{"pair": list(pair)} for pair in pairs]


SUITE: list[tuple[str, Body]] = [
    ("clear only removes entries from the cleared store", clear_only_removes_its_store),
    ("distinct store and key pairs do not alias", distinct_pairs_do_not_alias),
]
IDS = [body.__name__ for _, body in SUITE]
