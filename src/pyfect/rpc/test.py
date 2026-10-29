"""An in-memory client of a group's handlers (Effect's ``RpcTest``)."""

from __future__ import annotations

from typing import Never

from pyfect._core import Effect
from pyfect.effect import gen
from pyfect.rpc.client._core import ClientCore, OnFromClient
from pyfect.rpc.client._core import make_no_serialization as make_client_core
from pyfect.rpc.group import HandlersFor, RpcGroup
from pyfect.rpc.message import FromServer
from pyfect.rpc.server._core import ServerOptions
from pyfect.rpc.server._core import make_no_serialization as make_server_core
from pyfect.scope import Scope


def make_client[G: RpcGroup](
    group: type[G], *, disable_fatal_defects: bool = False
) -> Effect[G, Never, Scope | HandlersFor[G]]:
    """A client of ``group`` calling its handlers directly, without
    serialization: the handlers (and middleware) come from the context."""
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
