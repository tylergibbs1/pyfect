"""The part of asyncmy the driver uses, typed (its stubs leave most of it
unknown)."""

from __future__ import annotations

import codecs
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
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
    @property
    def server_status(self) -> int: ...
    def thread_id(self) -> int: ...
    def cursor(self, cursor: type[Any]) -> Any: ...
    async def prepare(self, query: str) -> PreparedStatement: ...
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


_UNKNOWN_THREAD = 1094


async def kill(conn: RawConnection, thread_id: int, *, only_statement: bool) -> None:
    """Send ``KILL`` (or ``KILL QUERY``) as a statement over ``conn``. asyncmy's own ``kill``
    sends ``COM_PROCESS_KILL``, which MySQL 8.4 answers with "Unknown command". A thread
    already gone is what the kill wanted."""
    from asyncmy.errors import MySQLError

    cursor = text_cursor(conn, as_tuples=True)
    try:
        await cursor.execute(f"KILL {'QUERY ' if only_statement else ''}{thread_id:d}")
    except MySQLError as error:
        if not error.args or error.args[0] != _UNKNOWN_THREAD:
            raise
    finally:
        await cursor.close()


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


def result_settled(conn: RawConnection) -> bool:
    """Whether the server is done with the statement whose unbuffered result
    ``conn`` is reading: every row read, and no further result set to come."""
    result: Any = getattr(conn, "_result", None)
    return result is None or (not result.unbuffered_active and not result.has_next)


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


_REPLACING_UTF8 = "pyfect_mysql_utf8"


def _replacing_utf8(name: str) -> codecs.CodecInfo | None:
    if name != _REPLACING_UTF8:
        return None
    return codecs.CodecInfo(
        name=_REPLACING_UTF8,
        encode=lambda text, errors="strict": codecs.utf_8_encode(text, errors),
        decode=lambda data, errors="strict": codecs.utf_8_decode(data, "replace", True),
    )


codecs.register(_replacing_utf8)


class UnsupportedAsyncmyError(RuntimeError):
    """The installed asyncmy lacks the connection internals the driver relies on."""


class Writes:
    """Whether a connection has written any part of a command since ``begin``. ``adapt``
    puts it in place of the connection's ``_write_bytes``, which asyncmy writes every packet
    through, so it only watches: it never changes what asyncmy keeps or sends."""

    __slots__ = ("_sent", "_write")

    def __init__(self, write: Callable[[bytes], object]) -> None:
        self._write = write
        self._sent = False

    def __call__(self, data: bytes) -> object:
        self._sent = True
        return self._write(data)

    def begin(self) -> None:
        """Nothing of the next command is written yet."""
        self._sent = False

    @property
    def sent(self) -> bool:
        """Whether some of the command begun with ``begin`` was written. A failure before
        that left the connection in step; one after it, unless the server's own error
        packet, did not."""
        return self._sent


@dataclass(frozen=True, slots=True)
class Adapted:
    """A connection set up by ``adapt``, and what it has written."""

    raw: RawConnection
    writes: Writes


def _unsupported(detail: str) -> UnsupportedAsyncmyError:
    from asyncmy.version import __VERSION__

    return UnsupportedAsyncmyError(
        f"asyncmy {__VERSION__} is not supported by pyfect.sql.mysql: its connection {detail}"
    )


def adapt(conn: Any) -> Adapted:
    """``conn`` checked and set up for the driver. Two of asyncmy's internals are used, so an
    asyncmy that renames or changes them fails here, at connect, never later and quietly:

    - ``_encoding``, the codec asyncmy decodes text with, swapped for one that reads bytes
      that are not UTF-8 as U+FFFD, as mysql2 does (Node's ``Buffer.toString``); asyncmy's
      own fails part way through a result (``SELECT ?`` of such bytes on the prepared path);
    - ``_write_bytes``, which asyncmy writes every packet through, watched by ``Writes``
      (``tests/test_mysql_asyncmy_internals.py`` pins both against the installed asyncmy)."""
    encoding: object = getattr(conn, "_encoding", None)
    if not isinstance(encoding, str):
        raise _unsupported(f"has no str _encoding (got {encoding!r})")
    try:
        is_utf8 = codecs.lookup(encoding).name == "utf-8"
    except LookupError as cause:
        raise _unsupported(f"_encoding {encoding!r} is not a codec") from cause
    write: object = getattr(conn, "_write_bytes", None)
    if not callable(write):
        raise _unsupported(f"has no _write_bytes method (got {write!r})")
    writes = Writes(cast("Callable[[bytes], object]", write))
    try:
        conn._write_bytes = writes
    except (AttributeError, TypeError) as cause:
        raise _unsupported("does not let its _write_bytes be watched") from cause
    if getattr(conn, "_write_bytes", None) is not writes:
        raise _unsupported("does not let its _write_bytes be watched")
    if is_utf8:
        conn._encoding = _REPLACING_UTF8
    return Adapted(cast("RawConnection", conn), writes)


async def connect(options: Mapping[str, Any]) -> Adapted:
    """A connection, checked and set up by ``adapt``."""
    connecting = cast(
        "Callable[..., Awaitable[object]]",
        asyncmy.connect,  # pyright: ignore[reportUnknownMemberType]
    )
    return adapt(await connecting(**options))


__all__ = [
    "Adapted",
    "Cursor",
    "Description",
    "PreparedStatement",
    "RawConnection",
    "Result",
    "UnsupportedAsyncmyError",
    "Writes",
    "adapt",
    "connect",
    "connect_keywords",
    "end_unbuffered_result",
    "is_server_error",
    "kill",
    "result_settled",
    "stream_cursor",
    "text_cursor",
]
