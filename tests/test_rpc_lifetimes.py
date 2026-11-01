"""RPC clients and the protocol or handlers they run on (DOGFOOD trawl 1, 2).

``rpc_client.make(G).pipe(provide(protocol))`` releases the protocol, and its
WebSocket, once the client is made. Effect 4.0.7 then waits forever on every
call (checked under Node: a pending call and a new one both time out);
pyfect fails them with an ``RpcClientError`` saying the protocol is closed.
``make(G, layer=protocol)`` and ``rpc_test.make_client(G, layer=handlers)``
build the layer into the caller's scope, so it lives as long as the client.
"""

# pyright: reportUnknownLambdaType=false, reportUnknownMemberType=false
# pyright: reportUnknownVariableType=false, reportUnknownArgumentType=false

from pathlib import Path
from typing import Any, Never, cast

import pyfect as fx
from pyfect import effect, layer, scope
from pyfect import schema as S
from pyfect.cause import Interrupted
from pyfect.exit import Failure
from pyfect.fiber_map import FiberMap
from pyfect.http import router, server, uvicorn_server
from pyfect.queue import Queue
from pyfect.rpc import RpcGroup, RpcRequest, make, serialization
from pyfect.rpc import client as rpc_client
from pyfect.rpc import server as rpc_server
from pyfect.rpc import test as rpc_test
from pyfect.rpc.client_error import RpcClientError
from pyfect.scope import CloseableScope
from pyfect.socket import Reader, Socket, Writer, ws
from pyfect.socket import make as socket_make
from pyfect.sql import sqlite
from pyfect.sql.client import SqlClient
from pyfect.sql.error import SqlError

CLOSED = "the RPC client protocol is closed"


class Calls(RpcGroup):
    ping = make("Ping", success=S.String)
    hang = make("Hang", success=S.String)


CallsLive = Calls.to_layer(
    Calls.handlers()
    .handle(Calls.ping)(lambda _r: fx.succeed("pong"))
    .handle(Calls.hang)(lambda _r: fx.never)
)


def _serve(program: fx.Effect[Any, Any, Any]) -> Any:
    """Run ``program`` with ``Calls`` served over a WebSocket on a free port."""
    live = (
        rpc_server.layer_http(Calls, path="/rpc")
        .pipe(layer.provide(CallsLive))
        .pipe(layer.provide(serialization.layer_json))
    )
    served = router.serve(live, disable_logger=True, disable_listen_log=True)
    return fx.run_sync(
        fx.scoped(program)
        .pipe(fx.provide(served))
        .pipe(fx.provide(uvicorn_server.layer(host="127.0.0.1")))
        .or_die()
    )


def _web_socket_protocol() -> fx.Effect[Any, Never, Any]:
    def protocol(origin: str) -> fx.Effect[Any]:
        url = origin.replace("http://", "ws://") + "/rpc"
        return fx.succeed(
            rpc_client.layer_protocol_socket()
            .pipe(layer.provide(ws.layer_web_socket(url)))
            .pipe(layer.provide(serialization.layer_json))
        )

    return server.address_formatted_with(protocol)


def _rpc_client_error(exit_: object) -> RpcClientError:
    assert isinstance(exit_, Failure), exit_
    error = exit_.cause.squash()
    assert isinstance(error, RpcClientError), exit_.cause
    return error


def test_a_call_on_a_client_whose_web_socket_was_released_fails_at_once() -> None:
    @fx.fn
    def program():
        protocol = yield from _web_socket_protocol()
        client = yield from rpc_client.make(Calls).pipe(fx.provide(protocol))
        return (yield from client.ping().timeout(5).exit())

    error = _rpc_client_error(_serve(program()))
    assert CLOSED in error.message


def test_the_protocol_given_to_make_lives_as_long_as_the_client() -> None:
    @fx.fn
    def program():
        protocol = yield from _web_socket_protocol()
        client = yield from rpc_client.make(Calls, layer=protocol)
        first = yield from client.ping()
        second = yield from client.ping()
        return first, second

    assert _serve(program()) == ("pong", "pong")


def test_a_call_waiting_when_the_protocol_closes_fails() -> None:
    """The protocol's scope closes under a call the server never answers."""

    @fx.fn
    def program():
        protocol = yield from _web_socket_protocol()
        protocol_scope = CloseableScope()
        built = yield from protocol.build().pipe(fx.provide_service(scope.Scope, protocol_scope))
        client = yield from rpc_client.make(Calls).pipe(fx.provide_context(built))
        waiting = yield from client.hang().timeout(5).exit().fork()
        yield from client.ping()  # the hang request went out before it
        yield from protocol_scope.close(fx.exit.succeed(None))
        return (yield from waiting.join())

    error = _rpc_client_error(_serve(program()))
    assert CLOSED in error.message


def test_a_call_waiting_on_a_socket_protocol_whose_scope_closes_fails() -> None:
    """The same without a server: a socket that never answers."""

    @fx.fn
    def program():
        frames = yield from Queue[str].unbounded()
        sent = yield from Queue[object].unbounded()
        socket = socket_make(
            effect.succeed(Reader(frames.take().map(lambda frame: (frame,)))),
            effect.succeed(
                Writer(
                    lambda data: sent.offer(data).as_void(),
                    lambda chunks: sent.offer(chunks[0]).as_void(),
                )
            ),
        )
        protocol = (
            rpc_client.layer_protocol_socket()
            .pipe(layer.provide(serialization.layer_json))
            .pipe(layer.provide(layer.succeed(Socket, socket)))
        )
        protocol_scope = CloseableScope()
        built = yield from protocol.build().pipe(fx.provide_service(scope.Scope, protocol_scope))
        client = yield from rpc_client.make(Calls).pipe(fx.provide_context(built))
        waiting = yield from client.hang().timeout(5).exit().fork()
        yield from sent.take()
        yield from protocol_scope.close(fx.exit.succeed(None))
        return (yield from waiting.join())

    error = _rpc_client_error(fx.run_sync(fx.scoped(program())))
    assert CLOSED in error.message


# --- the in-memory client over handlers on a scoped layer (trawl 2) ---------------------


class Jobs(RpcGroup):
    start = make("Start", payload=S.String, success=S.Int, error=SqlError)


class Workers(fx.Tag[FiberMap[str, None, Never]]): ...


@fx.fn
def _start(request: RpcRequest[str]):
    workers = yield from Workers()
    yield from workers.run(request.payload, fx.never)
    sql = yield from SqlClient()
    yield from sql("INSERT INTO jobs (name) VALUES ({})", request.payload)
    rows = yield from sql("SELECT count(*) AS n FROM jobs")
    return cast("int", rows[0]["n"])


def _jobs_live(tmp_path: Path) -> fx.Layer[Any, Any, Any]:
    database = sqlite.layer(sqlite.SqliteClientConfig(filename=str(tmp_path / "jobs.db")))

    @fx.fn
    def migrate():
        sql = yield from SqlClient()
        yield from sql("CREATE TABLE jobs (name TEXT)")

    services = layer.merge(
        layer.effect(Workers, FiberMap[str, None, Never].make()),
        layer.effect_discard(migrate()),
    ).pipe(layer.provide_merge(database))
    return Jobs.to_layer(Jobs.handlers().handle(Jobs.start)(_start)).pipe(layer.provide(services))


def test_make_client_keeps_a_scoped_handlers_layer_open_while_the_client_is_used(
    tmp_path: Path,
) -> None:
    @fx.fn
    def program():
        client = yield from rpc_test.make_client(Jobs, layer=_jobs_live(tmp_path))
        first = yield from client.start("a")
        second = yield from client.start("b")
        return first, second

    assert fx.run_sync(fx.scoped(program()).or_die()) == (1, 2)


def test_handlers_provided_to_make_client_alone_name_what_was_released(tmp_path: Path) -> None:
    """As in Effect the layer is released once the client is made; the
    handler's first use of it, the closed ``FiberMap``, says so (a released
    SQLite client fails with an ``SqlError``: test_use_after_release.py)."""

    @fx.fn
    def program():
        client = yield from rpc_test.make_client(Jobs).pipe(fx.provide(_jobs_live(tmp_path)))
        return (yield from client.start("a").timeout(5).exit())

    exit_ = fx.run_sync(fx.scoped(program()))
    assert isinstance(exit_, Failure), exit_
    error = exit_.cause.squash()
    assert isinstance(error, Interrupted), exit_.cause
    assert "the FiberMap is closed" in "\n".join(error.__notes__)
