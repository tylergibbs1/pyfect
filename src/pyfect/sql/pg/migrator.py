"""Migrations for PostgreSQL (Effect's ``@effect/sql-pg`` ``PgMigrator``):
``Migrator``'s runner, dumping the schema with ``pg_dump``.

``pg_dump`` connects with the client's own libpq parameters (the URL and
explicit fields, socket, user, database, ``application_name``,
``options``, TLS, connect timeout); the password goes through
``PGPASSWORD`` and nothing else of the environment but ``PATH``. A dump
that fails is logged, as for every driver.
"""

from __future__ import annotations

import math
import os
import re
from typing import Never

from psycopg.conninfo import make_conninfo

from pyfect._all import all as all_effects
from pyfect._core import Effect
from pyfect.effect import fail, gen
from pyfect.file_system import FileSystem
from pyfect.layer import Layer
from pyfect.layer import effect_discard as layer_effect_discard
from pyfect.path import Path
from pyfect.process import ChildProcessSpawner
from pyfect.process import make as make_command
from pyfect.sql.client import SqlClient
from pyfect.sql.error import SqlError
from pyfect.sql.migrator import (
    Loader,
    MigrationError,
    Runner,
    from_record,
    make,
)
from pyfect.sql.migrator_file_system import from_file_system
from pyfect.sql.pg._resolve import ResolvedConfig, resolve, resolve_password
from pyfect.sql.pg.client import PgClient

_COMMENT = re.compile(r"^--.*$", re.MULTILINE)
_SET = re.compile(r"^SET .*$", re.MULTILINE)
_SELECT_CATALOG = re.compile(r"^SELECT pg_catalog\..*$", re.MULTILINE)
_BLANK_LINES = re.compile(r"\n{2,}")

type DumpServices = PgClient | ChildProcessSpawner | FileSystem | Path


def _clean(dump: str) -> str:
    dump = _COMMENT.sub("", dump)
    dump = _SET.sub("", dump)
    dump = _SELECT_CATALOG.sub("", dump)
    return _BLANK_LINES.sub("\n\n", dump).strip()


def _conninfo(resolved: ResolvedConfig) -> str:
    params = dict(resolved.params)
    params.pop("client_encoding", None)
    if math.isfinite(resolved.connect_timeout):
        params["connect_timeout"] = str(max(1, math.ceil(resolved.connect_timeout)))
    return make_conninfo(**params)


def _pg_dump(
    conninfo: str, password: str | None, args: list[str]
) -> Effect[str, Exception, ChildProcessSpawner]:
    env: dict[str, str | None] = {"PATH": os.environ.get("PATH")}
    if password is not None:
        env["PGPASSWORD"] = password
    command = make_command(
        "pg_dump",
        [*args, "--no-owner", "--no-privileges", "--no-password", f"--dbname={conninfo}"],
        env=env,
        extend_env=False,
    )
    return ChildProcessSpawner().flat_map(lambda spawner: spawner.string(command)).map(_clean)


def _dump_all(table: str) -> Effect[str, Exception, PgClient | ChildProcessSpawner]:
    def body():
        client = yield from PgClient()
        resolved = yield from resolve(client.config)
        password = yield from resolve_password(resolved.password)
        conninfo = _conninfo(resolved)
        schema, migrations = yield from all_effects(
            _pg_dump(conninfo, password, ["--schema-only"]),
            _pg_dump(conninfo, password, ["--column-inserts", "--data-only", f"--table={table}"]),
            concurrency=2,
        )
        return schema + "\n\n" + migrations

    return gen(body)


def dump_schema(path: str, table: str) -> Effect[None, MigrationError, DumpServices]:
    """Write the schema and the migrations table's rows to ``path``."""

    def body():
        fs = yield from FileSystem()
        paths = yield from Path()
        dump = yield from _dump_all(table)
        yield from fs.make_directory(paths.dirname(path), recursive=True)
        yield from fs.write_file_string(path, dump)

    def failed(error: Exception) -> Effect[Never, MigrationError]:
        message = getattr(error, "message", None) or str(error)
        return fail(MigrationError(kind="Failed", message=str(message), cause=error))

    written: Effect[None, Exception, DumpServices] = gen(body)
    return written.catch_all(failed)


run: Runner[DumpServices] = make(dump_schema)
"""Run the new migrations of ``loader`` (see ``migrator.make``); with a
``schema_directory``, dump the schema there with ``pg_dump``."""


def layer[R = Never](
    *,
    loader: Loader[R],
    schema_directory: str | None = None,
    table: str = "effect_sql_migrations",
) -> Layer[Never, MigrationError | SqlError, SqlClient | DumpServices | R]:
    """Runs the migrations when built."""
    return layer_effect_discard(run(loader=loader, schema_directory=schema_directory, table=table))


__all__ = [
    "DumpServices",
    "Loader",
    "MigrationError",
    "SqlError",
    "dump_schema",
    "from_file_system",
    "from_record",
    "layer",
    "run",
]
