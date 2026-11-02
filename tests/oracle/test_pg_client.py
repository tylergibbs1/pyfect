"""Ports of Effect's ``sql-pg/test/Client.integration.test.ts``, against a
throwaway local PostgreSQL (``_postgres.pg_server``; skipped without one).

Each Effect ``it.layer`` block is a client built per test here: ``PgClient``
for ``layer``, ``make_client`` for the ``makeClient`` layers, with the
block's options. Effect's ``Date`` and ``Uint8Array`` are ``datetime`` and
``bytes``.

Adapted: "PgClient.makeClient surfaces transport creation failures"
connects to a port nothing listens on (libpq opens its own socket; there is
no ``stream`` factory). The ``PgClient listen`` block runs on a two-session
pool without ``multiplex`` (not ported: psycopg runs one statement at a time
per session), so a listener still reserves one session of two.
"""
# pyright: reportPrivateUsage=false

import time
import warnings
from collections.abc import Callable, Generator
from datetime import UTC, datetime
from typing import Any

import pytest

pytest.importorskip("psycopg")

import pyfect as fx
from pyfect import case, schedule, scope, stream, testing
from pyfect import schema as S
from pyfect.context import Reference, Tag
from pyfect.option import Some
from pyfect.schema import model as Model
from pyfect.sql import SqlClient, pg
from pyfect.sql import model as sql_model
from pyfect.sql.error import SqlError
from pyfect.sql.statement import default_transforms

from ._postgres import PgServer, refused_port

_compiler_transform = pg.make_compiler(case.camel_to_snake)
_transforms_nested = default_transforms(case.snake_to_camel)
_transforms = default_transforms(case.snake_to_camel, False)

type Body = Callable[[], Generator[Any, Any, Any]]


def _with_pool(server: PgServer, body: Body, **fields: Any) -> fx.Effect[Any, Any]:
    layer = pg.layer(pg.PgPoolConfig(url=server.url, **fields))
    return fx.scoped(fx.gen(body)).pipe(fx.provide(layer))


def _with_single(
    server: PgServer, body: Body, *, acquire_for_stream: bool = False, **fields: Any
) -> fx.Effect[Any, Any]:
    config = pg.PgClientConfig(url=server.url, **fields)
    layer = pg.layer_from(pg.make_client(config, acquire_for_stream=acquire_for_stream))
    return fx.scoped(fx.gen(body)).pipe(fx.provide(layer))


# --- PgClient ------------------------------------------------------------------


class _Entry(Model.Class):
    id: int = Model.field(Model.field_except(["insert"])(S.Int))
    created_at: datetime = Model.field(Model.DateTimeInsertFromDate)


@testing.effect
def test_round_trips_model_date_time_insert_from_date_through_a_repository(pg_server: PgServer):
    """round trips Model.DateTimeInsertFromDate through a repository"""

    def body():
        sql = yield from pg.PgClient()
        repo = yield from sql_model.make_repository(
            _Entry, table_name="model_timestamp", id_column="id", span_prefix="EntryRepository"
        )
        instant = datetime(2024, 5, 6, 7, 8, 9, 123000, tzinfo=UTC)

        def transaction():
            yield from sql("SET LOCAL TIME ZONE 'Europe/Berlin'")
            yield from sql(
                "CREATE TEMP TABLE model_timestamp (id SERIAL PRIMARY KEY, created_at TIMESTAMPTZ)"
                " ON COMMIT DROP"
            )
            inserted = yield from repo.insert(
                _Entry.insert.make({"created_at": Model.override(instant)})
            )
            assert inserted.created_at == instant
            assert inserted.created_at.tzinfo is UTC
            selected = yield from repo.find_by_id(inserted.id)
            assert selected == inserted
            assert selected.created_at == instant

        yield from sql.with_transaction(fx.gen(transaction))

    yield from _with_pool(pg_server, body)


@testing.effect
def test_insert_helper(pg_server: PgServer):
    """insert helper"""

    def body():
        sql = yield from pg.PgClient()
        query, params = sql(
            "INSERT INTO people {}", sql.insert({"name": "Tim", "age": 10})
        ).compile()
        assert query == 'INSERT INTO people ("name","age") VALUES ($1,$2)'
        assert params == ("Tim", 10)

    yield from _with_pool(pg_server, body)


@testing.effect
def test_update_values_helper(pg_server: PgServer):
    """updateValues helper"""

    def body():
        sql = yield from pg.PgClient()
        query, params = sql(
            "UPDATE people SET name = data.name FROM {}",
            sql.update_values([{"name": "Tim"}, {"name": "John"}], "data"),
        ).compile()
        assert query == (
            'UPDATE people SET name = data.name FROM (values ($1),($2)) AS "data"("name")'
        )
        assert params == ("Tim", "John")

    yield from _with_pool(pg_server, body)


@testing.effect
def test_update_values_helper_returning(pg_server: PgServer):
    """updateValues helper returning"""

    def body():
        sql = yield from pg.PgClient()
        query, params = sql(
            "UPDATE people SET name = data.name FROM {}",
            sql.update_values([{"name": "Tim"}, {"name": "John"}], "data").returning("*"),
        ).compile()
        assert query == (
            "UPDATE people SET name = data.name FROM (values ($1),($2)) "
            'AS "data"("name") RETURNING *'
        )
        assert params == ("Tim", "John")

    yield from _with_pool(pg_server, body)


@testing.effect
def test_update_helper(pg_server: PgServer):
    """update helper"""

    def body():
        sql = yield from pg.PgClient()
        query, params = sql("UPDATE people SET {}", sql.update({"name": "Tim"})).compile()
        assert query == 'UPDATE people SET "name" = $1'
        assert params == ("Tim",)
        query, params = sql(
            "UPDATE people SET {}", sql.update({"name": "Tim", "age": 10}, ["age"])
        ).compile()
        assert query == 'UPDATE people SET "name" = $1'
        assert params == ("Tim",)

    yield from _with_pool(pg_server, body)


@testing.effect
def test_update_helper_returning(pg_server: PgServer):
    """update helper returning"""

    def body():
        sql = yield from pg.PgClient()
        query, params = sql(
            "UPDATE people SET {}", sql.update({"name": "Tim"}).returning("*")
        ).compile()
        assert query == 'UPDATE people SET "name" = $1 RETURNING *'
        assert params == ("Tim",)

    yield from _with_pool(pg_server, body)


@testing.effect
def test_binds_an_empty_array_using_the_type_inferred_by_postgresql(pg_server: PgServer):
    """binds an empty array using the type inferred by PostgreSQL"""

    def body():
        sql = yield from SqlClient()
        ids: list[str] = []
        assert (yield from sql("SELECT 1 WHERE 'a' = ANY({})", ids)) == []

    yield from _with_pool(pg_server, body)


@testing.effect
def test_array_helper(pg_server: PgServer):
    """array helper"""

    def body():
        sql = yield from pg.PgClient()
        query, params = sql(
            "SELECT * FROM {} WHERE id IN {}", sql.identifier("people"), sql.in_([1, 2, "string"])
        ).compile()
        assert query == 'SELECT * FROM "people" WHERE id IN ($1,$2,$3)'
        assert params == (1, 2, "string")

    yield from _with_pool(pg_server, body)


@testing.effect
def test_array_helper_with_column(pg_server: PgServer):
    """array helper with column"""

    def body():
        sql = yield from pg.PgClient()
        people = sql.identifier("people")
        query, params = sql(
            "SELECT * FROM {} WHERE {}", people, sql.in_("id", [1, 2, "string"])
        ).compile()
        assert query == 'SELECT * FROM "people" WHERE "id" IN ($1,$2,$3)'
        assert params == (1, 2, "string")
        query, params = sql("SELECT * FROM {} WHERE {}", people, sql.in_("id", [])).compile()
        assert query == 'SELECT * FROM "people" WHERE 1=0'
        assert params == ()

    yield from _with_pool(pg_server, body)


@testing.effect
def test_and(pg_server: PgServer):
    """and"""

    def body():
        sql = yield from pg.PgClient()
        now = datetime.now(UTC)
        query, params = sql(
            "SELECT * FROM {} WHERE {}",
            sql.identifier("people"),
            sql.and_([sql.in_("name", ["Tim", "John"]), sql("created_at < {}", now)]),
        ).compile()
        assert query == 'SELECT * FROM "people" WHERE ("name" IN ($1,$2) AND created_at < $3)'
        assert params == ("Tim", "John", now)

    yield from _with_pool(pg_server, body)


def test_transform_nested():
    """transform nested"""
    rows = [{"a_key": 1, "nested": [{"b_key": 2}], "arr_primitive": [1, "2", True]}]
    assert _transforms_nested.array(rows) == [
        {"aKey": 1, "nested": [{"bKey": 2}], "arrPrimitive": [1, "2", True]}
    ]


def test_transform_non_nested():
    """transform non nested"""
    rows = [{"a_key": 1, "nested": [{"b_key": 2}], "arr_primitive": [1, "2", True]}]
    assert _transforms.array(rows) == [
        {"aKey": 1, "nested": [{"b_key": 2}], "arrPrimitive": [1, "2", True]}
    ]
    value = [1, True, None, "text"]
    json_rows = [{"json_field": {"test_value": value, "test_nested": {"test_value": value}}}]
    assert _transforms.array(json_rows) == [
        {"jsonField": {"test_value": value, "test_nested": {"test_value": value}}}
    ]


@testing.effect
def test_insert_fragments(pg_server: PgServer):
    """insert fragments"""

    def body():
        sql = yield from pg.PgClient()
        query, params = sql(
            "INSERT INTO people {}",
            sql.insert({"name": "Tim", "age": 10, "json": sql.json({"a": 1})}),
        ).compile()
        assert query == 'INSERT INTO people ("name","age","json") VALUES ($1,$2,$3)'
        assert len(params) == 3

    yield from _with_pool(pg_server, body)


@testing.effect
def test_update_fragments(pg_server: PgServer):
    """update fragments"""

    def body():
        sql = yield from pg.PgClient()
        now = datetime.now(UTC)
        query, params = sql(
            "UPDATE people SET json = data.json FROM {} WHERE created_at > {}",
            sql.update_values([{"json": sql.json({"a": 1})}, {"json": sql.json({"b": 1})}], "data"),
            now,
        ).compile()
        assert query == (
            "UPDATE people SET json = data.json FROM (values ($1),($2)) "
            'AS "data"("json") WHERE created_at > $3'
        )
        assert len(params) == 3

    yield from _with_pool(pg_server, body)


@testing.effect
def test_on_dialect(pg_server: PgServer):
    """onDialect"""

    def body():
        sql = yield from pg.PgClient()
        chosen = sql.on_dialect(
            sqlite=lambda: "A",
            pg=lambda: "B",
            mysql=lambda: "C",
            mssql=lambda: "D",
            clickhouse=lambda: "E",
        )
        assert chosen == "B"
        assert sql.on_dialect_or_else(or_else=lambda: "A", pg=lambda: "B") == "B"

    yield from _with_pool(pg_server, body)


@testing.effect
def test_identifier_transform(pg_server: PgServer):
    """identifier transform"""

    def body():
        sql = yield from pg.PgClient()
        query, _ = _compiler_transform.compile(
            sql("SELECT * from {}", sql.identifier("peopleTest")), False
        )
        assert query == 'SELECT * from "people_test"'

    yield from _with_pool(pg_server, body)


@testing.effect
def test_jsonb(pg_server: PgServer):
    """jsonb"""

    def body():
        sql = yield from pg.PgClient()
        rows = yield from sql("select {}::jsonb as json", sql.json({"testValue": 123}))
        assert rows[0]["json"] == {"testValue": 123}

    yield from _with_pool(pg_server, body)


@testing.effect
def test_reads_scalar_enums_as_strings_without_registering_their_oids(pg_server: PgServer):
    """reads scalar enums as strings without registering their OIDs"""

    def body():
        sql = yield from pg.PgClient()

        def transaction():
            yield from sql("CREATE TYPE capability_scalar AS ENUM ('use_key', 'manage', 'gérer')")
            rows = yield from sql(
                "SELECT 'use_key'::capability_scalar AS capability, "
                "{}::capability_scalar AS bound, NULL::capability_scalar AS nullable",
                "gérer",
            )
            yield from sql("DROP TYPE capability_scalar")
            assert rows == [{"capability": "use_key", "bound": "gérer", "nullable": None}]

        yield from sql.with_transaction(fx.gen(transaction))

    yield from _with_pool(pg_server, body)


@testing.effect
def test_reads_bytea_as_uint8array(pg_server: PgServer):
    """reads bytea as Uint8Array"""

    def body():
        sql = yield from pg.PgClient()
        payload = bytes([0, 1, 254, 255])
        rows = yield from sql("SELECT {}::bytea AS payload", payload)
        assert isinstance(rows[0]["payload"], bytes)
        assert rows == [{"payload": payload}]

    yield from _with_pool(pg_server, body)


@testing.effect
def test_stream(pg_server: PgServer):
    """stream"""

    def body():
        sql = yield from SqlClient()
        rows = yield from sql("SELECT generate_series(1, 3)").stream.run_collect()
        assert rows == [{"generate_series": 1}, {"generate_series": 2}, {"generate_series": 3}]

    yield from _with_pool(pg_server, body)


@testing.effect
def test_releases_completed_nested_transaction_locks(pg_server: PgServer):
    """releases completed nested transaction locks"""

    def body():
        sql = yield from pg.PgClient()
        locks = sql(
            "SELECT count(*)::integer AS count FROM pg_locks "
            "WHERE pid = pg_backend_pid() AND locktype = 'transactionid'"
        )

        def transaction():
            yield from sql("CREATE TEMP TABLE savepoint_locks (value INTEGER) ON COMMIT DROP")
            yield from sql.with_transaction(sql("INSERT INTO savepoint_locks VALUES (1)"))
            assert (yield from locks) == [{"count": 1}]
            error = yield from sql.with_transaction(
                sql("INSERT INTO savepoint_locks VALUES (2)").and_then(fx.fail("rollback"))
            ).flip()
            assert error == "rollback"
            assert (yield from locks) == [{"count": 1}]
            assert (yield from sql("SELECT value FROM savepoint_locks")) == [{"value": 1}]

        yield from sql.with_transaction(fx.gen(transaction))

    yield from _with_pool(pg_server, body)


@testing.live
def test_preserves_successful_concurrent_nested_transactions(pg_server: PgServer):
    """preserves successful concurrent nested transactions"""

    def body():
        sql = yield from pg.PgClient()
        first_started = yield from fx.Deferred[None].make()
        first_inserted = yield from fx.Deferred[None].make()

        def first():
            yield from first_started.succeed(None)
            yield from fx.sleep(0.1)
            yield from sql("INSERT INTO nested_transactions VALUES ('first')")
            yield from first_inserted.succeed(None)

        second = first_started.wait().and_then(
            sql.with_transaction(first_inserted.wait().and_then(fx.fail("rollback")))
        )

        def transaction():
            yield from sql("CREATE TEMP TABLE nested_transactions (value TEXT) ON COMMIT DROP")
            yield from fx.all(
                sql.with_transaction(fx.gen(first)), second, concurrency="unbounded"
            ).catch_all(lambda _: fx.void)
            return (yield from sql("SELECT value FROM nested_transactions"))

        rows = yield from sql.with_transaction(fx.gen(transaction))
        assert rows == [{"value": "first"}]

    yield from _with_pool(pg_server, body)


@testing.effect
def test_fails_a_transaction_whose_commit_rolls_back_after_a_caught_error(pg_server: PgServer):
    """fails a transaction whose COMMIT rolls back after a caught error"""

    def body():
        sql = yield from pg.PgClient()
        exit_ = yield from sql.with_transaction(sql("SELECT 1 / 0").ignore()).exit()
        assert isinstance(exit_, fx.Failure)
        assert not exit_.cause.has_dies
        assert exit_.cause.has_fails
        error = exit_.cause.squash()
        assert isinstance(error, SqlError)
        assert error.reason._tag == "UnknownError"
        assert error.reason.operation == "commit"

    yield from _with_pool(pg_server, body)


@testing.effect
def test_after_commit_runs_once_other_connections_see_the_transactions_rows(pg_server: PgServer):
    """afterCommit runs once other connections see the transaction's rows"""

    def body():
        sql = yield from pg.PgClient()
        yield from sql("CREATE TABLE after_commit_visibility (value INTEGER)")
        seen: list[object] = []

        def transaction():
            yield from sql("INSERT INTO after_commit_visibility VALUES (1)")
            count = sql("SELECT count(*)::integer AS count FROM after_commit_visibility")
            yield from sql.after_commit(count.map(seen.extend).as_void().or_die())

        yield from sql.with_transaction(fx.gen(transaction))
        yield from sql("DROP TABLE after_commit_visibility")
        assert seen == [{"count": 1}]

    yield from _with_pool(pg_server, body)


# --- PgClient.makeClient without preparation ------------------------------------


@testing.effect
def test_fails_an_aborted_commit_and_reuses_the_connection(pg_server: PgServer):
    """fails an aborted COMMIT and reuses the connection"""

    def body():
        sql = yield from pg.PgClient()
        exit_ = yield from sql.with_transaction(sql("SELECT 1 / 0").ignore()).exit()
        assert isinstance(exit_, fx.Failure)
        assert not exit_.cause.has_dies
        error = exit_.cause.squash()
        assert isinstance(error, SqlError)
        assert error.reason._tag == "UnknownError"
        assert error.reason.operation == "commit"
        rows = yield from sql.with_transaction(sql("SELECT 1 AS value"))
        assert rows == [{"value": 1}]

    yield from _with_single(pg_server, body, prepare=False)


# --- PgClient.makeClient --------------------------------------------------------


@testing.effect
def test_connects_before_executing_queries(pg_server: PgServer):
    """connects before executing queries"""

    def body():
        sql = yield from pg.PgClient()
        assert (yield from sql("SELECT 1 AS value")) == [{"value": 1}]

    yield from _with_single(pg_server, body)


@testing.effect
def test_skips_prepared_statements_for_unprepared_executions_only(pg_server: PgServer):
    """skips prepared statements for unprepared executions only"""

    def body():
        sql = yield from pg.PgClient()
        rows = sql("SELECT {}::int4 AS unprepared_row", 1)
        values = sql("SELECT {}::int4 AS unprepared_values", 2)
        prepared = sql(
            "SELECT statement FROM pg_prepared_statements WHERE statement IN ("
            "'SELECT $1::int4 AS unprepared_row', 'SELECT $1::int4 AS unprepared_values'"
            ") ORDER BY statement"
        )
        assert (yield from rows.unprepared) == [{"unprepared_row": 1}]
        assert (yield from values.values_unprepared) == [(2,)]
        assert (yield from prepared) == []
        assert (yield from rows) == [{"unprepared_row": 1}]
        assert (yield from values.values) == [(2,)]
        assert (yield from prepared) == [
            {"statement": "SELECT $1::int4 AS unprepared_row"},
            {"statement": "SELECT $1::int4 AS unprepared_values"},
        ]

    yield from _with_single(pg_server, body)


@testing.live
def test_pins_the_primary_connection_for_streams_by_default(pg_server: PgServer):
    """pins the primary connection for streams by default"""

    def body():
        sql = yield from pg.PgClient()
        started = yield from fx.Deferred[None].make()
        release = yield from fx.Deferred[None].make()
        running = (
            sql("SELECT generate_series(1, 2) AS value")
            .stream.tap(lambda _: started.succeed(None).and_then(release.wait()))
            .run_collect()
        )
        fiber = yield from scope.fork_scoped(running)
        yield from started.wait()
        rows = yield from sql("SELECT 1 AS value").timeout_option(0.1)
        yield from release.succeed(None)
        yield from fiber.join()
        assert rows is None

    yield from _with_single(pg_server, body)


@testing.live
def test_serializes_transactions_on_its_single_connection(pg_server: PgServer):
    """serializes transactions on its single connection"""

    def body():
        sql = yield from pg.PgClient()
        first_started = yield from fx.Deferred[None].make()
        release_first = yield from fx.Deferred[None].make()
        second_started = yield from fx.Deferred[None].make()
        first = yield from scope.fork_scoped(
            sql.with_transaction(first_started.succeed(None).and_then(release_first.wait()))
        )
        yield from first_started.wait()
        second = yield from scope.fork_scoped(sql.with_transaction(second_started.succeed(None)))
        overlap = yield from second_started.wait().timeout_option(0.1)
        yield from release_first.succeed(None)
        yield from first.join()
        yield from second.join()
        assert overlap is None

    yield from _with_single(pg_server, body)


# --- PgClient.makeClient acquireForStream ---------------------------------------


@testing.live
def test_runs_queries_while_a_stream_is_active(pg_server: PgServer):
    """runs queries while a stream is active"""

    def body():
        sql = yield from pg.PgClient()
        started = yield from fx.Deferred[None].make()
        release = yield from fx.Deferred[None].make()
        running = (
            sql("SELECT generate_series(1, 2) AS value")
            .stream.tap(lambda _: started.succeed(None).and_then(release.wait()))
            .run_collect()
        )
        fiber = yield from scope.fork_scoped(running)
        yield from started.wait()
        rows = yield from sql("SELECT 1 AS value").timeout_or_else(
            3, lambda: fx.fail(RuntimeError("query timed out while stream was active"))
        )
        yield from release.succeed(None)
        yield from fiber.join()
        assert rows == [{"value": 1}]

    yield from _with_single(
        pg_server, body, acquire_for_stream=True, application_name="side-default"
    )


@testing.effect
def test_uses_a_new_session_for_streams(pg_server: PgServer):
    """uses a new session for streams"""

    def body():
        sql = yield from pg.PgClient()
        yield from sql("SET application_name = 'sticky-primary'")
        rows = yield from sql(
            "SELECT current_setting('application_name') AS \"applicationName\""
        ).stream.run_collect()
        assert rows == [{"applicationName": "side-default"}]

    yield from _with_single(
        pg_server, body, acquire_for_stream=True, application_name="side-default"
    )


@testing.live
def test_pg_client_make_client_surfaces_transport_creation_failures():
    """PgClient.makeClient surfaces transport creation failures"""
    config = pg.PgClientConfig(username="test", host="127.0.0.1", port=refused_port())
    made = fx.scoped(pg.make_client(config)).pipe(fx.provide(fx.reactivity.layer))
    error = yield from made.flip()
    assert error.reason._tag == "ConnectionError"
    assert error.reason.operation == "connect"


# --- PgClient transforms ------------------------------------------------------


def _with_transforms(server: PgServer, body: Body) -> fx.Effect[Any, Any]:
    return _with_pool(
        server,
        body,
        transform_result_names=case.snake_to_camel,
        transform_query_names=case.camel_to_snake,
    )


@testing.effect
def test_transforms_insert_helper(pg_server: PgServer):
    """insert helper"""

    def body():
        sql = yield from pg.PgClient()
        query, params = sql(
            "INSERT INTO people {}", sql.insert({"firstName": "Tim", "age": 10})
        ).compile()
        assert query == 'INSERT INTO people ("first_name","age") VALUES ($1,$2)'
        assert params == ("Tim", 10)

    yield from _with_transforms(pg_server, body)


@testing.effect
def test_insert_helper_without_transforms(pg_server: PgServer):
    """insert helper withoutTransforms"""

    def body():
        sql = (yield from pg.PgClient()).without_transforms()
        query, params = sql(
            "INSERT INTO people {}", sql.insert({"first_name": "Tim", "age": 10})
        ).compile()
        assert query == 'INSERT INTO people ("first_name","age") VALUES ($1,$2)'
        assert params == ("Tim", 10)

    yield from _with_transforms(pg_server, body)


@testing.effect
def test_rejects_multi_statement_queries(pg_server: PgServer):
    """rejects multi-statement queries"""

    def body():
        sql = yield from SqlClient()
        error = yield from sql(
            "CREATE TABLE test_multi (id TEXT PRIMARY KEY, name TEXT); SELECT 1;"
        ).flip()
        assert error.reason._tag == "SqlSyntaxError"

    yield from _with_transforms(pg_server, body)


@testing.live
def test_interruption(pg_server: PgServer):
    """interruption"""

    def body():
        sql = yield from SqlClient()
        conn = yield from sql.reserve
        yield from conn.execute_raw("select pg_sleep(1000)", ()).timeout_option(0.05)
        assert (yield from conn.execute_values("select 1", ())) == [(1,)]

    yield from _with_transforms(pg_server, body)


@testing.effect
def test_retains_the_supplied_config(pg_server: PgServer):
    """retains the supplied config"""

    def body():
        sql = yield from pg.PgClient()
        assert sql.config.url is not None
        assert sql.config.transform_result_names is case.snake_to_camel
        assert sql.config.transform_query_names is case.camel_to_snake

    yield from _with_transforms(pg_server, body)


# --- PgClient listen ----------------------------------------------------------


def _with_listen(server: PgServer, body: Body) -> fx.Effect[Any, Any]:
    return _with_pool(server, body, max_connections=2)


def _within(seconds: float, effect: fx.Effect[Any, Any], message: str) -> fx.Effect[Any, Any]:
    return effect.timeout_or_else(seconds, lambda: fx.fail(RuntimeError(message)))


@testing.live
def test_keeps_queries_available_while_a_listener_reserves_one_connection(pg_server: PgServer):
    """keeps queries available while a listener reserves one connection"""

    def body():
        sql = yield from pg.PgClient()
        channel = "pool_connection_listen"
        payloads = yield from sql.listen(channel)
        rows = yield from _within(
            3, sql("SELECT 1 as value"), "query timed out while listener was active"
        )
        assert rows == [{"value": 1}]
        yield from sql.notify(channel, "payload")
        payload = yield from _within(
            3, payloads.take(), "listener did not receive notification in time"
        )
        assert payload.payload == "payload"

    yield from _with_listen(pg_server, body)


def test_an_idle_listener_does_not_hold_the_test_clock(pg_server: PgServer):
    """A listener waits for notifications that may never come: ``adjust``
    must not wait for it (DOGFOOD beacon #9)."""

    def body():
        sql = yield from pg.PgClient()
        yield from sql.listen("idle_listen")
        started = time.monotonic()
        yield from testing.adjust(10)
        assert time.monotonic() - started < 0.5

    with warnings.catch_warnings():
        warnings.simplefilter("error", testing.BusyFiberWarning)
        testing.run_test(_with_listen(pg_server, body))


@testing.live
def test_notify_sends_payload(pg_server: PgServer):
    """notify sends payload"""

    def body():
        sql = yield from pg.PgClient()
        channel = "pool_connection_notify"
        payloads = yield from sql.listen(channel)
        yield from sql.notify(channel, "payload")
        payload = yield from _within(
            3, payloads.take(), "listener did not receive notification in time"
        )
        assert payload.payload == "payload"

    yield from _with_listen(pg_server, body)


@testing.live
def test_retries_a_failed_listener_and_receives_notifications_on_a_new_connection(
    pg_server: PgServer,
):
    """retries a failed listener and receives notifications on a new connection"""

    def body():
        sql = yield from pg.PgClient()
        channel = "retry_listener"
        registered = yield from fx.Queue[None].unbounded()

        def listening():
            notifications = yield from sql.listen(channel)
            yield from registered.offer(None)
            return stream.from_queue(notifications)

        consumer = yield from scope.fork_scoped(
            stream.unwrap(fx.gen(listening)).retry(schedule.recurs(1)).run_head()
        )
        yield from registered.take()
        listener_query = f'LISTEN "{channel}"'
        [listener] = yield from sql(
            "SELECT pid FROM pg_stat_activity WHERE query = {}", listener_query
        )
        yield from sql("SELECT pg_terminate_backend({})", listener["pid"])
        # PostgreSQL does not replay missed notifications: wait for the new LISTEN.
        yield from registered.take()
        [replacement] = yield from sql(
            "SELECT pid FROM pg_stat_activity WHERE query = {} AND pid <> {}",
            listener_query,
            listener["pid"],
        )
        assert replacement["pid"] != listener["pid"]
        yield from sql.notify(channel, "after reconnect")
        head = yield from consumer.join()
        assert isinstance(head, Some)
        notification = head.value
        assert notification.channel == channel
        assert notification.payload == "after reconnect"

    yield from _with_listen(pg_server, body)


@testing.effect
def test_listen_rejects_channel_names_longer_than_63_utf8_bytes(pg_server: PgServer):
    """listen rejects channel names longer than 63 UTF-8 bytes"""

    def body():
        sql = yield from pg.PgClient()
        error = yield from fx.scoped(sql.listen("é" * 32)).flip()
        assert error.message == "PostgreSQL channel names must not exceed 63 UTF-8 bytes"
        assert error.reason.operation == "listen"

    yield from _with_listen(pg_server, body)


@testing.effect
def test_notify_rejects_channel_names_longer_than_63_utf8_bytes(pg_server: PgServer):
    """notify rejects channel names longer than 63 UTF-8 bytes"""

    def body():
        sql = yield from pg.PgClient()
        error = yield from sql.notify("é" * 32, "payload").flip()
        assert error.message == "PostgreSQL channel names must not exceed 63 UTF-8 bytes"
        assert error.reason.operation == "notify"

    yield from _with_listen(pg_server, body)


# --- PgClient onAcquire -------------------------------------------------------


class _RequestId(Reference[str], key="test/RequestId"):
    @classmethod
    def default(cls) -> str:
        return "none"


class _Prefix(Tag[str], key="test/Prefix"):
    pass


@testing.effect
def test_runs_once_per_acquisition_with_construction_services_in_the_consuming_fiber(
    pg_server: PgServer,
):
    """runs once per acquisition with construction services in the consuming fiber"""
    calls: list[str] = []

    def hook():
        prefix = yield from _Prefix()
        request = yield from _RequestId()
        calls.append(f"{prefix}:{request}")

    def body():
        layer = pg.layer(pg.PgPoolConfig(url=pg_server.url, on_acquire=fx.gen(hook))).pipe(
            fx.provide(fx.layer.succeed(_Prefix, "pool"))
        )
        context = yield from layer.build()
        sql = context.get(pg.PgClient)
        yield from sql("SELECT 1").pipe(fx.provide_service(_RequestId, "statement"))
        yield from sql.with_transaction(sql("SELECT 1").and_then(sql("SELECT 2"))).pipe(
            fx.provide_service(_RequestId, "transaction")
        )
        assert calls == ["pool:statement", "pool:transaction"]

    yield from fx.scoped(fx.gen(body))


@testing.effect
def test_closes_the_hooks_scope_after_each_statement(pg_server: PgServer):
    """closes the hook's scope after each statement"""
    finalized: list[None] = []

    def body():
        hook = scope.add_finalizer(lambda _: fx.sync(lambda: finalized.append(None)))
        sql = yield from pg.make(pg.PgPoolConfig(url=pg_server.url, on_acquire=hook))
        yield from sql("SELECT 1")
        yield from sql("SELECT 1")
        assert len(finalized) == 2

    yield from fx.scoped(fx.gen(body)).pipe(fx.provide(fx.reactivity.layer))
