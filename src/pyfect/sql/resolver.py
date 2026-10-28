"""Batched SQL requests (Effect's ``effect/sql/SqlResolver``).

A resolver turns the requests made in the same scheduler tick into one
query: each payload is encoded with the request schema (a payload that
fails to encode fails its own request), ``execute`` runs once with the
encoded payloads, and the rows decode with the result schema. Requests
inside a client's transaction batch only with requests of the same
transaction::

    get_person = resolver.find_by_id(
        id=S.Number,
        result=Person,
        result_id=lambda person, _row: person.id,
        execute=lambda ids: sql("SELECT * FROM people WHERE id IN {}", sql.in_(ids)),
    )
    person = yield from resolver.request(1, get_person)
"""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from collections.abc import Callable, Hashable, Sequence
from typing import Any, Never, cast, overload

from pyfect._core import Effect, _Locally, _MatchCause, _Succeed, _Suspend
from pyfect.batching import Entry, Request, RequestResolver
from pyfect.batching import request as make_request
from pyfect.cause import Cause
from pyfect.errors import NoSuchElementException
from pyfect.exit import Failure, Success
from pyfect.exit import fail as exit_fail
from pyfect.schema import Array, Codec, SchemaError, decode_unknown_effect, encode_effect
from pyfect.sql.client import SqlClient, TransactionLevel
from pyfect.sql.error import ResultLengthMismatch


class SqlRequest[In, A, E = Never, R = Never](Request[A, E, R]):
    """A request carrying ``payload``; requests with equal payloads are
    equal."""

    __slots__ = ("payload",)

    def __init__(self, payload: In) -> None:
        self.payload = payload

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, SqlRequest):
            return False
        that: SqlRequest[Any, Any, Any, Any] = other  # pyright: ignore[reportUnknownVariableType]
        return bool(that.payload == self.payload)

    def __hash__(self) -> int:
        return hash(self.payload)

    def __repr__(self) -> str:
        return f"SqlRequest({self.payload!r})"


type SqlResolver[In, A, E, R] = RequestResolver[SqlRequest[In, A, E, R], E]


@overload
def request[In, A, E, R](payload: In, resolver: SqlResolver[In, A, E, R], /) -> Effect[A, E, R]: ...
@overload
def request[In, A, E, R](
    resolver: SqlResolver[In, A, E, R], /
) -> Callable[[In], Effect[A, E, R]]: ...
def request(*args: Any) -> Any:
    """Make the request of ``payload`` through ``resolver``;
    ``request(resolver)`` is the function of the payload."""
    if len(args) == 1:
        resolver: SqlResolver[Any, Any, Any, Any] = args[0]

        def make(payload: object) -> Effect[Any, Any, Any]:
            return _request(payload, resolver)

        return make
    return _request(args[0], args[1])


def _request(payload: object, resolver: SqlResolver[Any, Any, Any, Any]) -> Effect[Any, Any, Any]:
    req: SqlRequest[Any, Any, Any, Any] = SqlRequest(payload)
    return make_request(req, resolver)


def _transaction_key(entry: Entry[Any]) -> Hashable:
    """The transaction the request was made in (by identity), or ``None``."""
    context = entry.context
    found, client = context.lookup(SqlClient)
    if not found:
        return None
    found, level = context.lookup(client.transaction_service)
    return cast("TransactionLevel", level) if found else None


type _Entries = Sequence[Entry[SqlRequest[Any, Any, Any, Any]]]


def _in_context[A, E](effect: Effect[A, E, Any], entry: Entry[Any]) -> Effect[A, E]:
    context = entry.context
    return _Locally(effect, lambda _: context)


def _fail_entry(entry: Entry[Any], cause: Cause[SchemaError]) -> None:
    entry.complete_unsafe(Failure(cause))


def _encode_each(
    entries: _Entries,
    schema: Codec[Any, Any, Any, Any],
    fail: Callable[[Entry[Any], Cause[SchemaError]], None] = _fail_entry,
) -> Effect[tuple[list[object], list[Entry[Any]]]]:
    """Each entry's encoded payload, and the entries that encoded; those
    that did not are failed with the schema error (by ``fail``)."""
    encode = encode_effect(schema)
    inputs: list[object] = []
    encoded: list[Entry[Any]] = []

    def one(entry: Entry[Any]) -> Effect[None]:
        def failed(cause: Cause[SchemaError]) -> Effect[None]:
            fail(entry, cause)
            return _Succeed(None)

        def succeeded(value: object) -> Effect[None]:
            inputs.append(value)
            encoded.append(entry)
            return _Succeed(None)

        return _MatchCause(_in_context(encode(entry.request.payload), entry), failed, succeeded)

    run: Effect[None] = _Succeed(None)
    for entry in entries:
        run = run.and_then(_Suspend(lambda entry=entry: one(entry)))
    return run.map(lambda _: (inputs, encoded))


def _decode_rows(
    result: Codec[Any, Any, Any, Any], rows: Sequence[object], entry: Entry[Any]
) -> Effect[tuple[Any, ...], SchemaError]:
    return _in_context(decode_unknown_effect(Array(result))(rows), entry)


def ordered[In, A, E = Never, R = Never](
    *,
    request: Codec[In, Any, Any, Any],
    result: Codec[A, Any, Any, Any],
    execute: Callable[[Sequence[Any]], Effect[Sequence[object], E, R]],
) -> SqlResolver[In, A, E | ResultLengthMismatch | SchemaError, R]:
    """``execute`` returns one row per request, in the order of the
    requests; a different number of rows fails every request with
    ``ResultLengthMismatch``."""

    def resolve(entries: _Entries, _key: Hashable) -> Effect[None, Any]:
        def run(encoded: tuple[list[object], list[Entry[Any]]]) -> Effect[None, Any]:
            inputs, encoded_entries = encoded
            if not inputs:
                return _Succeed(None)

            def check(rows: Sequence[object]) -> Effect[None, Any]:
                if len(rows) != len(inputs):
                    from pyfect.effect import fail

                    return fail(ResultLengthMismatch(expected=len(inputs), actual=len(rows)))
                return _decode_rows(result, rows, entries[0]).map(
                    lambda values: _complete_all(encoded_entries, values)
                )

            return _in_context(execute(inputs), entries[0]).flat_map(check)

        return _encode_each(entries, request).flat_map(run)

    return RequestResolver.make_grouped(key=_transaction_key, resolver=resolve)


def _complete_all(entries: Sequence[Entry[Any]], values: Sequence[object]) -> None:
    for entry, value in zip(entries, values, strict=True):
        entry.complete_unsafe(Success(value))


_NO_SUCH_ELEMENT = exit_fail(NoSuchElementException())


def grouped[In, A, K: Hashable, Row, E = Never, R = Never](
    *,
    request: Codec[In, Any, Any, Any],
    request_group_key: Callable[[In], K],
    result: Codec[A, Any, Any, Any],
    result_group_key: Callable[[A, Row], K],
    execute: Callable[[Sequence[Any]], Effect[Sequence[Row], E, R]],
) -> SqlResolver[In, tuple[A, ...], E | SchemaError | NoSuchElementException, R]:
    """Each request gets the results whose ``result_group_key`` equals its
    ``request_group_key`` (at least one; none fails with
    ``NoSuchElementException``)."""

    def resolve(entries: _Entries, _key: Hashable) -> Effect[None, Any]:
        def run(encoded: tuple[list[object], list[Entry[Any]]]) -> Effect[None, Any]:
            inputs, _ = encoded
            if not inputs:
                return _Succeed(None)

            def complete(rows: Sequence[Row], values: Sequence[A]) -> None:
                groups: dict[K, list[A]] = {}
                for value, row in zip(values, rows, strict=True):
                    groups.setdefault(result_group_key(value, row), []).append(value)
                for entry in entries:
                    group = groups.get(request_group_key(entry.request.payload))
                    entry.complete_unsafe(
                        _NO_SUCH_ELEMENT if group is None else Success(tuple(group))
                    )

            def decode(rows: Sequence[Row]) -> Effect[None, Any]:
                return _decode_rows(result, rows, entries[0]).map(
                    lambda values: complete(rows, values)
                )

            return _in_context(execute(inputs), entries[0]).flat_map(decode)

        return _encode_each(entries, request).flat_map(run)

    return RequestResolver.make_grouped(key=_transaction_key, resolver=resolve)


def find_by_id[Id: Hashable, A, Row, E = Never, R = Never](
    *,
    id: Codec[Id, Any, Any, Any],
    result: Codec[A, Any, Any, Any],
    result_id: Callable[[A, Row], Id],
    execute: Callable[[Sequence[Any]], Effect[Sequence[Row], E, R]],
) -> SqlResolver[Id, A, E | SchemaError | NoSuchElementException, R]:
    """Each request gets the result whose ``result_id`` is its id (none
    fails with ``NoSuchElementException``). Equal ids are queried once."""

    def resolve(entries: _Entries, _key: Hashable) -> Effect[None, Any]:
        by_id: dict[Hashable, list[Entry[Any]]] = {}
        for entry in entries:
            by_id.setdefault(entry.request.payload, []).append(entry)
        firsts = [same[0] for same in by_id.values()]

        def run(encoded: tuple[list[object], list[Entry[Any]]]) -> Effect[None, Any]:
            inputs, _ = encoded
            if not inputs:
                return _Succeed(None)

            def complete(rows: Sequence[Row], values: Sequence[A]) -> None:
                for value, row in zip(values, rows, strict=True):
                    same = by_id.pop(result_id(value, row), None)
                    for entry in same or ():
                        entry.complete_unsafe(Success(value))
                for same in by_id.values():
                    for entry in same:
                        entry.complete_unsafe(_NO_SUCH_ELEMENT)

            def decode(rows: Sequence[Row]) -> Effect[None, Any]:
                return _decode_rows(result, rows, entries[0]).map(
                    lambda values: complete(rows, values)
                )

            return _in_context(execute(inputs), entries[0]).flat_map(decode)

        def fail_all(entry: Entry[Any], cause: Cause[SchemaError]) -> None:
            # Requests for the same id share its encoding failure.
            for same in by_id.pop(entry.request.payload):
                same.complete_unsafe(Failure(cause))

        return _encode_each(firsts, id, fail_all).flat_map(run)

    return RequestResolver.make_grouped(key=_transaction_key, resolver=resolve)


def void[In, E = Never, R = Never](
    *,
    request: Codec[In, Any, Any, Any],
    execute: Callable[[Sequence[Any]], Effect[object, E, R]],
) -> SqlResolver[In, None, E | SchemaError, R]:
    """Requests without a result: ``execute`` runs them together."""

    def resolve(entries: _Entries, _key: Hashable) -> Effect[None, Any]:
        def run(encoded: tuple[list[object], list[Entry[Any]]]) -> Effect[None, Any]:
            inputs, _ = encoded
            if not inputs:
                return _Succeed(None)

            def complete(_: object) -> None:
                for entry in entries:
                    entry.complete_unsafe(Success(None))

            return _in_context(execute(inputs), entries[0]).map(complete)

        return _encode_each(entries, request).flat_map(run)

    return RequestResolver.make_grouped(key=_transaction_key, resolver=resolve)


__all__ = ["SqlRequest", "SqlResolver", "find_by_id", "grouped", "ordered", "request", "void"]
