"""Routes served in memory to an ``HttpClient``, for tests: no socket, and
response bodies streamed as the handler writes them."""

from __future__ import annotations

from typing import Any, Never, overload

from pyfect._core import Effect
from pyfect._layer_core import Layer, require_layer
from pyfect.context import Context, ServiceMarker, Tag
from pyfect.effect import context, gen, update_context
from pyfect.http import _in_memory
from pyfect.http.client import HttpClient, HttpClientService
from pyfect.http.error import HttpClientError
from pyfect.http.router._api import to_http_effect
from pyfect.http.router._markers import GlobalRaises, GlobalRequires, Raises, Requires
from pyfect.http.router._router import HttpRouter
from pyfect.layer import effect as layer_effect
from pyfect.scope import CloseableScope, Scope


@overload
def in_memory_client[A, LE, X: Tag[Any] | ServiceMarker = Never](
    app_layer: Layer[A, LE, HttpRouter | X],
) -> Effect[HttpClientService[HttpClientError], LE, Scope | X]: ...
@overload
def in_memory_client[A, LE, E = Never, GE = Never, X: Tag[Any] | ServiceMarker = Never](
    app_layer: Layer[A, LE, HttpRouter | Raises[E] | GlobalRaises[GE] | X],
) -> Effect[HttpClientService[HttpClientError], LE, Scope | X]: ...
@overload
def in_memory_client[
    A,
    LE,
    E = Never,
    R = Never,
    GE = Never,
    GR = Never,
    X: Tag[Any] | ServiceMarker = Never,
](
    app_layer: Layer[
        A, LE, HttpRouter | Requires[R] | Raises[E] | GlobalRequires[GR] | GlobalRaises[GE] | X
    ],
) -> Effect[HttpClientService[HttpClientError, R | GR], LE, Scope | X]: ...
def in_memory_client(app_layer: Layer[Any, Any, Any]) -> Effect[Any, Any, Any]:
    """A client whose requests the routes of ``app_layer`` answer in
    memory, built into the current ``Scope`` (the client of Effect's
    ``HttpApiTest``, for any router). As there, every failure is a defect of
    the request (``Effect.orDie``), including those a server answers with a
    response: a route not found dies with its ``HttpServerError``, an
    ``HttpApi`` payload failing its schema with its ``HttpApiSchemaError``,
    and ``schema_path_params`` failing with its ``SchemaError``. The
    services its routes need come from the request's context. A streamed
    body reaches the client chunk by chunk, as the handler writes it, so a
    test can read server-sent events while the handler runs; the handler's
    request scope closes when the body ends or its reader stops."""
    require_layer(app_layer, "app_layer")

    @gen
    def run():
        app = yield from to_http_effect(app_layer)
        scope: CloseableScope = yield from Scope()
        return _in_memory.client(app, scope)

    return run


@overload
def layer_in_memory_client[A, LE, X: Tag[Any] | ServiceMarker = Never](
    app_layer: Layer[A, LE, HttpRouter | X],
) -> Layer[HttpClient, LE, X]: ...
@overload
def layer_in_memory_client[A, LE, E = Never, GE = Never, X: Tag[Any] | ServiceMarker = Never](
    app_layer: Layer[A, LE, HttpRouter | Raises[E] | GlobalRaises[GE] | X],
) -> Layer[HttpClient, LE, X]: ...
@overload
def layer_in_memory_client[
    A,
    LE,
    E = Never,
    R = Never,
    GE = Never,
    GR = Never,
    X: Tag[Any] | ServiceMarker = Never,
](
    app_layer: Layer[
        A, LE, HttpRouter | Requires[R] | Raises[E] | GlobalRequires[GR] | GlobalRaises[GE] | X
    ],
) -> Layer[HttpClient, LE, R | GR | X]: ...
def layer_in_memory_client(app_layer: Layer[Any, Any, Any]) -> Layer[Any, Any, Any]:
    """``in_memory_client`` as the ``HttpClient``. The services the routes
    need are the layer's, as with ``serve``; one the request provides itself
    comes first."""
    require_layer(app_layer, "app_layer")

    @gen
    def build():
        client: HttpClientService[HttpClientError, Any] = yield from in_memory_client(app_layer)
        services: Context[Any] = yield from context()

        def under_request(current: Context[Any]) -> Context[Any]:
            return services.merge(current)

        return client.transform(
            lambda sending, _request: sending.pipe(update_context(under_request))
        )

    return layer_effect(HttpClient, build)


__all__ = ["in_memory_client", "layer_in_memory_client"]
