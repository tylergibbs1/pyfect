"""The ``BackingPersistence`` suite of Effect's
``sql-sqlite-node/test/Persistence.test.ts`` (its ``suite(name, layer,
options)``) and ``test/persistence/SqlCleanupTest.ts``, as bodies for the
SQL driver test modules. A missing value is ``None``; ``TestClock.adjust``
is ``testing.adjust`` (seconds)."""

from __future__ import annotations

from collections.abc import Callable, Generator
from typing import Any, LiteralString

import pyfect as fx
from pyfect import schedule, testing
from pyfect.persistence import persistence
from pyfect.persistence.persistence import BackingPersistence
from pyfect.sql import SqlClient

type Body = Callable[[], Generator[Any, Any]]

EXPIRED_ENTRY_COUNT = persistence.SQL_CLEANUP_BATCH_SIZE + 1
EXPIRED_AT_EPOCH = 0
FUTURE_EXPIRES_AT = 2**53 - 1
CLEANUP_BATCH_DELAY = 0.01
TEST_TIMEOUT = 30.0


def set_get():
    store = yield from (yield from BackingPersistence()).make("test_store")
    yield from store.set("key1", {"name": "Alice"}, None)
    assert (yield from store.get("key1")) == {"name": "Alice"}
    # test upsert
    yield from store.set("key1", {"name": "Alice"}, None)


def set_many_get_many():
    store = yield from (yield from BackingPersistence()).make("test_store_2")
    yield from store.set_many(
        [
            ("key1", {"name": "Alice"}, None),
            ("key2", {"name": "Bob"}, None),
            ("key3", {"name": "Charlie"}, None),
        ]
    )
    assert (yield from store.get_many(["key1", "key2", "key3", "key4"])) == [
        {"name": "Alice"},
        {"name": "Bob"},
        {"name": "Charlie"},
        None,
    ]


def get_many_with_duplicate_keys():
    store = yield from (yield from BackingPersistence()).make("test_store_duplicate_keys")
    yield from store.set("key", {"value": 1}, None)
    assert (yield from store.get_many(["key", "key"])) == [{"value": 1}, {"value": 1}]


def remove():
    store = yield from (yield from BackingPersistence()).make("test_store_2")
    yield from store.set_many(
        [
            ("key1", {"name": "Alice"}, None),
            ("key2", {"name": "Bob"}, None),
            ("key3", {"name": "Charlie"}, None),
        ]
    )
    yield from store.remove("key2")
    assert (yield from store.get_many(["key1", "key2", "key3"])) == [
        {"name": "Alice"},
        None,
        {"name": "Charlie"},
    ]


def expires():
    store = yield from (yield from BackingPersistence()).make("test_store_3")
    yield from store.set_many(
        [
            ("key1", {"name": "Alice"}, None),
            ("key2", {"name": "Bob"}, None),
            ("key3", {"name": "Charlie"}, fx.duration.Seconds(10)),
        ]
    )
    everyone = [{"name": "Alice"}, {"name": "Bob"}, {"name": "Charlie"}]
    assert (yield from store.get_many(["key1", "key2", "key3"])) == everyone
    yield from testing.adjust(5)
    assert (yield from store.get_many(["key1", "key2", "key3"])) == everyone
    yield from testing.adjust(5)
    assert (yield from store.get_many(["key1", "key2", "key3"])) == [
        {"name": "Alice"},
        {"name": "Bob"},
        None,
    ]


def reused_get_expires():
    store = yield from (yield from BackingPersistence()).make("test_store_reused_get")
    yield from store.set("key", {"name": "Alice"}, fx.duration.Seconds(10))
    get = store.get("key")
    assert (yield from get) == {"name": "Alice"}
    yield from testing.adjust(10)
    assert (yield from get) is None


def reused_get_many_expires():
    store = yield from (yield from BackingPersistence()).make("test_store_reused_get_many")
    yield from store.set("key", {"name": "Alice"}, fx.duration.Seconds(10))
    get_many = store.get_many(["key"])
    assert (yield from get_many) == [{"name": "Alice"}]
    yield from testing.adjust(10)
    assert (yield from get_many) == [None]


def isolation_between_stores():
    backing = yield from BackingPersistence()
    store_a = yield from backing.make("test_store_a")
    store_b = yield from backing.make("test_store_b")
    yield from store_a.set("shared-key", {"name": "Alice"}, None)
    yield from store_b.set("shared-key", {"name": "Bob"}, None)
    assert (yield from store_a.get("shared-key")) == {"name": "Alice"}
    assert (yield from store_b.get("shared-key")) == {"name": "Bob"}
    yield from store_a.clear
    assert (yield from store_a.get("shared-key")) is None
    assert (yield from store_b.get("shared-key")) == {"name": "Bob"}


def get_many_treats_quotes_as_data():
    store = yield from (yield from BackingPersistence()).make("test_store_quotes")
    yield from store.set("it's-a-key", {"name": "Alice"}, None)
    assert (yield from store.get_many(["it's-a-key", "missing'key"])) == [{"name": "Alice"}, None]


def get_many_preserves_store_isolation(injection_probe: str) -> Body:
    def body():
        backing = yield from BackingPersistence()
        victim = yield from backing.make("sqli_victim")
        yield from victim.set("secret", {"secret": "victim-data"}, None)
        attacker = yield from backing.make("sqli_attacker")
        yield from attacker.set("innocent", {"name": "Mallory"}, None)
        assert (yield from attacker.get_many(["secret", injection_probe])) == [None, None]
        assert (yield from attacker.get("secret")) is None

    return body


def wait_for_count(
    effect: fx.Effect[int, Any, Any], predicate: Callable[[int], bool]
) -> fx.Effect[int, Any, Any]:
    """``effect`` run every 10 ms on the live clock until ``predicate``
    holds, for at most 30 seconds (``SqlCleanupTest.waitForCount``)."""
    return testing.with_live(
        effect.repeat(until=predicate, schedule=schedule.spaced(CLEANUP_BATCH_DELAY)).timeout(
            TEST_TIMEOUT
        )
    )


def deletes_expired_entries_in_batches(index_count: str, key_type: LiteralString = "TEXT") -> Body:
    """``Persistence SQL cleanup / deletes expired entries in batches``:
    ``index_count`` counts the expires index in the dialect's catalog;
    ``key_type`` is the key columns' type (MySQL keys no ``TEXT``)."""

    def body():
        sql = (yield from SqlClient()).without_transforms()
        table = sql.identifier("effect_persistence")
        expired_count = sql(
            "SELECT COUNT(*) AS count FROM {} WHERE store_id = 'expired'", table
        ).map(lambda rows: int(rows[0]["count"]))  # pyright: ignore[reportArgumentType]
        yield from sql(
            f"CREATE TABLE {{}} (store_id {key_type} NOT NULL, id {key_type} NOT NULL, "
            "value TEXT NOT NULL, expires BIGINT, PRIMARY KEY (store_id, id))",
            table,
        )
        entries = [
            {"store_id": "expired", "id": str(i), "value": "{}", "expires": EXPIRED_AT_EPOCH}
            for i in range(EXPIRED_ENTRY_COUNT)
        ]
        yield from sql("INSERT INTO {} {}", table, sql.insert(entries)).unprepared
        yield from sql(
            "INSERT INTO {} (store_id, id, value, expires) "
            "VALUES ('live', 'live', '{{}}', NULL), ('live', 'future', '{{}}', {})",
            table,
            FUTURE_EXPIRES_AT,
        )

        yield from testing.with_live(persistence.layer_backing_sql.build())

        assert (yield from wait_for_count(expired_count, lambda count: count == 0)) == 0
        live = yield from sql("SELECT COUNT(*) AS count FROM {} WHERE store_id = 'live'", table)
        assert live[0]["count"] == 2
        indexes = yield from sql.unsafe(index_count)
        assert indexes[0]["count"] == 1

    return body
