"""A database for the SQL encrypted event log server's legacy stores, on
SQLite, PostgreSQL, MySQL or SQL Server, and earlier versions simulated on
it: ``as_065()`` names tables with the legacy key and creates only the
tables 0.6.5 had; ``as_067()`` creates the tables 0.6.6 and 0.6.7 had, and
``Db.alias_as_067`` gives legacy tables as they did, leaving no origin.
"""

from __future__ import annotations

import hashlib
import itertools
import os
from collections.abc import Callable, Generator, Sequence
from pathlib import Path
from typing import Any

import pytest

import pyfect as fx
from pyfect import logger
from pyfect.crypto import digest
from pyfect.eventlog import event_journal as J
from pyfect.eventlog import event_log_server_encrypted as Server
from pyfect.eventlog import sql_event_log_server_encrypted as SqlServer
from pyfect.eventlog._sql_server_encrypted import legacy, tables, upgrade
from pyfect.eventlog._sql_server_encrypted.db import Db
from pyfect.eventlog.event_journal import StoreId
from pyfect.eventlog.event_log_encryption import EncryptedBatch
from pyfect.eventlog.sql_event_log_server_encrypted import (
    LegacyStore,
    LegacyStoreMigrationError,
    LegacyStoreNeedsMigration,
)
from pyfect.persistence._columns import column_bytes
from pyfect.sql import sqlite
from pyfect.sql.client import SqlClient

type Pair = tuple[str, str]

OWNER: Pair = ("Kq9/xT2+bQ==", "main")
"""A base64 public key with a ``/``, which wrote its store under 0.6.5."""
OTHER: Pair = ("Kq9", "xT2+bQ==/main")
"""Another split of the owner's legacy key ``Kq9/xT2+bQ==/main``."""

_namespaces = itertools.count()


def scope_hash(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()[:16]


class LegacyDb:
    """One database, with tables of their own under a fresh prefix."""

    def __init__(self, client: Callable[[], fx.Layer[SqlClient, Any]]) -> None:
        self.client = client
        namespace = f"legacy_{os.getpid()}_{next(_namespaces)}"
        self.prefix = f"{namespace}_events"
        self.remote_id_table = f"{namespace}_remote_id"
        self.migration: SqlServer.LegacyMigration = "never"
        """The servers' ``migrate_legacy_stores``."""

    def storage(self) -> fx.Layer[Server.Storage, Any]:
        return (
            SqlServer.layer_storage(
                entry_table_prefix=self.prefix,
                remote_id_table=self.remote_id_table,
                migrate_legacy_stores=self.migration,
            )
            .pipe(fx.layer.provide(self.client()))
            .pipe(fx.layer.provide(digest.layer_web_crypto))
        )

    def tool[A, E](self, effect: fx.Effect[A, E, SqlClient | digest.Digest]) -> fx.Exit[A, E]:
        """Runs an operator call, outside any server."""
        return fx.run_blocking(
            effect.pipe(fx.provide(digest.layer_web_crypto)).pipe(fx.provide(self.client())).exit()
        )

    def migrate(
        self,
        pair: Pair,
        not_written_by: Sequence[str] = (),
        *,
        without_binding: bool = False,
        taken_from: Pair | None = None,
        through_sequence: int | None = None,
    ) -> fx.Exit[bool, Any]:
        return self.tool(
            SqlServer.migrate_legacy_store(
                *pair,
                not_written_by=not_written_by,
                without_binding=without_binding,
                taken_from=taken_from,
                through_sequence=through_sequence,
                entry_table_prefix=self.prefix,
                remote_id_table=self.remote_id_table,
            )
        )

    def report(
        self, store_ids: Sequence[str], public_keys: Sequence[str] = ()
    ) -> list[LegacyStore]:
        found = self.tool(
            SqlServer.legacy_stores(
                store_ids,
                public_keys=public_keys,
                entry_table_prefix=self.prefix,
                remote_id_table=self.remote_id_table,
            )
        )
        assert isinstance(found, fx.Success)
        return found.value

    def run[A](
        self, body: Callable[[], Generator[Any, Any, A]], logs: list[str] | None = None
    ) -> fx.Exit[A, Any]:
        """``body`` with one storage, as one server process, adding the
        messages of its warnings to ``logs``."""
        effect = fx.scoped(fx.gen(body)).pipe(fx.provide(self.storage()))
        if logs is not None:
            found = logs

            def keep(entry: logger.Options) -> None:
                if entry.log_level == fx.LogLevel.WARN:
                    found.append(str(entry.message[0]))

            effect = effect.pipe(fx.provide(logger.layer([fx.Logger.make(keep)])))
        return fx.run_blocking(effect.exit())

    def tables(self) -> set[str]:
        """The names of the tables under this database's prefixes."""

        def body():
            sql = (yield from SqlClient()).without_transforms()
            rows = yield from sql.on_dialect_or_else(
                pg=lambda: sql("SELECT tablename AS name FROM pg_tables"),
                mysql=lambda: sql(
                    "SELECT table_name AS name FROM information_schema.tables "
                    "WHERE table_schema = DATABASE()"
                ),
                mssql=lambda: sql("SELECT name FROM sys.tables"),
                or_else=lambda: sql("SELECT name FROM sqlite_master WHERE type = 'table'"),
            )
            names = {str(row["name"]) for row in rows}
            return {n for n in names if n.lower().startswith(self.prefix.split("_events")[0])}

        found = self.tool(fx.gen(body))
        assert isinstance(found, fx.Success)
        return found.value

    def start(self) -> None:
        """Starts a server once, as the first start after an upgrade does."""

        def body():
            yield from Server.Storage()

        assert isinstance(self.run(body), fx.Success)

    def bind(self, public_key: str) -> None:
        """Authenticates ``public_key`` once, as a server does."""

        def body():
            storage = yield from Server.Storage()
            yield from storage.get_or_create_session_auth_binding(public_key, bytes(32))

        assert isinstance(self.run(body), fx.Success)

    def write(self, pair: Pair, tag: str) -> None:
        def body():
            storage = yield from Server.Storage()
            yield from storage.write(pair[0], StoreId(pair[1]), [batch(tag)])

        assert isinstance(self.run(body), fx.Success)

    def read(self, pair: Pair, logs: list[str] | None = None) -> list[str]:
        """The tags of the pair's batches; raises the store's refusal."""
        found = self.run(lambda: read_tags(pair), logs)
        if isinstance(found, fx.Failure):
            raise found.cause.squash()  # pyright: ignore[reportGeneralTypeIssues]
        return found.value

    def alias_as_067(self, pair: Pair) -> None:
        """Gives ``pair`` its legacy tables as 0.6.6 or 0.6.7 did."""

        def body():
            sql = (yield from SqlClient()).without_transforms()
            yield from sql(
                "INSERT INTO {} (legacy_scope, scope) VALUES ({}, {})",
                sql.identifier(f"{self.prefix}_scope_aliases"),
                scope_hash(legacy.legacy_key(*pair)),
                scope_hash(legacy.scope_key(*pair)),
            )

        assert isinstance(self.tool(fx.gen(body)), fx.Success)


def batch(tag: str) -> EncryptedBatch:
    return EncryptedBatch(
        entry_ids=(J.make_entry_id_unsafe(),), iv=bytes(12), encrypted_batch=tag.encode()
    )


def read_tags(pair: Pair) -> Generator[Any, Any, list[str]]:
    storage = yield from Server.Storage()
    latest = yield from storage.latest_sequence(pair[0], StoreId(pair[1]))
    if latest is None:
        return []
    # Sequences can start past 1, as in tables taken back from a pair.
    batches = yield from (
        storage.changes(pair[0], StoreId(pair[1]), 1)
        .take_until(lambda b: b.sequence + len(b.entry_ids) > latest)
        .run_collect()
    )
    return [b.encrypted_batch.decode() for b in batches]


def sqlite_db(path: Path) -> LegacyDb:
    return LegacyDb(lambda: sqlite.layer(sqlite.SqliteClientConfig(filename=str(path))))


def any_db(request: pytest.FixtureRequest, tmp_path: Path) -> LegacyDb:
    """A database: a SQLite file, or the session's PostgreSQL server or its
    MySQL or SQL Server container (skipped without one)."""
    match request.param:
        case "SQLite":
            return sqlite_db(tmp_path / "log.db")
        case "pg":
            pytest.importorskip("psycopg")
            from pyfect.sql import pg

            from ._postgres import PgServer

            server: PgServer = request.getfixturevalue("pg_server")
            return LegacyDb(lambda: pg.layer(pg.PgPoolConfig(url=server.url)))
        case "mssql":
            pytest.importorskip("pytds")
            from pyfect.sql import mssql

            from ._mssql import MssqlServer

            mssql_server: MssqlServer = request.getfixturevalue("mssql_server")
            return LegacyDb(lambda: mssql.layer(mssql_server.config()))
        case _:
            pytest.importorskip("asyncmy")
            from pyfect.sql import mysql

            from ._mysql import MysqlServer

            mysql_server: MysqlServer = request.getfixturevalue("mysql_server")
            return LegacyDb(lambda: mysql.layer(mysql.MysqlClientConfig(url=mysql_server.url)))


DIALECTS = ["SQLite", "pg", "mysql2", "mssql"]


def _remote_id(db: Db, remote_id_table: str) -> Generator[Any, Any, J.RemoteId]:
    """The remote id as earlier versions read or made it."""
    table = db.sql.identifier(remote_id_table)
    rows = yield from db.sql("SELECT remote_id FROM {}", table)
    if rows:
        return J.RemoteId(column_bytes(rows[0]["remote_id"]))
    created = J.make_remote_id_unsafe()
    yield from db.sql("INSERT INTO {} (remote_id) VALUES ({})", table, created)
    return created


def _prepare_065(db: Db, remote_id_table: str) -> fx.Effect[J.RemoteId, Any]:
    def body():
        yield from tables.create_065_tables(db.sql, db.prefix, remote_id_table)
        return (yield from _remote_id(db, remote_id_table))

    return fx.gen(body)


def _prepare_067(db: Db, remote_id_table: str) -> fx.Effect[J.RemoteId, Any]:
    def body():
        yield from tables.create_065_tables(db.sql, db.prefix, remote_id_table)
        yield from tables.create_alias_tables(db.sql, db.prefix)
        return (yield from _remote_id(db, remote_id_table))

    return fx.gen(body)


class Earlier:
    """A context in which the storage behaves as an earlier version as far
    as its tables go."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch, version: str) -> None:
        self._monkeypatch = monkeypatch
        self._version = version

    def __enter__(self) -> None:
        if self._version == "0.6.5":
            self._monkeypatch.setattr(legacy, "scope_key", legacy.legacy_key)
            self._monkeypatch.setattr(upgrade, "prepare", _prepare_065)
        else:
            self._monkeypatch.setattr(upgrade, "prepare", _prepare_067)

    def __exit__(self, *_: object) -> None:
        self._monkeypatch.undo()


def refusal(db: LegacyDb, pair: Pair) -> LegacyStoreNeedsMigration:
    with pytest.raises(LegacyStoreNeedsMigration) as raised:
        db.read(pair)
    return raised.value


def migration_refused(found: fx.Exit[bool, Any]) -> str:
    assert isinstance(found, fx.Failure)
    error = found.cause.squash()
    assert isinstance(error, LegacyStoreMigrationError)
    return error.message


__all__ = [
    "DIALECTS",
    "OTHER",
    "OWNER",
    "Earlier",
    "LegacyDb",
    "Pair",
    "any_db",
    "batch",
    "migration_refused",
    "read_tags",
    "refusal",
    "scope_hash",
    "sqlite_db",
]
