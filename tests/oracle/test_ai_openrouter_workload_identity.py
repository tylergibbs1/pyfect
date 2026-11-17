"""Ports of Effect's ``packages/ai/openrouter/test/OpenRouterWorkloadIdentity.test.ts``. Each
docstring is the Effect test title (with its ``describe``). The token endpoint and the API are
a mocked ``HttpClient``."""

from __future__ import annotations

# pyright: reportUnknownVariableType=false, reportUnknownArgumentType=false
# pyright: reportUnknownMemberType=false, reportUnknownLambdaType=false
import json
from typing import Any, cast
from urllib.parse import parse_qsl

import pyfect as fx
from pyfect import layer as L
from pyfect import testing
from pyfect.ai.openrouter import client, workload_identity
from pyfect.http import response as http_response
from pyfect.http.body import Bytes
from pyfect.http.request import HttpClientRequest
from pyfect.redacted import make as redact

from ._ai_http import MockHttp

IDENTITY_TOKEN = "identity.token.signature"
# A trailing slash, which the OpenRouter client also accepts.
API_URL = "https://openrouter.ai/api/v1/"
TOKEN_URL = "https://openrouter.ai/api/v1/oauth/token"


def _body_params(request: HttpClientRequest) -> dict[str, str]:
    body = request.body
    assert isinstance(body, Bytes)
    return dict(parse_qsl(body.body.decode()))


@testing.effect
def test_exchanges_the_identity_token_and_authenticates_every_client_request_path():
    """OpenRouterWorkloadIdentity / exchanges the identity token and authenticates every client request path"""  # noqa: E501

    def answer(request: HttpClientRequest) -> fx.Effect[Any]:
        if request.url == TOKEN_URL:
            body = json.dumps({"access_token": "access-1", "expires_in": 900})
            return fx.succeed(http_response.make(request, body))
        return fx.succeed(http_response.make(request, ""))

    http = MockHttp(answer)
    authenticated = workload_identity.layer(
        identity_token=fx.succeed(redact(IDENTITY_TOKEN)),
        federation_policy_id="policy_1",
        api_url=API_URL,
    )
    layer = client.layer(api_url=API_URL).pipe(L.provide(authenticated))
    service = (
        yield from client.OpenRouterClient().pipe(fx.provide(layer)).pipe(fx.provide(http.layer))
    )
    messages = [{"role": "user", "content": "hello"}]
    chat = cast("Any", {"model": "openai/gpt-4o-mini", "messages": messages})

    yield from service.create_chat_completion(chat).ignore()
    yield from service.create_chat_completion_stream(chat).ignore()
    yield from service.create_decisions(
        cast("Any", {"model": "openai/gpt-4o-mini", "state": {}, "questions": {}})
    ).ignore()

    exchange, *api_requests = http.requests
    assert exchange.url == TOKEN_URL
    assert "authorization" not in exchange.headers
    assert exchange.headers["content-type"] == "application/x-www-form-urlencoded"
    assert _body_params(exchange) == {
        "grant_type": "urn:ietf:params:oauth:grant-type:token-exchange",
        "subject_token": IDENTITY_TOKEN,
        "subject_token_type": "urn:ietf:params:oauth:token-type:jwt",
        "federation_policy_id": "policy_1",
        "scope": "inference",
    }
    assert [(request.url, request.headers.get("authorization")) for request in api_requests] == [
        ("https://openrouter.ai/api/v1/chat/completions", "Bearer access-1"),
        ("https://openrouter.ai/api/v1/chat/completions", "Bearer access-1"),
        ("https://openrouter.ai/api/alpha/decisions", "Bearer access-1"),
    ]
