"""Queries typed by schemas (Effect's ``effect/sql/SqlSchema``).

Each function takes the request schema, the result schema and ``execute``,
and returns the query as a function of the request: the request is encoded
before ``execute`` runs with it, and the rows it returns are decoded::

    find_person = sql_schema.find_one(
        request=S.Number,
        result=Person,
        execute=lambda id: sql("SELECT * FROM people WHERE id = {}", id),
    )
    person = yield from find_person(1)
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any, Never

from pyfect._core import Effect
from pyfect.effect import fail, succeed
from pyfect.errors import NoSuchElementException
from pyfect.option import Option, Some
from pyfect.schema import Array, Codec, SchemaError, decode_unknown_effect, encode_effect


def find_all[In, A, E = Never, R = Never](
    *,
    request: Codec[In, Any, Any, Any],
    result: Codec[A, Any, Any, Any],
    execute: Callable[[Any], Effect[Sequence[object], E, R]],
) -> Callable[[In], Effect[list[A], E | SchemaError, R]]:
    """Every row, decoded."""
    encode = encode_effect(request)
    decode = decode_unknown_effect(Array(result))

    def query(value: In) -> Effect[list[A], E | SchemaError, R]:
        return encode(value).flat_map(execute).flat_map(decode).map(list)

    return query


def find_non_empty[In, A, E = Never, R = Never](
    *,
    request: Codec[In, Any, Any, Any],
    result: Codec[A, Any, Any, Any],
    execute: Callable[[Any], Effect[Sequence[object], E, R]],
) -> Callable[[In], Effect[list[A], E | SchemaError | NoSuchElementException, R]]:
    """Every row, decoded; no rows fails with ``NoSuchElementException``."""
    find = find_all(request=request, result=result, execute=execute)

    def non_empty(rows: list[A]) -> Effect[list[A], NoSuchElementException]:
        return succeed(rows) if rows else fail(NoSuchElementException())

    def query(value: In) -> Effect[list[A], E | SchemaError | NoSuchElementException, R]:
        return find(value).flat_map(non_empty)

    return query


def void[In, E = Never, R = Never](
    *,
    request: Codec[In, Any, Any, Any],
    execute: Callable[[Any], Effect[object, E, R]],
) -> Callable[[In], Effect[None, E | SchemaError, R]]:
    """Runs ``execute``, ignoring its result."""
    encode = encode_effect(request)

    def query(value: In) -> Effect[None, E | SchemaError, R]:
        return encode(value).flat_map(execute).as_void()

    return query


def find_one[In, A, E = Never, R = Never](
    *,
    request: Codec[In, Any, Any, Any],
    result: Codec[A, Any, Any, Any],
    execute: Callable[[Any], Effect[Sequence[object], E, R]],
) -> Callable[[In], Effect[A, E | SchemaError | NoSuchElementException, R]]:
    """The first row, decoded; no rows fails with
    ``NoSuchElementException``."""
    encode = encode_effect(request)
    decode = decode_unknown_effect(result)

    def first(rows: Sequence[object]) -> Effect[A, SchemaError | NoSuchElementException]:
        return decode(rows[0]) if rows else fail(NoSuchElementException())

    def query(value: In) -> Effect[A, E | SchemaError | NoSuchElementException, R]:
        return encode(value).flat_map(execute).flat_map(first)

    return query


def find_one_option[In, A, E = Never, R = Never](
    *,
    request: Codec[In, Any, Any, Any],
    result: Codec[A, Any, Any, Any],
    execute: Callable[[Any], Effect[Sequence[object], E, R]],
) -> Callable[[In], Effect[Option[A], E | SchemaError, R]]:
    """The first row decoded, or ``None`` for no rows."""
    encode = encode_effect(request)
    decode = decode_unknown_effect(result)

    def first(rows: Sequence[object]) -> Effect[Option[A], SchemaError]:
        if not rows:
            return succeed(None)
        return decode(rows[0]).map(Some)

    def query(value: In) -> Effect[Option[A], E | SchemaError, R]:
        return encode(value).flat_map(execute).flat_map(first)

    return query


__all__ = ["find_all", "find_non_empty", "find_one", "find_one_option", "void"]
