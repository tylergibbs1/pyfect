"""Creating the tables of ``pyfect.eventlog.sql_event_log_server_encrypted``
on the session's SQL Server container (skipped without one), while another
instance is creating them too.
"""

from __future__ import annotations

import uuid
from collections.abc import Generator
from typing import Any, Literal

import pytest

pytest.importorskip("pytds")

import pyfect as fx
from pyfect import testing
from pyfect.eventlog._sql_server_encrypted import tables
from pyfect.reactivity import layer as reactivity_layer
from pyfect.sql import SqlClientService, mssql

from ._mssql import MssqlServer


def _blocked_by(sql: SqlClientService, spid: int) -> fx.Effect[Literal["waited"], Any]:
    """Succeeds once a request waits on a lock that session ``spid`` holds."""

    def body() -> Generator[Any, Any, Literal["waited"]]:
        while True:
            rows = yield from sql(
                "SELECT COUNT(*) AS n FROM sys.dm_exec_requests WHERE blocking_session_id = {}",
                spid,
            )
            if int(str(rows[0]["n"])) > 0:
                return "waited"
            yield from fx.sleep("20 millis")

    return fx.gen(body)


def test_creates_a_table_while_another_instance_is_creating_its_index(
    mssql_server: MssqlServer,
):
    """creates a table without waiting on another instance still creating its index"""
    name = f"tables_{uuid.uuid4().hex[:16]}"

    def body():
        sql = yield from mssql.make(mssql_server.config())
        table = sql.identifier(name)
        # Another instance created the table and is in the middle of creating
        # its index. A statement waiting on that index holds locks the index's
        # creation needs next, which SQL Server only breaks as a deadlock
        # after up to 5 seconds.
        yield from sql("CREATE TABLE {} (a INT NOT NULL PRIMARY KEY, b INT NOT NULL)", table)
        indexing = yield from fx.Deferred[int].make()
        release = yield from fx.Deferred[None].make()

        def other_instance():
            yield from sql("CREATE INDEX {} ON {} (b)", sql.identifier(f"{name}_i0"), table)
            [row] = yield from sql("SELECT @@SPID AS spid")
            yield from indexing.succeed(int(str(row["spid"])))
            yield from release.wait()

        other = yield from sql.with_transaction(fx.gen(other_instance)).fork_scoped()
        spid = yield from indexing.wait()

        created = tables.create_table(
            sql, name, sql("a INT NOT NULL PRIMARY KEY, b INT NOT NULL"), ["b"]
        )
        outcome = yield from created.as_("created").race(_blocked_by(sql, spid))
        yield from release.succeed(None)
        yield from other.join()

        assert outcome == "created"
        yield from sql("DROP TABLE {}", table)

    program = testing.with_live(fx.scoped(fx.gen(body)))
    testing.run_test(program.pipe(fx.provide(reactivity_layer)).or_die())
