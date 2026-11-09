"""The ``Connection`` of a MySQL session (the ``ConnectionImpl`` of Effect's
``MysqlClient``): its statements run on the SQL loop thread, so no fiber
blocks, and interrupting one ends it on the server with ``KILL QUERY`` (the
session goes on; see ``Session.stop``).

``execute`` and its kin run prepared unless the client disables prepared
statements; the ``unprepared`` ones and streams always go as text.
Results are as mysql2 gives them: a statement's rows, a
``ResultSetHeader`` for one without rows (``execute_raw``), or a list with
each statement's result when the text held several.
"""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from collections.abc import Callable, Coroutine, Sequence
from typing import TYPE_CHECKING, Any, Never, cast

from pyfect._core import Effect
from pyfect._primitives import uninterruptible_mask
from pyfect.effect import fail, succeed
from pyfect.errors import Done
from pyfect.scope import Scope, add_finalizer
from pyfect.sql._loop import call
from pyfect.sql.connection import Row, TransformRows, ValueRow
from pyfect.sql.error import SqlError
from pyfect.sql.mysql._asyncmy import Cursor
from pyfect.sql.mysql._session import ResultSet, ResultSetHeader, Session
from pyfect.sql.mysql.error import catch

if TYPE_CHECKING:
    from pyfect.stream import Stream

_EXECUTE = catch("Failed to execute statement", "execute")
_EXECUTE_UNPREPARED = catch("Failed to execute statement", "executeUnprepared")
_STREAM = catch("Failed to stream statement", "stream")


def _raw(results: list[ResultSet]) -> object:
    return results[0] if len(results) == 1 else results


def _rows(results: list[ResultSet]) -> list[Any]:
    """mysql2's ``Array.isArray(results) ? results : []``."""
    if len(results) > 1:
        return results
    first = results[0]
    return [] if isinstance(first, ResultSetHeader) else first


def _transform(transform_rows: TransformRows | None, results: list[ResultSet]) -> list[Any]:
    rows = _rows(results)
    if transform_rows is None:
        return rows
    if len(results) == 1:
        return list(transform_rows(cast("list[Row]", rows)))
    return [
        r if isinstance(r, ResultSetHeader) else list(transform_rows(cast("list[Row]", r)))
        for r in results
    ]


class MysqlConnection:
    """A ``Connection`` on one session."""

    __slots__ = ("_prepare", "session")

    def __init__(self, session: Session, *, prepare: bool) -> None:
        self.session = session
        self._prepare = prepare

    def _call[A](
        self,
        run: Callable[[], Coroutine[Any, Any, A]],
        on_error: Callable[[BaseException], SqlError],
    ) -> Effect[A, SqlError]:
        return call(run, on_error, self.session.stop, waits_for="work")

    def _run(
        self, sql: str, params: Sequence[object], *, prepared: bool, as_tuples: bool
    ) -> Effect[list[ResultSet], SqlError]:
        session = self.session
        values = tuple(params)
        return self._call(
            lambda: session.run(sql, values, prepared=prepared, as_tuples=as_tuples),
            _EXECUTE if prepared else _EXECUTE_UNPREPARED,
        )

    def execute(
        self, sql: str, params: Sequence[object], transform_rows: TransformRows | None, /
    ) -> Effect[Sequence[Row], SqlError]:
        run = self._run(sql, params, prepared=self._prepare, as_tuples=False)
        return run.map(lambda results: _transform(transform_rows, results))

    def execute_unprepared(
        self, sql: str, params: Sequence[object], transform_rows: TransformRows | None, /
    ) -> Effect[Sequence[Row], SqlError]:
        run = self._run(sql, params, prepared=False, as_tuples=False)
        return run.map(lambda results: _transform(transform_rows, results))

    def execute_raw(self, sql: str, params: Sequence[object], /) -> Effect[object, SqlError]:
        """The statement's rows or ``ResultSetHeader`` (a list of them for
        several statements)."""
        return self._run(sql, params, prepared=self._prepare, as_tuples=False).map(_raw)

    def execute_values(
        self, sql: str, params: Sequence[object], /
    ) -> Effect[Sequence[ValueRow], SqlError]:
        return self._run(sql, params, prepared=self._prepare, as_tuples=True).map(_rows)

    def execute_values_unprepared(
        self, sql: str, params: Sequence[object], /
    ) -> Effect[Sequence[ValueRow], SqlError]:
        return self._run(sql, params, prepared=False, as_tuples=True).map(_rows)

    def execute_stream(
        self, sql: str, params: Sequence[object], transform_rows: TransformRows | None, /
    ) -> Stream[Row, SqlError]:
        from pyfect import stream as stream_module

        rows = stream_module.unwrap(self._open_stream(sql, tuple(params)))
        if transform_rows is None:
            return rows
        transform = transform_rows
        return rows.map_array(lambda chunk: tuple(transform(chunk)))

    def _open_stream(
        self, sql: str, params: tuple[object, ...]
    ) -> Effect[Stream[Row, SqlError], SqlError, Scope]:
        from pyfect import stream as stream_module

        session = self.session

        def build(cursor: Cursor) -> Effect[Stream[Row, SqlError], Never, Scope]:
            def chunk(found: list[dict[str, Any]]) -> Effect[tuple[Row, ...], SqlError | Done]:
                return succeed(tuple(found)) if found else fail(Done())

            pull = self._call(lambda: session.next_rows(cursor), _STREAM).flat_map(chunk)
            stream: Stream[Row, SqlError] = stream_module.from_pull(succeed(pull))
            close = call(lambda: session.close_stream(cursor), _STREAM, waits_for="work")
            return add_finalizer(lambda _: close.ignore()).as_(stream)

        opened = call(
            lambda: session.open_stream(sql, params),
            _STREAM,
            session.stop,
            release=session.close_stream,
            waits_for="work",
        )
        return uninterruptible_mask(lambda restore: restore(opened).flat_map(build))


def wrap(prepare: bool) -> Callable[[Session], MysqlConnection]:
    return lambda session: MysqlConnection(session, prepare=prepare)


__all__ = ["MysqlConnection", "ResultSetHeader", "wrap"]
