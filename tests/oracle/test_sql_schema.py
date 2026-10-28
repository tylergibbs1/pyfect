"""Ports of Effect's ``sql/SqlSchema.test.ts``.

Each test's docstring is the Effect test title.
"""

from collections.abc import Callable
from typing import TypedDict

import pyfect as fx
from pyfect import schema as S
from pyfect import testing
from pyfect.sql import schema as SqlSchema


class _Value(TypedDict):
    value: str


class _Id(TypedDict):
    id: float


def _rows(*rows: object) -> Callable[[object], fx.Effect[list[object]]]:
    def execute(_request: object) -> fx.Effect[list[object]]:
        return fx.succeed(list(rows))

    return execute


@testing.effect
def test_find_all_returns_decoded_results():
    """findAll / returns decoded results"""
    query = SqlSchema.find_all(
        request=S.NumberFromString,
        result=S.Struct(_Value),
        execute=lambda request: fx.succeed([{"value": f"id:{request}"}]),
    )
    assert (yield from query(1)) == [{"value": "id:1"}]


@testing.effect
def test_find_all_returns_empty_array_when_no_rows():
    """findAll / returns empty array when no rows"""
    query = SqlSchema.find_all(request=S.String, result=S.String, execute=_rows())
    assert (yield from query("test")) == []


@testing.effect
def test_find_all_fails_when_a_row_cannot_be_decoded():
    """findAll / fails when a row cannot be decoded"""
    query = SqlSchema.find_all(
        request=S.String, result=S.Struct(_Id), execute=_rows({"id": "not-a-number"})
    )
    error = yield from query("ignored").flip()
    assert isinstance(error, S.SchemaError)


@testing.effect
def test_find_non_empty_returns_non_empty_decoded_results():
    """findNonEmpty / returns non-empty decoded results"""
    query = SqlSchema.find_non_empty(
        request=S.NumberFromString,
        result=S.Struct(_Value),
        execute=lambda request: fx.succeed([{"value": f"id:{request}"}]),
    )
    assert (yield from query(1)) == [{"value": "id:1"}]


@testing.effect
def test_find_non_empty_fails_with_no_such_element_error_when_no_rows():
    """findNonEmpty / fails with NoSuchElementError when no rows"""
    query = SqlSchema.find_non_empty(request=S.String, result=S.String, execute=_rows())
    error = yield from query("test").flip()
    assert isinstance(error, fx.NoSuchElementException)


@testing.effect
def test_void_encodes_request_and_discards_result():
    """void / encodes request and discards result"""
    captured: list[object] = []

    def execute(request: object) -> fx.Effect[None]:
        captured.append(request)
        return fx.void

    query = SqlSchema.void(request=S.NumberFromString, execute=execute)
    yield from query(42)
    assert captured == ["42"]


@testing.effect
def test_find_one_returns_the_first_decoded_row():
    """findOne / returns the first decoded row"""
    query = SqlSchema.find_one(request=S.String, result=S.NumberFromString, execute=_rows("1", "2"))
    assert (yield from query("ignored")) == 1


@testing.effect
def test_find_one_fails_with_no_such_element_error_when_no_rows_are_returned():
    """findOne / fails with NoSuchElementError when no rows are returned"""
    query = SqlSchema.find_one(request=S.String, result=S.String, execute=_rows())
    error = yield from query("ignored").flip()
    assert isinstance(error, fx.NoSuchElementException)


@testing.effect
def test_find_one_fails_when_the_first_row_cannot_be_decoded():
    """findOne / fails when the first row cannot be decoded"""
    query = SqlSchema.find_one(
        request=S.String, result=S.Struct(_Id), execute=_rows({"id": "not-a-number"})
    )
    error = yield from query("ignored").flip()
    assert isinstance(error, S.SchemaError)


@testing.effect
def test_find_one_option_returns_option_some_when_a_row_exists():
    """findOneOption / returns Option.some when a row exists"""
    query = SqlSchema.find_one_option(
        request=S.NumberFromString,
        result=S.Struct(_Value),
        execute=lambda request: fx.succeed([{"value": f"id:{request}"}]),
    )
    result = yield from query(1)
    assert result == fx.Some({"value": "id:1"})


@testing.effect
def test_find_one_option_returns_option_none_when_no_rows_are_returned():
    """findOneOption / returns Option.none when no rows are returned"""
    query = SqlSchema.find_one_option(request=S.NumberFromString, result=S.String, execute=_rows())
    assert (yield from query(1)) is None


@testing.effect
def test_find_one_option_fails_when_the_first_row_cannot_be_decoded():
    """findOneOption / fails when the first row cannot be decoded"""
    query = SqlSchema.find_one_option(
        request=S.String, result=S.Struct(_Id), execute=_rows({"id": "not-a-number"})
    )
    error = yield from query("ignored").flip()
    assert isinstance(error, S.SchemaError)
