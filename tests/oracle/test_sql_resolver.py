"""Ports of Effect's ``sql/SqlResolver.test.ts``.

Each test's docstring is the Effect test title.
"""

from collections.abc import Sequence
from typing import Any, TypedDict

import pyfect as fx
from pyfect import schema as S
from pyfect import testing
from pyfect.sql import resolver as R

_Positive = S.Number.check(S.is_greater_than(0))


class _Id(TypedDict):
    id: float


class _Named(TypedDict):
    id: float
    name: str


@testing.effect
def test_grouped_does_not_execute_a_batch_when_every_request_fails_encoding():
    """grouped / does not execute a batch when every request fails encoding"""
    executions: list[int] = []

    def execute(inputs: Sequence[Any]) -> fx.Effect[Sequence[Any]]:
        executions.append(1)
        return fx.succeed(inputs)

    resolver = R.grouped(
        request=_Positive,
        request_group_key=lambda request: request,
        result=S.Number,
        result_group_key=lambda result, _row: result,
        execute=execute,
    )

    error = yield from R.request(-1, resolver).flip()

    assert isinstance(error, S.SchemaError)
    assert not executions


@testing.effect
def test_find_by_id_does_not_execute_a_batch_when_every_request_fails_encoding():
    """findById / does not execute a batch when every request fails encoding"""
    executions: list[int] = []

    def execute(inputs: Sequence[Any]) -> fx.Effect[Sequence[_Id]]:
        executions.append(1)
        return fx.succeed([{"id": i} for i in inputs])

    resolver = R.find_by_id(
        id=_Positive,
        result=S.Struct(_Id),
        result_id=lambda result, _row: result["id"],
        execute=execute,
    )

    error = yield from R.request(-1, resolver).flip()

    assert isinstance(error, S.SchemaError)
    assert not executions


@testing.effect
def test_find_by_id_completes_duplicate_requests_when_id_encoding_fails():
    """findById / completes duplicate requests when id encoding fails"""
    resolver = R.find_by_id(
        id=_Positive,
        result=S.Struct(_Id),
        result_id=lambda result, _row: result["id"],
        execute=lambda inputs: fx.succeed([{"id": i} for i in inputs]),
    )
    execute = R.request(resolver)

    errors = yield from fx.all(execute(-1).flip(), execute(-1).flip(), concurrency="unbounded")

    assert [type(error) for error in errors] == [S.SchemaError, S.SchemaError]


@testing.effect
def test_find_by_id_deduplicates_requests_by_id():
    """findById / deduplicates requests by id"""
    batches: list[list[float]] = []

    def execute(ids: Sequence[Any]) -> fx.Effect[Sequence[_Named]]:
        batches.append(list(ids))
        return fx.succeed([{"id": i, "name": f"name{i}"} for i in ids])

    find_by_id = R.find_by_id(
        id=S.Number,
        result=S.Struct(_Named),
        result_id=lambda result, _row: result["id"],
        execute=execute,
    )
    run = R.request(find_by_id)

    result = yield from fx.all_dict(
        {"one": run(1), "oneAgain": run(1), "two": run(2)}, concurrency="unbounded"
    )
    assert result == {
        "one": {"id": 1, "name": "name1"},
        "oneAgain": {"id": 1, "name": "name1"},
        "two": {"id": 2, "name": "name2"},
    }
    assert batches == [[1, 2]]


@testing.effect
def test_ordered_does_not_execute_a_batch_when_every_request_fails_encoding():
    """ordered / does not execute a batch when every request fails encoding"""
    executions: list[int] = []

    def execute(inputs: Sequence[Any]) -> fx.Effect[Sequence[str]]:
        executions.append(1)
        return fx.succeed([str(i) for i in inputs])

    resolver = R.ordered(request=_Positive, result=S.String, execute=execute)

    error = yield from R.request(-1, resolver).flip()

    assert isinstance(error, S.SchemaError)
    assert not executions


@testing.effect
def test_ordered_keeps_valid_results_aligned_when_another_request_fails_encoding():
    """ordered / keeps valid results aligned when another request fails encoding"""
    resolver = R.ordered(
        request=_Positive,
        result=S.String,
        execute=lambda inputs: fx.succeed([f"value-{i:g}" for i in inputs]),
    )
    run = R.request(resolver)

    invalid, valid = yield from fx.all(run(-1).exit(), run(2).exit(), concurrency="unbounded")

    assert isinstance(invalid, fx.Failure)
    assert valid == fx.Success("value-2")


@testing.effect
def test_void_does_not_execute_a_batch_when_every_request_fails_encoding():
    """void / does not execute a batch when every request fails encoding"""
    executions: list[int] = []

    def execute(inputs: Sequence[Any]) -> fx.Effect[Sequence[Any]]:
        executions.append(1)
        return fx.succeed(inputs)

    resolver = R.void(request=_Positive, execute=execute)

    error = yield from R.request(-1, resolver).flip()

    assert isinstance(error, S.SchemaError)
    assert not executions
