"""Creating the tables of ``pyfect.eventlog.sql_event_log_server_encrypted``
on the session's SQL Server container (skipped without one), while another
instance is creating them too. "opens a store while another instance is creating
an index" ports that title of ``sql/mssql/test/SqlEventLogServerEncrypted.integration.test.ts``.
"""

from __future__ import annotations

import uuid
from collections.abc import Generator, Sequence
from typing import Any, Literal

import pytest

pytest.importorskip("pytds")

import pyfect as fx
from pyfect import exit, testing
from pyfect.crypto import digest
from pyfect.eventlog import sql_event_log_server_encrypted
from pyfect.eventlog._sql_server_encrypted import tables
from pyfect.reactivity import layer as reactivity_layer
from pyfect.sql import SqlClient, SqlClientService, mssql
from pyfect.sql.connection import Acquirer, Connection, Row, TransformRows, ValueRow
from pyfect.sql.error import SqlError
from pyfect.stream import Stream

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


def test_opens_a_store_while_another_instance_is_creating_an_index(
    mssql_server: MssqlServer,
):
    """opens a store while another instance is creating an index"""
    prefix = f"indexing_{uuid.uuid4().hex[:12]}"

    def body():
        sql = yield from mssql.make(mssql_server.config())
        stores = sql.identifier(f"{prefix}_compaction_stores")
        yield from sql(
            "CREATE TABLE {} (scope NVARCHAR(36) PRIMARY KEY, next_sweep_at BIGINT NULL)", stores
        )
        # Hold a separate index creation open, as an older instance would.
        indexing = yield from fx.Deferred[int].make()
        release = yield from fx.Deferred[None].make()

        def other_instance():
            index = sql.identifier(f"{prefix}_compaction_stores_i0")
            yield from sql("CREATE INDEX {} ON {} (next_sweep_at)", index, stores)
            [row] = yield from sql("SELECT @@SPID AS spid")
            yield from indexing.succeed(int(str(row["spid"])))
            yield from release.wait()

        other = yield from sql.with_transaction(fx.gen(other_instance)).fork_scoped()
        spid = yield from indexing.wait()

        opened = (
            fx.scoped(sql_event_log_server_encrypted.make_storage(entry_table_prefix=prefix))
            .pipe(fx.provide_service(SqlClient, sql))
            .pipe(fx.provide(digest.layer_web_crypto))
        )
        outcome = yield from opened.as_("opened").race(_blocked_by(sql, spid))
        yield from release.succeed(None)
        yield from other.join()
        assert outcome == "opened"

    program = testing.with_live(fx.scoped(fx.gen(body)))
    testing.run_test(program.pipe(fx.provide(reactivity_layer)).or_die())


class _Gated:
    """A connection whose ``IF OBJECT_ID(...) IS NULL CREATE TABLE`` waits on
    ``gate``'s lock between the check and the create."""

    def __init__(self, conn: Connection, gate: str) -> None:
        self._conn = conn
        self._gate = gate

    def _gated(self, sql: str) -> str:
        if " IS NULL CREATE TABLE " not in sql:
            return sql
        wait = f" IS NULL BEGIN SELECT COUNT(*) AS n FROM [{self._gate}]; CREATE TABLE "
        return sql.replace(" IS NULL CREATE TABLE ", wait, 1) + " END"

    def execute(
        self, sql: str, params: Sequence[object], transform_rows: TransformRows | None, /
    ) -> fx.Effect[Sequence[Row], SqlError]:
        return self._conn.execute(self._gated(sql), params, transform_rows)

    def execute_raw(self, sql: str, params: Sequence[object], /) -> fx.Effect[object, SqlError]:
        return self._conn.execute_raw(self._gated(sql), params)

    def execute_stream(
        self, sql: str, params: Sequence[object], transform_rows: TransformRows | None, /
    ) -> Stream[Row, SqlError]:
        return self._conn.execute_stream(self._gated(sql), params, transform_rows)

    def execute_values(
        self, sql: str, params: Sequence[object], /
    ) -> fx.Effect[Sequence[ValueRow], SqlError]:
        return self._conn.execute_values(self._gated(sql), params)

    def execute_values_unprepared(
        self, sql: str, params: Sequence[object], /
    ) -> fx.Effect[Sequence[ValueRow], SqlError]:
        return self._conn.execute_values_unprepared(self._gated(sql), params)

    def execute_unprepared(
        self, sql: str, params: Sequence[object], transform_rows: TransformRows | None, /
    ) -> fx.Effect[Sequence[Row], SqlError]:
        return self._conn.execute_unprepared(self._gated(sql), params, transform_rows)


def test_creates_the_remote_id_table_when_another_instance_creates_it_first(
    mssql_server: MssqlServer,
):
    """creates the remote id table when another instance creates it between
    this one's check for it and its create"""
    prefix = f"tables_{uuid.uuid4().hex[:16]}"
    remote_ids = f"{prefix}_remote_id"
    gate = f"{prefix}_gate"

    def body():
        sql = yield from mssql.make(mssql_server.config())
        acquirer: Acquirer = sql.acquirer.map(lambda conn: _Gated(conn, gate))
        fields = sql.fields()
        fields["acquirer"] = acquirer
        fields["borrower"] = None
        gated = SqlClientService(**fields)
        yield from sql("CREATE TABLE {} (a INT)", sql.identifier(gate))
        locked = yield from fx.Deferred[int].make()
        release = yield from fx.Deferred[None].make()

        def lock_gate():
            yield from sql(
                "SELECT COUNT(*) AS n FROM {} WITH (TABLOCKX, HOLDLOCK)", sql.identifier(gate)
            )
            [row] = yield from sql("SELECT @@SPID AS spid")
            yield from locked.succeed(int(str(row["spid"])))
            yield from release.wait()

        holder = yield from sql.with_transaction(fx.gen(lock_gate)).fork_scoped()
        spid = yield from locked.wait()
        created = yield from tables.create_065_tables(gated, prefix, remote_ids).fork_scoped()
        # This instance found no table and waits before creating it; the other
        # instance creates it now.
        yield from _blocked_by(sql, spid)
        yield from sql(
            "CREATE TABLE {} (remote_id VARBINARY(16) PRIMARY KEY)", sql.identifier(remote_ids)
        )
        yield from release.succeed(None)
        yield from holder.join()

        outcome = yield from created.await_exit()
        made = [gate, remote_ids, f"{prefix}_session_auth_bindings"] + [
            f"{prefix}_compaction_{name}" for name in ("stores", "buckets", "activations", "stages")
        ]
        for table in made:
            yield from sql("DROP TABLE IF EXISTS {}", sql.identifier(table))
        assert exit.is_success(outcome), outcome

    program = testing.with_live(fx.scoped(fx.gen(body)))
    testing.run_test(program.pipe(fx.provide(reactivity_layer)).or_die())
