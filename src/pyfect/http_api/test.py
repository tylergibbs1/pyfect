"""A client of an API served in memory (Effect's ``HttpApiTest``).

``groups(api, (Users,), layer=UsersLive)`` serves the handlers of the
listed groups without a server, and gives a client of the whole API; an
endpoint of another group dies when called::

    api_client = yield from http_api.test.groups(api, (Users,), layer=UsersLive)
    users = http_api.get_group(api_client, Users)

The client, and the layer, are valid until the caller's ``Scope`` closes.
Without ``layer`` the groups' layers come from the context, which must
then outlive the client: a layer provided to ``groups(...)`` alone is
released once the client is made, as in Effect.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Never, overload

from pyfect._core import Effect
from pyfect._layer_core import require_layer
from pyfect.context import Context
from pyfect.effect import context, die, gen, provide_context, provide_service, succeed
from pyfect.exit import Exit, Success
from pyfect.http._request_state import CurrentRequestState, RequestState
from pyfect.http.client import make as make_http_client
from pyfect.http.http_effect import scope_transfer_to_stream
from pyfect.http.request import HttpClientRequest
from pyfect.http.router import to_http_effect
from pyfect.http.server_request import HttpServerRequest, from_client_request
from pyfect.http.server_response import HttpServerResponse, to_client_response
from pyfect.http_api._handlers import HandlerEntry
from pyfect.http_api.api import ApiServing, HttpApi, api_of
from pyfect.http_api.builder import handler_to_route
from pyfect.http_api.builder import layer as api_layer
from pyfect.http_api.client import Client, make_with
from pyfect.http_api.group import AnyGroup, GroupService, HttpApiGroup
from pyfect.layer import Layer, succeed_context
from pyfect.layer import provide as layer_provide
from pyfect.scope import CloseableScope, Scope


@overload
def groups[G, S: HttpApiGroup[Any, Any]](
    api: ApiServing[G, S],
    served: Sequence[type[S]],
    *,
    base_url: str = "http://localhost:3000",
) -> Effect[Client[G], Never, S | Scope]: ...
@overload
def groups[G, S: HttpApiGroup[Any, Any], E, R](
    api: ApiServing[G, S],
    served: Sequence[type[S]],
    *,
    layer: Layer[S, E, R],
    base_url: str = "http://localhost:3000",
) -> Effect[Client[G], E, R | Scope]: ...
def groups(
    api: ApiServing[Any, Any],
    served: Sequence[AnyGroup],
    *,
    layer: Layer[Any, Any, Any] | None = None,
    base_url: str = "http://localhost:3000",
) -> Effect[Client[Any], Any, Any]:
    """A client of ``api`` whose requests are handled in memory by the
    handlers of ``served`` (a group ``api`` lacks is a type error). The
    groups' layers are ``layer``, built into the caller's ``Scope``, or
    else come from the context; the client is valid until that scope
    closes."""
    if layer is not None:
        require_layer(layer, "layer")
    made = _groups(api_of(api), served, base_url)
    if layer is None:
        return made
    return layer.build().flat_map(lambda built: made.pipe(provide_context(built)))


def _groups(
    api: HttpApi[Any], served: Sequence[AnyGroup], base_url: str
) -> Effect[Client[Any], Never, Any]:
    served_ids = {group.identifier for group in served}

    def run() -> Any:
        services: Context[Any] = yield from context()
        for group in api.groups.values():
            if group.identifier in served_ids:
                continue
            services = services.add(group.origin, _unhandled(api, group, services))
        app = api_layer(api).pipe(layer_provide(succeed_context(services)))
        handler: Effect[HttpServerResponse, Any, Any] = yield from to_http_effect(app)
        scope: CloseableScope = yield from Scope()
        http_client = make_http_client(
            lambda request, _url, _signal, _fiber: _handle(handler, scope, request)
        )
        return (yield from make_with(api, http_client=http_client, base_url=base_url))

    return gen(run)


def _unhandled(api: HttpApi[Any], group: AnyGroup, services: Context[Any]) -> GroupService:
    entries = {
        identifier: HandlerEntry(
            endpoint,
            lambda _request, identifier=identifier: die(
                RuntimeError(f"Unhandled endpoint: {identifier}")
            ),
            is_raw=False,
            uninterruptible=False,
        )
        for identifier, endpoint in group.endpoints.items()
    }
    routes = tuple(handler_to_route(api, group, entry, services) for entry in entries.values())
    return GroupService(routes, entries)


def _handle(
    handler: Effect[HttpServerResponse, Any, Any],
    scope: CloseableScope,
    request: HttpClientRequest,
) -> Effect[Any, Never, Any]:
    def run() -> Any:
        request_scope: CloseableScope = yield from scope.fork()
        server_request = from_client_request(request)
        state = RequestState()
        transferred = False

        def pre_response(response: HttpServerResponse) -> Effect[HttpServerResponse, Any, Any]:
            pre = state.pre_response_handler
            return succeed(response) if pre is None else pre(server_request, response)

        def to_client(response: HttpServerResponse) -> Any:
            nonlocal transferred
            transfer = scope_transfer_to_stream(response)
            transferred = transfer is not response
            return to_client_response(transfer, request=request)

        def on_exit(exit_: Exit[Any, Any]) -> Effect[None]:
            if transferred and isinstance(exit_, Success):
                return succeed(None)
            return request_scope.close(exit_)

        return (
            yield from handler.flat_map(pre_response)
            .map(to_client)
            .pipe(provide_service(HttpServerRequest, server_request))
            .pipe(provide_service(CurrentRequestState, state))
            .pipe(provide_service(Scope, request_scope))
            .or_die()
            .on_exit(on_exit)
        )

    return gen(run)


__all__ = ["groups"]
