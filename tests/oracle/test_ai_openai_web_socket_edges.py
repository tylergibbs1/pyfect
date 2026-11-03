"""WebSocket mode edges Effect's tests leave open, checked against Effect's
``makeSocket`` (the error event decoding run under Node): a connection the
server closes or a consumer leaves mid-response is replaced, requests are
sent one at a time, and an error event's details are its decoded fields."""

from __future__ import annotations

# pyright: reportUnknownVariableType=false, reportUnknownArgumentType=false
# pyright: reportUnknownMemberType=false, reportUnknownLambdaType=false
from typing import Any, cast

import pyfect as fx
from pyfect import testing
from pyfect.ai import ai_error as E
from pyfect.ai import chat
from pyfect.ai.openai import client, language_model
from pyfect.exit import Failure, Success
from pyfect.redacted import make as redact

from ._ai_http import unexpected
from .test_ai_openai_client import (
    NOT_FOUND,
    WsServer,
    chat_over_ws,
    web_socket_mode,
    ws_completed,
    ws_turn,
)

_URL = "https://socket-edges.test/v1"


def _reason(exit: Failure[Any]) -> Any:
    found: Any = exit.cause.find_error()
    return found.value.reason


@testing.live
def test_server_close_mid_response_fails_the_turn_and_reconnects():
    server = WsServer()
    started = ws_completed("resp_1", "msg_1", "partial")[:2]

    def close_after_start(_: Any) -> fx.Effect[None]:
        return server.send(*started).flat_map(lambda _: fx.sync(server.close))

    def drive() -> Any:
        first = yield from ws_turn(server, {"model": "m", "input": "a"}, close_after_start)
        second = yield from ws_turn(
            server,
            {"model": "m", "input": "b"},
            lambda _: server.send(*ws_completed("resp_2", "msg_2", "ok")),
        )
        return first, second

    first, second = yield from web_socket_mode(server, fx.gen(drive), _URL).timeout(5)
    assert isinstance(first, Failure)
    reason = _reason(first)
    assert isinstance(reason, E.NetworkError)
    assert reason.reason == "TransportError"
    assert isinstance(second, Success)
    assert len(server.sockets) == 2


@testing.live
def test_leaving_mid_response_replaces_the_connection():
    server = WsServer()

    def drive() -> Any:
        c = yield from client.OpenAiClient()
        _, stream = yield from c.create_response_stream(cast("Any", {"model": "m", "input": "a"}))
        started = ws_completed("resp_1", "msg_1", "partial")[:2]
        yield from fx.all(
            stream.take(1).run_collect(),
            server.next_create.flat_map(lambda _: server.send(*started)),
            concurrency="unbounded",
        )
        return (
            yield from ws_turn(
                server,
                {"model": "m", "input": "b"},
                lambda _: server.send(*ws_completed("resp_2", "msg_2", "ok")),
            )
        )

    second = yield from web_socket_mode(server, fx.gen(drive), _URL).timeout(5)
    assert isinstance(second, Success)
    assert len(server.sockets) == 2


@testing.live
def test_concurrent_streams_are_sent_one_at_a_time():
    server = WsServer()
    order: list[str] = []

    def drive() -> Any:
        c = yield from client.OpenAiClient()

        def stream(name: str) -> fx.Effect[Any, Any]:
            sent = c.create_response_stream(cast("Any", {"model": "m", "input": name}))
            return sent.flat_map(lambda s: s[1].run_drain()).tap(
                lambda _: fx.sync(lambda: order.append(f"done {name}"))
            )

        def respond() -> Any:
            for index in range(2):
                message = yield from server.next_create
                order.append(f"sent {message['input']}")
                yield from fx.sleep(0.02)
                yield from server.send(*ws_completed(f"resp_{index}", f"msg_{index}", "ok"))

        yield from fx.all(stream("a"), stream("b"), fx.gen(respond), concurrency="unbounded")

    yield from web_socket_mode(server, fx.gen(drive), _URL).timeout(5)
    assert order == ["sent a", "done a", "sent b", "done b"]
    assert len(server.sockets) == 1


@testing.live
def test_error_event_details_are_its_decoded_fields():
    """Effect decodes ``error`` as ``{type?, code?, message}``: other keys
    are dropped and the description lists the fields in that order."""
    server = WsServer()
    error = {"error": {"message": "bad", "param": "input", "type": "invalid_request_error"}}
    turn = ws_turn(server, {"model": "m", "input": "a"}, lambda _: server.send(error))
    exit = yield from web_socket_mode(server, turn, _URL).timeout(5)
    assert isinstance(exit, Failure)
    reason = _reason(exit)
    assert isinstance(reason, E.InvalidRequestError)
    assert reason.description == '{"type":"invalid_request_error","message":"bad"}'


@testing.live
def test_response_not_found_keeps_the_connection():
    """``LanguageModel`` retries ``previous_response_not_found`` with the
    full prompt on the same socket."""
    server = WsServer()

    def respond() -> Any:
        yield from server.next_create
        yield from server.send(*ws_completed("resp_1", "msg_1", "ok"))
        yield from server.next_create
        yield from server.send(NOT_FOUND)
        yield from server.next_create
        yield from server.send(*ws_completed("resp_2", "msg_2", "retried"))

    drive = chat_over_ws(server, "gpt-4o-mini", ["hello", "again"], _URL)
    yield from fx.all(drive, fx.gen(respond), concurrency="unbounded").timeout(5)
    assert len(server.sockets) == 1


@testing.live
def test_a_closed_connection_forgets_its_response_ids():
    """The tracker is cleared when a connection ends, so the next request
    on a new one sends the whole prompt."""
    server = WsServer()
    requests: list[dict[str, Any]] = []

    def respond() -> Any:
        requests.append((yield from server.next_create))
        yield from server.send(*ws_completed("resp_1", "msg_1", "ok"))
        yield from fx.sleep(0.05)
        server.close()
        requests.append((yield from server.next_create))
        yield from server.send(*ws_completed("resp_2", "msg_2", "again"))

    def drive() -> Any:
        session = yield from chat.empty
        yield from session.stream_text(prompt="hello").run_drain()
        yield from fx.sleep(0.2)
        yield from session.stream_text(prompt="again").run_drain()

    program = (
        fx.gen(drive)
        .pipe(client.with_web_socket_mode)
        .pipe(fx.provide(language_model.model("gpt-4o-mini", {"store": True}).layer))
        .pipe(fx.provide(client.layer(api_key=redact("sk-test"), api_url=_URL)))
        .pipe(fx.provide(server.layer))
        .pipe(fx.provide(unexpected().layer))
    )
    yield from fx.all(program, fx.gen(respond), concurrency="unbounded").timeout(5)
    assert len(server.sockets) == 2
    assert "previous_response_id" not in requests[1]
    assert len(requests[1]["input"]) == 3
