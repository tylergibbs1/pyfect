"""uvicorn_server under ``run_blocking`` runs uvicorn on a loop thread, and request fibers run
on that loop. Fibers a request starts into a longer scope (a pool's connection, an eventlog
connection's subscriptions) must still be interrupted cleanly once the server has stopped
and been released (dogfood quill #1: ``Die(RuntimeError('Event loop is closed'))`` twice, or
a hang). The loop is shared by such servers and never stopped."""

from __future__ import annotations

from typing import Any, TypedDict

import pyfect as fx
from pyfect import layer
from pyfect import schema as S
from pyfect.ai import mcp_client, mcp_protocol, mcp_server, tool, toolkit
from pyfect.ai.mcp_client import McpClientService
from pyfect.ai.mcp_client_error import McpClientError
from pyfect.eventlog import event_group, event_journal, event_log, event_log_remote
from pyfect.eventlog import event_log_server_encrypted as eventlog_server
from pyfect.eventlog.event_log_encryption import layer_subtle
from pyfect.http import router, server_response, uvicorn_server
from pyfect.http import server as http_server
from pyfect.http.client import HttpClient
from pyfect.rc_map import RcMap
from pyfect.rpc import client as rpc_client
from pyfect.rpc import serialization
from pyfect.rpc import server as rpc_server
from pyfect.scope import CloseableScope, Scope, acquire_release, fork_in
from pyfect.socket import ws


class Background(fx.Tag[CloseableScope], key="test/uvicorn/Background"): ...


background = layer.effect(Background, Scope())


def _routes(finalized: list[str]) -> fx.Layer[Any, Any, Any]:
    def start() -> fx.Effect[Any, Any, Background]:
        lingering = fx.never.ensuring(fx.sync(lambda: finalized.append("done")))
        return Background().flat_map(lambda scope: fork_in(lingering, scope))

    return router.add("GET", "/", start().as_(server_response.text("ok")))


@fx.fn
def _get():
    client = yield from HttpClient()
    response = yield from client.get("/")
    return (yield from response.text)


def test_a_fiber_a_request_left_in_a_scope_closed_after_serving_is_interrupted() -> None:
    finalized: list[str] = []
    served = router.serve(_routes(finalized), disable_logger=True).pipe(
        layer.provide_merge(background)
    )
    app = served.pipe(layer.provide_merge(uvicorn_server.layer_test()))
    assert fx.run_blocking_exit(_get().pipe(fx.provide(app))) == fx.Success("ok")
    assert finalized == ["done"]


# Released between the server and what outlives it: the server is gone by then.
server_gone: list[bool] = []
mark_server_gone = layer.effect_discard(
    acquire_release(fx.void, lambda _a, _e: fx.sync(lambda: server_gone.append(True)))
)


def test_a_fiber_a_request_left_in_a_scope_that_outlives_the_server_is_interrupted() -> None:
    finalized: list[str] = []
    served = router.serve(_routes(finalized), disable_logger=True)
    server = (
        uvicorn_server.layer_test()
        .pipe(layer.provide_merge(mark_server_gone))
        .pipe(layer.provide_merge(background))
    )
    app = served.pipe(layer.provide_merge(server))
    server_gone.clear()
    assert fx.run_blocking_exit(_get().pipe(fx.provide(app))) == fx.Success("ok")
    assert finalized == ["done"]
    assert server_gone == [True]


def test_an_encrypted_eventlog_server_shuts_down_cleanly_after_a_client_connected() -> None:
    protocol = rpc_server.layer_protocol_websocket("/sync").pipe(
        layer.provide(serialization.layer_ndjson)
    )
    routes = eventlog_server.layer.pipe(
        layer.provide(layer.merge(protocol, eventlog_server.layer_storage_memory))
    )
    served = router.serve(routes, disable_logger=True, disable_listen_log=True).pipe(
        layer.provide_merge(uvicorn_server.layer_test())
    )

    def client(url: str):
        identity = layer.effect(
            event_log.Identity, event_log.make_identity.pipe(fx.provide(layer_subtle))
        )
        handlers = event_log.group(event_group.empty, lambda h: h)
        log = event_log.layer(event_log.schema(event_group.empty), handlers).pipe(
            layer.provide(layer.merge(event_journal.layer_memory, identity))
        )
        socket = rpc_client.layer_protocol_socket().pipe(
            layer.provide(layer.merge(ws.layer_web_socket(url), serialization.layer_ndjson))
        )
        return event_log_remote.layer_encrypted.pipe(layer.provide(socket)).pipe(
            layer.provide_merge(log)
        )

    @fx.fn
    def connect():
        url = yield from http_server.address_formatted_with(
            lambda a: fx.succeed(a.replace("http://", "ws://") + "/sync")
        )
        yield from fx.scoped(fx.sleep("300 millis")).pipe(fx.provide(client(url)))

    assert fx.run_blocking_exit(fx.scoped(connect()).pipe(fx.provide(served))) == fx.Success(None)


class _AddParams(TypedDict):
    a: int
    b: int


class _Sum(TypedDict):
    total: int


def test_a_pooled_client_connection_open_at_shutdown_is_closed_cleanly() -> None:
    add = tool.make("add", parameters=S.Struct(_AddParams), success=S.Struct(_Sum))
    calculator = toolkit.make(add)
    handlers = calculator.to_layer(
        add.handler(lambda p, _: fx.succeed(_Sum(total=p["a"] + p["b"])))
    )
    mcp = mcp_server.layer_http(
        name="calculator",
        version="1.0.0",
        path="/mcp",
        protocols=(mcp_protocol.v2025_11_25,),
        registrations=mcp_server.toolkit(calculator).pipe(layer.provide(handlers)),
    )

    class Clients(fx.Tag[RcMap[str, McpClientService, McpClientError]], key="test/Clients"): ...

    def connect(url: str):
        return mcp_client.http(url=url, protocol=mcp_protocol.v2025_11_25).flat_map(
            lambda t: mcp_client.make(name="test", version="0").pipe(
                fx.provide_service(mcp_client.Transport, t)
            )
        )

    @fx.fn
    def total():
        pool = yield from Clients()
        mcp_conn = yield from pool.get("/mcp")
        (listed,) = yield from mcp_conn.list_tools()
        summed = yield from mcp_conn.call_tool(listed, {"a": 2, "b": 3}, schema=S.Struct(_Sum))
        return summed["total"]

    route = router.use(
        lambda r: r.add("GET", "/", fx.scoped(total()).map(lambda n: server_response.text(str(n))))
    )
    # The pool keeps the connection a minute: it is still open when the server stops.
    pool = layer.effect(Clients, RcMap.make(connect, idle_time_to_live="1 minute"))
    served = router.serve(
        layer.merge(mcp, route), disable_logger=True, disable_listen_log=True
    ).pipe(layer.provide_merge(pool))
    app = served.pipe(layer.provide_merge(uvicorn_server.layer_test()))
    assert fx.run_blocking_exit(_get().pipe(fx.provide(app))) == fx.Success("5")
