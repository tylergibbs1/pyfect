"""Ports of Effect's ``packages/ai/anthropic/test/AnthropicWorkloadIdentity.test.ts``. Each
docstring is the Effect test title (with its ``describe``). The token endpoint and the API are
a mocked ``HttpClient``."""

from __future__ import annotations

# pyright: reportUnknownVariableType=false, reportUnknownArgumentType=false
# pyright: reportUnknownMemberType=false, reportUnknownLambdaType=false
import json
from typing import Any

import pyfect as fx
from pyfect import layer as L
from pyfect import testing
from pyfect.ai import ai_error as E
from pyfect.ai.anthropic import client, workload_identity
from pyfect.http import client as http_client
from pyfect.http import response as http_response
from pyfect.http.request import HttpClientRequest
from pyfect.http.response import HttpClientResponse
from pyfect.redacted import make as redact

from ._ai_http import MockHttp, body_json

IDENTITY_TOKEN = "identity.token.signature"
TOKEN_URL = "https://api.anthropic.com/v1/oauth/token"
OPTIONS: dict[str, Any] = {
    "identity_token": fx.succeed(redact(IDENTITY_TOKEN)),
    "federation_rule_id": "fdrl_1",
    "organization_id": "org_1",
}


def _token(request: HttpClientRequest) -> HttpClientResponse:
    return http_response.make(request, json.dumps({"access_token": "access-1", "expires_in": 3600}))


def make_http(token: Any = _token) -> MockHttp:
    return MockHttp(
        lambda request: fx.succeed(
            token(request) if request.url == TOKEN_URL else http_response.make(request, "")
        )
    )


@testing.effect
def test_exchanges_the_identity_token_and_adds_the_oauth_beta_to_authenticated_requests():
    """AnthropicWorkloadIdentity / exchanges the identity token and adds the OAuth beta to authenticated requests"""  # noqa: E501
    http = make_http()
    authenticated = workload_identity.layer(
        **OPTIONS, service_account_id="svac_1", workspace_id="wrkspc_1"
    )
    service = (
        yield from http_client.HttpClient()
        .pipe(fx.provide(authenticated))
        .pipe(fx.provide(http.layer))
    )

    yield from service.get(
        "https://api.anthropic.com/v1/messages",
        headers={"anthropic-beta": "files-api-2025-04-14"},
    )

    exchange, request = http.requests
    assert exchange.url == TOKEN_URL
    assert "authorization" not in exchange.headers
    assert exchange.headers["anthropic-beta"] == "oauth-2025-04-20,oidc-federation-2026-04-01"
    assert body_json(exchange) == {
        "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
        "assertion": IDENTITY_TOKEN,
        "federation_rule_id": "fdrl_1",
        "organization_id": "org_1",
        "service_account_id": "svac_1",
        "workspace_id": "wrkspc_1",
    }
    assert request.headers["authorization"] == "Bearer access-1"
    assert request.headers["anthropic-beta"] == "files-api-2025-04-14,oauth-2025-04-20"


@testing.effect
def test_maps_a_rejected_exchange_to_an_ai_error_without_the_identity_token():
    """AnthropicWorkloadIdentity / maps a rejected exchange to an AiError without the identity token"""  # noqa: E501
    body = json.dumps(
        {
            "type": "error",
            "error": {
                "type": "authentication_error",
                "message": f"Authentication failed for {IDENTITY_TOKEN}",
            },
        },
        separators=(",", ":"),
    ).replace(".", "\\u002e")

    def rejected(request: HttpClientRequest) -> HttpClientResponse:
        headers = {"www-authenticate": f'Bearer error_description="{IDENTITY_TOKEN}"'}
        return http_response.make(request, body, status=401, headers=headers)

    http = make_http(rejected)
    layer = client.layer().pipe(L.provide(workload_identity.layer(**OPTIONS)))
    service = (
        yield from client.AnthropicClient().pipe(fx.provide(layer)).pipe(fx.provide(http.layer))
    )

    error: E.AiError = yield from service.create_message(
        {
            "model": "claude-sonnet-4-20250514",
            "max_tokens": 1,
            "messages": [{"role": "user", "content": "hello"}],
        }
    ).flip()

    assert isinstance(error.reason, E.AuthenticationError)
    assert "Authentication failed for <redacted>" in error.message
