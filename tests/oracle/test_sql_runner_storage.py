"""Ports of platform-node's ``test/cluster/SqlRunnerStorage.integration.test.ts``
for ``pyfect.cluster.sql_runner_storage`` on SQLite and on the throwaway
PostgreSQL server (``_postgres.pg_server``; those cases skip without one).

Each test's docstring is the Effect test title. Effect gives each case an
empty database; here each one uses its own table prefix (advisory locks
are namespaced by prefix too). MySQL and Vitess are not run (no server).

Omitted:
- "cluster SQL storage with a DML-only role" (both titles): they revoke
  ``CREATE`` on the shared server's ``public`` schema, which every other
  PostgreSQL test needs.
- "bounds shard lock operations ...", "empty liveness probe ...", "recovers
  when a blackholed query ...", "rebuilds the reserved connection again
  ...", "rebuilds the reserved connection when releasing ... hangs",
  "replaces a pending reserved connection once ...", "replaces a connection
  that fails ...": they partition a connection through Effect's in-process
  socket proxy that drops packets mid-query; the rebuild logic they reach
  is ``ResourceRef``'s, covered by ``test_resource_ref.py``.
- "pg (no advisory) does not deadlock acquisition with refresh or bulk
  release": a timing stress test on triggers delaying each row.
- ``sql-pglite``'s "does not starve the shared PGlite connection": PGlite
  (PostgreSQL compiled to WebAssembly, one connection) has no Python
  counterpart.
"""

from __future__ import annotations

import itertools
import os
from collections.abc import Callable, Generator
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

import pyfect as fx
from pyfect import reactivity, testing
from pyfect.cluster import runner, runner_address, shard_id, sharding_config
from pyfect.cluster import sql_runner_storage as SqlRunnerStorage
from pyfect.cluster.runner_storage import RunnerStorageService
from pyfect.cluster.sharding_config import DEFAULTS
from pyfect.sql.client import SqlClient, SqlClientService

from ._sqlite import make_client

_prefixes = itertools.count()
runner_address1 = runner_address.make("localhost", 1234)
runner_address2 = runner_address.make("localhost", 1235)


def _prefix(name: str) -> str:
    return f"{name}_{os.getpid()}_{next(_prefixes)}"


type ClientMaker = Callable[[], fx.Effect[SqlClientService, Any, fx.Scope]]


@pytest.fixture(params=["sqlite", "pg"])
def backend(request: pytest.FixtureRequest, tmp_path: Path) -> tuple[str, ClientMaker]:
    if request.param == "sqlite":
        return "sqlite", lambda: make_client(tmp_path)
    pytest.importorskip("psycopg")
    server = request.getfixturevalue("pg_server")
    return "pg", lambda: _pg(server)


def _storage(
    client: SqlClientService, prefix: str, **config: Any
) -> fx.Effect[RunnerStorageService, Any, fx.Scope]:
    settings = sharding_config.layer(replace(DEFAULTS, **config))
    return (
        SqlRunnerStorage.make(prefix=prefix)
        .pipe(fx.provide_service(SqlClient, client))
        .pipe(fx.provide(settings))
    )


def _ids(shards: list[shard_id.ShardId]) -> list[int]:
    return [s.id for s in shards]


@pytest.mark.parametrize("advisory", [True, False], ids=["advisory", "no advisory"])
@testing.live
def test_get_runners(backend: tuple[str, ClientMaker], advisory: bool):
    """getRunners"""

    def body() -> Generator[fx.Effect[Any, Any, Any], Any]:
        client = yield from backend[1]()
        storage = yield from _storage(
            client, _prefix("runners"), shard_lock_disable_advisory=not advisory
        )
        r = runner.make(address=runner_address1, groups=("default",), weight=1)
        machine_id = yield from storage.register(r, True)
        yield from storage.register(r, True)
        assert machine_id == 1
        assert (yield from storage.get_runners) == [(r, True)]

        yield from storage.set_runner_health(runner_address1, False)
        assert (yield from storage.get_runners) == [(r, False)]

        yield from storage.unregister(runner_address1)
        assert (yield from storage.get_runners) == []

    yield from fx.gen(body)


@pytest.mark.parametrize("advisory", [True, False], ids=["advisory", "no advisory"])
@testing.live
def test_acquire_shards(backend: tuple[str, ClientMaker], advisory: bool):
    """acquireShards"""

    def body() -> Generator[fx.Effect[Any, Any, Any], Any]:
        client = yield from backend[1]()
        storage = yield from _storage(
            client, _prefix("acquire"), shard_lock_disable_advisory=not advisory
        )
        first = [shard_id.make("default", i) for i in (1, 2, 3)]
        assert _ids((yield from storage.acquire(runner_address1, first))) == [1, 2, 3]
        assert _ids((yield from storage.acquire(runner_address1, first))) == [1, 2, 3]
        fourth = [shard_id.make("default", 4)]
        assert _ids((yield from storage.acquire(runner_address1, fourth))) == [4]

        refreshed = yield from storage.refresh(runner_address1, first)
        assert sorted(_ids(refreshed)) == [1, 2, 3]

        yield from storage.release(runner_address1, shard_id.make("default", 2))

    yield from fx.gen(body)


def _pg(pg_server: Any) -> fx.Effect[SqlClientService, Any, fx.Scope]:
    pytest.importorskip("psycopg")
    from pyfect.sql import pg

    return pg.make(pg.PgPoolConfig(url=pg_server.url)).pipe(fx.provide(reactivity.layer))


@testing.live
def test_isolates_advisory_shard_locks_by_prefix(pg_server: Any):
    """isolates advisory shard locks by prefix"""

    def body() -> Generator[fx.Effect[Any, Any, Any], Any]:
        client = yield from _pg(pg_server)
        storage_a = yield from _storage(client, _prefix("cluster"))
        storage_b = yield from _storage(client, _prefix("other"))
        shard = shard_id.make("default", 1)
        assert (yield from storage_a.acquire(runner_address1, [shard])) == [shard]
        assert (yield from storage_b.acquire(runner_address2, [shard])) == [shard]

    yield from fx.gen(body)


@testing.live
def test_excludes_other_storages_using_same_prefix(pg_server: Any):
    """excludes other storages using the same prefix"""

    def body() -> Generator[fx.Effect[Any, Any, Any], Any]:
        client = yield from _pg(pg_server)
        prefix = _prefix("cluster")
        storage_a = yield from _storage(client, prefix)
        storage_b = yield from _storage(client, prefix)
        shard = shard_id.make("default", 1)
        assert (yield from storage_a.acquire(runner_address1, [shard])) == [shard]
        assert (yield from storage_b.acquire(runner_address2, [shard])) == []

    yield from fx.gen(body)


@testing.live
def test_runner_migrations_adopt_existing_tables(pg_server: Any):
    """runner migrations adopt existing tables without migration records"""

    def body() -> Generator[fx.Effect[Any, Any, Any], Any]:
        sql = yield from _pg(pg_server)
        prefix = _prefix("legacy")
        runners = sql.identifier(f"{prefix}_runners")
        yield from sql(
            "CREATE TABLE {} (machine_id SERIAL PRIMARY KEY, address VARCHAR(255) NOT NULL, "
            "runner TEXT NOT NULL, healthy BOOLEAN NOT NULL DEFAULT TRUE, "
            "last_heartbeat TIMESTAMP NOT NULL DEFAULT NOW(), UNIQUE(address))",
            runners,
        )
        yield from sql("INSERT INTO {} (address, runner) VALUES ('legacy:1', 'legacy')", runners)
        select = sql("SELECT machine_id, address, runner, healthy FROM {}", runners)
        rows = yield from select

        yield from SqlRunnerStorage.run_migrations(prefix=prefix).pipe(
            fx.provide_service(SqlClient, sql)
        )

        assert (yield from select) == rows
        assert (yield from sql("SELECT * FROM {}", sql.identifier(f"{prefix}_locks"))) == []

    yield from fx.gen(body)


def test_postgres_lock_namespace_matches_effect():
    """The advisory-lock namespace is Effect's FNV-1a wire format (values
    from Effect's ``postgresLockNamespace`` under Node)."""
    assert SqlRunnerStorage.postgres_lock_namespace("cluster") == -1455371005
    assert SqlRunnerStorage.postgres_lock_namespace("other") == -153440585
    assert SqlRunnerStorage.postgres_lock_namespace("\u00fcn\u00ef") == 1675597136


@testing.live
def test_an_interrupted_lock_operation_keeps_the_reserved_connection(pg_server: Any):
    """pyfect: an interrupted lock operation is not a broken connection, so
    the reserved connection is kept. Replacing it releases the old one in a
    fiber of the storage's scope; when that rebuild comes from a runner
    shutting down, closing the scope interrupts the release before
    ``pg_advisory_unlock_all``, and the old session goes back to the pool
    still holding every shard lock (seen as shards no runner could acquire in
    the cluster-integration restart tests)."""
    from ._cluster_harness import _LockFaultController  # pyright: ignore[reportPrivateUsage]

    def body() -> Generator[fx.Effect[Any, Any, Any], Any]:
        client = yield from _pg(pg_server)
        faults = _LockFaultController(client)
        reserve = faults.client.reserve
        reserves = [0]

        def counted() -> Any:
            reserves[0] += 1
            return reserve

        faults.client.reserve = fx.suspend(counted)
        storage = yield from _storage(faults.client, _prefix("interrupted"))
        shard = shard_id.make("default", 1)
        assert (yield from storage.acquire(runner_address1, [shard])) == [shard]
        assert reserves == [1]

        yield from faults.set("blackhole")
        refresh = yield from storage.refresh(runner_address1, [shard]).fork()
        yield from fx.sleep(0.05)
        yield from refresh.interrupt()
        yield from faults.set("clear")
        yield from fx.sleep(0.2)
        assert reserves == [1]

    yield from fx.gen(body)
