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
import re
import uuid
from collections.abc import Callable, Mapping, Sequence
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
from pyfect.logger import log_error, log_warning
from pyfect.redacted import value as redacted_value
from pyfect.sql.clickhouse._rows import RowSplitter, body_error
from pyfect.sql.clickhouse.config import Connection
from pyfect.sql.clickhouse.error import ClickhouseError, parse_error
from pyfect.sql.clickhouse.options import form_encoded_length
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

    __slots__ = ("_parse", "format", "query_id", "response")

    def __init__(
        self,
        response: HttpClientResponse,
        query_id: str,
        format: str | None,
        parse: Callable[[str], object] = _json_text.parse,
    ) -> None:
        self.response = response
        self.query_id = query_id
        self.format = format
        self._parse = parse

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
        JSON fails with the parser's ``ValueError`` (the config's ``json``
        parser reads it)."""
        if self.format in STREAMABLE_JSON_FORMATS:
            return self.stream().map(self._parse).run_collect().map(list)

        def parse(text: str) -> Effect[Any, ValueError]:
            try:
                return succeed(self._parse(text))
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


def _trim(query: str) -> str:
    return query.strip().rstrip(";")


def _columns(columns: InsertColumns | None) -> str:
    if columns is None:
        return ""
    if isinstance(columns, Mapping):
        excluded = columns.get("except", ())
        return f" (* EXCEPT ({', '.join(excluded)}))" if excluded else ""
    return f" ({', '.join(columns)})" if columns else ""


type Operation = Literal["Query", "Insert", "Command", "Exec"]

_SAFE_PART_NAME = re.compile(r"[A-Za-z0-9_.-]+", re.ASCII)
MAX_URL_BIND_PARAM_LENGTH = 4096
"""How long a query's parameters may make the URL under
``use_multipart_params_auto`` before they go in a multipart body."""


def _multipart(parts: Mapping[str, str], boundary: str) -> str:
    """``@clickhouse/client``'s ``buildMultipartBody``."""
    chunks: list[str] = []
    for name, value in parts.items():
        if not _SAFE_PART_NAME.fullmatch(name):
            raise ValueError(
                f'Invalid multipart part name: "{name}". Part names must match /^[A-Za-z0-9_.-]+$/.'
            )
        chunks.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'
        )
    chunks.append(f"--{boundary}--\r\n")
    return "".join(chunks)


def _is_one(value: object) -> bool:
    """JavaScript's ``value === 1``."""
    return not isinstance(value, bool) and isinstance(value, int | float) and value == 1


class ClickhouseDriver:
    """Requests to one server (see the module)."""

    __slots__ = ("connection", "connection_id", "http_client")

    def __init__(
        self, http_client: HttpClientService[HttpClientError], connection: Connection
    ) -> None:
        self.http_client = http_client
        self.connection = connection
        self.connection_id = str(uuid.uuid4())

    def _headers(self, options: RequestOptions) -> dict[str, str]:
        connection = self.connection
        agent = f"pyfect ({_SYSTEM})"
        headers = {
            **connection.http_headers,
            **options.get("http_headers", {}),
            "Connection": "keep-alive" if connection.keep_alive else "close",
            "User-Agent": agent
            if connection.application is None
            else f"{connection.application} {agent}",
        }
        credentials = connection.tls_credentials
        if credentials is None:
            return {**headers, "Authorization": redacted_value(connection.authorization)}
        headers["X-ClickHouse-User"] = credentials[0]
        headers["X-ClickHouse-Key"] = redacted_value(credentials[1])
        if connection.tls is not None and connection.tls.mutual:
            headers["X-ClickHouse-SSL-Certificate-Auth"] = "on"
        return headers

    def _settings(self, options: RequestOptions, *, compressed: bool) -> Settings:
        """The settings of a request: ``enable_http_compression=1`` first
        when a compressed response is configured (``withHttpSettings``)."""
        connection = self.connection
        asked: Settings = (
            {"enable_http_compression": 1}
            if compressed and connection.decompress_response is not None
            else {}
        )
        return {**asked, **connection.clickhouse_settings, **options.get("clickhouse_settings", {})}

    def _url_params(
        self,
        query_id: str,
        options: RequestOptions,
        settings: Settings,
        *,
        query: str | None = None,
        param_entries: list[tuple[str, str]] | None = None,
        params_in_url: bool = True,
    ) -> list[tuple[str, str]]:
        """``@clickhouse/client``'s ``toSearchParams``."""
        connection = self.connection
        if param_entries is not None:
            entries = [*param_entries, ("query_id", query_id)]
        else:
            entries = [("query_id", query_id)]
            if params_in_url:
                entries += self._param_entries(options)
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

    @staticmethod
    def _param_entries(options: RequestOptions) -> list[tuple[str, str]]:
        return [
            (f"param_{key}", format_query_param(value))
            for key, value in options.get("query_params", {}).items()
        ]

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

    def _logged[A](
        self, op: Operation, query_id: str, options: RequestOptions, sent: Effect[A, Any]
    ) -> Effect[A, Any]:
        """``sent``, its failure (or abort) logged as ``@clickhouse/client``
        logs a failed request, at ``ERROR``."""
        if not self.connection.logs("ERROR"):
            return sent
        annotations = {
            "module": "Connection",
            "operation": op,
            "connection_id": self.connection_id,
            "query_id": query_id,
            "session_id": options.get("session_id") or self.connection.session_id,
        }

        def log(error: object) -> Effect[None]:
            return log_error(f"{op}: HTTP request error.", error).annotate_logs(annotations)

        return sent.tap_error(log).on_interrupt(log(Exception("The user aborted a request.")))

    def _compressed(
        self, request: http_request.HttpClientRequest, data: bytes | Stream[bytes, object]
    ) -> http_request.HttpClientRequest:
        """``request`` with ``data`` as its body, compressed as the config
        says (``Content-Encoding``)."""
        from pyfect import stream as stream_module

        codec = self.connection.compress_request
        if codec is None:
            return (
                request.body_bytes(data) if isinstance(data, bytes) else request.body_stream(data)
            )
        request = request.set_header("Content-Encoding", codec.codec)
        if isinstance(data, bytes):
            compressor = codec.compressor()
            return request.body_bytes(compressor.compress(data) + compressor.flush())

        def compressed() -> Stream[bytes, object]:
            compressor = codec.compressor()
            body = data.map(compressor.compress).concat(stream_module.sync(compressor.flush))
            return body.filter(lambda chunk: len(chunk) > 0)

        return request.body_stream(stream_module.suspend(compressed))

    def _accept(
        self, request: http_request.HttpClientRequest, codec: str | None
    ) -> http_request.HttpClientRequest:
        return request if codec is None else request.set_header("Accept-Encoding", codec)

    def _encode_row(self, row: object) -> str:
        stringify = self.connection.json.stringify
        if stringify is not None:
            return stringify(row) + "\n"
        return _json_text.stringify(row, default=_json_default) + "\n"

    def _run_exec(
        self, query: str, query_id: str, options: RequestOptions
    ) -> Effect[HttpClientResponse, ClickhouseRequestError]:
        """``runExec``: the query as the (compressed) body."""

        def build() -> Effect[HttpClientResponse, ClickhouseRequestError]:
            settings = self._settings(options, compressed=True)
            request = http_request.post(
                self.connection.url + "/",
                url_params=self._url_params(query_id, options, settings),
                headers=self._headers(options),
            )
            request = self._accept(request, self.connection.decompress_response)
            if self.connection.compress_request is None:
                request = request.body_text(query, "text/plain; charset=UTF-8")
            else:
                request = self._compressed(request, text_encode(query))
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
            settings = {
                **self.connection.clickhouse_settings,
                **options.get("clickhouse_settings", {}),
            }
            request = http_request.post(
                self.connection.url + "/",
                url_params=self._url_params(query_id, options, settings, query=query),
                headers=self._headers(options),
            )
            data: bytes | Stream[bytes, object]
            match values:
                case bytes():
                    data = values
                case str():
                    data = text_encode(values)
                case Stream():
                    items: Stream[Any, object] = values
                    if format in _JSON_FORMATS:
                        items = items.map(lambda row: text_encode(self._encode_row(row)))
                    data = items
                case Mapping():
                    data = text_encode(self._encode_row(values))
                case _:
                    data = text_encode("".join(self._encode_row(row) for row in values))
            return self._send(self._compressed(request, data))

        return suspend(build)

    @staticmethod
    def _query_id(query_id: str | None) -> str:
        return query_id or str(uuid.uuid4())

    def ping(self) -> Effect[None, ClickhouseRequestError]:
        """``GET /ping``, the body drained; a failure is logged at
        ``WARN``."""

        def build() -> Effect[None, ClickhouseRequestError]:
            request = http_request.get(self.connection.url + "/ping", headers=self._headers({}))
            return self._send(request).flat_map(lambda response: response.bytes_).as_void()

        pinged = suspend(build)
        if not self.connection.logs("WARN"):
            return pinged
        annotations = {
            "module": "Connection",
            "connection_id": self.connection_id,
            "query_id": str(uuid.uuid4()),
        }
        return pinged.tap_error(
            lambda error: log_warning("Ping: HTTP request error.", error).annotate_logs(annotations)
        )

    def query(
        self, query: str, *, format: DataFormat = "JSON", **options: Unpack[RequestOptions]
    ) -> Effect[ResultSet, ClickhouseRequestError]:
        """``query`` with ``FORMAT <format>`` appended; its parameters go in
        a multipart body under ``use_multipart_params`` (or, once long,
        ``use_multipart_params_auto``)."""
        query_id = self._query_id(options.get("query_id"))
        body = f"{_trim(query)} \nFORMAT {format}"
        connection = self.connection

        def build() -> Effect[HttpClientResponse, ClickhouseRequestError]:
            settings = self._settings(options, compressed=True)
            has_params = bool(options.get("query_params"))
            multipart = has_params and connection.use_multipart_params
            entries = None
            if has_params and not multipart and connection.use_multipart_params_auto:
                entries = self._param_entries(options)
                if form_encoded_length(entries) > MAX_URL_BIND_PARAM_LENGTH:
                    multipart, entries = True, None
            request = http_request.post(
                connection.url + "/",
                url_params=self._url_params(
                    query_id, options, settings, param_entries=entries, params_in_url=not multipart
                ),
                headers=self._headers(options),
            )
            asked = settings.get("enable_http_compression")
            request = self._accept(
                request, (connection.decompress_response or "gzip") if _is_one(asked) else None
            )
            if multipart:
                boundary = f"----clickhouse-js-{uuid.uuid4()}"
                parts = {"query": body, **dict(self._param_entries(options))}
                request = request.body_text(
                    _multipart(parts, boundary), f"multipart/form-data; boundary={boundary}"
                )
            else:
                request = request.body_text(body, "text/plain; charset=UTF-8")
            return self._send(request)

        sent = self._logged("Query", query_id, options, suspend(build))
        return sent.map(
            lambda response: ResultSet(response, query_id, format, connection.json.parse)
        )

    def command(
        self, query: str, **options: Unpack[RequestOptions]
    ) -> Effect[CommandResult, ClickhouseRequestError]:
        """``query`` as written; its body is drained."""
        query_id = self._query_id(options.get("query_id"))

        def done(response: HttpClientResponse) -> Effect[CommandResult, HttpClientError]:
            result = CommandResult(query_id, _summary(response.headers), response.headers)
            return response.bytes_.as_(result)

        sent = self._run_exec(_trim(query), query_id, options)
        return self._logged("Command", query_id, options, sent).flat_map(done)

    def exec(
        self, query: str, **options: Unpack[RequestOptions]
    ) -> Effect[ResultSet, ClickhouseRequestError]:
        """``query`` as written (with its own ``FORMAT``); read the body
        through the ``ResultSet``."""
        query_id = self._query_id(options.get("query_id"))
        sent = self._run_exec(_trim(query), query_id, options)
        return self._logged("Exec", query_id, options, sent).map(
            lambda response: ResultSet(response, query_id, None, self.connection.json.parse)
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

        sent = self._with_body(values, format, query_id, options, query).flat_map(done)
        return self._logged("Insert", query_id, options, sent)


__all__ = [
    "MAX_URL_BIND_PARAM_LENGTH",
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
