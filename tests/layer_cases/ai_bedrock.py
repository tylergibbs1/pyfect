"""Reuse cases for the Amazon Bedrock layers (``pyfect.ai.amazon_bedrock``): each
generates text through a fake ``HttpClient`` answering a Converse reply, signing
with the Web Crypto ``Digest`` and ``Mac``."""

# pyright: reportUnknownLambdaType=false, reportUnknownMemberType=false
# pyright: reportUnknownVariableType=false, reportUnknownArgumentType=false

from __future__ import annotations

from typing import Any

from oracle import _ai_http
from oracle._bedrock import WEB_CRYPTO

import pyfect as fx
from layer_cases._case import AnyEffect, AnyLayer, Case
from pyfect import config_provider
from pyfect import layer as L
from pyfect.ai import language_model as lm
from pyfect.ai.amazon_bedrock import client as bedrock_client
from pyfect.ai.amazon_bedrock import language_model as bedrock_lm
from pyfect.http.client import layer_test as http_layer_test
from pyfect.http.request import HttpClientRequest
from pyfect.redacted import make as redact

_MODEL = "anthropic.claude-sonnet"
_REPLY = {
    "output": {"message": {"role": "assistant", "content": [{"text": "Hi"}]}},
    "stopReason": "end_turn",
    "usage": {"inputTokens": 7, "outputTokens": 3, "totalTokens": 10},
    "metrics": {"latencyMs": 1},
}


def _respond(request: HttpClientRequest) -> AnyEffect:
    return fx.succeed(_ai_http.json_response(request, _REPLY))


def _transport() -> AnyLayer:
    return L.merge(http_layer_test(_respond), WEB_CRYPTO)


def _keys() -> AnyLayer:
    return config_provider.layer(
        config_provider.from_unknown(
            {"AWS_REGION": "us-west-2", "AWS_ACCESS_KEY_ID": "AKID", "AWS_SECRET_ACCESS_KEY": "s"}
        )
    )


def _model() -> AnyLayer:
    return bedrock_lm.layer(model=_MODEL)


def _client() -> AnyLayer:
    return bedrock_client.layer(api_key=redact("bedrock-key")).pipe(L.provide(_transport()))


def _generates() -> AnyEffect:
    def check(response: lm.GenerateTextResponse[Any, Any]) -> AnyEffect:
        return fx.void if response.text == "Hi" else fx.die(AssertionError(response.text))

    return lm.generate_text("Hello").flat_map(check)


def _with_model() -> AnyEffect:
    return _generates().pipe(fx.provide(_model()))


CASES: dict[str, Case] = {
    "pyfect.ai.amazon_bedrock.client.layer": Case(
        layer=lambda: bedrock_client.layer(access_key_id="AKID", secret_access_key=redact("s")),
        needs=_transport,
        use=_with_model,
    ),
    "pyfect.ai.amazon_bedrock.client.layer_config": Case(
        layer=bedrock_client.layer_config,
        needs=lambda: L.merge(_transport(), _keys()),
        use=_with_model,
    ),
    "pyfect.ai.amazon_bedrock.language_model.layer": Case(
        layer=_model, needs=_client, use=_generates
    ),
}

SKIPPED: dict[str, str] = {}
