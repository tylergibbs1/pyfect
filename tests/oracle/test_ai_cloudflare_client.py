"""Ports of Effect's ``packages/ai/cloudflare/test/CloudflareClient.test.ts``.
Each docstring is the Effect test title (with its ``describe``); the status
table is one parametrized test. Responses are answered by a mocked
``HttpClient``."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import timedelta
from typing import Any

import pytest

import pyfect as fx
from pyfect import config, config_provider, testing
from pyfect.ai import ai_error as E
from pyfect.ai.cloudflare import client
from pyfect.ai.cloudflare import schema as W
from pyfect.http import error as http_error
from pyfect.http.request import HttpClientRequest
from pyfect.redacted import make as redact

from ._ai_http import MockHttp, body_json, json_response, text_response

PAYLOAD: W.DecisionsRequest = {
    "model": "clef-flash",
    "state": "Checkout is down",
    "questions": {
        "urgent": {"type": "noul", "instructions": "Does this need immediate attention?"}
    },
}

RESULT = {
    "model": "clef-flash",
    "answers": {"urgent": {"type": "noul", "noul": 0.99}},
    "usage": {"input_tokens": 120, "output_tokens": 0},
}


def respond(handler: Callable[[HttpClientRequest], Any]) -> MockHttp:
    return MockHttp(lambda request: fx.succeed(handler(request)))


def create_decisions(mock: MockHttp, **options: Any) -> fx.Effect[W.DecisionsResponse, Any, Any]:
    layer = client.layer(account_id="test-account", api_key=redact("test-token"), **options)
    return (
        client.CloudflareClient()
        .flat_map(lambda c: c.create_decisions(PAYLOAD))
        .pipe(fx.provide(layer))
        .pipe(fx.provide(mock.layer))
    )


@testing.effect
def test_posts_and_unwraps():
    """CloudflareClient / posts decisions to the account model endpoint and unwraps the result
    envelope"""
    mock = respond(
        lambda r: json_response(
            r, {"success": True, "result": RESULT, "errors": [], "messages": []}
        )
    )
    response = yield from create_decisions(mock)
    assert response == RESULT
    request = mock.requests[0]
    assert request.method == "POST"
    assert request.url == (
        "https://api.cloudflare.com/client/v4/accounts/test-account/ai/run/@cf/cloudflare/clef-flash"
    )
    assert request.headers["authorization"] == "Bearer test-token"
    assert "cf-aig-gateway-id" not in request.headers
    assert body_json(request) == PAYLOAD


@testing.effect
def test_gateway():
    """CloudflareClient / routes requests through the configured AI Gateway"""
    mock = respond(lambda r: json_response(r, {"success": True, "result": RESULT}))
    yield from create_decisions(mock, gateway_id="test-gateway")
    assert mock.requests[0].headers["cf-aig-gateway-id"] == "test-gateway"


@testing.effect
def test_layer_config():
    """CloudflareClient / layerConfig reads Cloudflare credentials and AI Gateway configuration
    from the environment"""
    mock = respond(lambda r: json_response(r, {"success": True, "result": RESULT}))
    provider = config_provider.from_env(
        {
            "CLOUDFLARE_ACCOUNT_ID": "configured-account",
            "CLOUDFLARE_API_TOKEN": "configured-token",
            "CLOUDFLARE_AI_GATEWAY_ID": "configured-gateway",
            "TEST_API_URL": "https://example.com/api",
        }
    )
    layer = client.layer_config(
        api_url=config.string("TEST_API_URL"),
        transform_client=lambda c: c.map_request(lambda r: r.set_header("x-test", "configured")),
    )
    yield from (
        client.CloudflareClient()
        .flat_map(lambda c: c.create_decisions(PAYLOAD))
        .pipe(fx.provide(layer))
        .pipe(fx.provide(config_provider.layer(provider)))
        .pipe(fx.provide(mock.layer))
    )
    request = mock.requests[0]
    assert request.url == (
        "https://example.com/api/accounts/configured-account/ai/run/@cf/cloudflare/clef-flash"
    )
    assert request.headers["authorization"] == "Bearer configured-token"
    assert request.headers["cf-aig-gateway-id"] == "configured-gateway"
    assert request.headers["x-test"] == "configured"


ENVELOPE = {
    "success": False,
    "result": None,
    "errors": [{"code": 3040, "message": "Request failed"}],
}


@pytest.mark.parametrize(
    ("status", "tag"),
    [
        (401, E.AuthenticationError),
        (404, E.InvalidRequestError),
        (422, E.InvalidRequestError),
        (200, E.InternalProviderError),
    ],
)
@testing.effect
def test_failure_envelope(status: int, tag: type[E.AiErrorReason]):
    """CloudflareClient / error mapping / maps a failure envelope with HTTP 401 / 404 / 422 /
    200 to AuthenticationError / InvalidRequestError / InvalidRequestError /
    InternalProviderError"""
    mock = respond(
        lambda r: json_response(r, ENVELOPE, status=status, headers={"cf-ray": "test-ray"})
    )
    error = yield from create_decisions(mock).flip()
    assert error.module == "CloudflareClient"
    assert error.method == "createDecisions"
    reason = error.reason
    assert isinstance(reason, tag)
    http = getattr(reason, "http", None)
    assert http is not None
    assert http["response"]["status"] == status
    assert "test-token" not in json.dumps(http["request"])
    description = getattr(reason, "description", None)
    assert description is not None
    assert "Request failed" in description
    assert "3040" in description
    assert "test-ray" in description


@testing.effect
def test_failure_envelope_without_errors():
    """CloudflareClient / error mapping / maps a failure envelope without errors with HTTP 200
    to InternalProviderError"""
    mock = respond(lambda r: json_response(r, {"success": False, "result": None}))
    error = yield from create_decisions(mock).flip()
    assert isinstance(error.reason, E.InternalProviderError)


@testing.effect
def test_rate_limit():
    """CloudflareClient / error mapping / maps 429 to RateLimitError with Retry-After and
    Cloudflare metadata"""
    mock = respond(
        lambda r: json_response(
            r, ENVELOPE, status=429, headers={"cf-ray": "test-ray", "retry-after": "2"}
        )
    )
    error = yield from create_decisions(mock).flip()
    reason = error.reason
    assert isinstance(reason, E.RateLimitError)
    assert reason.retry_after == timedelta(seconds=2)
    assert reason.metadata == {
        "cloudflare": {"rayId": "test-ray", "errors": [{"code": 3040, "message": "Request failed"}]}
    }


@testing.effect
def test_non_json_failure():
    """CloudflareClient / error mapping / maps a non-JSON failure body by HTTP status"""
    mock = respond(lambda r: text_response(r, "Bad gateway", status=502))
    error = yield from create_decisions(mock).flip()
    reason = error.reason
    assert isinstance(reason, E.InternalProviderError)
    assert "Bad gateway" in reason.description


@testing.effect
def test_success_without_envelope():
    """CloudflareClient / error mapping / maps a success body without a result envelope to a
    non-retryable InvalidResponseError"""
    error = yield from create_decisions(respond(lambda r: json_response(r, RESULT))).flip()
    assert isinstance(error.reason, E.InvalidResponseError)
    assert not error.is_retryable


@testing.effect
def test_transport_error():
    """CloudflareClient / error mapping / maps TransportError to NetworkError"""

    def refuse(request: HttpClientRequest) -> Any:
        return fx.fail(
            http_error.HttpClientError(
                http_error.TransportError(request=request, cause=ConnectionRefusedError())
            )
        )

    error = yield from create_decisions(MockHttp(refuse)).flip()
    assert isinstance(error.reason, E.NetworkError)
