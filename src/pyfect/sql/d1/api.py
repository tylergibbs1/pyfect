"""D1's HTTP API, as ``D1Client`` uses it: ``POST .../query`` (rows as
objects) and ``POST .../raw`` (rows as arrays), each with one statement
(``{"sql", "params"}``) or a batch (``{"batch": [...]}``), which D1 runs
in one transaction.

Every method is an effect sent with a pyfect ``HttpClient``; interrupting
it aborts the request. Failures are a ``D1ApiError`` for an answer that
reports one and an ``HttpClientError`` for a request that got no answer.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, cast

from pyfect._core import Effect
from pyfect._json_text import Json
from pyfect.effect import fail, provide_service, succeed, suspend
from pyfect.http import request as http_request
from pyfect.http.client import HttpClientService, TracerDisabledWhen
from pyfect.http.error import HttpClientError
from pyfect.http.response import HttpClientResponse
from pyfect.redacted import Redacted
from pyfect.sql.connection import Row, ValueRow

type Param = int | float | str | None
"""What D1's HTTP API binds: ``bool`` is sent as ``1`` / ``0``, as the
Workers binding stores it."""

type Query = tuple[str, Sequence[Param]]
"""A statement's SQL and parameters."""


@dataclass(frozen=True, slots=True)
class D1Message:
    """One entry of the API's ``errors``."""

    code: int
    message: str


class D1ApiError(Exception):
    """An answer reporting a failure: its HTTP status and the API's
    ``errors`` (D1's own message, such as ``UNIQUE constraint failed: ...:
    SQLITE_CONSTRAINT``, is the first)."""

    def __init__(self, status: int, errors: Sequence[D1Message]) -> None:
        message = errors[0].message if errors else f"D1 request failed with status {status}"
        super().__init__(message)
        self.status = status
        self.errors = tuple(errors)


@dataclass(frozen=True, slots=True, kw_only=True)
class D1Meta:
    """What D1 reports about a statement (unreported fields are ``0`` /
    ``None``)."""

    changes: int = 0
    last_row_id: int = 0
    changed_db: bool = False
    duration: float = 0.0
    rows_read: int = 0
    rows_written: int = 0
    size_after: int | None = None
    served_by_region: str | None = None
    served_by_primary: bool | None = None


@dataclass(frozen=True, slots=True)
class D1Result:
    """The answer to one statement of ``query`` (the Workers binding's
    ``D1Result``): ``.raw`` of a ``D1Client`` statement gives it."""

    results: Sequence[Row]
    meta: D1Meta = field(default_factory=D1Meta)
    success: bool = True


@dataclass(frozen=True, slots=True)
class D1RawResult:
    """The answer to one statement of ``raw``: its columns and the values
    of each row in their order."""

    columns: Sequence[str]
    rows: Sequence[ValueRow]
    meta: D1Meta = field(default_factory=D1Meta)


def bind(value: object) -> Param:
    """``value`` as D1's HTTP API binds it; ``TypeError`` for what JSON
    cannot carry as a parameter (``bytes`` included: the API binds no
    blobs)."""
    if isinstance(value, bool):
        return int(value)
    if value is None or isinstance(value, (int, float, str)):
        return value
    raise TypeError(f"D1's HTTP API cannot bind a value of type {type(value).__name__}")


def _always(_request: object) -> bool:
    return True


def _malformed(status: int) -> D1ApiError:
    return D1ApiError(status, [D1Message(0, "malformed D1 API response")])


def _int(meta: Mapping[str, Any], key: str) -> int:
    value = meta.get(key)
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def _meta(value: object) -> D1Meta:
    if not isinstance(value, dict):
        return D1Meta()
    meta = cast("dict[str, Any]", value)
    size_after = meta.get("size_after")
    region = meta.get("served_by_region")
    primary = meta.get("served_by_primary")
    duration = meta.get("duration")
    return D1Meta(
        changes=_int(meta, "changes"),
        last_row_id=_int(meta, "last_row_id"),
        changed_db=meta.get("changed_db") is True,
        duration=float(duration) if isinstance(duration, (int, float)) else 0.0,
        rows_read=_int(meta, "rows_read"),
        rows_written=_int(meta, "rows_written"),
        size_after=size_after if isinstance(size_after, int) else None,
        served_by_region=region if isinstance(region, str) else None,
        served_by_primary=primary if isinstance(primary, bool) else None,
    )


def _messages(value: object) -> list[D1Message]:
    if not isinstance(value, list):
        return []
    found: list[D1Message] = []
    for entry in cast("list[object]", value):
        if isinstance(entry, dict):
            item = cast("dict[str, Any]", entry)
            code = item.get("code")
            found.append(
                D1Message(code if isinstance(code, int) else 0, str(item.get("message", "")))
            )
    return found


def _results(status: int, body: Json) -> list[dict[str, Any]]:
    """The envelope's ``result`` entries, or the failure it reports."""
    if not isinstance(body, dict):
        raise _malformed(status)
    if body.get("success") is not True or not 200 <= status < 300:
        raise D1ApiError(status, _messages(body.get("errors")))
    result = body.get("result")
    if not isinstance(result, list):
        raise _malformed(status)
    entries: list[dict[str, Any]] = []
    for entry in result:
        if not isinstance(entry, dict):
            raise _malformed(status)
        if entry.get("success") is False:
            raise D1ApiError(status, _messages(entry.get("errors")))
        entries.append(cast("dict[str, Any]", entry))
    return entries


def _rows(status: int, entry: Mapping[str, Any]) -> D1Result:
    results: object = entry.get("results", [])
    if not isinstance(results, list) or not all(
        isinstance(r, dict) for r in cast("list[object]", results)
    ):
        raise _malformed(status)
    return D1Result(cast("list[Row]", results), _meta(entry.get("meta")))


def _raw_rows(status: int, entry: Mapping[str, Any]) -> D1RawResult:
    results: object = entry.get("results") or {"columns": [], "rows": []}
    if not isinstance(results, dict):
        raise _malformed(status)
    table = cast("dict[str, Any]", results)
    columns, rows = table.get("columns", []), table.get("rows", [])
    if not isinstance(columns, list) or not isinstance(rows, list):
        raise _malformed(status)
    values = [tuple(cast("list[object]", row)) for row in cast("list[object]", rows)]
    return D1RawResult(
        [str(c) for c in cast("list[object]", columns)], values, _meta(entry.get("meta"))
    )


def _body(queries: Sequence[Query]) -> dict[str, Json]:
    def one(query: Query) -> dict[str, Json]:
        sql, params = query
        return {"sql": sql, "params": list(params)}

    if len(queries) == 1:
        return one(queries[0])
    return {"batch": [one(q) for q in queries]}


class D1Api:
    """D1's HTTP API for one database."""

    __slots__ = ("api_token", "database_url", "http_client")

    def __init__(
        self, http_client: HttpClientService[Any], database_url: str, api_token: Redacted[str]
    ) -> None:
        self.http_client = http_client
        self.database_url = database_url
        self.api_token = api_token

    def query(
        self, queries: Sequence[Query]
    ) -> Effect[list[D1Result], D1ApiError | HttpClientError]:
        """Run ``queries`` (one, or a batch in one transaction); rows as
        objects, one result per statement."""
        return self._post("query", queries, _rows)

    def raw(
        self, queries: Sequence[Query]
    ) -> Effect[list[D1RawResult], D1ApiError | HttpClientError]:
        """``query`` with rows as arrays of values."""
        return self._post("raw", queries, _raw_rows)

    def _post[A](
        self,
        endpoint: str,
        queries: Sequence[Query],
        decode: Callable[[int, Mapping[str, Any]], A],
    ) -> Effect[list[A], D1ApiError | HttpClientError]:
        def read(response: HttpClientResponse) -> Effect[list[A], D1ApiError | HttpClientError]:
            def parse(body: Json) -> Effect[list[A], D1ApiError]:
                status = response.status
                try:
                    return succeed([decode(status, entry) for entry in _results(status, body)])
                except D1ApiError as error:
                    return fail(error)

            return response.json.flat_map(parse)

        def build() -> Effect[list[A], D1ApiError | HttpClientError]:
            request = (
                http_request.post(f"{self.database_url}/{endpoint}")
                .bearer_token(self.api_token)
                .accept_json()
                .body_json_unsafe(_body(queries))
            )
            # The statement's own span covers the request.
            sent = self.http_client.execute(request).pipe(
                provide_service(TracerDisabledWhen, _always)
            )
            return sent.flat_map(read)

        return suspend(build)


__all__ = [
    "D1Api",
    "D1ApiError",
    "D1Message",
    "D1Meta",
    "D1RawResult",
    "D1Result",
    "HttpClientError",
    "Param",
    "Query",
    "bind",
]
