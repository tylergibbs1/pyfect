"""The advisory-lock session of ``pyfect.cluster.sql_runner_storage`` on the
throwaway PostgreSQL and MySQL servers (skips without one), as in Effect
4.1.2's ``SqlRunnerStorage``: a refresh confirms only the locks the current
session holds, the server ends a session left idle for
``shard_lock_expiration``, an acquire retries once on the replacement
session, and the connection goes back to the pool with its settings
restored."""

from __future__ import annotations

import itertools
import os
from collections.abc import Callable, Generator
from dataclasses import replace
from typing import Any

import pytest

import pyfect as fx
from pyfect import reactivity, testing
from pyfect.cluster import runner_address, shard_id, sharding_config
from pyfect.cluster import sql_runner_storage as SqlRunnerStorage
from pyfect.cluster.runner_storage import RunnerStorageService
from pyfect.cluster.sharding_config import DEFAULTS
from pyfect.duration import millis
from pyfect.exit import Success
from pyfect.sql.client import SqlClient, SqlClientService

_prefixes = itertools.count()
address1 = runner_address.make("localhost", 1234)
address2 = runner_address.make("localhost", 1235)
shard1 = shard_id.make("default", 1)
shard2 = shard_id.make("default", 2)

type ClientMaker = Callable[[], fx.Effect[SqlClientService, Any, fx.Scope]]


def _prefix() -> str:
    return f"sessions_{os.getpid()}_{next(_prefixes)}"


def _pg(server: Any) -> fx.Effect[SqlClientService, Any, fx.Scope]:
    from pyfect.sql import pg

    config = pg.PgPoolConfig(url=server.url, max_connections=1)
    return pg.make(config).pipe(fx.provide(reactivity.layer))


def _mysql(server: Any) -> fx.Effect[SqlClientService, Any, fx.Scope]:
    from pyfect.sql import mysql

    config = mysql.MysqlClientConfig(url=server.url, max_connections=1)
    return mysql.make(config).pipe(fx.provide(reactivity.layer))


@pytest.fixture(params=["pg", "mysql"])
def backend(request: pytest.FixtureRequest) -> tuple[str, ClientMaker]:
    if request.param == "mysql":
        pytest.importorskip("asyncmy")
        server = request.getfixturevalue("mysql_server")
        return "mysql", lambda: _mysql(server)
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


def _end_lock_session(dialect: str, sql: SqlClientService, prefix: str) -> fx.Effect[None, Any]:
    """End the session holding ``shard1``'s advisory lock, as a server
    restart or a network partition would."""
    if dialect == "pg":
        namespace = SqlRunnerStorage.postgres_lock_namespace(prefix) & 0xFFFFFFFF
        return sql.unsafe(
            "SELECT pg_terminate_backend(pid, 10000) FROM pg_locks "
            f"WHERE locktype = 'advisory' AND objsubid = 2 AND classid = {namespace}"
        ).as_void()

    @fx.gen
    def mysql():
        rows = yield from sql.unsafe(f"SELECT IS_USED_LOCK('{prefix}.{shard1}') AS owner")
        yield from sql.unsafe(f"KILL {int(str(rows[0]['owner']))}")

    return mysql


@testing.live(timeout="60 seconds")
def test_an_advisory_refresh_does_not_reacquire_locks_lost_with_the_session(
    backend: tuple[str, ClientMaker],
):
    """pyfect: a replaced lock session has lost its predecessor's locks,
    maybe to another runner in between, so a refresh on it confirms none of
    them (a refresh that reacquired them would hide the loss)."""
    dialect, make_client = backend

    def body() -> Generator[fx.Effect[Any, Any, Any], Any]:
        client = yield from make_client()
        prefix = _prefix()
        storage = yield from _storage(client, prefix)
        assert (yield from storage.acquire(address1, [shard1])) == [shard1]

        # The pool has one connection, which the storage reserved.
        yield from _end_lock_session(dialect, (yield from make_client()), prefix)
        # The first operation on the ended session fails and replaces it.
        first = yield from storage.refresh(address1, [shard1]).exit()
        second = yield from storage.refresh(address1, [shard1])
        assert not isinstance(first, Success) or first.value == []
        assert second == []
        # Acquiring takes the lock again on the new session.
        assert (yield from storage.acquire(address1, [shard1])) == [shard1]

    yield from fx.gen(body)


@testing.live(timeout="60 seconds")
def test_the_server_ends_a_lock_session_left_idle_for_the_lock_expiration(
    backend: tuple[str, ClientMaker],
):
    """pyfect: a runner whose process is frozen with its connection open
    holds its advisory locks only until the server ends the idle session,
    after ``shard_lock_expiration``. Acquiring again then succeeds on the
    first try, on a new session."""
    _, make_client = backend

    def body() -> Generator[fx.Effect[Any, Any, Any], Any]:
        client = yield from make_client()
        prefix = _prefix()
        expiring = yield from _storage(client, prefix, shard_lock_expiration=millis(1000))
        assert (yield from expiring.acquire(address1, [shard1])) == [shard1]

        other_client = yield from make_client()
        other = yield from _storage(other_client, prefix)
        assert (yield from other.acquire(address2, [shard1])) == []
        yield from fx.sleep("2500 millis")
        assert (yield from other.acquire(address2, [shard1])) == [shard1]

        assert (yield from expiring.acquire(address1, [shard2])) == [shard2]

    yield from fx.gen(body)


@testing.live(timeout="60 seconds")
def test_the_lock_connection_goes_back_to_the_pool_with_its_idle_timeout_restored(
    backend: tuple[str, ClientMaker],
):
    """pyfect: the lock connection comes from the shared pool (of one
    connection here), so closing the storage restores the idle timeout it
    changed."""
    dialect, make_client = backend
    show = (
        "SELECT current_setting('idle_session_timeout') AS value"
        if dialect == "pg"
        else "SELECT @@SESSION.wait_timeout AS value"
    )

    def body() -> Generator[fx.Effect[Any, Any, Any], Any]:
        client = yield from make_client()
        before = yield from client.unsafe(show)
        yield from fx.scoped(
            _storage(client, _prefix(), shard_lock_expiration=millis(1000)).flat_map(
                lambda storage: storage.acquire(address1, [shard1])
            )
        )
        assert (yield from client.unsafe(show)) == before

    yield from fx.gen(body)
