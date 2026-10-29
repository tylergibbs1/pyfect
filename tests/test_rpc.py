"""RPC behaviours Effect's tests do not pin, checked against its source."""

import asyncio
import json
from typing import Any

import pyfect as fx
from pyfect import effect, layer, stream, testing
from pyfect import schema as S
from pyfect.http import router
from pyfect.http.web import WebRequest
from pyfect.rpc import RpcClientDefect, RpcClientError, RpcGroup, RpcMiddleware, make, rpc_schema
from pyfect.rpc import client as rpc_client
from pyfect.rpc import serialization as rs
from pyfect.rpc import server as rpc_server
from pyfect.rpc.client import ClientOptions
from pyfect.rpc.middleware import MiddlewareOptions, SuccessValue
from pyfect.socket import Reader, Socket, Writer
from pyfect.socket import make as socket_make
from pyfect.tracer import CurrentTracer, NativeSpan, SpanRequest, Tracer


class Echo(RpcGroup):
    ping = make("Ping", success=S.String)


def test_the_server_span_links_the_span_the_request_was_written_in() -> None:
    """Effect's server span: a child of the client's span, linked to the
    span of the fiber that wrote the request (``links: [{ span: parentSpan }]``)."""
    spans: list[NativeSpan] = []

    def span(request: SpanRequest) -> NativeSpan:
        made = NativeSpan(request)
        spans.append(made)
        return made

    def body():
        cores: list[rpc_client.ClientCore] = []
        server = yield from rpc_server.make_no_serialization(
            Echo,
            lambda response: cores[0].write(response),  # noqa: PLW0108 (made below)
        )
        client, core = yield from rpc_client.make_no_serialization(
            Echo, lambda sent: server.write(0, sent.message), ClientOptions()
        )
        cores.append(core)
        return (yield from client.ping())

    handlers = Echo.to_layer(Echo.handlers().handle(Echo.ping)(lambda _: effect.succeed("pong")))
    program = (
        fx.scoped(effect.gen(body))
        .pipe(fx.provide(handlers))
        .pipe(effect.provide_service(CurrentTracer, Tracer.make(span)))
    )
    assert fx.run_sync(program.timeout(10).or_die()) == "pong"
    (client,) = [span for span in spans if span.kind == "client"]
    (server,) = [span for span in spans if span.kind == "server"]
    assert [link.span for link in server.links] == [client]
    assert server.parent is not None
    assert server.parent.span_id == client.span_id


class Opaque(RpcMiddleware, key="Opaque"):
    pass


class Events(RpcGroup):
    events = make("Events", success=rpc_schema.Stream(S.String, S.Never)).middleware(Opaque)


def _opaque(eff: Any, _options: MiddlewareOptions) -> Any:
    """A middleware passing on its own success value, as Effect's may."""
    return eff.as_(SuccessValue())


def test_a_stream_rpc_ends_whatever_value_its_middleware_succeeds_with() -> None:
    """Effect encodes the end of a stream with ``Schema.Void``, so any value
    a middleware succeeds with ends it."""
    handlers = Events.to_layer(
        Events.handlers().handle(Events.events)(lambda _: stream.make("a", "b"))
    )
    app = (
        rpc_server.layer_http(Events, path="/rpc", protocol="http")
        .pipe(layer.provide(handlers))
        .pipe(layer.provide(layer.succeed(Opaque, _opaque)))
        .pipe(layer.provide(rs.layer_ndjson))
    )

    async def main() -> list[Any]:
        made = router.to_web_handler(app, disable_logger=True)
        try:
            request = '{"_tag":"Request","id":1,"tag":"Events","payload":null,"headers":[]}\n'
            response = await made.handler(
                WebRequest("http://test/rpc", method="POST", body=request)
            )
            return [json.loads(line) for line in (await response.text()).splitlines()]
        finally:
            await made.dispose()

    assert asyncio.run(main()) == [
        {"_tag": "Chunk", "requestId": 1, "values": ["a", "b"]},
        {"_tag": "Exit", "requestId": 1, "exit": {"_tag": "Success", "value": None}},
    ]


class Pings(RpcGroup):
    events = make("Events", success=rpc_schema.Stream(S.String, S.Never))


@testing.effect
def test_a_socket_connection_defect_fails_the_calls_in_flight():
    """Effect's socket protocol taps every cause of a connection, so a
    defect (here in ``onConnect``) fails the calls waiting with an
    ``RpcClientDefect`` instead of leaving them waiting."""
    socket = socket_make(
        effect.succeed(Reader(effect.never)),
        effect.succeed(Writer(lambda _d: effect.succeed(None), lambda _c: effect.succeed(None))),
    )
    hooks = rpc_client.ConnectionHooksService(
        effect.die(RuntimeError("hook died")), effect.succeed(None)
    )
    protocol = yield from (
        rpc_client.make_protocol_socket()
        .pipe(effect.provide_service(Socket, socket))
        .pipe(effect.provide_service(rpc_client.ConnectionHooks, hooks))
        .pipe(fx.provide(rs.layer_ndjson))
    )
    client = yield from rpc_client.make(Pings).pipe(
        effect.provide_service(rpc_client.ClientProtocol, protocol)
    )
    error = yield from client.events().run_drain().flip()
    assert isinstance(error, RpcClientError)
    assert isinstance(error.reason, RpcClientDefect)
    assert error.reason.message == "Unknown socket error"
