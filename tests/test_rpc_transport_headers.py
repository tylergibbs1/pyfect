"""A header the transport carried (the HTTP request's, the WebSocket
upgrade's) cannot be replaced by the same name in a request's own
``headers``: an authenticating proxy vouches for the transport's, while the
message body is the caller's (audit #10). Every server transport merges
through one helper; each entry point and serialization is checked here."""

# pyright: reportUnknownLambdaType=false, reportUnknownMemberType=false
# pyright: reportUnknownVariableType=false

import asyncio
import json
from typing import Any

import pytest

import pyfect as fx
from pyfect import effect, layer
from pyfect import schema as S
from pyfect.http import router
from pyfect.http.web import WebRequest
from pyfect.queue import Queue
from pyfect.rpc import RpcGroup, make
from pyfect.rpc import serialization as rs
from pyfect.rpc import server as rpc_server
from pyfect.rpc.server import ServerProtocol
from pyfect.scope import fork_scoped
from pyfect.socket import Reader, Writer
from pyfect.socket import make as socket_make


class Who(RpcGroup):
    who = make("Who", success=S.String)


_HANDLERS = Who.to_layer(
    Who.handlers().handle(Who.who)(
        lambda request: effect.succeed(request.headers.get("x-remote-user", ""))
    )
)


def _request(*, json_rpc: bool) -> object:
    forged = [["X-Remote-User", "admin"], ["x-trace", "client"]]
    if json_rpc:
        return {"jsonrpc": "2.0", "id": 1, "method": "Who", "params": None, "headers": forged}
    return {"_tag": "Request", "id": "1", "tag": "Who", "payload": None, "headers": forged}


_SERIALIZATIONS = {
    "json": (rs.layer_json, False),
    "ndjson": (rs.layer_ndjson, False),
    "jsonrpc": (rs.layer_json_rpc(), True),
    "ndjsonrpc": (rs.layer_nd_json_rpc(), True),
}


def _value(body: str, *, json_rpc: bool) -> object:
    lines = [line for line in body.splitlines() if line.strip()]
    decoded = [json.loads(line) for line in lines]
    flat = [m for d in decoded for m in (d if isinstance(d, list) else [d])]
    if json_rpc:
        (reply,) = [m for m in flat if "result" in m]
        return reply["result"]
    (reply,) = [m for m in flat if m.get("_tag") == "Exit"]
    return reply["exit"]["value"]


@pytest.mark.parametrize("name", list(_SERIALIZATIONS))
def test_http_transport_headers_win_over_in_band_headers(name: str) -> None:
    serialization, json_rpc = _SERIALIZATIONS[name]
    app = (
        rpc_server.layer_http(Who, path="/rpc", protocol="http")
        .pipe(layer.provide(_HANDLERS))
        .pipe(layer.provide(serialization))
    )

    async def main() -> object:
        made = router.to_web_handler(app, disable_logger=True)
        try:
            request = WebRequest(
                "http://test/rpc",
                method="POST",
                body=json.dumps(_request(json_rpc=json_rpc)) + "\n",
                headers=[("x-remote-user", "alice")],
            )
            response = await made.handler(request)
            return _value(await response.text(), json_rpc=json_rpc)
        finally:
            await made.dispose()

    assert asyncio.run(main()) == "alice"


@pytest.mark.parametrize("name", ["ndjson", "ndjsonrpc"])
def test_socket_transport_headers_win_over_in_band_headers(name: str) -> None:
    """``make_socket_protocol``'s ``on_socket``, which the WebSocket handler
    calls with the upgrade request's headers."""
    serialization, json_rpc = _SERIALIZATIONS[name]

    def body():
        frames = yield from Queue[str].unbounded()
        written = yield from Queue[Any].unbounded()
        socket = socket_make(
            effect.succeed(Reader(frames.take().map(lambda frame: (frame,)))),
            effect.succeed(
                Writer(
                    lambda data: written.offer(data).as_void(),
                    lambda chunks: written.offer(chunks[0]).as_void(),
                )
            ),
        )
        made = yield from rpc_server.make_socket_protocol()
        server = rpc_server.make(Who).pipe(effect.provide_service(ServerProtocol, made.protocol))
        yield from fork_scoped(server.pipe(fx.provide(_HANDLERS)))
        yield from fork_scoped(fx.scoped(made.on_socket(socket, (("x-remote-user", "alice"),))))
        yield from frames.offer(json.dumps(_request(json_rpc=json_rpc)) + "\n")
        while True:
            data = yield from written.take()
            text = data if isinstance(data, str) else bytes(data).decode()
            try:
                return _value(text, json_rpc=json_rpc)
            except ValueError:
                continue

    program = fx.scoped(effect.gen(body)).pipe(fx.provide(serialization))
    assert fx.run_blocking(program.timeout("5 seconds").or_die()) == "alice"


def test_in_band_headers_the_transport_does_not_carry_still_arrive() -> None:
    """Only the names the transport carries are protected; a client's own
    headers (``with_headers``) reach the handler as before."""
    seen: list[str] = []
    handlers = Who.to_layer(
        Who.handlers().handle(Who.who)(
            lambda request: effect.sync(
                lambda: seen.append(request.headers.get("x-trace", ""))
            ).as_("ok")
        )
    )
    app = (
        rpc_server.layer_http(Who, path="/rpc", protocol="http")
        .pipe(layer.provide(handlers))
        .pipe(layer.provide(rs.layer_ndjson))
    )

    async def main() -> None:
        made = router.to_web_handler(app, disable_logger=True)
        try:
            request = WebRequest(
                "http://test/rpc",
                method="POST",
                body=json.dumps(_request(json_rpc=False)) + "\n",
                headers=[("x-remote-user", "alice")],
            )
            await (await made.handler(request)).text()
        finally:
            await made.dispose()

    asyncio.run(main())
    assert seen == ["client"]
