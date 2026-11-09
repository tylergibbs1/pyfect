"""Ports of Effect's ``packages/ai/openrouter/test/OpenRouterLanguageModel.test.ts``.
Each docstring is the Effect test title (with its ``describe``). Responses
are recorded JSON or Server-Sent Events answered by a mocked
``HttpClient``."""

from __future__ import annotations

# pyright: reportUnknownVariableType=false, reportUnknownArgumentType=false
# pyright: reportUnknownMemberType=false, reportUnknownLambdaType=false
from typing import Any, TypedDict

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
from pyfect.redacted import make as redact

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
