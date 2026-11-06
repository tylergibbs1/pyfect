"""Ports of Effect's ``sql-d1/test/Client.test.ts``.

Each test's docstring is the Effect test title. Effect runs them on
Miniflare's D1 binding; these run on ``_d1_fake.FakeD1``, D1's HTTP API in
process over a real SQLite database, sent with ``http_client.layer_test``.

Adapted: "classifies native errors without stable sqlite codes" fails the
request itself (a ``TransportError``), the HTTP API's equivalent of a
binding that throws; "names batches with the configured target" answers
every request with empty results, as Effect's stub binding does.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Generator
from typing import Any

import pyfect as fx
from pyfect import reactivity, testing
from pyfect.http import body as http_body
from pyfect.http import client as http_client
from pyfect.http import error as http_error
from pyfect.http import response as http_response
from pyfect.http.request import HttpClientRequest
from pyfect.sql import d1
from pyfect.sql import statement as st
from pyfect.sql.error import SqlError, UnknownError
from pyfect.tracer import NativeSpan, SpanRequest, Tracer

from ._d1_fake import FakeD1

type Body = Callable[[], Generator[Any, Any, Any]]


def _on_fake(body: Body, fake: FakeD1 | None = None) -> fx.Effect[Any, Any]:
    fake = fake or FakeD1()
    return fx.gen(body).pipe(fx.provide(fake.client_layer()))


def _rename(source: str, target: str) -> Callable[[str], str]:
    return lambda name: target if name == source else name


def _make(fake: FakeD1, **fields: Any) -> fx.Effect[d1.D1ClientService, Any, fx.Scope]:
    return (
        d1.make(fake.config(**fields))
        .pipe(fx.provide(reactivity.layer))
        .pipe(fx.provide(fake.layer))
    )


@testing.effect
def test_raw_preserves_the_native_result_envelope():
    """raw preserves the native result envelope"""

    def body():
        sql = yield from d1.D1Client()
        yield from sql("CREATE TABLE raw_test (id INTEGER PRIMARY KEY, name TEXT)")
        raw = yield from sql("INSERT INTO raw_test (name) VALUES ({})", "effect").raw
        assert isinstance(raw, d1.D1Result)
        assert raw.success is True
        assert list(raw.results) == []
        assert raw.meta.changes == 1
        assert raw.meta.last_row_id == 1

    yield from _on_fake(body)


@testing.effect
def test_classifies_native_errors_without_stable_sqlite_codes_as_unknown_error():
    """classifies native errors without stable sqlite codes as UnknownError"""

    def refuse(request: HttpClientRequest) -> fx.Effect[Any, http_error.HttpClientError]:
        return fx.fail(
            http_error.HttpClientError(
                http_error.TransportError(request=request, cause=RuntimeError("boom"))
            )
        )

    client = (
        yield from d1.make(FakeD1().config())
        .pipe(fx.provide(reactivity.layer))
        .pipe(fx.provide(http_client.layer_test(refuse)))
    )
    error = yield from client("SELECT 1").flip()
    assert isinstance(error, SqlError)
    assert isinstance(error.reason, UnknownError)


@testing.effect
def test_should_handle_queries_without_transactions():
    """should handle queries without transactions"""

    def body():
        sql = yield from d1.D1Client()
        yield from sql("CREATE TABLE test (id INTEGER PRIMARY KEY, name TEXT)")
        yield from sql("INSERT INTO test (name) VALUES ('hello')")
        rows = yield from sql("SELECT * FROM test")
        assert rows == [{"id": 1, "name": "hello"}]
        yield from sql("INSERT INTO test (name) VALUES ('world')")
        rows = yield from sql("SELECT * FROM test")
        assert rows == [{"id": 1, "name": "hello"}, {"id": 2, "name": "world"}]

    yield from _on_fake(body)


@testing.effect
def test_should_handle_queries_with_params_without_transactions():
    """should handle queries with params without transactions"""

    def body():
        sql = yield from d1.D1Client()
        yield from sql("CREATE TABLE test (id INTEGER PRIMARY KEY, name TEXT)")
        yield from sql("INSERT INTO test {}", sql.insert({"name": "hello"}))
        rows = yield from sql("SELECT * FROM test WHERE name = {}", "hello")
        assert rows == [{"id": 1, "name": "hello"}]

    yield from _on_fake(body)


@testing.effect
def test_should_execute_statements_in_a_batch():
    """should execute statements in a batch"""

    def body():
        sql = yield from d1.D1Client()
        yield from sql("CREATE TABLE test (id INTEGER PRIMARY KEY, name TEXT)")
        results = yield from sql.batch(
            (
                sql("INSERT INTO test (name) VALUES ({}) RETURNING *", "hello"),
                sql("INSERT INTO test (name) VALUES ({}) RETURNING *", "world"),
                sql("SELECT COUNT(*) AS count FROM test"),
            )
        )
        assert results == (
            [{"id": 1, "name": "hello"}],
            [{"id": 2, "name": "world"}],
            [{"count": 2}],
        )

    yield from _on_fake(body)


def _first_name_table() -> Generator[Any, Any, d1.D1ClientService]:
    sql = yield from d1.D1Client()
    yield from sql('CREATE TABLE test (first_name TEXT, "firstName" TEXT)')
    yield from sql("INSERT INTO test (first_name, \"firstName\") VALUES ('John', 'Jane')")
    return sql


@testing.effect
def test_should_apply_result_transforms_to_batch_results():
    """should apply result transforms to batch results"""
    fake = FakeD1()

    def body():
        yield from _first_name_table()
        transformed = yield from _make(
            fake,
            transform_query_names=_rename("firstName", "first_name"),
            transform_result_names=_rename("first_name", "firstName"),
        )
        (rows,) = yield from transformed.batch(
            (transformed("SELECT {} FROM test", transformed.identifier("firstName")),)
        )
        assert rows == [{"firstName": "John"}]

        without = transformed.without_transforms()
        (raw_rows,) = yield from without.batch(
            (without("SELECT {} FROM test", without.identifier("firstName")),)
        )
        assert raw_rows == [{"firstName": "Jane"}]

        (raw_from_transformed,) = yield from transformed.batch(
            (without("SELECT {} FROM test", without.identifier("first_name")),)
        )
        assert raw_from_transformed == [{"first_name": "John"}]

        (transformed_from_raw,) = yield from without.batch(
            (transformed("SELECT {} FROM test", transformed.identifier("firstName")),)
        )
        assert transformed_from_raw == [{"firstName": "John"}]

    yield from fx.scoped(_on_fake(body, fake))


@testing.effect
def test_should_disable_query_only_transforms():
    """should disable query-only transforms"""
    fake = FakeD1()

    def body():
        yield from _first_name_table()
        transformed = yield from _make(
            fake, transform_query_names=_rename("firstName", "first_name")
        )
        (rows,) = yield from transformed.batch(
            (transformed("SELECT {} FROM test", transformed.identifier("firstName")),)
        )
        assert rows == [{"first_name": "John"}]

        without = transformed.without_transforms()
        (raw_rows,) = yield from without.batch(
            (without("SELECT {} FROM test", without.identifier("firstName")),)
        )
        assert raw_rows == [{"firstName": "Jane"}]

    yield from fx.scoped(_on_fake(body, fake))


@testing.effect
def test_should_roll_back_a_failed_batch():
    """should roll back a failed batch"""

    def body():
        sql = yield from d1.D1Client()
        yield from sql("CREATE TABLE test (id INTEGER PRIMARY KEY, name TEXT UNIQUE)")
        error = yield from sql.batch(
            (
                sql("INSERT INTO test (name) VALUES ({})", "duplicate"),
                sql("INSERT INTO test (name) VALUES ({})", "duplicate"),
            )
        ).flip()
        assert isinstance(error.reason, UnknownError)
        assert error.reason.operation == "execute"
        assert error.reason.message == "Failed to execute batch"
        assert isinstance(error.reason.cause, d1.D1ApiError)
        assert "UNIQUE constraint failed" in str(error.reason.cause)
        assert (yield from sql("SELECT * FROM test")) == []

    yield from _on_fake(body)


@testing.effect
def test_should_support_an_empty_batch():
    """should support an empty batch"""

    def body():
        sql = yield from d1.D1Client()
        assert (yield from sql.batch(())) == ()

    yield from _on_fake(body)


@testing.effect
def test_should_apply_statement_transformers_in_a_batch():
    """should apply statement transformers in a batch"""

    def body():
        sql = yield from d1.D1Client()
        queries: list[str] = []

        def transformer(
            statement: st.Statement[Any], constructor: st.Constructor, _fiber: Any, _span: Any
        ) -> fx.Effect[st.Statement[Any]]:
            def record() -> st.Statement[Any]:
                queries.append(statement.compile()[0])
                return constructor("SELECT {} AS value", 3)

            return fx.sync(record)

        results = yield from sql.batch(
            (sql("SELECT {} AS value", 1), sql("SELECT {} AS value", 2))
        ).pipe(fx.provide_service(st.CurrentTransformer, transformer))
        assert queries == ["SELECT ? AS value", "SELECT ? AS value"]
        assert results == ([{"value": 3}], [{"value": 3}])

    yield from _on_fake(body)


@testing.effect
def test_should_defect_on_transactions():
    """should defect on transactions"""

    def body():
        sql = yield from d1.D1Client()
        yield from sql("CREATE TABLE test (id INTEGER PRIMARY KEY, name TEXT)")
        insert = sql("INSERT INTO test {}", sql.insert({"name": "hello"}))
        exit = yield from sql.with_transaction(insert).exit()
        assert (yield from sql("SELECT * FROM test")) == []
        assert isinstance(exit, fx.exit.Failure)
        assert exit.cause.has_dies

    yield from _on_fake(body)


@testing.effect
def test_names_batches_with_the_configured_target():
    """names batches with the configured target"""

    def empty(request: HttpClientRequest) -> fx.Effect[Any]:
        body = request.body
        assert isinstance(body, http_body.Bytes)
        sent: dict[str, list[object]] = json.loads(body.body)
        entries: list[object] = [
            {"results": [], "success": True, "meta": {}} for _ in sent["batch"]
        ]
        answer = json.dumps({"result": entries, "success": True, "errors": []})
        return fx.succeed(http_response.make(request, answer))

    spans: list[NativeSpan] = []

    def make_span(request: SpanRequest) -> NativeSpan:
        span = NativeSpan(request)
        spans.append(span)
        return span

    sql = (
        yield from d1.make(FakeD1().config(span_attributes={"db.namespace": "app"}))
        .pipe(fx.provide(reactivity.layer))
        .pipe(fx.provide(http_client.layer_test(empty)))
    )
    yield from sql.batch((sql("SELECT 1"), sql("SELECT 2"))).with_tracer(Tracer(make_span))
    assert [span.name for span in spans] == ["BATCH app"]
    assert spans[0].attributes.get("db.operation.name") == "BATCH"
    assert spans[0].attributes.get("db.operation.batch.size") == 2
    assert spans[0].attributes.get("db.query.text") == "SELECT 1; SELECT 2"


@testing.effect
def test_should_defect_when_batching_in_a_transaction():
    """should defect when batching in a transaction"""

    def body():
        sql = yield from d1.D1Client()
        yield from sql("CREATE TABLE test (id INTEGER PRIMARY KEY, name TEXT)")
        batch = sql.batch((sql("INSERT INTO test {}", sql.insert({"name": "hello"})),))
        exit = yield from sql.with_transaction(batch).exit()
        assert (yield from sql("SELECT * FROM test")) == []
        assert isinstance(exit, fx.exit.Failure)
        assert exit.cause.has_dies

    yield from _on_fake(body)


@testing.effect
def test_a_batch_of_one_statement_holding_several_gives_every_result():
    """(pyfect) D1 answers the request with a result per statement it ran, one
    request here where Effect sends ``db.batch([prepared])``. Effect's
    ``responses.map`` keeps them all, renaming only by the statements it knows"""
    fake = FakeD1()

    def body():
        sql = yield from _make(fake, transform_result_names=_rename("name", "NAME"))
        results = yield from sql.batch((sql("CREATE TABLE test (x TEXT); SELECT 1 AS name"),))
        assert results == ([], [{"name": 1}])
        results = yield from sql.batch((sql("SELECT 1 AS name; SELECT 2 AS name"),))
        assert results == ([{"NAME": 1}], [{"name": 2}])

    yield from _on_fake(body, fake)
