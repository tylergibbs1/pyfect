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
from pyfect._layer_for_life import with_layer
from pyfect.context import Context
from pyfect.effect import context, die, gen
from pyfect.http._in_memory import client as in_memory_client
from pyfect.http.router import to_http_effect
from pyfect.http.server_response import HttpServerResponse
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
    return with_layer(lambda: _groups(api_of(api), served, base_url), layer)


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
        http_client = in_memory_client(handler, scope)
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


__all__ = ["groups"]
