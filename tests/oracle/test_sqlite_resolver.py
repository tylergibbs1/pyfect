"""Ports of Effect's ``sql-sqlite-node/test/Resolver.test.ts``.

Each test's docstring is the Effect test title.
"""

from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any, TypedDict, cast

import pyfect as fx
from pyfect import schema as S
from pyfect import testing
from pyfect.context import Context
from pyfect.sql import resolver as R
from pyfect.sql.client import SqlClient
from pyfect.sql.error import ResultLengthMismatch

from ._sqlite import make_client


class _Row(TypedDict):
    id: float
    name: str


def _seeded(directory: Path):
    def body():
        sql = yield from make_client(directory)
        yield from sql("CREATE TABLE test (id INTEGER PRIMARY KEY, name TEXT)")
        rows = [{"id": i, "name": f"name{i}"} for i in range(1, 101)]
        yield from sql("INSERT INTO test {}", sql.insert(rows))
        return sql

    return fx.gen(body)


@testing.effect
def test_ordered_insert(tmp_path: Path):
    """ordered / insert"""
    batches: list[list[str]] = []
    sql = yield from _seeded(tmp_path)

    def execute(names: Sequence[Any]) -> fx.Effect[Sequence[object], Any]:
        batches.append(list(names))
        return sql("INSERT INTO test {} RETURNING *", sql.insert([{"name": n} for n in names]))

    insert = R.ordered(request=S.String, result=S.Struct(_Row), execute=execute)
    run = R.request(insert)
    result = yield from fx.all_dict({"one": run("one"), "two": run("two")}, concurrency="unbounded")
    assert result == {"one": {"id": 101, "name": "one"}, "two": {"id": 102, "name": "two"}}
    assert batches == [["one", "two"]]


@testing.effect
def test_ordered_result_length_mismatch(tmp_path: Path):
    """ordered / result length mismatch"""
    batches: list[list[float]] = []
    sql = yield from _seeded(tmp_path)

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


def _find_by_name(sql: Any, *, raw: bool) -> Any:
    return R.grouped(
        request=S.String,
        request_group_key=lambda name: name,
        result=S.Struct(_Row),
        result_group_key=(lambda _result, row: row["name"])
        if raw
        else (lambda result, _row: result["name"]),
        execute=lambda names: sql("SELECT * FROM test WHERE name IN {}", sql.in_(names)),
    )


def _grouped(directory: Path, *, raw: bool):
    sql = yield from _seeded(directory)
    find_by_name = _find_by_name(sql, raw=raw)
    yield from sql("INSERT INTO test {}", sql.insert({"name": "name1"}))
    run = R.request(find_by_name)
    result = yield from fx.all_dict(
        {"one": run("name1"), "two": run("name2"), "three": run("name0").flip()},
        concurrency="unbounded",
    )
    assert result["one"] == ({"id": 1, "name": "name1"}, {"id": 101, "name": "name1"})
    assert result["two"] == ({"id": 2, "name": "name2"},)
    assert isinstance(result["three"], fx.NoSuchElementException)


@testing.effect
def test_grouped_find_by_name(tmp_path: Path):
    """grouped / find by name"""
    yield from _grouped(tmp_path, raw=False)


@testing.effect
def test_grouped_using_raw_rows(tmp_path: Path):
    """grouped / using raw rows"""
    yield from _grouped(tmp_path, raw=True)


def _find_by_id(directory: Path, *, raw: bool):
    sql = yield from _seeded(directory)
    find_by_id = R.find_by_id(
        id=S.Number,
        result=S.Struct(_Row),
        result_id=(lambda _result, row: row["id"]) if raw else (lambda result, _row: result["id"]),
        execute=lambda ids: sql("SELECT * FROM test WHERE id IN {}", sql.in_(ids)),
    )
    run = R.request(find_by_id)
    result = yield from fx.all_dict(
        {"one": run(1), "two": run(2), "three": run(101).flip()}, concurrency="unbounded"
    )
    assert result["one"] == {"id": 1, "name": "name1"}
    assert result["two"] == {"id": 2, "name": "name2"}
    assert isinstance(result["three"], fx.NoSuchElementException)


@testing.effect
def test_find_by_id_find_by_id(tmp_path: Path):
    """findById / find by id"""
    yield from _find_by_id(tmp_path, raw=False)


@testing.effect
def test_find_by_id_using_raw_rows(tmp_path: Path):
    """findById / using raw rows"""
    yield from _find_by_id(tmp_path, raw=True)


def _void_insert(sql: Any, batches: list[list[float]]) -> Callable[[float], fx.Effect[None, Any]]:
    def execute(ids: Sequence[Any]) -> fx.Effect[Any, Any]:
        batches.append(list(ids))
        return sql("INSERT INTO writes {}", sql.insert([{"id": i} for i in ids]))

    resolver = R.void(request=S.Number, execute=execute)

    def insert(id_: float) -> fx.Effect[None, Any]:
        return R.request(id_, resolver)

    return insert


def _two_clients(directory: Path):
    def body():
        (directory / "a").mkdir()
        (directory / "b").mkdir()
        sql = yield from make_client(directory / "a")
        other = yield from make_client(directory / "b")
        yield from sql("CREATE TABLE writes (id INTEGER PRIMARY KEY)")
        return sql, other

    return fx.gen(body)


@testing.effect
def test_void_keeps_requests_outside_a_transaction_out_of_its_batch(tmp_path: Path):
    """void / keeps requests outside a transaction out of its batch"""
    batches: list[list[float]] = []
    sql, other = yield from _two_clients(tmp_path)
    insert = _void_insert(sql, batches)
    # The driver's BEGIN runs on its worker thread, where Effect's node:sqlite
    # runs it synchronously, so the request outside waits for the transaction
    # to begin to be made in the same batching window.
    begun = fx.Deferred[None]()
    yield from fx.all(
        sql.with_transaction(
            begun.succeed(None)
            .and_then(fx.all(insert(1), insert(3), concurrency="unbounded"))
            .and_then(fx.fail("rollback"))
        ).exit(),
        begun.wait().and_then(fx.yield_now()).and_then(insert(2)),
        concurrency="unbounded",
    ).pipe(fx.provide_service(SqlClient, other))
    assert batches == [[1, 3], [2]]
    assert (yield from sql("SELECT * FROM writes")) == [{"id": 2}]


@testing.effect
def test_void_keeps_requests_in_another_clients_transaction_out_of_its_batch(tmp_path: Path):
    """void / keeps requests in another client's transaction out of its batch"""
    batches: list[list[float]] = []
    sql, other = yield from _two_clients(tmp_path)
    insert = _void_insert(sql, batches)
    begun = fx.Deferred[None]()
    yield from other.with_transaction(
        fx.all(
            sql.with_transaction(
                begun.succeed(None).and_then(insert(1)).and_then(fx.fail("rollback"))
            )
            .exit()
            .pipe(fx.provide_service(SqlClient, other)),
            begun.wait().and_then(fx.yield_now()).and_then(insert(2)),
            concurrency="unbounded",
        )
    )
    assert batches == [[1], [2]]
    assert (yield from sql("SELECT * FROM writes")) == [{"id": 2}]


@testing.effect
def test_void_keeps_requests_without_the_transaction_service_out_of_its_batch(tmp_path: Path):
    """void / keeps requests without the transaction service out of its batch"""
    batches: list[list[float]] = []
    (tmp_path / "a").mkdir()
    sql = yield from make_client(tmp_path / "a")
    yield from sql("CREATE TABLE writes (id INTEGER PRIMARY KEY)")
    insert = _void_insert(sql, batches)
    outside: list[fx.Fiber[None, Any]] = []

    def body():
        # Omitting the service types the request as needing it again; at run time
        # the connection it would name is simply gone.
        without: fx.Effect[None, Any] = cast(
            "fx.Effect[None, Any]",
            insert(2).pipe(fx.update_context(Context.omit(sql.transaction_service))),
        )
        fiber = yield from without.fork()
        outside.append(fiber)
        yield from insert(1)
        return (yield from fx.fail("rollback"))

    yield from sql.with_transaction(fx.gen(body)).exit()
    yield from outside[0].join()
    assert batches == [[1], [2]]
    assert (yield from sql("SELECT * FROM writes")) == [{"id": 2}]
