"""Ports of Effect's ``packages/ai/openrouter/test/Generated.test.ts``. Each
docstring is the Effect test title (with its ``describe``): the generated
client and schemas of ``scripts/gen_ai_schemas.py``, and the finish reason
of tool calls signed by encrypted reasoning over a stubbed
``OpenRouterClient``."""

from __future__ import annotations

# pyright: reportUnknownVariableType=false, reportUnknownArgumentType=false
# pyright: reportUnknownMemberType=false, reportUnknownLambdaType=false
import json
from typing import Any, TypedDict

import pytest

import pyfect as fx
from pyfect import schema as S
from pyfect import stream as St
from pyfect import testing
from pyfect.ai import language_model as lm
from pyfect.ai import tool as T
from pyfect.ai import toolkit as K
from pyfect.ai.openrouter import client, language_model
from pyfect.ai.openrouter import generated as G
from pyfect.ai.openrouter.generated import client as generated_client
from pyfect.ai.openrouter.generated import types as GT
from pyfect.http import client as http_client
from pyfect.http import request as http_request
from pyfect.http import response as http_response
from pyfect.http.body import Bytes
from pyfect.http.request import HttpClientRequest

from ._ai_http import json_response


def _decode(schema: Any, value: object) -> Any:
    return S.decode_unknown_sync(schema)(value)


@testing.effect
def test_audio_transcriptions_as_json():
    """Generated / sends audio transcriptions as JSON with structured provider options"""
    payload: GT.CreateAudioTranscriptionsRequestJson = {
        "model": "openai/whisper-1",
        "input_audio": {"data": "UklGRg==", "format": "wav"},
        "provider": {"options": {"openai": {"prompt": "Effect"}}},
        "language": "en",
        "response_format": "verbose_json",
        "timestamp_granularities": ["word"],
    }
    answer = {"text": "Hello Effect", "language": "en", "duration": 1.5}
    requests: list[HttpClientRequest] = []

    def send(request: HttpClientRequest, *_: Any) -> Any:
        requests.append(request)
        assert request.method == "POST"
        assert str(request.url) == "https://openrouter.ai/api/v1/audio/transcriptions"
        assert request.headers["content-type"] == "application/json"
        assert isinstance(request.body, Bytes)
        assert json.loads(request.body.body) == payload
        return fx.succeed(json_response(request, answer))

    base = http_client.make(send).map_request(
        lambda request: request.prepend_url("https://openrouter.ai/api/v1")
    )
    generated = generated_client.make(base)
    assert (yield from generated.create_audio_transcriptions(payload=payload)) == answer
    assert len(requests) == 1


def test_nullable_generation_statistics():
    """Generated / decodes nullable generation statistics"""
    nulls = [
        "upstream_id",
        "cache_discount",
        "upstream_inference_cost",
        "app_id",
        "streamed",
        "cancelled",
        "provider_name",
        "http_referer",
        "latency",
        "moderation_latency",
        "generation_time",
        "finish_reason",
        "tokens_prompt",
        "tokens_completion",
        "native_tokens_prompt",
        "native_tokens_completion",
        "native_tokens_completion_images",
        "native_tokens_reasoning",
        "native_tokens_cached",
        "num_fetches",
        "num_media_prompt",
        "num_input_audio_prompt",
        "num_media_completion",
        "num_search_results",
        "preset_id",
        "native_finish_reason",
        "external_user",
        "api_type",
        "request_id",
        "response_cache_source_id",
        "router",
        "service_tier",
        "session_id",
        "provider_responses",
        "user_agent",
        "web_search_engine",
    ]
    response = {
        "data": {
            "id": "gen-test",
            "total_cost": 0.003294,
            "created_at": "2026-07-24T12:00:00Z",
            "data_region": "global",
            "model": "openrouter/auto",
            "origin": "https://openrouter.ai/",
            "usage": 0.003294,
            "is_byok": False,
            **dict.fromkeys(nulls),
        }
    }
    assert _decode(G.GetGeneration200, response) == response


def test_streamed_usage_cost():
    """Generated / preserves streamed usage cost fields"""
    usage = {
        "completion_tokens": 11,
        "prompt_tokens": 7,
        "total_tokens": 18,
        "cost": 0.000365,
        "is_byok": False,
        "prompt_tokens_details": {"cached_tokens": 0, "cache_write_tokens": 0},
    }
    assert _decode(G.ChatUsage, usage) == usage


class ProbeParams(TypedDict):
    value: float


ProbeTool = T.make("ProbeTool", parameters=S.Struct(ProbeParams), success=S.String)
ProbeToolkit = K.make(ProbeTool)


def _unexpected(*_: Any) -> Any:
    return fx.die(RuntimeError("unexpected request"))


@pytest.mark.parametrize(
    ("mode", "encrypted", "tool", "reason"),
    [
        ("stream", True, True, "tool-calls"),
        ("stream", False, True, "stop"),
        ("stream", True, False, "stop"),
        ("generate", True, True, "tool-calls"),
    ],
)
@testing.effect
def test_encrypted_reasoning_finish_reason(mode: str, encrypted: bool, tool: bool, reason: str):
    """Generated / ${mode}: encrypted=${encrypted}, tool=${tool} finishes with ${reason}"""
    model = "test/reasoning-model"
    metadata: dict[str, Any] = {"id": "response-1", "model": model, "created": 1}
    details = (
        [{"type": "reasoning.encrypted", "data": "opaque-signature", "format": "unknown"}]
        if encrypted
        else []
    )
    calls = (
        [
            {
                "index": 0,
                "id": "call-1",
                "type": "function",
                "function": {"name": "ProbeTool", "arguments": '{"value":1}'},
            }
        ]
        if tool
        else []
    )
    usage = {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}
    chunks = _decode(
        S.Array(G.ChatStreamChunk),
        [
            {
                **metadata,
                "object": "chat.completion.chunk",
                "choices": [
                    {"index": 0, "delta": {"reasoning_details": details, "tool_calls": calls}}
                ],
            },
            {
                **metadata,
                "object": "chat.completion.chunk",
                "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                "usage": usage,
            },
        ],
    )
    body = _decode(
        G.SendChatCompletionRequest200,
        {
            **metadata,
            "object": "chat.completion",
            "system_fingerprint": None,
            "choices": [
                {
                    "index": 0,
                    "finish_reason": "stop",
                    "message": {
                        "role": "assistant",
                        "reasoning_details": details,
                        "tool_calls": calls,
                    },
                }
            ],
            "usage": usage,
        },
    )
    response = http_response.make(http_request.post("https://example.com/chat/completions"), "")
    service = client.Service(
        generated_client.make(http_client.make(_unexpected)),
        lambda _: fx.die(RuntimeError("unexpected decisions request")),
        lambda _: fx.succeed((body, response)),
        lambda _: fx.succeed((response, St.from_iterable(chunks))),
    )
    options: dict[str, Any] = {
        "prompt": "Use the probe tool",
        "toolkit": ProbeToolkit,
        "disable_tool_call_resolution": True,
    }
    operation: fx.Effect[Any, Any, Any] = (
        lm.stream_text(**options).run_collect()
        if mode == "stream"
        else lm.generate_text(**options).map(lambda result: result.content)
    )
    parts = list(
        (
            yield from operation.pipe(fx.provide(language_model.model(model).layer))
            .pipe(fx.provide(ProbeToolkit.to_layer(ProbeTool.handler(lambda *_: fx.succeed("ok")))))
            .pipe(fx.provide_service(client.OpenRouterClient, service))
        )
    )
    assert [part.name for part in parts if part.type == "tool-call"] == (
        ["ProbeTool"] if tool else []
    )
    assert [part.reason for part in parts if part.type == "finish"] == [reason]
