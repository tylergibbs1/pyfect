"""Ports of Effect's ``sql-libsql/test/Client.integration.test.ts``.

Each test's docstring is the Effect test title. The first six run on
``:memory:`` databases or fake SDK clients; "shared tables" runs on the
session's sqld container (``_libsql.libsql_server``; skipped without
Docker), each test recreating the same table.

Adapted: the fake SDK clients are async (``LibsqlSdk``), awaited on the
SQL loop thread, so "releases transaction serialization after begin
fails" waits until the forked transaction calls ``transaction`` instead
of yielding once; ``.raw`` gives a ``ResultSet`` (Effect's ``toJSON()``
of one).
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine, Generator, Sequence
from typing import Any

import pyfect as fx
from pyfect import option, reactivity, testing
from pyfect.exit import Failure
from pyfect.sql import _loop, libsql
from pyfect.sql.error import SqlError, UnknownError
from pyfect.sql.libsql import LibsqlClientConfig, LibsqlLiveConfig, ResultSet
from pyfect.sql.libsql.sdk import SdkProtocol

from ._libsql import LibsqlServer

type Body = Callable[[], Generator[Any, Any, Any]]


def _memory() -> fx.Effect[libsql.LibsqlClientService, Any, fx.Scope]:
    return libsql.make(LibsqlClientConfig(url=":memory:")).pipe(fx.provide(reactivity.layer))


def _live(sdk: libsql.LibsqlSdk) -> fx.Effect[libsql.LibsqlClientService, Any, fx.Scope]:
    return libsql.make(LibsqlLiveConfig(live_client=sdk)).pipe(fx.provide(reactivity.layer))


_EMPTY = ResultSet((), (), (), 0, None)


def _on_loop(make: Callable[[], Coroutine[Any, Any, Any]]) -> fx.Effect[Any]:
    """Await ``make()`` on the SQL loop, where the fake SDK clients run."""
    return _loop.call(
        make, lambda error: SqlError(reason=UnknownError(cause=error)), waits_for="work"
    ).or_die()


@testing.effect
def test_exposes_the_active_transaction_service_for_each_client():
    """exposes the active transaction service for each client"""
    a = yield from _memory()
    b = yield from _memory()
    active = fx.all(
        fx.service_option(a.transaction_service).map(option.is_some),
        fx.service_option(b.transaction_service).map(option.is_some),
    )
    assert (yield from active) == (False, False)

    def in_a():
        assert (yield from active) == (True, False)
        assert (yield from b.with_transaction(active)) == (True, True)
        assert (yield from active) == (True, False)

    yield from a.with_transaction(fx.gen(in_a))
    assert (yield from active) == (False, False)


@testing.effect
def test_releases_completed_nested_savepoints():
    """releases completed nested savepoints"""
    sql = yield from _memory()
    yield from sql("CREATE TABLE savepoint_release (value INTEGER)")

    def outer():
        for rollback in (False, True):
            insert = sql("INSERT INTO savepoint_release VALUES (1)")
            yield from sql.with_transaction(
                insert.and_then(fx.fail("rollback") if rollback else fx.void)
            ).ignore()
            error = yield from sql("RELEASE SAVEPOINT effect_sql_1").unprepared.flip()
            assert isinstance(error, SqlError)

    yield from sql.with_transaction(fx.gen(outer))
    assert (yield from sql("SELECT value FROM savepoint_release")) == [{"value": 1}]
    error = yield from sql.with_transaction(
        sql.with_transaction(sql("INSERT INTO savepoint_release VALUES (2)")).and_then(
            fx.fail("outer rollback")
        )
    ).flip()
    assert error == "outer rollback"
    assert (yield from sql("SELECT value FROM savepoint_release")) == [{"value": 1}]


@testing.effect
def test_keeps_transactions_isolated_between_clients():
    """keeps transactions isolated between clients"""
    a = yield from _memory()
    b = yield from _memory()
    yield from a("CREATE TABLE marker (owner TEXT NOT NULL)")
    yield from b("CREATE TABLE marker (owner TEXT NOT NULL)")
    yield from a("INSERT INTO marker VALUES ('A')")
    yield from b("INSERT INTO marker VALUES ('B')")
    rows = yield from a.with_transaction(b("SELECT owner FROM marker"))
    assert rows == [{"owner": "B"}]


class _Transaction:
    def __init__(self, calls: list[str] | None = None, rollback_error: Exception | None = None):
        self.calls = [] if calls is None else calls
        self.rollback_error = rollback_error

    async def execute(self, sql: str, args: Sequence[object], /) -> ResultSet:
        return _EMPTY

    async def commit(self) -> None:
        self.calls.append("commit")

    async def rollback(self) -> None:
        self.calls.append("rollback")
        if self.rollback_error is not None:
            raise self.rollback_error


class _FlakyBegin:
    """Its first ``transaction`` fails; a later one sets ``called``."""

    protocol: SdkProtocol = "file"

    def __init__(self) -> None:
        self.transaction_calls = 0
        self.called = asyncio.Event()

    async def execute(self, sql: str, args: Sequence[object], /) -> ResultSet:
        return _EMPTY

    async def transaction(self, mode: libsql.TransactionMode, /) -> _Transaction:
        self.transaction_calls += 1
        if self.transaction_calls == 1:
            raise RuntimeError("transient begin failure")
        self.called.set()
        return _Transaction()


@testing.effect
def test_releases_transaction_serialization_after_begin_fails():
    """releases transaction serialization after begin fails"""
    sdk = _FlakyBegin()
    client = yield from _live(sdk)
    first = yield from client.with_transaction(fx.void).exit()
    assert isinstance(first, Failure)

    yield from client.with_transaction(fx.void).fork()
    yield from _on_loop(sdk.called.wait)
    assert sdk.transaction_calls == 2


class _PendingBegin:
    """Its first ``transaction`` sets ``started`` and waits for ``begin``."""

    protocol: SdkProtocol = "file"

    def __init__(self, transaction: _Transaction) -> None:
        self.open = transaction
        self.started = asyncio.Event()
        self.begin = asyncio.Event()
        self.transaction_calls = 0

    async def execute(self, sql: str, args: Sequence[object], /) -> ResultSet:
        return _EMPTY

    async def transaction(self, mode: libsql.TransactionMode, /) -> _Transaction:
        self.transaction_calls += 1
        if self.transaction_calls == 1:
            self.started.set()
            await self.begin.wait()
        return self.open

    def resolve_begin(self) -> None:
        _loop.get_loop().call_soon_threadsafe(self.begin.set)


def _interrupted_pending_begin(rollback_fails: bool):
    calls: list[str] = []
    rollback_error = RuntimeError("rollback failed")
    transaction = _Transaction(calls, rollback_error if rollback_fails else None)
    sdk = _PendingBegin(transaction)
    client = yield from _live(sdk)
    fiber = yield from client.with_transaction(
        fx.sync(lambda: calls.append("cancelled body"))
    ).fork()
    yield from _on_loop(sdk.started.wait)
    # Request interruption while the SDK still owns the pending BEGIN.
    fiber.interrupt_as_unsafe(None)
    sdk.resolve_begin()
    exit_ = yield from fiber.await_exit()

    assert isinstance(exit_, Failure)
    assert exit_.cause.has_interrupts
    defects = exit_.cause.defects
    assert len(defects) == (1 if rollback_fails else 0)
    if rollback_fails:
        assert isinstance(defects[0], SqlError)
        assert defects[0].reason.cause is rollback_error
    assert calls == ["rollback"]

    yield from client.with_transaction(fx.sync(lambda: calls.append("next body")))
    assert calls == ["rollback", "next body", "commit"]


@testing.effect
def test_rolls_back_an_interrupted_pending_begin_rollback_succeeds():
    """rolls back an interrupted pending begin (rollback succeeds)"""
    yield from _interrupted_pending_begin(False)


@testing.effect
def test_rolls_back_an_interrupted_pending_begin_rollback_rejects():
    """rolls back an interrupted pending begin (rollback rejects)"""
    yield from _interrupted_pending_begin(True)


class _RemoteStatements:
    """A remote client whose statements wait until ``resolve`` is called."""

    protocol: SdkProtocol = "http"

    def __init__(self, calls: list[str]) -> None:
        self.calls = calls
        self.statement = asyncio.Event()

    async def execute(self, sql: str, args: Sequence[object], /) -> ResultSet:
        self.calls.append("execute")
        await self.statement.wait()
        return _EMPTY

    async def transaction(self, mode: libsql.TransactionMode, /) -> _Transaction:
        return _Transaction()

    def resolve(self) -> None:
        _loop.get_loop().call_soon_threadsafe(self.statement.set)


@testing.effect
def test_overlaps_remote_statements_with_each_other_and_open_transactions():
    """overlaps remote statements with each other and open transactions"""
    calls: list[str] = []
    sdk = _RemoteStatements(calls)
    client = yield from _live(sdk)
    opened = fx.Deferred[None]()
    release = fx.Deferred[None]()
    tx = yield from client.with_transaction(opened.succeed(None).and_then(release.wait())).fork()
    yield from opened.wait()

    statements = yield from fx.all(
        client("SELECT 1"), client("SELECT 2"), concurrency="unbounded"
    ).fork()
    # The SDK runs on the SQL loop thread: wait until both statements reach it.
    yield from _on_loop(lambda: _until(lambda: len(calls) == 2))
    assert calls == ["execute", "execute"]

    sdk.resolve()
    yield from statements.join()
    yield from release.succeed(None)
    yield from tx.join()


async def _until(done: Callable[[], bool]) -> None:
    while not done():
        await asyncio.sleep(0)


@testing.effect
def test_serializes_local_statements_behind_open_transactions():
    """serializes local statements behind open transactions"""
    sql = yield from _memory()
    yield from sql("CREATE TABLE serialized (value INTEGER)")
    opened = fx.Deferred[None]()
    release = fx.Deferred[None]()
    tx = yield from sql.with_transaction(
        sql("INSERT INTO serialized VALUES (1)")
        .and_then(opened.succeed(None))
        .and_then(release.wait())
    ).fork()
    yield from opened.wait()

    read = yield from sql("SELECT value FROM serialized").fork()
    yield from fx.yield_now()
    yield from release.succeed(None)
    yield from tx.join()

    assert (yield from read.join()) == [{"value": 1}]


# --- shared tables (sqld) ---------------------------------------------------------


def _with_table(server: LibsqlServer, body: Body) -> fx.Effect[Any, Any]:
    """``body`` with a fresh ``test`` table (Effect's ``Migrations``)."""

    def run():
        sql = yield from libsql.LibsqlClient()
        yield from sql("DROP TABLE IF EXISTS test")
        yield from fx.acquire_release(
            sql("CREATE TABLE test (id INTEGER PRIMARY KEY, name TEXT)"),
            lambda _, __: sql("DROP TABLE test;").ignore(),
        )
        return (yield from fx.gen(body))

    layer = libsql.layer(LibsqlClientConfig(url=server.url))
    return fx.scoped(fx.gen(run)).pipe(fx.provide(layer))


@testing.effect
def test_shared_tables_should_work(libsql_server: LibsqlServer):
    """shared tables / should work"""

    def body():
        sql = yield from libsql.LibsqlClient()
        response = yield from sql("INSERT INTO test (name) VALUES ('hello')")
        assert response == []
        response = yield from sql("SELECT * FROM test")
        assert response == [{"id": 1, "name": "hello"}]
        assert (yield from sql("select * from test").values) == [(1, "hello")]

    yield from _with_table(libsql_server, body)


@testing.effect
def test_shared_tables_should_work_with_raw(libsql_server: LibsqlServer):
    """shared tables / should work with raw"""

    def body():
        sql = yield from libsql.LibsqlClient()
        yield from sql("DROP TABLE IF EXISTS test2")
        response = yield from sql("CREATE TABLE test2 (id INTEGER PRIMARY KEY, name TEXT)").raw
        yield from fx.add_finalizer(lambda _: sql("DROP TABLE test2;").ignore())
        assert response == ResultSet((), (), (), 0, None)
        response = yield from sql("INSERT INTO test (name) VALUES ('hello')").raw
        assert response == ResultSet((), (), (), 1, 1)
        response = yield from sql("SELECT * FROM test").raw
        assert response == ResultSet(("id", "name"), ("INTEGER", "TEXT"), ((1, "hello"),), 0, None)

    yield from _with_table(libsql_server, body)


@testing.effect
def test_shared_tables_with_transaction(libsql_server: LibsqlServer):
    """shared tables / withTransaction"""

    def body():
        sql = yield from libsql.LibsqlClient()
        yield from sql.with_transaction(sql("INSERT INTO test (name) VALUES ('hello')"))
        assert (yield from sql("SELECT * FROM test")) == [{"id": 1, "name": "hello"}]

    yield from _with_table(libsql_server, body)


@testing.effect
def test_shared_tables_with_transaction_rollback(libsql_server: LibsqlServer):
    """shared tables / withTransaction rollback"""

    def body():
        sql = yield from libsql.LibsqlClient()
        yield from sql.with_transaction(
            sql("INSERT INTO test (name) VALUES ('hello')").and_then(fx.fail("boom"))
        ).ignore()
        assert (yield from sql("SELECT * FROM test")) == []

    yield from _with_table(libsql_server, body)


@testing.effect
def test_shared_tables_with_transaction_nested(libsql_server: LibsqlServer):
    """shared tables / withTransaction nested"""

    def body():
        sql = yield from libsql.LibsqlClient()
        stmt = sql("INSERT INTO test (name) VALUES ('hello')")
        yield from sql.with_transaction(stmt.and_then(sql.with_transaction(stmt)))
        rows = yield from sql("select count(*) as total_rows FROM test")
        assert rows[0]["total_rows"] == 2

    yield from _with_table(libsql_server, body)


@testing.effect
def test_shared_tables_with_transaction_nested_rollback(libsql_server: LibsqlServer):
    """shared tables / withTransaction nested rollback"""

    def body():
        sql = yield from libsql.LibsqlClient()
        stmt = sql("INSERT INTO test (name) VALUES ('hello')")
        yield from sql.with_transaction(
            stmt.and_then(sql.with_transaction(stmt.and_then(fx.fail("boom"))).ignore())
        )
        rows = yield from sql("select count(*) as total_rows FROM test")
        assert rows[0]["total_rows"] == 1

    yield from _with_table(libsql_server, body)
