"""Ports of Effect's ``packages/ai/amazon-bedrock/test/AmazonBedrockLanguageModel.test.ts``.
Each docstring is the Effect test title (with its ``describe``). Responses are recorded
Converse JSON or ConverseStream frames answered by a mocked ``HttpClient``."""

from __future__ import annotations

# pyright: reportUnknownVariableType=false, reportUnknownArgumentType=false
# pyright: reportUnknownMemberType=false, reportUnknownLambdaType=false
import json
from collections.abc import Sequence
from typing import Any, TypedDict

import pytest

import pyfect as fx
from pyfect import layer as L
from pyfect import schema as S
from pyfect import testing
from pyfect.ai import ai_error as E
from pyfect.ai import language_model as lm
from pyfect.ai import prompt as Pr
from pyfect.ai import response as R
from pyfect.ai import tool as T
from pyfect.ai import toolkit as K
from pyfect.ai.amazon_bedrock import client
from pyfect.ai.amazon_bedrock import language_model as blm
from pyfect.ai.response import FinishReason
from pyfect.redacted import make as redact

from ._ai_http import MockHttp
from ._bedrock import (
    ACCESS_KEY_ID,
    ENCODED_MODEL_ID,
    MODEL_ID,
    SECRET_ACCESS_KEY,
    WEB_CRYPTO,
    body_json,
    event_frame,
    event_stream_response,
    json_response,
    respond,
)

USAGE: dict[str, int] = {"inputTokens": 7, "outputTokens": 3, "totalTokens": 10}


def converse_response(
    content: Sequence[object], stop_reason: str = "end_turn", usage: dict[str, int] = USAGE
) -> dict[str, Any]:
    return {
        "output": {"message": {"role": "assistant", "content": list(content)}},
        "stopReason": stop_reason,
        "usage": usage,
        "metrics": {"latencyMs": 1},
    }


class _City(TypedDict):
    city: str


Weather = T.make(
    "Weather", description="Get the weather", parameters=S.Struct(_City), success=S.String
)
toolkit = K.make(Weather)


def _replying(body: dict[str, Any]) -> MockHttp:
    return respond(lambda request: json_response(request, body))


def _streaming(frames: Sequence[bytes]) -> MockHttp:
    return respond(lambda request: event_stream_response(request, [b"".join(frames)]))


def _provided(
    effect: fx.Effect[Any, Any, Any], http: MockHttp, config: blm.ConfigService | None = None
) -> fx.Effect[Any, Any, Any]:
    bedrock = client.layer(
        region="us-east-1", access_key_id=ACCESS_KEY_ID, secret_access_key=redact(SECRET_ACCESS_KEY)
    ).pipe(L.provide(L.merge(http.layer, WEB_CRYPTO)))
    return effect.pipe(fx.provide(blm.model(MODEL_ID, config).layer)).pipe(fx.provide(bedrock))


def _text(parts: Sequence[object]) -> str:
    return "".join(part.delta for part in parts if isinstance(part, R.TextDeltaPart))


def _reasoning_metadata(parts: Sequence[object]) -> list[object]:
    return [
        part.metadata.get("amazon-bedrock")
        for part in parts
        if isinstance(part, R.ReasoningStartPart | R.ReasoningDeltaPart | R.ReasoningEndPart)
    ]


def _usage_frame() -> bytes:
    return event_frame(
        "metadata",
        {
            "usage": {"inputTokens": 10, "outputTokens": 5, "totalTokens": 15},
            "metrics": {"latencyMs": 1},
        },
    )


@testing.effect
def test_sends_prompt_and_config():
    """AmazonBedrockLanguageModel / generateText / sends the prompt and config as a Converse
    request and decodes the reply"""
    http = _replying(
        converse_response(
            [{"text": "Hi"}],
            "end_turn",
            {**USAGE, "cacheReadInputTokens": 2, "cacheWriteInputTokens": 1},
        )
    )
    response = yield from _provided(
        lm.generate_text(
            Pr.make(
                [Pr.SystemMessage("Be brief"), Pr.UserMessage([Pr.TextPart("Hello")])],
            )
        ),
        http,
        {
            "inferenceConfig": {"maxTokens": 100, "temperature": 0.5},
            "additionalModelRequestFields": {
                "thinking": {"type": "enabled", "budget_tokens": 1024}
            },
        },
    )
    request = http.requests[0]
    assert request.url.endswith(f"/model/{ENCODED_MODEL_ID}/converse")
    body = body_json(request)
    assert "modelId" not in body
    assert body["system"] == [{"text": "Be brief"}]
    assert body["messages"] == [{"role": "user", "content": [{"text": "Hello"}]}]
    assert body["inferenceConfig"] == {"maxTokens": 100, "temperature": 0.5}
    assert body["additionalModelRequestFields"] == {
        "thinking": {"type": "enabled", "budget_tokens": 1024}
    }
    assert response.text == "Hi"
    assert response.finish_reason == "stop"
    assert response.usage.input_tokens == R.InputTokens(
        uncached=7, total=10, cache_read=2, cache_write=1
    )
    assert response.usage.output_tokens.total == 3


_TOOL_CHOICES: list[tuple[str, lm.ToolChoice, object]] = [
    ("auto", "auto", {"auto": {}}),
    ("required", "required", {"any": {}}),
    ("a named tool", {"tool": "Weather"}, {"tool": {"name": "Weather"}}),
]


@pytest.mark.parametrize(
    ("tool_choice", "expected"),
    [(choice, expected) for _, choice, expected in _TOOL_CHOICES],
    ids=[f"encodes the toolkit with tool choice {label}" for label, _, _ in _TOOL_CHOICES],
)
@testing.effect
def test_encodes_toolkit(tool_choice: lm.ToolChoice, expected: object):
    """AmazonBedrockLanguageModel / generateText / encodes the toolkit with tool choice auto,
    required or a named tool"""
    http = _replying(converse_response([{"text": "Hi"}]))
    yield from _provided(
        lm.generate_text(
            "What is the weather in SF?",
            toolkit=toolkit,
            tool_choice=tool_choice,
            disable_tool_call_resolution=True,
        ),
        http,
    )
    body = body_json(http.requests[0])
    assert len(body["toolConfig"]["tools"]) == 1
    spec = body["toolConfig"]["tools"][0]["toolSpec"]
    assert spec["name"] == "Weather"
    assert spec["description"] == "Get the weather"
    assert spec["inputSchema"]["json"]["properties"]["city"]["type"] == "string"
    assert "city" in spec["inputSchema"]["json"]["required"]
    assert body["toolConfig"]["toolChoice"] == expected


@testing.effect
def test_omits_tool_config_for_none():
    """AmazonBedrockLanguageModel / generateText / omits the tool configuration when tool
    choice is none"""
    http = _replying(converse_response([{"text": "Hi"}]))
    yield from _provided(
        lm.generate_text(
            "Hello", toolkit=toolkit, tool_choice="none", disable_tool_call_resolution=True
        ),
        http,
    )
    assert "toolConfig" not in body_json(http.requests[0])


@testing.effect
def test_decodes_tool_use():
    """AmazonBedrockLanguageModel / generateText / decodes tool use blocks as tool calls"""
    http = _replying(
        converse_response(
            [
                {"text": "Let me check."},
                {"toolUse": {"toolUseId": "tooluse_1", "name": "Weather", "input": {"city": "SF"}}},
            ],
            "tool_use",
        )
    )
    response = yield from _provided(
        lm.generate_text(
            "What is the weather in SF?", toolkit=toolkit, disable_tool_call_resolution=True
        ),
        http,
    )
    assert response.text == "Let me check."
    assert response.finish_reason == "tool-calls"
    assert len(response.tool_calls) == 1
    call = response.tool_calls[0]
    assert (call.id, call.name, call.params) == ("tooluse_1", "Weather", {"city": "SF"})


@testing.effect
def test_sends_tool_calls_and_results():
    """AmazonBedrockLanguageModel / generateText / sends tool calls and results back as toolUse
    and toolResult blocks

    Effect sends a ``null`` result as the text ``null``; ``None`` is also Effect's
    ``undefined``, which it sends as empty text, and pyfect keeps that. The last two
    results are not in Effect's test: a nested array and a boolean go as JSON text too."""
    http = _replying(converse_response([{"text": "Done"}]))
    prompt = Pr.make(
        [
            Pr.UserMessage([Pr.TextPart("Weather in SF, LA, NY and DC?")]),
            Pr.AssistantMessage(
                [
                    Pr.ToolCallPart("tooluse_1", "Weather", {"city": "SF"}),
                    Pr.ToolCallPart("tooluse_2", "Weather", {"city": "LA"}),
                    Pr.ToolCallPart("tooluse_3", "Weather", {"city": "NY"}),
                    Pr.ToolCallPart("tooluse_4", "Weather", {"city": "DC"}),
                    Pr.ToolCallPart("tooluse_5", "Weather", {"city": "LV"}),
                    Pr.ToolCallPart("tooluse_6", "Weather", {"city": "SD"}),
                ]
            ),
            Pr.ToolMessage(
                [
                    Pr.ToolResultPart("tooluse_1", "Weather", False, {"temperature": 20}),
                    Pr.ToolResultPart("tooluse_2", "Weather", True, "service unavailable"),
                    Pr.ToolResultPart("tooluse_3", "Weather", False, []),
                    Pr.ToolResultPart("tooluse_4", "Weather", False, None),
                    Pr.ToolResultPart("tooluse_5", "Weather", False, [{"t": 0.5}, "é"]),
                    Pr.ToolResultPart("tooluse_6", "Weather", False, True),
                ]
            ),
        ]
    )
    yield from _provided(
        lm.generate_text(prompt, toolkit=toolkit, disable_tool_call_resolution=True), http
    )
    assert body_json(http.requests[0])["messages"] == [
        {"role": "user", "content": [{"text": "Weather in SF, LA, NY and DC?"}]},
        {
            "role": "assistant",
            "content": [
                {"toolUse": {"toolUseId": f"tooluse_{i}", "name": "Weather", "input": {"city": c}}}
                for i, c in enumerate(["SF", "LA", "NY", "DC", "LV", "SD"], 1)
            ],
        },
        {
            "role": "user",
            "content": [
                {
                    "toolResult": {
                        "toolUseId": "tooluse_1",
                        "content": [{"json": {"temperature": 20}}],
                    }
                },
                {
                    "toolResult": {
                        "toolUseId": "tooluse_2",
                        "content": [{"text": "service unavailable"}],
                        "status": "error",
                    }
                },
                {"toolResult": {"toolUseId": "tooluse_3", "content": [{"text": "[]"}]}},
                {"toolResult": {"toolUseId": "tooluse_4", "content": [{"text": ""}]}},
                {
                    "toolResult": {
                        "toolUseId": "tooluse_5",
                        "content": [{"text": '[{"t":0.5},"é"]'}],
                    }
                },
                {"toolResult": {"toolUseId": "tooluse_6", "content": [{"text": "true"}]}},
            ],
        },
    ]


@pytest.mark.parametrize(
    ("model_output", "text"),
    [((Pr.TextPart("Sunny"),), "Sunny"), ((), "")],
    ids=["as text", "as empty text when it is empty"],
)
@testing.effect
def test_sends_tool_result_model_output(model_output: tuple[Pr.TextPart, ...], text: str):
    """AmazonBedrockLanguageModel / generateText / sends tool result model output %s"""
    http = _replying(converse_response([{"text": "Done"}]))
    prompt = Pr.make(
        [
            Pr.UserMessage([Pr.TextPart("Weather in SF?")]),
            Pr.AssistantMessage([Pr.ToolCallPart("tooluse_1", "Weather", {"city": "SF"})]),
            Pr.ToolMessage(
                [
                    Pr.ToolResultPart(
                        "tooluse_1",
                        "Weather",
                        False,
                        {"temperature": 20},
                        model_output=model_output,
                    )
                ]
            ),
        ]
    )
    yield from _provided(
        lm.generate_text(prompt, toolkit=toolkit, disable_tool_call_resolution=True), http
    )
    assert body_json(http.requests[0])["messages"][2]["content"] == [
        {"toolResult": {"toolUseId": "tooluse_1", "content": [{"text": text}]}}
    ]


@testing.effect
def test_round_trips_reasoning():
    """AmazonBedrockLanguageModel / generateText / round-trips reasoning blocks with their
    signature and redacted content"""
    http = _replying(
        converse_response(
            [
                {"reasoningContent": {"reasoningText": {"text": "Think", "signature": "sig"}}},
                {"reasoningContent": {"redactedContent": "aGlkZGVu"}},
                {"text": "Hi"},
            ]
        )
    )
    response = yield from _provided(lm.generate_text("Hello"), http)
    assert response.text == "Hi"
    assert len(response.reasoning) == 2
    assert response.reasoning[0].text == "Think"
    assert response.reasoning[0].metadata["amazon-bedrock"] == {"signature": "sig"}
    assert response.reasoning[1].text == ""
    assert response.reasoning[1].metadata["amazon-bedrock"] == {"redactedContent": "aGlkZGVu"}

    prompt = Pr.make(
        [
            Pr.UserMessage([Pr.TextPart("Hello")]),
            Pr.AssistantMessage(
                [
                    Pr.ReasoningPart("Think", options={"amazon-bedrock": {"signature": "sig"}}),
                    Pr.ReasoningPart(
                        "", options={"amazon-bedrock": {"redactedContent": "aGlkZGVu"}}
                    ),
                    Pr.TextPart("Hi"),
                ]
            ),
            Pr.UserMessage([Pr.TextPart("Next")]),
        ]
    )
    yield from _provided(lm.generate_text(prompt), http)
    assert body_json(http.requests[1])["messages"][1] == {
        "role": "assistant",
        "content": [
            {"reasoningContent": {"reasoningText": {"text": "Think", "signature": "sig"}}},
            {"reasoningContent": {"redactedContent": "aGlkZGVu"}},
            {"text": "Hi"},
        ],
    }


@testing.effect
def test_appends_cache_points():
    """AmazonBedrockLanguageModel / generateText / appends cache points after system and
    message content"""
    http = _replying(converse_response([{"text": "Hi"}]))
    cache_point: Pr.ProviderOptions = {"amazon-bedrock": {"cachePoint": {"type": "default"}}}
    prompt = Pr.make(
        [
            Pr.SystemMessage("Be brief", options=cache_point),
            Pr.UserMessage([Pr.TextPart("Hello")], options=cache_point),
        ]
    )
    yield from _provided(lm.generate_text(prompt), http)
    body = body_json(http.requests[0])
    assert body["system"] == [{"text": "Be brief"}, {"cachePoint": {"type": "default"}}]
    assert body["messages"][0]["content"] == [
        {"text": "Hello"},
        {"cachePoint": {"type": "default"}},
    ]


@testing.effect
def test_encodes_files():
    """AmazonBedrockLanguageModel / generateText / encodes image and document file parts"""
    http = _replying(converse_response([{"text": "Hi"}]))
    png = (
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAAC0lEQVR4nGP4DwQACfsD"
        "/fteaysAAAAASUVORK5CYII="
    )
    prompt = Pr.make(
        [
            Pr.UserMessage(
                [
                    Pr.FilePart("image/png", png),
                    Pr.FilePart("application/pdf", bytes([0x25, 0x50, 0x44, 0x46]), "report"),
                    Pr.TextPart("Summarize these"),
                ]
            )
        ]
    )
    yield from _provided(lm.generate_text(prompt), http)
    assert body_json(http.requests[0])["messages"][0]["content"] == [
        {"image": {"format": "png", "source": {"bytes": png}}},
        {"document": {"format": "pdf", "name": "report", "source": {"bytes": "JVBERg=="}}},
        {"text": "Summarize these"},
    ]


@testing.effect
def test_rejects_unsupported_media_types():
    """AmazonBedrockLanguageModel / generateText / rejects unsupported file media types"""
    http = _replying(converse_response([{"text": "Hi"}]))
    prompt = Pr.make([Pr.UserMessage([Pr.FilePart("audio/mpeg", bytes([1, 2, 3]))])])
    error = yield from _provided(lm.generate_text(prompt).flip(), http)
    assert isinstance(error, E.AiError)
    assert isinstance(error.reason, E.InvalidUserInputError)
    assert http.requests == []


_STOP_REASONS: list[tuple[str, FinishReason]] = [
    ("end_turn", "stop"),
    ("stop_sequence", "stop"),
    ("tool_use", "tool-calls"),
    ("max_tokens", "length"),
    ("model_context_window_exceeded", "length"),
    ("guardrail_intervened", "content-filter"),
    ("content_filtered", "content-filter"),
    ("some_future_reason", "other"),
]


@pytest.mark.parametrize(
    ("stop_reason", "finish_reason"),
    _STOP_REASONS,
    ids=[f"maps stop reason {stop} to {finish}" for stop, finish in _STOP_REASONS],
)
@testing.effect
def test_maps_stop_reason(stop_reason: str, finish_reason: FinishReason):
    """AmazonBedrockLanguageModel / generateText / maps stop reason each Converse stop reason
    to its finish reason"""
    http = _replying(converse_response([{"text": "Hi"}], stop_reason))
    response = yield from _provided(lm.generate_text("Hello"), http)
    assert response.finish_reason == finish_reason


class Summary(TypedDict):
    title: str


@testing.effect
def test_forces_object_tool():
    """AmazonBedrockLanguageModel / generateObject / forces a tool for structured output by
    default"""
    http = _replying(
        converse_response(
            [
                {
                    "toolUse": {
                        "toolUseId": "tooluse_summary",
                        "name": "summary",
                        "input": {"title": "Rain"},
                    }
                }
            ],
            "tool_use",
        )
    )
    response = yield from _provided(
        lm.generate_object(
            "Give a title for a story about rain.", schema=S.Struct(Summary), object_name="summary"
        ),
        http,
    )
    body = body_json(http.requests[0])
    assert [tool["toolSpec"]["name"] for tool in body["toolConfig"]["tools"]] == ["summary"]
    assert body["toolConfig"]["toolChoice"] == {"tool": {"name": "summary"}}
    assert "outputConfig" not in body
    assert response.value == {"title": "Rain"}
    assert response.finish_reason == "stop"


@testing.effect
def test_native_structured_output():
    """AmazonBedrockLanguageModel / generateObject / uses native structured output when
    structuredOutputs is enabled"""
    http = _replying(converse_response([{"text": json.dumps({"title": "Rain"})}]))
    response = yield from _provided(
        lm.generate_object(
            "Give a title for a story about rain.", schema=S.Struct(Summary), object_name="summary"
        ),
        http,
        {"structured_outputs": True},
    )
    body = body_json(http.requests[0])
    assert "toolConfig" not in body
    text_format = body["outputConfig"]["textFormat"]
    assert text_format["type"] == "json_schema"
    json_schema = text_format["structure"]["jsonSchema"]
    assert json_schema["name"] == "summary"
    assert json.loads(json_schema["schema"])["properties"]["title"]["type"] == "string"
    assert response.value == {"title": "Rain"}


@testing.effect
def test_streams_text_tool_calls_and_usage():
    """AmazonBedrockLanguageModel / streamText / streams text, tool calls and usage from
    ConverseStream events"""
    http = _streaming(
        [
            event_frame("messageStart", {"role": "assistant"}),
            event_frame("contentBlockDelta", {"contentBlockIndex": 0, "delta": {"text": "Hello"}}),
            event_frame(
                "contentBlockDelta", {"contentBlockIndex": 0, "delta": {"text": ", world"}}
            ),
            event_frame("contentBlockStop", {"contentBlockIndex": 0}),
            event_frame(
                "contentBlockStart",
                {
                    "contentBlockIndex": 1,
                    "start": {"toolUse": {"toolUseId": "tooluse_1", "name": "Weather"}},
                },
            ),
            event_frame(
                "contentBlockDelta",
                {"contentBlockIndex": 1, "delta": {"toolUse": {"input": '{"city":'}}},
            ),
            event_frame(
                "contentBlockDelta",
                {"contentBlockIndex": 1, "delta": {"toolUse": {"input": '"SF"}'}}},
            ),
            event_frame("contentBlockStop", {"contentBlockIndex": 1}),
            event_frame("messageStop", {"stopReason": "tool_use"}),
            event_frame(
                "metadata",
                {
                    "usage": {
                        "inputTokens": 10,
                        "outputTokens": 5,
                        "totalTokens": 15,
                        "cacheReadInputTokens": 4,
                    },
                    "metrics": {"latencyMs": 1},
                },
            ),
        ]
    )
    parts = yield from _provided(
        lm.stream_text(
            "What is the weather in SF?", toolkit=toolkit, disable_tool_call_resolution=True
        ).run_collect(),
        http,
    )
    assert http.requests[0].url.endswith(f"/model/{ENCODED_MODEL_ID}/converse-stream")
    assert _text(parts) == "Hello, world"
    call = next(part for part in parts if isinstance(part, R.ToolCallPart))
    assert (call.id, call.name, call.params) == ("tooluse_1", "Weather", {"city": "SF"})
    finish = next(part for part in parts if isinstance(part, R.FinishPart))
    assert finish.reason == "tool-calls"
    assert finish.usage.input_tokens == R.InputTokens(
        uncached=10, total=14, cache_read=4, cache_write=None
    )
    assert finish.usage.output_tokens.total == 5


@testing.effect
def test_joins_redacted_reasoning_chunks():
    """AmazonBedrockLanguageModel / streamText / joins redacted reasoning streamed as several
    base64 chunks"""
    # The bytes 01 02 03 04, streamed as two chunks that are not a multiple of
    # 3 bytes, so each chunk's base64 carries its own padding.
    http = _streaming(
        [
            event_frame("messageStart", {"role": "assistant"}),
            event_frame(
                "contentBlockDelta",
                {
                    "contentBlockIndex": 0,
                    "delta": {"reasoningContent": {"redactedContent": "AQI="}},
                },
            ),
            event_frame(
                "contentBlockDelta",
                {
                    "contentBlockIndex": 0,
                    "delta": {"reasoningContent": {"redactedContent": "AwQ="}},
                },
            ),
            event_frame("contentBlockStop", {"contentBlockIndex": 0}),
            event_frame("messageStop", {"stopReason": "end_turn"}),
            _usage_frame(),
        ]
    )
    parts = yield from _provided(lm.stream_text("Hello").run_collect(), http)
    assert {"redactedContent": "AQIDBA=="} in _reasoning_metadata(parts)


@testing.effect
def test_ignores_unmodelled_stream_events():
    """AmazonBedrockLanguageModel / streamText / ignores stream events it does not model"""
    http = _streaming(
        [
            event_frame("messageStart", {"role": "assistant"}),
            event_frame("someFutureEvent", {"detail": 1}),
            event_frame("contentBlockDelta", {"contentBlockIndex": 0, "delta": {"text": "Hi"}}),
            event_frame("contentBlockStop", {"contentBlockIndex": 0}),
            event_frame("messageStop", {"stopReason": "end_turn"}),
            _usage_frame(),
        ]
    )
    parts = yield from _provided(lm.stream_text("Hello").run_collect(), http)
    assert _text(parts) == "Hi"
    finish = next(part for part in parts if isinstance(part, R.FinishPart))
    assert finish.reason == "stop"


@testing.effect
def test_streams_reasoning_signature():
    """AmazonBedrockLanguageModel / streamText / streams reasoning deltas with their
    signature"""
    http = _streaming(
        [
            event_frame("messageStart", {"role": "assistant"}),
            event_frame(
                "contentBlockDelta",
                {"contentBlockIndex": 0, "delta": {"reasoningContent": {"text": "Think"}}},
            ),
            event_frame(
                "contentBlockDelta",
                {"contentBlockIndex": 0, "delta": {"reasoningContent": {"signature": "sig"}}},
            ),
            event_frame("contentBlockStop", {"contentBlockIndex": 0}),
            event_frame("contentBlockDelta", {"contentBlockIndex": 1, "delta": {"text": "Hi"}}),
            event_frame("contentBlockStop", {"contentBlockIndex": 1}),
            event_frame("messageStop", {"stopReason": "end_turn"}),
            _usage_frame(),
        ]
    )
    parts = yield from _provided(lm.stream_text("Hello").run_collect(), http)
    reasoning = "".join(part.delta for part in parts if isinstance(part, R.ReasoningDeltaPart))
    assert reasoning == "Think"
    assert {"signature": "sig"} in _reasoning_metadata(parts)
    assert _text(parts) == "Hi"
