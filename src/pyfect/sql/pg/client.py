"""The PostgreSQL client (Effect's ``@effect/sql-pg`` ``PgClient``): an
``SqlClient`` on psycopg, with ``json`` values and ``LISTEN`` / ``NOTIFY``.

``make`` builds it on a pool (``pyfect.sql.pg.pool``), ``make_client`` on
one session shared by every fiber (statements wait for it in turn, and a
transaction or a stream holds it until it ends)::

    program.pipe(fx.provide(pg.layer(pg.PgPoolConfig(url=redacted.make(url)))))
"""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import TYPE_CHECKING, Any, Never, Unpack, cast

from pyfect._core import Effect, _Locally, _WithFiber
from pyfect._effect_args import require_effect
from pyfect._subscriber_queue import check_capacity
from pyfect.config import Config, ConfigError, unwrap
from pyfect.context import Context, Tag
from pyfect.effect import fail, succeed, void
from pyfect.layer import Layer, provide
from pyfect.layer import effect_context as layer_effect_context
from pyfect.queue import Dequeue
from pyfect.reactivity import Reactivity
from pyfect.reactivity import layer as reactivity_layer
from pyfect.scope import Scope, scoped
from pyfect.sql.client import ClientFields, SqlClient, SqlClientService
from pyfect.sql.client import make as make_sql_client
from pyfect.sql.connection import Acquirer, Borrower, Connection, Row, TransformRows, ValueRow
from pyfect.sql.error import SqlError, UnknownError
from pyfect.sql.pg import pool as pg_pool
from pyfect.sql.pg.config import PgClientConfig, PgPoolConfig
from pyfect.sql.pg.connection import DEFAULT_LISTEN_CAPACITY, Notification, PgConnection, Result
from pyfect.sql.pg.connection import make as make_connection
from pyfect.sql.pg.error import validate_channel_name
from pyfect.sql.statement import (
    Compiled,
    Compiler,
    Custom,
    Fragment,
    Placeholder,
    default_escape,
    default_transforms,
)
from pyfect.sql.statement import (
    make_compiler as make_statement_compiler,
)

if TYPE_CHECKING:
    from pyfect.stream import Stream

_escape = default_escape('"')


class PgSqlConnection:
    """A ``Connection`` on a session; with ``stream_acquirer``, each
    stream runs on a session of its own."""

    __slots__ = ("connection", "stream_acquirer")

    def __init__(
        self,
        connection: PgConnection,
        stream_acquirer: Effect[PgConnection, SqlError, Scope] | None = None,
    ) -> None:
        self.connection = connection
        self.stream_acquirer = stream_acquirer

    def _rows(
        self,
        sql: str,
        params: Sequence[object],
        prepare: bool,
        transform_rows: TransformRows | None,
    ) -> Effect[Sequence[Row], SqlError]:
        rows = self.connection.query(sql, params, prepare).map(lambda result: result.rows)
        return rows if transform_rows is None else rows.map(transform_rows)

    def execute(
        self, sql: str, params: Sequence[object], transform_rows: TransformRows | None, /
    ) -> Effect[Sequence[Row], SqlError]:
        return self._rows(sql, params, True, transform_rows)

    def execute_unprepared(
        self, sql: str, params: Sequence[object], transform_rows: TransformRows | None, /
    ) -> Effect[Sequence[Row], SqlError]:
        return self._rows(sql, params, False, transform_rows)

    def execute_raw(self, sql: str, params: Sequence[object], /) -> Effect[object, SqlError]:
        """The statement's ``Result``."""
        return self.connection.query(sql, params)

    def execute_values(
        self, sql: str, params: Sequence[object], /
    ) -> Effect[Sequence[ValueRow], SqlError]:
        return self.connection.query_values(sql, params)

    def execute_values_unprepared(
        self, sql: str, params: Sequence[object], /
    ) -> Effect[Sequence[ValueRow], SqlError]:
        return self.connection.query_values(sql, params, False)

    def execute_stream(
        self, sql: str, params: Sequence[object], transform_rows: TransformRows | None, /
    ) -> Stream[Row, SqlError]:
        from pyfect import stream

        if self.stream_acquirer is None:
            rows: Stream[Row, SqlError] = self.connection.stream(sql, params)
        else:
            rows = stream.unwrap(self.stream_acquirer.map(lambda c: c.stream(sql, params)))
        if transform_rows is None:
            return rows
        transform = transform_rows
        return rows.map_array(lambda chunk: tuple(transform(chunk)))


def _commit(conn: Connection) -> Effect[None, SqlError]:
    """PostgreSQL answers ``ROLLBACK`` to the ``COMMIT`` of an aborted
    transaction."""

    def check(result: object) -> Effect[None, SqlError]:
        if cast("Result", result).command != "ROLLBACK":
            return void
        message = "COMMIT rolled back an aborted transaction"
        return fail(
            SqlError(
                reason=UnknownError(
                    cause=Exception(message), message=f"PgClient: {message}", operation="commit"
                )
            )
        )

    return conn.execute_raw("COMMIT", ()).flat_map(check)


class PgClientService(SqlClientService):
    """A PostgreSQL client: an ``SqlClientService`` with ``json`` values
    and ``LISTEN`` / ``NOTIFY``."""

    __slots__ = ("_listen_acquirer", "config")

    config: PgClientConfig

    def __init__(
        self,
        *,
        config: PgClientConfig,
        listen_acquirer: Effect[PgConnection, SqlError, Scope],
        **fields: Unpack[ClientFields],
    ) -> None:
        super().__init__(**fields)
        self.config = config
        self._listen_acquirer = listen_acquirer

    @staticmethod
    def json(value: object) -> Fragment:
        """``value`` bound as ``jsonb`` (its keys renamed with
        ``transform_query_names`` when ``transform_json``)."""
        return Fragment((Custom("PgJson", value, None, None),))

    def listen(
        self, channel: str, *, capacity: int = DEFAULT_LISTEN_CAPACITY
    ) -> Effect[Dequeue[Notification, SqlError], SqlError, Scope]:
        """A queue of ``channel``'s notifications once ``LISTEN`` is
        confirmed; the listener holds a session until the scope closes. If
        the session fails, the queue fails with its error; closing the
        scope interrupts the queue's takers. The queue holds at most
        ``capacity`` notifications not yet taken; one more fails it (after
        those) with an error saying the listener fell behind."""
        check_capacity(capacity)
        return self._listen_acquirer.flat_map(
            lambda connection: connection.listen(channel, capacity=capacity)
        )

    def notify(self, channel: str, payload: str) -> Effect[None, SqlError]:
        """Send ``payload`` on ``channel`` (``pg_notify``)."""
        error = validate_channel_name(channel, "notify")
        if error is not None:
            return fail(error)
        sent = self.acquirer.flat_map(
            lambda conn: conn.execute_raw("SELECT pg_notify($1, $2)", (channel, payload))
        )
        return scoped(sent).as_void()


class PgClient(Tag[PgClientService], key="@effect/sql-pg/PgClient"):
    """The PostgreSQL client service."""


def make_compiler(
    transform: Callable[[str], str] | None = None, transform_json: bool = True
) -> Compiler:
    """PostgreSQL's compiler: ``$1`` placeholders, ``"quoted"`` names
    (renamed with ``transform``), ``update_values`` as a ``VALUES`` list
    and ``json`` values as ``jsonb``."""
    transform_value = (
        default_transforms(transform).value if transform_json and transform is not None else None
    )

    def on_identifier(value: str, without_transform: bool) -> str:
        if transform is None or without_transform:
            return _escape(value)
        return _escape(transform(value))

    def on_record_update(
        placeholders: str,
        alias: str,
        columns: str,
        values: Sequence[Sequence[object]],
        returning: Compiled | None,
    ) -> Compiled:
        sql = f"(values {placeholders}) AS {alias}{columns}"
        binds = [value for row in values for value in row]
        if returning is not None:
            sql += f" RETURNING {returning[0]}"
            binds.extend(returning[1])
        return sql, tuple(binds)

    def on_custom(
        segment: Custom[Any, Any, Any, Any], placeholder: Placeholder, without_transform: bool
    ) -> Compiled:
        from psycopg.types.json import Jsonb

        if segment.kind != "PgJson":
            raise TypeError(f"PostgreSQL has no custom segment {segment.kind!r}")
        value = (
            segment.param_a
            if without_transform or transform_value is None
            else transform_value(segment.param_a)
        )
        return placeholder(None), (Jsonb(value),)

    return make_statement_compiler(
        dialect="pg",
        placeholder=lambda index, _value: f"${index}",
        on_identifier=on_identifier,
        on_record_update=on_record_update,
        on_custom=on_custom,
    )


def _make_impl(
    *,
    acquirer: Acquirer,
    borrower: Borrower | None,
    transaction_acquirer: Acquirer,
    listen_acquirer: Effect[PgConnection, SqlError, Scope],
    config: PgClientConfig,
) -> Effect[PgClientService, Never, Reactivity]:
    def with_context(fiber: Any) -> Effect[PgClientService, Never, Reactivity]:
        captured: Context[Any] = fiber._context
        hook = config.on_acquire
        acquire, transact, listen, borrow = (
            acquirer,
            transaction_acquirer,
            listen_acquirer,
            borrower,
        )
        if hook is not None:
            # The consuming fiber's services win over the captured ones.
            on_acquire: Effect[None] = _Locally(hook, captured.merge)
            acquire = acquirer.tap(lambda _: on_acquire)
            transact = transaction_acquirer.tap(lambda _: on_acquire)
            listen = listen_acquirer.tap(lambda _: on_acquire)
            if borrower is not None:
                lend = borrower

                def borrowing[A, E, R](
                    f: Callable[[Connection], Effect[A, E, R]],
                ) -> Effect[A, E | SqlError, R]:
                    return lend(lambda conn: scoped(on_acquire.and_then(f(conn))))

                borrow = borrowing
        compiler = make_compiler(config.transform_query_names, config.transform_json)
        transform_rows = (
            None
            if config.transform_result_names is None
            else default_transforms(config.transform_result_names, config.transform_json).array
        )
        span_attributes = [
            *config.span_attributes.items(),
            ("db.system.name", "postgresql"),
            ("db.namespace", config.database or config.username or "postgres"),
            ("server.address", config.host or "localhost"),
            ("server.port", config.port or 5432),
        ]
        client = make_sql_client(
            driver="pg",
            acquirer=acquire,
            borrower=borrow,
            prepare_transaction_controls=True,
            commit=_commit,
            release_savepoint=lambda name: f"RELEASE SAVEPOINT {name}",
            transaction_acquirer=transact,
            compiler=compiler,
            span_attributes=span_attributes,
            transform_rows=transform_rows,
        )
        return client.map(
            lambda c: PgClientService(config=config, listen_acquirer=listen, **c.fields())
        )

    return _WithFiber(with_context)


def _wrap(connection: PgConnection) -> Connection:
    return PgSqlConnection(connection)


def make(config: PgPoolConfig) -> Effect[PgClientService, SqlError, Scope | Reactivity]:
    """A client on a pool of sessions; it closes with the scope."""

    def build(pool: pg_pool.PgPoolService) -> Effect[PgClientService, Never, Reactivity]:
        def borrow[A, E, R](
            f: Callable[[Connection], Effect[A, E, R]],
        ) -> Effect[A, E | SqlError, R]:
            return pool.use(lambda connection: f(_wrap(connection)))

        return _make_impl(
            acquirer=pool.get.map(_wrap),
            borrower=borrow,
            transaction_acquirer=pool.reserve.map(_wrap),
            listen_acquirer=pool.reserve,
            config=config,
        )

    return pg_pool.make(config).flat_map(build)


def make_client(
    config: PgClientConfig, *, acquire_for_stream: bool = False
) -> Effect[PgClientService, SqlError, Scope | Reactivity]:
    """A client on one session; with ``acquire_for_stream``, each stream
    and listener opens a session of its own."""

    def build(connection: PgConnection) -> Effect[PgClientService, Never, Reactivity]:
        side = make_connection(config) if acquire_for_stream else None
        return _make_impl(
            acquirer=succeed(PgSqlConnection(connection, side)),
            borrower=None,
            transaction_acquirer=connection.pin.map(_wrap),
            listen_acquirer=side if side is not None else connection.pin,
            config=config,
        )

    return make_connection(config).flat_map(build)


def _contexts(client: PgClientService) -> Context[PgClient | SqlClient]:
    return Context.empty().add(PgClient, client).add(SqlClient, client)


def layer_from[E](
    acquire: Effect[PgClientService, E, Scope | Reactivity],
) -> Layer[PgClient | SqlClient, E]:
    """Provides the client ``acquire`` makes as ``PgClient`` and
    ``SqlClient``, with its own ``Reactivity``."""
    require_effect(acquire, "acquire")
    return layer_effect_context(acquire.map(_contexts)).pipe(provide(reactivity_layer))


def layer(config: PgPoolConfig) -> Layer[PgClient | SqlClient, SqlError]:
    """Provides a pooled client (``make``)."""
    return layer_from(make(config))


def layer_config(
    config: Config[PgPoolConfig] | Mapping[str, Any],
) -> Layer[PgClient | SqlClient, ConfigError | SqlError]:
    """``layer`` with the config read from the ``ConfigProvider``: a
    ``Config`` of the whole config, or a mapping from field names to their
    ``Config`` (Effect's ``Config.Wrap``)::

        pg.layer_config({"url": fx.config.redacted("DATABASE_URL")})
    """
    read: Effect[PgPoolConfig, ConfigError] = (
        config
        if isinstance(config, Config)
        else unwrap(config).map(lambda fields: PgPoolConfig(**fields))
    )
    return layer_from(read.flat_map(make))


__all__ = [
    "PgClient",
    "PgClientService",
    "PgSqlConnection",
    "layer",
    "layer_config",
    "layer_from",
    "make",
    "make_client",
    "make_compiler",
]
