"""Ports of Effect's ``sql-clickhouse/test/Client.test.ts``.

Each test's docstring is the Effect test title. Effect's
``vi.mock("@clickhouse/client")`` is ``_clickhouse_fake``: the client
sends its requests through a fake ``HttpClient``, so the tests see the
HTTP requests ``@clickhouse/client`` would send.

Adapted: "closes the client when the connection check times out" checks
that the pending ``/ping`` was aborted (the HTTP client here is the
test's, not the client's to close; one the client creates closes with its
scope). "exposes the underlying ClickHouse client" checks ``client`` is
the ``ClickhouseDriver`` on the configured HTTP client. "preserves
fractional JavaScript numbers" also pins that an ``int`` is an ``Int64``.
The query ids of the ``KILL QUERY`` requests are compared as sent, escaped
as parameter text (Effect compares the ``query_params`` object). The
ledger rows of "retries a failed migration" carry ``created_at``, as a
server's do. "parameterizes the query id when cancelling an insert"
inserts one row: an empty list sends nothing, as in ``@clickhouse/client``
(Effect's mock stands in for that check).
"""

from __future__ import annotations

import json
from collections.abc import Callable, Generator
from datetime import UTC, datetime
from typing import Any

import pyfect as fx
from pyfect import stream, testing
from pyfect.exit import Failure
from pyfect.reactivity import layer as reactivity_layer
from pyfect.result import Ok
from pyfect.sql import SqlClient, clickhouse
from pyfect.sql import statement as st
from pyfect.sql.clickhouse import migrator
from pyfect.sql.clickhouse.params import format_query_param

from ._clickhouse_fake import Call, FakeClickhouse

type Body = Callable[[], Generator[Any, Any, Any]]

sql = st.make(fx.never, clickhouse.make_compiler(), [], None)
_KILL = "KILL QUERY WHERE query_id = {queryId:String}"


def _run(body: Body) -> Any:
    return fx.run_blocking(
        fx.scoped(fx.gen(body)).pipe(fx.provide(reactivity_layer)).timeout("5 seconds").or_die()
    )


def _make(fake: FakeClickhouse) -> fx.Effect[clickhouse.ClickhouseClientService, Any, Any]:
    return clickhouse.make(fake.config())


def test_infers_datetime_parameters_without_empty_parentheses():
    """infers DateTime parameters without empty parentheses"""
    date = datetime(2024, 1, 15, 14, 30, tzinfo=UTC)
    assert sql("SELECT {}", date).compile() == ("SELECT {p1: DateTime}", (date,))


def test_preserves_an_explicit_nullable_parameter_type_and_null_value():
    """preserves an explicit nullable parameter type and null value"""

    def body():
        client = yield from _make(FakeClickhouse())
        compiled = client("SELECT {}", client.param("Nullable(Int32)", None)).compile()
        assert compiled == ("SELECT {p1: Nullable(Int32)}", (None,))

    _run(body)


def test_preserves_fractional_javascript_numbers_in_inferred_parameters():
    """preserves fractional JavaScript numbers in inferred parameters"""
    assert sql("SELECT {}", 1.5).compile()[0] == "SELECT {p1: Float64}"
    assert sql("SELECT {}", 2).compile()[0] == "SELECT {p1: Int64}"


def test_uses_the_clickhouse_dialect_for_dialect_specific_fragments():
    """uses the ClickHouse dialect for dialect-specific fragments"""
    chosen = sql.on_dialect(
        sqlite=lambda: "sqlite",
        pg=lambda: "pg",
        mysql=lambda: "mysql",
        mssql=lambda: "mssql",
        clickhouse=lambda: "clickhouse",
    )
    assert chosen == "clickhouse"


def test_exposes_the_underlying_clickhouse_client():
    """exposes the underlying ClickHouse client"""
    fake = FakeClickhouse()
    http = fake.http_client

    def body():
        client = yield from clickhouse.make(fake.config(http_client=http))
        assert isinstance(client.client, clickhouse.ClickhouseDriver)
        assert client.client.http_client is http
        yield from client.client.command("SELECT 1")
        assert [call.sql for call in fake.commands] == ["SELECT 1"]

    _run(body)


@testing.effect
def test_closes_the_client_when_the_connection_check_times_out():
    """closes the client when the connection check times out"""
    fake = FakeClickhouse(ping=None)
    made = fx.scoped(_make(fake)).pipe(fx.provide(reactivity_layer))
    fiber = yield from made.fork_daemon()
    yield from fx.yield_now()
    yield from testing.adjust("5 seconds")
    result = fiber.poll_unsafe()
    assert isinstance(result, Failure)
    error = result.cause.find_error()
    assert isinstance(error, Ok)
    assert error.value.message == "ClickhouseClient: Connection timeout"
    assert [call.signal.aborted for call in fake.calls] == [True]


def _kills(fake: FakeClickhouse) -> list[tuple[str, dict[str, str]]]:
    return [(call.sql, call.params) for call in fake.commands]


def test_parameterizes_the_query_id_when_cancelling_a_query():
    """parameterizes the query id when cancelling a query"""
    fake = FakeClickhouse(query=None)
    query_id = "id' OR 1 = 1 --"

    def body():
        client = yield from _make(fake)
        fiber = yield from client.with_query_id(client.unsafe("SELECT 1"), query_id).fork_scoped()
        yield from fx.yield_now()
        yield from fiber.interrupt()
        assert _kills(fake) == [(_KILL, {"queryId": format_query_param(query_id)})]

    _run(body)


def test_parameterizes_the_query_id_when_cancelling_an_insert():
    """parameterizes the query id when cancelling an insert"""
    fake = FakeClickhouse(insert=None)
    query_id = "id' OR 1 = 1 --"

    def body():
        client = yield from _make(fake)
        insert = client.insert_query(table="test", values=[{"a": 1}])
        fiber = yield from client.with_query_id(insert, query_id).fork_scoped()
        yield from fx.yield_now()
        yield from fiber.interrupt()
        assert _kills(fake) == [(_KILL, {"queryId": format_query_param(query_id)})]

    _run(body)


def test_passes_column_selection_to_insert_query():
    """passes column selection to insertQuery"""
    fake = FakeClickhouse()

    def body():
        client = yield from _make(fake)
        yield from client.insert_query(table="people", values=[{"name": "Alice"}], columns=["name"])
        yield from client.insert_query(
            table="people", values=[{"name": "Bob"}], columns={"except": ["id"]}
        )
        assert [call.sql for call in fake.inserts] == [
            "INSERT INTO people (name) FORMAT JSONEachRow",
            "INSERT INTO people (* EXCEPT (id)) FORMAT JSONEachRow",
        ]

    _run(body)


def test_creates_the_ledger_without_sqlite_ddl_or_begin():
    """creates the ledger without sqlite ddl or BEGIN"""
    fake = FakeClickhouse()

    def body():
        client = yield from _make(fake)
        applied = yield from migrator.run(loader=migrator.from_record({"1_init": fx.void})).pipe(
            fx.provide_service(SqlClient, client)
        )
        assert applied == [(1, "init")]
        queries = [call.sql for call in fake.calls if call.format is not None]
        assert "ENGINE = MergeTree" in queries[0]
        assert not any("PRIMARY KEY NOT NULL" in q or "BEGIN" in q for q in queries)

    _run(body)


def test_retries_a_failed_migration_and_the_ones_after_it_on_the_next_run():
    """retries a failed migration and the ones after it on the next run"""
    ledger: list[dict[str, object]] = []

    def query(call: Call) -> fx.Effect[Any, Any]:
        if call.sql.startswith('INSERT INTO "effect_sql_migrations"'):
            params = list(call.params.values())
            for i in range(0, len(params), 2):
                row: dict[str, object] = {
                    "migration_id": int(params[i]),
                    "name": params[i + 1],
                    "created_at": None,
                }
                ledger.insert(0, row)
        data = ledger if call.sql.startswith("SELECT migration_id") else []
        return call.answer(json.dumps({"data": data}))

    fake = FakeClickhouse(query=query)
    attempts = [0]

    def second() -> fx.Effect[None, str]:
        attempts[0] += 1
        return fx.fail("rejected") if attempts[0] == 1 else fx.void

    def body():
        client = yield from _make(fake)
        run = migrator.run(
            loader=migrator.from_record(
                {
                    "1_first": client("CREATE TABLE first"),
                    "2_second": fx.suspend(second),
                    "3_third": client("CREATE TABLE third"),
                }
            )
        ).pipe(fx.provide_service(SqlClient, client))
        error = yield from run.flip()
        assert error.message == 'Migration "2_second" failed'
        assert (yield from run) == [(2, "second"), (3, "third")]

    _run(body)


def test_kills_a_streamed_query_only_when_the_stream_is_not_read_to_the_end():
    """kills a streamed query only when the stream is not read to the end"""

    def query(call: Call) -> fx.Effect[Any, Any]:
        chunks = stream.from_iterable([b'{"a":1}\n', b'{"a":2}\n'])
        return call.answer(b"").map(
            lambda response: type(response)(response.request, 200, response.headers, chunks)
        )

    fake = FakeClickhouse(query=query)

    def body():
        client = yield from _make(fake)
        statement = client("SELECT a FROM t")
        whole = yield from client.with_query_id(statement.stream.run_collect(), "full-id")
        first = yield from client.with_query_id(statement.stream.take(1).run_collect(), "take-id")
        assert list(whole) == [{"a": 1}, {"a": 2}]
        assert list(first) == [{"a": 1}]
        assert _kills(fake) == [(_KILL, {"queryId": "take-id"})]

    _run(body)


def test_interrupting_a_stream_before_its_response_kills_the_query():
    """(pyfect) interrupting a stream before its response kills the query"""
    fake = FakeClickhouse(query=None)

    def body():
        client = yield from _make(fake)
        rows = client("SELECT a FROM t").stream.run_collect()
        fiber = yield from client.with_query_id(rows, "stream-id").fork_scoped()
        yield from fx.yield_now()
        yield from fiber.interrupt()
        assert _kills(fake) == [(_KILL, {"queryId": "stream-id"})]

    _run(body)
