"""The ClickHouse client (Effect's ``@effect/sql-clickhouse``
``ClickhouseClient``): an ``SqlClient`` over ClickHouse's HTTP interface,
with typed parameters (``param``), commands (``as_command``), inserts in any
format (``insert_query``) and per-effect query ids and settings.

``make`` checks the server with ``/ping`` (within five seconds). Statements
compile to ``{p1: Type}`` placeholders, the type inferred from the value
(``params.type_of``) unless ``param`` names it, and ``"quoted"`` names::

    program.pipe(fx.provide(clickhouse.layer(clickhouse.ClickhouseClientConfig(url=...))))

A statement runs as a ``query`` with ``FORMAT JSON`` appended, which a
statement with data (``INSERT ... VALUES``) does not accept: run those with
``as_command`` or use ``insert_query``.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any, Never, Unpack

from pyfect._core import Effect
from pyfect._effect_args import require_effect
from pyfect.config import Config, ConfigError, unwrap
from pyfect.context import Context, Tag
from pyfect.effect import fail, provide_service, succeed, with_fiber
from pyfect.layer import Layer, provide
from pyfect.layer import effect_context as layer_effect_context
from pyfect.reactivity import Reactivity
from pyfect.reactivity import layer as reactivity_layer
from pyfect.scope import Scope
from pyfect.sql.clickhouse._connection import (
    ClickhouseConnection,
    ClickhouseSettings,
    ClientMethod,
    QueryId,
    kill_query,
    query_id_of,
)
from pyfect.sql.clickhouse.config import ClickhouseClientConfig
from pyfect.sql.clickhouse.driver import (
    ClickhouseDriver,
    DataFormat,
    InsertColumns,
    InsertResult,
    InsertValues,
)
from pyfect.sql.clickhouse.error import catch
from pyfect.sql.clickhouse.params import Settings, type_of
from pyfect.sql.client import ClientFields, SqlClient, SqlClientService
from pyfect.sql.client import make as make_sql_client
from pyfect.sql.connection import Connection
from pyfect.sql.error import ConnectionError, SqlError
from pyfect.sql.statement import (
    Compiled,
    Compiler,
    Custom,
    Fragment,
    Parameter,
    Placeholder,
    custom,
    default_escape,
    default_transforms,
    is_custom,
)
from pyfect.sql.statement import make_compiler as make_statement_compiler

type ClickhouseParam = Custom[str, str, object, None]
"""A parameter bound as a named ClickHouse type (``param``)."""

_clickhouse_param: Callable[[str, object, None], ClickhouseParam] = custom("ClickhouseParam")
is_clickhouse_param = is_custom("ClickhouseParam")

CONNECT_TIMEOUT = "5 seconds"
"""How long ``make`` waits for ``/ping``, in seconds."""

_INSERT = catch("Failed to insert data", "insert")


class ClickhouseClientService(SqlClientService):
    """A ClickHouse client: an ``SqlClientService``, its config and the
    ``ClickhouseDriver`` it runs on (``client``)."""

    __slots__ = ("client", "config")

    config: ClickhouseClientConfig
    client: ClickhouseDriver
    """The HTTP client behind this one, for what the SQL client does not
    wrap (``exec`` with raw formats). Its requests ignore ``with_query_id``,
    ``with_clickhouse_settings`` and ``as_command``, and interrupting one
    does not kill its query; pass ``query_id`` and ``clickhouse_settings``
    to it directly."""

    def __init__(
        self,
        *,
        config: ClickhouseClientConfig,
        client: ClickhouseDriver,
        **fields: Unpack[ClientFields],
    ) -> None:
        super().__init__(**fields)
        self.config = config
        self.client = client

    def param(self, data_type: str, value: object) -> Fragment:
        """``value`` bound as ``data_type`` (``sql.param("Nullable(Int32)",
        None)`` is ``{p1: Nullable(Int32)}``)."""
        return Fragment((_clickhouse_param(data_type, value, None),))

    def as_command[A, E, R](self, effect: Effect[A, E, R]) -> Effect[A, E, R]:
        """``effect`` with its statements run as commands: no ``FORMAT`` is
        appended and their output is discarded (``INSERT ... VALUES``,
        DDL)."""
        require_effect(effect, "effect")
        return effect.pipe(provide_service(ClientMethod, "command"))

    def with_query_id[A, E, R](self, effect: Effect[A, E, R], query_id: str) -> Effect[A, E, R]:
        """``effect`` with ``query_id`` as the id of its statements and
        inserts."""
        require_effect(effect, "effect")
        return effect.pipe(provide_service(QueryId, query_id))

    def with_clickhouse_settings[A, E, R](
        self, effect: Effect[A, E, R], settings: Settings
    ) -> Effect[A, E, R]:
        """``effect`` with ``settings`` sent with its statements and inserts
        (in place of any set further out)."""
        require_effect(effect, "effect")
        return effect.pipe(provide_service(ClickhouseSettings, settings))

    def insert_query(
        self,
        *,
        table: str,
        values: InsertValues,
        format: DataFormat = "JSONEachRow",
        columns: InsertColumns | None = None,
    ) -> Effect[InsertResult, SqlError]:
        """Insert ``values`` into ``table`` in ``format`` (``JSONEachRow``:
        a list of dicts), setting ``columns`` (``["a"]`` or ``{"except":
        ["id"]}``). Interrupting it kills the insert."""
        driver = self.client

        def body(fiber: Any) -> Effect[InsertResult, SqlError]:
            query_id = query_id_of(fiber)
            sent = driver.insert(
                table=table,
                values=values,
                format=format,
                columns=columns,
                query_id=query_id,
                clickhouse_settings=fiber.get_ref(ClickhouseSettings),
            )
            return sent.map_error(_INSERT).on_interrupt(kill_query(driver, query_id))

        return with_fiber(body)


class ClickhouseClient(Tag[ClickhouseClientService], key="@effect/sql-clickhouse/ClickhouseClient"):
    """The ClickHouse client service."""


_escape = default_escape('"')


def _placeholder_type(value: object) -> str:
    if isinstance(value, Fragment):
        return _placeholder_type(value.segments[0]) if value.segments else "String"
    if is_clickhouse_param(value):
        return value.param_a
    if isinstance(value, Parameter):
        return type_of(value.value)
    return type_of(value)


def _on_custom(
    segment: Custom[Any, Any, Any, Any], placeholder: Placeholder, _without_transform: bool
) -> Compiled:
    if is_clickhouse_param(segment):
        return (placeholder(segment), (segment.param_b,))
    return ("", ())


def _nothing(*_args: object) -> Compiled:
    return ("", ())


def make_compiler(transform: Callable[[str], str] | None = None) -> Compiler:
    """ClickHouse's compiler: ``{p1: Type}`` placeholders and ``"quoted"``
    names (renamed with ``transform`` unless a statement runs without
    transforms)."""

    def on_identifier(value: str, without_transform: bool) -> str:
        if transform is None or without_transform:
            return _escape(value)
        return _escape(transform(value))

    return make_statement_compiler(
        dialect="clickhouse",
        placeholder=lambda index, value: f"{{p{index}: {_placeholder_type(value)}}}",
        on_identifier=on_identifier,
        on_record_update=_nothing,
        on_custom=_on_custom,
    )


def _connect_timed_out() -> Effect[Never, SqlError]:
    return fail(
        SqlError(
            reason=ConnectionError(
                cause=Exception("connection timeout"),
                message="ClickhouseClient: Connection timeout",
                operation="connect",
            )
        )
    )


def _http_client(config: ClickhouseClientConfig) -> Effect[Any, Never, Scope]:
    if config.http_client is not None:
        return succeed(config.http_client)
    from pyfect.http import httpx_client

    return httpx_client.make(timeout=float(config.connection.request_timeout))


def make(
    config: ClickhouseClientConfig,
) -> Effect[ClickhouseClientService, SqlError, Scope | Reactivity]:
    """A client on ``config``'s server; the HTTP client it creates closes
    with the scope."""
    compiler = make_compiler(config.transform_query_names)
    transform_rows = (
        None
        if config.transform_result_names is None
        else default_transforms(config.transform_result_names).array
    )
    span_attributes: list[tuple[str, object]] = [
        *config.span_attributes.items(),
        ("db.system.name", "clickhouse"),
        ("db.namespace", config.connection.database),
    ]

    def build(http: Any) -> Effect[ClickhouseClientService, SqlError, Reactivity]:
        driver = ClickhouseDriver(http, config.connection)
        connected = (
            driver.ping()
            .map_error(catch("ClickhouseClient: Failed to connect", "connect", "connection"))
            .timeout_or_else(CONNECT_TIMEOUT, _connect_timed_out)
        )
        connection: Connection = ClickhouseConnection(driver)
        client = make_sql_client(
            driver="clickhouse",
            acquirer=succeed(connection),
            compiler=compiler,
            span_attributes=span_attributes,
            begin_transaction="BEGIN TRANSACTION",
            transform_rows=transform_rows,
        )

        def finish(c: SqlClientService) -> ClickhouseClientService:
            return ClickhouseClientService(config=config, client=driver, **c.fields())

        return connected.and_then(client.map(finish))

    return _http_client(config).flat_map(build)


def _contexts(client: ClickhouseClientService) -> Context[ClickhouseClient | SqlClient]:
    return Context.empty().add(ClickhouseClient, client).add(SqlClient, client)


def layer_from[E](
    acquire: Effect[ClickhouseClientService, E, Scope | Reactivity],
) -> Layer[ClickhouseClient | SqlClient, E]:
    """Provides the client ``acquire`` makes as ``ClickhouseClient`` and
    ``SqlClient``, with its own ``Reactivity``."""
    require_effect(acquire, "acquire")
    return layer_effect_context(acquire.map(_contexts)).pipe(provide(reactivity_layer))


def layer(config: ClickhouseClientConfig) -> Layer[ClickhouseClient | SqlClient, SqlError]:
    """Provides a client (``make``)."""
    return layer_from(make(config))


def layer_config(
    config: Config[ClickhouseClientConfig] | Mapping[str, Any],
) -> Layer[ClickhouseClient | SqlClient, ConfigError | SqlError]:
    """``layer`` with the config read from the ``ConfigProvider``: a
    ``Config`` of the whole config, or a mapping from field names to their
    ``Config`` (Effect's ``Config.Wrap``)::

        clickhouse.layer_config({
            "url": fx.config.string("CLICKHOUSE_URL"),
            "password": fx.config.redacted("CLICKHOUSE_PASSWORD"),
        })
    """
    read: Effect[ClickhouseClientConfig, ConfigError] = (
        config
        if isinstance(config, Config)
        else unwrap(config).map(lambda fields: ClickhouseClientConfig(**fields))
    )
    return layer_from(read.flat_map(make))


__all__ = [
    "CONNECT_TIMEOUT",
    "ClickhouseClient",
    "ClickhouseClientService",
    "ClickhouseParam",
    "ClickhouseSettings",
    "ClientMethod",
    "QueryId",
    "SqlError",
    "is_clickhouse_param",
    "layer",
    "layer_config",
    "layer_from",
    "make",
    "make_compiler",
]
