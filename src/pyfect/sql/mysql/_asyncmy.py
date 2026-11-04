"""The part of asyncmy the driver uses, typed (its stubs leave most of it
unknown)."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from typing import Any, Protocol, cast

import asyncmy
from asyncmy.constants import CLIENT, FIELD_TYPE
from asyncmy.converters import conversions  # pyright: ignore[reportUnknownVariableType]
from asyncmy.cursors import Cursor as _Cursor
from asyncmy.cursors import DictCursor as _DictCursor
from asyncmy.cursors import SSDictCursor as _SSDictCursor

from pyfect import _json_text as json_text

type Description = tuple[tuple[Any, ...], ...]


class Result(Protocol):
    """A prepared statement's result."""

    @property
    def description(self) -> Description | None: ...
    @property
    def rows(self) -> tuple[tuple[Any, ...], ...] | None: ...
    @property
    def affected_rows(self) -> object: ...
    @property
    def insert_id(self) -> int: ...


class PreparedStatement(Protocol):
    async def execute(self, args: tuple[object, ...]) -> Result: ...
    async def close(self) -> None: ...


class Cursor(Protocol):
    @property
    def description(self) -> Description | None: ...
    @property
    def rowcount(self) -> object: ...
    @property
    def lastrowid(self) -> int: ...
    async def execute(self, query: str) -> object: ...
    async def fetchall(self) -> Any: ...
    async def fetchmany(self, size: int) -> Any: ...
    async def nextset(self) -> bool | None: ...
    async def close(self) -> None: ...


class RawConnection(Protocol):
    @property
    def connected(self) -> bool: ...
    def escape(self, obj: object) -> str: ...
    def thread_id(self) -> int: ...
    def cursor(self, cursor: type[Any]) -> Any: ...
    async def prepare(self, query: str) -> PreparedStatement: ...
    async def kill(self, thread_id: int) -> object: ...
    async def ensure_closed(self) -> None: ...
    def close(self) -> None: ...


class _QuietCursor(_Cursor):
    """A text cursor that leaves warnings on the server (asyncmy logs each
    one, after a second round trip)."""

    async def _show_warnings(self, conn: Any) -> None:
        return None


class _QuietDictCursor(_DictCursor):
    async def _show_warnings(self, conn: Any) -> None:
        return None


def text_cursor(conn: RawConnection, *, as_tuples: bool) -> Cursor:
    return cast("Cursor", conn.cursor(_QuietCursor if as_tuples else _QuietDictCursor))


def stream_cursor(conn: RawConnection) -> Cursor:
    """An unbuffered cursor of dict rows."""
    return cast("Cursor", conn.cursor(_SSDictCursor))


def is_server_error(error: BaseException) -> bool:
    """Whether ``error`` is the server's error packet (not one of the
    client's own, errnos 2000 to 2999), which ends the response in step."""
    from asyncmy.errors import MySQLError

    if not isinstance(error, MySQLError) or not error.args:
        return False
    errno = error.args[0]
    return type(errno) is int and not 2000 <= errno < 3000


def end_unbuffered_result(conn: RawConnection) -> None:
    """Mark the unbuffered result an error packet ended as read: asyncmy
    leaves it active, so the next command (or closing its cursor) would
    wait for rows the server never sends."""
    result: Any = getattr(conn, "_result", None)
    if result is not None:
        result.unbuffered_active = False


_CONVERSIONS: dict[Any, Any] = {
    **cast("dict[Any, Any]", conversions),
    FIELD_TYPE.JSON: json_text.parse,
}
"""asyncmy's conversions, and JSON columns parsed (as mysql2 does)."""


def connect_keywords(options: Mapping[str, Any]) -> dict[str, Any]:
    """``asyncmy.connect``'s keywords for ``options``: autocommit on,
    several statements per text query, utf8mb4 and JSON parsed, unless
    ``options`` say otherwise."""
    return {
        "autocommit": True,
        "charset": "utf8mb4",
        "client_flag": CLIENT.MULTI_STATEMENTS,
        "conv": _CONVERSIONS,
        **options,
    }


async def connect(options: Mapping[str, Any]) -> RawConnection:
    connecting = cast(
        "Callable[..., Awaitable[object]]",
        asyncmy.connect,  # pyright: ignore[reportUnknownMemberType]
    )
    return cast("RawConnection", await connecting(**options))


__all__ = [
    "Cursor",
    "Description",
    "PreparedStatement",
    "RawConnection",
    "Result",
    "connect",
    "connect_keywords",
    "end_unbuffered_result",
    "is_server_error",
    "stream_cursor",
    "text_cursor",
]
