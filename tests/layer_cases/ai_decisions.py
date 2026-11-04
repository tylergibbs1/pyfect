"""Reuse cases for the ``DecisionModel`` providers (``pyfect.ai.openai``,
``pyfect.ai.cloudflare``, ``pyfect.ai.typesafe``, ``pyfect.ai.openrouter``):
each decides one probability against a fake ``HttpClient`` answering in the
provider's wire format (OpenRouter's language model generates text)."""

# pyright: reportUnknownLambdaType=false, reportUnknownMemberType=false
# pyright: reportUnknownVariableType=false, reportUnknownArgumentType=false

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from oracle import _ai_http

import pyfect as fx
from layer_cases._case import AnyEffect, AnyLayer, Case
from pyfect import config, config_provider
from pyfect import layer as L
from pyfect import schema as S
from pyfect.ai import decision as D
from pyfect.ai import decision_model as DM
from pyfect.ai import language_model as lm
from pyfect.ai.cloudflare import client as cloudflare_client
from pyfect.ai.cloudflare import decision_model as cloudflare_dm
from pyfect.ai.openai import client as openai_client
from pyfect.ai.openai import decision_model as openai_dm
from pyfect.ai.openrouter import client as openrouter_client
from pyfect.ai.openrouter import decision_model as openrouter_dm
from pyfect.ai.openrouter import language_model as openrouter_lm
from pyfect.ai.typesafe import client as typesafe_client
from pyfect.ai.typesafe import decision_model as typesafe_dm
from pyfect.http.client import layer_test as http_layer_test
from pyfect.http.request import HttpClientRequest
from pyfect.redacted import make as redact

_urgent = D.probability(instructions="Does this need attention now?")
_DEFINITION = D.make(input=S.String, decisions={"urgent": _urgent})
_PROBABILITY = 0.75


def _http(body: object) -> Callable[[], AnyLayer]:
    def respond(request: HttpClientRequest) -> AnyEffect:
        return fx.succeed(_ai_http.json_response(request, body))

    return lambda: http_layer_test(respond)


def _decides() -> AnyEffect:
    def check(result: DM.DecideResponse) -> AnyEffect:
        found = result.answers[_urgent].probability
        if found == _PROBABILITY:
            return fx.void
        return fx.die(AssertionError(found))

    return DM.decide(_DEFINITION, input="Checkout is down").flat_map(check)


_openai_http = _http(
    {
        "id": "dec_1",
        "object": "decision",
        "model": "gpt-6-luna",
        "answers": [{"name": "urgent", "type": "predicate", "probability": _PROBABILITY}],
    }
)
_noul = {"answers": {"urgent": {"type": "noul", "noul": _PROBABILITY}}}
_cloudflare_http = _http(
    {
        "success": True,
        "result": {**_noul, "model": "clef", "usage": {"input_tokens": 1, "output_tokens": 0}},
    }
)
_typesafe_http = _http({**_noul, "model": "jev-latest"})


_CHAT = {
    "id": "gen-1",
    "object": "chat.completion",
    "created": 1,
    "model": "openai/gpt-4o-mini",
    "system_fingerprint": None,
    "choices": [
        {"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": "Hi"}}
    ],
}


def _openrouter_http() -> AnyLayer:
    def respond(request: HttpClientRequest) -> AnyEffect:
        decisions = request.url.endswith("/alpha/decisions")
        body = {**_noul, "model": "or-model", "usage": {"input_tokens": 1, "output_tokens": 0}}
        return fx.succeed(_ai_http.json_response(request, body if decisions else _CHAT))

    return http_layer_test(respond)


def _keys() -> AnyLayer:
    return config_provider.layer(
        config_provider.from_unknown(
            {
                "CLOUDFLARE_ACCOUNT_ID": "acct",
                "CLOUDFLARE_API_TOKEN": "cf-test",
                "TYPESAFE_API_KEY": "ts-test",
                "OPENROUTER_API_KEY": "or-test",
            }
        )
    )


def _openai_client() -> AnyLayer:
    return openai_client.layer(api_key=redact("sk-test")).pipe(L.provide_merge(_openai_http()))


def _cloudflare_client() -> AnyLayer:
    return cloudflare_client.layer(account_id="acct", api_key=redact("cf-test")).pipe(
        L.provide_merge(_cloudflare_http())
    )


def _typesafe_client() -> AnyLayer:
    return typesafe_client.layer(api_key=redact("ts-test")).pipe(L.provide_merge(_typesafe_http()))


def _openrouter_client() -> AnyLayer:
    return openrouter_client.layer(api_key=redact("or-test")).pipe(
        L.provide_merge(_openrouter_http())
    )


def _generates() -> AnyEffect:
    def check(response: lm.GenerateTextResponse[Any, Any]) -> AnyEffect:
        return fx.void if response.text == "Hi" else fx.die(AssertionError(response.text))

    return lm.generate_text("Hello").flat_map(check)


def _with(model: Callable[[], AnyLayer]) -> Callable[[], AnyEffect]:
    return lambda: _decides().pipe(fx.provide(model()))


_cloudflare_model = lambda: cloudflare_dm.layer(model="clef")  # noqa: E731
_typesafe_model = lambda: typesafe_dm.layer(model="jev-latest")  # noqa: E731
_openrouter_model = lambda: openrouter_dm.layer(model="or-model")  # noqa: E731

CASES: dict[str, Case] = {
    "pyfect.ai.openai.decision_model.layer": Case(
        layer=lambda: openai_dm.layer(model="gpt-6-luna"), needs=_openai_client, use=_decides
    ),
    "pyfect.ai.cloudflare.client.layer": Case(
        layer=lambda: cloudflare_client.layer(account_id="acct", api_key=redact("cf-test")),
        needs=_cloudflare_http,
        use=_with(_cloudflare_model),
    ),
    "pyfect.ai.cloudflare.client.layer_config": Case(
        layer=cloudflare_client.layer_config,
        needs=lambda: L.merge(_cloudflare_http(), _keys()),
        use=_with(_cloudflare_model),
    ),
    "pyfect.ai.cloudflare.decision_model.layer": Case(
        layer=_cloudflare_model, needs=_cloudflare_client, use=_decides
    ),
    "pyfect.ai.typesafe.client.layer": Case(
        layer=lambda: typesafe_client.layer(api_key=redact("ts-test")),
        needs=_typesafe_http,
        use=_with(_typesafe_model),
    ),
    "pyfect.ai.typesafe.client.layer_config": Case(
        layer=lambda: typesafe_client.layer_config(api_key=config.redacted("TYPESAFE_API_KEY")),
        needs=lambda: L.merge(_typesafe_http(), _keys()),
        use=_with(_typesafe_model),
    ),
    "pyfect.ai.typesafe.decision_model.layer": Case(
        layer=_typesafe_model, needs=_typesafe_client, use=_decides
    ),
    "pyfect.ai.openrouter.client.layer": Case(
        layer=lambda: openrouter_client.layer(api_key=redact("or-test")),
        needs=_openrouter_http,
        use=_with(_openrouter_model),
    ),
    "pyfect.ai.openrouter.client.layer_config": Case(
        layer=lambda: openrouter_client.layer_config(api_key=config.redacted("OPENROUTER_API_KEY")),
        needs=lambda: L.merge(_openrouter_http(), _keys()),
        use=_with(_openrouter_model),
    ),
    "pyfect.ai.openrouter.decision_model.layer": Case(
        layer=_openrouter_model, needs=_openrouter_client, use=_decides
    ),
    "pyfect.ai.openrouter.language_model.layer": Case(
        layer=lambda: openrouter_lm.layer(model="openai/gpt-4o-mini"),
        needs=_openrouter_client,
        use=_generates,
    ),
}

SKIPPED: dict[str, str] = {}
