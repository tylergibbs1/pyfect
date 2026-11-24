"""The key columns of the SQL cluster storages on MySQL and SQL Server,
compared exactly (``persistence._sql_keys`` has the reasons and SQL
Server's ``key_equals``)."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Final

from pyfect.persistence._sql_keys import MSSQL_BINARY_COLLATION, key_equals
from pyfect.sql.client import SqlClientService
from pyfect.sql.statement import Fragment

MSSQL_EXACT_TEXT: Final = f"COLLATE {MSSQL_BINARY_COLLATION}"
"""Case and accents count; ``=`` still ignores trailing spaces."""


def key_in(sql: SqlClientService, column: str, keys: Sequence[str]) -> Fragment:
    """``column IN (keys)``, counting every character on every dialect."""
    if sql.dialect == "mssql":
        return sql.or_([key_equals(sql, column, key) for key in keys])
    return sql.in_(column, keys)
