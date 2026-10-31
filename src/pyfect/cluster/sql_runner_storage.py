"""Runner storage in a SQL database (Effect's ``SqlRunnerStorage``).

Runners are rows of ``<prefix>_runners``. Shard locks are PostgreSQL or
MySQL advisory locks held by one reserved connection (rebuilt when a
statement on it fails), or, on SQLite and SQL Server (or with
``shard_lock_disable_advisory``), leases in ``<prefix>_locks`` that
expire after ``shard_lock_expiration``. Every lock operation has a
deadline of the effective lock refresh interval.

MySQL and SQL Server statements are ported but not run by the tests.
"""

from __future__ import annotations

import math
import random
from collections.abc import Callable, Generator, Sequence
from typing import Any, Never, cast

from pyfect import layer as layer_
from pyfect._core import Effect
from pyfect._fiber import Fiber
from pyfect._js import text_encode
from pyfect.cause import Cause
from pyfect.cluster._resource_ref import ResourceRef
from pyfect.cluster._shard_lock import effective_interval
from pyfect.cluster.cluster_error import PersistenceError
from pyfect.cluster.runner_storage import (
    RunnerStorage,
    RunnerStorageService,
    make_encoded,
)
from pyfect.cluster.sharding_config import ShardingConfig, ShardingConfigService, shard_group_config
from pyfect.duration import Seconds
from pyfect.effect import gen, provide_service, suspend, void
from pyfect.exit import Exit
from pyfect.scope import CloseableScope, Scope, fork_in
from pyfect.sql import migrator
from pyfect.sql.client import SqlClient, SqlClientService
from pyfect.sql.connection import Connection
from pyfect.sql.error import SqlError
from pyfect.sql.statement import Fragment, Statement


def postgres_lock_namespace(prefix: str) -> int:
    """The advisory-lock namespace of ``prefix``: FNV-1a of
    ``effect-cluster:<prefix>`` as a signed 32-bit integer. A persistent
    wire format shared with Effect: it must never change."""
    h = 0x811C9DC5
    for byte in text_encode(f"effect-cluster:{prefix}"):
        h = ((h ^ byte) * 0x01000193) & 0xFFFFFFFF
    return h - 0x1_0000_0000 if h >= 0x8000_0000 else h


type _Held = tuple[Connection, int]


class _Storage:
    """The ``EncodedRunnerStorage`` of one client."""

    def __init__(
        self,
        *,
        sql: SqlClientService,
        config: ShardingConfigService,
        prefix: str,
        layer_scope: CloseableScope,
        lock_conn: ResourceRef[_Held] | None,
        disable_advisory: bool,
    ) -> None:
        self.sql = sql
        self.prefix = prefix
        self.layer_scope = layer_scope
        self.lock_conn = lock_conn
        self.disable_advisory = disable_advisory
        self.deadline = effective_interval(config)
        self.lock_namespace = postgres_lock_namespace(prefix)
        # pg_locks shows the signed int4 key as an unsigned oid
        self.lock_namespace_oid = self.lock_namespace & 0xFFFFFFFF
        self.runners = sql.identifier(f"{prefix}_runners")
        self.locks = sql.identifier(f"{prefix}_locks")
        self.now: Fragment = sql.on_dialect_or_else(
            pg=lambda: sql.literal("NOW()"),
            mysql=lambda: sql.literal("NOW()"),
            mssql=lambda: sql.literal("GETDATE()"),
            or_else=lambda: sql.literal("CURRENT_TIMESTAMP"),
        )
        self.pg_lock_order = sql.literal('ORDER BY shard_id COLLATE "C"')
        seconds = sql.unsafe(str(math.ceil(config.shard_lock_expiration)))
        self.expires_seconds = seconds
        now = self.now
        self.lock_expires_at: Fragment = sql.on_dialect_or_else(
            pg=lambda: sql("{} - INTERVAL '{} seconds'", now, seconds),
            mysql=lambda: sql("DATE_SUB({}, INTERVAL {} SECOND)", now, seconds),
            mssql=lambda: sql("DATEADD(SECOND, -{}, {})", seconds, now),
            or_else=lambda: sql("datetime({}, '-{} seconds')", now, seconds),
        )
        self.lock_numbers: dict[str, int] = {}
        self.shard_index: dict[str, int] = {}
        self.lock_names: dict[str, str] = {}
        index = 0
        for i, group in enumerate(shard_group_config(config).available):
            base = (i + 1) * 1_000_000
            for shard in range(1, config.shards_per_group + 1):
                shard_id = f"{group}:{shard}"
                self.lock_numbers[shard_id] = base + shard
                self.shard_index[shard_id] = index
                self.lock_names[shard_id] = f"{prefix}.{shard_id}"
                index += 1

    # --- helpers ----------------------------------------------------------------------

    def bool_(self, value: bool) -> object:
        return self.sql.on_dialect_or_else(
            mssql=lambda: int(value), sqlite=lambda: int(value), or_else=lambda: value
        )

    def wrap_string(self, text: str) -> str:
        return self.sql.on_dialect_or_else(mssql=lambda: f"N'{text}'", or_else=lambda: f"'{text}'")

    def string_literal(self, text: str) -> Statement[Any]:
        return self.sql.unsafe(self.wrap_string(text))

    def string_list(self, texts: Sequence[str]) -> Statement[Any]:
        return self.sql.unsafe("(" + ",".join(self.wrap_string(t) for t in texts) + ")")

    def with_deadline[A, E](self, operation: Effect[A, E]) -> Effect[A, E]:
        """``operation`` on a fiber of the layer's scope, joined with the
        deadline: an operation stuck in an uninterruptible region (closing
        an unresponsive connection) finishes detached."""

        def body() -> Generator[Effect[Any, Any, Any], Any, A]:
            fiber: Fiber[A, E] = yield from fork_in(
                operation, self.layer_scope, start_immediately=True
            )

            def stop() -> Effect[None]:
                if fiber.poll_unsafe() is not None:
                    return void
                return fork_in(
                    fiber.interrupt(), self.layer_scope, start_immediately=True
                ).as_void()

            return (yield from fiber.join().timeout(self.deadline).ensuring(suspend(stop)))

        return gen(body)

    def rebuild_lock_conn(self, from_: _Held | None = None) -> Effect[None]:
        rebuild = None if self.lock_conn is None else self.lock_conn.rebuild_unsafe(from_=from_)
        if rebuild is None:
            return void
        # A stalled release must not block later rebuilds.
        return fork_in(
            self.with_deadline(rebuild).exit(), self.layer_scope, start_immediately=True
        ).as_void()

    @staticmethod
    def _rebuild_on_failure[A, E](
        operation: Effect[A, E], rebuild: Callable[[], Effect[None]]
    ) -> Effect[A, E]:
        """``operation``, running ``rebuild`` when it fails. An interrupt
        is not a broken connection: a rebuild on shutdown can lose its
        ``pg_advisory_unlock_all`` and pool a session holding the locks."""

        def failed(cause: Cause[Any]) -> Effect[None]:
            return void if cause.has_interrupts_only else rebuild()

        return operation.on_error(failed)

    def use_lock_conn[A, E](self, f: Callable[[Connection, int], Effect[A, E]]) -> Effect[A, E]:
        """``f`` on the reserved connection (PostgreSQL and MySQL, which
        always have one); a failure replaces it."""
        lock_conn = cast("ResourceRef[_Held]", self.lock_conn)

        def run(held: _Held) -> Effect[A, E]:
            return self._rebuild_on_failure(
                f(held[0], held[1]), lambda: self.rebuild_lock_conn(held)
            )

        return lock_conn.await_.flat_map(run)

    def exec(self, statement: Statement[Any]) -> Effect[object, SqlError]:
        if self.lock_conn is None:
            return statement.raw
        query, params = statement.compile()
        return self.use_lock_conn(lambda conn, _pid: conn.execute_raw(query, params))

    def exec_values(
        self, statement: Statement[Any]
    ) -> Effect[Sequence[tuple[object, ...]], SqlError]:
        if self.lock_conn is None:
            return statement.values
        query, params = statement.compile()
        return self.use_lock_conn(lambda conn, _pid: conn.execute_values(query, params))

    def exec_unprepared(self, statement: Statement[Any]) -> Effect[Sequence[Any], SqlError]:
        if self.lock_conn is None:
            return statement.values_unprepared
        query, params = statement.compile()
        return self.use_lock_conn(lambda conn, _pid: conn.execute_unprepared(query, params, None))

    def with_lock_operation_deadline[A, E](self, operation: Effect[A, E]) -> Effect[A, E]:
        """``operation`` with the deadline; on failure the connection ready
        at entry is replaced (or a failed rebuild retried)."""

        def run() -> Effect[A, E]:
            ready = None if self.lock_conn is None else self.lock_conn.get_unsafe()

            def rebuild() -> Effect[None]:
                if ready is not None:
                    return self.rebuild_lock_conn(ready)
                if self.lock_conn is not None and self.lock_conn.get_unsafe() is None:
                    return self.rebuild_lock_conn()
                return void

            return self._rebuild_on_failure(self.with_deadline(operation), rebuild)

        return suspend(run)

    # --- statements -------------------------------------------------------------------

    def lock_values(self, address: str, shard_ids: Sequence[str]) -> Fragment:
        sql = self.sql
        return sql.csv(
            [
                sql("({}, {}, {})", self.string_literal(s), self.string_literal(address), self.now)
                for s in shard_ids
            ]
        )

    def acquired_locks(self, address: str, shard_ids: Sequence[str]) -> Effect[list[str], SqlError]:
        statement = self.sql(
            "SELECT shard_id FROM {} WHERE address = {} AND acquired_at >= {} AND shard_id IN {}",
            self.locks,
            address,
            self.lock_expires_at,
            self.string_list(shard_ids),
        )
        return self.exec_values(statement).map(lambda rows: [str(r[0]) for r in rows])

    def acquire_lock(self, address: str, shard_ids: Sequence[str]) -> Effect[list[str], SqlError]:
        sql = self.sql
        if sql.dialect == "pg":
            if self.disable_advisory:
                statement = sql(
                    "INSERT INTO {} (shard_id, address, acquired_at) "
                    "SELECT * FROM (VALUES {}) AS requested (shard_id, address, acquired_at) {} "
                    "ON CONFLICT (shard_id) DO UPDATE SET address = {}, acquired_at = {} "
                    "WHERE {}.address = {} OR {}.acquired_at < {}",
                    self.locks,
                    self.lock_values(address, shard_ids),
                    self.pg_lock_order,
                    address,
                    self.now,
                    self.locks,
                    address,
                    self.locks,
                    self.lock_expires_at,
                )
                return self.exec(statement).flat_map(
                    lambda _: self.acquired_locks(address, shard_ids)
                )
            return self.use_lock_conn(lambda conn, pid: self._pg_try_locks(conn, pid, shard_ids))
        if sql.dialect == "mysql":
            if self.disable_advisory:
                statement = sql(
                    "INSERT INTO {} (shard_id, address, acquired_at) VALUES {} "
                    "ON DUPLICATE KEY UPDATE "
                    "address = IF(address = VALUES(address) OR acquired_at < {}, "
                    "VALUES(address), address), "
                    "acquired_at = IF(address = VALUES(address) OR acquired_at < {}, "
                    "VALUES(acquired_at), acquired_at)",
                    self.locks,
                    self.lock_values(address, shard_ids),
                    self.lock_expires_at,
                    self.lock_expires_at,
                )
                return self.exec_unprepared(statement).flat_map(
                    lambda _: self.acquired_locks(address, shard_ids)
                )
            return self.use_lock_conn(lambda conn, pid: self._mysql_get_locks(conn, pid, shard_ids))
        if sql.dialect == "mssql":
            statement = sql(
                "MERGE {} WITH (HOLDLOCK) AS target "
                "USING (SELECT * FROM (VALUES {})) AS source (shard_id, address, acquired_at) "
                "ON target.shard_id = source.shard_id "
                "WHEN MATCHED AND (target.address = source.address OR "
                "DATEDIFF(SECOND, target.acquired_at, {}) > {}) THEN "
                "UPDATE SET address = source.address, acquired_at = source.acquired_at "
                "WHEN NOT MATCHED THEN INSERT (shard_id, address, acquired_at) "
                "VALUES (source.shard_id, source.address, source.acquired_at);",
                self.locks,
                self.lock_values(address, shard_ids),
                self.now,
                self.expires_seconds,
            )
            return sql.with_transaction(
                statement.flat_map(lambda _: self.acquired_locks(address, shard_ids))
            )
        statement = sql(
            "WITH source(shard_id, address, acquired_at) AS (VALUES {}) "
            "INSERT INTO {} (shard_id, address, acquired_at) "
            "SELECT source.shard_id, source.address, source.acquired_at FROM source "
            "WHERE NOT EXISTS (SELECT 1 FROM {} WHERE shard_id = source.shard_id "
            "AND address != {} "
            "AND (strftime('%s', {}) - strftime('%s', acquired_at)) <= {}) "
            "ON CONFLICT(shard_id) DO UPDATE SET address = {}, acquired_at = {}",
            self.lock_values(address, shard_ids),
            self.locks,
            self.locks,
            address,
            self.now,
            self.expires_seconds,
            address,
            self.now,
        )
        return sql.with_transaction(
            statement.flat_map(lambda _: self.acquired_locks(address, shard_ids))
        )

    def _pg_try_locks(
        self, conn: Connection, pid: int, shard_ids: Sequence[str]
    ) -> Effect[list[str], SqlError]:
        def body() -> Generator[Effect[Any, Any, Any], Any, list[str]]:
            acquired: list[str] = []
            to_acquire = {self.lock_numbers[s]: s for s in shard_ids}
            taken = yield from conn.execute_values(
                "SELECT objid FROM pg_locks WHERE locktype = 'advisory' AND granted = true "
                f"AND classid = {self.lock_namespace_oid} AND objsubid = 2 AND pid = {pid} "
                "ORDER BY objid",
                [],
            )
            for lock_number, *_rest in taken:
                shard_id = to_acquire.pop(int(str(lock_number)), None)
                if shard_id is not None:
                    acquired.append(shard_id)
            if not to_acquire:
                return acquired
            locks = ", ".join(
                f'pg_try_advisory_lock({self.lock_namespace}, {number}) AS "{shard_id}"'
                for number, shard_id in to_acquire.items()
            )
            rows = yield from conn.execute_unprepared(f"SELECT {locks}", [], None)
            for shard_id, got in rows[0].items():
                if got:
                    acquired.append(shard_id)
            return acquired

        return gen(body)

    def _mysql_get_locks(
        self, conn: Connection, pid: int, shard_ids: Sequence[str]
    ) -> Effect[list[str], SqlError]:
        def body() -> Generator[Effect[Any, Any, Any], Any, list[str]]:
            all_taken = ", ".join(
                f"IS_USED_LOCK('{name}') AS \"{shard_id}\""
                for shard_id, name in self.lock_names.items()
            )
            taken = (yield from conn.execute_values(f"SELECT {all_taken}", []))[0]
            acquired: list[str] = []
            to_acquire: list[str] = []
            for shard_id in shard_ids:
                if taken[self.shard_index[shard_id]] == pid:
                    acquired.append(shard_id)
                else:
                    to_acquire.append(shard_id)
            if not to_acquire:
                return acquired
            locks = ", ".join(f"GET_LOCK('{self.lock_names[s]}', 0) AS \"{s}\"" for s in to_acquire)
            results = (yield from conn.execute_values(f"SELECT {locks}", []))[0]
            for shard_id, result in zip(to_acquire, results, strict=True):
                if result == 1:
                    acquired.append(shard_id)
            return acquired

        return gen(body)

    def refresh_shards(self, address: str, shard_ids: Sequence[str]) -> Effect[list[str], SqlError]:
        sql = self.sql
        shards = self.string_list(shard_ids)

        def first_column(rows: Sequence[Any]) -> list[str]:
            return [str(r[0]) for r in rows]

        if sql.dialect == "pg":
            if not self.disable_advisory:
                return self.acquire_lock(address, shard_ids)
            statement = sql(
                "WITH locked AS (SELECT shard_id FROM {} WHERE address = {} AND shard_id IN {} "
                "{} FOR UPDATE) "
                "UPDATE {} SET acquired_at = {} "
                "WHERE address = {} AND shard_id IN (SELECT shard_id FROM locked) "
                "RETURNING shard_id",
                self.locks,
                address,
                shards,
                self.pg_lock_order,
                self.locks,
                self.now,
                address,
            )
            return self.exec_values(statement).map(first_column)
        if sql.dialect == "mysql":
            if not self.disable_advisory:
                return self.acquire_lock(address, shard_ids)
            statement = sql(
                "UPDATE {} SET acquired_at = {} WHERE address = {} AND shard_id IN {}; "
                "SELECT shard_id FROM {} WHERE address = {} AND shard_id IN {}",
                self.locks,
                self.now,
                address,
                shards,
                self.locks,
                address,
                shards,
            )
            return self.exec_unprepared(statement).map(
                lambda results: [str(row["shard_id"]) for row in results[1]]
            )
        if sql.dialect == "mssql":
            statement = sql(
                "UPDATE {} SET acquired_at = {} OUTPUT inserted.shard_id "
                "WHERE address = {} AND shard_id IN {}",
                self.locks,
                self.now,
                address,
                shards,
            )
            return self.exec_values(statement).map(first_column)
        statement = sql(
            "UPDATE {} SET acquired_at = {} WHERE address = {} AND shard_id IN {} "
            "RETURNING shard_id",
            self.locks,
            self.now,
            address,
            shards,
        )
        return self.exec_values(statement).map(first_column)

    def release_shard(self, address: str, shard_id: str) -> Effect[object, SqlError]:
        sql = self.sql
        delete = sql(
            "DELETE FROM {} WHERE address = {} AND shard_id = {}", self.locks, address, shard_id
        )
        if sql.dialect in ("pg", "mysql") and self.disable_advisory:
            return self.exec(delete)
        if sql.dialect == "pg":
            number = self.lock_numbers[shard_id]

            def pg(conn: Connection, _pid: int) -> Effect[None, SqlError]:
                def body() -> Generator[Effect[Any, Any, Any], Any]:
                    for _ in range(5):
                        yield from conn.execute_raw(
                            f"SELECT pg_advisory_unlock({self.lock_namespace}, {number})", []
                        )
                        taken = yield from conn.execute_values(
                            "SELECT 1 FROM pg_locks WHERE locktype = 'advisory' AND granted = true "
                            f"AND classid = {self.lock_namespace_oid} AND objid = {number} "
                            "AND objsubid = 2 AND pid = pg_backend_pid()",
                            [],
                        )
                        if not taken:
                            return
                    yield from conn.execute_raw("SELECT pg_advisory_unlock_all()", [])

                return gen(body)

            return self.use_lock_conn(pg)
        if sql.dialect == "mysql":
            name = self.lock_names[shard_id]

            def mysql(conn: Connection, pid: int) -> Effect[None, SqlError]:
                def body() -> Generator[Effect[Any, Any, Any], Any]:
                    while True:
                        yield from conn.execute_raw(f"SELECT RELEASE_LOCK('{name}')", [])
                        taken = yield from conn.execute_values(f"SELECT IS_USED_LOCK('{name}')", [])
                        if not taken or taken[0][0] != pid:
                            return

                return gen(body)

            return self.use_lock_conn(mysql)
        return delete

    def release_all_shards(self, address: str) -> Effect[object, SqlError]:
        sql = self.sql
        if sql.dialect == "pg":
            if self.disable_advisory:
                return self.exec(
                    sql(
                        "WITH locked AS (SELECT shard_id FROM {} WHERE address = {} {} FOR UPDATE) "
                        "DELETE FROM {} WHERE address = {} "
                        "AND shard_id IN (SELECT shard_id FROM locked)",
                        self.locks,
                        address,
                        self.pg_lock_order,
                        self.locks,
                        address,
                    )
                )
            return self.exec(sql("SELECT pg_advisory_unlock_all()"))
        if sql.dialect == "mysql":
            if self.disable_advisory:
                return self.exec(sql("DELETE FROM {} WHERE address = {}", self.locks, address))
            return self.exec(sql("SELECT RELEASE_ALL_LOCKS()"))
        return sql("DELETE FROM {} WHERE address = {}", self.locks, address)

    def insert_runner(
        self, address: str, runner: str, healthy: bool
    ) -> Effect[Sequence[Any], SqlError]:
        sql = self.sql
        if sql.dialect == "mssql":
            return sql(
                "MERGE {} AS target USING (SELECT {} AS address, {} AS runner, "
                "{} AS last_heartbeat, {} AS healthy) AS source ON target.address = source.address "
                "WHEN MATCHED THEN UPDATE SET runner = source.runner, "
                "last_heartbeat = source.last_heartbeat, healthy = source.healthy "
                "WHEN NOT MATCHED THEN INSERT (address, runner, last_heartbeat, healthy) "
                "VALUES (source.address, source.runner, source.last_heartbeat, source.healthy) "
                "OUTPUT INSERTED.machine_id;",
                self.runners,
                address,
                runner,
                self.now,
                self.bool_(healthy),
            ).values
        if sql.dialect == "mysql":
            return sql(
                "INSERT INTO {} (address, runner, last_heartbeat, healthy) VALUES ({}, {}, {}, {}) "
                "ON DUPLICATE KEY UPDATE runner = VALUES(runner), "
                "last_heartbeat = VALUES(last_heartbeat), healthy = VALUES(healthy); "
                "SELECT machine_id FROM {} WHERE address = {};",
                self.runners,
                address,
                runner,
                self.now,
                healthy,
                self.runners,
                address,
            ).unprepared.map(_mysql_machine_id)
        if sql.dialect == "pg":
            return sql(
                "INSERT INTO {} (address, runner, last_heartbeat, healthy) VALUES ({}, {}, {}, {}) "
                "ON CONFLICT (address) DO UPDATE SET runner = EXCLUDED.runner, "
                "last_heartbeat = EXCLUDED.last_heartbeat, healthy = EXCLUDED.healthy "
                "RETURNING machine_id",
                self.runners,
                address,
                runner,
                self.now,
                healthy,
            ).values
        return sql(
            "INSERT INTO {} (address, runner, last_heartbeat, healthy) VALUES ({}, {}, {}, {}) "
            "ON CONFLICT(address) DO UPDATE SET runner = excluded.runner, "
            "last_heartbeat = excluded.last_heartbeat, healthy = excluded.healthy "
            "RETURNING machine_id;",
            self.runners,
            address,
            runner,
            self.now,
            self.bool_(healthy),
        ).values

    # --- EncodedRunnerStorage ---------------------------------------------------------

    @property
    def get_runners(self) -> Effect[list[tuple[str, bool]], PersistenceError]:
        statement = self.sql(
            "SELECT runner, healthy FROM {} WHERE last_heartbeat > {}",
            self.runners,
            self.lock_expires_at,
        )
        return PersistenceError.refail(
            statement.values.map(lambda rows: [(str(r[0]), bool(r[1])) for r in rows])
        )

    def register(
        self, address: str, runner: str, healthy: bool, /
    ) -> Effect[int, PersistenceError]:
        return PersistenceError.refail(
            self.insert_runner(address, runner, healthy).map(lambda rows: int(rows[0][0]))
        )

    def unregister(self, address: str, /) -> Effect[None, PersistenceError]:
        statement = self.sql(
            "DELETE FROM {} WHERE address = {} OR last_heartbeat < {}",
            self.runners,
            address,
            self.lock_expires_at,
        )
        return PersistenceError.refail(statement.as_void())

    def set_runner_health(self, address: str, healthy: bool, /) -> Effect[None, PersistenceError]:
        statement = self.sql(
            "UPDATE {} SET healthy = {} WHERE address = {}",
            self.runners,
            self.bool_(healthy),
            address,
        )
        return PersistenceError.refail(statement.as_void())

    def acquire(
        self, address: str, shard_ids: Sequence[str], /
    ) -> Effect[list[str], PersistenceError]:
        return PersistenceError.refail(
            self.with_lock_operation_deadline(self.acquire_lock(address, shard_ids))
        )

    def refresh(
        self, address: str, shard_ids: Sequence[str], /
    ) -> Effect[list[str], PersistenceError]:
        heartbeat = self.sql(
            "UPDATE {} SET last_heartbeat = {} WHERE address = {}", self.runners, self.now, address
        )
        if not shard_ids:
            # The liveness probe while lock storage is unhealthy: on the
            # shared pool, so a wedged reserved connection cannot block it.
            return PersistenceError.refail(self.with_deadline(heartbeat).as_([]))
        return PersistenceError.refail(
            self.with_lock_operation_deadline(
                self.exec(heartbeat).flat_map(lambda _: self.refresh_shards(address, shard_ids))
            )
        )

    def release(self, address: str, shard_id: str, /) -> Effect[None, PersistenceError]:
        return PersistenceError.refail(
            self.with_lock_operation_deadline(self.release_shard(address, shard_id)).as_void()
        )

    def release_all(self, address: str, /) -> Effect[None, PersistenceError]:
        return PersistenceError.refail(
            self.with_lock_operation_deadline(self.release_all_shards(address)).as_void()
        )


def _mysql_machine_id(results: Sequence[Any]) -> list[list[object]]:
    """The machine id of a MySQL multi-statement upsert's second result."""
    return [[results[1][0]["machine_id"]]]


def _acquire_lock_conn(
    sql: SqlClientService, disable_advisory: bool, deadline: Seconds
) -> Callable[[CloseableScope], Effect[_Held]] | None:
    """How to reserve the lock connection (PostgreSQL and MySQL only)."""

    def unlock_on_close(scope: CloseableScope, conn: Connection, query: str) -> Effect[None]:
        def finalizer(_: Exit[Any, Any]) -> Effect[None]:
            return conn.execute_raw(query, []).timeout(deadline).interruptible().ignore_cause()

        return scope.add_finalizer(finalizer)

    def reserve(scope: CloseableScope) -> Effect[Connection]:
        return sql.reserve.or_die().pipe(provide_service(Scope, scope))

    def pg(scope: CloseableScope) -> Effect[_Held]:
        def body() -> Generator[Effect[Any, Any, Any], Any, _Held]:
            conn = yield from reserve(scope)
            if disable_advisory:
                return (conn, 0)
            pid = (yield from conn.execute_values("SELECT pg_backend_pid()", []))[0][0]
            yield from unlock_on_close(scope, conn, "SELECT pg_advisory_unlock_all()")
            return (conn, int(str(pid)))

        return gen(body).or_die()

    def mysql(scope: CloseableScope) -> Effect[_Held]:
        def body() -> Generator[Effect[Any, Any, Any], Any, _Held]:
            conn = yield from reserve(scope)
            if disable_advisory:
                return (conn, 0)
            # IS_USED_LOCK names the connection id, also under Vitess
            pid: int | None = None
            while pid is None:
                name = f"cluster:pid:{random.randrange(2**53)}"
                taken = (
                    yield from conn.execute_values(
                        f"SELECT GET_LOCK('{name}', 10), IS_USED_LOCK('{name}')", []
                    )
                )[0]
                if taken[0] is None:
                    continue
                pid = int(str(taken[1]))
            yield from unlock_on_close(scope, conn, "SELECT RELEASE_ALL_LOCKS()")
            return (conn, pid)

        return gen(body).or_die()

    return sql.on_dialect_or_else(pg=lambda: pg, mysql=lambda: mysql, or_else=lambda: None)


def make_storage(
    *, prefix: str = "cluster"
) -> Effect[RunnerStorageService, Never, SqlClient | ShardingConfig | Scope]:
    """Runner storage on the tables of ``prefix`` (already migrated)."""

    def body() -> Generator[Effect[Any, Any, Any], Any, RunnerStorageService]:
        config = yield from ShardingConfig()
        sql = (yield from SqlClient()).without_transforms()
        layer_scope = yield from Scope()
        # PGlite runs every statement on one session: it gets table leases
        # on the shared client.
        single_session = sql.driver == "pglite"
        disable_advisory = config.shard_lock_disable_advisory or single_session
        acquire = (
            None
            if single_session
            else _acquire_lock_conn(sql, disable_advisory, effective_interval(config))
        )
        lock_conn = None
        if acquire is not None:
            lock_conn = yield from ResourceRef.make(layer_scope, acquire)
        storage = _Storage(
            sql=sql,
            config=config,
            prefix=prefix,
            layer_scope=layer_scope,
            lock_conn=lock_conn,
            disable_advisory=disable_advisory,
        )
        return make_encoded(storage)

    return gen(body).with_tracer_enabled(False)


def migrations(*, prefix: str = "cluster") -> migrator.Loader:
    """The runner tables' migrations (existing deployments may have the
    tables without a migration history: they are created if absent)."""
    runners_table = f"{prefix}_runners"
    locks_table = f"{prefix}_locks"

    def create() -> Generator[Effect[Any, Any, Any], Any]:
        sql = (yield from SqlClient()).without_transforms()
        runners = sql.identifier(runners_table)
        locks = sql.identifier(locks_table)
        yield from sql.on_dialect_or_else(
            mssql=lambda: sql(
                "IF OBJECT_ID(N'{}', N'U') IS NULL CREATE TABLE {} ("
                "machine_id INT IDENTITY PRIMARY KEY, address VARCHAR(255) NOT NULL, "
                "runner TEXT NOT NULL, healthy BIT NOT NULL DEFAULT 1, "
                "last_heartbeat DATETIME NOT NULL DEFAULT GETDATE(), UNIQUE(address))",
                runners,
                runners,
            ),
            mysql=lambda: sql(
                "CREATE TABLE IF NOT EXISTS {} ("
                "machine_id INT AUTO_INCREMENT PRIMARY KEY, address VARCHAR(255) NOT NULL, "
                "runner TEXT NOT NULL, healthy BOOLEAN NOT NULL DEFAULT TRUE, "
                "last_heartbeat DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP, UNIQUE(address))",
                runners,
            ),
            pg=lambda: sql(
                "CREATE TABLE IF NOT EXISTS {} ("
                "machine_id SERIAL PRIMARY KEY, address VARCHAR(255) NOT NULL, "
                "runner TEXT NOT NULL, healthy BOOLEAN NOT NULL DEFAULT TRUE, "
                "last_heartbeat TIMESTAMP NOT NULL DEFAULT NOW(), UNIQUE(address))",
                runners,
            ),
            or_else=lambda: sql(
                "CREATE TABLE IF NOT EXISTS {} ("
                "machine_id INTEGER PRIMARY KEY AUTOINCREMENT, address TEXT NOT NULL, "
                "runner TEXT NOT NULL, healthy INTEGER NOT NULL DEFAULT 1, "
                "last_heartbeat DATETIME NOT NULL DEFAULT (CURRENT_TIMESTAMP), UNIQUE(address))",
                runners,
            ),
        )
        yield from sql.on_dialect_or_else(
            mssql=lambda: sql(
                "IF OBJECT_ID(N'{}', N'U') IS NULL CREATE TABLE {} ("
                "shard_id VARCHAR(50) PRIMARY KEY, address VARCHAR(255) NOT NULL, "
                "acquired_at DATETIME NOT NULL)",
                locks,
                locks,
            ),
            mysql=lambda: sql(
                "CREATE TABLE IF NOT EXISTS {} (shard_id VARCHAR(50) PRIMARY KEY, "
                "address VARCHAR(255) NOT NULL, acquired_at DATETIME NOT NULL)",
                locks,
            ),
            pg=lambda: sql(
                "CREATE TABLE IF NOT EXISTS {} (shard_id VARCHAR(50) PRIMARY KEY, "
                "address VARCHAR(255) NOT NULL, acquired_at TIMESTAMP NOT NULL)",
                locks,
            ),
            or_else=lambda: sql(
                "CREATE TABLE IF NOT EXISTS {} (shard_id TEXT PRIMARY KEY, "
                "address TEXT NOT NULL, acquired_at DATETIME NOT NULL)",
                locks,
            ),
        )

    return migrator.from_record({"0001_create_tables": gen(create)})


def run_migrations(*, prefix: str = "cluster") -> Effect[None, Never, SqlClient]:
    """Run the runner migrations; a failure is a defect. Message and runner
    migration ids overlap, so they keep separate histories."""
    return (
        migrator.make()(loader=migrations(prefix=prefix), table=f"{prefix}_runner_migrations")
        .as_void()
        .or_die()
    )


def make(
    *, prefix: str = "cluster"
) -> Effect[RunnerStorageService, Never, SqlClient | ShardingConfig | Scope]:
    """Run the migrations, then ``make_storage``."""
    return run_migrations(prefix=prefix).flat_map(lambda _: make_storage(prefix=prefix))


def layer_migrations(*, prefix: str = "cluster") -> layer_.Layer[Never, Never, SqlClient]:
    return layer_.effect_discard(run_migrations(prefix=prefix))


def layer_storage(
    *, prefix: str = "cluster"
) -> layer_.Layer[RunnerStorage, Never, SqlClient | ShardingConfig]:
    return layer_.effect(RunnerStorage, make_storage(prefix=prefix))


def layer_with(
    *, prefix: str = "cluster"
) -> layer_.Layer[RunnerStorage, Never, SqlClient | ShardingConfig]:
    return layer_.effect(RunnerStorage, make(prefix=prefix))


layer: layer_.Layer[RunnerStorage, Never, SqlClient | ShardingConfig] = layer_with()

__all__ = [
    "effective_interval",
    "layer",
    "layer_migrations",
    "layer_storage",
    "layer_with",
    "make",
    "make_storage",
    "migrations",
    "postgres_lock_namespace",
    "run_migrations",
]
