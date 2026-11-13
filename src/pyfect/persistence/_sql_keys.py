"""The string keys of the SQL stores on MySQL and SQL Server, compared
exactly.

Both servers compare strings under the column's collation. Their usual
defaults (``utf8mb4_0900_ai_ci``, ``*_CI_AS``) ignore case (and on MySQL
accents), and every SQL Server collation, like MySQL's ``PAD SPACE`` ones
(``utf8mb4_bin`` among them), ignores trailing spaces in ``=``: ``K:Alice``,
``K:alice`` and ``K:alice `` would be one key. On MySQL a key is
``VARBINARY``, whose bytes all count. On SQL Server it is a ``BIN2``
``NVARCHAR`` compared with ``key_equals`` / ``mssql_match``, which also
compare lengths; a write whose key differs from a stored one only in
trailing spaces then fails on the primary key instead of replacing it.
"""

from __future__ import annotations

from typing import Final, LiteralString

from pyfect.sql.client import SqlClientService
from pyfect.sql.statement import Fragment

MYSQL_KEY: Final = "VARBINARY(764)"
"""191 four-byte characters, as the ``VARCHAR(191)`` it replaces."""
MSSQL_BINARY_COLLATION: Final = "Latin1_General_100_BIN2"
MSSQL_KEY: Final = f"NVARCHAR(450) COLLATE {MSSQL_BINARY_COLLATION}"
MSSQL_PAIR_KEY: Final = f"NVARCHAR(191) COLLATE {MSSQL_BINARY_COLLATION}"
"""Each half of a two-column key (the index key stays under 900 bytes)."""


def _same_length(column: LiteralString, value: LiteralString) -> LiteralString:
    return f"DATALENGTH({column}) = DATALENGTH(CAST({value} AS NVARCHAR(4000)))"


def key_equals(sql: SqlClientService, column: str, key: str) -> Fragment:
    """``column = key``, counting every character on every dialect."""
    name = sql.identifier(column)
    return sql.on_dialect_or_else(
        mssql=lambda: sql(f"({{}} = {{}} AND {_same_length('{}', '{}')})", name, key, name, key),
        or_else=lambda: sql("{} = {}", name, key),
    )


def mssql_match(column: LiteralString) -> LiteralString:
    """The ``MERGE ... ON`` condition matching ``target.column`` to
    ``source.column`` exactly."""
    target = f"target.{column}"
    source = f"source.{column}"
    return f"{target} = {source} AND {_same_length(target, source)}"
