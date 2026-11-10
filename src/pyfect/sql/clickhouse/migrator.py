"""Migrations for ClickHouse (Effect's ``@effect/sql-clickhouse``
``ClickhouseMigrator``): ``Migrator``'s runner, without a schema dump.

The ledger is a ``MergeTree`` table; migrations run outside transactions,
each recorded once it succeeds, so a failed one and those after it run
again next time."""

from __future__ import annotations

from typing import Never

from pyfect._core import Effect
from pyfect.effect import provide_service
from pyfect.layer import Layer
from pyfect.layer import effect_discard as layer_effect_discard
from pyfect.sql.clickhouse._connection import ClientMethod
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


def _as_command[A, E, R](effect: Effect[A, E, R], /) -> Effect[A, E, R]:
    return effect.pipe(provide_service(ClientMethod, "command"))


run: Runner[Never] = make(transform_writes=_as_command)
"""Run the new migrations of ``loader`` (see ``migrator.make``). The
migrations table is created and written with commands; reads and the
migrations themselves run as queries."""


def layer[R = Never](
    *,
    loader: Loader[R],
    schema_directory: str | None = None,
    table: str = "effect_sql_migrations",
) -> Layer[Never, MigrationError | SqlError, SqlClient | R]:
    """Runs the migrations when built."""
    return layer_effect_discard(run(loader=loader, schema_directory=schema_directory, table=table))


__all__ = [
    "Loader",
    "MigrationError",
    "SqlError",
    "from_file_system",
    "from_record",
    "layer",
    "run",
]
