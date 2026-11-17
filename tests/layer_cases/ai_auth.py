"""Reuse cases for the workload identity layers (``pyfect.ai.*.workload_identity``):
each authenticates one request through a fake ``HttpClient`` that answers the token
exchange and echoes the ``authorization`` header of every other request."""

from __future__ import annotations

from oracle import _ai_http

import pyfect as fx
from layer_cases._case import AnyEffect, AnyLayer, Case
from pyfect.ai.anthropic import workload_identity as anthropic_wi
from pyfect.ai.openai import workload_identity as openai_wi
from pyfect.ai.openrouter import workload_identity as openrouter_wi
from pyfect.http import request as http_request
from pyfect.http.client import HttpClient
from pyfect.http.client import layer_test as http_layer_test
from pyfect.http.request import HttpClientRequest
from pyfect.redacted import make as redact

_ACCESS_TOKEN = "access-1"
_IDENTITY_TOKEN = fx.succeed(redact("identity-jwt"))


def _respond(request: HttpClientRequest) -> AnyEffect:
    if request.url.endswith("/oauth/token"):
        body: object = {"access_token": _ACCESS_TOKEN, "expires_in": 3600}
    else:
        body = {"authorization": request.headers.get("authorization")}
    return fx.succeed(_ai_http.json_response(request, body))


def _http() -> AnyLayer:
    return http_layer_test(_respond)


def _authenticates() -> AnyEffect:
    def check(body: object) -> AnyEffect:
        if body == {"authorization": f"Bearer {_ACCESS_TOKEN}"}:
            return fx.void
        return fx.die(AssertionError(body))

    return (
        HttpClient()
        .flat_map(lambda client: client.execute(http_request.get("https://api.example.com/v1/x")))
        .flat_map(lambda response: response.json)
        .flat_map(check)
    )


CASES: dict[str, Case] = {
    "pyfect.ai.anthropic.workload_identity.layer": Case(
        layer=lambda: anthropic_wi.layer(
            identity_token=_IDENTITY_TOKEN,
            federation_rule_id="fdrl_1",
            organization_id="org-1",
        ),
        needs=_http,
        use=_authenticates,
    ),
    "pyfect.ai.openai.workload_identity.layer": Case(
        layer=lambda: openai_wi.layer(
            identity_token=_IDENTITY_TOKEN,
            identity_provider_id="idp-1",
            service_account_id="sa-1",
        ),
        needs=_http,
        use=_authenticates,
    ),
    "pyfect.ai.openrouter.workload_identity.layer": Case(
        layer=lambda: openrouter_wi.layer(
            identity_token=_IDENTITY_TOKEN, federation_policy_id="policy-1"
        ),
        needs=_http,
        use=_authenticates,
    ),
}

SKIPPED: dict[str, str] = {}
