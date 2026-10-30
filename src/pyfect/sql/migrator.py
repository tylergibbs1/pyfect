"""Database migrations (Effect's ``effect/sql/Migrator``).

A loader lists the migrations as ``(id, name, load)``: ``load`` succeeds
with the migration, an effect needing ``SqlClient`` (or a module whose
``default`` is one). ``make()`` gives the function that runs the
migrations newer than the latest one recorded in the migrations table, in
one transaction (except on ClickHouse), recording each::

    run = migrator.make()
    yield from run(loader=migrator.from_record({"1_create_users": create_users}))

Two runners at once: the second finds the rows already recorded and
returns ``[]``.
"""
# pyright: reportPrivateUsage=false

from __future__ import annotations

import importlib.util
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal, Never, Protocol, cast

from pyfect import schema as S
from pyfect._core import Effect, _MatchCause, _Suspend
from pyfect.effect import fail, succeed, void
from pyfect.file_system import FileSystem
from pyfect.logger._log import log_debug, log_info
from pyfect.path import Path
from pyfect.sql.client import SqlClient, SqlClientService
from pyfect.sql.error import ConstraintError, SqlError, UniqueViolation
from pyfect.sql.statement import Fragment
from pyfect.sql.statement._segments import literal_unsafe

type MigrationKind = Literal["BadState", "ImportError", "Failed", "Duplicates", "Locked"]


class MigrationError(S.TaggedError, tag="MigrationError"):
    """A migration run failed; ``kind`` says how."""

    kind: MigrationKind = S.field(
        S.Literals("BadState", "ImportError", "Failed", "Duplicates", "Locked")
    )
    message: str = S.field(S.String)
    cause: object = S.field(S.Unknown, default=None)


type Migration = Effect[object, object, SqlClient]
"""A migration: an effect run with the client."""

type ResolvedMigration = tuple[int, str, Effect[object, object, SqlClient]]
"""A migration's id, name, and the effect that loads it."""

type Loader[R = Never] = Effect[Sequence[ResolvedMigration], MigrationError, R]


@dataclass(frozen=True, slots=True)
class MigrationRecord:
    """A row of the migrations table."""

    id: int
    name: str
    created_at: object


type DumpSchema[RD] = Callable[[str, str], Effect[None, MigrationError, RD]]
"""Writes the schema to a path, given the migrations table."""


class Runner[RD](Protocol):
    """Runs the new migrations of ``loader``; succeeds with their ids and
    names."""

    def __call__[R2 = Never](
        self,
        *,
        loader: Loader[R2],
        schema_directory: str | None = None,
        table: str = "effect_sql_migrations",
    ) -> Effect[list[tuple[int, str]], MigrationError | SqlError, SqlClient | RD | R2]: ...


def _nstring(text: str) -> Fragment:
    """``text`` as a SQL Server ``N'...'`` string literal, quotes doubled."""
    return Fragment((literal_unsafe("N'" + text.replace("'", "''") + "'"),))


def _ensure_table(sql: SqlClientService, table: str) -> Effect[object, SqlError]:
    name = sql.identifier(table)
    return sql.on_dialect_or_else(
        mssql=lambda: sql(
            "IF OBJECT_ID({literal}, N'U') IS NULL\n"
            "  CREATE TABLE {table} (\n"
            "    migration_id INT NOT NULL PRIMARY KEY,\n"
            "    name VARCHAR(255) NOT NULL,\n"
            "    created_at DATETIME NOT NULL DEFAULT GETDATE()\n"
            "  )",
            literal=_nstring(table),
            table=name,
        ),
        mysql=lambda: sql(
            "CREATE TABLE IF NOT EXISTS {} (\n"
            "  migration_id INTEGER UNSIGNED NOT NULL,\n"
            "  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,\n"
            "  name VARCHAR(255) NOT NULL,\n"
            "  PRIMARY KEY (migration_id)\n"
            ")",
            name,
        ),
        # sqlite's ``PRIMARY KEY NOT NULL`` is a syntax error here
        clickhouse=lambda: sql(
            "CREATE TABLE IF NOT EXISTS {} (\n"
            "  migration_id Int32,\n"
            "  created_at DateTime DEFAULT now(),\n"
            "  name String\n"
            ") ENGINE = MergeTree\n"
            "ORDER BY migration_id",
            name,
        ),
        pg=lambda: _ensure_table_pg(sql, table),
        or_else=lambda: sql(
            "CREATE TABLE IF NOT EXISTS {} (\n"
            "  migration_id integer PRIMARY KEY NOT NULL,\n"
            "  created_at datetime NOT NULL DEFAULT current_timestamp,\n"
            "  name VARCHAR(255) NOT NULL\n"
            ")",
            name,
        ),
    )


def _table_exists(sql: SqlClientService, table: str) -> Effect[bool, SqlError]:
    # Match query quoting: to_regclass folds unquoted names to lowercase.
    quoted = sql("{}", sql.identifier(table)).compile(True)[0]
    found = sql("SELECT 1 AS found WHERE to_regclass({}) IS NOT NULL", quoted).without_transform
    return found.map(lambda rows: len(rows) > 0)


def _ensure_table_pg(sql: SqlClientService, table: str) -> Effect[object, SqlError]:
    create = sql(
        "CREATE TABLE {} (\n"
        "  migration_id integer primary key,\n"
        "  created_at timestamp with time zone not null default now(),\n"
        "  name text not null\n"
        ")",
        sql.identifier(table),
    )

    def retry_check(error: SqlError) -> Effect[None, SqlError]:
        return _table_exists(sql, table).flat_map(lambda exists: void if exists else fail(error))

    return _table_exists(sql, table).flat_map(
        lambda exists: void if exists else create.as_void().catch_all(retry_check)
    )


def _is_constraint_conflict(error: SqlError) -> bool:
    return isinstance(error.reason, ConstraintError | UniqueViolation)


def _load_migration(resolved: ResolvedMigration) -> Effect[Migration, MigrationError]:
    id_, name, load = resolved

    def import_failed(defect: BaseException) -> Effect[Never, MigrationError]:
        return fail(
            MigrationError(
                kind="ImportError",
                message=f'Could not import migration "{id_}_{name}"\n\n{defect!r}',
            )
        )

    def resolve(loaded: object) -> Effect[Migration, MigrationError]:
        if isinstance(loaded, Effect):
            return succeed(cast("Migration", loaded))
        default = getattr(loaded, "default", None)
        if default is None:
            return fail(
                MigrationError(
                    kind="ImportError",
                    message=f'Default export not found for migration "{id_}_{name}"',
                )
            )
        if not isinstance(default, Effect):
            return fail(
                MigrationError(
                    kind="ImportError",
                    message=f'Default export was not an Effect for migration "{id_}_{name}"',
                )
            )
        return succeed(cast("Migration", default))

    loaded = load.catch_defect(import_failed).flat_map(resolve)
    return cast("Effect[Migration, MigrationError]", loaded)


def make[RD = Never](dump_schema: DumpSchema[RD] | None = None) -> Runner[RD]:
    """The migration runner: ``run(loader=, schema_directory=None,
    table="effect_sql_migrations")`` runs the new migrations and succeeds
    with their ids and names. With ``schema_directory`` and migrations run,
    ``dump_schema`` writes ``<schema_directory>/_schema.sql``."""

    def run[R2 = Never](
        *,
        loader: Loader[R2],
        schema_directory: str | None = None,
        table: str = "effect_sql_migrations",
    ) -> Effect[list[tuple[int, str]], MigrationError | SqlError, SqlClient | RD | R2]:
        return SqlClient().flat_map(
            lambda sql: _run(sql, dump_schema, loader, schema_directory, table)
        )

    return run


def _run(
    sql: SqlClientService,
    dump_schema: DumpSchema[Any] | None,
    loader: Loader[Any],
    schema_directory: str | None,
    table: str,
) -> Effect[list[tuple[int, str]], MigrationError | SqlError, Any]:
    name = sql.identifier(table)

    def insert_migrations(rows: Sequence[tuple[int, str]]) -> Effect[object, SqlError]:
        values = [{"migration_id": id_, "name": n} for id_, n in rows]
        return sql("INSERT INTO {} {}", name, sql.insert(values)).without_transform

    def to_record(rows: Sequence[Mapping[str, object]]) -> MigrationRecord | None:
        if not rows:
            return None
        row = rows[0]
        return MigrationRecord(
            cast("int", row["migration_id"]), cast("str", row["name"]), row["created_at"]
        )

    latest: Effect[MigrationRecord | None, SqlError] = sql(
        "SELECT migration_id, name, created_at FROM {} ORDER BY migration_id DESC", name
    ).without_transform.map(to_record)

    def run_migration(
        id_: int, migration_name: str, migration: Migration
    ) -> Effect[object, Any, Any]:
        return migration.map_error(
            lambda error: MigrationError(
                cause=error, kind="Failed", message=f'Migration "{id_}_{migration_name}" failed'
            )
        )

    # BEGIN is still experimental on clickhouse
    transactional = sql.on_dialect_or_else(clickhouse=lambda: False, or_else=lambda: True)

    def body() -> Effect[list[tuple[int, str]], Any, Any]:
        lock: Effect[object, SqlError] = sql.on_dialect_or_else(
            pg=lambda: sql("LOCK TABLE {} IN ACCESS EXCLUSIVE MODE", name), or_else=lambda: void
        )

        def with_current(
            latest_id: int, current: Sequence[ResolvedMigration]
        ) -> Effect[list[tuple[int, str]], Any, Any]:
            if len({id_ for id_, _, _ in current}) != len(current):
                return fail(
                    MigrationError(kind="Duplicates", message="Found duplicate migration id's")
                )
            pending = [resolved for resolved in current if resolved[0] > latest_id]
            required: list[tuple[int, str, Migration]] = []

            def load_all() -> Effect[None, MigrationError]:
                step: Effect[None, MigrationError] = void
                for resolved in pending:
                    step = step.and_then(
                        _load_migration(resolved).map(
                            lambda m, r=resolved: required.append((r[0], r[1], m))
                        )
                    )
                return step

            def record_up_front(_: object) -> Effect[object, Any]:
                # rows recorded up front are only rolled back inside a transaction
                if not transactional or not required:
                    return void

                def locked(error: SqlError) -> MigrationError | SqlError:
                    if _is_constraint_conflict(error):
                        return MigrationError(kind="Locked", message="Migrations already running")
                    return error

                return insert_migrations([(i, n) for i, n, _ in required]).map_error(locked)

            def run_all(_: object) -> Effect[object, Any, Any]:
                step: Effect[object, Any, Any] = void
                for id_, migration_name, migration in required:
                    one = (
                        log_debug("Running migration")
                        .and_then(run_migration(id_, migration_name, migration))
                        .and_then(
                            void if transactional else insert_migrations([(id_, migration_name)])
                        )
                        .annotate_logs("migration_id", str(id_))
                        .annotate_logs("migration_name", migration_name)
                        .with_span(f"Migrator {id_}_{migration_name}")
                    )
                    step = step.and_then(one)
                return step

            def log_complete(record: MigrationRecord | None) -> Effect[None]:
                done = log_debug("Migrations complete")
                if record is None:
                    return done
                return done.annotate_logs("latest_migration_id", str(record.id)).annotate_logs(
                    "latest_migration_name", record.name
                )

            return (
                load_all()
                .flat_map(record_up_front)
                .flat_map(run_all)
                .and_then(latest.flat_map(log_complete))
                .map(lambda _: [(i, n) for i, n, _ in required])
            )

        return lock.and_then(
            latest.flat_map(
                lambda record: loader.flat_map(
                    lambda current: with_current(0 if record is None else record.id, current)
                )
            )
        )

    running = _Suspend(body)
    migrations = sql.with_transaction(running) if transactional else running

    def unlocked(error: object) -> Effect[list[tuple[int, str]], Any]:
        if isinstance(error, MigrationError) and error.kind == "Locked":
            return log_debug(error.message).as_([])
        return fail(error)

    completed = migrations.catch_if(lambda e: isinstance(e, MigrationError), unlocked)

    def dump(done: list[tuple[int, str]]) -> Effect[list[tuple[int, str]], Any, Any]:
        if dump_schema is None or not schema_directory or not done:
            return succeed(done)
        written = dump_schema(f"{schema_directory}/_schema.sql", table)
        return _MatchCause(
            written,
            lambda cause: log_info("Could not dump schema", cause),
            lambda _: void,
        ).as_(done)

    return _ensure_table(sql, table).and_then(completed).flat_map(dump)


_RECORD_KEY = re.compile(r"^(\d+)_(.+)$")
_FILE_NAME = re.compile(r"^(?:.*/)?(\d+)_([^.]+)\.py$")


def _sorted(migrations: list[ResolvedMigration]) -> list[ResolvedMigration]:
    return sorted(migrations, key=lambda m: m[0])


def from_record(migrations: Mapping[str, Migration]) -> Loader:
    """Migrations keyed ``"<id>_<name>"``; other keys are skipped."""
    found: list[ResolvedMigration] = []
    for key, migration in migrations.items():
        match = _RECORD_KEY.match(key)
        if match is not None:
            found.append((int(match[1]), match[2], succeed(migration)))
    return succeed(_sorted(found))


def _import(path: str, module_name: str) -> object:
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot import {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def from_file_system(directory: str) -> Loader[FileSystem | Path]:
    """The ``<id>_<name>.py`` modules of ``directory``; each migration is
    the module's ``default``."""

    def read(fs: Any, path: Any) -> Loader:
        def failed(cause: object) -> MigrationError:
            return MigrationError(
                kind="Failed", cause=cause, message="Failed to read migrations directory"
            )

        def resolve(files: Sequence[str]) -> list[ResolvedMigration]:
            found: list[ResolvedMigration] = []
            for file in files:
                match = _FILE_NAME.match(file)
                if match is None:
                    continue
                basename = match[0].rsplit("/", 1)[-1]
                full = path.join(directory, basename)
                module_name = f"pyfect_migration_{match[1]}_{match[2]}"
                load: Effect[object] = _Suspend(
                    lambda full=full, module_name=module_name: succeed(_import(full, module_name))
                )
                found.append((int(match[1]), match[2], load))
            return _sorted(found)

        listed: Effect[Sequence[str], Any] = fs.read_directory(directory)
        return listed.map_error(failed).map(resolve)

    return FileSystem().flat_map(lambda fs: Path().flat_map(lambda path: read(fs, path)))


__all__ = [
    "DumpSchema",
    "Loader",
    "Migration",
    "MigrationError",
    "MigrationKind",
    "MigrationRecord",
    "ResolvedMigration",
    "Runner",
    "from_file_system",
    "from_record",
    "make",
]
