"""Ports of Effect's ``packages/ai/openai-compat/test/OpenAiLanguageModel.test.ts``.
Each docstring is the Effect test title (with its ``describe``). Responses
are recorded JSON or Server-Sent Events answered by a mocked
``HttpClient``; no test reaches a real API.

Omitted:

- ``prepares selected tool codecs once per ${mode} request ...``, ``decodes
  tool call params with the OpenAI codec``, ``decodes Effect Schema dynamic
  tool call params with the OpenAI codec``, ``decodes streamed tool call
  params with the OpenAI codec`` and ``uses OpenAI codec transformer for
  optional structured fields``: Effect's ``OpenAiStructuredOutput`` codec
  (records as key/value arrays, optional keys as nullable) is not ported;
  pyfect sends the default JSON Schema.
"""

from __future__ import annotations

# pyright: reportUnknownVariableType=false, reportUnknownArgumentType=false
# pyright: reportUnknownMemberType=false, reportUnknownLambdaType=false
import json
from collections.abc import Sequence
from typing import Any, Literal, NotRequired, TypedDict
from urllib.parse import urlsplit

import pyfect as fx
from pyfect import schema as S
from pyfect import testing
from pyfect.ai import ai_error as E
from pyfect.ai import language_model as lm
from pyfect.ai import prompt as Pr
from pyfect.ai import response as R
from pyfect.ai import tool as T
from pyfect.ai import toolkit as K
from pyfect.ai.openai_compat import client
from pyfect.ai.openai_compat import language_model as olm
from pyfect.http.url import Url
from pyfect.layer import Layer
from pyfect.redacted import make as redact

from ._ai_http import MockHttp, json_response, mock_json, mock_sse, sse_response


class Input(TypedDict):
    input: str


class Output(TypedDict):
    output: str


class Failure(TypedDict):
    error: str


class Person(TypedDict):
    name: str
    age: float


class PatchParams(TypedDict):
    call_id: str
    operation: Any


class PatchResult(TypedDict):
    status: Literal["completed", "failed"]
    output: NotRequired[str | None]


class ShellParams(TypedDict):
    action: Any


TestTool = T.make(
    "TestTool", description="A test tool", parameters=S.Struct(Input), success=S.Struct(Output)
)
TestToolkit = K.make(TestTool)
TestLayer = TestToolkit.to_layer(
    TestTool.handler(lambda params, _: fx.succeed({"output": params["input"]}))
)
ApplyPatch = T.provider_defined(
    id="compat.apply_patch",
    custom_name="CompatApplyPatch",
    provider_name="apply_patch",
    requires_handler=True,
    parameters=S.Struct(PatchParams),
    success=S.Struct(PatchResult),
)
LocalShell = T.provider_defined(
    id="compat.local_shell",
    custom_name="CompatLocalShell",
    provider_name="local_shell",
    requires_handler=True,
    parameters=S.Struct(ShellParams),
    success=S.String,
)
_SHELL_ACTION = {"type": "exec", "command": ["pwd"], "env": {}}
_DELETE = {"call_id": "call_1", "operation": {"type": "delete_file", "path": "src/obsolete.ts"}}


def _provided(
    effect: fx.Effect[Any, Any, Any],
    mock: MockHttp,
    model: str = "gpt-4o-mini",
    config: olm.ModelConfig | None = None,
    *layers: Layer[Any, Any, Any],
) -> fx.Effect[Any, Any, Any]:
    for extra in layers:
        effect = effect.pipe(fx.provide(extra))
    return (
        effect.pipe(fx.provide(olm.model(model, config).layer))
        .pipe(fx.provide(client.layer(api_key=redact("sk-test-key"))))
        .pipe(fx.provide(mock.layer))
    )


def completion(message: dict[str, Any] | None = None, **fields: Any) -> dict[str, Any]:
    finish = fields.pop("finish_reason", "stop")
    return {
        "id": "chatcmpl_test_1",
        "object": "chat.completion",
        "model": "gpt-4o-mini",
        "created": 1,
        "choices": [
            {
                "index": 0,
                "finish_reason": finish,
                "message": {"role": "assistant", "content": "", **(message or {})},
            }
        ],
        **fields,
    }


def _calls(*calls: tuple[str, str, object]) -> dict[str, Any]:
    return completion(
        {
            "content": None,
            "tool_calls": [
                {
                    "id": id,
                    "type": "function",
                    "function": {"name": name, "arguments": json.dumps(args)},
                }
                for id, name, args in calls
            ],
        },
        finish_reason="tool_calls",
    )


def chunk(id: str, delta: dict[str, Any], finish_reason: str | None = None, **fields: Any) -> Any:
    return {
        "id": id,
        "object": "chat.completion.chunk",
        "model": "gpt-4o-mini",
        "created": 1,
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish_reason}],
        **fields,
    }


def _first[A](parts: Sequence[object], kind: type[A]) -> A:
    return next(part for part in parts if isinstance(part, kind))


def _types(parts: Sequence[Any]) -> list[str]:
    return [part.type for part in parts]


# generateText --------------------------------------------------------------------------


@testing.effect
def test_text_only_user_messages():
    """generateText / serializes text-only user messages and decodes text output"""
    mock = mock_json(completion({"content": "Hello, compat!"}))
    prompt = [
        Pr.UserMessage(content=(Pr.TextPart(text="hello"),)),
        Pr.UserMessage(content=(Pr.TextPart(text=""),)),
        Pr.UserMessage(content=(Pr.TextPart(text="  Hello, 世界!\nGoodbye.  "),)),
        Pr.UserMessage(content=(Pr.TextPart(text="first"), Pr.TextPart(text="second"))),
        Pr.UserMessage(content=()),
    ]
    result = yield from _provided(lm.generate_text(prompt), mock)
    assert result.text == "Hello, compat!"
    body = mock.bodies[0]
    assert body["model"] == "gpt-4o-mini"
    assert body["messages"] == [
        {"role": "user", "content": "hello"},
        {"role": "user", "content": ""},
        {"role": "user", "content": "  Hello, 世界!\nGoodbye.  "},
        {"role": "user", "content": "first\nsecond"},
        {"role": "user", "content": ""},
    ]


@testing.effect
def test_invalid_params_return_mode():
    """generateText / routes invalid tool call params through failureMode: return without failing the effect"""  # noqa: E501
    tool = T.make(
        "ReturnModeTool",
        description="A test tool",
        failure_mode="return",
        parameters=S.Struct(Input),
        success=S.Struct(Output),
        failure=S.Struct(Failure),
    )
    toolkit = K.make(tool)
    layer = toolkit.to_layer(
        tool.handler(lambda params, _: fx.succeed({"output": f"processed: {params['input']}"}))
    )
    mock = mock_json(_calls(("call_1", "ReturnModeTool", {"input": 123})))
    result = yield from _provided(
        lm.generate_text("use the tool", toolkit=toolkit), mock, "gpt-4o-mini", None, layer
    )
    assert len(result.tool_results) == 1
    tool_result = result.tool_results[0]
    assert tool_result.is_failure
    assert isinstance(tool_result.result, E.AiError)
    assert isinstance(tool_result.result.reason, E.ToolParameterValidationError)


@testing.effect
def test_reasoning_config():
    """generateText / forwards reasoning config to chat completions request"""
    mock = mock_json(completion({"content": "Done"}))
    reasoning = {"effort": "medium", "summary": "auto"}
    yield from _provided(lm.generate_text("hello"), mock, "gpt-5", {"reasoning": reasoning})
    assert mock.bodies[0]["reasoning"] == reasoning


@testing.effect
def test_custom_config_properties():
    """generateText / forwards custom model config properties to chat completions request"""
    mock = mock_json(completion({"content": "Done"}))
    yield from _provided(
        lm.generate_text("hello"), mock, "gpt-4o-mini", {"vendor_setting": {"mode": "strict"}}
    )
    assert mock.bodies[0]["vendor_setting"] == {"mode": "strict"}


@testing.effect
def test_multimodal_order():
    """generateText / preserves URL and base64 images in multimodal content order"""
    data = "iVBORw0KGgo="
    mock = mock_json(completion({"content": "done"}))
    content = (
        Pr.TextPart(text="first text"),
        Pr.FilePart(
            media_type="image/png", data=Url._make(urlsplit("https://example.com/image.png"))
        ),
        Pr.FilePart(media_type="image/png", data="https://example.com/string-image.png"),
        Pr.FilePart(media_type="image/png", data=data),
        Pr.TextPart(text="second text"),
    )
    yield from _provided(lm.generate_text([Pr.UserMessage(content=content)]), mock)

    def image(url: str) -> dict[str, Any]:
        return {"type": "image_url", "image_url": {"url": url, "detail": "auto"}}

    assert mock.bodies[0]["messages"][0]["content"] == [
        {"type": "text", "text": "first text"},
        image("https://example.com/image.png"),
        image("https://example.com/string-image.png"),
        image(f"data:image/png;base64,{data}"),
        {"type": "text", "text": "second text"},
    ]


@testing.effect
def test_empty_assistant_content():
    """generateText / normalizes empty assistant message content to an empty string"""
    mock = mock_json(completion({"content": "done"}))
    prompt = [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": [{"type": "text", "text": ""}]},
        {"role": "user", "content": "continue"},
    ]
    yield from _provided(lm.generate_text(prompt), mock)
    assistant = next(m for m in mock.bodies[0]["messages"] if m["role"] == "assistant")
    assert assistant["content"] == ""
    assert "tool_calls" not in assistant


@testing.effect
def test_function_call_output():
    """generateText / maps function_call output to tool-call part and sends function tool schema"""
    mock = mock_json(_calls(("call_1", "TestTool", {"input": "hello"})))
    result = yield from _provided(
        lm.generate_text("use the tool", toolkit=TestToolkit, disable_tool_call_resolution=True),
        mock,
        "gpt-4o-mini",
        None,
        TestLayer,
    )
    call = _first(result.content, R.ToolCallPart)
    assert call.name == "TestTool"
    assert call.params == {"input": "hello"}
    function = next(t for t in mock.bodies[0]["tools"] if t["type"] == "function")
    assert function["function"]["name"] == "TestTool"
    assert function["function"]["strict"] is True


@testing.effect
def test_raw_dynamic_params():
    """generateText / preserves raw JSON Schema dynamic tool call params"""
    params = {"query": "effect"}
    schema: Any = {
        "type": "object",
        "properties": {"query": {"type": "string"}},
        "required": ["query"],
        "additionalProperties": False,
    }
    tool = T.dynamic("DynamicTool", parameters=schema)
    result = yield from _provided(
        lm.generate_text(
            "use the dynamic tool", toolkit=K.make(tool), disable_tool_call_resolution=True
        ),
        mock_json(_calls(("call_dynamic_1", "DynamicTool", params))),
    )
    assert result.tool_calls[0].params == params


def _tool_turns(*calls: tuple[str, object]) -> list[dict[str, Any]]:
    return [
        {
            "role": "assistant",
            "content": [
                {"type": "tool-call", "id": id, "name": "TestTool", "params": {"input": value}}
                for id, value in calls
            ],
        },
        {
            "role": "tool",
            "content": [
                {
                    "type": "tool-result",
                    "id": id,
                    "name": "TestTool",
                    "isFailure": False,
                    "result": {"output": value},
                }
                for id, value in calls
            ],
        },
    ]


@testing.effect
def test_parallel_tool_calls_grouped():
    """generateText / groups parallel tool calls into one assistant message"""
    mock = mock_json(completion({"content": "done"}))
    prompt = [
        {"role": "user", "content": "use both tools"},
        *_tool_turns(("call_1", "first"), ("call_2", "second")),
    ]
    yield from _provided(
        lm.generate_text(prompt, toolkit=TestToolkit), mock, "gpt-4o-mini", None, TestLayer
    )

    def call(id: str, value: str) -> dict[str, Any]:
        arguments = json.dumps({"input": value}, separators=(",", ":"))
        return {
            "id": id,
            "type": "function",
            "function": {"name": "TestTool", "arguments": arguments},
        }

    assert mock.bodies[0]["messages"] == [
        {"role": "user", "content": "use both tools"},
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [call("call_1", "first"), call("call_2", "second")],
        },
        {"role": "tool", "tool_call_id": "call_1", "content": '{"output":"first"}'},
        {"role": "tool", "tool_call_id": "call_2", "content": '{"output":"second"}'},
    ]


def _sequenced(*bodies: Any) -> MockHttp:
    mock: MockHttp

    def handle(request: Any) -> Any:
        body = bodies[min(len(mock.requests), len(bodies)) - 1]
        return fx.succeed(body(request))

    mock = MockHttp(handle)
    return mock


@testing.effect
def test_extra_content_echoed():
    """generateText / echoes tool call extra_content in follow-up requests"""
    extra = {"google": {"thought_signature": "signature-1"}}
    first_body = _calls(("call_1", "TestTool", {"input": "hello"}))
    first_body["choices"][0]["message"]["tool_calls"][0]["extra_content"] = extra
    mock = _sequenced(
        lambda request: json_response(request, first_body),
        lambda request: json_response(request, completion()),
    )

    def generate(prompt: Pr.Prompt) -> Any:
        return _provided(
            lm.generate_text(prompt, toolkit=TestToolkit, disable_tool_call_resolution=True), mock
        )

    prompt = Pr.make("use the tool")
    first = yield from generate(prompt)
    yield from generate(prompt.concat(Pr.from_response_parts(first.content)))
    assert mock.bodies[1]["messages"][1]["tool_calls"][0]["extra_content"] == extra


@testing.effect
def test_dynamic_tools_function_type():
    """generateText / converts dynamic tools to function type"""
    schema: Any = {
        "type": "object",
        "properties": {"query": {"type": "string"}, "limit": {"type": "number"}},
        "required": ["query"],
        "additionalProperties": False,
    }
    tool = T.dynamic("DynamicTool", description="A dynamic tool", parameters=schema)
    mock = mock_json(completion({"content": "Done"}))
    yield from _provided(
        lm.generate_text(
            "use dynamic tool", toolkit=K.make(tool), disable_tool_call_resolution=True
        ),
        mock,
    )
    function = next(t for t in mock.bodies[0]["tools"] if t["function"]["name"] == "DynamicTool")
    assert function["function"]["description"] == "A dynamic tool"
    assert function["function"]["parameters"] == schema


@testing.effect
def test_non_object_parameters():
    """generateText / names the tool when its parameters are not an object schema"""
    toolkit = K.make(T.make("NoParams", parameters=S.String))
    error = yield from _provided(
        lm.generate_text("Use the tool", toolkit=toolkit, disable_tool_call_resolution=True).flip(),
        MockHttp(lambda _: fx.die(RuntimeError("unexpected request"))),
    )
    assert isinstance(error.reason, E.UnsupportedSchemaError)
    assert '"NoParams"' in error.message
    assert "Tool.EmptyParams" in error.message


def _patch_layer(toolkit: Any) -> Any:
    return toolkit.to_layer(
        ApplyPatch({}).handler(
            lambda _, __: fx.succeed({"status": "completed", "output": "deleted"})
        )
    )


@testing.effect
def test_apply_patch_generate():
    """generateText / maps provider apply_patch function call back to custom provider-defined tool"""  # noqa: E501
    toolkit = K.make(ApplyPatch({}))
    mock = mock_json(_calls(("call_1", "apply_patch", _DELETE)))
    result = yield from _provided(
        lm.generate_text(
            "delete src/obsolete.ts",
            toolkit=toolkit,
            tool_choice={"tool": "CompatApplyPatch"},
            disable_tool_call_resolution=True,
        ),
        mock,
        "gpt-4o-mini",
        None,
        _patch_layer(toolkit),
    )
    call = _first(result.content, R.ToolCallPart)
    assert call.name == "CompatApplyPatch"
    assert call.params == _DELETE
    body = mock.bodies[0]
    assert body["tools"][0]["function"]["name"] == "apply_patch"
    assert body["tool_choice"] == {"type": "function", "function": {"name": "apply_patch"}}


@testing.effect
def test_usage_without_details():
    """generateText / decodes usage when token detail fields are absent"""
    usage = {
        "prompt_tokens": 4,
        "completion_tokens": 5,
        "total_tokens": 9,
        "provider_future_field": True,
    }
    result = yield from _provided(
        lm.generate_text("hello"), mock_json(completion({"content": "Hello"}, usage=usage))
    )
    finish = _first(result.content, R.FinishPart)
    assert finish.usage.input_tokens == R.InputTokens(uncached=4, total=4, cache_read=0)
    assert finish.usage.output_tokens == R.OutputTokens(total=5, text=5, reasoning=0)


@testing.effect
def test_reasoning_non_streaming():
    """generateText / surfaces reasoning from non-streaming responses"""
    mock = mock_json(completion({"reasoning": "I should greet the user.", "content": "Hello!"}))
    result = yield from _provided(lm.generate_text("hello"), mock)
    assert _first(result.content, R.ReasoningPart).text == "I should greet the user."
    assert result.text == "Hello!"


@testing.effect
def test_reasoning_content_non_streaming():
    """generateText / surfaces reasoning_content from non-streaming responses"""
    mock = mock_json(
        completion({"reasoning_content": "I should greet the user.", "content": "Hello!"})
    )
    result = yield from _provided(lm.generate_text("hello"), mock)
    assert _first(result.content, R.ReasoningPart).text == "I should greet the user."
    assert result.text == "Hello!"


def _read_call() -> dict[str, Any]:
    arguments = json.dumps({"input": "a.txt"}, separators=(",", ":"))
    return {
        "id": "call_1",
        "type": "function",
        "function": {"name": "TestTool", "arguments": arguments},
    }


_TOOL_HELLO = {
    "role": "tool",
    "content": [
        {
            "type": "tool-result",
            "id": "call_1",
            "name": "TestTool",
            "isFailure": False,
            "result": "hello",
        }
    ],
}


@testing.effect
def test_replays_reasoning():
    """generateText / replays reasoning alongside assistant text and tool calls"""
    mock = mock_json(completion({"content": "done"}))
    prompt = [
        {"role": "user", "content": "What is in a.txt?"},
        {
            "role": "assistant",
            "content": [
                {"type": "reasoning", "text": "The user wants a.txt; I should read it."},
                {"type": "text", "text": "Let me read it."},
                {
                    "type": "tool-call",
                    "id": "call_1",
                    "name": "TestTool",
                    "params": {"input": "a.txt"},
                },
            ],
        },
        _TOOL_HELLO,
    ]
    yield from _provided(
        lm.generate_text(prompt, toolkit=TestToolkit, disable_tool_call_resolution=True),
        mock,
        "deepseek-reasoner",
    )
    assert mock.bodies[0]["messages"] == [
        {"role": "user", "content": "What is in a.txt?"},
        {
            "role": "assistant",
            "content": "Let me read it.",
            "reasoning_content": "The user wants a.txt; I should read it.",
            "tool_calls": [_read_call()],
        },
        {"role": "tool", "tool_call_id": "call_1", "content": "hello"},
    ]


@testing.effect
def test_replays_groq_reasoning():
    """generateText / replays decoded Groq reasoning under its original field alongside text and tool calls"""  # noqa: E501
    first_body = completion(
        {"reasoning": "Need the file", "content": "Let me read it.", "tool_calls": [_read_call()]},
        finish_reason="tool_calls",
    )
    mock = _sequenced(
        lambda request: json_response(request, first_body),
        lambda request: json_response(request, completion()),
    )

    def generate(prompt: Pr.Prompt) -> Any:
        return _provided(
            lm.generate_text(prompt, toolkit=TestToolkit, disable_tool_call_resolution=True),
            mock,
            "openai/gpt-oss-120b",
        )

    prompt = Pr.make("What is in a.txt?")
    first = yield from generate(prompt)
    yield from generate(prompt.concat(Pr.from_response_parts(first.content)).concat([_TOOL_HELLO]))
    assert mock.bodies[1]["messages"] == [
        {"role": "user", "content": "What is in a.txt?"},
        {
            "role": "assistant",
            "content": "Let me read it.",
            "reasoning": "Need the file",
            "tool_calls": [_read_call()],
        },
        {"role": "tool", "tool_call_id": "call_1", "content": "hello"},
    ]


# generateObject ------------------------------------------------------------------------


@testing.effect
def test_json_schema_format():
    """generateObject / uses json_schema format for structured output"""
    mock = mock_json(completion({"content": json.dumps({"name": "Ada", "age": 37})}))
    person = yield from _provided(
        lm.generate_object("Return a person", schema=S.Struct(Person)), mock
    )
    assert person.value == {"name": "Ada", "age": 37}
    response_format = mock.bodies[0]["response_format"]
    assert response_format["type"] == "json_schema"
    assert response_format["json_schema"]["strict"] is True


# streamText ----------------------------------------------------------------------------


@testing.effect
def test_stream_replay_with_store():
    """streamText / replays streamed assistant text and tool calls with store enabled"""
    events = [
        chunk(
            "chatcmpl_store_1",
            {"content": "Let me read it.", "tool_calls": [{**_read_call(), "index": 0}]},
            "tool_calls",
        ),
        "[DONE]",
    ]
    mock = _sequenced(
        lambda request: sse_response(request, events),
        lambda request: json_response(request, completion()),
    )
    config: olm.ModelConfig = {"store": True}
    prompt = Pr.make("What is in a.txt?")
    parts = yield from _provided(
        lm.stream_text(
            prompt, toolkit=TestToolkit, disable_tool_call_resolution=True
        ).run_collect(),
        mock,
        "gpt-4o-mini",
        config,
    )
    follow_up = prompt.concat(Pr.from_response_parts(parts)).concat([_TOOL_HELLO])
    yield from _provided(
        lm.generate_text(follow_up, toolkit=TestToolkit, disable_tool_call_resolution=True),
        mock,
        "gpt-4o-mini",
        config,
    )
    assert mock.bodies[1]["messages"] == [
        {"role": "user", "content": "What is in a.txt?"},
        {"role": "assistant", "content": "Let me read it.", "tool_calls": [_read_call()]},
        {"role": "tool", "tool_call_id": "call_1", "content": "hello"},
    ]
    assert "store" not in mock.bodies[1]


@testing.effect
def test_stream_chunks():
    """streamText / handles chat completion stream chunks"""
    mock = mock_sse([chunk("chatcmpl_test123", {}, "stop"), "[DONE]"])
    parts = yield from _provided(lm.stream_text("test").run_collect(), mock)
    assert any(isinstance(p, R.ResponseMetadataPart) for p in parts)
    assert _first(parts, R.FinishPart).reason == "stop"


def _text(parts: Sequence[object]) -> str:
    return "".join(p.delta for p in parts if isinstance(p, R.TextDeltaPart))


@testing.effect
def test_stream_null_tool_calls():
    """streamText / emits text when streamed tool_calls is null"""
    events = [
        chunk(
            "chatcmpl_nullable_tool_calls",
            {"content": "Hello", "tool_calls": None},
            model="inception/mercury-2",
        ),
        "[DONE]",
    ]
    parts = yield from _provided(
        lm.stream_text("test").run_collect(), mock_sse(events), "inception/mercury-2"
    )
    assert _text(parts) == "Hello"


def _stream_tool(
    events: list[object], *layers: Layer[Any, Any, Any], toolkit: Any = TestToolkit
) -> Any:
    return _provided(
        lm.stream_text(
            "use the tool", toolkit=toolkit, disable_tool_call_resolution=True
        ).run_collect(),
        mock_sse(events),
        "gpt-4o-mini",
        None,
        *layers,
    )


@testing.effect
def test_stream_nullable_delta_fields():
    """streamText / preserves streamed text and tool args with nullable delta fields"""
    extra = {"google": {"thought_signature": "signature-1"}}
    id = "chatcmpl_nullable_delta_fields"
    events: list[object] = [
        chunk(id, {"content": "Hello", "role": None}),
        chunk(
            id,
            {
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "extra_content": extra,
                        "function": {"name": "TestTool", "arguments": ""},
                    }
                ]
            },
        ),
        chunk(
            id,
            {
                "tool_calls": [
                    {
                        "id": None,
                        "extra_content": None,
                        "function": {"name": None, "arguments": '{"in'},
                    }
                ]
            },
        ),
        chunk(
            id,
            {
                "tool_calls": [
                    {"index": 0, "id": None, "function": {"name": None, "arguments": 'put":"hel'}}
                ]
            },
        ),
        chunk(
            id,
            {
                "tool_calls": [
                    {"index": 0, "id": None, "function": {"name": None, "arguments": 'lo"}'}}
                ]
            },
        ),
        chunk(id, {}, "tool_calls"),
        "[DONE]",
    ]
    parts = yield from _stream_tool(events, TestLayer)
    assert _text(parts) == "Hello"
    call = _first(parts, R.ToolCallPart)
    assert call.id == "call_1"
    assert call.params == {"input": "hello"}
    assert call.metadata["openai-compat"] == {"itemId": "call_1", "extraContent": extra}


def _shell_events() -> list[object]:
    call = {
        "index": 0,
        "id": "local_shell_call_1",
        "type": "function",
        "function": {"name": "local_shell", "arguments": json.dumps({"action": _SHELL_ACTION})},
    }
    return [chunk("chatcmpl_local_shell_1", {"tool_calls": [call]}, "tool_calls"), "[DONE]"]


@testing.effect
def test_stream_local_shell():
    """streamText / maps local shell stream tool calls to local_shell call outputs"""
    toolkit = K.make(LocalShell({}))
    layer = toolkit.to_layer(LocalShell({}).handler(lambda _, __: fx.succeed("done")))
    mock = _sequenced(
        lambda request: sse_response(request, _shell_events()),
        lambda request: json_response(request, completion()),
    )
    parts = yield from _provided(
        lm.stream_text("Run pwd", toolkit=toolkit, disable_tool_call_resolution=True).run_collect(),
        mock,
        "gpt-4o-mini",
        None,
        layer,
    )
    call = _first(parts, R.ToolCallPart)
    assert call.name == "CompatLocalShell"
    assert call.params == {"action": _SHELL_ACTION}
    prompt = [
        {"role": "user", "content": "Run pwd"},
        {
            "role": "assistant",
            "content": [
                {
                    "type": "tool-call",
                    "id": call.id,
                    "name": call.name,
                    "params": {"action": _SHELL_ACTION},
                    "options": {"openai-compat": {"itemId": "ls_call_1"}},
                }
            ],
        },
        {
            "role": "tool",
            "content": [
                {
                    "type": "tool-result",
                    "id": call.id,
                    "name": call.name,
                    "isFailure": False,
                    "result": "done",
                }
            ],
        },
    ]
    yield from _provided(
        lm.generate_text(prompt, toolkit=toolkit), mock, "gpt-4o-mini", None, layer
    )
    body = mock.bodies[1]
    shell = next(
        m
        for m in body["messages"]
        if m["role"] == "assistant" and m["tool_calls"][0]["function"]["name"] == "local_shell"
    )
    assert shell["content"] is None
    assert shell["tool_calls"][0]["id"] == call.id
    output = next(m for m in body["messages"] if m["role"] == "tool")
    assert output["tool_call_id"] == call.id
    assert output["content"] == "done"


@testing.effect
def test_stream_apply_patch():
    """streamText / maps apply_patch stream tool calls to custom provider-defined tool"""
    params = {
        "call_id": "patch_call_1",
        "operation": {"type": "delete_file", "path": "src/legacy.ts"},
    }
    call = {
        "id": "patch_call_1",
        "type": "function",
        "function": {"name": "apply_patch", "arguments": json.dumps(params)},
    }
    toolkit = K.make(ApplyPatch({}))
    parts = yield from _stream_tool(
        [chunk("chatcmpl_apply_patch_1", {"tool_calls": [call]}, "tool_calls"), "[DONE]"],
        _patch_layer(toolkit),
        toolkit=toolkit,
    )
    tool_call = _first(parts, R.ToolCallPart)
    assert tool_call.name == "CompatApplyPatch"
    assert tool_call.params == params


@testing.effect
def test_stream_fragmented_ids():
    """streamText / preserves fragmented stream tool call ids and names"""
    expected = {
        "call_id": "patch_call_2",
        "operation": {"type": "delete_file", "path": "src/fragmented.ts"},
    }
    arguments = json.dumps(expected)
    id = "chatcmpl_apply_patch_fragmented_1"
    events: list[object] = [
        chunk(
            id,
            {
                "tool_calls": [
                    {
                        "id": "patch_call_2",
                        "type": "function",
                        "function": {"name": "apply_patch", "arguments": arguments[:24]},
                    }
                ]
            },
        ),
        chunk(id, {"tool_calls": [{"function": {"arguments": arguments[24:48]}}]}),
        chunk(id, {"tool_calls": [{"function": {"arguments": arguments[48:]}}]}, "tool_calls"),
        "[DONE]",
    ]
    toolkit = K.make(ApplyPatch({}))
    parts = yield from _stream_tool(events, _patch_layer(toolkit), toolkit=toolkit)
    start = _first(parts, R.ToolParamsStartPart)
    assert start.id == "patch_call_2"
    assert start.name == "CompatApplyPatch"
    deltas = "".join(
        p.delta for p in parts if isinstance(p, R.ToolParamsDeltaPart) and p.id == "patch_call_2"
    )
    assert json.loads(deltas) == expected
    assert any(isinstance(p, R.ToolParamsEndPart) and p.id == "patch_call_2" for p in parts)
    call = _first(parts, R.ToolCallPart)
    assert (call.id, call.name, call.params) == ("patch_call_2", "CompatApplyPatch", expected)


@testing.effect
def test_stream_invalid_events():
    """streamText / continues after invalid JSON and schema-mismatched events"""
    usage = {
        "prompt_tokens": 10,
        "completion_tokens": 7,
        "total_tokens": 17,
        "prompt_tokens_details": {"cached_tokens": 3},
        "completion_tokens_details": {"reasoning_tokens": 2},
    }
    events: list[object] = [
        "{invalid-json",
        chunk("chatcmpl_stream_1", {"content": "Hello"}),
        {
            "type": "provider.chat.completion.delta",
            "provider_payload": {"content": "provider-specific"},
        },
        chunk(
            "chatcmpl_stream_1", {}, "stop", usage=usage, provider_future_field={"accepted": True}
        ),
        "[DONE]",
    ]
    mock = mock_sse(events)
    parts = yield from _provided(lm.stream_text("hello").run_collect(), mock)
    assert any(isinstance(p, R.ResponseMetadataPart) for p in parts)
    deltas = [p for p in parts if isinstance(p, R.TextDeltaPart)]
    assert [d.delta for d in deltas] == ["Hello"]
    finish = _first(parts, R.FinishPart)
    assert finish.reason == "stop"
    assert finish.usage.input_tokens == R.InputTokens(uncached=7, total=10, cache_read=3)
    assert finish.usage.output_tokens == R.OutputTokens(total=7, text=5, reasoning=2)
    assert mock.bodies[0]["stream"] is True


@testing.effect
def test_stream_null_name_fragments():
    """streamText / assembles streamed tool args when continuation fragments have function.name: null"""  # noqa: E501

    def fragment(function: dict[str, Any]) -> object:
        call = {"index": 0, "id": "call_1", "type": "function", "function": function}
        return chunk("chatcmpl_null_name_1", {"tool_calls": [call]})

    events: list[object] = [
        fragment({"name": "TestTool", "arguments": ""}),
        fragment({"name": None, "arguments": '{"in'}),
        fragment({"name": None, "arguments": 'put":"hel'}),
        fragment({"name": None, "arguments": 'lo"}'}),
        chunk("chatcmpl_null_name_1", {}, "tool_calls"),
        "[DONE]",
    ]
    parts = yield from _stream_tool(events, TestLayer)
    assert any(isinstance(p, R.ToolParamsDeltaPart) for p in parts)
    call = _first(parts, R.ToolCallPart)
    assert call.name == "TestTool"
    assert call.params == {"input": "hello"}


@testing.effect
def test_stream_reasoning_lifecycle():
    """streamText / emits reasoning lifecycle parts for delta.reasoning"""
    id = "chatcmpl_reasoning_1"
    events: list[object] = [
        chunk(id, {"content": "", "reasoning": "Let me think"}),
        chunk(id, {"content": "", "reasoning": " about this."}),
        chunk(id, {"content": "Hello"}),
        chunk(id, {"content": " there"}),
        chunk(id, {"content": ""}, "stop"),
        "[DONE]",
    ]
    parts = yield from _provided(lm.stream_text("test").run_collect(), mock_sse(events))
    assert _types(parts) == [
        "response-metadata",
        "reasoning-start",
        "reasoning-delta",
        "reasoning-delta",
        "reasoning-end",
        "text-start",
        "text-delta",
        "text-delta",
        "text-end",
        "finish",
    ]
    reasoning = [p for p in parts if p.type.startswith("reasoning")]
    assert "".join(p.delta for p in reasoning if isinstance(p, R.ReasoningDeltaPart)) == (
        "Let me think about this."
    )
    assert len({p.id for p in reasoning}) == 1
    assert _first(parts, R.TextStartPart).id != reasoning[0].id


@testing.effect
def test_stream_reasoning_content_lifecycle():
    """streamText / emits reasoning lifecycle parts for delta.reasoning_content"""
    id = "chatcmpl_reasoning_2"
    events: list[object] = [
        chunk(id, {"reasoning_content": "Thinking..."}),
        chunk(id, {"content": "Answer."}, "stop"),
        "[DONE]",
    ]
    parts = yield from _provided(lm.stream_text("test").run_collect(), mock_sse(events))
    assert _types(parts) == [
        "response-metadata",
        "reasoning-start",
        "reasoning-delta",
        "reasoning-end",
        "text-start",
        "text-delta",
        "text-end",
        "finish",
    ]
    assert "".join(p.delta for p in parts if isinstance(p, R.ReasoningDeltaPart)) == "Thinking..."


@testing.effect
def test_stream_closes_reasoning():
    """streamText / closes an open reasoning part at stream end"""
    events: list[object] = [
        chunk("chatcmpl_reasoning_3", {"reasoning": "Only thoughts."}, "stop"),
        "[DONE]",
    ]
    parts = yield from _provided(lm.stream_text("test").run_collect(), mock_sse(events))
    assert _types(parts) == [
        "response-metadata",
        "reasoning-start",
        "reasoning-delta",
        "reasoning-end",
        "finish",
    ]


# config --------------------------------------------------------------------------------


@testing.effect
def test_library_fields_not_leaked():
    """config / does not leak library-only fields into request body"""
    mock = mock_json(completion())
    yield from _provided(
        lm.generate_text("test"),
        mock,
        "gpt-4o-mini",
        {"file_id_prefixes": ["file-"], "strict_json_schema": False, "temperature": 0.5},
    )
    body = mock.bodies[0]
    assert "file_id_prefixes" not in body
    assert "fileIdPrefixes" not in body
    assert "strict_json_schema" not in body
    assert "strictJsonSchema" not in body
    assert body["temperature"] == 0.5


# toolCallValidation: "deferred" ----------------------------------------------------------


@testing.effect
def test_deferred_returns_invalid_and_undeclared_calls():
    """generateText / returns invalid and undeclared tool calls when tool call validation is deferred"""  # noqa: E501
    mock = mock_json(
        _calls(("call_1", "TestTool", {"input": 42}), ("call_2", "Write", {"path": "a"}))
    )
    result = yield from _provided(
        lm.generate_text(
            "use the tools",
            toolkit=TestToolkit,
            disable_tool_call_resolution=True,
            tool_call_validation="deferred",
        ),
        mock,
        "gpt-4o-mini",
        None,
        TestLayer,
    )
    assert [(c.name, c.params) for c in result.tool_calls] == [
        ("TestTool", {"input": 42}),
        ("Write", {"path": "a"}),
    ]


@testing.effect
def test_deferred_streams_undeclared_calls():
    """streamText / streams undeclared tool calls when tool call validation is deferred"""
    call = {
        "index": 0,
        "id": "call_1",
        "type": "function",
        "function": {"name": "Write", "arguments": json.dumps({"path": "a"})},
    }
    events = [chunk("chatcmpl_undeclared", {"tool_calls": [call]}, "tool_calls"), "[DONE]"]
    parts = yield from _provided(
        lm.stream_text(
            "use the tools",
            toolkit=TestToolkit,
            disable_tool_call_resolution=True,
            tool_call_validation="deferred",
        ).run_collect(),
        mock_sse(events),
        "gpt-4o-mini",
        None,
        TestLayer,
    )
    assert [(p.name, p.params) for p in parts if isinstance(p, R.ToolCallPart)] == [
        ("Write", {"path": "a"})
    ]
