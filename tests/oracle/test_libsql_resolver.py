"""Ports of Effect's ``sql-libsql/test/Resolver.integration.test.ts``, on
the session's sqld container (``_libsql.libsql_server``; skipped without
Docker).

Each test's docstring is the Effect test title. Each test seeds the
``test`` table and drops it when it ends.
"""

from collections.abc import Sequence
from typing import Any, TypedDict

import pyfect as fx
from pyfect import schema as S
from pyfect import testing
from pyfect.sql import libsql
from pyfect.sql import resolver as R
from pyfect.sql.error import ResultLengthMismatch

from ._libsql import LibsqlServer


class _Row(TypedDict):
    id: float
    name: str


def _seeded():
    sql = yield from libsql.LibsqlClient()
    yield from sql("DROP TABLE IF EXISTS test")
    yield from sql("CREATE TABLE test (id INTEGER PRIMARY KEY, name TEXT)")
    rows = [
        {"id": 1, "name": "name1"},
        {"id": 2, "name": "name2"},
        {"id": 3, "name": "name3"},
        {"id": 100, "name": "name100"},
    ]
    yield from sql("INSERT INTO test {}", sql.insert(rows))
    yield from fx.add_finalizer(lambda _: sql("DROP TABLE test;").or_die())
    return sql


def _on(server: LibsqlServer, body: Any) -> fx.Effect[Any, Any]:
    layer = libsql.layer(libsql.LibsqlClientConfig(url=server.url))
    return fx.scoped(fx.gen(body)).pipe(fx.provide(layer))


@testing.effect
def test_ordered_insert(libsql_server: LibsqlServer):
    """ordered / insert"""

    def body():
        batches: list[list[str]] = []
        sql = yield from _seeded()

        def execute(names: Sequence[Any]) -> fx.Effect[Sequence[object], Any]:
            batches.append(list(names))
            return sql("INSERT INTO test {} RETURNING *", sql.insert([{"name": n} for n in names]))

        insert = R.ordered(request=S.String, result=S.Struct(_Row), execute=execute)
        run = R.request(insert)
        result = yield from fx.all_dict(
            {"one": run("one"), "two": run("two")}, concurrency="unbounded"
        )
        assert result == {"one": {"id": 101, "name": "one"}, "two": {"id": 102, "name": "two"}}
        assert batches == [["one", "two"]]

    yield from _on(libsql_server, body)


@testing.effect
def test_ordered_result_length_mismatch(libsql_server: LibsqlServer):
    """ordered / result length mismatch"""

    def body():
        batches: list[list[float]] = []
        sql = yield from _seeded()

        def execute(ids: Sequence[Any]) -> fx.Effect[Sequence[object], Any]:
            batches.append(list(ids))
            return sql("SELECT * FROM test WHERE id IN {}", sql.in_(ids))

        select = R.ordered(request=S.Number, result=S.Struct(_Row), execute=execute)
        run = R.request(select)
        error = yield from fx.all(run(1), run(2), run(3), run(101), concurrency="unbounded").flip()
        assert isinstance(error, ResultLengthMismatch)
        assert error.actual == 3
        assert error.expected == 4
        assert batches == [[1, 2, 3, 101]]

    yield from _on(libsql_server, body)


def _grouped(*, raw: bool):
    def body():
        sql = yield from _seeded()
        find_by_name = R.grouped(
            request=S.String,
            request_group_key=lambda name: name,
            result=S.Struct(_Row),
            result_group_key=(lambda _result, row: row["name"])
            if raw
            else (lambda result, _row: result["name"]),
            execute=lambda names: sql("SELECT * FROM test WHERE name IN {}", sql.in_(names)),
        )
        yield from sql("INSERT INTO test {}", sql.insert({"name": "name1"}))
        run = R.request(find_by_name)
        result = yield from fx.all_dict(
            {"one": run("name1"), "two": run("name2"), "three": run("name0").flip()},
            concurrency="unbounded",
        )
        assert result["one"] == ({"id": 1, "name": "name1"}, {"id": 101, "name": "name1"})
        assert result["two"] == ({"id": 2, "name": "name2"},)
        assert isinstance(result["three"], fx.NoSuchElementException)

    return body


@testing.effect
def test_grouped_find_by_name(libsql_server: LibsqlServer):
    """grouped / find by name"""
    yield from _on(libsql_server, _grouped(raw=False))


@testing.effect
def test_grouped_using_raw_rows(libsql_server: LibsqlServer):
    """grouped / using raw rows"""
    yield from _on(libsql_server, _grouped(raw=True))


def _find_by_id(*, raw: bool):
    def body():
        sql = yield from _seeded()
        find_by_id = R.find_by_id(
            id=S.Number,
            result=S.Struct(_Row),
            result_id=(lambda _result, row: row["id"])
            if raw
            else (lambda result, _row: result["id"]),
            execute=lambda ids: sql("SELECT * FROM test WHERE id IN {}", sql.in_(ids)),
        )
        run = R.request(find_by_id)
        result = yield from fx.all_dict(
            {"one": run(1), "two": run(2), "three": run(101).flip()}, concurrency="unbounded"
        )
        assert result["one"] == {"id": 1, "name": "name1"}
        assert result["two"] == {"id": 2, "name": "name2"}
        assert isinstance(result["three"], fx.NoSuchElementException)

    return body


@testing.effect
def test_find_by_id_find_by_id(libsql_server: LibsqlServer):
    """findById / find by id"""
    yield from _on(libsql_server, _find_by_id(raw=False))


@testing.effect
def test_find_by_id_using_raw_rows(libsql_server: LibsqlServer):
    """findById / using raw rows"""
    yield from _on(libsql_server, _find_by_id(raw=True))
