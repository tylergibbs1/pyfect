"""Reuse cases for the RPC and worker layers: each is one part of a client
and server talking over a real transport (HTTP and WebSocket on a loopback
server, TCP, a worker thread), the subject in its place and every other
part made afresh for the run."""

# pyright: reportUnknownLambdaType=false, reportUnknownMemberType=false
# pyright: reportUnknownVariableType=false, reportUnknownArgumentType=false

from dataclasses import replace
from typing import Any, Never

import pyfect as fx
from layer_cases._case import AnyEffect, AnyLayer, Case
from pyfect import layer as L
from pyfect import schema as S
from pyfect import sink, stdio, stream
from pyfect.context import Tag
from pyfect.http import router, uvicorn_server
from pyfect.http.server import HttpServer
from pyfect.rpc import RpcGroup, RpcRequest, make
from pyfect.rpc import client as rpc_client
from pyfect.rpc import group as rpc_group
from pyfect.rpc import middleware as rpc_middleware
from pyfect.rpc import serialization as rs
from pyfect.rpc import server as rpc_server
from pyfect.rpc import test as rpc_test
from pyfect.rpc import worker as rpc_worker
from pyfect.socket import layer_net, ws
from pyfect.socket import server as socket_server
from pyfect.socket.server import SocketServer
from pyfect.workers import ThreadWorker, python_worker, python_worker_runner
from pyfect.workers import worker as workers


class Greeting(Tag[str], key="layer_cases/rpc/Greeting"):
    pass


class Stamp(rpc_middleware.RpcMiddleware[Greeting, Never], key="layer_cases/rpc/Stamp"):
    """Reads the ``greeting`` header the client side of ``Stamp`` sets."""


class Echo(RpcGroup):
    echo = make("Echo", payload=S.String, success=S.String)
    greet = make("Greet", success=S.String).middleware(Stamp)
    initial = make("Initial", success=S.String)


def _stamp(eff: Any, options: rpc_middleware.MiddlewareOptions) -> Any:
    return eff.pipe(fx.provide_service(Greeting, options.headers.get("greeting", "none")))


def _stamp_client(options: rpc_middleware.ClientMiddlewareOptions) -> Any:
    request = options.request
    return options.next(replace(request, headers=request.headers.set("greeting", "hello")))


def _handlers() -> AnyLayer:
    return Echo.to_layer(
        Echo.handlers()
        .handle(Echo.echo)(_echo)
        .handle(Echo.greet)(lambda _: Greeting())
        .handle(Echo.initial)(lambda _: rpc_worker.initial_message(S.String).or_die())
    ).pipe(L.provide_merge(L.succeed(Stamp, _stamp)))


def _echo(request: RpcRequest[str]) -> fx.Effect[str]:
    return fx.succeed(request.payload)


def _expect(found: object, wanted: object) -> AnyEffect:
    if found == wanted:
        return fx.void
    return fx.die(AssertionError(f"expected {wanted!r}, got {found!r}"))


def _call(client: Any) -> AnyEffect:
    return client.echo("hi").flat_map(lambda reply: _expect(reply, "hi"))


def _call_through(protocol: AnyLayer | None = None) -> AnyEffect:
    made = rpc_client.make(Echo) if protocol is None else rpc_client.make(Echo, layer=protocol)
    return made.flat_map(_call)


# --- HTTP and WebSocket on a loopback server ------------------------------------------


def _http_client_protocol() -> AnyLayer:
    def append_rpc(client: Any) -> Any:
        return client.map_request(lambda request: request.append_url("/rpc"))

    return rpc_client.layer_protocol_http("", transform_client=append_rpc)


def _server_app(server_protocol: AnyLayer | None = None) -> AnyLayer:
    protocol = (
        rpc_server.layer_protocol_http("/rpc") if server_protocol is None else server_protocol
    )
    return rpc_server.layer(Echo).pipe(L.provide(protocol))


def _over_http(
    *,
    client: AnyLayer | None = None,
    app: AnyLayer | None = None,
    handlers: AnyLayer | None = None,
    serialization: AnyLayer | None = None,
    program: AnyEffect | None = None,
) -> AnyEffect:
    """``program`` (one call) through ``client`` to ``app`` served on a
    loopback server: by default the HTTP protocol on both ends."""
    served = router.serve(
        (_server_app() if app is None else app).pipe(
            L.provide(_handlers() if handlers is None else handlers)
        ),
        disable_logger=True,
        disable_listen_log=True,
    )
    protocol = _http_client_protocol() if client is None else client
    stack = (
        protocol.pipe(L.provide_merge(served))
        .pipe(L.provide(uvicorn_server.layer_test()))
        .pipe(L.provide(rs.layer_json if serialization is None else serialization))
    )
    return (_call_through() if program is None else program).pipe(fx.provide(stack))


def _on_web_socket(protocol: AnyLayer) -> AnyLayer:
    """``protocol`` over a WebSocket to the loopback server's ``/rpc``."""

    def socket(server: Any) -> AnyLayer:
        return ws.layer_web_socket(f"ws://127.0.0.1:{server.address.port}/rpc")

    return protocol.pipe(L.provide(L.unwrap(HttpServer().map(socket))))


def _over_web_socket(
    *,
    client: AnyLayer | None = None,
    app: AnyLayer | None = None,
    serialization: AnyLayer | None = None,
) -> AnyEffect:
    return _over_http(
        client=_on_web_socket(rpc_client.layer_protocol_socket() if client is None else client),
        app=_server_app(rpc_server.layer_protocol_websocket("/rpc")) if app is None else app,
        serialization=serialization,
    )


# --- TCP -------------------------------------------------------------------------------


def _over_tcp(*, server_protocol: AnyLayer | None = None) -> AnyEffect:
    def socket(server: Any) -> AnyLayer:
        return layer_net(server.address.port, "127.0.0.1")

    protocol = (
        rpc_server.layer_protocol_socket_server if server_protocol is None else server_protocol
    )
    server = (
        rpc_server.layer(Echo)
        .pipe(L.provide(_handlers()))
        .pipe(L.provide_merge(protocol))
        .pipe(L.provide_merge(socket_server.layer(0, "127.0.0.1")))
    )
    client = rpc_client.layer_protocol_socket().pipe(
        L.provide(L.unwrap(SocketServer().map(socket)))
    )
    stack = client.pipe(L.provide_merge(server)).pipe(L.provide(rs.layer_json))
    return _call_through().pipe(fx.provide(stack))


# --- a worker thread -------------------------------------------------------------------


def _worker_main(runner: AnyLayer, platform: AnyLayer) -> None:
    main = (
        rpc_server.layer(Echo)
        .pipe(L.provide(_handlers()))
        .pipe(L.provide(runner))
        .pipe(L.provide(platform))
    )
    fx.run_blocking_exit(main.launch())


def _thread_workers(runner: AnyLayer | None = None, platform: AnyLayer | None = None) -> Any:
    chosen_runner = rpc_server.layer_protocol_worker_runner if runner is None else runner
    chosen_platform = python_worker_runner.layer if platform is None else platform
    return lambda _id: ThreadWorker(lambda: _worker_main(chosen_runner, chosen_platform))


def _over_stdio(protocol: AnyLayer) -> AnyEffect:
    """One ``Ping`` on stdin; the server ends once its ``Pong`` is written."""
    lines: list[bytes] = []

    def stdout(*, end_on_done: bool = False) -> Any:
        def write(data: str | bytes) -> AnyEffect:
            return fx.sync(lambda: lines.append(data if isinstance(data, bytes) else data.encode()))

        return sink.for_each(write)

    server = (
        rpc_server.layer(Echo)
        .pipe(L.provide(_handlers()))
        .pipe(L.provide(protocol))
        .pipe(L.provide(rs.layer_ndjson))
        .pipe(L.provide(stdio.layer_test(stdin=stream.make(b'{"_tag":"Ping"}\n'), stdout=stdout)))
    )

    @fx.fn
    def body():
        fiber = yield from server.launch().fork()
        yield from fiber.await_exit()
        assert lines == [b'{"_tag":"Pong"}\n']

    return body()


def _over_worker(
    *,
    client: AnyLayer | None = None,
    workers_layer: AnyLayer | None = None,
    initial: AnyLayer | None = None,
    program: AnyEffect | None = None,
) -> AnyEffect:
    protocol = rpc_client.layer_protocol_worker(size=1) if client is None else client
    stack = protocol.pipe(
        L.provide(
            rpc_worker.layer_initial_message(S.String, fx.succeed("hello"))
            if initial is None
            else initial
        )
    ).pipe(
        L.provide(
            python_worker.layer(_thread_workers()) if workers_layer is None else workers_layer
        )
    )
    return (_call_through() if program is None else program).pipe(fx.provide(stack))


def _initial_through_worker() -> AnyEffect:
    return rpc_client.make(Echo).flat_map(
        lambda client: client.initial().flat_map(lambda reply: _expect(reply, "hello"))
    )


# --- in memory -------------------------------------------------------------------------


def _in_memory(program: Any) -> AnyEffect:
    return rpc_test.make_client(Echo).flat_map(program)


def _greet(client: Any) -> AnyEffect:
    return client.greet().flat_map(lambda reply: _expect(reply, "hello"))


class Plain(RpcGroup):
    echo = make("Echo", payload=S.String, success=S.String)


def _greeting_client(value: AnyLayer) -> AnyEffect:
    return (
        rpc_test.make_client(Echo)
        .flat_map(_greet)
        .pipe(fx.provide(_handlers().pipe(L.provide_merge(value))))
    )


CASES: dict[str, Case] = {
    "pyfect.rpc.client.layer_protocol_http": Case(
        layer=_http_client_protocol,
        run=lambda value: _over_http(client=value),
    ),
    "pyfect.rpc.client.layer_protocol_socket": Case(
        layer=rpc_client.layer_protocol_socket,
        run=lambda value: _over_web_socket(client=value),
    ),
    "pyfect.rpc.client.layer_protocol_worker": Case(
        layer=lambda: rpc_client.layer_protocol_worker(size=1),
        run=lambda value: _over_worker(client=value),
    ),
    "pyfect.rpc.server.layer": Case(
        layer=lambda: rpc_server.layer(Echo),
        run=lambda value: _over_http(
            app=value.pipe(L.provide(rpc_server.layer_protocol_http("/rpc")))
        ),
    ),
    "pyfect.rpc.server.layer_http": Case(
        layer=lambda: rpc_server.layer_http(Echo, path="/rpc"),
        run=lambda value: _over_web_socket(app=value),
    ),
    "pyfect.rpc.server.layer_protocol_http": Case(
        layer=lambda: rpc_server.layer_protocol_http("/rpc"),
        run=lambda value: _over_http(app=_server_app(value)),
    ),
    "pyfect.rpc.server.layer_protocol_websocket": Case(
        layer=lambda: rpc_server.layer_protocol_websocket("/rpc"),
        run=lambda value: _over_web_socket(app=_server_app(value)),
    ),
    "pyfect.rpc.server.layer_protocol_socket_server": Case(
        layer=lambda: rpc_server.layer_protocol_socket_server,
        run=lambda value: _over_tcp(server_protocol=value),
    ),
    "pyfect.rpc.server.layer_protocol_stdio": Case(
        layer=lambda: rpc_server.layer_protocol_stdio,
        run=_over_stdio,
    ),
    "pyfect.rpc.server.layer_protocol_worker_runner": Case(
        layer=lambda: rpc_server.layer_protocol_worker_runner,
        run=lambda value: _over_worker(workers_layer=python_worker.layer(_thread_workers(value))),
    ),
    "pyfect.workers.python_worker_runner.layer": Case(
        layer=lambda: python_worker_runner.layer,
        run=lambda value: _over_worker(
            workers_layer=python_worker.layer(_thread_workers(platform=value))
        ),
    ),
    "pyfect.workers.python_worker.layer": Case(
        layer=lambda: python_worker.layer(_thread_workers()),
        run=lambda value: _over_worker(workers_layer=value),
    ),
    "pyfect.workers.python_worker.layer_platform": Case(
        layer=lambda: python_worker.layer_platform,
        run=lambda value: _over_worker(
            workers_layer=L.merge(value, workers.layer_spawner(_thread_workers()))
        ),
    ),
    "pyfect.workers.layer_spawner": Case(
        layer=lambda: workers.layer_spawner(_thread_workers()),
        run=lambda value: _over_worker(workers_layer=L.merge(python_worker.layer_platform, value)),
    ),
    "pyfect.rpc.worker.layer_initial_message": Case(
        layer=lambda: rpc_worker.layer_initial_message(S.String, fx.succeed("hello")),
        run=lambda value: _over_worker(initial=value, program=_initial_through_worker()),
    ),
    "pyfect.rpc.serialization.layer_json": Case(
        layer=lambda: rs.layer_json,
        run=lambda value: _over_web_socket(serialization=value),
    ),
    "pyfect.rpc.serialization.layer_ndjson": Case(
        layer=lambda: rs.layer_ndjson,
        run=lambda value: _over_web_socket(serialization=value),
    ),
    "pyfect.rpc.serialization.layer_ndjson_with": Case(
        layer=lambda: rs.layer_ndjson_with(max_buffer_size=1 << 20),
        run=lambda value: _over_web_socket(serialization=value),
    ),
    "pyfect.rpc.serialization.layer_schema_binary": Case(
        layer=rs.layer_schema_binary,
        run=lambda value: _over_web_socket(serialization=value),
    ),
    "pyfect.rpc.serialization.layer_json_rpc": Case(
        layer=rs.layer_json_rpc,
        run=lambda value: _over_http(serialization=value),
    ),
    "pyfect.rpc.serialization.layer_nd_json_rpc": Case(
        layer=rs.layer_nd_json_rpc,
        run=lambda value: _over_web_socket(serialization=value),
    ),
    "pyfect.rpc.RpcGroup.to_layer": Case(layer=_handlers, use=lambda: _in_memory(_call)),
    "pyfect.rpc.RpcGroup.to_layer_effect": Case(
        layer=lambda: Echo.to_layer_effect(
            fx.sync(
                lambda: (
                    Echo.handlers()
                    .handle(Echo.echo)(_echo)
                    .handle(Echo.greet)(lambda _: fx.succeed("unused"))
                    .handle(Echo.initial)(lambda _: fx.succeed("unused"))
                )
            )
        ),
        use=lambda: _in_memory(_call),
    ),
    "pyfect.rpc.group.to_layer_handler": Case(
        layer=lambda: rpc_group.to_layer_handler(Plain.echo, _echo),
        use=lambda: rpc_test.make_client(Plain).flat_map(_call),
    ),
    "pyfect.rpc.middleware.layer_client": Case(
        layer=lambda: rpc_middleware.layer_client(Stamp, _stamp_client),
        run=_greeting_client,
    ),
    "pyfect.rpc.middleware.layer_client_effect": Case(
        layer=lambda: rpc_middleware.layer_client_effect(Stamp, fx.sync(lambda: _stamp_client)),
        run=_greeting_client,
    ),
}

SKIPPED: dict[str, str] = {}
