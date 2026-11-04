"""The client of ClickHouse's HTTP interface that ``ClickhouseClient`` runs
on (``@clickhouse/client``'s ``ClickHouseClient``), sending its requests
with a pyfect ``HttpClient``.

Every method is an effect: interrupting it aborts its request (the server
may still run the query; ``ClickhouseClient`` kills it). Failures are a
``ClickhouseError`` for what the server answered and an ``HttpClientError``
for a request that got no answer.

- ``query``: a statement with output, ``FORMAT <format>`` appended
  (``JSON`` by default); its ``ResultSet`` reads the body
- ``command``: a statement without output (DDL); the body is drained
- ``exec``: a statement as written (its own ``FORMAT``), its body unread
- ``insert``: rows into a table, encoded for ``format``
- ``ping``: the ``/ping`` endpoint, which checks no credentials
"""

from __future__ import annotations

import platform
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Literal, TypedDict, Unpack, cast

from pyfect import _json_text
from pyfect._core import Effect
from pyfect._js import text_encode
from pyfect.effect import fail, provide_service, succeed, suspend
from pyfect.http import request as http_request
from pyfect.http.client import HttpClientService, TracerDisabledWhen
from pyfect.http.error import HttpClientError
from pyfect.http.headers import Headers
from pyfect.http.response import HttpClientResponse
from pyfect.redacted import value as redacted_value
from pyfect.sql.clickhouse._rows import RowSplitter, body_error
from pyfect.sql.clickhouse.config import Connection
from pyfect.sql.clickhouse.error import ClickhouseError, parse_error
from pyfect.sql.clickhouse.params import Settings, format_query_param, format_setting

if TYPE_CHECKING:
    from pyfect.stream import Stream

type ClickhouseRequestError = ClickhouseError | HttpClientError
"""How a request fails: the server's error, or no answer."""

type DataFormat = str
"""A ClickHouse format name (``JSON``, ``JSONEachRow``, ``CSV``, ...)."""

type InsertValues = Sequence[object] | Mapping[str, object] | bytes | str | Stream[Any, object]
"""What ``insert`` sends: rows (each JSON-encoded on its own line), one
JSON document (``JSON``, ``JSONObjectEachRow``), a body already in
``format`` (``bytes`` / ``str``), or a stream of rows (JSON formats) or of
``bytes`` (any other format)."""

type InsertColumns = Sequence[str] | Mapping[Literal["except"], Sequence[str]]
"""The columns an insert sets: ``["a", "b"]``, or ``{"except": ["id"]}``."""

STREAMABLE_JSON_FORMATS = frozenset(
    {
        "JSONEachRow",
        "JSONStringsEachRow",
        "JSONCompactEachRow",
        "JSONCompactStringsEachRow",
        "JSONCompactEachRowWithNames",
        "JSONCompactEachRowWithNamesAndTypes",
        "JSONCompactStringsEachRowWithNames",
        "JSONCompactStringsEachRowWithNamesAndTypes",
        "JSONEachRowWithProgress",
    }
)
"""Formats with one JSON value per line."""

SINGLE_DOCUMENT_JSON_FORMATS = frozenset(
    {"JSON", "JSONStrings", "JSONCompact", "JSONCompactStrings", "JSONColumnsWithMetadata"}
)
"""Formats whose whole body is one JSON document."""

_JSON_FORMATS = STREAMABLE_JSON_FORMATS | SINGLE_DOCUMENT_JSON_FORMATS | {"JSONObjectEachRow"}
_SYSTEM = f"lv:python/{platform.python_version()}; os:{platform.system().lower()}"


class RequestOptions(TypedDict, total=False):
    """What every request may set; unset ones come from the config.

    ``query_params`` are the values of ``{name: Type}`` placeholders;
    ``clickhouse_settings`` are added to the config's."""

    query_params: Mapping[str, object]
    query_id: str | None
    clickhouse_settings: Settings
    session_id: str | None
    role: str | Sequence[str] | None
    http_headers: Mapping[str, str]


def _summary(headers: Headers) -> Mapping[str, object] | None:
    text = headers.get("x-clickhouse-summary")
    if text is None:
        return None
    try:
        parsed = _json_text.parse(text)
    except ValueError:
        return None
    return cast("Mapping[str, object]", parsed) if isinstance(parsed, dict) else None


@dataclass(frozen=True, slots=True)
class CommandResult:
    """The answer to a ``command``: its query id, the server's
    ``X-ClickHouse-Summary`` and the response headers."""

    query_id: str
    summary: Mapping[str, object] | None = None
    response_headers: Headers = field(default_factory=Headers, compare=False)


@dataclass(frozen=True, slots=True)
class InsertResult:
    """The answer to an ``insert``; ``executed`` is ``False`` for no rows
    (nothing is sent)."""

    executed: bool
    query_id: str
    summary: Mapping[str, object] | None = None
    response_headers: Headers = field(default_factory=Headers, compare=False)


class ResultSet:
    """The answer to a ``query`` or ``exec``, its body not yet read (read it
    once): ``text``, ``json`` or the rows of ``stream``."""

    __slots__ = ("format", "query_id", "response")

    def __init__(self, response: HttpClientResponse, query_id: str, format: str | None) -> None:
        self.response = response
        self.query_id = query_id
        self.format = format

    def __repr__(self) -> str:
        return f"ResultSet(query_id={self.query_id!r}, format={self.format!r})"

    @property
    def response_headers(self) -> Headers:
        return self.response.headers

    @property
    def _tag(self) -> str | None:
        return self.response.headers.get("x-clickhouse-exception-tag")

    def text(self) -> Effect[str, ClickhouseRequestError]:
        """The whole body; the server's error if it ended with one (also
        when the server then cut the body short)."""
        received = bytearray()
        tag = self._tag

        def add(chunk: bytes) -> Effect[None]:
            received.extend(chunk)
            return succeed(None)

        def ended(cut: HttpClientError | None) -> Effect[str, ClickhouseRequestError]:
            error = body_error(bytes(received), tag) or cut
            return succeed(received.decode()) if error is None else fail(error)

        read = self.response.stream.run_for_each(add)
        return read.match_effect(on_failure=ended, on_success=lambda _: ended(None))

    def json(self) -> Effect[Any, ClickhouseRequestError | ValueError]:
        """The body as JSON: the document of a single-document format, the
        list of rows of a format with a value per line. A body that is not
        JSON fails with the parser's ``ValueError``."""
        if self.format in STREAMABLE_JSON_FORMATS:
            return self.stream().map(_json_text.parse).run_collect().map(list)

        def parse(text: str) -> Effect[Any, ValueError]:
            try:
                return succeed(_json_text.parse(text))
            except ValueError as error:
                return fail(error)

        return self.text().flat_map(parse)

    def stream(self) -> Stream[str, ClickhouseRequestError]:
        """The body's rows, a line each, as they arrive; the server's error
        if one ends the body."""
        from pyfect import stream as stream_module

        def rows() -> Stream[str, ClickhouseRequestError]:
            splitter = RowSplitter(self._tag)

            def finish() -> Stream[str, ClickhouseRequestError]:
                try:
                    return stream_module.from_iterable(splitter.finish())
                except ClickhouseError as error:
                    return stream_module.fail(error)

            def cut(error: HttpClientError) -> Stream[str, ClickhouseRequestError]:
                return stream_module.fail(splitter.failure() or error)

            body: Stream[str, ClickhouseRequestError] = (
                self.response.stream.map(splitter.feed).flatten_iterable().catch_all(cut)
            )
            return body.concat(stream_module.suspend(finish))

        return stream_module.suspend(rows)


def _always(_request: object) -> bool:
    return True


def _json_default(value: object) -> object:
    match value:
        case datetime():
            return format_query_param(value)
        case date() | Decimal() | uuid.UUID():
            return str(value)
        case _:
            raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def _encode_row(row: object) -> str:
    return _json_text.stringify(row, default=_json_default) + "\n"


def _trim(query: str) -> str:
    return query.strip().rstrip(";")


def _columns(columns: InsertColumns | None) -> str:
    if columns is None:
        return ""
    if isinstance(columns, Mapping):
        excluded = columns.get("except", ())
        return f" (* EXCEPT ({', '.join(excluded)}))" if excluded else ""
    return f" ({', '.join(columns)})" if columns else ""


class ClickhouseDriver:
    """Requests to one server (see the module)."""

    __slots__ = ("connection", "http_client")

    def __init__(
        self, http_client: HttpClientService[HttpClientError], connection: Connection
    ) -> None:
        self.http_client = http_client
        self.connection = connection

    def _headers(self, options: RequestOptions) -> dict[str, str]:
        connection = self.connection
        agent = f"pyfect ({_SYSTEM})"
        return {
            **connection.http_headers,
            **options.get("http_headers", {}),
            "Connection": "keep-alive",
            "User-Agent": agent
            if connection.application is None
            else f"{connection.application} {agent}",
            "Authorization": redacted_value(connection.authorization),
        }

    def _url_params(
        self, query_id: str, options: RequestOptions, query: str | None
    ) -> list[tuple[str, str]]:
        """``@clickhouse/client``'s ``toSearchParams``."""
        connection = self.connection
        entries = [("query_id", query_id)]
        entries += [
            (f"param_{key}", format_query_param(value))
            for key, value in options.get("query_params", {}).items()
        ]
        settings = {**connection.clickhouse_settings, **options.get("clickhouse_settings", {})}
        entries += [(key, format_setting(value)) for key, value in settings.items()]
        if connection.database != "default":
            entries.append(("database", connection.database))
        if query:
            entries.append(("query", query))
        session_id = options.get("session_id") or connection.session_id
        if session_id:
            entries.append(("session_id", session_id))
        role = options.get("role")
        roles = connection.role if role is None else (role,) if isinstance(role, str) else role
        entries += [("role", r) for r in roles]
        return entries

    def _send(
        self, request: http_request.HttpClientRequest
    ) -> Effect[HttpClientResponse, ClickhouseRequestError]:
        def check(
            response: HttpClientResponse,
        ) -> Effect[HttpClientResponse, ClickhouseRequestError]:
            failed = not 200 <= response.status < 300 or (
                "x-clickhouse-exception-code" in response.headers
            )
            if not failed:
                return succeed(response)
            return response.text.flat_map(lambda text: fail(parse_error(text)))

        # The statement's own span covers the request; its URL holds the
        # parameters, so it gets no span of its own.
        sent = self.http_client.execute(request).pipe(provide_service(TracerDisabledWhen, _always))
        return sent.flat_map(check)

    def _post(
        self, body: str, query_id: str, options: RequestOptions
    ) -> Effect[HttpClientResponse, ClickhouseRequestError]:
        def build() -> Effect[HttpClientResponse, ClickhouseRequestError]:
            request = http_request.post(
                self.connection.url + "/",
                url_params=self._url_params(query_id, options, None),
                headers=self._headers(options),
            ).body_text(body, "text/plain; charset=UTF-8")
            return self._send(request)

        return suspend(build)

    def _with_body(
        self,
        values: InsertValues,
        format: DataFormat,
        query_id: str,
        options: RequestOptions,
        query: str,
    ) -> Effect[HttpClientResponse, ClickhouseRequestError]:
        from pyfect.stream import Stream

        def build() -> Effect[HttpClientResponse, ClickhouseRequestError]:
            request = http_request.post(
                self.connection.url + "/",
                url_params=self._url_params(query_id, options, query),
                headers=self._headers(options),
            )
            match values:
                case bytes():
                    request = request.body_bytes(values)
                case str():
                    request = request.body_text(values)
                case Stream():
                    items: Stream[Any, object] = values
                    if format in _JSON_FORMATS:
                        items = items.map(lambda row: text_encode(_encode_row(row)))
                    request = request.body_stream(items)
                case Mapping():
                    request = request.body_text(_encode_row(values))
                case _:
                    request = request.body_text("".join(_encode_row(row) for row in values))
            return self._send(request)

        return suspend(build)

    @staticmethod
    def _query_id(query_id: str | None) -> str:
        return query_id or str(uuid.uuid4())

    def ping(self) -> Effect[None, ClickhouseRequestError]:
        """``GET /ping``, the body drained."""

        def build() -> Effect[None, ClickhouseRequestError]:
            request = http_request.get(self.connection.url + "/ping", headers=self._headers({}))
            return self._send(request).flat_map(lambda response: response.bytes_).as_void()

        return suspend(build)

    def query(
        self, query: str, *, format: DataFormat = "JSON", **options: Unpack[RequestOptions]
    ) -> Effect[ResultSet, ClickhouseRequestError]:
        """``query`` with ``FORMAT <format>`` appended."""
        query_id = self._query_id(options.get("query_id"))
        body = f"{_trim(query)} \nFORMAT {format}"
        return self._post(body, query_id, options).map(
            lambda response: ResultSet(response, query_id, format)
        )

    def command(
        self, query: str, **options: Unpack[RequestOptions]
    ) -> Effect[CommandResult, ClickhouseRequestError]:
        """``query`` as written; its body is drained."""
        query_id = self._query_id(options.get("query_id"))

        def done(response: HttpClientResponse) -> Effect[CommandResult, HttpClientError]:
            result = CommandResult(query_id, _summary(response.headers), response.headers)
            return response.bytes_.as_(result)

        return self._post(_trim(query), query_id, options).flat_map(done)

    def exec(
        self, query: str, **options: Unpack[RequestOptions]
    ) -> Effect[ResultSet, ClickhouseRequestError]:
        """``query`` as written (with its own ``FORMAT``); read the body
        through the ``ResultSet``."""
        query_id = self._query_id(options.get("query_id"))
        return self._post(_trim(query), query_id, options).map(
            lambda response: ResultSet(response, query_id, None)
        )

    def insert(
        self,
        *,
        table: str,
        values: InsertValues,
        format: DataFormat = "JSONCompactEachRow",
        columns: InsertColumns | None = None,
        **options: Unpack[RequestOptions],
    ) -> Effect[InsertResult, ClickhouseRequestError]:
        """``INSERT INTO <table> [(columns)] FORMAT <format>`` with
        ``values`` as its data. An empty list of rows sends nothing."""
        if isinstance(values, Sequence) and not isinstance(values, str | bytes) and not values:
            return succeed(InsertResult(False, ""))
        query_id = self._query_id(options.get("query_id"))
        query = f"INSERT INTO {table.strip()}{_columns(columns)} FORMAT {format}"

        def done(response: HttpClientResponse) -> Effect[InsertResult, HttpClientError]:
            result = InsertResult(True, query_id, _summary(response.headers), response.headers)
            return response.bytes_.as_(result)

        return self._with_body(values, format, query_id, options, query).flat_map(done)


__all__ = [
    "SINGLE_DOCUMENT_JSON_FORMATS",
    "STREAMABLE_JSON_FORMATS",
    "ClickhouseDriver",
    "ClickhouseRequestError",
    "CommandResult",
    "DataFormat",
    "InsertColumns",
    "InsertResult",
    "InsertValues",
    "RequestOptions",
    "ResultSet",
]
