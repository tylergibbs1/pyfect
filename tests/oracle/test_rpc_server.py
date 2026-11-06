"""Ports of Effect's rpc/RpcServer.test.ts, and the "request defect
isolation over HTTP" cases of platform-node's RpcServer.test.ts. Each
test's docstring is the Effect test title, prefixed by its describe block.

A Web handler of the server answers the POSTs (Effect's
``HttpEffect.toWebHandler``).

Omitted:
- "finalizes an aborted ... HTTP RPC before output": aborting the Web
  request of an in-process handler is covered by the web handler tests.
- "decodes payloads with the ParseOptions annotation": pyfect has no
  request resolvers inside schema transformations.
- "closes a socket when the serialization buffer limit is exceeded":
  covered by test_rpc_serialization.py's max buffer size cases.
"""

# pyright: reportUnknownLambdaType=false, reportUnknownMemberType=false
# pyright: reportUnknownVariableType=false, reportUnknownArgumentType=false

import asyncio
import json
from collections.abc import Awaitable, Callable
from typing import Any, TypedDict

import pytest

import pyfect as fx
from pyfect import effect, layer, schedule, stream
from pyfect import error_reporter as ErrorReporter
from pyfect import exit as Exit
from pyfect import schema as S
from pyfect.cause import Die
from pyfect.http import router, uvicorn_server
from pyfect.http.web import WebRequest, WebResponse
from pyfect.layer import Layer
from pyfect.rpc import RpcGroup, RpcMiddleware, make
from pyfect.rpc import client as rpc_client
from pyfect.rpc import serialization as rs
from pyfect.rpc import server as rpc_server
from pyfect.rpc import test as rpc_test
from pyfect.rpc.message import FromServer, Request, ResponseExit
from pyfect.rpc.middleware import SuccessValue
from pyfect.schema import DecodedDefect
from pyfect.tracer import CurrentTracer, Ended, NativeSpan, SpanRequest, Tracer

type Handler = Callable[[WebRequest], Awaitable[WebResponse]]


def _serve(app: Layer[Any, Any, Any], use: Callable[[Handler], Awaitable[None]]) -> None:
    async def main() -> None:
        made = router.to_web_handler(app, disable_logger=True)
        try:
            await use(made.handler)
        finally:
            await made.dispose()

    asyncio.run(main())


def _message(defect: object) -> str:
    """Effect dies with a string; pyfect with a ``DecodedDefect`` of it."""
    assert isinstance(defect, DecodedDefect)
    return str(defect.value)


def _post(body: str) -> WebRequest:
    return WebRequest("http://test/rpc", method="POST", body=body)


def _http(group: type[RpcGroup], handlers: Layer[Any, Any, Any], serialization: Any) -> Any:
    return (
        rpc_server.layer_http(group, path="/rpc", protocol="http")
        .pipe(layer.provide(handlers))
        .pipe(layer.provide(serialization))
    )


class Ping(RpcGroup):
    ping = make("ping", success=S.String)


@pytest.mark.parametrize(
    "serialization",
    [rs.layer_ndjson, rs.layer_nd_json_rpc(), rs.layer_schema_binary()],
    ids=["ndjson", "ndJsonRpc", "schemaBinary"],
)
def test_returns_http_200_with_an_empty_body_for_an_empty_post(serialization: Any) -> None:
    """RpcServer / returns HTTP 200 with an empty body for an empty ${name} POST"""
    handlers = Ping.to_layer(Ping.handlers().handle(Ping.ping)(lambda _: effect.succeed("pong")))

    async def use(handler: Handler) -> None:
        response = await handler(_post(""))
        assert response.status == 200
        assert await response.text() == ""

    _serve(_http(Ping, handlers, serialization), use)


_NOT_A_NUMBER: Any = "not a number"
"""A handler's success that does not match its schema."""


class Empty(TypedDict):
    pass


class Age(RpcGroup):
    get_user_age = make("getUserAge", payload=S.Struct(Empty), success=S.Number)


def test_reports_success_encode_failures_with_the_rpc_tag() -> None:
    """RpcServer / reports success encode failures with the rpc tag"""
    reports: list[str] = []
    handlers = Age.to_layer(
        Age.handlers().handle(Age.get_user_age)(lambda _: effect.succeed(_NOT_A_NUMBER))
    )
    reporter = ErrorReporter.layer(
        [ErrorReporter.make(lambda report: reports.append(_message(report.error)))]
    )
    app = _http(Age, handlers, rs.layer_ndjson).pipe(layer.provide(reporter))

    async def use(handler: Handler) -> None:
        response = await handler(
            _post('{"_tag":"Request","id":1,"tag":"getUserAge","payload":{},"headers":[]}\n')
        )
        body = json.loads(await response.text())
        message = 'Failed to encode response for RPC "getUserAge": Expected number\n  at ["value"]'
        assert body["exit"] == {"_tag": "Failure", "cause": [{"_tag": "Die", "defect": message}]}
        assert reports == [message]

    _serve(app, use)


class Swallow(RpcMiddleware, key="Swallow"):
    pass


class Encodes(RpcGroup):
    get_user_age = make("getUserAge", payload=S.Struct(Empty), success=S.Number)
    ages = make("ages", payload=S.Struct(Empty), success=S.Number, stream=True).middleware(Swallow)


def test_records_effect_and_stream_encode_defects_on_server_spans() -> None:
    """RpcServer / records effect and stream encode defects on server spans, even when middleware swallows them"""  # noqa: E501
    spans: list[NativeSpan] = []

    def span(request: SpanRequest) -> NativeSpan:
        made = NativeSpan(request)
        spans.append(made)
        return made

    handlers = Encodes.to_layer(
        Encodes.handlers()
        .handle(Encodes.get_user_age)(lambda _: effect.succeed(_NOT_A_NUMBER))
        .handle(Encodes.ages)(lambda _: stream.make(_NOT_A_NUMBER))
    )
    swallow = layer.succeed(
        Swallow, lambda eff, _options: eff.catch_defect(lambda _: effect.succeed(SuccessValue()))
    )
    app = (
        _http(Encodes, handlers, rs.layer_ndjson)
        .pipe(layer.provide(swallow))
        .pipe(layer.provide(layer.succeed(CurrentTracer, Tracer.make(span))))
    )

    async def use(handler: Handler) -> None:
        await (
            await handler(
                _post(
                    '{"_tag":"Request","id":1,"tag":"getUserAge","payload":{},"headers":[]}\n'
                    '{"_tag":"Request","id":2,"tag":"ages","payload":{},"headers":[]}\n'
                )
            )
        ).text()

    _serve(app, use)

    def defects(exit: Any) -> list[str]:
        assert isinstance(exit, Exit.Failure)
        return [_message(defect) for defect in exit.cause.defects]

    ended = {
        span.name: span.status.exit
        for span in spans
        if span.kind == "server" and isinstance(span.status, Ended)
    }
    assert {name: defects(exit) for name, exit in ended.items()} == {
        "getUserAge": [
            'Failed to encode response for RPC "getUserAge": Expected number\n  at ["value"]'
        ],
        "ages": ['Failed to encode response for RPC "ages": Expected number\n  at [0]'],
    }


@pytest.mark.parametrize("disable_fatal_defects", [False, True])
def test_rpc_test_handler_defects(disable_fatal_defects: bool) -> None:
    """RpcClient / RpcTest handler defects with disableFatalDefects: ${disableFatalDefects}"""

    class Group(RpcGroup):
        block = make("Block", success=S.String)
        boom = make("Boom")

    def body():
        started = fx.Deferred[None]()
        release = fx.Deferred[None]()
        handlers = Group.to_layer(
            Group.handlers()
            .handle(Group.block)(
                lambda _: started.succeed(None).flat_map(lambda _: release.wait()).as_("ok")
            )
            .handle(Group.boom)(lambda _: effect.die(DecodedDefect("boom")))
        )
        client = yield from rpc_test.make_client(
            Group, disable_fatal_defects=disable_fatal_defects
        ).pipe(fx.provide(handlers))
        blocked = (
            yield from client.block().catch_defect(lambda d: effect.succeed(_message(d))).fork()
        )
        yield from started.wait()
        assert (
            yield from client.boom().catch_defect(lambda d: effect.succeed(_message(d)))
        ) == "boom"
        yield from release.succeed(None)
        assert (yield from blocked.join()) == ("ok" if disable_fatal_defects else "boom")

    fx.run_sync(fx.scoped(effect.gen(body)).timeout(5).or_die())


# --- platform-node: request defect isolation over HTTP --------------------------------


class Ok(RpcGroup):
    ok = make("Ok", success=S.String)


class StringValue(TypedDict):
    value: str


class NumberValue(TypedDict):
    value: float


class ServerGroup(RpcGroup):
    ok = Ok.ok
    invalid = make("Invalid", payload=S.Struct(StringValue))


class ClientGroup(RpcGroup):
    ok = Ok.ok
    missing = make("Missing")
    missing_with_schemas = make("MissingWithSchemas", success=S.Number, error=S.String)
    invalid = make("Invalid", payload=S.Struct(NumberValue))


def _isolation_client(body: Any, serialization: Any = rs.layer_json) -> Any:
    handlers = ServerGroup.to_layer(
        ServerGroup.handlers()
        .handle(ServerGroup.ok)(lambda _: effect.succeed("ok"))
        .handle(ServerGroup.invalid)(lambda _: effect.succeed(None))
    )
    server = router.serve(
        rpc_server.layer(ServerGroup)
        .pipe(layer.provide(handlers))
        .pipe(layer.provide_merge(rpc_server.layer_protocol_http("/rpc")))
        .pipe(layer.provide(serialization)),
        disable_logger=True,
        disable_listen_log=True,
    )
    protocol = (
        rpc_client.layer_protocol_http(
            "", transform_client=lambda c: c.map_request(lambda r: r.append_url("/rpc"))
        )
        .pipe(layer.provide_merge(server))
        .pipe(layer.provide(uvicorn_server.layer_test()))
        .pipe(layer.provide(serialization))
    )
    program = fx.scoped(effect.gen(body)).pipe(fx.provide(protocol))
    return fx.run_sync(program.timeout(10).or_die())


@pytest.mark.parametrize("tag", ["Missing", "MissingWithSchemas"])
def test_json_unknown_tag_fails_only_its_request(tag: str) -> None:
    """RpcServer / request defect isolation over HTTP / JSON: unknown tag ${tag} fails only its request and the client remains reusable"""  # noqa: E501

    def body():
        client = yield from rpc_client.make(ClientGroup)
        assert (yield from client.ok()) == "ok"
        call = client.missing if tag == "Missing" else client.missing_with_schemas
        missing = yield from call().exit()
        assert (yield from client.ok()) == "ok"
        assert missing == Exit.die(DecodedDefect(f"Unknown request tag: {tag}"))

    _isolation_client(body)


def test_json_an_invalid_payload_fails_only_its_request() -> None:
    """RpcServer / request defect isolation over HTTP / JSON: an invalid payload fails only its request and the client remains reusable"""  # noqa: E501

    def body():
        client = yield from rpc_client.make(ClientGroup)
        assert (yield from client.ok()) == "ok"
        invalid = yield from client.invalid({"value": 42}).exit()
        assert (yield from client.ok()) == "ok"
        assert isinstance(invalid, Exit.Failure)
        assert len(invalid.cause.reasons) == 1
        diagnostic = _message(invalid.cause.squash())
        assert "Expected string" in diagnostic
        assert 'at ["value"]' in diagnostic

    _isolation_client(body)


_FINGERPRINT_DIAGNOSTIC = "Expected matching layout fingerprint"
"""Fingerprinted payloads need both peers to share the schema, so a mismatch is
reported as a fingerprint error instead of the original diagnostic."""
_BINARY_CASES = [
    pytest.param(
        rs.layer_schema_binary(), None, ["Missing key", 'at ["value"]'], id="SchemaBinary"
    ),
    pytest.param(
        rs.layer_schema_binary(fingerprint_payloads=True),
        _FINGERPRINT_DIAGNOSTIC,
        [_FINGERPRINT_DIAGNOSTIC],
        id="SchemaBinary with fingerprints",
    ),
]


@pytest.mark.parametrize("tag", ["Missing", "MissingWithSchemas"])
@pytest.mark.parametrize(("serialization", "unknown_tag", "invalid"), _BINARY_CASES)
def test_binary_unknown_tag_fails_only_its_request(
    serialization: Any, unknown_tag: str | None, invalid: list[str], tag: str
) -> None:
    """RpcServer / request defect isolation over HTTP / ${name}: unknown tag ${tag} fails only its request and the client remains reusable"""  # noqa: E501

    def body():
        client = yield from rpc_client.make(ClientGroup)
        assert (yield from client.ok()) == "ok"
        call = client.missing if tag == "Missing" else client.missing_with_schemas
        missing = yield from call().exit()
        assert (yield from client.ok()) == "ok"
        if unknown_tag is None:
            assert missing == Exit.die(DecodedDefect(f"Unknown request tag: {tag}"))
        else:
            assert isinstance(missing, Exit.Failure)
            assert len(missing.cause.reasons) == 1
            assert unknown_tag in str(missing.cause.squash())

    _isolation_client(body, serialization)


@pytest.mark.parametrize(("serialization", "unknown_tag", "invalid"), _BINARY_CASES)
def test_binary_an_invalid_payload_fails_only_its_request(
    serialization: Any, unknown_tag: str | None, invalid: list[str]
) -> None:
    """RpcServer / request defect isolation over HTTP / ${name}: an invalid payload fails only its request and the client remains reusable"""  # noqa: E501

    def body():
        client = yield from rpc_client.make(ClientGroup)
        assert (yield from client.ok()) == "ok"
        exit = yield from client.invalid({"value": 42}).exit()
        assert (yield from client.ok()) == "ok"
        assert isinstance(exit, Exit.Failure)
        assert len(exit.cause.reasons) == 1
        diagnostic = _message(exit.cause.squash())
        for expected in invalid:
            assert expected in diagnostic

    _isolation_client(body, serialization)


# --- platform-node: Ticker isolation over TCP ------------------------------------------


def _ticker_survives[G: TickerClient | Booming](
    group: type[G],
    server: Any,
    failing_call: Callable[[G], Any],
) -> None:
    """Effect's ``assertTickerSurvives``: a failing sibling call does not
    affect an in-flight ``Ticker`` stream on the same connection."""
    from pyfect import socket as fx_socket
    from pyfect.socket import server as socket_server
    from pyfect.socket.server import SocketServer

    def port() -> Any:
        return SocketServer().map(lambda s: fx_socket.layer_net(s.address.port, "127.0.0.1"))  # pyright: ignore[reportAttributeAccessIssue]

    client_protocol = (
        rpc_client.layer_protocol_socket()
        .pipe(layer.provide(layer.unwrap(port())))
        .pipe(layer.provide(rs.layer_ndjson))
    )
    served = server.pipe(layer.provide_merge(socket_server.layer(0, "127.0.0.1")))

    def body():
        client = yield from rpc_client.make(group)
        received: list[float] = []
        ticker = (
            yield from client.ticker()
            .run_for_each(lambda value: effect.sync(lambda: received.append(value)))
            .fork()
        )
        enough = effect.suspend(
            lambda: effect.succeed(None) if len(received) >= 2 else effect.fail("not yet")
        )
        yield from enough.retry(schedule=schedule.spaced(0.05), times=200)
        before = len(received)
        assert before >= 2
        yield from failing_call(client)
        yield from fx.sleep(0.3)
        after = len(received)
        status = ticker.poll_unsafe()
        yield from ticker.interrupt()
        assert status is None, "Ticker stream must still be running"
        assert after > before, "Ticker stream must keep emitting"

    program = fx.scoped(effect.gen(body)).pipe(
        fx.provide(client_protocol.pipe(layer.provide_merge(served)))
    )
    fx.run_sync(program.timeout(30).or_die())


def _ticker_rpc() -> Any:
    return make("Ticker", success=S.Number, stream=True)


class GhostValue(TypedDict):
    value: str


class TickerServer(RpcGroup):
    ticker = _ticker_rpc()


class TickerClient(RpcGroup):
    ticker = TickerServer.ticker
    ghost = make("Ghost", payload=S.Struct(GhostValue), success=S.String)


def test_an_unknown_request_tag_fails_only_its_own_request() -> None:
    """RpcServer / unknown-tag isolation / an unknown request tag fails only its own request, not other in-flight streams on the same connection"""  # noqa: E501
    handlers = TickerServer.to_layer(
        TickerServer.handlers().handle(TickerServer.ticker)(
            lambda _: stream.from_schedule(schedule.spaced(0.06))
        )
    )
    server = (
        rpc_server.layer(TickerServer)
        .pipe(layer.provide(handlers))
        .pipe(layer.provide_merge(rpc_server.layer_protocol_socket_server))
    )

    def ghost(client: TickerClient) -> Any:
        @effect.gen
        def run():
            exit = yield from client.ghost({"value": "boo"}).exit()
            assert isinstance(exit, Exit.Failure), "Ghost call should fail with the routing miss"

        return run

    _ticker_survives(TickerClient, server.pipe(layer.provide(rs.layer_ndjson)), ghost)


class Booming(RpcGroup):
    ticker = _ticker_rpc()
    boom = make("Boom", success=S.String)


def test_with_disable_fatal_defects_a_handler_defect_fails_only_its_own_request() -> None:
    """RpcServer / fatal-defect isolation / with disableFatalDefects a handler defect fails only its own request, not other in-flight streams"""  # noqa: E501
    handlers = Booming.to_layer(
        Booming.handlers()
        .handle(Booming.ticker)(lambda _: stream.from_schedule(schedule.spaced(0.06)))
        .handle(Booming.boom)(lambda _: effect.die(DecodedDefect("boom")))
    )
    server = (
        rpc_server.layer(Booming, rpc_server.ServerOptions(disable_fatal_defects=True))
        .pipe(layer.provide(handlers))
        .pipe(layer.provide_merge(rpc_server.layer_protocol_socket_server))
    )

    def boom(client: Booming) -> Any:
        @effect.gen
        def run():
            exit = yield from client.boom().exit()
            assert isinstance(exit, Exit.Failure), "Boom call must fail with the handler defect"
            assert "boom" in _message(exit.cause.squash())

        return run

    _ticker_survives(Booming, server.pipe(layer.provide(rs.layer_ndjson)), boom)


class Throwing(RpcGroup):
    pending = make("pending", success=S.String)
    throws = make("throws", success=S.String)
    throws_stream = make("throwsStream", success=S.String, stream=True)


def test_isolates_synchronous_handler_throws_when_fatal_defects_are_disabled() -> None:
    """RpcServer / isolates synchronous handler throws when fatal defects are disabled"""

    def throws(_: object) -> fx.Effect[str]:
        raise RuntimeError("boom")

    def throws_stream(_: object) -> stream.Stream[str]:
        raise RuntimeError("boom stream")

    def summarize(response: FromServer) -> object:
        if not isinstance(response, ResponseExit):
            return [type(response).__name__]
        if isinstance(response.exit, Exit.Success):
            return [response.request_id, ["Success", response.exit.value]]
        return [
            response.request_id,
            [
                ["Die", str(reason.defect)] if isinstance(reason, Die) else [type(reason).__name__]
                for reason in response.exit.cause.reasons
            ],
        ]

    def body():
        started = fx.Deferred[None]()
        release = fx.Deferred[None]()
        messages = yield from fx.Queue.unbounded()
        handlers = Throwing.to_layer(
            Throwing.handlers()
            .handle(Throwing.pending)(
                lambda _: started.succeed(None).flat_map(lambda _: release.wait()).as_("served")
            )
            .handle(Throwing.throws)(throws)
            .handle(Throwing.throws_stream)(throws_stream)
        )
        server = yield from rpc_server.make_no_serialization(
            Throwing,
            lambda response: messages.offer(response).as_void(),
            rpc_server.ServerOptions(disable_fatal_defects=True),
        ).pipe(fx.provide(handlers))

        def request(id: str, tag: str) -> Request:
            return Request(id, tag, None)

        yield from server.write(1, request("1", "pending"))
        yield from started.wait()
        yield from server.write(1, request("2", "throws"))
        yield from server.write(1, request("3", "throwsStream"))
        assert summarize((yield from messages.take())) == ["2", [["Die", "boom"]]]
        assert summarize((yield from messages.take())) == ["3", [["Die", "boom stream"]]]
        yield from release.succeed(None)
        assert summarize((yield from messages.take())) == ["1", ["Success", "served"]]

    fx.run_sync(fx.scoped(effect.gen(body)).timeout(5).or_die())
