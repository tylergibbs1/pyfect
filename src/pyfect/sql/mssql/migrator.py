"""Migrations for SQL Server (Effect's ``@effect/sql-mssql`` ``MssqlMigrator``):
``Migrator``'s runner, without a schema dump (as Effect's)."""

from __future__ import annotations

from typing import Never

from pyfect.layer import Layer
from pyfect.layer import effect_discard as layer_effect_discard
from pyfect.sql.client import SqlClient
from pyfect.sql.error import SqlError
from pyfect.sql.migrator import (
    Loader,
    MigrationError,
    Runner,
    from_file_system,
    from_record,
    make,
)

run: Runner[Never] = make()
"""Run the new migrations of ``loader`` (see ``migrator.make``)."""


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
