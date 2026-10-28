"""Ports of Effect's ``sql-sqlite-node/test/Resolver.test.ts``.

Each test's docstring is the Effect test title.
"""

from collections.abc import Sequence
from pathlib import Path
from typing import Any, TypedDict

import pyfect as fx
from pyfect import schema as S
from pyfect import testing
from pyfect.sql import resolver as R
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
