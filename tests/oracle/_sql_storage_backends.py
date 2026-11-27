"""The backends the ``SqlMessageStorage.integration.test.ts`` ports run on:
SQLite in a fresh file, and the throwaway PostgreSQL, MySQL and SQL Server
servers (``_postgres``, ``_mysql``, ``_mssql``; those cases skip without
one) under a fresh table prefix. ``run`` migrates the prefix's tables and
hands the test body its storage and client."""

from __future__ import annotations

from collections.abc import Callable, Generator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from _db_names import fresh_name

import pyfect as fx
from pyfect import reactivity
from pyfect.cluster import snowflake
from pyfect.cluster import sql_message_storage as SqlMessageStorage
from pyfect.cluster.message_storage import EncodedStorage, MessageStorageService
from pyfect.sql.client import SqlClient, SqlClientService

from ._sqlite import make_client


def fresh_prefix(name: str) -> str:
    """A table prefix no other test of this run uses."""
    return fresh_name(name)


type ClientMaker = Callable[[], fx.Effect[SqlClientService, Any, fx.Scope]]


@dataclass(frozen=True)
class Backend:
    name: str
    client: ClientMaker
    prefix: str


@dataclass(frozen=True)
class Env:
    storage: MessageStorageService
    sql: SqlClientService
    prefix: str

    @property
    def messages(self) -> Any:
        return self.sql.identifier(f"{self.prefix}_messages")

    def encoded(self) -> fx.Effect[EncodedStorage]:
        return SqlMessageStorage.make_encoded_storage(prefix=self.prefix).pipe(
            fx.provide_service(SqlClient, self.sql)
        )


def pg(pg_server: Any) -> fx.Effect[SqlClientService, Any, fx.Scope]:
    pytest.importorskip("psycopg")
    from pyfect.sql import pg

    return pg.make(pg.PgPoolConfig(url=pg_server.url)).pipe(fx.provide(reactivity.layer))


def mssql(server: Any) -> fx.Effect[SqlClientService, Any, fx.Scope]:
    from pyfect.sql import mssql

    return mssql.make(server.config()).pipe(fx.provide(reactivity.layer))


def mysql(server: Any) -> fx.Effect[SqlClientService, Any, fx.Scope]:
    from pyfect.sql import mysql

    return mysql.make(mysql.MysqlClientConfig(url=server.url)).pipe(fx.provide(reactivity.layer))


BACKENDS = ("sqlite", "pg", "mysql", "mssql")


def make_backend(request: pytest.FixtureRequest, tmp_path: Path) -> Backend:
    """The backend of a fixture parametrized over ``BACKENDS``."""
    if request.param == "sqlite":
        return Backend("sqlite", lambda: make_client(tmp_path), "cluster")
    if request.param == "mssql":
        pytest.importorskip("pytds")
        server = request.getfixturevalue("mssql_server")
        return Backend("mssql", lambda: mssql(server), fresh_prefix("msg"))
    if request.param == "mysql":
        pytest.importorskip("asyncmy")
        server = request.getfixturevalue("mysql_server")
        return Backend("mysql", lambda: mysql(server), fresh_prefix("msg"))
    pytest.importorskip("psycopg")
    server = request.getfixturevalue("pg_server")
    return Backend("pg", lambda: pg(server), fresh_prefix("msg"))


def run(
    backend: Backend, body: Callable[[Env], Generator[fx.Effect[Any, Any, Any], Any]]
) -> fx.Effect[None, Any, Any]:
    def run() -> Generator[fx.Effect[Any, Any, Any], Any]:
        sql = yield from backend.client()
        storage = yield from SqlMessageStorage.make(prefix=backend.prefix).pipe(
            fx.provide_service(SqlClient, sql)
        )
        yield from fx.gen(lambda: body(Env(storage, sql, backend.prefix)))

    return fx.gen(run).pipe(fx.provide(snowflake.layer_generator))
