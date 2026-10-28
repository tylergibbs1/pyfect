"""Ports of Effect's ``sql-pg/test/PgConnection.integration.test.ts`` and
``StartupParameters.integration.test.ts``, against a throwaway local
PostgreSQL (``_postgres.pg_server``; skipped without one).

Values are psycopg's: ``int8`` reads as ``int`` (Effect's ``BigInt``),
``bytea`` as ``bytes``, timestamps as ``datetime``; ``psycopg.types.json``'s
``Jsonb`` stands for ``PgTypes.jsonb``, and a naive ``datetime`` for
``PgTypes.timestamp`` (an aware one binds as ``timestamptz``, which
PostgreSQL converts to the session's ``TimeZone`` for a ``timestamp``
column).

Adapted: "closes statements it evicts from a full cache" counts with an
unprepared statement (psycopg evicts after preparing the next one, so a
prepared count would see one more). "closes a listener whose connection
stops responding" pauses a TCP proxy (``CancelGate.pause``) instead of the
sockets a ``stream`` factory made. "fails when the server refuses TLS"
reads libpq's message from the cause; the error's own message is
"PgConnection: Failed to connect".

Omitted:
- "closes statements parsed while a pipeline overfills the cache",
  "isolates errors between pipelined queries", "drains an interrupted
  pipelined query without cancelling its neighbors", "places pin requests
  between earlier and later pipelined queries", "reuses prepared statements
  across a pipeline": pipelining (``multiplex``) is not ported.
- "preserves a stale-plan error in a transaction and reparses after
  rollback", "preserves a missing-statement error in a transaction and
  reparses after rollback": psycopg drops its prepared statements after
  ``ALTER``, ``DROP``, ``DISCARD ALL`` or ``DEALLOCATE ALL``, so the next
  statement is parsed again and neither error happens.
- "prepares the same text once per parameter signature": psycopg keys its
  prepared statements by text and parameter types too, but binds a Python
  ``int`` by its size, so one ``int`` value cannot pick ``int4`` against
  ``int8`` as ``1`` against ``BigInt(2)`` does.
"""
# pyright: reportPrivateUsage=false

from collections.abc import Generator
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

import pytest

pytest.importorskip("psycopg")

from psycopg.types.json import Jsonb

import pyfect as fx
from pyfect import redacted, scope, testing
from pyfect.scope import Scope
from pyfect.sql import pg
from pyfect.sql.error import SqlError, UniqueViolation
from pyfect.sql.pg.connection import Field, Notification, PgConnection

from ._postgres import (
    PASSWORD,
    CancelGate,
    PgServer,
    wait_until_active,
    wait_until_advisory_lock,
)


def _connect(server: PgServer, **fields: Any) -> fx.Effect[PgConnection, SqlError, Scope]:
    return pg.connection.make(pg.PgConnectionConfig(url=server.url, **fields))


def _assert_interrupted_on_close(
    closing: fx.CloseableScope, notifications: fx.Dequeue[Notification, SqlError]
) -> Generator[Any, Any]:
    consumer = yield from scope.fork_scoped(notifications.take())
    yield from closing.close(fx.Success(None))
    exit_ = yield from consumer.await_exit()
    assert isinstance(exit_, fx.Failure)
    assert exit_.cause.has_interrupts_only


@testing.live
def test_interrupts_notification_consumers_when_the_connection_scope_closes(
    pg_server: PgServer,
):
    """interrupts notification consumers when the connection scope closes"""
    closing = yield from (yield from Scope()).fork()
    connection = yield from _connect(pg_server).pipe(fx.provide_service(Scope, closing))
    notifications = yield from connection.listen("closed_listener")
    yield from _assert_interrupted_on_close(closing, notifications)


@testing.live
def test_interrupts_notification_consumers_when_the_listener_scope_closes(pg_server: PgServer):
    """interrupts notification consumers when the listener scope closes"""
    closing = yield from (yield from Scope()).fork()
    connection = yield from _connect(pg_server)
    notifications = yield from connection.listen("closed_listener").pipe(
        fx.provide_service(Scope, closing)
    )
    yield from _assert_interrupted_on_close(closing, notifications)


@testing.live(timeout=30)
def test_closes_a_listener_whose_connection_stops_responding(cancel_gate: CancelGate):
    """closes a listener whose connection stops responding"""
    connection = yield from pg.connection.make(pg.PgConnectionConfig(url=cancel_gate.url))
    listen_scope = fx.CloseableScope()
    yield from connection.listen("unanswered_listener").pipe(
        fx.provide_service(Scope, listen_scope)
    )
    cancel_gate.pause()
    closing = yield from listen_scope.close(fx.Success(None)).fork()
    closed = yield from closing.await_exit().timeout_option(10)
    assert closed is not None, "listener scope did not close within 10 seconds"
    assert isinstance((yield from connection.query("SELECT 1").exit()), fx.Failure)


@testing.live(timeout=30)
def test_keeps_a_busy_pinned_session_when_a_listener_closes(pg_server: PgServer):
    """keeps a busy pinned session when a listener closes"""
    connection = yield from _connect(pg_server)
    observer = yield from _connect(pg_server)
    pinned = yield from connection.pin
    listen_scope = fx.CloseableScope()
    yield from pinned.listen("busy_listener").pipe(fx.provide_service(Scope, listen_scope))
    slow = yield from pinned.query("SELECT pg_sleep(6)").fork()
    yield from wait_until_active(observer, pinned.process_id)
    yield from listen_scope.close(fx.Success(None))
    yield from slow.join()
    result = yield from pinned.query("SELECT 1 AS one")
    assert result.rows == [{"one": 1}]


@testing.live
def test_skips_unlisten_queued_behind_a_pin_release(pg_server: PgServer):
    """skips UNLISTEN queued behind a pin release"""
    connection = yield from _connect(pg_server)
    pin_scope = fx.CloseableScope()
    pinned = yield from connection.pin.pipe(fx.provide_service(Scope, pin_scope))
    listen_scope = fx.CloseableScope()
    yield from pinned.listen("released_listener").pipe(fx.provide_service(Scope, listen_scope))
    # Queue the listener cleanup behind a statement that holds the session.
    closing = yield from fx.yield_now().and_then(listen_scope.close(fx.Success(None))).fork()
    yield from pinned.query("SELECT pg_sleep(0.05)")
    yield from pin_scope.close(fx.Success(None))
    following = yield from connection.query("SELECT 1 AS one").fork()
    result = yield from following.join().timeout(2)
    assert result.rows == [{"one": 1}]
    yield from closing.join()


@testing.effect
def test_connects_through_ready_for_query(pg_server: PgServer):
    """connects through ReadyForQuery"""
    connection = yield from _connect(pg_server)
    assert connection.process_id > 0


@testing.effect
def test_runs_unnamed_extended_queries_with_inferred_binary_parameters(pg_server: PgServer):
    """runs unnamed extended queries with inferred binary parameters"""
    connection = yield from _connect(pg_server)
    instant = datetime(2024, 5, 6, 7, 8, 9, 123000, tzinfo=UTC)
    result = yield from connection.query(
        "SELECT $1::int4 AS i, $2::float8 AS f, $3::int8 AS b, $4::bool AS flag, "
        "$5::text AS text, $6::bytea AS bytes, $7::timestamptz AS instant, "
        "$8::int4[] AS numbers, $9::text AS nil, $10::jsonb AS jsonb",
        [
            1,
            1.5,
            2,
            True,
            "hello",
            bytes([1, 255]),
            instant,
            [1, None, 3],
            None,
            Jsonb({"nested": True}),
        ],
    )
    assert result.command == "SELECT"
    assert result.row_count == 1
    assert result.oid is None
    assert result.rows == [
        {
            "i": 1,
            "f": 1.5,
            "b": 2,
            "flag": True,
            "text": "hello",
            "bytes": bytes([1, 255]),
            "instant": instant,
            "numbers": [1, None, 3],
            "nil": None,
            "jsonb": {"nested": True},
        }
    ]
    assert [field.name for field in result.fields] == [
        "i",
        "f",
        "b",
        "flag",
        "text",
        "bytes",
        "instant",
        "numbers",
        "nil",
        "jsonb",
    ]


@testing.effect
def test_applies_the_session_time_zone_only_to_dates_bound_into_timestamp_columns(
    pg_server: PgServer,
):
    """applies the session TimeZone only to Dates bound into timestamp columns"""
    connection = yield from _connect(pg_server)
    instant = datetime(2024, 5, 6, 7, 8, 9, 123000, tzinfo=UTC)
    naive = instant.replace(tzinfo=None)
    yield from connection.query(
        "CREATE TEMP TABLE timestamp_timezone"
        " (bare timestamp, explicit timestamp, zoned timestamptz)"
    )
    berlin = timezone(timedelta(hours=2))
    for zone, expected_bare in (("UTC", naive), ("Europe/Berlin", instant.astimezone(berlin))):
        yield from connection.query(f"SET TIME ZONE '{zone}'")
        yield from connection.query("TRUNCATE timestamp_timezone")
        yield from connection.query(
            "INSERT INTO timestamp_timezone VALUES ($1, $2, $3)", [instant, naive, instant]
        )
        result = yield from connection.query("SELECT * FROM timestamp_timezone")
        assert result.rows == [
            {"bare": expected_bare.replace(tzinfo=None), "explicit": naive, "zoned": instant}
        ]


@testing.effect
def test_returns_query_values_in_row_description_order(pg_server: PgServer):
    """returns queryValues in RowDescription order"""
    connection = yield from _connect(pg_server)
    rows = yield from connection.query_values(
        "SELECT $1::int8 AS second, $2::text AS first", [7, "value"]
    )
    assert rows == [(7, "value")]


@testing.effect
def test_drains_query_errors_and_keeps_the_connection_usable(pg_server: PgServer):
    """drains query errors and keeps the connection usable"""
    connection = yield from _connect(pg_server)
    yield from connection.query("CREATE TEMP TABLE pg_connection_unique (value int4 UNIQUE)")
    yield from connection.query("INSERT INTO pg_connection_unique VALUES ($1)", [1])
    error = yield from connection.query("INSERT INTO pg_connection_unique VALUES ($1)", [1]).flip()
    assert isinstance(error.reason, UniqueViolation)
    assert "pg_connection_unique" in error.reason.constraint
    result = yield from connection.query("SELECT count(*)::int8 AS count FROM pg_connection_unique")
    assert result.rows == [{"count": 1}]


@testing.effect
def test_binds_untyped_strings_and_integers_beyond_int4(pg_server: PgServer):
    """binds untyped strings and integers beyond int4"""
    connection = yield from _connect(pg_server)
    yield from connection.query("CREATE TEMP TABLE inference_widening (id bigint, at timestamptz)")
    yield from connection.query(
        "INSERT INTO inference_widening (id, at) VALUES ($1, $2)",
        ["12345678901234", "2024-05-06T07:08:09Z"],
    )
    yield from connection.query("INSERT INTO inference_widening (id) VALUES ($1)", [1755000000000])
    rows = yield from connection.query_values("SELECT id FROM inference_widening ORDER BY id")
    assert [row[0] for row in rows] == [1755000000000, 12345678901234]


@testing.effect
def test_reparses_a_statement_whose_first_execution_failed_at_bind(pg_server: PgServer):
    """reparses a statement whose first execution failed at bind"""
    connection = yield from _connect(pg_server)
    missing = yield from connection.query("select $1::regclass", ["prepared_bind_failure"]).flip()
    assert missing.reason._tag == "SqlSyntaxError"
    yield from connection.query("CREATE TEMP TABLE prepared_bind_failure (id int)")
    found = yield from connection.query("select $1::regclass AS rel", ["prepared_bind_failure"])
    assert len(found.rows) == 1


@testing.effect
def test_fails_with_authentication_error_on_a_bad_password(pg_server: PgServer):
    """fails with AuthenticationError on a bad password"""
    error = yield from fx.scoped(
        pg.connection.make(
            pg.PgConnectionConfig(
                host=pg_server.host,
                port=pg_server.port,
                username="postgres",
                password=redacted.make("definitely-wrong"),
                database="postgres",
            )
        )
    ).flip()
    assert isinstance(error, SqlError)
    assert error.reason._tag == "AuthenticationError"


@testing.effect
def test_fails_when_the_server_refuses_tls(pg_server: PgServer):
    """fails when the server refuses TLS"""
    error = yield from fx.scoped(
        pg.connection.make(
            pg.PgConnectionConfig(
                host=pg_server.host,
                port=pg_server.port,
                username="postgres",
                password=redacted.make(PASSWORD),
                database="postgres",
                ssl=True,
            )
        )
    ).flip()
    assert error.reason._tag == "ConnectionError"
    assert "SSL" in str(error.reason.cause)


@testing.effect
def test_reuses_a_prepared_statement_and_keeps_its_columns(pg_server: PgServer):
    """reuses a prepared statement and keeps its columns"""
    connection = yield from _connect(pg_server)
    for index in range(3):
        result = yield from connection.query(
            "SELECT $1::int4 AS value, $2::text AS label", [index, "x"]
        )
        assert result.rows == [{"value": index, "label": "x"}]
        assert result.fields == (Field("value", 23), Field("label", 25))
    prepared = yield from connection.query("SELECT count(*)::int4 AS n FROM pg_prepared_statements")
    assert prepared.rows[0] == {"n": 2}


@testing.effect
def test_re_parses_a_statement_whose_result_type_changed(pg_server: PgServer):
    """re-parses a statement whose result type changed"""
    connection = yield from _connect(pg_server)
    yield from connection.query("CREATE TEMP TABLE shifting (a int)")
    yield from connection.query("INSERT INTO shifting VALUES (1)")
    assert (yield from connection.query("SELECT * FROM shifting")).rows == [{"a": 1}]
    yield from connection.query("ALTER TABLE shifting ADD COLUMN b text DEFAULT 'added'")
    after = yield from connection.query("SELECT * FROM shifting")
    assert after.rows == [{"a": 1, "b": "added"}]
    assert after.fields == (Field("a", 23), Field("b", 25))


@testing.effect
def test_re_parses_a_statement_the_backend_no_longer_holds(pg_server: PgServer):
    """re-parses a statement the backend no longer holds"""
    connection = yield from _connect(pg_server)
    assert (yield from connection.query("SELECT $1::int4 AS n", [7])).rows == [{"n": 7}]
    yield from connection.query("DEALLOCATE ALL")
    assert (yield from connection.query("SELECT $1::int4 AS n", [8])).rows == [{"n": 8}]


@testing.effect
def test_closes_statements_it_evicts_from_a_full_cache(pg_server: PgServer):
    """closes statements it evicts from a full cache"""
    connection = yield from _connect(pg_server, prepared_statement_cache_size=3)
    for _ in range(2):
        for index in range(8):
            result = yield from connection.query(f"SELECT {index}::int4 AS n, $1::text AS t", ["v"])
            assert result.rows == [{"n": index, "t": "v"}]
    held = yield from connection.query(
        "SELECT count(*)::int4 AS n FROM pg_prepared_statements", prepare=False
    )
    assert held.rows[0] == {"n": 3}


@testing.effect
def test_parses_every_statement_when_prepare_is_off(pg_server: PgServer):
    """parses every statement when prepare is off"""
    connection = yield from _connect(pg_server, prepare=False)
    for index in range(3):
        assert (yield from connection.query("SELECT $1::int4 AS n", [index])).rows == [{"n": index}]
    held = yield from connection.query("SELECT count(*)::int4 AS n FROM pg_prepared_statements")
    assert held.rows[0] == {"n": 0}


@testing.effect
def test_stays_usable_after_a_statement_the_server_refuses_to_parse(pg_server: PgServer):
    """stays usable after a statement the server refuses to parse"""
    connection = yield from _connect(pg_server)
    missing = yield from connection.query("SELECT * FROM does_not_exist").flip()
    assert missing.reason._tag == "SqlSyntaxError"
    syntax = yield from connection.query("SELECT FROM WHERE ????").flip()
    assert syntax.reason._tag == "SqlSyntaxError"
    assert (yield from connection.query("SELECT 42::int4 AS answer")).rows == [{"answer": 42}]


@testing.effect
def test_closes_a_statement_whose_plan_it_had_to_throw_away(pg_server: PgServer):
    """closes a statement whose plan it had to throw away"""
    connection = yield from _connect(pg_server)
    yield from connection.query("CREATE TEMP TABLE churn (a int)")
    for round_ in range(4):
        yield from connection.query("SELECT * FROM churn")
        yield from connection.query(f"ALTER TABLE churn ADD COLUMN c{round_} text")
    yield from connection.query("SELECT * FROM churn")
    held = yield from connection.query(
        "SELECT count(*)::int4 AS n FROM pg_prepared_statements"
        " WHERE statement = 'SELECT * FROM churn'"
    )
    assert held.rows[0] == {"n": 1}


@testing.effect
def test_re_parses_a_statement_first_prepared_in_a_rolled_back_transaction(pg_server: PgServer):
    """re-parses a statement first prepared in a rolled back transaction"""
    connection = yield from _connect(pg_server)
    yield from connection.query("CREATE TEMP TABLE rolled_back (a int)")
    yield from connection.query("BEGIN")
    yield from connection.query("INSERT INTO rolled_back VALUES ($1::int4)", [1])
    yield from connection.query("ROLLBACK")
    yield from connection.query("INSERT INTO rolled_back VALUES ($1::int4)", [2])
    yield from connection.query("INSERT INTO rolled_back VALUES ($1::int4)", [3])
    rows = (yield from connection.query("SELECT a FROM rolled_back ORDER BY a")).rows
    assert rows == [{"a": 2}, {"a": 3}]


@testing.live
def test_orders_ordinary_statements_against_a_stream_on_the_same_session(pg_server: PgServer):
    """orders ordinary statements against a stream on the same session"""
    connection = yield from _connect(pg_server)
    streamed = yield from scope.fork_scoped(
        connection.stream("SELECT generate_series(1, 200) AS n").run_collect()
    )
    queried = yield from scope.fork_scoped(
        fx.all(
            *[connection.query("SELECT $1::int4 AS n", [index]) for index in range(12)],
            concurrency="unbounded",
        )
    )
    rows = yield from streamed.join()
    assert len(rows) == 200
    results = yield from queried.join()
    for index, result in enumerate(results):
        assert result.rows == [{"n": index}]
    assert (yield from connection.query("SELECT 1 AS ok")).rows == [{"ok": 1}]


@testing.effect
def test_fails_work_through_a_released_pin_without_touching_the_next_owners_session(
    pg_server: PgServer,
):
    """fails work through a released pin without touching the next owner's session"""
    connection = yield from _connect(pg_server)
    released = yield from fx.scoped(connection.pin)

    def owning():
        owner = yield from connection.pin
        yield from owner.query("BEGIN")
        yield from owner.query("SET LOCAL application_name = 'next_owner'")
        exits = [
            (yield from released.query("ROLLBACK").exit()),
            (yield from released.query_values("ROLLBACK").exit()),
            (yield from released.stream("SELECT 1").run_collect().exit()),
            (yield from fx.scoped(released.listen("released_pin")).exit()),
        ]
        for exit_ in exits:
            assert isinstance(exit_, fx.Failure)
        setting = yield from owner.query("SELECT current_setting('application_name') AS name")
        assert setting.rows == [{"name": "next_owner"}]
        yield from owner.query("ROLLBACK")

    yield from fx.scoped(fx.gen(owning))


@testing.live
def test_fails_a_statement_that_was_queued_on_a_pin_before_its_release(pg_server: PgServer):
    """fails a statement that was queued on a pin before its release"""
    connection = yield from _connect(pg_server)
    pin_scope = fx.CloseableScope()
    pinned = yield from connection.pin.pipe(fx.provide_service(Scope, pin_scope))
    queued = yield from scope.fork_scoped(
        fx.yield_now().and_then(pinned.query("SELECT 1 AS queued"))
    )
    yield from pinned.query("SELECT 1 AS holder")
    yield from pin_scope.close(fx.Success(None))
    assert isinstance((yield from queued.await_exit()), fx.Failure)
    assert (yield from connection.query("SELECT 1 AS ok")).rows == [{"ok": 1}]


@testing.live
def test_ignores_interrupt_on_a_released_pin(pg_server: PgServer):
    """ignores interrupt on a released pin"""
    connection = yield from _connect(pg_server)
    blocker = yield from _connect(pg_server)
    observer = yield from _connect(pg_server)
    released = yield from fx.scoped(connection.pin)

    def waiting_on_lock():
        yield from blocker.query("BEGIN")
        yield from blocker.query("SELECT pg_advisory_xact_lock($1::int4)", [connection.process_id])
        waiting = yield from scope.fork_scoped(
            connection.query("SELECT pg_advisory_xact_lock($1::int4)", [connection.process_id])
        )
        # A cancel only lands while the backend is executing, so wait for the lock.
        yield from wait_until_advisory_lock(observer, connection.process_id)
        yield from released.interrupt
        return waiting

    waiting = yield from fx.gen(waiting_on_lock).ensuring(blocker.query("ROLLBACK").ignore())
    assert isinstance((yield from waiting.await_exit()), fx.Success)


# --- PostgreSQL startup defaults ------------------------------------------------


@testing.live
def test_preserves_named_and_opaque_defaults_across_replacement_and_reset_all(
    pg_server: PgServer,
):
    """preserves named and opaque defaults across replacement and RESET ALL"""
    pool = yield from pg.pool.make(
        pg.PgPoolConfig(
            url=pg_server.url,
            startup_parameters={"statement_timeout": "1234ms"},
            startup_options="-c lock_timeout=2345",
            max_connections=1,
        )
    )
    query = (
        "SELECT current_setting('statement_timeout') AS timeout,"
        " current_setting('lock_timeout') AS lock"
    )
    defaults = [{"timeout": "1234ms", "lock": "2345ms"}]

    def first_session():
        connection = yield from pool.get
        assert (yield from connection.query(query)).rows == defaults
        yield from pool.invalidate(connection)
        return connection.process_id

    first_pid = yield from fx.scoped(fx.gen(first_session))
    replacement = yield from pool.get
    assert replacement.process_id != first_pid
    assert (yield from replacement.query(query)).rows == defaults
    yield from replacement.query("SET statement_timeout = '5678ms'")
    yield from replacement.query("SET lock_timeout = '6789ms'")
    assert (yield from replacement.query(query)).rows == [{"timeout": "5678ms", "lock": "6789ms"}]
    yield from replacement.query("RESET ALL")
    assert (yield from replacement.query(query)).rows == defaults
