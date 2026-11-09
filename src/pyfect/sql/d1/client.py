"""The Cloudflare D1 client (Effect's ``@effect/sql-d1`` ``D1Client``): an
``SqlClient`` with SQLite's SQL over D1's HTTP API, sent with the
``HttpClient`` in context (``pyfect.http.httpx_client.layer``, or any
other)::

    program.pipe(
        fx.provide(d1.layer(d1.D1ClientConfig(account_id=..., database_id=..., api_token=...))),
        fx.provide(httpx_client.layer),
    )

As in Effect: ``batch`` runs statements in one request that D1 commits or
rolls back as a whole; transactions are a defect (D1 has none across
requests), as are streams; ``update_values`` is not supported; every
failure is an ``UnknownError``. ``pyfect.sql.migrator`` runs its migrations
in a transaction, so it dies on D1 too; apply D1 migrations with Cloudflare's
own tooling (``wrangler d1 migrations apply``).
"""
# pyright: reportPrivateUsage=false

from __future__ import annotations

import copy as copy_module
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Any, Never, Self, Unpack, overload
from warnings import deprecated

from pyfect._concurrency import for_each
from pyfect._core import Effect, _WithFiber
from pyfect._effect_args import require_effect
from pyfect.config import Config, ConfigError, unwrap
from pyfect.context import Context, Tag
from pyfect.effect import die, fail, succeed, suspend
from pyfect.http.client import HttpClient, HttpClientService
from pyfect.http.error import HttpClientError
from pyfect.layer import Layer, provide
from pyfect.layer import effect_context as layer_effect_context
from pyfect.reactivity import Reactivity
from pyfect.reactivity import layer as reactivity_layer
from pyfect.scope import Scope
from pyfect.sql.client import ClientFields, SqlClient, SqlClientService
from pyfect.sql.client import make as make_sql_client
from pyfect.sql.connection import Row, TransformRows, ValueRow
from pyfect.sql.d1.api import D1Api, D1ApiError, D1Result, Param, Query, bind
from pyfect.sql.d1.config import D1ClientConfig
from pyfect.sql.error import SqlError, UnknownError
from pyfect.sql.statement import (
    CurrentTransformer,
    RecordUpdateHelper,
    Statement,
    default_transforms,
    make_compiler_sqlite,
    span_name,
    span_target,
)
from pyfect.tracer._model import Span
from pyfect.tracer._spans import use_span

if TYPE_CHECKING:
    from pyfect._fiber import Fiber
    from pyfect.stream import Stream

_ATTR_DB_OPERATION_NAME = "db.operation.name"
_ATTR_DB_OPERATION_BATCH_SIZE = "db.operation.batch.size"
_ATTR_DB_QUERY_TEXT = "db.query.text"


def _error(cause: object, message: str) -> SqlError:
    return SqlError(reason=UnknownError(cause=cause, message=message, operation="execute"))


def _query(sql: str, params: Sequence[object], message: str) -> Effect[Query, SqlError]:
    def build() -> Effect[Query, SqlError]:
        try:
            bound: list[Param] = [bind(p) for p in params]
        except TypeError as cause:
            return fail(_error(cause, message))
        return succeed((sql, bound))

    return suspend(build)


class _D1Connection:
    """Statements on D1's HTTP API: one request each."""

    __slots__ = ("api",)

    def __init__(self, api: D1Api) -> None:
        self.api = api

    def _results(self, sql: str, params: Sequence[object]) -> Effect[D1Result, SqlError]:
        message = "Failed to execute statement"

        def run(query: Query) -> Effect[D1Result, SqlError]:
            sent: Effect[list[D1Result], D1ApiError | HttpClientError] = self.api.query([query])
            return sent.map(lambda results: results[0]).map_error(lambda e: _error(e, message))

        return _query(sql, params, message).flat_map(run)

    def execute(
        self, sql: str, params: Sequence[object], transform_rows: TransformRows | None, /
    ) -> Effect[Sequence[Row], SqlError]:
        rows = self._results(sql, params).map(lambda result: result.results)
        return rows if transform_rows is None else rows.map(transform_rows)

    def execute_raw(self, sql: str, params: Sequence[object], /) -> Effect[object, SqlError]:
        return self._results(sql, params)

    def execute_unprepared(
        self, sql: str, params: Sequence[object], transform_rows: TransformRows | None, /
    ) -> Effect[Sequence[Row], SqlError]:
        return self.execute(sql, params, transform_rows)

    def execute_values(
        self, sql: str, params: Sequence[object], /
    ) -> Effect[Sequence[ValueRow], SqlError]:
        message = "Failed to execute statement"

        def run(query: Query) -> Effect[Sequence[ValueRow], SqlError]:
            sent = self.api.raw([query])
            return sent.map(lambda results: results[0].rows).map_error(lambda e: _error(e, message))

        return _query(sql, params, message).flat_map(run)

    def execute_values_unprepared(
        self, sql: str, params: Sequence[object], /
    ) -> Effect[Sequence[ValueRow], SqlError]:
        return self.execute_values(sql, params)

    def execute_stream(
        self, sql: str, params: Sequence[object], transform_rows: TransformRows | None, /
    ) -> Stream[Row, SqlError]:
        from pyfect import stream

        return stream.die(NotImplementedError("executeStream not implemented"))


def _batch_span_name(attributes: Sequence[tuple[str, object]]) -> str:
    target = span_target(attributes)
    return "BATCH" if target is None else f"BATCH {target}"


def _rows_of(
    results: Sequence[D1Result], transforms: Sequence[TransformRows | None]
) -> tuple[Any, ...]:
    """Each result's rows, renamed by its statement's transform. One entry of
    several statements gets a result for each, with no transform past the
    statements sent (Effect's ``transforms[index]``)."""
    padded = [*transforms, *[None] * (len(results) - len(transforms))]
    return tuple(
        list(result.results if transform is None else transform(result.results))
        for result, transform in zip(results, padded, strict=False)
    )


class D1ClientService(SqlClientService):
    """A D1 client: an ``SqlClientService`` with ``batch``, its config and
    the HTTP API it runs on (``api``)."""

    __slots__ = ("api", "config", "has_transforms")

    config: D1ClientConfig
    api: D1Api
    has_transforms: bool

    def __init__(
        self,
        *,
        config: D1ClientConfig,
        api: D1Api,
        **fields: Unpack[ClientFields],
    ) -> None:
        super().__init__(**fields)
        self.config = config
        self.api = api
        self.has_transforms = (
            config.transform_query_names is not None or config.transform_result_names is not None
        )

    def without_transforms(self) -> Self:
        """This client, without renaming identifiers or result columns
        (also when it only renames identifiers)."""
        if not self.has_transforms:
            return self
        copy = copy_module.copy(self)
        copy.compiler = self.compiler.without_transform
        copy.transform_rows = None
        copy.has_transforms = False
        return copy

    @overload
    def batch(self, statements: tuple[()], /) -> Effect[tuple[()], SqlError]: ...
    @overload
    def batch[A](self, statements: tuple[Statement[A]], /) -> Effect[tuple[list[A]], SqlError]: ...
    @overload
    def batch[A, B](
        self, statements: tuple[Statement[A], Statement[B]], /
    ) -> Effect[tuple[list[A], list[B]], SqlError]: ...
    @overload
    def batch[A, B, C](
        self, statements: tuple[Statement[A], Statement[B], Statement[C]], /
    ) -> Effect[tuple[list[A], list[B], list[C]], SqlError]: ...
    @overload
    def batch[A, B, C, D](
        self, statements: tuple[Statement[A], Statement[B], Statement[C], Statement[D]], /
    ) -> Effect[tuple[list[A], list[B], list[C], list[D]], SqlError]: ...
    @overload
    def batch[A](
        self, statements: Sequence[Statement[A]], /
    ) -> Effect[tuple[list[A], ...], SqlError]: ...
    def batch(self, statements: Sequence[Statement[Any]], /) -> Effect[tuple[Any, ...], SqlError]:
        """Run ``statements`` in one request, as one transaction: their
        rows in order, each renamed by the client that made it. A failure
        rolls back all of them. Outside the client's transactions (inside
        one it is a defect, as every D1 transaction is)."""
        if not statements:
            return succeed(())
        attributes = self.span_attributes
        is_batch = len(statements) > 1
        name = _batch_span_name(attributes) if is_batch else span_name(attributes)
        return use_span(name, lambda span: self._batch(statements, span), kind="client")

    def _batch(
        self, statements: Sequence[Statement[Any]], span: Span
    ) -> Effect[tuple[Any, ...], SqlError]:
        message = "Failed to execute batch"

        def body(fiber: Fiber[Any, Any]) -> Effect[tuple[Any, ...], SqlError]:
            transformer = fiber.get_ref(CurrentTransformer)

            def prepare(original: Statement[Any]) -> Effect[Statement[Any]]:
                if transformer is None:
                    return succeed(original)
                return transformer(original, self, fiber, span)

            def run(prepared: list[Statement[Any]]) -> Effect[tuple[Any, ...], SqlError]:
                compiled = [statement.compile() for statement in prepared]
                transforms = [statement.transform_rows for statement in prepared]
                for key, value in self.span_attributes:
                    span.attribute(key, value)
                if len(prepared) > 1:
                    span.attribute(_ATTR_DB_OPERATION_NAME, "BATCH")
                    span.attribute(_ATTR_DB_OPERATION_BATCH_SIZE, len(prepared))
                span.attribute(_ATTR_DB_QUERY_TEXT, "; ".join(sql for sql, _ in compiled))

                def send(queries: list[Query]) -> Effect[tuple[Any, ...], SqlError]:
                    sent = self.api.query(queries).map_error(lambda e: _error(e, message))
                    return sent.map(lambda results: _rows_of(results, transforms))

                queries = for_each(compiled, lambda c: _query(c[0], c[1], message))
                return queries.flat_map(send)

            return for_each(statements, prepare).flat_map(run)

        return _WithFiber(body)

    @staticmethod
    @deprecated("update_values is not supported by D1")
    def update_values(value: Sequence[Mapping[str, object]], alias: str) -> RecordUpdateHelper:
        """Not supported by D1: a type error (Effect's ``never``), and a
        ``TypeError`` when called anyway."""
        raise TypeError("update_values is not supported by D1")


class D1Client(Tag[D1ClientService], key="@effect/sql-d1/D1Client"):
    """The D1 client service."""


def make(
    config: D1ClientConfig,
) -> Effect[D1ClientService, Never, Scope | Reactivity | HttpClient]:
    """A client on ``config``'s database, sending with the ``HttpClient`` in
    context."""
    transform_rows = (
        None
        if config.transform_result_names is None
        else default_transforms(config.transform_result_names).array
    )
    span_attributes: list[tuple[str, object]] = [
        *config.span_attributes.items(),
        ("db.system.name", "sqlite"),
    ]

    def build(http: HttpClientService[Any]) -> Effect[D1ClientService, Never, Reactivity]:
        api = D1Api(http, config.database_url, config.api_token)
        connection = _D1Connection(api)
        client = make_sql_client(
            driver="d1",
            acquirer=succeed(connection),
            compiler=make_compiler_sqlite(config.transform_query_names),
            transaction_acquirer=die(NotImplementedError("transactions are not supported in D1")),
            span_attributes=span_attributes,
            transform_rows=transform_rows,
        )
        return client.map(lambda c: D1ClientService(config=config, api=api, **c.fields()))

    return HttpClient().flat_map(build)


def _contexts(client: D1ClientService) -> Context[D1Client | SqlClient]:
    return Context.empty().add(D1Client, client).add(SqlClient, client)


def layer_from[E](
    acquire: Effect[D1ClientService, E, Scope | Reactivity | HttpClient],
) -> Layer[D1Client | SqlClient, E, HttpClient]:
    """Provides the client ``acquire`` makes as ``D1Client`` and
    ``SqlClient``, with its own ``Reactivity``."""
    require_effect(acquire, "acquire")
    return layer_effect_context(acquire.map(_contexts)).pipe(provide(reactivity_layer))


def layer(config: D1ClientConfig) -> Layer[D1Client | SqlClient, Never, HttpClient]:
    """Provides a client (``make``)."""
    return layer_from(make(config))


def layer_config(
    config: Config[D1ClientConfig] | Mapping[str, Any],
) -> Layer[D1Client | SqlClient, ConfigError, HttpClient]:
    """``layer`` with the config read from the ``ConfigProvider``: a
    ``Config`` of the whole config, or a mapping from ``D1ClientConfig``
    field names to their ``Config`` (Effect's ``Config.Wrap``)::

        d1.layer_config({
            "account_id": fx.config.string("CLOUDFLARE_ACCOUNT_ID"),
            "database_id": fx.config.string("D1_DATABASE_ID"),
            "api_token": fx.config.redacted("CLOUDFLARE_API_TOKEN"),
        })
    """
    read: Effect[D1ClientConfig, ConfigError] = (
        config
        if isinstance(config, Config)
        else unwrap(config).map(lambda fields: D1ClientConfig(**fields))
    )
    return layer_from(read.flat_map(make))


__all__ = [
    "D1Client",
    "D1ClientService",
    "SqlError",
    "layer",
    "layer_config",
    "layer_from",
    "make",
]
