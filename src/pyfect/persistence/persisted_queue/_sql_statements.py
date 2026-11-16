"""The SQL of the queue store, per dialect: the claimed ``Element``, the
offer, poll and cleanup statements, and ``Settlements``, the statements
that settle or renew a claim."""

from __future__ import annotations

import math
import re
from collections.abc import Callable, Generator, Sequence
from dataclasses import dataclass
from typing import Any, Final

from pyfect._core import Effect
from pyfect.cause import Cause
from pyfect.duration import Duration
from pyfect.effect import fail, gen, sync, void
from pyfect.persistence._columns import column_int
from pyfect.persistence._sql_keys import key_equals
from pyfect.persistence.persistence._sql import SQL_CLEANUP_BATCH_SIZE
from pyfect.schedule import Schedule
from pyfect.scope import Scope, scoped
from pyfect.sql.client import SqlClientService
from pyfect.sql.connection import Row
from pyfect.sql.error import ConstraintError, SqlError
from pyfect.sql.statement import Fragment, Statement

_LONE_SURROGATE = re.compile("[\ud800-\udfff]")
_BATCH_LIMIT: Final = str(SQL_CLEANUP_BATCH_SIZE)


@dataclass(eq=False, slots=True)
class Element:
    """A row this store claimed and has not settled, under the ``lock`` of
    the poll that claimed it."""

    sequence: int | str
    id: str
    element: str
    attempts: int
    lock: str


def store_text(text: str) -> str:
    """Text as Node's drivers store it: a lone surrogate becomes U+FFFD."""
    return _LONE_SURROGATE.sub("\ufffd", text)


def _string(text: str) -> str:
    return f"'{text}'"


def _national_string(text: str) -> str:
    return f"N'{text}'"


class Dialect:
    """The SQL of one client's dialect."""

    __slots__ = ("now", "sql", "wrap_string")

    def __init__(self, sql: SqlClientService) -> None:
        self.sql = sql
        # SYSDATETIME: GETDATE() rounds to 1/300 s and can land in the
        # future, hiding freshly written visible_at values from a poll
        self.now: Fragment = sql.on_dialect_or_else(
            mssql=lambda: sql.literal("SYSDATETIME()"),
            mysql=lambda: sql.literal("NOW()"),
            pg=lambda: sql.literal("NOW()"),
            or_else=lambda: sql.literal("CURRENT_TIMESTAMP"),
        )
        self.wrap_string: Callable[[str], str] = sql.on_dialect_or_else(
            mssql=lambda: _national_string, or_else=lambda: _string
        )

    def string_literal(self, text: str) -> Statement[Row]:
        """``text`` (a UUID this store made) as a string literal."""
        return self.sql.unsafe(self.wrap_string(text))

    def seconds_offset(self, seconds: int) -> Fragment:
        """The database's now plus ``seconds`` (a whole number, maybe
        negative)."""
        sql = self.sql
        s = sql.unsafe(str(seconds))
        return sql.on_dialect_or_else(
            pg=lambda: sql("{} + INTERVAL '{} seconds'", self.now, s),
            mysql=lambda: sql("DATE_ADD({}, INTERVAL {} SECOND)", self.now, s),
            mssql=lambda: sql("DATEADD(SECOND, {}, {})", s, self.now),
            or_else=lambda: sql("datetime({}, '{} seconds')", self.now, s),
        )

    def seconds_ago(self, duration: Duration) -> Fragment:
        return self.seconds_offset(-max(math.ceil(duration.to_seconds()), 0))

    def sqlite_offset(self, seconds: int) -> Fragment:
        """SQLite's now plus ``seconds``, keeping milliseconds:
        ``CURRENT_TIMESTAMP`` drops the current second's fraction, so
        ``visible_at`` deadlines and the readiness check share this clock."""
        sql = self.sql
        return sql("strftime('%Y-%m-%d %H:%M:%f', 'now', '{} seconds')", sql.unsafe(str(seconds)))

    def visible_after(self, delay: Duration) -> Fragment:
        """When a delayed offer or a retry becomes visible, never before
        ``delay`` elapses: PostgreSQL reads ``clock_timestamp()`` (``NOW()``
        is fixed at the transaction's start); MySQL stores whole seconds and
        its ``NOW()`` drops the current fraction, so it gets a second more."""
        sql = self.sql
        seconds = max(math.ceil(delay.to_seconds()), 0)
        return sql.on_dialect_or_else(
            pg=lambda: sql("clock_timestamp() + INTERVAL '{} seconds'", sql.unsafe(str(seconds))),
            mysql=lambda: self.seconds_offset(seconds + 1),
            mssql=lambda: self.seconds_offset(seconds),
            or_else=lambda: self.sqlite_offset(seconds),
        )


type OfferStatement = Callable[[str, str, str, Fragment], Effect[object, SqlError]]
type PollStatement = Callable[[str, int, int, Fragment], Effect[Sequence[Row], SqlError]]
type CleanupBatch = Callable[[str, Duration], Effect[int, SqlError]]
type ReplaceExecuted = Callable[[str, str, Effect[object, SqlError]], Effect[object, SqlError]]


def replace_executed_statement(dialect: Dialect, table_name: str) -> ReplaceExecuted:
    """Run ``insert`` for an ``"untilExecuted"`` offer of id ``id`` in queue
    ``name``, first deleting that id's completed or failed row so the
    re-offer is stored as a new row with a fresh sequence. The plain read
    keeps new ids lock-free, since under MySQL's repeatable read deleting an
    absent key takes gap locks that deadlock concurrent inserts. The delete
    re-checks the state and shares a transaction with the insert, so
    concurrent offers of the id wait on the deleted row and then see the
    re-offer."""
    sql = dialect.sql
    table = sql.identifier(table_name)

    def replace(id: str, name: str, insert: Effect[object, SqlError]) -> Effect[object, SqlError]:
        def then(rows: Sequence[Row]) -> Effect[object, SqlError]:
            if not rows:
                return insert
            return sql.with_transaction(
                sql(
                    "DELETE FROM {} WHERE sequence = {} AND state IN ('completed', 'failed')",
                    table,
                    rows[0]["sequence"],
                ).and_then(insert)
            )

        return sql(
            "SELECT sequence FROM {} WHERE {} AND {} AND state IN ('completed', 'failed')",
            table,
            key_equals(sql, "id", id),
            key_equals(sql, "queue_name", name),
        ).flat_map(then)

    return replace


MYSQL_KEY_BYTES: Final = 1020
"""The bytes of MySQL's ``id`` and ``queue_name`` columns (``VARBINARY(1020)``)."""

MYSQL_ELEMENT_BYTES: Final = 16_777_215
"""The bytes of MySQL's ``element`` column (``MEDIUMTEXT``)."""


def _too_long(column: str, limit: int) -> SqlError:
    message = f"The {column} is longer than its column ({limit} bytes of UTF-8)"
    return SqlError(reason=ConstraintError(cause=None, message=message, operation="offer"))


def offer_statement(dialect: Dialect, table_name: str) -> OfferStatement:
    sql = dialect.sql
    table = sql.identifier(table_name)
    now = dialect.now

    def pg() -> OfferStatement:
        return lambda id, name, element, visible_at: sql(
            "INSERT INTO {} (id, queue_name, element, state, attempts, visible_at, created_at, "
            "updated_at) VALUES ({}, {}, {}, 'pending', 0, {}, {}, {}) "
            "ON CONFLICT (id, queue_name) DO NOTHING",
            table,
            id,
            name,
            element,
            visible_at,
            now,
            now,
        )

    def mysql() -> OfferStatement:
        # INSERT IGNORE, as in Effect: it only takes a shared lock on a
        # duplicate's (id, queue_name) entry. ON DUPLICATE KEY UPDATE then
        # also locks the row's primary key, the reverse of the order an
        # untilExecuted re-offer's DELETE locks them in, and deadlocks it.
        # IGNORE would cut a value longer than its column (so a second id
        # sharing the kept bytes is dropped as a duplicate), so such a value
        # fails here instead.
        def offer(
            id: str, name: str, element: str, visible_at: Fragment
        ) -> Effect[object, SqlError]:
            for column, value, limit in (
                ("id", id, MYSQL_KEY_BYTES),
                ("queue_name", name, MYSQL_KEY_BYTES),
                ("element", element, MYSQL_ELEMENT_BYTES),
            ):
                if len(value.encode("utf-8", "surrogatepass")) > limit:
                    return fail(_too_long(column, limit))
            return sql(
                "INSERT IGNORE INTO {} (id, queue_name, element, state, attempts, visible_at, "
                "created_at, updated_at) VALUES ({}, {}, {}, 'pending', 0, {}, {}, {})",
                table,
                id,
                name,
                element,
                visible_at,
                now,
                now,
            )

        return offer

    def mssql() -> OfferStatement:
        # No MERGE WITH (HOLDLOCK), whose range locks deadlock concurrent
        # offers: READCOMMITTEDLOCK makes the check wait for an uncommitted
        # duplicate; a duplicate inserted after it raises 2601 / 2627 with
        # XACT_ABORT off, so the caller's transaction survives; the nested
        # sp_executesql restores XACT_ABORT on exit.
        def escape(name: str) -> str:
            return "[" + name.replace("]", "]]").replace(".", "].[") + "]"

        escaped = escape(table_name)
        index = escape(f"idx_{table_name}_id")
        offer_sql = (
            "SET XACT_ABORT OFF; BEGIN TRY IF NOT EXISTS (SELECT 1 FROM "
            f"{escaped} WITH (READCOMMITTEDLOCK, FORCESEEK, INDEX({index})) "
            "WHERE id = @id AND queue_name = @name "
            "AND DATALENGTH(id) = DATALENGTH(@id) AND DATALENGTH(queue_name) = DATALENGTH(@name)) "
            f"INSERT INTO {escaped} (id, queue_name, element, state, attempts, visible_at, "
            "created_at, updated_at) VALUES (@id, @name, @element, 'pending', 0, @visible_at, "
            "SYSDATETIME(), SYSDATETIME()); END TRY BEGIN CATCH "
            "IF ERROR_NUMBER() NOT IN (2601, 2627) OR XACT_STATE() = -1 BEGIN "
            "IF @xact_abort <> 0 SET XACT_ABORT ON; THROW; END END CATCH"
        )
        return lambda id, name, element, visible_at: sql(
            "DECLARE @visible_at DATETIME2 = {}; DECLARE @xact_abort INT = @@OPTIONS & 16384; "
            "EXEC sp_executesql {}, N'@id NVARCHAR(MAX), @name NVARCHAR(MAX), "
            "@element NVARCHAR(MAX), @visible_at DATETIME2, @xact_abort INT', "
            "@id = {}, @name = {}, @element = {}, @visible_at = @visible_at, "
            "@xact_abort = @xact_abort;",
            visible_at,
            offer_sql,
            id,
            name,
            element,
        )

    def sqlite() -> OfferStatement:
        return lambda id, name, element, visible_at: sql(
            "INSERT OR IGNORE INTO {} (id, queue_name, element, state, attempts, visible_at, "
            "created_at, updated_at) VALUES ({}, {}, {}, 'pending', 0, {}, {}, {})",
            table,
            id,
            name,
            element,
            visible_at,
            now,
            now,
        )

    return sql.on_dialect_or_else(pg=pg, mysql=mysql, mssql=mssql, or_else=sqlite)


def poll_statement(dialect: Dialect, table_name: str, expires_at: Fragment) -> PollStatement:
    """Claim up to ``size`` visible rows of queue ``name`` under ``lock``,
    counting an attempt, oldest first."""
    sql = dialect.sql
    table = sql.identifier(table_name)
    now = dialect.now

    def pg() -> PollStatement:
        return lambda name, max_attempts, size, lock: sql(
            "WITH cte AS (UPDATE {table} SET acquired_at = {now}, acquired_by = {lock}, "
            "attempts = attempts + 1 WHERE sequence IN (SELECT sequence FROM {table} "
            "WHERE queue_name = {name} AND state = 'pending' AND attempts < {max_attempts} "
            "AND visible_at <= {now} AND (acquired_at IS NULL OR acquired_at < {expires_at}) "
            "ORDER BY visible_at ASC, sequence ASC FOR UPDATE SKIP LOCKED LIMIT {size}) "
            "RETURNING sequence, id, element, attempts, visible_at) "
            "SELECT sequence, id, element, attempts FROM cte ORDER BY visible_at ASC, sequence ASC",
            table=table,
            now=now,
            lock=lock,
            name=name,
            max_attempts=max_attempts,
            expires_at=expires_at,
            size=sql.unsafe(str(size)),
        )

    def mysql() -> PollStatement:
        def poll(name: str, max_attempts: int, size: int, lock: Fragment) -> Effect[Any, SqlError]:
            def claim(rows: Sequence[Row]) -> Effect[object, SqlError]:
                if not rows:
                    return void
                sequences = ",".join(str(row["sequence"]) for row in rows)
                return sql(
                    "UPDATE {} SET acquired_at = {}, acquired_by = {}, attempts = attempts + 1 "
                    "WHERE sequence IN ({})",
                    table,
                    now,
                    lock,
                    sql.unsafe(sequences),
                ).unprepared

            def counted(rows: Sequence[Row]) -> list[Row]:
                return [{**row, "attempts": column_int(row["attempts"]) + 1} for row in rows]

            return sql.with_transaction(
                sql(
                    "SELECT sequence, id, element, attempts FROM {} q WHERE queue_name = {} "
                    "AND state = 'pending' AND attempts < {} AND visible_at <= {} "
                    "AND (acquired_at IS NULL OR acquired_at < {}) "
                    "ORDER BY visible_at ASC, sequence ASC LIMIT {} FOR UPDATE SKIP LOCKED",
                    table,
                    name,
                    max_attempts,
                    now,
                    expires_at,
                    sql.unsafe(str(size)),
                )
                .tap(claim)
                .map(counted)
            )

        return poll

    def mssql() -> PollStatement:
        # READPAST skips rows another claim or a settlement holds instead of
        # deadlocking with them
        return lambda name, max_attempts, size, lock: sql(
            "WITH cte AS (SELECT TOP {size} sequence FROM {table} "
            "WITH (UPDLOCK, READPAST, ROWLOCK) "
            "WHERE {queue} AND state = 'pending' AND attempts < {max_attempts} "
            "AND visible_at <= {now} AND (acquired_at IS NULL OR acquired_at < {expires_at}) "
            "ORDER BY visible_at ASC, sequence ASC) "
            "UPDATE q SET acquired_at = {now}, acquired_by = {lock}, attempts = q.attempts + 1 "
            "OUTPUT inserted.sequence, inserted.id, inserted.element, inserted.attempts "
            "FROM {table} AS q INNER JOIN cte ON q.sequence = cte.sequence",
            table=table,
            now=now,
            lock=lock,
            queue=key_equals(sql, "queue_name", name),
            max_attempts=max_attempts,
            expires_at=expires_at,
            size=sql.unsafe(str(size)),
        )

    def sqlite() -> PollStatement:
        return lambda name, max_attempts, size, lock: sql(
            "UPDATE {table} SET acquired_at = {now}, acquired_by = {lock}, "
            "attempts = attempts + 1 WHERE sequence IN (SELECT sequence FROM {table} "
            "WHERE queue_name = {name} AND state = 'pending' AND attempts < {max_attempts} "
            "AND visible_at <= {ready} AND (acquired_at IS NULL OR acquired_at < {expires_at}) "
            "ORDER BY visible_at ASC, sequence ASC LIMIT {size}) "
            "RETURNING sequence, id, element, attempts",
            table=table,
            now=now,
            ready=dialect.sqlite_offset(0),
            lock=lock,
            name=name,
            max_attempts=max_attempts,
            expires_at=expires_at,
            size=sql.unsafe(str(size)),
        )

    return sql.on_dialect_or_else(pg=pg, mysql=mysql, mssql=mssql, or_else=sqlite)


def cleanup_statement(dialect: Dialect, table_name: str) -> CleanupBatch:
    """Delete up to a batch of rows in ``state`` last updated more than
    ``seconds`` ago; the number deleted."""
    sql = dialect.sql
    table = sql.identifier(table_name)
    limit = sql.unsafe(_BATCH_LIMIT)

    def pg() -> CleanupBatch:
        return lambda state, seconds: sql(
            "WITH deleted_entries AS (DELETE FROM {} WHERE sequence IN (SELECT sequence FROM {} "
            "WHERE state = {} AND updated_at <= {} LIMIT {}) RETURNING 1) "
            "SELECT COUNT(*)::INT AS count FROM deleted_entries",
            table,
            table,
            state,
            dialect.seconds_ago(seconds),
            limit,
        ).map(lambda rows: column_int(rows[0]["count"]))

    def mysql() -> CleanupBatch:
        def run(state: str, seconds: Duration) -> Effect[int, SqlError]:
            statement, params = sql(
                "DELETE FROM {} WHERE state = {} AND updated_at <= {} LIMIT {}",
                table,
                state,
                dialect.seconds_ago(seconds),
                limit,
            ).compile()

            def body() -> Generator[Effect[Any, SqlError, Scope], Any, int]:
                connection = yield from sql.reserve
                yield from connection.execute(statement, params, None)
                rows = yield from connection.execute_values("SELECT ROW_COUNT()", ())
                return column_int(rows[0][0])

            return scoped(gen(body))

        return run

    def mssql() -> CleanupBatch:
        return lambda state, seconds: sql(
            "DELETE TOP ({}) FROM {} OUTPUT DELETED.sequence WHERE state = {} AND updated_at <= {}",
            limit,
            table,
            state,
            dialect.seconds_ago(seconds),
        ).map(len)

    def sqlite() -> CleanupBatch:
        return lambda state, seconds: sql(
            "DELETE FROM {} WHERE sequence IN (SELECT sequence FROM {} "
            "WHERE state = {} AND updated_at <= {} LIMIT {}) RETURNING 1 AS deleted",
            table,
            table,
            state,
            dialect.seconds_ago(seconds),
            limit,
        ).map(len)

    return sql.on_dialect_or_else(pg=pg, mysql=mysql, mssql=mssql, or_else=sqlite)


class Settlements:
    """The statements that settle or renew this store's claims. Each only
    matches the claim it belongs to (its sequence and poll lock), so a
    stale settlement never touches a newer claim of the same row."""

    __slots__ = ("_ack_schedule", "_dialect", "_table", "held")

    def __init__(
        self, dialect: Dialect, table_name: str, ack_schedule: Schedule[object, object]
    ) -> None:
        self._dialect = dialect
        self._table = dialect.sql.identifier(table_name)
        self._ack_schedule = ack_schedule
        self.held: dict[Element, None] = {}
        """The claims this store holds, renewed by ``refresh_locks``."""

    def refresh_locks(self) -> Effect[object, SqlError]:
        if not self.held:
            return void
        sql = self._dialect.sql
        sequences = dict.fromkeys(str(element.sequence) for element in self.held)
        locks = dict.fromkeys(self._dialect.wrap_string(element.lock) for element in self.held)
        # a row only carries the lock of the poll that claimed it, so matching
        # every held sequence against every held lock renews just this
        # store's own claims
        return sql(
            "UPDATE {} SET acquired_at = {} WHERE sequence IN ({}) AND acquired_by IN ({})",
            self._table,
            self._dialect.now,
            sql.unsafe(",".join(sequences)),
            sql.unsafe(",".join(locks)),
        )

    def _ack(self, element: Element, set_clause: Fragment) -> Effect[None]:
        sql = self._dialect.sql
        statement = sql(
            "UPDATE {} SET acquired_at = NULL, acquired_by = NULL, {} "
            "WHERE sequence = {} AND acquired_by = {}",
            self._table,
            set_clause,
            element.sequence,
            self._dialect.string_literal(element.lock),
        )
        return (
            statement.retry(self._ack_schedule)
            .or_die()
            .ensuring(sync(lambda: self.held.pop(element, None)))
            .as_void()
        )

    def complete(self, element: Element) -> Effect[None]:
        sql = self._dialect.sql
        return self._ack(element, sql("updated_at = {}, state = 'completed'", self._dialect.now))

    def fail(self, element: Element, cause: Cause[Any]) -> Effect[None]:
        sql = self._dialect.sql
        return self._ack(
            element,
            sql(
                "updated_at = {}, state = 'failed', last_failure = {}",
                self._dialect.now,
                cause.pretty(),
            ),
        )

    def retry(self, element: Element, delay: Duration, cause: Cause[Any]) -> Effect[None]:
        sql = self._dialect.sql
        return self._ack(
            element,
            sql(
                "updated_at = {}, visible_at = {}, last_failure = {}",
                self._dialect.now,
                self._dialect.visible_after(delay),
                cause.pretty(),
            ),
        )

    def interrupt(self, element: Element) -> Effect[None]:
        """Release the claim without counting its attempt."""
        return self._ack(element, self._dialect.sql.literal("attempts = attempts - 1"))
