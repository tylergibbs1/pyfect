"""Ports of Effect's ``packages/ai/openrouter/test/OpenRouterLanguageModel.test.ts``.
Each docstring is the Effect test title (with its ``describe``). Responses
are recorded JSON or Server-Sent Events answered by a mocked
``HttpClient``."""

from __future__ import annotations

# pyright: reportUnknownVariableType=false, reportUnknownArgumentType=false
# pyright: reportUnknownMemberType=false, reportUnknownLambdaType=false
import json
from typing import Any, Required, TypedDict

import pytest

import pyfect as fx
from pyfect import schema as S
from pyfect import testing
from pyfect._url import Url
from pyfect.ai import ai_error as E
from pyfect.ai import language_model as lm
from pyfect.ai import model as M
from pyfect.ai import prompt as Pr
from pyfect.ai import response as R
from pyfect.ai import tool as T
from pyfect.ai import toolkit as K
from pyfect.ai.openrouter import client, language_model
from pyfect.context import Tag
from pyfect.redacted import make as redact
from pyfect.schema import getter as G
from pyfect.schema import transformation as Tr

from ._ai_http import MockHttp, json_response, mock_sse

GEMINI = "google/gemini-2.5-flash"
GPT = "openai/gpt-4o-mini"
CLAUDE = "anthropic/claude-sonnet-4.5"


def default_response(**overrides: Any) -> dict[str, Any]:
    """Effect's ``makeDefaultResponse``."""
    return {
        "id": "gen-test123",
        "choices": [
            {
                "finish_reason": "stop",
                "index": 0,
                "message": {"role": "assistant", "content": "Hello!"},
            }
        ],
        "created": 1234567890,
        "model": GEMINI,
        "object": "chat.completion",
        "system_fingerprint": None,
        **overrides,
    }


def mock(**overrides: Any) -> MockHttp:
    body = default_response(**overrides)
    return MockHttp(lambda request: fx.succeed(json_response(request, body)))


def stream_mock(events: list[Any]) -> MockHttp:
    return mock_sse([*events, "[DONE]"])


def _provided(
    effect: fx.Effect[Any, Any, Any],
    http: MockHttp,
    model: str = GEMINI,
    config: language_model.ModelConfig | None = None,
) -> fx.Effect[Any, Any, Any]:
    return (
        effect.pipe(fx.provide(language_model.model(model, config).layer))
        .pipe(fx.provide(client.layer(api_key=redact("sk-test-key"))))
        .pipe(fx.provide(http.layer))
    )


def _user_body(content: list[Any], model: str = GEMINI) -> fx.Effect[Any, Any, Any]:
    """The user message ``generate_text`` sends for ``content``."""
    http = mock()
    prompt = Pr.make([Pr.UserMessage(content=content)])
    return _provided(lm.generate_text(prompt), http, model).map(
        lambda _: next(m for m in http.bodies[0]["messages"] if m["role"] == "user")
    )


def _user_error(content: list[Any]) -> fx.Effect[E.AiError, Any, Any]:
    prompt = Pr.make([Pr.UserMessage(content=content)])
    return _provided(lm.generate_text(prompt).flip(), mock())


class Name(TypedDict):
    name: str


NAME_RESPONSE = {
    "choices": [
        {
            "finish_reason": "stop",
            "index": 0,
            "message": {"role": "assistant", "content": '{"name": "Alice"}'},
        }
    ]
}


# strictJsonSchema -------------------------------------------------------------------------


@pytest.mark.parametrize(("model", "strict"), [(GPT, True), (GEMINI, None)])
@testing.effect
def test_default_response_strictness(model: str, strict: bool | None):
    """OpenRouterLanguageModel / strictJsonSchema / defaults response strictness to ${strict} for
    ${model}"""
    http = mock(**NAME_RESPONSE)
    yield from _provided(lm.generate_object("Give me a name", schema=S.Struct(Name)), http, model)
    assert http.bodies[0]["response_format"]["json_schema"]["strict"] == strict


@testing.effect
def test_strict_false_omitted():
    """OpenRouterLanguageModel / strictJsonSchema / omits false from requests while preserving
    response strictness"""
    http = mock(**NAME_RESPONSE)
    yield from _provided(
        lm.generate_object("Give me a name", schema=S.Struct(Name)),
        http,
        GPT,
        {"strict_json_schema": False},
    )
    body = http.bodies[0]
    assert body["response_format"]["json_schema"]["strict"] is False
    assert "strict_json_schema" not in body
    assert "strictJsonSchema" not in body


class Query(TypedDict):
    query: str


@testing.effect
def test_strict_true_omitted_streaming():
    """OpenRouterLanguageModel / strictJsonSchema / omits true from streaming requests while
    preserving tool strictness"""
    tool = T.make("FlexibleTool", parameters=S.Struct(Query)).annotate(T.Strict, False)
    http = stream_mock([])
    yield from _provided(
        lm.stream_text(
            prompt="Use a tool", toolkit=K.make(tool), disable_tool_call_resolution=True
        ).run_drain(),
        http,
        GPT,
        {"strict_json_schema": True},
    )
    body = http.bodies[0]
    assert body["stream"] is True
    assert body["tools"][0]["function"]["strict"] is False
    assert "strict_json_schema" not in body


@testing.effect
def test_provider_name():
    """OpenRouterLanguageModel / model provides openrouter provider metadata"""
    assert (yield from _provided(M.ProviderName(), mock())) == "openrouter"


# generateText / message preparation / audio file parts -----------------------------------


@testing.effect
def test_audio_bytes():
    """OpenRouterLanguageModel / generateText / message preparation / audio file parts / converts
    audio bytes to input_audio"""
    user = yield from _user_body(
        [Pr.FilePart(media_type="audio/mpeg", data=bytes([0x49, 0x44, 0x33, 0x04]))]
    )
    assert user["content"] == [
        {"type": "input_audio", "input_audio": {"data": "SUQzBA==", "format": "mp3"}}
    ]


@testing.effect
def test_audio_data_url():
    """OpenRouterLanguageModel / generateText / message preparation / audio file parts / converts
    base64 data url audio to input_audio"""
    user = yield from _user_body(
        [Pr.FilePart(media_type="audio/wav", data="data:audio/wav;base64,UklGRg==")]
    )
    assert user["content"] == [
        {"type": "input_audio", "input_audio": {"data": "UklGRg==", "format": "wav"}}
    ]


@testing.effect
def test_audio_formats():
    """OpenRouterLanguageModel / generateText / message preparation / audio file parts / maps audio
    media types to OpenRouter audio formats"""
    media_types = [
        ("audio/aac", "aac"),
        ("audio/x-aiff", "aiff"),
        ("audio/flac", "flac"),
        ("audio/L16", "pcm16"),
        ("audio/mp4", "m4a"),
        ("audio/mp3", "mp3"),
        ("audio/ogg", "ogg"),
        ("audio/x-wav", "wav"),
    ]
    user = yield from _user_body(
        [Pr.FilePart(media_type=media_type, data=bytes([0])) for media_type, _ in media_types]
    )
    assert [item["input_audio"]["format"] for item in user["content"]] == [
        audio_format for _, audio_format in media_types
    ]


@testing.effect
def test_unsupported_audio():
    """OpenRouterLanguageModel / generateText / message preparation / audio file parts / fails on
    unsupported audio media types"""
    error = yield from _user_error([Pr.FilePart(media_type="audio/webm", data=bytes([0]))])
    assert isinstance(error.reason, E.InvalidUserInputError)
    assert "audio/webm" in error.message


@testing.effect
def test_audio_url():
    """OpenRouterLanguageModel / generateText / message preparation / audio file parts / fails on
    audio URLs"""
    url = Url("https://example.com/audio.mp3")
    error = yield from _user_error([Pr.FilePart(media_type="audio/mpeg", data=url)])
    assert isinstance(error.reason, E.InvalidUserInputError)


@testing.effect
def test_file_blocks():
    """OpenRouterLanguageModel / generateText / message preparation / audio file parts / converts
    non-audio files to file blocks"""
    user = yield from _user_body(
        [
            Pr.FilePart(
                media_type="application/pdf",
                file_name="document.pdf",
                data=bytes([0x25, 0x50, 0x44, 0x46]),
            )
        ]
    )
    assert user["content"] == [
        {
            "type": "file",
            "file": {
                "filename": "document.pdf",
                "file_data": "data:application/pdf;base64,JVBERg==",
            },
        }
    ]


def _messages(prompt: list[Pr.Message], model: str = GEMINI) -> fx.Effect[Any, Any, Any]:
    http = mock()
    return _provided(
        lm.generate_text(Pr.make(prompt), disable_tool_call_resolution=True), http, model
    ).map(lambda _: http.bodies[0]["messages"])


@testing.effect
def test_string_tool_results():
    """OpenRouterLanguageModel / generateText / message preparation / preserves string tool results
    OpenRouterLanguageModel / generateText / message preparation / preserves string tool results"""
    messages = yield from _messages(
        [
            Pr.UserMessage(content=[Pr.TextPart(text="Use the tool")]),
            Pr.AssistantMessage(
                content=[Pr.ToolCallPart(id="call_text", name="text_tool", params={})]
            ),
            Pr.ToolMessage(
                content=[
                    Pr.ToolResultPart(
                        id="call_text",
                        name="text_tool",
                        result="PLAIN_TEXT_SENTINEL\n",
                        is_failure=False,
                    )
                ]
            ),
        ]
    )
    tool_result = next(m for m in messages if m["role"] == "tool")
    assert tool_result["content"] == "PLAIN_TEXT_SENTINEL\n"


_MODEL_OUTPUT_CASES = [
    pytest.param(
        [
            {"type": "text", "text": "Screenshot"},
            {
                "type": "file",
                "mediaType": "image/png",
                "fileName": "screenshot.png",
                "data": "iVBORw0KGgo=",
            },
        ],
        "Screenshot\n[image/png screenshot.png omitted]",
        id="as text with file placeholders",
    ),
    pytest.param([], "", id="as an empty string when it is empty"),
]


@pytest.mark.parametrize(("model_output", "content"), _MODEL_OUTPUT_CASES)
@testing.effect
def test_tool_result_model_output(model_output: list[Any], content: str):
    """OpenRouterLanguageModel / generateText / message preparation / sends tool result model
    output as text with file placeholders / as an empty string when it is empty"""
    result = Pr.ToolResultPart(
        id="call_image",
        name="image_tool",
        result={"output": "APPLICATION_ONLY"},
        is_failure=False,
        model_output=tuple(S.decode_unknown_sync(S.Array(Pr.TOOL_MODEL_OUTPUT_PART))(model_output)),
    )
    messages = yield from _messages(
        [
            Pr.UserMessage(content=[Pr.TextPart(text="Use the tool")]),
            Pr.AssistantMessage(
                content=[Pr.ToolCallPart(id="call_image", name="image_tool", params={})]
            ),
            Pr.ToolMessage(content=[result]),
        ]
    )
    tool_result = next(m for m in messages if m["role"] == "tool")
    assert tool_result["content"] == content


# generateText / message preparation / cache control --------------------------------------

EPHEMERAL = {"type": "ephemeral"}
ONE_HOUR = {"type": "ephemeral", "ttl": "1h"}
CACHED: Any = {"openrouter": {"cacheControl": EPHEMERAL}}
PART_CACHED: Any = {"openrouter": {"cacheControl": ONE_HOUR}}


@testing.effect
def test_cached_void_tool_result():
    """OpenRouterLanguageModel / generateText / message preparation / cache control / sends cached
    void tool results without throwing"""
    messages = yield from _messages(
        [
            Pr.ToolMessage(
                content=[
                    Pr.ToolResultPart(
                        id="call_void", name="void_tool", result=None, is_failure=False
                    )
                ],
                options=CACHED,
            )
        ],
        CLAUDE,
    )
    tool_result = next(m for m in messages if m["role"] == "tool")
    assert tool_result["tool_call_id"] == "call_void"


@pytest.mark.parametrize("part_level", [False, True], ids=["message", "part"])
@testing.effect
def test_cache_breakpoints(part_level: bool):
    """OpenRouterLanguageModel / generateText / message preparation / cache control / puts message
    breakpoints on the last assistant text and tool result; preserves part breakpoints and prefers
    them to message breakpoints"""
    part_options: Any = PART_CACHED if part_level else {}
    messages = yield from _messages(
        [
            Pr.UserMessage(content=[Pr.TextPart(text="Look up both")]),
            Pr.AssistantMessage(
                content=[
                    Pr.ReasoningPart(text="Thinking"),
                    Pr.TextPart(text="First", options=part_options),
                    Pr.TextPart(text="Second"),
                    Pr.TextPart(text="Last", options=part_options),
                    *(Pr.ToolCallPart(id=id, name="lookup", params={}) for id in "abc"),
                ],
                options=CACHED,
            ),
            Pr.ToolMessage(
                content=[
                    *(
                        Pr.ToolResultPart(
                            id=id,
                            name="lookup",
                            result={"value": 42} if id == "c" else id,
                            is_failure=False,
                            options=part_options if id != "b" else {},
                        )
                        for id in "abc"
                    ),
                    Pr.ToolApprovalResponsePart(approval_id="approval", approved=True),
                ],
                options=CACHED,
            ),
        ],
        CLAUDE,
    )
    assistant = next(m for m in messages if m["role"] == "assistant")
    assert assistant["content"] == [
        {"type": "text", "text": "First", "cache_control": ONE_HOUR}
        if part_level
        else {"type": "text", "text": "First"},
        {"type": "text", "text": "Second"},
        {"type": "text", "text": "Last", "cache_control": ONE_HOUR if part_level else EPHEMERAL},
    ]
    assert assistant["reasoning"] == "Thinking"
    assert assistant["tool_calls"] == [
        {"id": id, "type": "function", "function": {"name": "lookup", "arguments": "{}"}}
        for id in "abc"
    ]
    assert [m for m in messages if m["role"] == "tool"] == [
        {
            "role": "tool",
            "tool_call_id": "a",
            "content": [{"type": "text", "text": "a", "cache_control": ONE_HOUR}]
            if part_level
            else "a",
        },
        {"role": "tool", "tool_call_id": "b", "content": "b"},
        {
            "role": "tool",
            "tool_call_id": "c",
            "content": [
                {
                    "type": "text",
                    "text": '{"value":42}',
                    "cache_control": ONE_HOUR if part_level else EPHEMERAL,
                }
            ],
        },
    ]


# generateText / tool preparation ----------------------------------------------------------


def _tools(toolkit: Any) -> fx.Effect[Any, Any, Any]:
    http = mock()
    return _provided(
        lm.generate_text("Use the tool", toolkit=toolkit, disable_tool_call_resolution=True), http
    ).map(lambda _: http.bodies[0]["tools"])


@testing.effect
def test_dynamic_tool_raw_schema():
    """OpenRouterLanguageModel / generateText / tool preparation / passes raw JSON schema for
    dynamic tools"""
    input_schema: Any = {"properties": {"query": {"type": "string"}}}
    tool = T.dynamic("DynamicTool", description="A dynamic tool", parameters=input_schema)
    tools = yield from _tools(K.make(tool))
    found = next(t for t in tools if t["function"]["name"] == "DynamicTool")
    assert found["function"]["description"] == "A dynamic tool"
    assert found["function"]["parameters"] == input_schema


class Id(TypedDict):
    id: str


@testing.effect
def test_object_union_parameters():
    """OpenRouterLanguageModel / generateText / tool preparation / passes object union parameters
    through"""
    tool = T.make(
        "UnionTool",
        parameters=S.Union(S.Struct(Query).annotate(identifier="Query"), S.Struct(Id)),
    )
    tools = yield from _tools(K.make(tool))
    assert tools[0]["function"]["parameters"] == {
        "anyOf": [
            {"$ref": "#/$defs/Query"},
            {
                "type": "object",
                "properties": {"id": {"type": "string"}},
                "required": ["id"],
                "additionalProperties": True,
            },
        ],
        "$defs": {
            "Query": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
                "additionalProperties": True,
            }
        },
    }


class Empty(TypedDict):
    pass


@testing.effect
def test_non_object_parameters():
    """OpenRouterLanguageModel / generateText / tool preparation / names the tool when its
    parameters are not an object schema"""
    toolkit = K.make(T.make("NoParams", parameters=S.Struct(Empty)))
    error = yield from _provided(
        lm.generate_text("Use the tool", toolkit=toolkit, disable_tool_call_resolution=True).flip(),
        mock(),
    )
    assert isinstance(error.reason, E.UnsupportedSchemaError)
    assert '"NoParams"' in error.message
    assert "Tool.EmptyParams" in error.message


# generateText / usage ---------------------------------------------------------------------


def _usage(usage: dict[str, Any]) -> fx.Effect[R.Usage, Any, Any]:
    return _provided(lm.generate_text("Hello"), mock(usage=usage), GPT).map(
        lambda result: result.usage
    )


@testing.effect
def test_refusal_finish_part():
    """OpenRouterLanguageModel / generateText / reports a refusal through the finish part"""
    message = {"role": "assistant", "content": None, "refusal": "I cannot do that"}
    http = mock(choices=[{"finish_reason": "stop", "index": 0, "message": message}])
    result = yield from _provided(lm.generate_text("Do something bad"), http, "openai/gpt-4o")
    finish = next(p for p in result.content if isinstance(p, R.FinishPart))
    metadata: Any = finish.metadata["openrouter"]
    assert (result.text, result.finish_reason, metadata["refusal"]) == (
        "",
        "content-filter",
        "I cannot do that",
    )


@testing.effect
def test_stream_refusal_finish_part():
    """OpenRouterLanguageModel / streamText / streams a refusal through the finish part"""

    def chunk(delta: dict[str, Any], **fields: Any) -> dict[str, Any]:
        choice = {"index": 0, "delta": delta, **fields}
        return {
            "id": "response-1",
            "object": "chat.completion.chunk",
            "model": "openai/gpt-4o",
            "created": 1,
            "choices": [choice],
        }

    usage = {"prompt_tokens": 5, "completion_tokens": 4, "total_tokens": 9}
    events = [
        chunk({"content": "", "refusal": "I cannot", "role": "assistant"}),
        chunk({"content": "", "refusal": " do that"}),
        {**chunk({"content": ""}, finish_reason="stop"), "usage": usage},
    ]
    parts = yield from _provided(
        lm.stream_text("Do something bad").run_collect(), stream_mock(events), "openai/gpt-4o"
    )
    finish = next(p for p in parts if isinstance(p, R.FinishPart))
    metadata: Any = finish.metadata["openrouter"]
    assert [p.type for p in parts if p.type.startswith("text-")] == []
    assert (finish.reason, metadata["refusal"]) == ("content-filter", "I cannot do that")


@testing.effect
def test_usage_subsets():
    """OpenRouterLanguageModel / generateText / usage / derives text and uncached tokens when
    details are subsets of their totals"""
    usage = yield from _usage(
        {
            "prompt_tokens": 100,
            "prompt_tokens_details": {"cached_tokens": 30},
            "completion_tokens": 50,
            "completion_tokens_details": {"reasoning_tokens": 20},
            "total_tokens": 150,
        }
    )
    assert usage.input_tokens == R.InputTokens(uncached=70, total=100, cache_read=30, cache_write=0)
    assert usage.output_tokens == R.OutputTokens(total=50, text=30, reasoning=20)


@testing.effect
def test_usage_equal_counts():
    """OpenRouterLanguageModel / generateText / usage / preserves totals when detail counts equal
    their parent counts"""
    usage = yield from _usage(
        {
            "prompt_tokens": 100,
            "prompt_tokens_details": {"cached_tokens": 100},
            "completion_tokens": 20,
            "completion_tokens_details": {"reasoning_tokens": 20},
            "total_tokens": 120,
        }
    )
    assert usage.input_tokens == R.InputTokens(uncached=0, total=100, cache_read=100, cache_write=0)
    assert usage.output_tokens == R.OutputTokens(total=20, text=0, reasoning=20)


@testing.effect
def test_usage_disjoint_reasoning():
    """OpenRouterLanguageModel / generateText / usage / treats reasoning tokens as disjoint when
    they exceed completion tokens"""
    usage = yield from _usage(
        {
            "prompt_tokens": 100,
            "completion_tokens": 10,
            "completion_tokens_details": {"reasoning_tokens": 20},
            "total_tokens": 110,
        }
    )
    assert usage.output_tokens == R.OutputTokens(total=30, text=10, reasoning=20)


@testing.effect
def test_usage_disjoint_cached():
    """OpenRouterLanguageModel / generateText / usage / treats cached tokens as disjoint when they
    exceed prompt tokens"""
    usage = yield from _usage(
        {
            "prompt_tokens": 100,
            "prompt_tokens_details": {"cached_tokens": 300},
            "completion_tokens": 10,
            "total_tokens": 110,
        }
    )
    assert usage.input_tokens == R.InputTokens(
        uncached=100, total=400, cache_read=300, cache_write=0
    )


# streamText -------------------------------------------------------------------------------


def _chunk(**fields: Any) -> dict[str, Any]:
    return {
        "id": "response-1",
        "object": "chat.completion.chunk",
        "model": GPT,
        "created": 1,
        **fields,
    }


def _stream(events: list[Any], **options: Any) -> fx.Effect[list[Any], Any, Any]:
    return _provided(lm.stream_text(**options).run_collect().map(list), stream_mock(events), GPT)


@testing.effect
def test_stream_usage_disjoint_reasoning():
    """OpenRouterLanguageModel / streamText / usage / treats streamed reasoning tokens as disjoint
    when they exceed completion tokens"""
    parts = yield from _stream(
        [
            _chunk(
                choices=[],
                usage={
                    "prompt_tokens": 100,
                    "completion_tokens": 10,
                    "completion_tokens_details": {"reasoning_tokens": 20},
                    "total_tokens": 110,
                },
            )
        ],
        prompt="Hello",
    )
    finish = next(part for part in parts if part.type == "finish")
    assert finish.usage.output_tokens == R.OutputTokens(total=30, text=10, reasoning=20)


@testing.effect
def test_stream_citation_indexes():
    """OpenRouterLanguageModel / streamText / preserves streamed citation start and end indexes"""
    citation = {
        "type": "url_citation",
        "url_citation": {
            "url": "https://example.com/source",
            "title": "source",
            "start_index": 2,
            "end_index": 9,
        },
    }
    parts = yield from _stream(
        [_chunk(choices=[{"index": 0, "delta": {"annotations": [citation]}}])],
        prompt="cite a source",
    )
    source = next(part for part in parts if part.type == "source")
    assert source.metadata == {"openrouter": {"startIndex": 2, "endIndex": 9}}


@testing.effect
def test_stream_reasoning_end_metadata():
    """OpenRouterLanguageModel / streamText / uses lowercase openrouter reasoning-end metadata"""
    details = [
        {
            "type": "reasoning.text",
            "text": "thinking",
            "signature": "signature-final",
            "format": "unknown",
        }
    ]
    parts = yield from _stream(
        [
            _chunk(choices=[{"index": 0, "delta": {"reasoning_details": details}}]),
            _chunk(choices=[{"index": 0, "finish_reason": "stop", "delta": {"content": "answer"}}]),
        ],
        prompt="reason then answer",
    )
    end = next(part for part in parts if part.type == "reasoning-end")
    assert end.metadata == {"openrouter": {"reasoningDetails": details}}


class A(TypedDict):
    a: float


@testing.effect
def test_stream_tool_param_fragments():
    """OpenRouterLanguageModel / streamText / emits incremental tool parameter fragments"""
    probe = T.make("ProbeTool", parameters=S.Struct(A), success=S.String)
    toolkit = K.make(probe)
    events = [
        _chunk(
            choices=[
                {
                    "index": 0,
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": "call-1",
                                "type": "function",
                                "function": {"name": "ProbeTool", "arguments": '{"a":'},
                            }
                        ]
                    },
                }
            ]
        ),
        _chunk(choices=[{"index": 0, "delta": {"tool_calls": [{"index": 0}]}}]),
        _chunk(
            choices=[
                {
                    "index": 0,
                    "finish_reason": "tool_calls",
                    "delta": {"tool_calls": [{"index": 0, "function": {"arguments": "1}"}}]},
                }
            ]
        ),
    ]
    parts = yield from _stream(
        events,
        prompt="call the tool",
        toolkit=toolkit,
        disable_tool_call_resolution=True,
    ).pipe(fx.provide(toolkit.to_layer(probe.handler(lambda *_: fx.succeed("ok")))))
    assert [part.delta for part in parts if part.type == "tool-params-delta"] == ['{"a":', "1}"]


# finish reason inference ------------------------------------------------------------------

_USAGE = {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}
_PROBE_CALL = {
    "index": 0,
    "id": "call-1",
    "type": "function",
    "function": {"name": "ProbeTool", "arguments": '{"value":1}'},
}


class Value(TypedDict):
    value: float


class MaybeValue(TypedDict, total=False):
    value: float


_VALUE_TOOL = T.make("ProbeTool", parameters=S.Struct(Value), success=S.Finite)
_VALUE_TOOLKIT = K.make(_VALUE_TOOL)
_VALUE_LAYER = _VALUE_TOOLKIT.to_layer(_VALUE_TOOL.handler(lambda p, _: fx.succeed(p["value"])))


def _chunk_of(model: str, **fields: Any) -> dict[str, Any]:
    return {
        "id": "response-1",
        "object": "chat.completion.chunk",
        "model": model,
        "created": 1,
        **fields,
    }


@testing.effect
def test_generate_null_finish_reason():
    """OpenRouterLanguageModel / finish reason inference / generate executes tool calls with a
    null finish reason"""
    call = {key: value for key, value in _PROBE_CALL.items() if key != "index"}
    http = mock(
        choices=[
            {
                "index": 0,
                "finish_reason": None,
                "message": {"role": "assistant", "content": None, "tool_calls": [call]},
            }
        ]
    )
    response = yield from _provided(
        lm.generate_text("Use the tool", toolkit=_VALUE_TOOLKIT).pipe(fx.provide(_VALUE_LAYER)),
        http,
        "test/model",
    )
    assert response.finish_reason == "tool-calls"
    assert [part.result for part in response.tool_results] == [1]


@testing.effect
def test_stream_no_finish_reason():
    """OpenRouterLanguageModel / finish reason inference / stream executes complete tool calls
    without a finish reason"""
    first = {**_PROBE_CALL, "function": {"name": "ProbeTool", "arguments": '{"value":'}}
    events = [
        _chunk_of("test/model", choices=[{"index": 0, "delta": {"tool_calls": [first]}}]),
        _chunk_of(
            "test/model",
            choices=[
                {
                    "index": 0,
                    "delta": {"tool_calls": [{"index": 0, "function": {"arguments": "1}"}}]},
                }
            ],
            usage=_USAGE,
        ),
    ]
    parts = yield from _provided(
        lm.stream_text(prompt="Use the tool", toolkit=_VALUE_TOOLKIT)
        .run_collect()
        .map(list)
        .pipe(fx.provide(_VALUE_LAYER)),
        stream_mock(events),
        "test/model",
    )
    assert [part.reason for part in parts if part.type == "finish"] == ["tool-calls"]
    assert [part.result for part in parts if part.type == "tool-result"] == [1]


@testing.effect
def test_stream_truncated_call_without_finish_reason():
    """OpenRouterLanguageModel / finish reason inference / does not execute a truncated tool call
    alongside a complete call without a finish reason"""
    tool = T.make("ProbeTool", parameters=S.Struct(MaybeValue), success=S.String)
    toolkit = K.make(tool)
    executed: list[object] = []

    def handle(params: MaybeValue, _: Any) -> fx.Effect[str]:
        return fx.sync(lambda: executed.append(params.get("value"))).as_("ok")

    truncated = {
        "index": 1,
        "id": "call-2",
        "type": "function",
        "function": {"name": "ProbeTool", "arguments": '{"value":'},
    }
    events = [
        _chunk_of(
            "test/model", choices=[{"index": 0, "delta": {"tool_calls": [_PROBE_CALL, truncated]}}]
        ),
        _chunk_of("test/model", choices=[], usage=_USAGE),
    ]
    yield from _provided(
        lm.stream_text(prompt="Use the probe tool", toolkit=toolkit)
        .run_drain()
        .exit()
        .pipe(fx.provide(toolkit.to_layer(tool.handler(handle)))),
        stream_mock(events),
        "test/model",
    )
    # Either rejecting the response or leaving the partial call interrupted is safe.
    assert None not in executed


# schema codecs ----------------------------------------------------------------------------


class Tags(TypedDict):
    tags: dict[str, float]


_TAGS_TOOL = T.make(
    "TagsTool",
    failure_mode="return",
    parameters=S.Struct(Tags, tags=S.Record(S.String, S.Finite)),
    success=S.String,
)


def _tags_handler(params: Tags, _: Any) -> fx.Effect[str]:
    assert params == {"tags": {"a": 1}}
    return fx.succeed(_dumps(params["tags"]))


def _dumps(value: object) -> str:
    return json.dumps(value, separators=(",", ":"))


def _tool_calls_response(*calls: dict[str, Any], id: str = "gen-test123") -> MockHttp:
    return mock(
        id=id,
        choices=[
            {
                "finish_reason": "tool_calls",
                "index": 0,
                "message": {"role": "assistant", "content": None, "tool_calls": list(calls)},
            }
        ],
    )


def _function_call(id: str | None, name: str, arguments: object) -> dict[str, Any]:
    call: dict[str, Any] = {
        "type": "function",
        "function": {"name": name, "arguments": _dumps(arguments)},
    }
    if id is not None:
        call["id"] = id
    return call


@testing.effect
def test_decodes_with_sent_codec():
    """OpenRouterLanguageModel / schema codecs / decodes tool call parameters with the codec their
    schema was sent with"""
    toolkit = K.make(_TAGS_TOOL)
    http = _tool_calls_response(
        _function_call("call-1", "TagsTool", {"tags": [{"0": "a", "1": 1}]}),
        _function_call("call-2", "TagsTool", {"tags": 42}),
    )
    response = yield from _provided(
        lm.generate_text("Use a tool", toolkit=toolkit).pipe(
            fx.provide(toolkit.to_layer(_TAGS_TOOL.handler(_tags_handler)))
        ),
        http,
        GPT,
    )
    assert http.bodies[0]["tools"][0]["function"]["parameters"]["properties"]["tags"]["type"] == (
        "array"
    )
    assert len(response.tool_results) == 2
    success = next(part for part in response.tool_results if part.id == "call-1")
    invalid = next(part for part in response.tool_results if part.id == "call-2")
    assert (success.is_failure, success.result) == (False, '{"a":1}')
    assert invalid.is_failure
    assert isinstance(invalid.result, E.AiError)
    assert isinstance(invalid.result.reason, E.ToolParameterValidationError)


@testing.effect
def test_stream_decodes_with_sent_codec():
    """OpenRouterLanguageModel / schema codecs / decodes streamed tool call parameters with the
    codec their schema was sent with: the stream decodes as the response does"""
    toolkit = K.make(_TAGS_TOOL)
    call = {
        "index": 0,
        "id": "call-1",
        "type": "function",
        "function": {"name": "TagsTool", "arguments": _dumps({"tags": [{"0": "a", "1": 1}]})},
    }
    events = [
        _chunk(
            choices=[{"index": 0, "finish_reason": "tool_calls", "delta": {"tool_calls": [call]}}]
        ),
        _chunk(choices=[], usage=_USAGE),
    ]
    parts = yield from _stream(events, prompt="Use a tool", toolkit=toolkit).pipe(
        fx.provide(toolkit.to_layer(_TAGS_TOOL.handler(_tags_handler)))
    )
    assert [(p.is_failure, p.result) for p in parts if p.type == "tool-result"] == [
        (False, '{"a":1}')
    ]


class _Decoder(Tag[float], key="test/OpenRouterDecoder"):
    pass


class DecodeParams(TypedDict):
    n: float


@testing.effect
def test_disabled_resolution_encoded_params():
    """OpenRouterLanguageModel / schema codecs / returns encoded tool parameters without decoding
    services when resolution is disabled"""
    parameter = S.String.pipe(
        S.decode_to(
            S.Finite,
            Tr.Transformation(G.transform_effect(lambda _, __: _Decoder()), G.transform(str)),
        )
    )
    toolkit = K.make(T.make("Decode", parameters=S.Struct(DecodeParams, n=parameter)))
    response = yield from _provided(
        lm.generate_text("Use a tool", toolkit=toolkit, disable_tool_call_resolution=True),
        _tool_calls_response(_function_call("call-1", "Decode", {"n": "1"})),
        GPT,
    )
    assert [part.params for part in response.tool_calls] == [{"n": "1"}]


class StrictQuery(TypedDict, total=False):
    query: Required[str]
    limit: float


@testing.effect
def test_strict_tool_default_model():
    """OpenRouterLanguageModel / schema codecs / sends strict tools a strict-compatible schema for
    models without a provider codec"""
    tool = T.make("StrictTool", parameters=S.Struct(StrictQuery), success=S.String).annotate(
        T.Strict, True
    )
    toolkit = K.make(tool)
    seen: list[object] = []

    def handle(params: StrictQuery, _: Any) -> fx.Effect[str]:
        seen.append(params)
        return fx.succeed("ok")

    http = _tool_calls_response(
        _function_call("call-1", "StrictTool", {"query": "search", "limit": None})
    )
    response = yield from _provided(
        lm.generate_text("Use a tool", toolkit=toolkit).pipe(
            fx.provide(toolkit.to_layer(tool.handler(handle)))
        ),
        http,
        GEMINI,
    )
    assert seen == [{"query": "search"}]
    assert [(p.is_failure, p.result) for p in response.tool_results] == [(False, "ok")]
    function = http.bodies[0]["tools"][0]["function"]
    assert function["strict"] is True
    assert function["parameters"]["additionalProperties"] is False
    assert function["parameters"]["required"] == ["query", "limit"]


class Payload(TypedDict):
    payload: bool


@testing.effect
def test_non_strict_json_content_schema():
    """OpenRouterLanguageModel / generateText / tool preparation / preserves JSON content schemas
    for non-strict tools on default models"""
    tool = T.make(
        "JsonTool", parameters=S.Struct(Payload, payload=S.from_json_string(S.Boolean))
    ).annotate(T.Strict, False)
    tools = yield from _tools(K.make(tool))
    assert tools[0]["function"]["parameters"]["properties"]["payload"] == {
        "type": "string",
        "contentMediaType": "application/json",
        "contentSchema": {"type": "boolean"},
    }


# generateText / tool call ids, message preparation ----------------------------------------


@testing.effect
def test_tool_calls_without_ids():
    """OpenRouterLanguageModel / generateText / generates distinct IDs for tool calls without IDs
    and preserves supplied IDs"""
    tool = T.make("ProbeTool", parameters=S.Struct(A), success=S.String)
    http = _tool_calls_response(
        _function_call(None, "ProbeTool", {"a": 1}),
        _function_call(None, "ProbeTool", {"a": 2}),
        _function_call("provided-id", "ProbeTool", {"a": 3}),
        id="response-1",
    )
    response = yield from _provided(
        lm.generate_text("call the tools", toolkit=K.make(tool), disable_tool_call_resolution=True),
        http,
        GPT,
    )
    assert [(c.id, c.name, c.params) for c in response.tool_calls] == [
        ("response-1_tool_0", "ProbeTool", {"a": 1}),
        ("response-1_tool_1", "ProbeTool", {"a": 2}),
        ("provided-id", "ProbeTool", {"a": 3}),
    ]


@testing.effect
def test_base64_string_data_urls():
    """OpenRouterLanguageModel / generateText / message preparation / sends base64 string image
    and file data as data URLs"""
    user = yield from _user_body(
        [
            Pr.FilePart(media_type="image/png", data="iVBORw0KGgo="),
            Pr.FilePart(media_type="image/png", data="data:image/png;base64,iVBORw0KGgo="),
            Pr.FilePart(media_type="image/png", data="https://example.com/image.png"),
            Pr.FilePart(media_type="application/pdf", file_name="document.pdf", data="JVBERg=="),
        ]
    )
    assert user["content"] == [
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,iVBORw0KGgo="}},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,iVBORw0KGgo="}},
        {"type": "image_url", "image_url": {"url": "https://example.com/image.png"}},
        {
            "type": "file",
            "file": {
                "filename": "document.pdf",
                "file_data": "data:application/pdf;base64,JVBERg==",
            },
        },
    ]


# streamText (4.1.4) -----------------------------------------------------------------------


@testing.effect
def test_stream_empty_content_deltas():
    """OpenRouterLanguageModel / streamText / keeps streamed reasoning in one part when content
    deltas are empty"""
    model = "deepseek/deepseek-v4-flash"
    events = [
        _chunk_of(model, choices=[{"index": 0, "delta": {"content": "", "reasoning": "Thinking"}}]),
        _chunk_of(model, choices=[{"index": 0, "delta": {"content": "", "reasoning": " it over"}}]),
        _chunk_of(
            model,
            choices=[{"index": 0, "finish_reason": "stop", "delta": {"content": "Answer"}}],
            usage={"prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8},
        ),
    ]
    parts = yield from _provided(
        lm.stream_text(prompt="reason then answer").run_collect().map(list),
        stream_mock(events),
        model,
    )
    assert [
        f"{part.type}:{part.delta}" if hasattr(part, "delta") else part.type
        for part in parts
        if part.type.startswith(("reasoning-", "text-"))
    ] == [
        "reasoning-start",
        "reasoning-delta:Thinking",
        "reasoning-delta: it over",
        "reasoning-end",
        "text-start",
        "text-delta:Answer",
        "text-end",
    ]


def _probe_stream(events: list[Any]) -> fx.Effect[list[Any], Any, Any]:
    probe = T.make("ProbeTool", parameters=S.Struct(A), success=S.String)
    toolkit = K.make(probe)
    return _stream(
        events, prompt="call the tool", toolkit=toolkit, disable_tool_call_resolution=True
    ).pipe(fx.provide(toolkit.to_layer(probe.handler(lambda *_: fx.succeed("ok")))))


@testing.effect
def test_stream_calls_without_indices():
    """OpenRouterLanguageModel / streamText / streams parallel tool calls without indices exactly
    once"""
    events = [
        _chunk(
            choices=[
                {
                    "index": 0,
                    "delta": {
                        "tool_calls": [
                            {
                                "id": "call-1",
                                "type": "function",
                                "function": {"name": "ProbeTool", "arguments": '{"a":'},
                            },
                            {
                                "id": "call-2",
                                "type": "function",
                                "function": {"name": "ProbeTool", "arguments": '{"a":'},
                            },
                        ]
                    },
                }
            ]
        ),
        _chunk(
            choices=[
                {
                    "index": 0,
                    "finish_reason": "tool_calls",
                    "delta": {
                        "tool_calls": [
                            {"function": {"arguments": "1}"}},
                            {"function": {"arguments": "2}"}},
                        ]
                    },
                }
            ]
        ),
        _chunk(choices=[], usage={"prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8}),
    ]
    parts = yield from _probe_stream(events)
    assert [(p.id, p.name, p.params) for p in parts if p.type == "tool-call"] == [
        ("call-1", "ProbeTool", {"a": 1}),
        ("call-2", "ProbeTool", {"a": 2}),
    ]


@testing.effect
def test_stream_ends_mid_tool_call():
    """OpenRouterLanguageModel / streamText / fails when the response ends before a tool call's
    parameters are complete"""

    class Text(TypedDict):
        a: str

    probe = T.make("ProbeTool", parameters=S.Struct(Text), success=S.String)
    toolkit = K.make(probe)
    events = [
        _chunk(
            choices=[
                {
                    "index": 0,
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": "call-1",
                                "type": "function",
                                "function": {"name": "ProbeTool", "arguments": '{"a":"trunc'},
                            }
                        ]
                    },
                }
            ]
        ),
        _chunk(choices=[{"index": 0, "finish_reason": "length", "delta": {}}], usage=_USAGE),
    ]
    error = yield from _provided(
        lm.stream_text(prompt="call the tool", toolkit=toolkit, disable_tool_call_resolution=True)
        .run_drain()
        .flip()
        .pipe(fx.provide(toolkit.to_layer(probe.handler(lambda *_: fx.succeed("ok"))))),
        stream_mock(events),
        GPT,
    )
    assert isinstance(error.reason, E.ToolParameterValidationError)


@testing.effect
def test_stream_empty_fragment_after_call():
    """OpenRouterLanguageModel / streamText / ignores an empty fragment after a tool call
    completes"""
    calls = [
        {
            "index": 0,
            "id": "call-1",
            "type": "function",
            "function": {"name": "ProbeTool", "arguments": '{"a":1}'},
        },
        {"index": 0, "function": {"arguments": ""}},
    ]
    events = [_chunk(choices=[{"index": 0, "delta": {"tool_calls": [call]}}]) for call in calls]
    parts = yield from _probe_stream(events)
    assert [(p.id, p.params) for p in parts if p.type == "tool-call"] == [("call-1", {"a": 1})]
