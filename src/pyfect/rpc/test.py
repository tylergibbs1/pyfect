"""An in-memory client of a group's handlers (Effect's ``RpcTest``).

``make_client(Group, layer=GroupLive)`` builds the handlers' layer into the
caller's ``Scope``, so the handlers' resources (a database, forked workers)
stay open while the client is used::

    client = yield from rpc_test.make_client(Todos, layer=TodosLive)

Without ``layer`` the handlers come from the context, which must then
outlive the client: a layer provided to ``make_client(...)`` alone is
released once the client is made, as in Effect.
"""

from __future__ import annotations

from typing import Any, Never, overload

from pyfect._core import Effect
from pyfect._layer_core import Layer
from pyfect._layer_for_life import with_layer
from pyfect.effect import gen
from pyfect.rpc.client._core import ClientCore, OnFromClient
from pyfect.rpc.client._core import make_no_serialization as make_client_core
from pyfect.rpc.group import HandlersFor, RpcGroup
from pyfect.rpc.message import FromServer
from pyfect.rpc.server._core import ServerOptions
from pyfect.rpc.server._core import make_no_serialization as make_server_core
from pyfect.scope import Scope


@overload
def make_client[G: RpcGroup](
    group: type[G], *, disable_fatal_defects: bool = False
) -> Effect[G, Never, Scope | HandlersFor[G]]: ...
@overload
def make_client[G: RpcGroup, E, R](
    group: type[G], *, layer: Layer[HandlersFor[G], E, R], disable_fatal_defects: bool = False
) -> Effect[G, E, R | Scope]: ...
def make_client(
    group: type[RpcGroup],
    *,
    layer: Layer[Any, Any, Any] | None = None,
    disable_fatal_defects: bool = False,
) -> Effect[Any, Any, Any]:
    """A client of ``group`` calling its handlers directly, without
    serialization. The handlers (and middleware) are ``layer``, built into
    the caller's ``Scope``, or else come from the context; the client is
    valid until that scope closes."""
    return with_layer(lambda: _make_client(group, disable_fatal_defects), layer)


def _make_client(group: type[RpcGroup], disable_fatal_defects: bool) -> Effect[Any, Never, Any]:
    cores: list[ClientCore] = []

    def on_from_server(response: FromServer) -> Effect[None]:
        return cores[0].write(response)

    @gen
    def make():
        server = yield from make_server_core(
            group, on_from_server, ServerOptions(disable_fatal_defects=disable_fatal_defects)
        )

        def on_from_client(sent: OnFromClient) -> Effect[None]:
            return server.write(0, sent.message)

        client, core = yield from make_client_core(group, on_from_client)
        cores.append(core)
        return client

    return make


__all__ = ["make_client"]
