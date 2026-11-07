"""A server message that parses but has the wrong shape fails the requests
waiting, as an undecodable frame does, and leaves the client protocol
working (audit #25). Every client transport reads server messages through
one decoder, and each is checked here with the same malformed messages."""

# pyright: reportUnknownLambdaType=false, reportUnknownMemberType=false
# pyright: reportUnknownVariableType=false, reportUnknownArgumentType=false

import json
from collections.abc import Callable
from typing import Any

import pytest

import pyfect as fx
from pyfect import effect, layer, schedule
from pyfect import exit as Exit
from pyfect import schema as S
from pyfect._core import Effect
from pyfect.http import client as http_client
from pyfect.http import response as http_response
from pyfect.http.client import HttpClient
from pyfect.queue import Queue
from pyfect.rpc import RpcClientError, RpcGroup, make
from pyfect.rpc import client as rpc_client
from pyfect.rpc import serialization as rs
from pyfect.rpc.client import ClientOptions, ClientProtocol
from pyfect.socket import Reader, Socket, Writer
from pyfect.socket import make as socket_make
from pyfect.workers.worker import Spawner, Worker, WorkerPlatform, WorkerPlatformService


class Echo(RpcGroup):
    ping = make("Ping", success=S.String)


_SUCCESS = {"_tag": "Success", "value": "late"}

MALFORMED: dict[str, object] = {
    "number": 1,
    "list of number": [1],
    "null": None,
    "tag not a string": {"_tag": 5},
    "chunk without request id": {"_tag": "Chunk", "values": ["x"]},
    "exit without request id": {"_tag": "Exit", "exit": _SUCCESS},
    "exit without exit": {"_tag": "Exit", "requestId": "1"},
    "list request id": {"_tag": "Exit", "requestId": [1], "exit": _SUCCESS},
    "object request id": {"_tag": "Exit", "requestId": {"a": 1}, "exit": _SUCCESS},
    "boolean request id": {"_tag": "Exit", "requestId": True, "exit": _SUCCESS},
    "defect without defect": {"_tag": "Defect"},
    "forged protocol error": {"_tag": "ClientProtocolError", "error": "forged"},
}


def _exit(request_id: str, value: str) -> dict[str, Any]:
    return {"_tag": "Exit", "requestId": request_id, "exit": {"_tag": "Success", "value": value}}


def _ids() -> Callable[[], str]:
    counter = iter(range(1, 1000))
    return lambda: str(next(counter))


def _assert_rpc_error(exit: Exit.Exit[Any, Any]) -> None:
    assert isinstance(exit, Exit.Failure)
    assert not exit.cause.has_dies, exit.cause
    assert isinstance(exit.cause.squash(), RpcClientError)


def _run(body: Callable[[], Any]) -> Any:
    return fx.run_blocking(fx.scoped(effect.gen(body)).timeout("5 seconds").or_die())


# --- socket ----------------------------------------------------------------------------


def _socket_client(serialization: Any):
    frames = yield from Queue[str].unbounded()
    requests = yield from Queue[str].unbounded()

    def write(data: Any) -> Effect[None]:
        text = data if isinstance(data, str) else bytes(data).decode()
        if '"Ping"' not in text:
            return effect.succeed(None)
        return requests.offer(text).as_void()

    socket = socket_make(
        effect.succeed(Reader(frames.take().map(lambda frame: (frame,)))),
        effect.succeed(Writer(write, lambda chunks: write(chunks[0]))),
    )
    protocol = yield from (
        rpc_client.make_protocol_socket(rpc_client.SocketOptions(retry_policy=schedule.spaced(0)))
        .pipe(effect.provide_service(Socket, socket))
        .pipe(fx.provide(serialization))
    )
    client = yield from rpc_client.make(Echo, ClientOptions(generate_request_id=_ids())).pipe(
        effect.provide_service(ClientProtocol, protocol)
    )
    return client, frames, requests


@pytest.mark.parametrize("name", list(MALFORMED))
def test_a_malformed_socket_message_fails_the_waiting_calls_and_keeps_the_connection(
    name: str,
) -> None:
    def body():
        client, frames, requests = yield from _socket_client(rs.layer_ndjson)
        first = yield from client.ping().fork()
        yield from requests.take()
        yield from frames.offer(json.dumps(MALFORMED[name]) + "\n")
        _assert_rpc_error((yield from first.await_exit()))
        second = yield from client.ping().fork()
        yield from requests.take()
        yield from frames.offer(json.dumps(_exit("2", "pong")) + "\n")
        return (yield from second.join())

    assert _run(body) == "pong"


@pytest.mark.parametrize("request_id", [[1], {"a": 1}, True], ids=["list", "object", "boolean"])
def test_a_json_rpc_response_with_an_id_that_is_not_a_request_id_keeps_the_connection(
    request_id: object,
) -> None:
    def body():
        client, frames, requests = yield from _socket_client(rs.layer_nd_json_rpc())
        first = yield from client.ping().fork()
        yield from requests.take()
        yield from frames.offer(
            json.dumps({"jsonrpc": "2.0", "id": request_id, "result": 1}) + "\n"
        )
        _assert_rpc_error((yield from first.await_exit()))
        second = yield from client.ping().fork()
        yield from requests.take()
        yield from frames.offer(json.dumps({"jsonrpc": "2.0", "id": "2", "result": "pong"}) + "\n")
        return (yield from second.join())

    assert _run(body) == "pong"


# --- HTTP ------------------------------------------------------------------------------


@pytest.mark.parametrize("name", list(MALFORMED))
def test_a_malformed_http_response_fails_its_request_with_an_rpc_error(name: str) -> None:
    body_text = json.dumps(MALFORMED[name]) + "\n"

    def send(request: Any, *_: object) -> Effect[Any]:
        return effect.succeed(http_response.make(request, body_text))

    protocol = (
        rpc_client.layer_protocol_http("http://localhost/rpc")
        .pipe(layer.provide_merge(rs.layer_ndjson))
        .pipe(layer.provide_merge(layer.succeed(HttpClient, http_client.make(send))))
    )

    def body():
        client = yield from rpc_client.make(
            Echo, ClientOptions(generate_request_id=lambda: "1"), layer=protocol
        )
        _assert_rpc_error((yield from client.ping().exit()))

    _run(body)


# --- worker ----------------------------------------------------------------------------


def _worker_client(replies: Queue[Any], requests: Queue[Any]):
    def send(message: Any, _transfers: Any) -> Effect[None]:
        if message.get("_tag") != "Request":
            return effect.succeed(None)
        return requests.offer(message).as_void()

    def run(handler: Any, _on_spawn: Any) -> Effect[Any, Any, Any]:
        return replies.take().flat_map(handler).forever()

    backing = Worker[Any, Any](send=send, run=run)
    protocol = yield from (
        rpc_client.make_protocol_worker(size=1)
        .pipe(
            effect.provide_service(
                WorkerPlatform, WorkerPlatformService(lambda _: effect.succeed(backing))
            )
        )
        .pipe(effect.provide_service(Spawner, lambda _: None))
    )
    return (
        yield from rpc_client.make(Echo, ClientOptions(generate_request_id=_ids())).pipe(
            effect.provide_service(ClientProtocol, protocol)
        )
    )


def test_a_defect_the_client_cannot_decode_still_keeps_the_client() -> None:
    """Worker messages are values, so a ``Defect``'s value need not be
    JSON; decoding it failed inside the client's read fiber, which ended
    it, and every later call waited forever."""

    def body():
        replies = yield from Queue[Any].unbounded()
        requests = yield from Queue[Any].unbounded()
        client = yield from _worker_client(replies, requests)
        first = yield from client.ping().fork()
        yield from requests.take()
        yield from replies.offer({"_tag": "Defect", "defect": object()})
        assert isinstance((yield from first.await_exit()), Exit.Failure)
        second = yield from client.ping().fork()
        yield from requests.take()
        yield from replies.offer(_exit("2", "pong"))
        return (yield from second.join())

    assert _run(body) == "pong"


@pytest.mark.parametrize("name", list(MALFORMED))
def test_a_malformed_worker_message_fails_the_waiting_calls_and_keeps_the_worker(
    name: str,
) -> None:
    def body():
        replies = yield from Queue[Any].unbounded()
        requests = yield from Queue[Any].unbounded()
        client = yield from _worker_client(replies, requests)
        first = yield from client.ping().fork()
        yield from requests.take()
        yield from replies.offer(MALFORMED[name])
        _assert_rpc_error((yield from first.await_exit()))
        second = yield from client.ping().fork()
        yield from requests.take()
        yield from replies.offer(_exit("2", "pong"))
        return (yield from second.join())

    assert _run(body) == "pong"
