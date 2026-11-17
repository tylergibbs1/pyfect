"""Ports of Effect's ``packages/ai/openai/test/OpenAiWorkloadIdentity.test.ts``. Each docstring
is the Effect test title (with its ``describe``). The token endpoint and the API are a mocked
``HttpClient``; WebSocket mode runs against the in-memory server of the ``OpenAiClient`` ports,
which records the ``Authorization`` header of each connection."""

from __future__ import annotations

# pyright: reportUnknownVariableType=false, reportUnknownArgumentType=false
# pyright: reportUnknownMemberType=false, reportUnknownLambdaType=false
import json
from collections.abc import Callable
from typing import Any, cast

import pyfect as fx
from pyfect import layer as L
from pyfect import testing
from pyfect.ai import ai_error as E
from pyfect.ai.openai import client, workload_identity
from pyfect.http import client as http_client
from pyfect.http import response as http_response
from pyfect.http.request import HttpClientRequest
from pyfect.http.response import HttpClientResponse
from pyfect.redacted import make as redact

from ._ai_http import MockHttp, body_json
from .test_ai_openai_client import WsServer

IDENTITY_TOKEN = "identity.token.signature"
TOKEN_URL = "https://auth.openai.com/oauth/token"
API_URL = "https://api.openai.com/v1/responses"
OPTIONS: dict[str, Any] = {
    "identity_token": fx.succeed(redact(IDENTITY_TOKEN)),
    "identity_provider_id": "idp_1",
    "service_account_id": "sa_1",
}
PAYLOAD = cast("client.CreateResponse", {"model": "gpt-4o", "input": "test"})

type TokenAnswer = Callable[[HttpClientRequest, int], HttpClientResponse]


def token_response(request: HttpClientRequest, n: int, **extra: Any) -> HttpClientResponse:
    body = {"access_token": f"access-{n}", "expires_in": 3600, **extra}
    return http_response.make(request, json.dumps(body))


def make_http(token: TokenAnswer = token_response) -> MockHttp:
    exchanges = 0

    def answer(request: HttpClientRequest) -> fx.Effect[HttpClientResponse]:
        nonlocal exchanges
        if request.url == TOKEN_URL:
            exchanges += 1
            return fx.succeed(token(request, exchanges))
        return fx.succeed(http_response.make(request, ""))

    return MockHttp(answer)


def provide_client(
    effect: fx.Effect[Any, Any, Any], http: MockHttp, api_url: str | None = None
) -> fx.Effect[Any, Any, Any]:
    layer = client.layer(api_url=api_url).pipe(L.provide(workload_identity.layer(**OPTIONS)))
    return effect.pipe(fx.provide(layer)).pipe(fx.provide(http.layer))


def connections(server: WsServer) -> list[str | None]:
    """The ``Authorization`` header of every WebSocket connection."""
    return [(options.headers or {}).get("authorization") for _, options in server.urls]


def web_socket_mode(
    server: WsServer, effect: fx.Effect[Any, Any, Any], http: MockHttp, api_url: str
) -> fx.Effect[Any, Any, Any]:
    return provide_client(effect.pipe(client.with_web_socket_mode), http, api_url).pipe(
        fx.provide(server.layer)
    )


def reply(server: WsServer, event: dict[str, Any]) -> fx.Effect[None]:
    """Answers the next message the server receives."""
    return server.next_create.flat_map(lambda _: server.send(event))


COMPLETED: dict[str, Any] = {
    "type": "response.completed",
    "sequence_number": 1,
    "response": {
        "id": "resp_1",
        "object": "response",
        "created_at": 1,
        "model": "gpt-4o",
        "status": "completed",
        "output": [],
        "metadata": None,
        "temperature": None,
        "top_p": None,
        "tools": [],
        "tool_choice": "auto",
        "error": None,
        "incomplete_details": None,
        "instructions": None,
        "parallel_tool_calls": False,
    },
}


@testing.effect
def test_exchanges_the_identity_token_for_an_access_token():
    """OpenAiWorkloadIdentity / exchanges the identity token for an access token"""
    # OpenAI can leave ``expires_in`` out of the token response.
    http = make_http(
        lambda request, _n: http_response.make(request, json.dumps({"access_token": "access-1"}))
    )
    authenticated = workload_identity.layer(**OPTIONS, identity_token_type="id_token")
    service = (
        yield from http_client.HttpClient()
        .pipe(fx.provide(authenticated))
        .pipe(fx.provide(http.layer))
    )

    yield from service.get(API_URL)

    exchange, request = http.requests
    assert exchange.url == TOKEN_URL
    assert "authorization" not in exchange.headers
    assert body_json(exchange) == {
        "grant_type": "urn:ietf:params:oauth:grant-type:token-exchange",
        "subject_token": IDENTITY_TOKEN,
        "subject_token_type": "urn:ietf:params:oauth:token-type:id_token",
        "identity_provider_id": "idp_1",
        "service_account_id": "sa_1",
    }
    assert request.headers["authorization"] == "Bearer access-1"


@testing.effect
def test_maps_a_rejected_exchange_to_an_ai_error_without_the_identity_token():
    """OpenAiWorkloadIdentity / maps a rejected exchange to an AiError without the identity token"""
    body = json.dumps(
        {
            "error": {
                "message": f"Authentication failed for {IDENTITY_TOKEN}",
                "type": "invalid_request_error",
            }
        },
        separators=(",", ":"),
    ).replace(".", "\\u002e")

    def rejected(request: HttpClientRequest, _n: int) -> HttpClientResponse:
        headers = {"www-authenticate": f'Bearer error_description="{IDENTITY_TOKEN}"'}
        return http_response.make(request, body, status=401, headers=headers)

    service = yield from provide_client(client.OpenAiClient(), make_http(rejected))
    error: E.AiError = yield from service.create_response(PAYLOAD).flip()

    assert isinstance(error.reason, E.AuthenticationError)
    assert "Authentication failed for <redacted>" in error.message


@testing.effect
def test_authenticates_each_connection_with_the_current_access_token():
    """OpenAiWorkloadIdentity / WebSocket mode / authenticates each connection with the current access token"""  # noqa: E501
    server = WsServer()
    error_event = {"type": "error", "code": "server_error", "message": "bad", "param": None}

    @fx.gen
    def failed_turn():
        service = yield from client.OpenAiClient()
        _, stream = yield from service.create_response_stream(PAYLOAD)
        # An error event makes the client replace the connection.
        yield from fx.all(
            stream.run_drain().flip(), reply(server, error_event), concurrency="unbounded"
        )

    @fx.gen
    def program():
        yield from failed_turn
        yield from testing.adjust("1 hour")
        yield from failed_turn

    yield from web_socket_mode(server, program, make_http(), "https://connections.test/v1")

    assert connections(server) == ["Bearer access-1", "Bearer access-2"]


@testing.effect
def test_fails_the_stream_with_an_ai_error_when_the_exchange_fails_and_connects_once_it_succeeds():
    """OpenAiWorkloadIdentity / WebSocket mode / fails the stream with an AiError when the exchange fails, and connects once it succeeds"""  # noqa: E501
    server = WsServer()
    rejected = True

    def token(request: HttpClientRequest, n: int) -> HttpClientResponse:
        if rejected:
            body = json.dumps({"error": "invalid_subject_token"})
            return http_response.make(request, body, status=401)
        return token_response(request, n)

    @fx.gen
    def program():
        nonlocal rejected
        service = yield from client.OpenAiClient()
        error: E.AiError = yield from service.create_response_stream(PAYLOAD).flip()
        assert isinstance(error.reason, E.AuthenticationError)

        rejected = False
        _, stream = yield from service.create_response_stream(PAYLOAD)
        yield from fx.all(stream.run_drain(), reply(server, COMPLETED), concurrency="unbounded")

    yield from web_socket_mode(
        server, program, make_http(token), "https://exchange-failure.test/v1"
    )

    assert connections(server) == ["Bearer access-3"]


@testing.effect
def test_keeps_using_a_connected_socket_after_the_access_token_expires():
    """OpenAiWorkloadIdentity / WebSocket mode / keeps using a connected socket after the access token expires"""  # noqa: E501
    server = WsServer()
    http = make_http(
        lambda request, _n: http_response.make(
            request, json.dumps({"access_token": "access-1", "expires_in": 40})
        )
    )

    @fx.gen
    def turn():
        service = yield from client.OpenAiClient()
        _, stream = yield from service.create_response_stream(PAYLOAD)
        yield from fx.all(stream.run_drain(), reply(server, COMPLETED), concurrency="unbounded")

    @fx.gen
    def program():
        yield from turn
        # The access token is used for 30 seconds, and an idle socket stays open for 60.
        yield from testing.adjust("31 seconds")
        yield from turn

    yield from web_socket_mode(server, program, http, "https://connected.test/v1")

    assert connections(server) == ["Bearer access-1"]
    assert len(http.requests) == 1
