"""Reuse cases for the ``DecisionModel`` providers (``pyfect.ai.openai``,
``pyfect.ai.cloudflare``, ``pyfect.ai.typesafe``): each decides one
probability against a fake ``HttpClient`` answering in the provider's wire
format."""

# pyright: reportUnknownLambdaType=false, reportUnknownMemberType=false
# pyright: reportUnknownVariableType=false, reportUnknownArgumentType=false

from __future__ import annotations

from collections.abc import Callable

from oracle import _ai_http

import pyfect as fx
from layer_cases._case import AnyEffect, AnyLayer, Case
from pyfect import config, config_provider
from pyfect import layer as L
from pyfect import schema as S
from pyfect.ai import decision as D
from pyfect.ai import decision_model as DM
from pyfect.ai.cloudflare import client as cloudflare_client
from pyfect.ai.cloudflare import decision_model as cloudflare_dm
from pyfect.ai.openai import client as openai_client
from pyfect.ai.openai import decision_model as openai_dm
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


def _keys() -> AnyLayer:
    return config_provider.layer(
        config_provider.from_unknown(
            {
                "CLOUDFLARE_ACCOUNT_ID": "acct",
                "CLOUDFLARE_API_TOKEN": "cf-test",
                "TYPESAFE_API_KEY": "ts-test",
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


def _with(model: Callable[[], AnyLayer]) -> Callable[[], AnyEffect]:
    return lambda: _decides().pipe(fx.provide(model()))


_cloudflare_model = lambda: cloudflare_dm.layer(model="clef")  # noqa: E731
_typesafe_model = lambda: typesafe_dm.layer(model="jev-latest")  # noqa: E731

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
}

SKIPPED: dict[str, str] = {}
