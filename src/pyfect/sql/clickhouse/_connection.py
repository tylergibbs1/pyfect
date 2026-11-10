"""The ``Connection`` of a ClickHouse client (the ``ConnectionImpl`` of
Effect's ``ClickhouseClient``): each statement is one HTTP request, as a
``query`` (``FORMAT JSON``) or, under ``ClientMethod`` ``"command"``, a
``command``, with the fiber's ``QueryId`` (a random UUID by default) and
``ClickhouseSettings``. Parameters are named ``p1``, ``p2``, ...

Interrupting a statement aborts its request and kills the query on the
server (``KILL QUERY``, its id a parameter); a stream does so unless it was
read to the end.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING, Any, Literal, cast

from pyfect._core import Effect
from pyfect._fiber import Fiber
from pyfect.context import Reference
from pyfect.effect import fail, succeed, suspend, sync, with_fiber
from pyfect.sql.clickhouse.driver import ClickhouseDriver, CommandResult, ResultSet
from pyfect.sql.clickhouse.error import catch
from pyfect.sql.clickhouse.params import Settings
from pyfect.sql.connection import Row, TransformRows, ValueRow
from pyfect.sql.error import SqlError

if TYPE_CHECKING:
    from pyfect.stream import Stream

type ClientMethodName = Literal["query", "command", "insert"]


class ClientMethod(
    Reference[ClientMethodName], key="@effect/sql-clickhouse/ClickhouseClient/ClientMethod"
):
    """How statements run: as a ``query`` (the default) or a ``command``
    (``ClickhouseClientService.as_command``)."""

    @classmethod
    def default(cls) -> ClientMethodName:
        return "query"


class QueryId(Reference[str | None], key="@effect/sql-clickhouse/ClickhouseClient/QueryId"):
    """The ``query_id`` of statements and inserts; a random UUID each when
    unset (``ClickhouseClientService.with_query_id``)."""

    @classmethod
    def default(cls) -> str | None:
        return None


class ClickhouseSettings(
    Reference[Settings], key="@effect/sql-clickhouse/ClickhouseClient/ClickhouseSettings"
):
    """Settings sent with statements, commands and inserts
    (``ClickhouseClientService.with_clickhouse_settings``)."""

    @classmethod
    def default(cls) -> Settings:
        return {}


_EXECUTE = catch("Failed to execute statement", "execute")
_PARSE_RESULT = catch("Failed to parse result", "parseResult")
_STREAM = catch("Failed to execute stream", "stream")
_PARSE_ROW = catch("Failed to parse row", "parseRow")
_KILL = "KILL QUERY WHERE query_id = {queryId:String}"


def kill_query(driver: ClickhouseDriver, query_id: str) -> Effect[None]:
    """Stop the query ``query_id`` on the server; a failure is a defect, as
    Effect's ``Effect.promise``."""
    return driver.command(_KILL, query_params={"queryId": query_id}).as_void().or_die()


def query_id_of(fiber: Fiber[Any, Any]) -> str:
    return fiber.get_ref(QueryId) or str(uuid.uuid4())


def _params(params: Sequence[object]) -> dict[str, object]:
    return {f"p{i}": value for i, value in enumerate(params, 1)}


def _data(result: object) -> Any:
    """A JSON document's ``data``, or the result itself (rows of a format
    with a value per line)."""
    if not isinstance(result, dict):
        return result
    document = cast("dict[str, object]", result)
    return document.get("data", document)


def _document(text: str, parse: Callable[[str], object]) -> Effect[Any, SqlError]:
    """The rows of a ``JSON`` / ``JSONCompact`` body. A statement without
    output (DDL, ``INSERT ... SELECT``) answers with no body: no rows."""
    if not text.strip():
        return succeed([])
    try:
        return succeed(_data(parse(text)))
    except ValueError as error:
        return fail(_PARSE_RESULT(error))


class ClickhouseConnection:
    """A ``Connection`` on a ``ClickhouseDriver``."""

    __slots__ = ("driver",)

    def __init__(self, driver: ClickhouseDriver) -> None:
        self.driver = driver

    def _request(
        self, fiber: Fiber[Any, Any], query_id: str, sql: str, params: Sequence[object], format: str
    ) -> Effect[ResultSet | CommandResult, SqlError]:
        settings = fiber.get_ref(ClickhouseSettings)
        values = _params(params)
        if fiber.get_ref(ClientMethod) == "command":
            sent: Effect[ResultSet | CommandResult, Any] = self.driver.command(
                sql, query_params=values, query_id=query_id, clickhouse_settings=settings
            )
        else:
            sent = self.driver.query(
                sql,
                format=format,
                query_params=values,
                query_id=query_id,
                clickhouse_settings=settings,
            )
        return sent.map_error(_EXECUTE)

    def _killed[A](
        self, run: Callable[[Fiber[Any, Any], str], Effect[A, SqlError]]
    ) -> Effect[A, SqlError]:
        """``run`` with the fiber's query id; interrupting it kills the
        query."""

        def body(fiber: Fiber[Any, Any]) -> Effect[A, SqlError]:
            query_id = query_id_of(fiber)
            return run(fiber, query_id).on_interrupt(kill_query(self.driver, query_id))

        return with_fiber(body)

    def _rows(self, sql: str, params: Sequence[object], format: str) -> Effect[Any, SqlError]:
        def read(result: ResultSet | CommandResult) -> Effect[Any, SqlError]:
            if isinstance(result, CommandResult):
                return succeed([])
            parse = self.driver.connection.json.parse
            return (
                result.text().map_error(_PARSE_RESULT).flat_map(lambda text: _document(text, parse))
            )

        return self._killed(
            lambda fiber, query_id: self._request(fiber, query_id, sql, params, format).flat_map(
                read
            )
        )

    def execute(
        self, sql: str, params: Sequence[object], transform_rows: TransformRows | None, /
    ) -> Effect[Sequence[Row], SqlError]:
        rows: Effect[Sequence[Row], SqlError] = self._rows(sql, params, "JSON")
        return rows if transform_rows is None else rows.map(transform_rows)

    def execute_unprepared(
        self, sql: str, params: Sequence[object], transform_rows: TransformRows | None, /
    ) -> Effect[Sequence[Row], SqlError]:
        return self.execute(sql, params, transform_rows)

    def execute_raw(self, sql: str, params: Sequence[object], /) -> Effect[object, SqlError]:
        """The ``ResultSet`` of a query, its body unread, or the
        ``CommandResult`` of a command."""
        return self._killed(
            lambda fiber, query_id: self._request(fiber, query_id, sql, params, "JSON")
        )

    def execute_values(
        self, sql: str, params: Sequence[object], /
    ) -> Effect[Sequence[ValueRow], SqlError]:
        rows: Effect[list[list[object]], SqlError] = self._rows(sql, params, "JSONCompact")
        return rows.map(lambda found: [tuple(row) for row in found])

    def execute_values_unprepared(
        self, sql: str, params: Sequence[object], /
    ) -> Effect[Sequence[ValueRow], SqlError]:
        return self.execute_values(sql, params)

    def execute_stream(
        self, sql: str, params: Sequence[object], transform_rows: TransformRows | None, /
    ) -> Stream[Row, SqlError]:
        from pyfect import stream as stream_module

        driver = self.driver
        parse_row = driver.connection.json.parse

        def opened(fiber: Fiber[Any, Any]) -> Effect[Stream[str, SqlError], SqlError]:
            query_id = query_id_of(fiber)

            def rows(result: ResultSet | CommandResult) -> Stream[str, SqlError]:
                if isinstance(result, CommandResult):
                    return stream_module.empty
                # Closing the response does not stop a query the server is
                # still computing, so kill it unless the body was read to
                # the end.
                ended = [False]

                def end() -> None:
                    ended[0] = True

                def stop() -> Effect[None]:
                    return (
                        succeed(None) if ended[0] else kill_query(driver, query_id).ignore_cause()
                    )

                return result.stream().map_error(_STREAM).on_end(sync(end)).ensuring(suspend(stop))

            sent = self._request(fiber, query_id, sql, params, "JSONEachRow")
            return sent.map(rows).on_interrupt(kill_query(driver, query_id))

        def parse(chunk: tuple[str, ...]) -> Effect[tuple[Row, ...], SqlError]:
            try:
                found = [cast("Row", parse_row(text)) for text in chunk]
            except ValueError as error:
                return fail(_PARSE_ROW(error))
            return succeed(tuple(found if transform_rows is None else transform_rows(found)))

        lines: Stream[str, SqlError] = stream_module.unwrap(with_fiber(opened))
        return lines.map_array_effect(parse)


__all__ = [
    "ClickhouseConnection",
    "ClickhouseSettings",
    "ClientMethod",
    "ClientMethodName",
    "QueryId",
    "kill_query",
    "query_id_of",
]
