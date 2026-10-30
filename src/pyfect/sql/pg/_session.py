"""A psycopg ``AsyncConnection`` and what runs on it. Every coroutine here
runs on the psycopg loop (``_loop``); fibers reach them through
``_loop.call``.

Statements are sent with the extended query protocol, so a text holding
several statements fails as PostgreSQL's prepared statements do, and use
PostgreSQL's own ``$1`` placeholders (psycopg's raw cursors).

While anyone listens, a pump task reads notifications with
``notifies()``; a statement stops the pump first (psycopg keeps the
notifications that arrive meanwhile) and starts it again when done.
"""
# pyright: reportPrivateUsage=false

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, LiteralString, cast

import psycopg
from psycopg import AsyncRawCursor, pq
from psycopg.rows import dict_row, tuple_row

from pyfect._digits import parse_digits
from pyfect._subscriber_queue import FellBehind

if TYPE_CHECKING:
    from psycopg.adapt import AdaptersMap

_CANCEL_TIMEOUT = 5.0
_DRAIN_TIMEOUT = 5.0
_QUERY_CANCELED = "57014"
_STREAM_CHUNK = 128
_ACTIVE = pq.TransactionStatus.ACTIVE


def _text(sql: str) -> LiteralString:
    """psycopg types query text as ``LiteralString``; the text here was
    compiled from the client's templates (or ``unsafe``, which says so)."""
    return cast("LiteralString", sql)


class _ExtendedCursor(AsyncRawCursor[Any]):
    """A raw cursor that always uses the extended query protocol, as
    PostgreSQL's prepared statements do (psycopg sends a statement without
    parameters as a simple query, which runs several statements)."""

    def _execute_send(
        self, query: Any, *, force_extended: bool = False, binary: bool | None = None
    ) -> None:
        super()._execute_send(query, force_extended=True, binary=binary)


@dataclass(frozen=True, slots=True)
class Field:
    """A result column: its name and type OID."""

    name: str
    data_type_id: int


@dataclass(frozen=True, slots=True)
class Result:
    """What a statement gave: its command tag (``command``, ``row_count``,
    ``oid`` for ``INSERT``), its rows by column name, and its columns."""

    command: str
    row_count: int
    oid: int | None
    rows: list[dict[str, Any]]
    fields: tuple[Field, ...]


@dataclass(frozen=True, slots=True)
class Notification:
    """A ``NOTIFY`` received on ``channel``, sent by the session
    ``process_id``."""

    process_id: int
    channel: str
    payload: str


def parse_command_tag(tag: str) -> tuple[str, int, int | None]:
    """``(command, row_count, oid)`` from a command tag such as
    ``"INSERT 0 1"``."""
    command, space, rest = tag.partition(" ")
    if not space:
        return tag, 0, None
    first, second_space, last = rest.partition(" ")
    if command == "INSERT" and second_space:
        return command, int(last), int(first)
    count = last if second_space else first
    return command, parse_digits(count) or 0, None


class Session:
    """One PostgreSQL session."""

    __slots__ = (
        "_busy",
        "_cancel_pending",
        "_failure",
        "_fatal",
        "_pump",
        "_retire",
        "_subscribers",
        "conn",
        "prepare",
        "process_id",
    )

    def __init__(self, conn: psycopg.AsyncConnection[Any], prepare: bool) -> None:
        self.conn = conn
        self.prepare = prepare
        self.process_id: int = conn.info.backend_pid
        """The backend's process id, fixed at connect."""
        self._retire = False
        self._cancel_pending = False
        self._busy = 0
        self._failure: BaseException | None = None
        self._pump: asyncio.Task[None] | None = None
        self._subscribers: dict[str, set[Mailbox]] = {}
        self._fatal: tuple[str, str] | None = None
        conn.add_notice_handler(self._on_notice)

    @staticmethod
    async def connect(
        params: dict[str, str], password: str | None, types: AdaptersMap | None, cache: int
    ) -> Session:
        kwargs: dict[str, Any] = dict(params)
        if password is not None:
            kwargs["password"] = password
        conn = await psycopg.AsyncConnection.connect(
            autocommit=True,
            prepare_threshold=None if cache == 0 else 5,
            context=types,
            cursor_factory=_ExtendedCursor,
            **kwargs,
        )
        if cache > 0:
            conn.prepared_max = cache
        return Session(conn, cache > 0)

    def _on_notice(self, diagnostic: psycopg.errors.Diagnostic) -> None:
        # libpq reports an ErrorResponse that arrives between statements
        # (a FATAL before the server hangs up) as a notice. The diagnostic
        # is only readable during the call.
        sqlstate = diagnostic.sqlstate
        if diagnostic.severity_nonlocalized in ("FATAL", "PANIC") and sqlstate is not None:
            self._fatal = self._fatal or (sqlstate, diagnostic.message_primary or "")

    def explain(self, error: BaseException) -> BaseException:
        """``error``, or for a lost connection the server's FATAL error
        that came before it."""
        fatal = self._fatal
        if (
            fatal is None
            or not isinstance(error, psycopg.OperationalError)
            or error.sqlstate is not None
        ):
            return error
        sqlstate, message = fatal
        explained = psycopg.errors.lookup(sqlstate)(message)
        explained.__cause__ = error
        return explained

    @property
    def retire(self) -> bool:
        """Whether a pool should replace the session: a cancel was not
        confirmed, so a late one could hit its next statement."""
        return self._retire or self._cancel_pending

    @property
    def closed(self) -> bool:
        return self.conn.closed

    # --- statements -----------------------------------------------------------

    async def _exclusive[A](self, run: Callable[[], Awaitable[A]]) -> A:
        """Run a statement with the pump stopped."""
        self._busy += 1
        self._failure = None
        try:
            await self._stop_pump()
            return await run()
        except BaseException as failure:
            explained = self.explain(failure)
            self._failure = explained
            if isinstance(explained, psycopg.Error) and explained.sqlstate == _QUERY_CANCELED:
                self._cancel_pending = False
            if explained is failure:
                raise
            raise explained from failure
        finally:
            self._busy -= 1
            self._start_pump()

    async def query(self, sql: str, params: Sequence[object], prepare: bool) -> Result:
        async def run() -> Result:
            async with self.conn.cursor(row_factory=dict_row) as cursor:
                await cursor.execute(_text(sql), params, prepare=prepare and self.prepare)
                rows = await cursor.fetchall() if cursor.description is not None else []
                command, count, oid = parse_command_tag(cursor.statusmessage or "")
                fields = tuple(Field(c.name, c.type_code) for c in cursor.description or ())
                return Result(command, count, oid, rows, fields)

        return await self._exclusive(run)

    async def query_values(
        self, sql: str, params: Sequence[object], prepare: bool
    ) -> list[tuple[Any, ...]]:
        async def run() -> list[tuple[Any, ...]]:
            async with self.conn.cursor(row_factory=tuple_row) as cursor:
                await cursor.execute(_text(sql), params, prepare=prepare and self.prepare)
                return await cursor.fetchall() if cursor.description is not None else []

        return await self._exclusive(run)

    async def cancel_query(self, task: asyncio.Task[Any]) -> None:
        """Stop a running statement: send PostgreSQL a cancel request and
        wait for the statement to end. Unless it ends with PostgreSQL's
        ``57014``, the cancel was not confirmed and ``retire`` is set; a
        statement still running after the drain timeout closes the
        session."""
        if self.conn.pgconn.transaction_status != _ACTIVE:
            await _cancel(task)
            return
        with contextlib.suppress(Exception):
            await self.conn.cancel_safe(timeout=_CANCEL_TIMEOUT)
        done, _ = await asyncio.wait([task], timeout=_DRAIN_TIMEOUT)
        if not done:
            self._retire = True
            await self.close()
            await _cancel(task)
            return
        error = self._failure
        if not (isinstance(error, psycopg.Error) and error.sqlstate == _QUERY_CANCELED):
            self._retire = True

    async def interrupt(self) -> None:
        """Ask PostgreSQL to cancel whatever runs now. Until a statement
        ends cancelled, the cancel may still hit the next one."""
        self._cancel_pending = True
        with contextlib.suppress(Exception):
            await self.conn.cancel_safe(timeout=_CANCEL_TIMEOUT)

    # --- streams --------------------------------------------------------------

    async def open_stream(self, sql: str, params: Sequence[object]) -> AsyncIterator[Any]:
        await self._stop_pump()
        self._busy += 1
        cursor = self.conn.cursor(row_factory=dict_row)
        size = _STREAM_CHUNK if pq.version() >= 170000 else 1
        return cursor.stream(_text(sql), params, size=size)

    async def next_rows(self, rows: AsyncIterator[Any]) -> list[dict[str, Any]]:
        """Up to a chunk of rows; ``[]`` at the end."""
        chunk: list[dict[str, Any]] = []
        async for row in rows:
            chunk.append(row)
            if len(chunk) >= _STREAM_CHUNK:
                break
        return chunk

    async def close_stream(self, rows: AsyncIterator[Any]) -> None:
        """End a stream: psycopg cancels a statement still running and
        drains it, without saying whether PostgreSQL confirmed the cancel,
        so the session is retired."""
        try:
            if self.conn.pgconn.transaction_status == _ACTIVE:
                self._retire = True
            aclose = getattr(rows, "aclose", None)
            if aclose is not None:
                with contextlib.suppress(Exception):
                    await aclose()
        finally:
            self._busy -= 1
            self._start_pump()

    # --- notifications --------------------------------------------------------

    def subscribe(self, channel: str, capacity: int) -> Mailbox:
        """A mailbox of ``channel``'s notifications (and of the error that
        ended the session), holding at most ``capacity``. The caller sends
        ``LISTEN`` first."""
        mailbox = Mailbox(capacity)
        self._subscribers.setdefault(channel, set()).add(mailbox)
        self._start_pump()
        return mailbox

    def unsubscribe(self, channel: str, mailbox: Mailbox) -> bool:
        """Remove a subscriber; ``True`` when it was the channel's last."""
        subscribers = self._subscribers.get(channel)
        if subscribers is None:
            return False
        subscribers.discard(mailbox)
        if subscribers:
            return False
        del self._subscribers[channel]
        return True

    def _start_pump(self) -> None:
        if self._pump is None and self._busy == 0 and self._subscribers and not self.closed:
            self._pump = asyncio.get_running_loop().create_task(self._run_pump())

    async def _stop_pump(self) -> None:
        pump, self._pump = self._pump, None
        if pump is not None:
            await _cancel(pump)

    async def _run_pump(self) -> None:
        try:
            async for notify in self.conn.notifies():
                note = Notification(notify.pid, notify.channel, notify.payload)
                for mailbox in self._subscribers.get(notify.channel, ()):
                    mailbox.deliver(note)
        except psycopg.Error as error:
            self.fail_subscribers(self.explain(error))

    def fail_subscribers(self, error: BaseException) -> None:
        for subscribers in self._subscribers.values():
            for mailbox in subscribers:
                mailbox.items.put_nowait(error)

    async def close(self) -> None:
        await self._stop_pump()
        await self.conn.close()


async def _cancel(task: asyncio.Task[Any]) -> None:
    task.cancel()
    await asyncio.wait([task])


class Mailbox:
    """One listener's notifications on their way from the session's loop
    to its queue. Past ``capacity`` waiting it takes no more and holds a
    ``FellBehind`` instead, so a publisher outpacing the listener cannot
    grow it without limit."""

    __slots__ = ("behind", "capacity", "items")

    def __init__(self, capacity: int) -> None:
        self.capacity = capacity
        self.behind = False
        self.items: asyncio.Queue[Notification | BaseException] = asyncio.Queue()

    def deliver(self, note: Notification) -> None:
        if self.behind:
            return
        if self.items.qsize() >= self.capacity:
            self.behind = True
            self.items.put_nowait(FellBehind("PgConnection.listen", self.capacity))
            return
        self.items.put_nowait(note)


async def next_notification(mailbox: Mailbox) -> list[Notification | BaseException]:
    """The notifications waiting in ``mailbox``, at least one."""
    items = mailbox.items
    first = await items.get()
    batch = [first]
    while not items.empty():
        batch.append(items.get_nowait())
    return batch


__all__ = [
    "Field",
    "Mailbox",
    "Notification",
    "Result",
    "Session",
    "next_notification",
    "parse_command_tag",
]
