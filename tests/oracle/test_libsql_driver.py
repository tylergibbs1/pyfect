"""(pyfect) The libSQL driver's own behavior (``pyfect.sql.libsql``): URLs parsed
when the config is made, values in and out of a local file and a remote
server, and failures classified from SQLite's codes as in Effect."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import pytest

import pyfect as fx
from pyfect import reactivity, redacted, testing
from pyfect.sql import _loop, libsql
from pyfect.sql.error import ConstraintError, SqlError, UnknownError
from pyfect.sql.libsql import LibsqlClientConfig, LibsqlError
from pyfect.sql.libsql._targets import LocalTarget, RemoteTarget

from ._libsql import LibsqlServer


@pytest.mark.parametrize(
    ("url", "target"),
    [
        (":memory:", LocalTarget("file::memory:", uri=True, in_memory=True)),
        (
            "file::memory:?cache=shared",
            LocalTarget("file::memory:?cache=shared", uri=True, in_memory=True),
        ),
        ("file:local.db", LocalTarget("local.db", uri=False, in_memory=False)),
        ("file:///data/my%20app.db", LocalTarget("/data/my app.db", uri=False, in_memory=False)),
        ("libsql://db.turso.io", RemoteTarget("https://db.turso.io", None)),
        ("libsql://localhost:8080?tls=0", RemoteTarget("http://localhost:8080", None)),
        ("http://localhost:8080/", RemoteTarget("http://localhost:8080", None)),
        ("wss://db.turso.io/base", RemoteTarget("https://db.turso.io/base", None)),
        ("https://db.turso.io?authToken=abc", RemoteTarget("https://db.turso.io", "abc")),
    ],
)
def test_urls_name_their_database(url: str, target: object):
    """(pyfect) a URL names a local file, an in-memory database or a server"""
    assert LibsqlClientConfig(url=url).target == target


def test_auth_token_is_sent_unless_the_url_has_one():
    """(pyfect) auth_token is the server's token unless the URL has one"""
    config = LibsqlClientConfig(url="libsql://db.turso.io", auth_token=redacted.make("t"))
    assert config.target == RemoteTarget("https://db.turso.io", "t")


@pytest.mark.parametrize(
    ("url", "message"),
    [
        ("local.db", "no scheme"),
        ("postgres://db", "supports only"),
        ("libsql://db.turso.io?tls=0", "explicit port"),
        ("http://db?tls=1", "cannot opt into TLS"),
        ("https://db?tls=0", "cannot opt out of TLS"),
        ("https://db?tls=yes", "Unknown value"),
        ("https://db?mode=ro", "Unsupported URL query parameter"),
        ("https://user:pw@db", "Basic authentication"),
        ("https://db#frag", "fragments"),
        ("file://remote/x.db", "Invalid host"),
        (":memory:?cache=other", "no scheme"),
        ("file::memory:?cache=other", "Unknown value"),
    ],
)
def test_urls_libsql_refuses_fail_when_the_config_is_made(url: str, message: str):
    """(pyfect) URLs @libsql/client refuses fail when the config is made"""
    with pytest.raises(ValueError, match=message):
        LibsqlClientConfig(url=url)


def _client(url: str) -> fx.Effect[libsql.LibsqlClientService, Any, fx.Scope]:
    return libsql.make(LibsqlClientConfig(url=url)).pipe(fx.provide(reactivity.layer))


_VALUES = (None, 42, 2**62, 1.5, "text", b"\x00\xffblob")


def _round_trip(url: str):
    sql = yield from _client(url)
    yield from sql("DROP TABLE IF EXISTS kinds")
    yield from sql("CREATE TABLE kinds (v)")
    for value in (*_VALUES, True):
        yield from sql("INSERT INTO kinds (v) VALUES ({})", value)
    rows = yield from sql("SELECT v FROM kinds ORDER BY rowid").values
    assert rows == [(value,) for value in (*_VALUES, 1)]
    too_big = yield from sql("INSERT INTO kinds (v) VALUES ({})", 2**63).flip()
    assert isinstance(too_big.reason, UnknownError)
    assert isinstance(too_big.reason.cause, OverflowError)
    yield from sql("DROP TABLE kinds")


@testing.effect
def test_values_round_trip_through_a_local_file(tmp_path: Path):
    """(pyfect) values round trip through a local file"""
    yield from _round_trip(f"file:{tmp_path / 'kinds.db'}")


@testing.effect
def test_values_round_trip_through_a_remote_server(libsql_server: LibsqlServer):
    """(pyfect) values round trip through a remote server"""
    yield from _round_trip(libsql_server.url)


def _unique_violation(url: str):
    sql = yield from _client(url)
    yield from sql("DROP TABLE IF EXISTS uniq")
    yield from sql("CREATE TABLE uniq (id INTEGER PRIMARY KEY)")
    yield from sql("INSERT INTO uniq (id) VALUES (1)")
    error = yield from sql("INSERT INTO uniq (id) VALUES (1)").flip()
    yield from sql("DROP TABLE uniq")
    return error


@testing.effect
def test_a_unique_violation_is_a_constraint_error_locally(tmp_path: Path):
    """(pyfect) a unique violation is a ConstraintError locally, as in Effect"""
    error = yield from _unique_violation(f"file:{tmp_path / 'u.db'}")
    assert isinstance(error, SqlError)
    assert isinstance(error.reason, ConstraintError)
    cause = error.reason.cause
    assert isinstance(cause, LibsqlError)
    assert (cause.code, cause.extended_code, cause.raw_code) == (
        "SQLITE_CONSTRAINT",
        "SQLITE_CONSTRAINT_PRIMARYKEY",
        1555,
    )


@testing.effect
def test_a_unique_violation_is_a_constraint_error_remotely(libsql_server: LibsqlServer):
    """(pyfect) a unique violation is a ConstraintError remotely, as in Effect"""
    error = yield from _unique_violation(libsql_server.url)
    assert isinstance(error.reason, ConstraintError)
    assert isinstance(error.reason.cause, LibsqlError)
    assert error.reason.cause.code == "SQLITE_CONSTRAINT"


@testing.effect
def test_a_file_database_keeps_what_a_transaction_committed(tmp_path: Path):
    """(pyfect) a file database keeps what a transaction committed"""
    url = f"file:{tmp_path / 'kept.db'}"

    def write():
        sql = yield from _client(url)
        yield from sql("CREATE TABLE kept (v INTEGER)")
        yield from sql.with_transaction(sql("INSERT INTO kept VALUES (1)"))

    def read():
        sql = yield from _client(url)
        return (yield from sql("SELECT v FROM kept"))

    yield from fx.scoped(fx.gen(write))
    assert (yield from fx.scoped(fx.gen(read))) == [{"v": 1}]


@testing.effect
def test_an_in_memory_database_has_one_connection_a_transaction_holds():
    """(pyfect) an in-memory database has one connection, which a transaction holds"""
    sql = yield from _client(":memory:")
    sdk = sql.sdk

    def outside():
        return sdk.execute("SELECT 1", ())

    def body():
        return _loop.call(
            outside, lambda e: SqlError(reason=UnknownError(cause=e)), waits_for="work"
        ).flip()

    error = yield from sql.with_transaction(fx.suspend(body))
    assert isinstance(error.reason.cause, LibsqlError)
    assert error.reason.cause.code == "TRANSACTION_ACTIVE"
    assert (yield from sql("SELECT 1 AS one")) == [{"one": 1}]


@testing.effect
def test_a_local_database_that_cannot_be_opened_is_a_defect(tmp_path: Path):
    """(pyfect) a local database that cannot be opened is a defect"""
    exit_ = yield from _client(f"file:{tmp_path / 'missing' / 'x.db'}").exit()
    assert isinstance(exit_, fx.Failure)
    (defect,) = exit_.cause.defects
    assert isinstance(defect, SqlError)
    assert isinstance(defect.reason.cause, LibsqlError)
    assert defect.reason.cause.code == "SQLITE_CANTOPEN"


_SLOW = (
    "WITH RECURSIVE c(x) AS (SELECT 1 UNION ALL SELECT x + 1 FROM c WHERE x < 8000000) "
    "SELECT count(*) FROM c"
)


@testing.live(timeout=30)
def test_an_interrupted_remote_statement_still_rolls_its_transaction_back(
    libsql_server: LibsqlServer,
):
    """(pyfect) interrupting a remote transaction mid-statement rolls it back on the server"""
    sql = yield from _client(libsql_server.url)
    yield from sql("DROP TABLE IF EXISTS interrupted")
    yield from sql("CREATE TABLE interrupted (v INTEGER)")
    fiber = yield from sql.with_transaction(
        sql("INSERT INTO interrupted VALUES (1)").and_then(sql(_SLOW))
    ).fork()
    yield from fx.sleep(0.2)
    yield from fiber.interrupt()
    yield from fiber.await_exit()
    # The server's transaction is over, so its write lock does not hold
    # up the next one until the abandoned stream expires.
    started = time.monotonic()
    yield from sql.with_transaction(sql("INSERT INTO interrupted VALUES (2)"))
    assert time.monotonic() - started < 2.5
    assert (yield from sql("SELECT v FROM interrupted")) == [{"v": 2}]
    yield from sql("DROP TABLE interrupted")
