"""``TestRunner.layer`` and ``SingleRunner.layer`` serve entities end to
end. Effect has no tests of these two layers; these check that each one
builds a working runner."""

from __future__ import annotations

from pathlib import Path

import pyfect as fx
from pyfect import reactivity, testing
from pyfect.cluster import single_runner, test_runner
from pyfect.cluster.message_storage import MemoryDriver
from pyfect.sql import sqlite
from pyfect.sql.client import SqlClient

from ._cluster_entities import TestEntity, User, test_entity_layer


@testing.effect
def test_test_runner_serves_volatile_and_durable_requests():
    @fx.gen
    def body():
        yield from testing.adjust(0.001)
        driver = yield from MemoryDriver()
        client = (yield from TestEntity.client())("1")
        assert (yield from client.get_user_volatile({"id": 1})) == User(id=1, name="User 1")
        assert (yield from client.get_user({"id": 2})) == User(id=2, name="User 2")
        assert len(driver.encoded.journal) == 1

    yield from body.pipe(
        fx.provide(test_entity_layer.pipe(fx.layer.provide_merge(test_runner.layer)))
    )


@testing.live(timeout=30)
def test_single_runner_persists_durable_requests_in_sql(tmp_path: Path):
    sql = fx.layer.effect(
        SqlClient,
        sqlite.make(sqlite.SqliteClientConfig(filename=str(tmp_path / "runner.db"))),
    ).pipe(fx.layer.provide(reactivity.layer))

    @fx.gen
    def body():
        client = (yield from TestEntity.client())("1")
        assert (yield from client.get_user({"id": 3})) == User(id=3, name="User 3")
        rows = yield from (yield from SqlClient()).unsafe(
            "SELECT COUNT(*) AS n FROM cluster_messages"
        )
        assert rows[0]["n"] == 1

    yield from body.pipe(
        fx.provide(
            test_entity_layer.pipe(
                fx.layer.provide_merge(single_runner.layer(runner_storage_kind="memory"))
            ).pipe(fx.layer.provide_merge(sql))
        )
    )
