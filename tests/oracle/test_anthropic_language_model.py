"""Ports of Effect's ``packages/ai/anthropic/test/AnthropicLanguageModel.test.ts``.
Each docstring is the Effect test title (with its ``describe``). Responses
are recorded JSON or Server-Sent Events answered by a mocked
``HttpClient``; no test reaches the Anthropic API.

Every title is ported.
"""

from __future__ import annotations

# pyright: reportUnknownVariableType=false, reportUnknownArgumentType=false
# pyright: reportUnknownMemberType=false, reportUnknownLambdaType=false
import json
from collections.abc import Sequence
from typing import Any, TypedDict

import pytest

import pyfect as fx
from pyfect import schema as S
from pyfect import testing
from pyfect.ai import ai_error as E
from pyfect.ai import language_model as lm
from pyfect.ai import prompt as Pr
from pyfect.ai import response as R
from pyfect.ai import tool as T
from pyfect.ai import toolkit as K
from pyfect.ai.anthropic import client
from pyfect.ai.anthropic import language_model as alm
from pyfect.ai.anthropic import tool as AT
from pyfect.ai.anthropic_structured_output import to_codec_anthropic
from pyfect.layer import Layer
from pyfect.redacted import make as redact
from pyfect.result import Ok

from ._ai import SCREENSHOT_PNG, screenshot_prompt
from ._ai_http import MockHttp, json_response, meta, mock_json, mock_sse, recording_tracer
from ._ai_http import span_named as _span

_LEGACY = "claude-sonnet-4-20250514"


def _provided(
    effect: fx.Effect[Any, Any, Any],
    mock: MockHttp,
    model: str = _LEGACY,
    config: alm.ConfigService | None = None,
    *layers: Layer[Any, Any, Any],
) -> fx.Effect[Any, Any, Any]:
    for extra in layers:
        effect = effect.pipe(fx.provide(extra))
    return (
        effect.pipe(fx.provide(alm.model(model, config).layer))
        .pipe(fx.provide(client.layer(api_key=redact("sk-test-key"))))
        .pipe(fx.provide(mock.layer))
    )


def _usage(**fields: Any) -> dict[str, Any]:
    return {"input_tokens": 10, "output_tokens": 5, **fields}


def _message(content: Sequence[object], **fields: Any) -> dict[str, Any]:
    return {
        "id": "msg_test_1",
        "type": "message",
        "role": "assistant",
        "model": _LEGACY,
        "content": list(content),
        "stop_reason": "end_turn",
        "stop_sequence": None,
        "usage": _usage(),
        **fields,
    }


def _done() -> dict[str, Any]:
    return _message([{"type": "text", "text": "Done"}])


def _start(model: str = _LEGACY, **usage: Any) -> dict[str, Any]:
    return {
        "type": "message_start",
        "message": {
            "id": "msg_test_1",
            "type": "message",
            "role": "assistant",
            "model": model,
            "content": [],
            "stop_reason": None,
            "stop_sequence": None,
            "usage": {"input_tokens": 10, "output_tokens": 0, **usage},
        },
    }


def _delta(stop_reason: str = "end_turn", **usage: Any) -> dict[str, Any]:
    return {
        "type": "message_delta",
        "delta": {"stop_reason": stop_reason, "stop_sequence": None},
        "usage": {"output_tokens": 5, **usage},
    }


_STOP = {"type": "message_stop"}


def _tool_events(block: dict[str, Any], *partials: str) -> list[object]:
    return [
        _start(),
        {"type": "content_block_start", "index": 0, "content_block": block},
        *(
            {
                "type": "content_block_delta",
                "index": 0,
                "delta": {"type": "input_json_delta", "partial_json": p},
            }
            for p in partials
        ),
        {"type": "content_block_stop", "index": 0},
        _delta("tool_use"),
        _STOP,
    ]


def _first[A](parts: Sequence[object], kind: type[A]) -> A:
    return next(part for part in parts if isinstance(part, kind))


class Pattern(TypedDict):
    pattern: str


class Query(TypedDict):
    query: str


class City(TypedDict):
    city: str


class Title(TypedDict):
    title: str


class Person(TypedDict):
    name: str
    age: float


GlobTool = T.make(
    "GlobTool", description="Search for files", parameters=S.Struct(Pattern), success=S.String
)
GlobToolkit = K.make(GlobTool)
GlobLayer = GlobToolkit.to_layer(GlobTool.handler(lambda _, __: fx.succeed("found.ts")))


# streamText ----------------------------------------------------------------------------


@testing.effect
def test_stream_span_usage():
    """streamText / reports total input tokens and cache usage on the span"""
    tracer, spans = recording_tracer()
    mock = mock_sse(
        [
            _start(cache_creation_input_tokens=20, cache_read_input_tokens=30),
            _delta(
                cache_creation_input_tokens=None, cache_read_input_tokens=None, input_tokens=None
            ),
            _STOP,
        ]
    )
    parts = yield from _provided(lm.stream_text("Hello").run_collect(), mock).with_tracer(tracer)
    finish = _first(parts, R.FinishPart)
    assert finish.usage.input_tokens == R.InputTokens(
        uncached=10, total=60, cache_read=30, cache_write=20
    )
    attributes = _span(spans, "LanguageModel.streamText").attributes
    assert attributes["gen_ai.usage.input_tokens"] == 60
    assert attributes["gen_ai.usage.cache_read.input_tokens"] == 30
    assert attributes["gen_ai.usage.cache_write.input_tokens"] == 20
    assert attributes["gen_ai.usage.output_tokens"] == 5


@testing.effect
def test_stream_minimal_usage():
    """streamText / accepts minimal usage and preserves input and cache tokens omitted from message_delta"""  # noqa: E501
    mock = mock_sse(
        [
            _start(cache_creation_input_tokens=20, cache_read_input_tokens=30, output_tokens=1),
            _delta(),
            _STOP,
        ]
    )
    parts = yield from _provided(lm.stream_text("Hello").run_collect(), mock)
    finish = _first(parts, R.FinishPart)
    assert finish.usage.input_tokens == R.InputTokens(
        uncached=10, total=60, cache_read=30, cache_write=20
    )
    assert finish.usage.output_tokens.total == 5


@pytest.mark.parametrize("geo", [{}, {"inference_geo": "us"}], ids=["missing", "string"])
@testing.effect
def test_stream_inference_geo(geo: dict[str, str]):
    """streamText / accepts ${label} usage.inference_geo in message_start"""
    mock = mock_sse(
        [
            _start(cache_creation_input_tokens=None, cache_read_input_tokens=None, **geo),
            {
                "type": "content_block_start",
                "index": 0,
                "content_block": {"type": "text", "text": "Hello"},
            },
            {
                "type": "content_block_delta",
                "index": 0,
                "delta": {"type": "text_delta", "text": "Hello"},
            },
            {"type": "content_block_stop", "index": 0},
            _delta(),
            _STOP,
        ]
    )
    parts = yield from _provided(lm.stream_text("Hello").run_collect(), mock)
    assert any(isinstance(p, R.TextDeltaPart) and p.delta == "Hello" for p in parts)


@testing.effect
def test_stream_tool_params():
    """streamText / decodes tool call params in content_block_stop"""
    block = {"type": "tool_use", "id": "toolu_test_1", "name": "GlobTool", "input": {}}
    mock = mock_sse(_tool_events(block, json.dumps({"pattern": "*.ts"})))
    parts = yield from _provided(
        lm.stream_text(
            "find ts files", toolkit=GlobToolkit, disable_tool_call_resolution=True
        ).run_collect(),
        mock,
        _LEGACY,
        None,
        GlobLayer,
    )
    call = _first(parts, R.ToolCallPart)
    assert call.name == "GlobTool"
    assert call.params == {"pattern": "*.ts"}


@pytest.mark.parametrize("block_type", ["tool_use", "server_tool_use"])
@testing.effect
def test_stream_malformed_tool_json(block_type: str):
    """streamText / fails with AiError for malformed streamed ${blockType} JSON"""
    name = "GlobTool" if block_type == "tool_use" else "web_search"
    id = "toolu_test_1" if block_type == "tool_use" else "srvtoolu_test_1"
    block = {"type": block_type, "id": id, "name": name, "input": {}}
    events = _tool_events(block, '{"pattern":', '"*.ts')
    toolkit = K.make(T.make("GlobTool", parameters=S.Struct(Pattern)), AT.WebSearch_20250305({}))
    exit = yield from _provided(
        lm.stream_text("find ts files", toolkit=toolkit, disable_tool_call_resolution=True)
        .run_collect()
        .exit(),
        mock_sse(events),
    )
    assert isinstance(exit, fx.Failure)
    assert not exit.cause.has_dies
    error = exit.cause.find_error()
    assert isinstance(error, Ok)
    assert isinstance(error.value, E.AiError)
    assert isinstance(error.value.reason, E.ToolParameterValidationError)


@testing.effect
def test_stream_invalid_params_return_mode():
    """streamText / routes invalid tool call params through failureMode: return without failing the stream"""  # noqa: E501
    tool = T.make(
        "GlobTool",
        description="Search for files",
        failure_mode="return",
        parameters=S.Struct(Pattern),
        success=S.String,
        failure=S.String,
    )
    toolkit = K.make(tool)
    layer = toolkit.to_layer(tool.handler(lambda _, __: fx.succeed("found.ts")))
    block = {"type": "tool_use", "id": "toolu_test_1", "name": "GlobTool", "input": {}}
    mock = mock_sse(_tool_events(block, json.dumps({"pattern": 123})))
    parts = yield from _provided(
        lm.stream_text("find ts files", toolkit=toolkit).run_collect(), mock, _LEGACY, None, layer
    )
    result = _first(parts, R.ToolResultFailure)
    assert result.is_failure
    assert isinstance(result.result, E.AiError)
    assert isinstance(result.result.reason, E.ToolParameterValidationError)


@pytest.mark.parametrize(
    ("provider_name", "params", "expected"),
    [
        (
            "bash_code_execution",
            {"command": "pwd"},
            {"type": "bash_code_execution", "command": "pwd"},
        ),
        (
            "text_editor_code_execution",
            {"command": "view", "path": "/tmp/example.txt"},
            {"type": "text_editor_code_execution", "command": "view", "path": "/tmp/example.txt"},
        ),
    ],
)
@testing.effect
def test_stream_code_execution_params(provider_name: str, params: object, expected: object):
    """streamText / emits valid JSON for streamed ${providerName} parameters"""
    block = {"type": "server_tool_use", "id": "srvtoolu_test_1", "name": provider_name, "input": {}}
    toolkit = K.make(AT.CodeExecution_20250522())
    parts = yield from _provided(
        lm.stream_text("run pwd", toolkit=toolkit, disable_tool_call_resolution=True).run_collect(),
        mock_sse(_tool_events(block, json.dumps(params))),
    )
    assert json.loads(_first(parts, R.ToolParamsDeltaPart).delta) == expected
    assert _first(parts, R.ToolCallPart).params == expected


@testing.effect
def test_stream_unknown_model_id():
    """streamText / decodes responses for a model id that is not a known literal"""
    model = "claude-not-a-known-model-id"
    mock = mock_sse(
        [
            _start(model),
            {
                "type": "content_block_start",
                "index": 0,
                "content_block": {"type": "text", "text": ""},
            },
            {
                "type": "content_block_delta",
                "index": 0,
                "delta": {"type": "text_delta", "text": "Hello"},
            },
            {"type": "content_block_stop", "index": 0},
            _delta(),
            _STOP,
        ]
    )
    parts = yield from _provided(lm.stream_text("say hello").run_collect(), mock, model)
    assert _first(parts, R.ResponseMetadataPart).model_id == model
    assert _first(parts, R.TextDeltaPart).delta == "Hello"


_FALLBACK = {
    "type": "fallback",
    "from": {"model": "claude-opus-5-5"},
    "to": {"model": "claude-opus-4-8"},
    "trigger": {"type": "refusal", "category": "cyber"},
}


def _fallback_metadata(parts: Sequence[object]) -> R.ResponseMetadataPart:
    return next(
        p
        for p in parts
        if isinstance(p, R.ResponseMetadataPart) and meta(p.metadata, "anthropic", "fallback")
    )


@testing.effect
def test_stream_fallback_block():
    """streamText / emits response metadata for a fallback block"""
    mock = mock_sse(
        [
            _start("claude-opus-4-8"),
            {"type": "content_block_start", "index": 0, "content_block": _FALLBACK},
            {"type": "content_block_stop", "index": 0},
            _delta(),
            _STOP,
        ]
    )
    parts = yield from _provided(lm.stream_text("Hello").run_collect(), mock, "claude-opus-5-5")
    metadata = _fallback_metadata(parts)
    assert metadata.model_id == "claude-opus-4-8"
    assert meta(metadata.metadata, "anthropic", "fallback") == _FALLBACK


# generateText --------------------------------------------------------------------------


@pytest.mark.parametrize("geo", [{}, {"inference_geo": "us"}], ids=["missing", "string"])
@testing.effect
def test_generate_inference_geo(geo: dict[str, str]):
    """generateText / accepts ${label} usage.inference_geo in a message response"""
    mock = mock_json(_message([{"type": "text", "text": "Hello"}], usage=_usage(**geo)))
    response = yield from _provided(lm.generate_text("Hello"), mock)
    assert any(isinstance(p, R.TextPart) and p.text == "Hello" for p in response.content)


@testing.effect
def test_generate_minimal_usage():
    """generateText / accepts minimal usage in a message response"""
    body = _message(
        [{"type": "text", "text": "Hello"}], usage={"input_tokens": 3, "output_tokens": 1}
    )
    response = yield from _provided(lm.generate_text("Hello"), mock_json(body))
    assert response.usage.input_tokens == R.InputTokens(
        uncached=3, total=3, cache_read=0, cache_write=0
    )


@testing.effect
def test_generate_fallback_iterations():
    """generateText / emits response metadata for a fallback block and keeps fallback usage iterations"""  # noqa: E501
    iteration = {"cache_creation_input_tokens": 0, "cache_read_input_tokens": 0, "input_tokens": 10}
    iterations = [
        {"type": "message", "model": "claude-opus-5-5", **iteration, "output_tokens": 0},
        {"type": "fallback_message", "model": "claude-opus-4-8", **iteration, "output_tokens": 5},
    ]
    body = _message(
        [_FALLBACK, {"type": "text", "text": "Hello"}],
        model="claude-opus-4-8",
        usage=_usage(iterations=iterations),
    )
    response = yield from _provided(lm.generate_text("Hello"), mock_json(body), "claude-opus-5-5")
    metadata = _fallback_metadata(response.content)
    assert metadata.model_id == "claude-opus-4-8"
    assert meta(metadata.metadata, "anthropic", "fallback") == _FALLBACK
    finish = _first(response.content, R.FinishPart)
    assert meta(finish.metadata, "anthropic", "usage", "iterations") == iterations


@testing.effect
def test_generate_context_window_exceeded():
    """generateText / reports length when the model context window is exceeded"""
    body = _message(
        [{"type": "text", "text": "Hello"}], stop_reason="model_context_window_exceeded"
    )
    response = yield from _provided(lm.generate_text("Hello"), mock_json(body))
    assert response.finish_reason == "length"


@testing.effect
def test_generate_span_usage():
    """generateText / reports total input tokens and cache usage on the span"""
    tracer, spans = recording_tracer()
    body = _message(
        [{"type": "text", "text": "Hello"}],
        usage=_usage(cache_creation_input_tokens=20, cache_read_input_tokens=30),
    )
    yield from _provided(lm.generate_text("Hello"), mock_json(body)).with_tracer(tracer)
    attributes = _span(spans, "LanguageModel.generateText").attributes
    assert attributes["gen_ai.provider.name"] == "anthropic"
    assert attributes["gen_ai.usage.input_tokens"] == 60
    assert attributes["gen_ai.usage.cache_read.input_tokens"] == 30
    assert attributes["gen_ai.usage.cache_write.input_tokens"] == 20
    assert attributes["gen_ai.usage.output_tokens"] == 5


@testing.effect
def test_generate_omits_strict_json_schema():
    """generateText / omits strictJsonSchema from the request while preserving tool strictness"""
    model = "claude-sonnet-4-5"
    mock = mock_json(_message([{"type": "text", "text": "Hello"}], model=model))
    toolkit = K.make(T.make("Search", parameters=S.Struct(Query), success=S.String))
    yield from _provided(
        lm.generate_text("Hello", toolkit=toolkit, disable_tool_call_resolution=True),
        mock,
        model,
        {"strict_json_schema": False},
    )
    (body,) = mock.bodies
    assert body["model"] == model
    assert body["tools"][0]["name"] == "Search"
    assert body["tools"][0]["strict"] is False
    assert "strictJsonSchema" not in body
    assert "strict_json_schema" not in body


@testing.effect
def test_generate_string_tool_results():
    """generateText / preserves string tool results"""
    mock = mock_json(_done())
    prompt = Pr.make(
        [
            {"role": "user", "content": "Use the tool"},
            {
                "role": "assistant",
                "content": [
                    {"type": "tool-call", "id": "call_text", "name": "text_tool", "params": {}}
                ],
            },
            {
                "role": "tool",
                "content": [
                    {
                        "type": "tool-result",
                        "id": "call_text",
                        "name": "text_tool",
                        "result": "PLAIN_TEXT_SENTINEL\n",
                        "isFailure": False,
                    }
                ],
            },
        ]
    )
    yield from _provided(lm.generate_text(prompt, disable_tool_call_resolution=True), mock)
    (body,) = mock.bodies
    result = next(
        block
        for message in body["messages"]
        if isinstance(message["content"], list)
        for block in message["content"]
        if block["type"] == "tool_result"
    )
    assert result["content"] == "PLAIN_TEXT_SENTINEL\n"


_PDF = "JVBERi0xLjcK"


@pytest.mark.parametrize(
    ("model_output", "content"),
    [
        pytest.param(
            [
                Pr.TextPart(text="Screenshot of /home"),
                Pr.FilePart(media_type="image/png", data=SCREENSHOT_PNG),
                Pr.FilePart(
                    media_type="application/pdf", data=f"data:application/pdf;base64,{_PDF}"
                ),
            ],
            [
                {"type": "text", "text": "Screenshot of /home"},
                {
                    "type": "image",
                    "source": {"type": "base64", "media_type": "image/png", "data": SCREENSHOT_PNG},
                },
                {
                    "type": "document",
                    "source": {"type": "base64", "media_type": "application/pdf", "data": _PDF},
                    "title": None,
                },
            ],
            id="as native content blocks",
        ),
        pytest.param([], "", id="without the result when it is empty"),
    ],
)
@testing.effect
def test_generate_tool_result_model_output(
    model_output: list[Pr.ToolModelOutputPart], content: Any
):
    """generateText / sends tool result model output as native content blocks / without the
    result when it is empty"""
    mock = mock_json(_done())
    yield from _provided(
        lm.generate_text(screenshot_prompt(model_output), disable_tool_call_resolution=True),
        mock,
        "claude-sonnet-4-20250514",
    )
    (body,) = mock.bodies
    result = next(
        block
        for message in body["messages"]
        if isinstance(message["content"], list)
        for block in message["content"]
        if block["type"] == "tool_result"
    )
    assert result["tool_use_id"] == "call_screenshot"
    sent = result["content"]
    if isinstance(sent, list):
        sent = [{k: v for k, v in block.items() if k != "cache_control"} for block in sent]
    assert sent == content


@testing.effect
def test_generate_base64_image():
    """generateText / preserves base64 image string payloads"""
    data = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAAC0lEQVR4nGP4DwQACfsD/fteaysAAAAASUVORK5CYII="  # noqa: E501
    mock = mock_json(_done())
    prompt = [Pr.UserMessage(content=(Pr.FilePart(media_type="image/png", data=data),))]
    yield from _provided(lm.generate_text(prompt), mock)
    assert mock.bodies[0]["messages"][0]["content"][0]["source"]["data"] == data


@testing.effect
def test_generate_dynamic_tools():
    """generateText / encodes dynamic tools"""
    schema: Any = {"properties": {"query": {"type": "string"}}}
    tool = T.dynamic("DynamicTool", description="A dynamic tool", parameters=schema)
    mock = mock_json(_done())
    yield from _provided(
        lm.generate_text(
            "Use the dynamic tool", toolkit=K.make(tool), disable_tool_call_resolution=True
        ),
        mock,
    )
    dynamic = next(t for t in mock.bodies[0]["tools"] if t["name"] == "DynamicTool")
    assert dynamic["description"] == "A dynamic tool"
    assert dynamic["input_schema"] == schema


@testing.effect
def test_generate_non_object_parameters():
    """generateText / names the tool when its parameters are not an object schema"""
    toolkit = K.make(T.make("NoParams", parameters=S.String))
    mock = MockHttp(lambda _: fx.die(RuntimeError("unexpected request")))
    error = yield from _provided(
        lm.generate_text("Use the tool", toolkit=toolkit, disable_tool_call_resolution=True).flip(),
        mock,
    )
    assert isinstance(error.reason, E.UnsupportedSchemaError)
    assert '"NoParams"' in error.message
    assert "Tool.EmptyParams" in error.message


@testing.effect
def test_generate_provider_executed_web_search():
    """generateText / serializes provider-executed web_search parts from the assistant message"""
    mock = mock_json(_message([{"type": "text", "text": "You're welcome"}], id="msg_test_2"))
    results = [
        {
            "type": "web_search_result",
            "url": "https://example.com/gold",
            "title": "Gold price",
            "encrypted_content": "encrypted",
            "page_age": None,
        }
    ]
    history = Pr.from_response_parts(
        [
            R.ToolCallPart(
                id="srvtoolu_1",
                name="AnthropicWebSearch",
                params={"query": "gold price today"},
                provider_executed=True,
            ),
            R.ToolResultSuccess(
                id="srvtoolu_1",
                name="AnthropicWebSearch",
                result=results,
                encoded_result=results,
                provider_executed=True,
            ),
            R.TextPart(text="Gold is around $4,000."),
        ]
    )
    prompt = Pr.make("what is the gold price?").concat(history).concat("thanks")
    yield from _provided(
        lm.generate_text(
            prompt,
            toolkit=K.make(AT.WebSearch_20250305({})),
            disable_tool_call_resolution=True,
        ),
        mock,
    )
    (body,) = mock.bodies
    assistant = next(m for m in body["messages"] if m["role"] == "assistant")
    server = next(b for b in assistant["content"] if b["type"] == "server_tool_use")
    assert server["id"] == "srvtoolu_1"
    assert server["name"] == "web_search"
    search = next(b for b in assistant["content"] if b["type"] == "web_search_tool_result")
    assert search["tool_use_id"] == "srvtoolu_1"
    client_results = [
        b
        for m in body["messages"]
        if isinstance(m["content"], list)
        for b in m["content"]
        if b["type"] == "tool_result"
    ]
    assert client_results == []


@testing.effect
def test_generate_plaintext_bytes():
    """generateText / encodes plaintext bytes as UTF-8 text"""
    mock = mock_json(_message([{"type": "text", "text": "ok"}], id="msg_1"))
    prompt = [Pr.UserMessage(content=(Pr.FilePart(media_type="text/plain", data=b"hello"),))]
    yield from _provided(lm.generate_text(prompt), mock)
    assert mock.bodies[0]["messages"][0]["content"][0]["source"]["data"] == "hello"


# generateObject ------------------------------------------------------------------------


def _object_request(model: str, config: alm.ConfigService | None = None) -> Any:
    mock = mock_json(
        _message([{"type": "text", "text": json.dumps({"name": "John", "age": 30})}], model=model)
    )
    yield from _provided(
        lm.generate_object("Give me a person", schema=S.Struct(Person)).ignore(),
        mock,
        model,
        config,
    )
    return mock.bodies[0]


@testing.effect
def test_object_claude_4_6():
    """generateObject / uses native structured output and 128K for Claude 4.6"""
    body = yield from _object_request("claude-opus-4-6")
    assert body["max_tokens"] == 128000
    assert body["output_config"]["format"]["type"] == "json_schema"


@testing.effect
def test_object_future_model():
    """generateObject / uses optimistic modern defaults for an unknown future model"""
    body = yield from _object_request("claude-sonnet-6-0")
    assert body["max_tokens"] == 128000
    assert body["output_config"]["format"]["type"] == "json_schema"


@testing.effect
def test_object_legacy_model():
    """generateObject / preserves frozen legacy model exceptions"""
    body = yield from _object_request(_LEGACY)
    assert body["max_tokens"] == 64000
    assert "output_config" not in body


@testing.effect
def test_object_disable_structured_outputs():
    """generateObject / can disable structured outputs for a modern model"""
    body = yield from _object_request("claude-sonnet-6-0", {"structured_outputs": False})
    assert body["max_tokens"] == 128000
    assert "output_config" not in body
    assert "structuredOutputs" not in body
    assert "structured_outputs" not in body


@testing.effect
def test_object_enable_structured_outputs():
    """generateObject / can enable structured outputs for a legacy model"""
    body = yield from _object_request(_LEGACY, {"structured_outputs": True})
    assert body["max_tokens"] == 64000
    assert body["output_config"]["format"]["type"] == "json_schema"
    assert "structured_outputs" not in body


def _summary(content: Sequence[object]) -> dict[str, Any]:
    return _message(
        content, id="msg_summary", model="claude-sonnet-4-6", stop_reason="tool_use", usage=_usage()
    )


@testing.effect
def test_object_fallback_response_tool():
    """generateObject / forces the fallback response tool and decodes its input alongside prose"""
    mock = mock_json(
        _summary(
            [
                {"type": "text", "text": "Here is the summary."},
                {
                    "type": "tool_use",
                    "id": "toolu_summary",
                    "name": "summary",
                    "input": {"title": "Rain"},
                },
            ]
        )
    )
    response = yield from _provided(
        lm.generate_object(
            "Give a title for a story about rain.", object_name="summary", schema=S.Struct(Title)
        ),
        mock,
        "claude-sonnet-4-6",
        {"structured_outputs": False},
    )
    (body,) = mock.bodies
    assert [tool["name"] for tool in body["tools"]] == ["summary"]
    assert body["tool_choice"] == {
        "type": "tool",
        "name": "summary",
        "disable_parallel_tool_use": True,
    }
    assert response.value == {"title": "Rain"}


@testing.effect
def test_object_native_json_with_tool_call():
    """generateObject / decodes native JSON alongside an ordinary tool call"""
    mock = mock_json(
        _summary(
            [
                {"type": "text", "text": json.dumps({"title": "Rain"})},
                {
                    "type": "tool_use",
                    "id": "toolu_weather",
                    "name": "Weather",
                    "input": {"city": "SF"},
                },
            ]
        )
    )
    weather = T.make("Weather", parameters=S.Struct(City), success=S.String)
    toolkit = K.make(weather)
    response = yield from _provided(
        lm.generate_object(
            "Give a title for a story about rain.",
            object_name="summary",
            schema=S.Struct(Title),
            toolkit=toolkit,
        ),
        mock,
        "claude-sonnet-4-6",
        None,
        toolkit.to_layer(weather.handler(lambda _, __: fx.succeed("Rain"))),
    )
    assert response.value == {"title": "Rain"}
    assert response.tool_calls[0].name == "Weather"


# system messages -----------------------------------------------------------------------


def _system_request(
    model: str, prompt: Pr.RawInput, config: alm.ConfigService | None = None
) -> Any:
    mock = mock_json(_message([{"type": "text", "text": "Done"}], model=model, usage=_usage()))
    yield from _provided(
        lm.generate_text(prompt, disable_tool_call_resolution=True), mock, model, config
    )
    return mock.bodies[0]


_CONVERSATION: Pr.RawInput = [
    {"role": "system", "content": "A"},
    {"role": "user", "content": "Question 1"},
    {"role": "assistant", "content": "Answer 1"},
    {"role": "system", "content": "B"},
    {"role": "user", "content": "Question 2"},
]


@testing.effect
def test_system_after_next_user_turn():
    """system messages / sends later system messages after the next user turn"""
    body = yield from _system_request("claude-sonnet-5-5", _CONVERSATION)
    assert [block["text"] for block in body["system"]] == ["A"]
    assert [m["role"] for m in body["messages"]] == ["user", "assistant", "user", "system"]
    assert body["messages"][-1] == {
        "role": "system",
        "content": [{"type": "text", "text": "B", "cache_control": None}],
    }


@testing.effect
def test_system_top_level_when_disabled():
    """system messages / sends every system message top-level when disabled"""
    body = yield from _system_request(
        "claude-sonnet-5-5", _CONVERSATION, {"mid_conversation_system_messages": False}
    )
    assert [block["text"] for block in body["system"]] == ["A", "B"]
    assert [m["role"] for m in body["messages"]] == ["user", "assistant", "user"]
    assert "midConversationSystemMessages" not in body
    assert "mid_conversation_system_messages" not in body


@testing.effect
def test_system_top_level_in_order():
    """system messages / sends every system message top-level in order when one cannot follow a user turn"""  # noqa: E501
    body = yield from _system_request(
        "claude-sonnet-5-5",
        [
            {"role": "system", "content": "A"},
            {"role": "user", "content": "Question"},
            {"role": "system", "content": "B"},
            {"role": "assistant", "content": "Answer"},
            {"role": "system", "content": "C"},
        ],
    )
    assert [block["text"] for block in body["system"]] == ["A", "B", "C"]
    assert [m["role"] for m in body["messages"]] == ["user", "assistant"]


@testing.effect
def test_system_support_for_model():
    """system messages / reports support for the requested model"""

    def check(model: lm.Service) -> Any:
        supported = model.supports_system_messages_in_history
        assert supported is not None
        assert (yield from supported) is True
        older = yield from supported.pipe(alm.with_config_override({"model": "claude-sonnet-5"}))
        assert older is False

    yield from _provided(
        lm.LanguageModel().flat_map(lambda model: fx.gen(lambda: check(model))),
        MockHttp(lambda _: fx.die(RuntimeError("unexpected request"))),
        "claude-sonnet-5-5",
    )


# assistant cache control --------------------------------------------------------------

_EPHEMERAL = {"type": "ephemeral"}
_CACHED = {"anthropic": {"cacheControl": _EPHEMERAL}}
_THINKING: dict[str, Any] = {
    "type": "reasoning",
    "text": "Thinking",
    "options": {"anthropic": {"info": {"type": "thinking", "signature": "sig"}}},
}
_REDACTED: dict[str, Any] = {
    "type": "reasoning",
    "text": "",
    "options": {"anthropic": {"info": {"type": "redacted_thinking", "redactedData": "hidden"}}},
}


def _assistant_content(prompt: Pr.RawInput) -> Any:
    mock = mock_json(_done())
    yield from _provided(lm.generate_text(prompt, disable_tool_call_resolution=True), mock)
    return next(m for m in mock.bodies[0]["messages"] if m["role"] == "assistant")["content"]


@testing.effect
def test_cache_part_and_message_breakpoints():
    """assistant cache control / places part and message breakpoints without overriding a part's TTL"""  # noqa: E501
    one_hour = {"type": "ephemeral", "ttl": "1h"}
    call = {"type": "tool-call", "name": "lookup", "params": {}}
    content = yield from _assistant_content(
        [
            {"role": "user", "content": "Question"},
            {
                "role": "assistant",
                "content": [
                    {
                        "type": "text",
                        "text": "Answer",
                        "options": {"anthropic": {"cacheControl": one_hour}},
                    },
                    {**call, "id": "toolu_1"},
                    {**call, "id": "toolu_2", "options": {"anthropic": {"cacheControl": one_hour}}},
                ],
                "options": _CACHED,
            },
            {"role": "assistant", "content": [{**call, "id": "toolu_3"}], "options": _CACHED},
            {"role": "user", "content": "Thanks"},
        ]
    )
    assert content == [
        {"type": "text", "text": "Answer", "cache_control": one_hour},
        {"type": "tool_use", "id": "toolu_1", "name": "lookup", "input": {}},
        {
            "type": "tool_use",
            "id": "toolu_2",
            "name": "lookup",
            "input": {},
            "cache_control": one_hour,
        },
        {
            "type": "tool_use",
            "id": "toolu_3",
            "name": "lookup",
            "input": {},
            "cache_control": _EPHEMERAL,
        },
    ]


@testing.effect
def test_cache_breakpoint_before_thinking():
    """assistant cache control / places a message breakpoint before trailing thinking and skipped parts"""  # noqa: E501
    content = yield from _assistant_content(
        [
            {"role": "user", "content": "Question"},
            {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "Answer"},
                    _THINKING,
                    _REDACTED,
                    {"type": "file", "mediaType": "image/png", "data": "aGVsbG8="},
                ],
                "options": _CACHED,
            },
            {"role": "user", "content": "Thanks"},
        ]
    )
    assert content == [
        {"type": "text", "text": "Answer", "cache_control": _EPHEMERAL},
        {"type": "thinking", "thinking": "Thinking", "signature": "sig"},
        {"type": "redacted_thinking", "data": "hidden"},
    ]


def _with_cache(part: dict[str, Any]) -> dict[str, Any]:
    return {
        **part,
        "options": {"anthropic": {**part["options"]["anthropic"], **_CACHED["anthropic"]}},
    }


@testing.effect
def test_cache_thinking_only_breakpoints():
    """assistant cache control / drops thinking-only breakpoints without marking other parts or messages"""  # noqa: E501
    content = yield from _assistant_content(
        [
            {"role": "user", "content": "Question"},
            {"role": "assistant", "content": "Unmarked"},
            {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "Answer"},
                    _with_cache(_THINKING),
                    _with_cache(_REDACTED),
                ],
            },
            {"role": "assistant", "content": [_THINKING, _REDACTED], "options": _CACHED},
            {"role": "user", "content": "Thanks"},
        ]
    )
    assert content == [
        {"type": "text", "text": "Unmarked"},
        {"type": "text", "text": "Answer"},
        {"type": "thinking", "thinking": "Thinking", "signature": "sig"},
        {"type": "redacted_thinking", "data": "hidden"},
        {"type": "thinking", "thinking": "Thinking", "signature": "sig"},
        {"type": "redacted_thinking", "data": "hidden"},
    ]


# Memory tool --------------------------------------------------------------------------


def _memory(input: object, reply: str) -> Any:
    received: list[object] = []
    memory = AT.Memory_20250818({})
    toolkit = K.make(memory)

    def handle(params: object, _: object) -> fx.Effect[str]:
        received.append(params)
        return fx.succeed(reply)

    body = _message(
        [{"type": "tool_use", "id": "toolu_mem_1", "name": "memory", "input": input}],
        stop_reason="tool_use",
    )
    response = yield from _provided(
        lm.generate_text("check memory", toolkit=toolkit),
        MockHttp(lambda request: fx.succeed(json_response(request, body))),
        _LEGACY,
        None,
        toolkit.to_layer(memory.handler(handle)),
    )
    return received, response


@testing.effect
def test_memory_view():
    """Memory tool / resolves the provider wire name to the tool's custom name (view)"""
    received, response = yield from _memory(
        {"command": "view", "path": "/memories"}, "memory listing"
    )
    assert received == [{"command": "view", "path": "/memories"}]
    result = response.tool_results[0]
    assert result.name == "AnthropicMemory"
    assert result.result == "memory listing"


@testing.effect
def test_memory_create():
    """Memory tool / decodes the create command including file_text"""
    params = {"command": "create", "path": "/memories/notes.txt", "file_text": "hello world"}
    received, response = yield from _memory(
        params, "File created successfully at: /memories/notes.txt"
    )
    assert received == [params]
    assert response.tool_results[0].name == "AnthropicMemory"


# client provider tool parameters compile with the Anthropic codec ----------------------

_DISPLAY = {"displayWidthPx": 800, "displayHeightPx": 600}
_CLIENT_TOOLS = {
    "Bash_20241022": lambda: AT.Bash_20241022({}),
    "Bash_20250124": lambda: AT.Bash_20250124({}),
    "ComputerUse_20241022": lambda: AT.ComputerUse_20241022(_DISPLAY),
    "ComputerUse_20250124": lambda: AT.ComputerUse_20250124(_DISPLAY),
    "ComputerUse_20251124": lambda: AT.ComputerUse_20251124(_DISPLAY),
    "Memory_20250818": lambda: AT.Memory_20250818({}),
    "TextEditor_20241022": lambda: AT.TextEditor_20241022({}),
    "TextEditor_20250124": lambda: AT.TextEditor_20250124({}),
    "TextEditor_20250429": lambda: AT.TextEditor_20250429({}),
    "TextEditor_20250728": lambda: AT.TextEditor_20250728({}),
}


@pytest.mark.parametrize("name", list(_CLIENT_TOOLS))
def test_client_tool_parameters_compile(name: str):
    """client provider tool parameters compile with the Anthropic codec / ${name}"""
    assert to_codec_anthropic(_CLIENT_TOOLS[name]().parameters_schema).json_schema


class _ReadParams(TypedDict):
    path: str


@testing.effect
def test_stream_undeclared_calls_when_deferred():
    """streamText / streams undeclared tool calls when tool call validation is deferred"""
    read = T.make("Read", parameters=S.Struct(_ReadParams), success=S.String)
    toolkit = K.make(read)
    block = {"type": "tool_use", "id": "toolu_test_1", "name": "Write", "input": {}}
    mock = mock_sse(_tool_events(block, json.dumps({"path": "a"})))
    parts = yield from _provided(
        lm.stream_text(
            "use the tools",
            toolkit=toolkit,
            disable_tool_call_resolution=True,
            tool_call_validation="deferred",
        ).run_collect(),
        mock,
        _LEGACY,
        None,
        toolkit.to_layer(read.handler(lambda _, __: fx.succeed(""))),
    )
    assert [(p.name, p.params) for p in parts if isinstance(p, R.ToolCallPart)] == [
        ("Write", {"path": "a"})
    ]
