"""Statements and the constructor that builds them (Effect's
``Statement.Statement`` / ``Statement.make``).

A ``Statement`` is a fragment that runs: yielding it executes it on a
connection from the client's acquirer (or borrower) inside a client span
named after the database (``db.namespace``, ``server.address[:port]``,
``db.system.name``, else ``sql.execute``) with the client's span
attributes, ``effect.sql.method`` and ``db.query.text``.
"""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import TYPE_CHECKING, Any, LiteralString, Never, cast, overload

from pyfect._core import Effect, _Succeed, _Suspend, _WithFiber
from pyfect.clock import Clock, ClockService
from pyfect.context import Reference
from pyfect.scope import Scope, scoped
from pyfect.sql.connection import Acquirer, Borrower, Connection, Row, TransformRows, ValueRow
from pyfect.sql.error import SqlError
from pyfect.sql.statement._compiler import Compiled, Compiler, Dialect
from pyfect.sql.statement._segments import (
    ArrayHelper,
    Fragment,
    Identifier,
    RecordInsertHelper,
    RecordUpdateHelper,
    RecordUpdateHelperSingle,
    Segment,
    SqlText,
    and_,
    csv,
    identifier,
    in_,
    insert,
    join,
    literal,
    or_,
    segments_of,
    unsafe_literal,
    update,
    update_values,
)
from pyfect.tracer._model import Span
from pyfect.tracer._refs import ParentSpan, TracerEnabled, TracerTimingEnabled
from pyfect.tracer._spans import in_parent_span, make_span_scoped, use_span

if TYPE_CHECKING:
    from pyfect._fiber import Fiber
    from pyfect.stream import Stream

type SpanAttributes = Sequence[tuple[str, object]]

type Transformer = Callable[
    [Statement[Any], Constructor, Fiber[Any, Any], Span], Effect[Statement[Any]]
]
"""Rewrites or wraps a statement before it runs, given the constructor of
its client, the running fiber and the statement's span."""


class CurrentTransformer(Reference[Transformer | None], key="effect/sql/CurrentTransformer"):
    """The transformer applied to every statement before it runs (none by
    default)."""

    @classmethod
    def default(cls) -> Transformer | None:
        return None


class SpanPropagationEnabled(Reference[bool], key="effect/sql/SpanPropagationEnabled"):
    """``True``: a statement's span is the parent of the driver's spans
    (acquisition, execution, stream pulls), and the span records how long
    the statement waited for a connection as
    ``db.client.connection.wait_time_ms``. Ignored when tracing is off."""

    @classmethod
    def default(cls) -> bool:
        return False


_ATTR_DB_QUERY_TEXT = "db.query.text"
_ATTR_DB_CLIENT_CONNECTION_WAIT_TIME = "db.client.connection.wait_time_ms"
_ATTR_SQL_METHOD = "effect.sql.method"


def _span_attribute(attributes: SpanAttributes, key: str) -> object:
    # The last value wins, as when the attributes are set on a span in order.
    for name, value in reversed(attributes):
        if name == key:
            return value
    return None


def _non_empty_string(u: object) -> str | None:
    return u if isinstance(u, str) and u else None


def span_target(attributes: SpanAttributes) -> str | None:
    """The OpenTelemetry target of a client's spans: ``db.namespace``, else
    ``server.address[:server.port]``, else ``None``."""
    namespace = _non_empty_string(_span_attribute(attributes, "db.namespace"))
    if namespace is not None:
        return namespace
    address = _non_empty_string(_span_attribute(attributes, "server.address"))
    if address is not None:
        port = _span_attribute(attributes, "server.port")
        return address if port is None else f"{address}:{port}"
    return None


def span_name(attributes: SpanAttributes) -> str:
    """The name of a client's statement spans: its ``span_target``, else
    ``db.system.name``, else ``sql.execute``."""
    target = span_target(attributes)
    if target is not None:
        return target
    return _non_empty_string(_span_attribute(attributes, "db.system.name")) or "sql.execute"


def _wait_clock(fiber: Fiber[Any, Any]) -> ClockService | None:
    # Without span timing, the span has no start time to measure from.
    return fiber.get_ref(Clock) if fiber.get_ref(TracerTimingEnabled) else None


def _record_connection_wait(span: Span, clock: ClockService) -> None:
    # Measured from the span's start to the connection hand-off, so it also
    # covers compiling the statement and running a ``CurrentTransformer``.
    span.attribute(
        _ATTR_DB_CLIENT_CONNECTION_WAIT_TIME,
        (clock.unsafe_now_nanos() - span.status.start_time) / 1e6,
    )


type _Run[X] = Callable[[Connection, str, Sequence[object]], Effect[X, SqlError]]


class Statement[A = Row](Fragment, Effect[list[A], SqlError, Never]):
    """A statement: a fragment that runs when yielded, succeeding with its
    rows (renamed by the client's result transform). The other ways to run
    it are ``raw``, ``without_transform``, ``stream``, ``values``,
    ``values_unprepared`` and ``unprepared``; ``compile()`` gives the SQL
    and parameters without running it."""

    __slots__ = ("acquirer", "borrower", "compiler", "span_attributes", "transform_rows")

    acquirer: Acquirer
    compiler: Compiler
    span_attributes: tuple[tuple[str, object], ...]
    transform_rows: TransformRows | None
    borrower: Borrower | None

    def __init__(
        self,
        segments: Sequence[Segment],
        *,
        acquirer: Acquirer,
        compiler: Compiler,
        span_attributes: SpanAttributes,
        transform_rows: TransformRows | None,
        borrower: Borrower | None,
    ) -> None:
        super().__init__(segments)
        self.acquirer = acquirer
        self.compiler = compiler
        self.span_attributes = tuple(span_attributes)
        self.transform_rows = transform_rows
        self.borrower = borrower

    def __repr__(self) -> str:
        sql, params = self.compile()
        return f"Statement({sql!r}, {list(params)!r})"

    def compile(self, without_transform: bool = False) -> Compiled:
        """The SQL text and parameters, for the client's dialect."""
        return self.compiler.compile(self, without_transform)

    def to_json(self) -> dict[str, object]:
        sql, params = self.compile()
        return {"_id": "Statement", "segments": list(self.segments), "sql": sql, "params": params}

    def _step(self, fiber: Fiber[Any, Any]) -> Effect[list[A], SqlError]:
        transform = self.transform_rows
        return self._with_connection(
            "execute",
            lambda conn, sql, params: cast(
                "Effect[list[A], SqlError]", conn.execute(sql, params, transform).map(list)
            ),
            False,
        )

    # --- the ways to run it ----------------------------------------------------

    @property
    def without_transform(self) -> Effect[list[A], SqlError]:
        """Its rows, with identifiers and result columns not renamed."""
        return self._with_connection(
            "executeWithoutTransform",
            lambda conn, sql, params: cast(
                "Effect[list[A], SqlError]", conn.execute(sql, params, None).map(list)
            ),
            True,
        )

    @property
    def raw(self) -> Effect[object, SqlError]:
        """The driver's own result, with nothing renamed."""
        return self._with_connection(
            "executeRaw", lambda conn, sql, params: conn.execute_raw(sql, params), True
        )

    @property
    def values(self) -> Effect[list[ValueRow], SqlError]:
        """Its rows as tuples of values, in column order."""
        return self._with_connection(
            "executeValues",
            lambda conn, sql, params: conn.execute_values(sql, params).map(list),
            False,
        )

    @property
    def values_unprepared(self) -> Effect[list[ValueRow], SqlError]:
        return self._with_connection(
            "executeValuesUnprepared",
            lambda conn, sql, params: conn.execute_values_unprepared(sql, params).map(list),
            False,
        )

    @property
    def unprepared(self) -> Effect[list[A], SqlError]:
        """Its rows, running it without preparing it (or caching the
        prepared statement), where the driver tells the two apart."""
        transform = self.transform_rows
        return self._with_connection(
            "executeUnprepared",
            lambda conn, sql, params: cast(
                "Effect[list[A], SqlError]",
                conn.execute_unprepared(sql, params, transform).map(list),
            ),
            False,
        )

    @property
    def stream(self) -> Stream[A, SqlError]:
        """Its rows as a stream, holding the connection until the stream
        ends."""
        from pyfect import stream

        def with_span(span: Span) -> Effect[Stream[A, SqlError]]:
            def body(
                statement: Statement[A], fiber: Fiber[Any, Any]
            ) -> Effect[Any, SqlError, Scope]:
                sql, params = statement.compile()
                self._annotate(span, "executeStream", sql)
                propagate = _propagates(fiber)
                clock = _wait_clock(fiber) if propagate else None

                def open_stream(conn: Connection) -> Stream[Row, SqlError]:
                    if clock is not None:
                        _record_connection_wait(span, clock)
                    return conn.execute_stream(sql, params, self.transform_rows)

                acquire = self.acquirer.map(open_stream)
                if propagate:
                    inner = stream.unwrap(acquire).pipe(stream.provide_service(ParentSpan, span))
                    return _Succeed(inner)
                return acquire

            return cast("Effect[Stream[A, SqlError]]", _with_statement(self, span, body))

        span = make_span_scoped(span_name(self.span_attributes), kind="client")
        return stream.unwrap(span.flat_map(with_span))

    # --- running on a connection ---------------------------------------------------

    def _annotate(self, span: Span, operation: str, sql: str) -> None:
        for key, value in self.span_attributes:
            span.attribute(key, value)
        span.attribute(_ATTR_SQL_METHOD, operation)
        span.attribute(_ATTR_DB_QUERY_TEXT, sql)

    def _with_connection[X](
        self, operation: str, f: _Run[X], without_transform: bool
    ) -> Effect[X, SqlError]:
        return use_span(
            span_name(self.span_attributes),
            lambda span: self._with_connection_span(operation, f, without_transform, span),
            kind="client",
        )

    def _with_connection_span[X](
        self, operation: str, f: _Run[X], without_transform: bool, span: Span
    ) -> Effect[X, SqlError]:
        def body(statement: Statement[A], fiber: Fiber[Any, Any]) -> Effect[X, SqlError]:
            sql, params = statement.compile(without_transform)
            self._annotate(span, operation, sql)
            propagate = _propagates(fiber)
            clock = _wait_clock(fiber) if propagate else None

            def run(conn: Connection) -> Effect[X, SqlError]:
                return f(conn, sql, params)

            if clock is not None:
                wait_clock = clock

                def run(conn: Connection) -> Effect[X, SqlError]:
                    def waited() -> Effect[X, SqlError]:
                        _record_connection_wait(span, wait_clock)
                        return f(conn, sql, params)

                    return _Suspend(waited)

            execute: Effect[X, SqlError] = (
                scoped(self.acquirer.flat_map(run)) if self.borrower is None else self.borrower(run)
            )
            return in_parent_span(execute, span) if propagate else execute

        return _with_statement(self, span, body)


def _propagates(fiber: Fiber[Any, Any]) -> bool:
    return fiber.get_ref(TracerEnabled) and fiber.get_ref(SpanPropagationEnabled)


def _with_statement[A, X, E, R](
    self: Statement[A],
    span: Span,
    f: Callable[[Statement[A], Fiber[Any, Any]], Effect[X, E, R]],
) -> Effect[X, E, R]:
    def body(fiber: Fiber[Any, Any]) -> Effect[X, E, R]:
        transform = fiber.get_ref(CurrentTransformer)
        if transform is None:
            return f(self, fiber)
        constructor = make(
            self.acquirer, self.compiler, self.span_attributes, self.transform_rows, self.borrower
        )
        transformed = transform(self, constructor, fiber, span)
        return transformed.flat_map(lambda statement: f(statement, fiber))

    return _WithFiber(body)


class Constructor:
    """Builds statements for one client: call it with SQL text and values,
    and use its helpers for names, lists and records::

        sql("SELECT * FROM users WHERE id = {id}", id=user_id)
        sql("SELECT * FROM {table} WHERE {cond}", table=sql.identifier("users"),
            cond=sql.and_([sql("age > {}", 18), sql.in_("role", roles)]))
        sql("INSERT INTO users {}", sql.insert({"name": "Ada"}).returning("*"))

    The text must be a string literal (``LiteralString``; a t-string on
    Python 3.14): every value is bound as a parameter, unless it is a
    fragment or a helper, which are placed as they are. Write ``{{`` and
    ``}}`` for braces. ``unsafe`` is the only way to run text built at
    runtime."""

    __slots__ = ("acquirer", "borrower", "compiler", "span_attributes", "transform_rows")

    def __init__(
        self,
        acquirer: Acquirer,
        compiler: Compiler,
        span_attributes: SpanAttributes,
        transform_rows: TransformRows | None,
        borrower: Borrower | None = None,
    ) -> None:
        self.acquirer = acquirer
        self.compiler = compiler
        self.span_attributes = tuple(span_attributes)
        self.transform_rows = transform_rows
        self.borrower = borrower

    @property
    def dialect(self) -> Dialect:
        return self.compiler.dialect

    def _statement(self, segments: Sequence[Segment]) -> Statement[Row]:
        return Statement(
            segments,
            acquirer=self.acquirer,
            compiler=self.compiler,
            span_attributes=self.span_attributes,
            transform_rows=self.transform_rows,
            borrower=self.borrower,
        )

    def __call__(self, template: SqlText, /, *args: object, **kwargs: object) -> Statement[Row]:
        return self._statement(segments_of(template, args, kwargs))

    def unsafe(self, sql: str, params: Sequence[object] | None = None) -> Statement[Row]:
        """A statement of SQL text built at runtime, with ``params`` bound to
        its placeholders. Never build the text from untrusted input."""
        return self._statement((unsafe_literal(sql, params),))

    @staticmethod
    def literal(sql: LiteralString) -> Fragment:
        """SQL text as a fragment."""
        return Fragment((literal(sql),))

    @staticmethod
    def identifier(name: str) -> Identifier:
        """A name, escaped (Effect's ``sql("name")``)."""
        return identifier(name)

    @overload
    @staticmethod
    def in_(values: Sequence[object], /) -> ArrayHelper: ...
    @overload
    @staticmethod
    def in_(column: str, values: Sequence[object], /) -> Fragment: ...
    @staticmethod
    def in_(*args: Any) -> ArrayHelper | Fragment:
        """``in_(values)``: ``(a, b, ...)``; ``in_(column, values)``:
        ``"column" IN (...)``, or ``1=0`` for no values."""
        if len(args) == 1:
            return in_(args[0])
        column, values = args
        return in_(column, values)

    @staticmethod
    def insert(value: Mapping[str, object] | Sequence[Mapping[str, object]]) -> RecordInsertHelper:
        """``(columns) VALUES (...)`` for one row or several."""
        return insert(value)

    @staticmethod
    def update(value: Mapping[str, object], omit: Sequence[str] = ()) -> RecordUpdateHelperSingle:
        """``column = value, ...`` for one row, without the ``omit``
        columns."""
        return update(value, omit)

    @staticmethod
    def update_values(value: Sequence[Mapping[str, object]], alias: str) -> RecordUpdateHelper:
        """Several rows to update, as a ``VALUES`` list named ``alias``. Not
        supported by SQLite."""
        return update_values(value, alias)

    @staticmethod
    def and_(clauses: Sequence[LiteralString | Fragment]) -> Fragment:
        """``(a AND b ...)``; ``1=1`` for no clauses."""
        return and_(clauses)

    @staticmethod
    def or_(clauses: Sequence[LiteralString | Fragment]) -> Fragment:
        """``(a OR b ...)``; ``1=1`` for no clauses."""
        return or_(clauses)

    @staticmethod
    def csv(
        values: Sequence[LiteralString | Fragment], prefix: LiteralString | None = None
    ) -> Fragment:
        """``a,b,...`` after ``prefix`` (``ORDER BY``); nothing for none."""
        return csv(values, prefix)

    @staticmethod
    def join(
        separator: LiteralString, add_parens: bool = True, fallback: LiteralString = ""
    ) -> Callable[[Sequence[LiteralString | Fragment]], Fragment]:
        return join(separator, add_parens, fallback)

    def on_dialect[T](
        self,
        *,
        sqlite: Callable[[], T],
        pg: Callable[[], T],
        mysql: Callable[[], T],
        mssql: Callable[[], T],
        clickhouse: Callable[[], T],
    ) -> T:
        """The result of the function for the client's dialect."""
        branches: dict[str, Callable[[], T]] = {
            "sqlite": sqlite,
            "pg": pg,
            "mysql": mysql,
            "mssql": mssql,
            "clickhouse": clickhouse,
        }
        return branches[self.dialect]()

    def on_dialect_or_else[T](
        self,
        *,
        or_else: Callable[[], T],
        sqlite: Callable[[], T] | None = None,
        pg: Callable[[], T] | None = None,
        mysql: Callable[[], T] | None = None,
        mssql: Callable[[], T] | None = None,
        clickhouse: Callable[[], T] | None = None,
    ) -> T:
        """The result of the function for the client's dialect, or of
        ``or_else`` when it has none."""
        branches: dict[str, Callable[[], T] | None] = {
            "sqlite": sqlite,
            "pg": pg,
            "mysql": mysql,
            "mssql": mssql,
            "clickhouse": clickhouse,
        }
        branch = branches[self.dialect]
        return (or_else if branch is None else branch)()


def make(
    acquirer: Acquirer,
    compiler: Compiler,
    span_attributes: SpanAttributes,
    transform_rows: TransformRows | None,
    borrower: Borrower | None = None,
) -> Constructor:
    """A statement constructor running on ``acquirer`` (or ``borrower``,
    for single statements)."""
    return Constructor(acquirer, compiler, span_attributes, transform_rows, borrower)


__all__ = [
    "Constructor",
    "CurrentTransformer",
    "SpanAttributes",
    "SpanPropagationEnabled",
    "Statement",
    "Transformer",
    "make",
    "span_name",
    "span_target",
]
