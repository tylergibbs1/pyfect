"""Ports of Effect's ``sql/Statement.test.ts``.

Each test's docstring is the Effect test title. Effect's tagged templates
are ``str.format``-style templates here: ``sql("{} AS label", "label")``.

Omitted: "defaultTransforms ignores inherited properties" (a Python
mapping has no prototype to inherit keys from).
"""

from collections.abc import Callable, Sequence
from typing import Any

import pyfect as fx
from pyfect import case, testing
from pyfect.reactivity import layer as reactivity_layer
from pyfect.sql import client as sql_client
from pyfect.sql import statement as st
from pyfect.sql.connection import Row, TransformRows, ValueRow
from pyfect.sql.error import SqlError
from pyfect.tracer import CurrentStackFrame, NativeSpan, SpanRequest, Tracer, TracerEnabled


def test_transforms_sql_result_names_without_changing_nested_values():
    """transforms SQL result names without changing nested values"""
    rows = [
        {"user_id": 1, "profile_data": {"display_name": "Ada"}, "tags": [{"tag_name": "admin"}]}
    ]
    assert st.default_transforms(case.snake_to_camel).array(rows) == [
        {"userId": 1, "profileData": {"displayName": "Ada"}, "tags": [{"tagName": "admin"}]}
    ]
    assert st.default_transforms(case.snake_to_camel, False).array(rows) == [
        {"userId": 1, "profileData": {"display_name": "Ada"}, "tags": [{"tag_name": "admin"}]}
    ]


def test_keeps_null_and_scalar_items_in_transformed_arrays():
    """keeps null and scalar items in transformed arrays"""
    rows = [{"posts": [None], "tags": [{"tag_name": "admin"}, None, 1]}]
    assert st.default_transforms(case.snake_to_camel).array(rows) == [
        {"posts": [None], "tags": [{"tagName": "admin"}, None, 1]}
    ]
    assert st.default_transforms(case.snake_to_camel, False).value(
        [{"tag_name": "admin"}, None, 1]
    ) == [{"tagName": "admin"}, None, 1]


def test_keeps_previously_distinct_sql_column_names_distinct():
    """keeps previously distinct SQL column names distinct"""
    rows = [{"_id": 1, "id": 2, "foo__bar": 3, "foo_bar": 4, "_": 5, "___": 6}]
    assert st.default_transforms(case.snake_to_camel).array(rows) == [
        {"_id": 1, "id": 2, "foo_bar": 3, "fooBar": 4, "_": 5, "__": 6}
    ]
    assert st.default_transforms(case.snake_to_pascal).array(rows) == [
        {"_id": 1, "Id": 2, "Foo_bar": 3, "FooBar": 4, "_": 5, "__": 6}
    ]


def _pg_placeholder(index: int, _value: object) -> str:
    return f"${index}"


def _pg_identifier(value: str, _without_transform: bool) -> str:
    return st.default_escape('"')(value)


def _no_record_update(*_args: object) -> st.Compiled:
    return ("", ())


def _pg_compiler(
    on_identifier: Callable[[str, bool], str] = _pg_identifier,
    on_record_update: Callable[
        [str, str, str, Sequence[Sequence[object]], st.Compiled | None], st.Compiled
    ] = _no_record_update,
) -> st.Compiler:
    return st.make_compiler(
        dialect="pg",
        placeholder=_pg_placeholder,
        on_identifier=on_identifier,
        on_record_update=on_record_update,
        on_custom=_no_record_update,
    )


def test_compiles_one_fragment_independently_for_each_compiler():
    """compiles one fragment independently for each compiler"""
    postgres = _pg_compiler()
    sqlite = st.make_compiler_sqlite()
    fragment = st.fragment([st.identifier("value"), st.parameter(1)])

    assert postgres.compile(fragment, False) == ('"value"$1', (1,))
    assert sqlite.compile(fragment, False) == ('"value"?', (1,))


def test_escapes_update_values_aliases_without_transforming_them():
    """escapes updateValues aliases without transforming them"""

    def on_identifier(value: str, without_transform: bool) -> str:
        return st.default_escape('"')(value if without_transform else f"t_{value}")

    def on_record_update(
        placeholders: str,
        alias: str,
        columns: str,
        values: Sequence[Sequence[object]],
        _returning: st.Compiled | None,
    ) -> st.Compiled:
        return (
            f"(values {placeholders}) AS {alias}{columns}",
            tuple(v for row in values for v in row),
        )

    compiler = _pg_compiler(on_identifier, on_record_update)
    fragment = st.fragment([st.record_update_helper([{"name": "Ada"}], 'My"Data --')])

    assert compiler.compile(fragment, False) == (
        '(values ($1)) AS "My""Data --"("t_name")',
        ("Ada",),
    )


def test_renumbers_a_cached_returning_fragment():
    """renumbers a cached returning fragment"""
    sql = st.make(fx.never, _pg_compiler(), [], None)
    returning = sql("{} AS label", "label")

    assert returning.compile() == ("$1 AS label", ("label",))
    assert sql(
        "INSERT INTO people {}, {} AS extra",
        sql.insert({"name": "Ada"}).returning(returning),
        "extra",
    ).compile() == (
        'INSERT INTO people ("name") VALUES ($1) RETURNING $2 AS label, $3 AS extra',
        ("Ada", "label", "extra"),
    )


def test_binds_plain_objects_shaped_like_fragments_or_segments_as_parameters():
    """binds plain objects shaped like fragments or segments as parameters"""
    sql = st.make(fx.never, st.make_compiler_sqlite(), [], None)
    fragment_like = {
        "~effect/sql/Statement/Fragment": "~effect/sql/Statement/Fragment",
        "segments": [{"_tag": "Literal", "value": "1=1"}],
    }
    segment_like = {"_tag": "Literal", "value": "1=1"}

    assert sql("SELECT {}, {}", fragment_like, segment_like).compile() == (
        "SELECT ?, ?",
        (fragment_like, segment_like),
    )


class _Connection:
    def __init__(self, execute: fx.Effect[list[Any], SqlError]) -> None:
        self._execute = execute

    def execute(
        self, sql: str, params: Sequence[object], transform_rows: TransformRows | None, /
    ) -> fx.Effect[Sequence[Row], SqlError]:
        return self._execute

    def execute_raw(self, sql: str, params: Sequence[object], /) -> fx.Effect[object, SqlError]:
        return self._execute

    def execute_values(
        self, sql: str, params: Sequence[object], /
    ) -> fx.Effect[Sequence[ValueRow], SqlError]:
        return self._execute

    def execute_values_unprepared(
        self, sql: str, params: Sequence[object], /
    ) -> fx.Effect[Sequence[ValueRow], SqlError]:
        return self._execute

    def execute_unprepared(
        self, sql: str, params: Sequence[object], transform_rows: TransformRows | None, /
    ) -> fx.Effect[Sequence[Row], SqlError]:
        return self._execute

    def execute_stream(
        self, sql: str, params: Sequence[object], transform_rows: TransformRows | None, /
    ) -> fx.Stream[Row, SqlError]:
        return fx.stream.from_effect(self._execute).flat_map(fx.stream.from_iterable)


def _make_client(
    observe: fx.Effect[None], borrow: bool = False, acquire: fx.Effect[None] | None = None
) -> fx.Effect[sql_client.SqlClientService, Any, Any]:
    before = observe if acquire is None else acquire
    connection = _Connection(observe.as_([]))

    def borrower(f: Any) -> fx.Effect[Any, Any, Any]:
        return before.and_then(f(connection))

    return sql_client.make(
        driver="test",
        acquirer=before.as_(connection),
        borrower=borrower if borrow else None,
        compiler=st.make_compiler_sqlite(),
        span_attributes=[],
    )


def _span_name() -> fx.Effect[str]:
    return (
        fx.tracer.current_span().map(lambda span: span.name).catch_all(lambda _: fx.succeed("none"))
    )


@testing.effect
def test_reads_propagation_overrides_when_executing_existing_statements_and_streams():
    """reads propagation overrides when executing existing statements and streams"""
    expected = ["none"]

    def check(name: str) -> None:
        assert name == expected[0]

    sql = yield from _make_client(_span_name().map(check)).pipe(fx.provide(reactivity_layer))
    query = sql("select 1")
    run = query.and_then(query.stream.run_drain())

    yield from run
    expected[0] = "sql.execute"
    yield from run.pipe(fx.provide_service(st.SpanPropagationEnabled, True))
    expected[0] = "none"
    yield from run.pipe(fx.provide_service(st.SpanPropagationEnabled, False)).pipe(
        fx.provide_service(st.SpanPropagationEnabled, True)
    )


@testing.effect
def test_parents_acquisition_execution_and_pulls_without_adding_stack_frames():
    """parents acquisition, execution, and pulls without adding stack frames"""
    frame = yield from CurrentStackFrame()

    def observe_body():
        name = yield from fx.tracer.current_span().or_die().map(lambda span: span.name)
        assert name == "sql.execute"
        assert (yield from CurrentStackFrame()) is frame

    observe = fx.gen(observe_body)
    acquired = yield from _make_client(observe).pipe(fx.provide(reactivity_layer))
    borrowed = yield from _make_client(observe, True).pipe(fx.provide(reactivity_layer))

    def body():
        yield from acquired("select 1")
        yield from borrowed("select 1")
        yield from borrowed("select 1").stream.run_drain()

    yield from fx.gen(body).pipe(fx.provide_service(st.SpanPropagationEnabled, True))


def _recording_tracer() -> tuple[Tracer, list[NativeSpan]]:
    spans: list[NativeSpan] = []

    def make(request: SpanRequest) -> NativeSpan:
        span = NativeSpan(request)
        spans.append(span)
        return span

    return Tracer(make), spans


@testing.effect
def test_records_how_long_a_statement_waited_for_a_connection():
    """records how long a statement waited for a connection"""
    tracer, spans = _recording_tracer()
    wait = fx.sleep("30 millis")
    acquired = yield from _make_client(fx.void, False, wait).pipe(fx.provide(reactivity_layer))
    borrowed = yield from _make_client(fx.void, True, wait).pipe(fx.provide(reactivity_layer))

    def run(statement: fx.Effect[Any, Any], propagate: bool):
        fiber = yield from (
            statement.with_tracer(tracer)
            .pipe(fx.provide_service(st.SpanPropagationEnabled, propagate))
            .fork()
        )
        yield from testing.adjust("30 millis")
        yield from fiber.join()

    for propagate in (True, False):
        yield from run(acquired("select 1"), propagate)
        yield from run(borrowed("select 1"), propagate)
        yield from run(acquired("select 1").stream.run_drain(), propagate)
    assert [span.attributes.get("db.client.connection.wait_time_ms") for span in spans] == [
        30,
        30,
        30,
        None,
        None,
        None,
    ]


@testing.effect
def test_skips_propagation_when_tracing_is_disabled():
    """skips propagation when tracing is disabled"""

    def check(name: str) -> None:
        assert name == "none"

    sql = yield from _make_client(_span_name().map(check)).pipe(fx.provide(reactivity_layer))
    yield from (
        sql("select 1")
        .and_then(sql("select 1").stream.run_drain())
        .pipe(fx.provide_service(st.SpanPropagationEnabled, True))
        .pipe(fx.provide_service(TracerEnabled, False))
    )
