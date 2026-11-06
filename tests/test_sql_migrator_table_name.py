"""The migrations table name reaches SQL Server's ``OBJECT_ID(N'...')``
check as a string literal with its quotes doubled, never as SQL."""

from __future__ import annotations

from typing import Any

from test_sql_key_collation import _client  # pyright: ignore[reportPrivateUsage]

import pyfect as fx
from pyfect.sql import migrator


def test_a_quote_in_the_table_name_stays_inside_the_mssql_literal():
    sent: list[str] = []
    table = "m'); DROP TABLE users; --"
    run: Any = migrator.make()(loader=migrator.from_record({}), table=table)
    fx.run_blocking(run.pipe(fx.provide(_client("mssql", sent))).result())
    [check] = [sql for sql in sent if "OBJECT_ID" in sql]
    assert "OBJECT_ID(N'm''); DROP TABLE users; --', N'U')" in check
