"""Ports of the titles of Effect's other SQLite drivers whose behavior
``pyfect.sql.sqlite`` shares with ``node:sqlite``: from
``sql-sqlite-bun/test/Client.test.ts``, readonly clients and ``file:`` URIs
(``node:sqlite`` opens those too); from ``sql-sqlite-wasm/test/Memory.test.ts``,
the export (pyfect's ``backup``) after a failed commit cleanup.

Each test's docstring is the Effect test title. Adapted: "does not create
a missing file: URI with create: false" uses ``?mode=rw`` in the URI,
``node:sqlite``'s spelling of Bun's ``create: false``; "export does not
bypass failed-commit cleanup" backs up to a file and opens it, as
``backup`` is the export of ``node:sqlite`` and pyfect.

Omitted: "create implies readwrite for file: URIs" (Bun's ``create`` /
``readwrite`` options; ``node:sqlite`` has neither); "exports inside
transactions" (Bun's in-memory ``export`` while a transaction holds the
connection); the other titles of these files are sqlite-node's, ported in
``test_sqlite_client.py``, or are the runtime's own (docs/PARITY.md §4).
"""

from pathlib import Path
from typing import Any

import pyfect as fx
from pyfect import reactivity, testing
from pyfect.sql import sqlite
from pyfect.sql.error import ConnectionError, SqlError


def _make(
    filename: str, *, readonly: bool = False
) -> fx.Effect[sqlite.SqliteClientService, SqlError, fx.Scope]:
    config = sqlite.SqliteClientConfig(filename=filename, readonly=readonly)
    return sqlite.make(config).pipe(fx.provide(reactivity.layer))


def _create(filename: str, *statements: str) -> fx.Effect[None, SqlError]:
    def body():
        sql = yield from _make(filename)
        for statement in statements:
            yield from sql.unsafe(statement)

    return fx.scoped(fx.gen(body))


@testing.effect
def test_readonly_clients_reject_writes(tmp_path: Path):
    """readonly clients reject writes"""
    filename = str(tmp_path / "readonly.db")
    yield from _create(filename, "CREATE TABLE test (id INTEGER PRIMARY KEY)")

    sql = yield from _make(filename, readonly=True)
    assert (yield from sql("SELECT * FROM test")) == []
    error = yield from sql("INSERT INTO test DEFAULT VALUES").flip()
    assert isinstance(error, SqlError)
    assert isinstance(error.reason.cause, Exception)
    assert "attempt to write a readonly database" in str(error.reason.cause).lower()

    yield from sql("PRAGMA query_only = ON")
    assert (yield from sql.with_transaction(sql("SELECT * FROM test"))) == []


@testing.effect
def test_opens_file_uris_in_readonly_mode(tmp_path: Path):
    """opens file: URIs in readonly mode"""
    path = tmp_path / "uri.db"
    yield from _create(
        str(path), "CREATE TABLE test (id INTEGER PRIMARY KEY)", "INSERT INTO test (id) VALUES (1)"
    )

    sql = yield from _make(f"{path.as_uri()}?immutable=1", readonly=True)
    assert (yield from sql("SELECT * FROM test")) == [{"id": 1}]


@testing.effect
def test_rejects_writes_to_a_plain_readonly_file_uri(tmp_path: Path):
    """rejects writes to a plain readonly file: URI"""
    path = tmp_path / "uri-readonly.db"
    yield from _create(str(path), "CREATE TABLE test (id INTEGER PRIMARY KEY)")

    sql = yield from _make(path.as_uri(), readonly=True)
    assert (yield from sql("SELECT * FROM test")) == []
    error = yield from sql("INSERT INTO test (id) VALUES (1)").flip()
    assert "attempt to write a readonly database" in str(error.reason.cause).lower()


@testing.effect
def test_does_not_create_a_missing_file_uri_with_create_false(tmp_path: Path):
    """does not create a missing file: URI with create: false"""
    path = tmp_path / "uri-missing.db"
    error = yield from fx.scoped(_make(f"{path.as_uri()}?mode=rw")).flip()
    assert isinstance(error.reason, ConnectionError)
    assert not path.exists()


@testing.effect
def test_export_does_not_bypass_failed_commit_cleanup(tmp_path: Path):
    """export does not bypass failed-commit cleanup"""
    sql = yield from _make(str(tmp_path / "source.db"))
    yield from sql("PRAGMA foreign_keys = ON")
    yield from sql("CREATE TABLE parent (id INTEGER PRIMARY KEY)")
    yield from sql(
        "CREATE TABLE child (parent_id INTEGER REFERENCES parent(id) DEFERRABLE INITIALLY DEFERRED)"
    )

    # Fail only the cleanup ROLLBACK, leaving the deferred constraint failure real.
    conn: Any = yield from fx.scoped(sql.reserve)
    execute_unprepared = conn.execute_unprepared
    fail_rollback = [True]

    def patched(sql_text: str, *args: Any) -> fx.Effect[Any, SqlError]:
        if sql_text == "ROLLBACK" and fail_rollback[0]:
            return fx.fail(
                SqlError(
                    reason=ConnectionError(
                        message="injected rollback failure",
                        operation="rollback",
                        cause=Exception("injected rollback failure"),
                    )
                )
            )
        return execute_unprepared(sql_text, *args)

    conn.execute_unprepared = patched
    failed_commit = yield from sql.with_transaction(sql("INSERT INTO child VALUES (999)")).exit()
    assert isinstance(failed_commit, fx.Failure)

    snapshot = str(tmp_path / "snapshot.db")
    rejected = yield from sql.backup(snapshot).exit()
    assert isinstance(rejected, fx.Failure), "export bypassed the rejected connection"
    assert "cannot be reused after failed commit cleanup" in rejected.cause.pretty().lower()

    fail_rollback[0] = False
    yield from sql.backup(snapshot)
    copy = yield from _make(snapshot)
    assert (yield from copy("SELECT * FROM child")) == []
