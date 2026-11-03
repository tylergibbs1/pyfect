"""Ports of Effect's ``packages/ai/openai/test/OpenAiLanguageModel.test.ts``.
Each docstring is the Effect test title (with its ``describe``). Responses
are recorded JSON or Server-Sent Events answered by a mocked
``HttpClient`` (or a stub ``OpenAiClient`` streaming given events); no
test reaches a real API.

Omitted:

- ``response handling / decodes Effect Schema dynamic tool call params
  with the OpenAI codec`` and ``tool preparation / empty object on
  properties for empty parameters`` (both titles): Effect's
  ``OpenAiStructuredOutput`` codec (records as key/value arrays, optional
  keys as nullable, ``properties: {}`` added to empty objects) is not
  ported; pyfect sends the default JSON Schema (``docs/PARITY.md``).
"""

from __future__ import annotations

# pyright: reportUnknownVariableType=false, reportUnknownArgumentType=false
# pyright: reportUnknownMemberType=false, reportUnknownLambdaType=false
import json
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, TypedDict
from urllib.parse import urlsplit

import pytest

import pyfect as fx
from pyfect import schema as S
from pyfect import stream as St
from pyfect import testing
from pyfect.ai import _provider as P
from pyfect.ai import ai_error as E
from pyfect.ai import language_model as lm
from pyfect.ai import prompt as Pr
from pyfect.ai import response as R
from pyfect.ai import tool as T
from pyfect.ai import toolkit as K
from pyfect.ai.openai import client
from pyfect.ai.openai import language_model as olm
from pyfect.ai.openai import tool as OT
from pyfect.context import Tag
from pyfect.http import request as http_request
from pyfect.http import response as http_response
from pyfect.http.url import Url, href
from pyfect.layer import Layer
from pyfect.layer import succeed as layer_succeed
from pyfect.redacted import make as redact
from pyfect.schema import transformation as Tf

from ._ai_http import MockHttp, mock_json, text_response


class Input(TypedDict):
    input: str


class Output(TypedDict):
    output: str


class Failure(TypedDict):
    error: str


TestTool = T.make(
    "TestTool", description="A test tool", parameters=S.Struct(Input), success=S.Struct(Output)
)
TestToolkit = K.make(TestTool)
TestToolkitLayer = TestToolkit.to_layer(
    TestTool.handler(lambda params, _: fx.succeed({"output": f"processed: {params['input']}"}))
)


def response_body(**overrides: Any) -> dict[str, Any]:
    """Effect's ``makeDefaultResponse``."""
    return {
        "id": "resp_test123",
        "object": "response",
        "created_at": 1,
        "model": "gpt-4o-mini",
        "status": "completed",
        "output": [],
        "metadata": None,
        "temperature": None,
        "top_p": None,
        "tools": [],
        "tool_choice": "auto",
        "error": None,
        "incomplete_details": None,
        "instructions": None,
        "parallel_tool_calls": False,
        **overrides,
    }


def text_output(text: str, **overrides: Any) -> dict[str, Any]:
    return {
        "type": "message",
        "id": "msg_123",
        "role": "assistant",
        "status": "completed",
        "content": [{"type": "output_text", "text": text, "annotations": [], "logprobs": []}],
        **overrides,
    }


def function_call(name: str, args: dict[str, Any], **overrides: Any) -> dict[str, Any]:
    return {
        "type": "function_call",
        "id": "fc_123",
        "call_id": "call_123",
        "name": name,
        "arguments": json.dumps(args),
        "status": "completed",
        **overrides,
    }


def web_search_call(**overrides: Any) -> dict[str, Any]:
    return {
        "type": "web_search_call",
        "id": "ws_123",
        "status": "completed",
        "action": {"type": "search", "query": "Effect TypeScript"},
        **overrides,
    }


def file_search_call(**overrides: Any) -> dict[str, Any]:
    return {
        "type": "file_search_call",
        "id": "fs_123",
        "status": "completed",
        "queries": ["Effect TypeScript"],
        **overrides,
    }


def mcp_call(name: str, args: dict[str, Any], **overrides: Any) -> dict[str, Any]:
    return {
        "type": "mcp_call",
        "id": "mcp_call_123",
        "server_label": "npm",
        "name": name,
        "arguments": json.dumps(args),
        "output": "ok",
        "status": "completed",
        **overrides,
    }


def mcp_approval_request(name: str, args: dict[str, Any], **overrides: Any) -> dict[str, Any]:
    return {
        "type": "mcp_approval_request",
        "id": "approval_123",
        "server_label": "npm",
        "name": name,
        "arguments": json.dumps(args),
        **overrides,
    }


def reasoning_output(summaries: list[str], **overrides: Any) -> dict[str, Any]:
    return {
        "type": "reasoning",
        "id": "rs_123",
        "summary": [{"type": "summary_text", "text": text} for text in summaries],
        "encrypted_content": None,
        **overrides,
    }


def usage(**overrides: Any) -> dict[str, Any]:
    return {
        "input_tokens": 10,
        "output_tokens": 20,
        "total_tokens": 30,
        "input_tokens_details": {"cached_tokens": 0},
        "output_tokens_details": {"reasoning_tokens": 0},
        **overrides,
    }


def url(text: str) -> Url:
    return Url._make(urlsplit(text))


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


def _mock(**body: Any) -> MockHttp:
    return mock_json(response_body(**body))


def _generate(
    prompt: Any,
    model_name: str = "gpt-4o-mini",
    config: olm.ModelConfig | None = None,
    **body: Any,
) -> fx.Effect[dict[str, Any], Any, Any]:
    """The body of the request ``generate_text`` sends."""
    mock = _mock(**body)
    return _provided(lm.generate_text(prompt), mock, model_name, config).map(
        lambda _: mock.bodies[0]
    )


def plain(value: Any) -> Any:
    """``value`` with tuples (decoded arrays) as lists."""
    if isinstance(value, tuple | list):
        return [plain(v) for v in value]
    if isinstance(value, dict):
        return {k: plain(v) for k, v in value.items()}
    return value


def _content(
    options: dict[str, Any], mock: MockHttp, model: str, *layers: Layer[Any, Any, Any]
) -> fx.Effect[list[Any], Any, Any]:
    """The parts of ``generate_text``, or of ``stream_text`` with
    ``stream=True`` in ``options``."""
    streaming = options.pop("stream", False)
    if streaming:
        run: fx.Effect[Any, Any, Any] = lm.stream_text(**options).run_collect()
    else:
        run = lm.generate_text(**options).map(lambda response: list(response.content))
    return _provided(run, mock, model, None, *layers)


def stub_stream(events: Sequence[dict[str, Any]]) -> Layer[client.OpenAiClient]:
    """Effect's ``makeStreamTestLayer``: an ``OpenAiClient`` streaming
    ``events``."""
    response = http_response.make(
        http_request.get("https://api.openai.com/v1/responses"),
        "",
        headers={"content-type": "text/event-stream"},
    )

    def unexpected(name: str) -> Any:
        return lambda _: fx.die(RuntimeError(f"unexpected {name} call"))

    service = client.Service(
        http_client=None,  # pyright: ignore[reportArgumentType]
        create_response=unexpected("createResponse"),
        create_response_stream=lambda _: fx.succeed((response, St.from_iterable(events))),
        create_embedding=unexpected("createEmbedding"),
        create_decisions=unexpected("createDecisions"),
    )
    return layer_succeed(client.OpenAiClient, service)


def _stream_parts(
    events: Sequence[dict[str, Any]],
    model: str = "gpt-4o-mini",
    config: olm.ModelConfig | None = None,
    **options: Any,
) -> fx.Effect[list[Any], Any, Any]:
    return (
        lm.stream_text(**options)
        .run_collect()
        .pipe(fx.provide(olm.model(model, config).layer))
        .pipe(fx.provide(stub_stream(events)))
    )


def _first[A](parts: Sequence[object], kind: type[A]) -> A:
    return next(part for part in parts if isinstance(part, kind))


def _of[A](parts: Sequence[object], kind: type[A]) -> list[A]:
    return [part for part in parts if isinstance(part, kind)]


def _results(parts: Sequence[object]) -> list[Any]:
    return [p for p in parts if isinstance(p, R.ToolResultSuccess | R.ToolResultFailure)]


def raw_mock(body: str, content_type: str) -> MockHttp:
    return MockHttp(
        lambda request: fx.succeed(text_response(request, body, content_type=content_type))
    )


def _done_event(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "response.output_item.done",
        "sequence_number": 1,
        "output_index": 0,
        "item": item,
    }


def _web_search_mock(method: str, item: dict[str, Any]) -> MockHttp:
    if method == "generateText":
        return raw_mock(json.dumps(response_body(output=[item])), "application/json")
    return raw_mock(f"data: {json.dumps(_done_event(item))}\n\n", "text/event-stream")


def _web_search_parts(method: str, item: dict[str, Any], model: str, prompt: str) -> Any:
    options = {
        "prompt": prompt,
        "toolkit": K.make(OT.WebSearch()),
        "stream": method == "streamText",
    }
    return _content(options, _web_search_mock(method, item), model)


# make -----------------------------------------------------------------------------------


@testing.effect
def test_sends_model():
    """make / sends correct model in request"""
    result = yield from _provided(lm.generate_text("test"), _mock())
    assert _first(result.content, R.ResponseMetadataPart).model_id == "gpt-4o-mini"


@testing.effect
def test_custom_model():
    """make / sends custom model string in request"""
    result = yield from _provided(
        lm.generate_text("test"), _mock(model="ft:gpt-4o-mini:custom"), "ft:gpt-4o-mini:custom"
    )
    assert _first(result.content, R.ResponseMetadataPart).model_id == "ft:gpt-4o-mini:custom"


# web search -----------------------------------------------------------------------------


@pytest.mark.parametrize("method", ["generateText", "streamText"])
@testing.effect
def test_web_search_sources(method: str):
    """web search sources / preserves URL and API sources with %s"""
    sources = [
        {"type": "url", "url": "https://example.com/weather"},
        {"type": "api", "name": "oai-weather"},
    ]
    action = {"type": "search", "query": "weather in London", "sources": sources}
    parts = yield from _web_search_parts(
        method, web_search_call(action=action), "gpt-5.6", "Weather in London"
    )
    assert [plain(part.params) for part in _of(parts, R.ToolCallPart)] == [{"action": action}]
    assert [plain(part.result) for part in _results(parts)] == [
        {"action": action, "status": "completed"}
    ]


@pytest.mark.parametrize("method", ["generateText", "streamText"])
@testing.effect
def test_web_search_find_in_page(method: str):
    """web search find_in_page / preserves actions without a URL with %s"""
    action = {"type": "find_in_page", "pattern": "og:image"}
    item = {"type": "web_search_call", "id": "ws_123", "status": "completed", "action": action}
    parts = yield from _web_search_parts(method, item, "gpt-5.4", "Search the page")
    assert [plain(part.params) for part in _of(parts, R.ToolCallPart)] == [{"action": action}]
    assert [plain(part.result) for part in _results(parts)] == [
        {"action": action, "status": "completed"}
    ]


@pytest.mark.parametrize(
    ("method", "status", "is_failure"),
    [
        ("streamText", "incomplete", True),
        ("generateText", "incomplete", True),
        ("generateText", "completed", False),
    ],
)
@testing.effect
def test_web_search_omitted_action(method: str, status: str, is_failure: bool):
    """web search without an action / preserves omitted actions for $status with $method"""
    item = {"type": "web_search_call", "id": "ws_123", "status": status}
    parts = yield from _web_search_parts(method, item, "gpt-6-luna", "Search the web")
    found = [
        (part.type, part.id, part.provider_executed, part.params)
        if isinstance(part, R.ToolCallPart)
        else (part.type, part.id, part.provider_executed, part.result, part.is_failure)
        for part in parts
        if isinstance(part, R.ToolCallPart | R.ToolResultSuccess | R.ToolResultFailure)
    ]
    assert found == [
        ("tool-call", "ws_123", True, {}),
        ("tool-result", "ws_123", True, {"status": status}, is_failure),
    ]


@testing.effect
def test_web_search_malformed_action():
    """web search without an action / rejects null and malformed actions when present"""
    for action in [None, {"type": "find_in_page", "url": "https://example.com", "pattern": None}]:
        item = {"type": "web_search_call", "id": "ws_123", "status": "completed", "action": action}
        mock = raw_mock(f"data: {json.dumps(_done_event(item))}\n\n", "text/event-stream")
        error = yield from _provided(
            lm.stream_text(prompt="Search", toolkit=K.make(OT.WebSearch())).run_collect().flip(),
            mock,
            "gpt-6-luna",
        )
        assert isinstance(error, E.AiError)
        assert isinstance(error.reason, E.InvalidOutputError)


# generateText / message preparation -----------------------------------------------------

_BREAKPOINT: dict[str, Any] = {"mode": "explicit"}
_BREAKPOINT_OPTIONS: Pr.ProviderOptions = {"openai": {"promptCacheBreakpoint": _BREAKPOINT}}


@testing.effect
def test_prompt_cache_breakpoints():
    """generateText / message preparation / forwards prompt cache, safety configuration and text breakpoints"""  # noqa: E501
    options = _BREAKPOINT_OPTIONS
    prompt = [
        Pr.SystemMessage(content="Stable instructions", options=options),
        Pr.UserMessage(content=(Pr.TextPart(text="Stable context", options=options),)),
    ]
    cache_options = {"mode": "explicit", "ttl": "30m", "comparison_response_id": "resp_baseline"}
    body = yield from _generate(
        prompt,
        "gpt-5.6",
        {
            "prompt_cache_key": "assistant:v1",
            "prompt_cache_options": cache_options,
            "prompt_cache_retention": "24h",
            "safety_identifier": "user-hash-123",
        },
        model="gpt-5.6",
    )
    assert body["prompt_cache_key"] == "assistant:v1"
    assert body["prompt_cache_retention"] == "24h"
    assert body["safety_identifier"] == "user-hash-123"
    assert body["prompt_cache_options"] == cache_options
    assert body["input"] == [
        {
            "role": "developer",
            "content": [
                {
                    "type": "input_text",
                    "text": "Stable instructions",
                    "prompt_cache_breakpoint": _BREAKPOINT,
                }
            ],
        },
        {
            "role": "user",
            "content": [
                {
                    "type": "input_text",
                    "text": "Stable context",
                    "prompt_cache_breakpoint": _BREAKPOINT,
                }
            ],
        },
    ]


@testing.effect
def test_file_breakpoints():
    """generateText / message preparation / forwards image and file breakpoints"""
    options = _BREAKPOINT_OPTIONS
    content = (
        Pr.FilePart(
            media_type="image/png", data=url("https://example.com/image.png"), options=options
        ),
        Pr.FilePart(
            media_type="application/pdf",
            data=url("https://example.com/document.pdf"),
            options=options,
        ),
    )
    body = yield from _generate([Pr.UserMessage(content=content)], "gpt-5.6", model="gpt-5.6")
    assert body["input"] == [
        {
            "role": "user",
            "content": [
                {
                    "type": "input_image",
                    "image_url": "https://example.com/image.png",
                    "detail": "auto",
                    "prompt_cache_breakpoint": _BREAKPOINT,
                },
                {
                    "type": "input_file",
                    "file_url": "https://example.com/document.pdf",
                    "prompt_cache_breakpoint": _BREAKPOINT,
                },
            ],
        }
    ]


@testing.effect
def test_implicit_prompt_cache():
    """generateText / message preparation / forwards implicit prompt cache mode without text breakpoints"""  # noqa: E501
    body = yield from _generate(
        "Stable context", "gpt-5.6", {"prompt_cache_options": {"mode": "implicit"}}, model="gpt-5.6"
    )
    assert body["prompt_cache_options"] == {"mode": "implicit"}
    assert body["input"] == [
        {"role": "user", "content": [{"type": "input_text", "text": "Stable context"}]}
    ]


_SYSTEM_PROMPT = [
    {"role": "system", "content": "You are a helpful assistant"},
    {"role": "user", "content": "Hello"},
]
_SYSTEM_CONTENT = [{"type": "input_text", "text": "You are a helpful assistant"}]


@testing.effect
def test_system_role():
    """generateText / message preparation / system messages / uses system role for standard models"""  # noqa: E501
    body = yield from _generate(_SYSTEM_PROMPT)
    system = next(m for m in body["input"] if m.get("role") == "system")
    assert system["content"] == _SYSTEM_CONTENT


@testing.effect
def test_developer_role_reasoning():
    """generateText / message preparation / system messages / uses developer role for reasoning models"""  # noqa: E501
    body = yield from _generate(_SYSTEM_PROMPT, "o1", model="o1")
    developer = next(m for m in body["input"] if m.get("role") == "developer")
    assert developer["content"] == _SYSTEM_CONTENT


@testing.effect
def test_developer_role_gpt_5():
    """generateText / message preparation / system messages / uses developer role for gpt-5 models"""  # noqa: E501
    body = yield from _generate(_SYSTEM_PROMPT, "gpt-5", model="gpt-5")
    assert any(m.get("role") == "developer" for m in body["input"])


@testing.effect
def test_developer_role_o3():
    """generateText / message preparation / system messages / uses developer role for o3 models"""
    body = yield from _generate(_SYSTEM_PROMPT, "o3-mini", model="o3-mini")
    assert any(m.get("role") == "developer" for m in body["input"])


def _user_content(body: dict[str, Any]) -> list[Any]:
    return next(m for m in body["input"] if m.get("role") == "user")["content"]


def _files(*parts: Pr.FilePart) -> list[Pr.UserMessage]:
    return [Pr.UserMessage(content=parts)]


@testing.effect
def test_user_text():
    """generateText / message preparation / user messages / converts text parts to input_text"""
    body = yield from _generate("Hello world")
    assert _user_content(body) == [{"type": "input_text", "text": "Hello world"}]


@testing.effect
def test_image_urls():
    """generateText / message preparation / user messages / handles image URLs"""
    body = yield from _generate(
        _files(Pr.FilePart(media_type="image/png", data=url("https://example.com/image.png")))
    )
    assert _user_content(body) == [
        {"type": "input_image", "image_url": "https://example.com/image.png", "detail": "auto"}
    ]


@testing.effect
def test_image_strings():
    """generateText / message preparation / user messages / handles image strings"""
    data = "iVBORw0KGgo="
    data_url = f"data:image/png;base64,{data}"
    upper = f"DATA:image/png;base64,{data}"
    link = "https://example.com/image.png"
    body = yield from _generate(
        _files(
            *(Pr.FilePart(media_type="image/png", data=d) for d in (data, data_url, upper, link))
        )
    )
    assert body["input"] == [
        {
            "role": "user",
            "content": [
                {"type": "input_image", "image_url": data_url, "detail": "auto"},
                {"type": "input_image", "image_url": data_url, "detail": "auto"},
                {"type": "input_image", "image_url": upper, "detail": "auto"},
                {"type": "input_image", "image_url": link, "detail": "auto"},
            ],
        }
    ]


@testing.effect
def test_image_detail():
    """generateText / message preparation / user messages / handles image with custom detail level"""  # noqa: E501
    body = yield from _generate(
        _files(
            Pr.FilePart(
                media_type="image/png",
                data=url("https://example.com/image.png"),
                options={"openai": {"imageDetail": "high"}},
            )
        )
    )
    assert _user_content(body)[0]["detail"] == "high"


@testing.effect
def test_image_file_ids():
    """generateText / message preparation / user messages / handles image file IDs with configured prefixes"""  # noqa: E501
    body = yield from _generate(
        _files(Pr.FilePart(media_type="image/png", data="file-abc123")),
        config={"file_id_prefixes": ["file-"]},
    )
    assert _user_content(body) == [
        {"type": "input_image", "file_id": "file-abc123", "detail": "auto"}
    ]


@testing.effect
def test_image_bytes():
    """generateText / message preparation / user messages / handles image base64 data"""
    body = yield from _generate(
        _files(Pr.FilePart(media_type="image/png", data=bytes([137, 80, 78, 71])))
    )
    assert _user_content(body)[0]["image_url"].startswith("data:image/png;base64,")


@testing.effect
def test_pdf_urls():
    """generateText / message preparation / user messages / handles PDF URLs"""
    body = yield from _generate(
        _files(
            Pr.FilePart(media_type="application/pdf", data=url("https://example.com/document.pdf"))
        )
    )
    assert _user_content(body) == [
        {"type": "input_file", "file_url": "https://example.com/document.pdf"}
    ]


@testing.effect
def test_pdf_bytes():
    """generateText / message preparation / user messages / handles PDF base64 data with filename"""
    body = yield from _generate(
        _files(Pr.FilePart(media_type="application/pdf", data=b"%PDF", file_name="document.pdf"))
    )
    file = _user_content(body)[0]
    assert file["type"] == "input_file"
    assert file["filename"] == "document.pdf"
    assert file["file_data"].startswith("data:application/pdf;base64,")


@testing.effect
def test_assistant_text():
    """generateText / message preparation / assistant messages / converts text parts to message output"""  # noqa: E501
    body = yield from _generate(
        [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": [{"type": "text", "text": "Hi there!"}]},
            {"role": "user", "content": "How are you?"},
        ]
    )
    message = next(
        m for m in body["input"] if m.get("type") == "message" and m.get("role") == "assistant"
    )
    assert message["content"][0]["type"] == "output_text"
    assert message["content"][0]["text"] == "Hi there!"


@testing.effect
def test_assistant_reasoning():
    """generateText / message preparation / assistant messages / converts reasoning parts"""
    body = yield from _generate(
        [
            {"role": "user", "content": "Think step by step"},
            {
                "role": "assistant",
                "content": [
                    {
                        "type": "reasoning",
                        "text": "Let me think...",
                        "options": {"openai": {"itemId": "reasoning_123"}},
                    }
                ],
            },
            {"role": "user", "content": "Continue"},
        ],
        "o1",
        model="o1",
    )
    reasoning = next(m for m in body["input"] if m.get("type") == "reasoning")
    assert reasoning["id"] == "reasoning_123"


def _reasoning_history() -> Pr.Prompt:
    return Pr.from_response_parts(
        [
            R.ReasoningStartPart(
                id="reasoning_123:0", metadata={"openai": {"itemId": "reasoning_123"}}
            ),
            R.ReasoningDeltaPart(id="reasoning_123:0", delta="Let me think..."),
            R.ReasoningEndPart(
                id="reasoning_123:0",
                metadata={
                    "openai": {"itemId": "reasoning_123", "encryptedContent": "encrypted-reasoning"}
                },
            ),
        ]
    ).concat(Pr.make("Continue"))


_REPLAYED_REASONING = {
    "type": "reasoning",
    "id": "reasoning_123",
    "summary": [{"type": "summary_text", "text": "Let me think..."}],
    "encrypted_content": "encrypted-reasoning",
}


@testing.effect
def test_replays_encrypted_reasoning():
    """generateText / message preparation / assistant messages / replays encrypted reasoning from response parts"""  # noqa: E501
    body = yield from _generate(_reasoning_history(), "o1", model="o1")
    assert next(i for i in body["input"] if i.get("type") == "reasoning") == _REPLAYED_REASONING


@testing.effect
def test_replays_encrypted_reasoning_unknown_model():
    """generateText / message preparation / assistant messages / replays encrypted reasoning statelessly for an unknown model"""  # noqa: E501
    body = yield from _generate(
        _reasoning_history(), "custom-model", {"store": False}, model="custom-model"
    )
    assert next(i for i in body["input"] if i.get("type") == "reasoning") == _REPLAYED_REASONING


def _part(kind: str, **fields: Any) -> dict[str, Any]:
    return {"type": kind, **fields}


STORED_HISTORY: list[Any] = [
    {"role": "user", "content": "Question"},
    {
        "role": "assistant",
        "content": [
            _part("text", text="Answer", options={"openai": {"itemId": "msg_1"}}),
            _part(
                "reasoning",
                text="Thinking",
                options={"openai": {"itemId": "rs_1", "encryptedContent": "encrypted-reasoning"}},
            ),
            _part(
                "tool-call",
                id="call_1",
                name="TestTool",
                params={"input": "value"},
                providerExecuted=False,
                options={"openai": {"itemId": "fc_1"}},
            ),
        ],
    },
    {
        "role": "tool",
        "content": [
            _part(
                "tool-result",
                id="call_1",
                name="TestTool",
                isFailure=False,
                result={"output": "result"},
                providerExecuted=False,
            )
        ],
    },
    {"role": "user", "content": "Continue"},
]

_PROVIDER_CALL = _part(
    "tool-call",
    id="ws_1",
    name="OpenAiWebSearch",
    params={"action": {"type": "search", "query": "Effect TypeScript"}},
    providerExecuted=True,
    options={"openai": {"itemId": "ws_1", "status": "completed"}},
)
_PROVIDER_RESULT = _part(
    "tool-result",
    id="ws_1",
    name="OpenAiWebSearch",
    isFailure=False,
    result={"action": {"type": "search", "query": "Effect TypeScript"}, "status": "completed"},
    providerExecuted=True,
    options={"openai": {"itemId": "ws_1", "status": "completed"}},
)


def _search_history(*parts: dict[str, Any]) -> list[Any]:
    return [
        {"role": "user", "content": "Search"},
        {"role": "assistant", "content": list(parts)},
        {"role": "user", "content": "Continue"},
    ]


_INLINE = {"store": True, "use_item_references": False}


def _user(text: str) -> dict[str, Any]:
    return {"role": "user", "content": [{"type": "input_text", "text": text}]}


@testing.effect
def test_stored_history_references():
    """generateText / message preparation / assistant messages / serializes stored assistant history according to item reference config"""  # noqa: E501
    mock = _mock()
    for config in ({"store": True}, _INLINE):
        yield from _provided(
            lm.generate_text(
                STORED_HISTORY, toolkit=TestToolkit, disable_tool_call_resolution=True
            ),
            mock,
            "gpt-4o-mini",
            config,
        )
    referenced, inline = mock.bodies
    output = {"type": "function_call_output", "call_id": "call_1", "output": '{"output":"result"}'}
    assert referenced["input"] == [
        _user("Question"),
        {"type": "item_reference", "id": "msg_1"},
        {"type": "item_reference", "id": "rs_1"},
        {"type": "item_reference", "id": "fc_1"},
        output,
        _user("Continue"),
    ]
    assert inline["input"] == [
        _user("Question"),
        {
            "id": "msg_1",
            "type": "message",
            "role": "assistant",
            "status": "completed",
            "content": [
                {"type": "output_text", "text": "Answer", "annotations": [], "logprobs": []}
            ],
        },
        {
            "type": "reasoning",
            "id": "rs_1",
            "summary": [{"type": "summary_text", "text": "Thinking"}],
            "encrypted_content": "encrypted-reasoning",
        },
        {
            "type": "function_call",
            "name": "TestTool",
            "call_id": "call_1",
            "arguments": '{"input":"value"}',
            "id": "fc_1",
        },
        output,
        _user("Continue"),
    ]
    assert "useItemReferences" not in inline
    assert "use_item_references" not in inline


@testing.effect
def test_provider_history_inline():
    """generateText / message preparation / assistant messages / replays matched provider-executed history inline"""  # noqa: E501
    mock = _mock()
    yield from _provided(
        lm.generate_text(
            _search_history(_PROVIDER_CALL, _PROVIDER_RESULT),
            toolkit=K.make(OT.WebSearch()),
            disable_tool_call_resolution=True,
        ),
        mock,
        "gpt-4o-mini",
        _INLINE,
    )
    assert mock.bodies[0]["input"] == [
        _user("Search"),
        {
            "type": "web_search_call",
            "id": "ws_1",
            "status": "completed",
            "action": {"type": "search", "query": "Effect TypeScript"},
        },
        _user("Continue"),
    ]


@testing.effect
def test_web_search_history_omitted_action():
    """generateText / message preparation / assistant messages / replays web search history with an omitted action"""  # noqa: E501
    mock = _mock()
    history = _search_history(
        _part("tool-call", id="ws_1", name="OpenAiWebSearch", params={}, providerExecuted=True),
        _part(
            "tool-result",
            id="ws_1",
            name="OpenAiWebSearch",
            providerExecuted=True,
            isFailure=True,
            result={"status": "incomplete"},
        ),
    )
    yield from _provided(
        lm.generate_text(
            history, toolkit=K.make(OT.WebSearch()), disable_tool_call_resolution=True
        ),
        mock,
        "gpt-6-luna",
        _INLINE,
    )
    assert mock.bodies[0]["input"][1] == {
        "type": "web_search_call",
        "id": "ws_1",
        "status": "incomplete",
    }


@testing.effect
def test_unreplayable_provider_history():
    """generateText / message preparation / assistant messages / fails locally when provider-executed history cannot be replayed inline"""  # noqa: E501
    mock = _mock()
    for part in (_PROVIDER_CALL, _PROVIDER_RESULT):
        error = yield from _provided(
            lm.generate_text(
                _search_history(part),
                toolkit=K.make(OT.WebSearch()),
                disable_tool_call_resolution=True,
            ).flip(),
            mock,
            "gpt-4o-mini",
            _INLINE,
        )
        assert isinstance(error.reason, E.InvalidRequestError)
        assert "OpenAiWebSearch" in (error.reason.description or "")
        assert "ws_1" in (error.reason.description or "")
    assert mock.requests == []


def _tool_history(
    id: str,
    result: object,
    name: str = "TestTool",
    params: object = None,
    prompt: str = "Use the tool",
) -> list[Any]:
    return [
        {"role": "user", "content": prompt},
        {
            "role": "assistant",
            "content": [
                _part(
                    "tool-call",
                    id=id,
                    name=name,
                    params={"input": "test"} if params is None else params,
                    providerExecuted=False,
                )
            ],
        },
        {
            "role": "tool",
            "content": [
                _part(
                    "tool-result",
                    id=id,
                    name=name,
                    isFailure=False,
                    result=result,
                    providerExecuted=False,
                )
            ],
        },
    ]


def _with_tools(prompt: Any, toolkit: Any, *layers: Any, **options: Any) -> Any:
    mock = _mock()
    return _provided(
        lm.generate_text(prompt, toolkit=toolkit, **options), mock, "gpt-4o-mini", None, *layers
    ).map(lambda _: mock.bodies[0])


@testing.effect
def test_tool_call_parts():
    """generateText / message preparation / assistant messages / converts tool call parts to function_call"""  # noqa: E501
    body = yield from _with_tools(
        _tool_history("call_abc", {"output": "result"}), TestToolkit, TestToolkitLayer
    )
    call = next(m for m in body["input"] if m.get("type") == "function_call")
    assert call["name"] == "TestTool"
    assert call["call_id"] == "call_abc"


@testing.effect
def test_tool_results():
    """generateText / message preparation / tool messages / converts tool results to function_call_output"""  # noqa: E501
    body = yield from _with_tools(
        _tool_history("call_abc", {"output": "result"}), TestToolkit, TestToolkitLayer
    )
    output = next(m for m in body["input"] if m.get("type") == "function_call_output")
    assert output["call_id"] == "call_abc"
    assert output["output"] == json.dumps({"output": "result"}, separators=(",", ":"))


@testing.effect
def test_string_tool_results():
    """generateText / message preparation / tool messages / preserves string tool results"""
    body = yield from _with_tools(
        _tool_history("call_text", "PLAIN_TEXT_SENTINEL\n"), TestToolkit, TestToolkitLayer
    )
    output = next(m for m in body["input"] if m.get("type") == "function_call_output")
    assert output["output"] == "PLAIN_TEXT_SENTINEL\n"


def _output_types(body: dict[str, Any], call_id: str) -> list[str]:
    return [
        item["type"]
        for item in body["input"]
        if item.get("call_id") == call_id and item["type"].endswith("_output")
    ]


@testing.effect
def test_apply_patch_output():
    """generateText / message preparation / tool messages / emits only the specialized output for apply_patch results"""  # noqa: E501
    history = _tool_history(
        "call_apply_patch",
        {"status": "completed", "output": "deleted"},
        "OpenAiApplyPatch",
        {"call_id": "call_apply_patch", "operation": {"type": "delete_file", "path": "old.ts"}},
        "Apply a patch",
    )
    body = yield from _with_tools(
        history, K.make(OT.ApplyPatch()), disable_tool_call_resolution=True
    )
    assert _output_types(body, "call_apply_patch") == ["apply_patch_call_output"]


@testing.effect
def test_shell_output():
    """generateText / message preparation / tool messages / emits only the specialized output for shell results"""  # noqa: E501
    history = _tool_history(
        "call_shell",
        {
            "output": [
                {"stdout": "hello\n", "stderr": "", "outcome": {"type": "exit", "exit_code": 0}}
            ]
        },
        "OpenAiShell",
        {"action": {"commands": ["echo hello"], "timeout_ms": None, "max_output_length": None}},
        "Run a shell command",
    )
    body = yield from _with_tools(history, K.make(OT.Shell()), disable_tool_call_resolution=True)
    assert _output_types(body, "call_shell") == ["shell_call_output"]


@testing.effect
def test_local_shell_output():
    """generateText / message preparation / tool messages / emits only the specialized output for local_shell results"""  # noqa: E501
    history = _tool_history(
        "call_local_shell",
        {"output": "hello\n"},
        "OpenAiLocalShell",
        {"action": {"type": "exec", "command": ["echo", "hello"], "env": {}}},
        "Run a local shell command",
    )
    body = yield from _with_tools(
        history, K.make(OT.LocalShell()), disable_tool_call_resolution=True
    )
    assert _output_types(body, "call_local_shell") == ["local_shell_call_output"]


# generateText / tool preparation --------------------------------------------------------


@testing.effect
def test_user_defined_tools():
    """generateText / tool preparation / converts user-defined tools to function type"""
    body = yield from _with_tools("Use the tool", TestToolkit, TestToolkitLayer)
    tool = next(t for t in body["tools"] if t["type"] == "function")
    assert tool["name"] == "TestTool"
    assert tool["description"] == "A test tool"
    assert tool["strict"] is True


@testing.effect
def test_dynamic_tools():
    """generateText / tool preparation / converts dynamic tools to function type"""
    schema: Any = {
        "type": "object",
        "properties": {"query": {"type": "string"}, "limit": {"type": "number"}},
        "required": ["query"],
        "additionalProperties": False,
    }
    tool = T.dynamic("DynamicTool", description="A dynamic tool", parameters=schema)
    body = yield from _with_tools(
        "Use the dynamic tool", K.make(tool), disable_tool_call_resolution=True
    )
    found = next(t for t in body["tools"] if t["type"] == "function" and t["name"] == "DynamicTool")
    assert found["description"] == "A dynamic tool"
    assert found["parameters"] == schema


@testing.effect
def test_non_object_parameters():
    """generateText / tool preparation / names the tool when its parameters are not an object schema

    Effect's case is ``Schema.Struct({})``, which its OpenAI codec rejects;
    without the codec, a string schema is the non-object case."""
    toolkit = K.make(T.make("NoParams", parameters=S.String))
    mock = _mock()
    error = yield from _provided(
        lm.generate_text("Use the tool", toolkit=toolkit, disable_tool_call_resolution=True).flip(),
        mock,
    )
    assert isinstance(error.reason, E.UnsupportedSchemaError)
    assert '"NoParams"' in error.message
    assert "Tool.EmptyParams" in error.message


@pytest.mark.parametrize(
    ("choice", "expected"),
    [
        ("auto", "auto"),
        ("none", "none"),
        ("required", "required"),
        ({"tool": "TestTool"}, {"type": "function", "name": "TestTool"}),
    ],
    ids=[
        "handles tool choice auto",
        "handles tool choice none",
        "handles tool choice required",
        "handles specific tool choice",
    ],
)
@testing.effect
def test_tool_choice(choice: Any, expected: Any):
    """generateText / tool preparation / handles tool choice auto, handles tool choice none,
    handles tool choice required, handles specific tool choice"""
    body = yield from _with_tools("Use the tool", TestToolkit, TestToolkitLayer, tool_choice=choice)
    assert body["tool_choice"] == expected


@testing.effect
def test_code_interpreter_tool():
    """generateText / tool preparation / adds code_interpreter tool"""
    body = yield from _with_tools(
        "Run some code", K.make(OT.CodeInterpreter(container={"type": "auto"}))
    )
    assert any(t["type"] == "code_interpreter" for t in body["tools"])


@testing.effect
def test_web_search_tool():
    """generateText / tool preparation / adds web_search tool"""
    body = yield from _with_tools("Search the web", K.make(OT.WebSearch()))
    assert any(t["type"] == "web_search" for t in body["tools"])


@testing.effect
def test_file_search_tool():
    """generateText / tool preparation / adds file_search tool with vector store IDs"""
    body = yield from _with_tools(
        "Search files", K.make(OT.FileSearch(vector_store_ids=["vs_123"]))
    )
    tool = next(t for t in body["tools"] if t["type"] == "file_search")
    assert tool["vector_store_ids"] == ["vs_123"]


# generateText / response format ---------------------------------------------------------


class Person(TypedDict):
    name: str
    age: float


@testing.effect
def test_text_format_default():
    """generateText / response format / uses text format by default"""
    body = yield from _generate("Hello")
    assert body["text"]["format"]["type"] == "text"


@testing.effect
def test_json_schema_format():
    """generateText / response format / uses json_schema format for structured output"""
    mock = _mock(output=[text_output(json.dumps({"name": "John", "age": 30}))])
    yield from _provided(lm.generate_object("Give me a person", schema=S.Struct(Person)), mock)
    format = mock.bodies[0]["text"]["format"]
    assert format["type"] == "json_schema"
    assert format["strict"] is True


# generateText / response handling -------------------------------------------------------


def _respond(
    *layers: Any, prompt: str = "Hello", model_name: str = "gpt-4o-mini", **body: Any
) -> Any:
    toolkit = body.pop("toolkit", None)
    options: dict[str, Any] = {} if toolkit is None else {"toolkit": toolkit}
    options.update(body.pop("options", {}))
    return _provided(lm.generate_text(prompt, **options), _mock(**body), model_name, None, *layers)


@testing.effect
def test_ultrafast_service_tier():
    """generateText / response handling / preserves ultrafast service tier alongside prompt cache diagnostics"""  # noqa: E501
    diagnostics = {
        "type": "cache_miss",
        "reason": "tools_changed",
        "cache_missed_tokens": 1024,
        "comparison_reusable_tokens": 2048,
    }
    body = json.dumps(
        {**response_body(service_tier="ultrafast"), "prompt_cache_diagnostics": diagnostics}
    )
    result = yield from _provided(lm.generate_text("test"), raw_mock(body, "application/json"))
    finish = _first(result.content, R.FinishPart)
    assert plain(finish.metadata["openai"]) == {
        "serviceTier": "ultrafast",
        "promptCacheDiagnostics": diagnostics,
    }


@testing.effect
def test_output_text():
    """generateText / response handling / extracts text from output_text"""
    result = yield from _respond(output=[text_output("Hello, world!")])
    assert result.text == "Hello, world!"


@testing.effect
def test_multiple_text_parts():
    """generateText / response handling / extracts multiple text parts"""
    result = yield from _respond(output=[text_output("First"), text_output("Second", id="msg_456")])
    assert len(_of(result.content, R.TextPart)) == 2


@testing.effect
def test_refusal():
    """generateText / response handling / handles refusal content"""
    refusal = {
        "type": "message",
        "id": "msg_123",
        "role": "assistant",
        "status": "completed",
        "content": [{"type": "refusal", "refusal": "I cannot do that"}],
    }
    result = yield from _respond(prompt="Do something bad", output=[refusal])
    text = _first(result.content, R.TextPart)
    assert text.text == ""
    assert P.obj(text.metadata["openai"])["refusal"] == "I cannot do that"


@testing.effect
def test_function_call_arguments():
    """generateText / response handling / parses function call arguments"""
    result = yield from _respond(
        TestToolkitLayer,
        prompt="Use the tool",
        toolkit=TestToolkit,
        output=[function_call("TestTool", {"input": "hello"})],
    )
    call = _first(result.content, R.ToolCallPart)
    assert call.name == "TestTool"
    assert call.params == {"input": "hello"}


@testing.effect
def test_dynamic_tool_raw_params():
    """generateText / response handling / preserves raw JSON Schema dynamic tool call params"""
    schema: Any = {
        "type": "object",
        "properties": {"query": {"type": "string"}},
        "required": ["query"],
        "additionalProperties": False,
    }
    params = {"query": "effect"}
    result = yield from _respond(
        prompt="Use the dynamic tool",
        toolkit=K.make(T.dynamic("DynamicTool", parameters=schema)),
        options={"disable_tool_call_resolution": True},
        output=[function_call("DynamicTool", params)],
    )
    assert result.tool_calls[0].params == params


ReturnModeTool = T.make(
    "ReturnModeTool",
    description="A test tool",
    failure_mode="return",
    parameters=S.Struct(Input),
    success=S.Struct(Output),
    failure=S.Struct(Failure),
)
ReturnModeToolkit = K.make(ReturnModeTool)
ReturnModeLayer = ReturnModeToolkit.to_layer(
    ReturnModeTool.handler(
        lambda params, _: fx.succeed({"output": f"processed: {params['input']}"})
    )
)


def _is_validation_failure(result: Any) -> bool:
    return (
        result.is_failure
        and isinstance(result.result, E.AiError)
        and isinstance(result.result.reason, E.ToolParameterValidationError)
    )


@testing.effect
def test_invalid_params_return_mode():
    """generateText / response handling / routes invalid tool call params through failureMode: return without failing the effect"""  # noqa: E501
    result = yield from _respond(
        ReturnModeLayer,
        prompt="Use the tool",
        toolkit=ReturnModeToolkit,
        output=[function_call("ReturnModeTool", {"input": 123})],
    )
    assert len(result.tool_results) == 1
    assert _is_validation_failure(result.tool_results[0])


class FiniteInput(TypedDict):
    input: float


class FiniteOutput(TypedDict):
    output: float


TransformParamsTool = T.make(
    "TransformParamsTool",
    description="A test tool",
    parameters=S.Struct(FiniteInput, input=S.FiniteFromString),
    success=S.Struct(FiniteOutput, output=S.Finite),
)


@testing.effect
def test_transformed_params():
    """generateText / response handling / converts transformed tool call params to the tool's standard encoded form"""  # noqa: E501
    received: list[float] = []
    toolkit = K.make(TransformParamsTool)

    def handle(params: FiniteInput, _: Any) -> Any:
        received.append(params["input"])
        return fx.succeed({"output": params["input"] * 2})

    result = yield from _respond(
        toolkit.to_layer(TransformParamsTool.handler(handle)),
        prompt="Use the tool",
        toolkit=toolkit,
        output=[function_call("TransformParamsTool", {"input": "21"})],
    )
    assert result.tool_calls[0].params == {"input": "21"}
    assert received == [21]
    assert result.tool_results[0].is_failure is False
    assert result.tool_results[0].result == {"output": 42}


@dataclass(frozen=True)
class ParamEncode:
    use: fx.Effect[None]


class ParamEncodeService(Tag[ParamEncode], key="ParamEncodeService"):
    pass


AsymmetricParam = S.String.pipe(
    S.decode_to(
        S.String,
        Tf.transform_effect(
            decode=lambda value, _: fx.succeed(value),
            encode=lambda value, _: (
                ParamEncodeService().flat_map(lambda service: service.use).map(lambda _: value)
            ),
        ),
    )
)

AsymmetricParamsTool = T.make(
    "AsymmetricParamsTool",
    description="A test tool",
    parameters=S.Struct(Input, input=AsymmetricParam),
    success=S.Struct(Output),
)


def _asymmetric(used: list[bool], *, resolve: bool) -> Any:
    toolkit = K.make(AsymmetricParamsTool)
    layers: list[Any] = []
    if resolve:
        layers.append(
            toolkit.to_layer(
                AsymmetricParamsTool.handler(
                    lambda params, _: fx.succeed({"output": f"processed: {params['input']}"})
                )
            )
        )
    return _respond(
        *layers,
        prompt="Use the tool",
        toolkit=toolkit,
        options={"disable_tool_call_resolution": not resolve},
        output=[function_call("AsymmetricParamsTool", {"input": "hello"})],
    ).pipe(fx.provide_service(ParamEncodeService, ParamEncode(fx.sync(lambda: used.append(True)))))


@testing.effect
def test_param_encoding_services():
    """generateText / response handling / provides parameter encoding services to provider normalization"""  # noqa: E501
    used: list[bool] = []
    result = yield from _asymmetric(used, resolve=True)
    assert used
    assert result.tool_results[0].is_failure is False
    assert result.tool_results[0].result == {"output": "processed: hello"}


@testing.effect
def test_param_encoding_services_unresolved():
    """generateText / response handling / provides parameter encoding services to provider normalization when tool call resolution is disabled"""  # noqa: E501
    used: list[bool] = []
    result = yield from _asymmetric(used, resolve=False)
    assert used
    assert result.tool_calls[0].params == {"input": "hello"}


McpToolkit = K.make(
    OT.Mcp(server_label="npm", server_url="https://example.com/mcp", require_approval="never")
)


@testing.effect
def test_mcp_call_name():
    """generateText / response handling / uses canonical OpenAiMcp name for mcp_call"""
    result = yield from _respond(
        prompt="Use MCP",
        toolkit=McpToolkit,
        output=[mcp_call("CheckPackage", {"packageName": "effect"})],
    )
    call = _first(result.content, R.ToolCallPart)
    assert call.name == "OpenAiMcp"
    assert call.params == {"packageName": "effect"}
    tool_result = _results(result.content)[0]
    assert tool_result.name == "OpenAiMcp"
    assert not tool_result.is_failure
    assert tool_result.result["name"] == "CheckPackage"


@pytest.mark.parametrize("model_name", ["gpt-4.1", "gpt-5.6"])
@testing.effect
def test_stable_web_search_action(model_name: str):
    """generateText / response handling / maps stable web search action to tool call parameters with %s"""  # noqa: E501
    action = {"type": "search", "query": "Effect TypeScript"}
    result = yield from _respond(
        prompt="Search the web",
        model_name=model_name,
        toolkit=K.make(OT.WebSearch()),
        model=model_name,
        output=[web_search_call()],
    )
    assert plain(_first(result.content, R.ToolCallPart).params) == {"action": action}
    assert plain(_results(result.content)[0].result) == {"action": action, "status": "completed"}


@pytest.mark.parametrize(
    ("tool", "status"),
    [
        (OT.WebSearch(), "failed"),
        (OT.WebSearch(), "incomplete"),
        (OT.WebSearchPreview(), "searching"),
    ],
    ids=[
        "OpenAiWebSearch preserves failed results",
        "OpenAiWebSearch preserves incomplete results",
        "OpenAiWebSearchPreview preserves searching results",
    ],
)
@testing.effect
def test_web_search_failures(tool: Any, status: str):
    """generateText / response handling / ${tool.name} preserves ${status} results"""
    result = yield from _respond(
        prompt="Search the web", toolkit=K.make(tool), output=[web_search_call(status=status)]
    )
    tool_result = result.tool_results[0]
    assert tool_result.is_failure is True
    assert plain(tool_result.result) == {
        "action": {"type": "search", "query": "Effect TypeScript"},
        "status": status,
    }


@pytest.mark.parametrize(
    ("status", "is_failure", "results"),
    [
        ("completed", False, None),
        ("failed", True, None),
        ("incomplete", True, [{"file_id": "file_123", "text": "Matching text"}]),
    ],
)
@testing.effect
def test_file_search_outcomes(status: str, is_failure: bool, results: Any):
    """generateText / response handling / OpenAiFileSearch reports $status results"""
    extra = {} if results is None and status == "completed" else {"results": results}
    result = yield from _respond(
        prompt="Search the files",
        toolkit=K.make(OT.FileSearch(vector_store_ids=["vs_123"])),
        output=[file_search_call(status=status, **extra)],
    )
    tool_result = result.tool_results[0]
    assert tool_result.is_failure is is_failure
    assert plain(tool_result.result) == {
        "status": status,
        "queries": ["Effect TypeScript"],
        "results": results,
    }


@testing.effect
def test_mcp_approval_request_name():
    """generateText / response handling / uses canonical OpenAiMcp name for mcp_approval_request"""
    result = yield from _respond(
        prompt="Use MCP",
        toolkit=McpToolkit,
        output=[mcp_approval_request("CheckPackage", {"packageName": "effect"})],
    )
    call = _first(result.content, R.ToolCallPart)
    assert call.name == "OpenAiMcp"
    assert call.params == {"packageName": "effect"}
    approval = _first(result.content, R.ToolApprovalRequestPart)
    assert approval.tool_call_id == call.id


@testing.effect
def test_reasoning_parts():
    """generateText / response handling / extracts reasoning parts"""
    result = yield from _respond(
        prompt="Think about this",
        model_name="o1",
        model="o1",
        output=[reasoning_output(["First thought", "Second thought"])],
    )
    reasoning = _of(result.content, R.ReasoningPart)
    assert len(reasoning) == 2
    assert reasoning[0].text == "First thought"


_CACHED_USAGE = usage(input_tokens_details={"cached_tokens": 3, "cache_write_tokens": 4})
_CACHED_INPUT = R.InputTokens(uncached=7, total=10, cache_read=3, cache_write=4)


@testing.effect
def test_usage():
    """generateText / response handling / extracts usage information"""
    result = yield from _respond(output=[text_output("Hello")], usage=_CACHED_USAGE)
    finish = _first(result.content, R.FinishPart)
    assert finish.usage.input_tokens == _CACHED_INPUT
    assert finish.usage.output_tokens == R.OutputTokens(total=20, text=20, reasoning=0)


@testing.effect
def test_incomplete_details_finish_reason():
    """generateText / response handling / determines finish reason from incomplete_details"""
    result = yield from _respond(
        output=[text_output("Hello")], incomplete_details={"reason": "content_filter"}
    )
    assert _first(result.content, R.FinishPart).reason == "content-filter"


@testing.effect
def test_default_finish_reason():
    """generateText / response handling / defaults finish reason to stop"""
    result = yield from _respond(output=[text_output("Hello")])
    assert _first(result.content, R.FinishPart).reason == "stop"


@testing.effect
def test_tool_calls_finish_reason():
    """generateText / response handling / sets finish reason to tool-calls when has tool calls"""
    result = yield from _respond(
        TestToolkitLayer,
        prompt="Use the tool",
        toolkit=TestToolkit,
        output=[function_call("TestTool", {"input": "test"})],
    )
    assert _first(result.content, R.FinishPart).reason == "tool-calls"


@testing.effect
def test_length_interrupts_tool_calls():
    """generateText / response handling / reports length and interrupts tool calls when max_output_tokens truncates the response"""  # noqa: E501
    result = yield from _respond(
        TestToolkitLayer,
        prompt="Use the tool",
        toolkit=TestToolkit,
        status="incomplete",
        output=[function_call("TestTool", {"input": "test"})],
        incomplete_details={"reason": "max_output_tokens"},
    )
    assert result.finish_reason == "length"
    assert [plain(part.result) for part in result.tool_results] == [
        {
            "type": "execution-interrupted",
            "reason": 'Tool call execution was interrupted because the response finished with reason "length"',  # noqa: E501
        }
    ]


@testing.effect
def test_url_citations():
    """generateText / response handling / extracts url citations as source parts"""
    annotation = {
        "type": "url_citation",
        "url": "https://example.com",
        "title": "Example",
        "start_index": 0,
        "end_index": 14,
    }
    message = text_output("Check this out")
    message["content"][0]["annotations"] = [annotation]
    result = yield from _respond(output=[message])
    source = _first(result.content, R.UrlSourcePart)
    assert href(source.url) == "https://example.com/"
    assert source.title == "Example"


# streamText -----------------------------------------------------------------------------


def _created(**overrides: Any) -> dict[str, Any]:
    return {
        "type": "response.created",
        "sequence_number": 1,
        "response": response_body(status="in_progress", **overrides),
    }


def _completed(sequence: int, **overrides: Any) -> dict[str, Any]:
    return {
        "type": "response.completed",
        "sequence_number": sequence,
        "response": response_body(**overrides),
    }


def _item_event(kind: str, sequence: int, item: dict[str, Any], index: int = 0) -> dict[str, Any]:
    return {
        "type": f"response.output_item.{kind}",
        "sequence_number": sequence,
        "output_index": index,
        "item": item,
    }


@pytest.mark.parametrize(
    ("status", "tier", "expected"),
    [
        ("completed", "fast", {"promptCacheDiagnostics": {"type": "cache_hit"}}),
        (
            "completed",
            "ultrafast",
            {"serviceTier": "ultrafast", "promptCacheDiagnostics": {"type": "cache_hit"}},
        ),
        (
            "failed",
            "ultrafast",
            {"serviceTier": "ultrafast", "promptCacheDiagnostics": {"type": "cache_hit"}},
        ),
    ],
)
@testing.effect
def test_stream_service_tiers(status: str, tier: str, expected: dict[str, Any]):
    """streamText / preserves supported tiers and prompt cache diagnostics in response.$status with $serviceTier"""  # noqa: E501
    error = {"code": "server_error", "message": "generation failed"} if status == "failed" else None
    event = {
        "type": f"response.{status}",
        "sequence_number": 1,
        "response": {
            **response_body(status=status, error=error),
            "service_tier": tier,
            "prompt_cache_diagnostics": {"type": "cache_hit"},
        },
    }
    mock = raw_mock(f"data: {json.dumps(event)}\n\n", "text/event-stream")
    parts = yield from _provided(lm.stream_text(prompt="test").run_collect(), mock)
    assert plain(_first(parts, R.FinishPart).metadata["openai"]) == expected


@testing.effect
def test_stream_usage():
    """streamText / extracts usage information"""
    parts = yield from _stream_parts(
        [_created(), _completed(2, usage=_CACHED_USAGE)], prompt="Hello"
    )
    assert _first(parts, R.FinishPart).usage.input_tokens == _CACHED_INPUT


def _stream_params(parts: Sequence[object], id: str) -> Any:
    """Effect's ``decodeToolParamsFromStream``."""
    assert any(isinstance(p, R.ToolParamsStartPart) and p.id == id for p in parts)
    assert any(isinstance(p, R.ToolParamsEndPart) and p.id == id for p in parts)
    deltas = "".join(p.delta for p in _of(parts, R.ToolParamsDeltaPart) if p.id == id)
    return json.loads(deltas)


@testing.effect
def test_stream_apply_patch_params():
    """streamText / emits valid apply_patch tool params JSON for update_file diffs"""
    diff = "@@ -1 +1 @@\n-old\n+new\n"
    operation = {"type": "update_file", "path": "src/example.ts", "diff": diff}
    item = {
        "type": "apply_patch_call",
        "id": "patch_item_1",
        "call_id": "patch_call_1",
        "status": "in_progress",
        "operation": operation,
    }
    events = [
        _created(id="resp_patch_stream"),
        _item_event("added", 2, item),
        {
            "type": "response.apply_patch_call_operation_diff.delta",
            "sequence_number": 3,
            "output_index": 0,
            "item_id": "patch_item_1",
            "delta": diff,
        },
        {
            "type": "response.apply_patch_call_operation_diff.done",
            "sequence_number": 4,
            "output_index": 0,
            "item_id": "patch_item_1",
        },
    ]
    parts = yield from _stream_parts(
        events, prompt="Update src/example.ts", disable_tool_call_resolution=True
    )
    assert _stream_params(parts, "patch_call_1") == {
        "call_id": "patch_call_1",
        "operation": operation,
    }


def _function_events(name: str, arguments: str, *, delta: str | None = None) -> list[Any]:
    added = function_call(name, {}, id="fc_1", call_id="call_1", arguments="", status="in_progress")
    events: list[Any] = [_created(id="resp_function_call_done"), _item_event("added", 2, added)]
    if delta is not None:
        events.append(
            {
                "type": "response.function_call_arguments.delta",
                "sequence_number": 3,
                "output_index": 0,
                "item_id": "fc_1",
                "delta": delta,
            }
        )
    events.append(
        {
            "type": "response.function_call_arguments.done",
            "sequence_number": 4,
            "output_index": 0,
            "item_id": "fc_1",
            "name": name,
            "arguments": arguments,
        }
    )
    events.append(_completed(5, id="resp_function_call_done"))
    return events


def _with_layers(effect: Any, *layers: Any) -> Any:
    for extra in layers:
        effect = effect.pipe(fx.provide(extra))
    return effect


@testing.effect
def test_stream_function_arguments_done():
    """streamText / emits tool call from function_call_arguments.done when output_item.done is missing"""  # noqa: E501
    parts = yield from _with_layers(
        _stream_parts(
            _function_events("TestTool", '{"input":"hello"}', delta='{"input":"hel'),
            prompt="Use the test tool",
            toolkit=TestToolkit,
            disable_tool_call_resolution=True,
        ),
        TestToolkitLayer,
    )
    calls = [p for p in _of(parts, R.ToolCallPart) if p.id == "call_1"]
    assert [(c.name, c.params) for c in calls] == [("TestTool", {"input": "hello"})]
    assert any(isinstance(p, R.ToolParamsEndPart) and p.id == "call_1" for p in parts)


@testing.effect
def test_stream_invalid_params_return_mode():
    """streamText / routes invalid tool call params through failureMode: return without failing the stream"""  # noqa: E501
    parts = yield from _with_layers(
        _stream_parts(
            _function_events("ReturnModeTool", '{"input":123}'),
            prompt="Use the test tool",
            toolkit=ReturnModeToolkit,
        ),
        ReturnModeLayer,
    )
    results = _results(parts)
    assert len(results) == 1
    assert _is_validation_failure(results[0])
    assert any(isinstance(p, R.FinishPart) for p in parts)


@testing.effect
def test_stream_undeclared_tool_calls():
    """streamText / streams undeclared tool calls when tool call validation is deferred"""
    events = [
        _created(),
        _item_event("added", 2, function_call("Write", {}, arguments="", status="in_progress")),
        _item_event("done", 3, function_call("Write", {"path": "a"})),
        _completed(4),
    ]
    parts = yield from _with_layers(
        _stream_parts(
            events,
            prompt="Use the tools",
            toolkit=TestToolkit,
            disable_tool_call_resolution=True,
            tool_call_validation="deferred",
        ),
        TestToolkitLayer,
    )
    assert [(c.name, c.params) for c in _of(parts, R.ToolCallPart)] == [("Write", {"path": "a"})]


@testing.effect
def test_stream_stable_web_search_action():
    """streamText / waits for the stable streamed web search action before emitting the tool call"""
    events = [
        _created(),
        _item_event(
            "added", 2, {"type": "web_search_call", "id": "ws_123", "status": "in_progress"}
        ),
        _item_event("done", 3, web_search_call()),
    ]
    parts = yield from _stream_parts(
        events,
        prompt="Search the web",
        toolkit=K.make(OT.WebSearch()),
        disable_tool_call_resolution=True,
    )
    action = {"type": "search", "query": "Effect TypeScript"}
    calls = _of(parts, R.ToolCallPart)
    assert [plain(c.params) for c in calls] == [{"action": action}]
    assert plain(_results(parts)[0].result) == {"action": action, "status": "completed"}


@pytest.mark.parametrize(
    ("tool", "status"),
    [
        (OT.WebSearch(), "failed"),
        (OT.WebSearch(), "incomplete"),
        (OT.WebSearchPreview(), "searching"),
    ],
    ids=[
        "OpenAiWebSearch preserves failed results from output_item.done",
        "OpenAiWebSearch preserves incomplete results from output_item.done",
        "OpenAiWebSearchPreview preserves searching results from output_item.done",
    ],
)
@testing.effect
def test_stream_web_search_failures(tool: Any, status: str):
    """streamText / ${tool.name} preserves ${status} results from output_item.done"""
    parts = yield from _stream_parts(
        [_item_event("done", 1, web_search_call(status=status))],
        prompt="Search the web",
        toolkit=K.make(tool),
    )
    result = _results(parts)[0]
    assert result.is_failure is True
    assert plain(result.result) == {
        "action": {"type": "search", "query": "Effect TypeScript"},
        "status": status,
    }


@pytest.mark.parametrize(
    ("status", "is_failure", "results"),
    [
        ("completed", False, None),
        ("failed", True, None),
        ("incomplete", True, [{"file_id": "file_123", "text": "Matching text"}]),
    ],
)
@testing.effect
def test_stream_file_search_outcomes(status: str, is_failure: bool, results: Any):
    """streamText / OpenAiFileSearch reports $status results from output_item.done"""
    extra = {} if results is None and status == "completed" else {"results": results}
    parts = yield from _stream_parts(
        [_item_event("done", 1, file_search_call(status=status, **extra))],
        prompt="Search the files",
        toolkit=K.make(OT.FileSearch(vector_store_ids=["vs_123"])),
    )
    result = _results(parts)[0]
    assert result.is_failure is is_failure
    assert plain(result.result) == {
        "status": status,
        "queries": ["Effect TypeScript"],
        "results": results,
    }


@testing.effect
def test_stream_reasoning_without_state():
    """streamText / handles reasoning summary events when reasoning state is missing"""

    def summary(kind: str, sequence: int, **extra: Any) -> dict[str, Any]:
        return {
            "type": f"response.reasoning_summary_{kind}",
            "sequence_number": sequence,
            "output_index": 0,
            "item_id": "rs_missing",
            "summary_index": 1,
            **extra,
        }

    events = [
        _created(id="resp_reasoning_missing_state"),
        summary("part.added", 2),
        summary("text.delta", 3, delta="thinking"),
        summary("part.done", 4),
        _item_event("done", 5, reasoning_output(["thinking"], id="rs_missing")),
        _item_event("done", 6, reasoning_output([], id="rs_done_only"), 1),
        _completed(7, id="resp_reasoning_missing_state"),
    ]
    parts = yield from _stream_parts(events, prompt="reason")
    assert any(isinstance(p, R.ReasoningStartPart) and p.id == "rs_missing:1" for p in parts)
    assert any(isinstance(p, R.ReasoningEndPart) and p.id == "rs_missing:1" for p in parts)
    assert any(isinstance(p, R.FinishPart) for p in parts)


@testing.effect
def test_stream_mcp_call_name():
    """streamText / uses canonical OpenAiMcp name for streamed mcp_call"""
    item = mcp_call("CheckPackage", {"packageName": "effect"}, id="mcp_call_1")
    parts = yield from _stream_parts(
        [_created(id="resp_mcp_stream"), _item_event("done", 2, item)],
        prompt="Use MCP",
        toolkit=McpToolkit,
        disable_tool_call_resolution=True,
    )
    call = _first(parts, R.ToolCallPart)
    assert call.name == "OpenAiMcp"
    assert call.params == {"packageName": "effect"}
    result = _results(parts)[0]
    assert result.name == "OpenAiMcp"
    assert not result.is_failure
    assert result.result["name"] == "CheckPackage"


@testing.effect
def test_stream_mcp_approval_request_name():
    """streamText / uses canonical OpenAiMcp name for streamed mcp_approval_request"""
    item = mcp_approval_request("CheckPackage", {"packageName": "effect"}, id="approval_1")
    parts = yield from _stream_parts(
        [_created(id="resp_mcp_approval_stream"), _item_event("done", 2, item)],
        prompt="Use MCP",
        toolkit=McpToolkit,
        disable_tool_call_resolution=True,
    )
    call = _first(parts, R.ToolCallPart)
    assert call.name == "OpenAiMcp"
    assert call.params == {"packageName": "effect"}
    assert _first(parts, R.ToolApprovalRequestPart).tool_call_id == call.id


@testing.effect
def test_denied_mcp_approvals():
    """streamText / pre-resolves denied OpenAiMcp approvals without lookup failure"""
    prompt = [
        {
            "role": "assistant",
            "content": [
                _part(
                    "tool-call",
                    id="mcp_tool_call_1",
                    name="OpenAiMcp",
                    params={"packageName": "effect"},
                    providerExecuted=True,
                ),
                _part(
                    "tool-approval-request", approvalId="approval_1", toolCallId="mcp_tool_call_1"
                ),
            ],
        },
        {
            "role": "tool",
            "content": [
                _part(
                    "tool-approval-response",
                    approvalId="approval_1",
                    approved=False,
                    reason="Denied",
                )
            ],
        },
        {"role": "user", "content": "Continue"},
    ]
    result = yield from _provided(
        lm.generate_text(prompt, toolkit=McpToolkit),
        _mock(output=[text_output("Handled denied MCP approval")]),
    )
    assert result.text == "Handled denied MCP approval"


# withConfigOverride / config ------------------------------------------------------------


@testing.effect
def test_config_override_merges():
    """withConfigOverride / merges config overrides"""
    mock = _mock()
    yield from _provided(
        lm.generate_text("test").pipe(olm.with_config_override({"temperature": 0.5})), mock
    )
    assert mock.bodies[0]["temperature"] == 0.5


@testing.effect
def test_config_override_precedence():
    """withConfigOverride / override takes precedence"""
    mock = _mock()
    yield from _provided(
        lm.generate_text("test").pipe(olm.with_config_override({"temperature": 0.9})),
        mock,
        "gpt-4o-mini",
        {"temperature": 0.5},
    )
    assert mock.bodies[0]["temperature"] == 0.9


@testing.effect
def test_library_fields_not_leaked():
    """config / does not leak library-only fields into request body"""
    config: olm.ModelConfig = {
        "file_id_prefixes": ["file-"],
        "strict_json_schema": False,
        "use_item_references": False,
        "reasoning_model": True,
        "temperature": 0.5,
    }
    body = yield from _generate("test", config=config)
    for key in [
        *config,
        "fileIdPrefixes",
        "strictJsonSchema",
        "useItemReferences",
        "reasoningModel",
    ]:
        if key != "temperature":
            assert key not in body
    assert body["temperature"] == 0.5


# reasoning capabilities -----------------------------------------------------------------


@testing.effect
def test_merges_include_values():
    """reasoning capabilities / merges explicit include values with generated values"""
    body = yield from _generate(
        "test",
        "custom-model",
        {
            "store": False,
            "include": ["message.input_image.image_url", "reasoning.encrypted_content"],
            "top_logprobs": 2,
        },
    )
    assert body["include"] == [
        "message.input_image.image_url",
        "reasoning.encrypted_content",
        "message.output_text.logprobs",
    ]


@pytest.mark.parametrize(
    ("model_name", "config", "include", "role"),
    [
        ("custom-model", {"store": False}, ["reasoning.encrypted_content"], "developer"),
        (
            "custom-model",
            {
                "store": False,
                "reasoning_model": False,
                "include": ["message.input_image.image_url"],
            },
            ["message.input_image.image_url"],
            "system",
        ),
    ],
    ids=[
        "defaults an unknown model to reasoning",
        "disables automatic reasoning without dropping explicit includes",
    ],
)
@testing.effect
def test_reasoning_capabilities(
    model_name: str, config: olm.ModelConfig, include: list[str], role: str
):
    """reasoning capabilities / defaults an unknown model to reasoning, disables automatic reasoning without dropping explicit includes"""  # noqa: E501
    body = yield from _generate(_SYSTEM_PROMPT, model_name, config, model=model_name)
    assert body.get("include") == include
    assert body["input"][0]["role"] == role


@testing.effect
def test_reasoning_model_override():
    """reasoning capabilities / prefers the reasoningModel override from withConfigOverride"""
    mock = _mock(model="gpt-4.1")
    yield from _provided(
        lm.generate_text(_SYSTEM_PROMPT).pipe(olm.with_config_override({"reasoning_model": True})),
        mock,
        "gpt-4.1",
        {"store": False, "reasoning_model": False},
    )
    assert mock.bodies[0]["include"] == ["reasoning.encrypted_content"]
    assert mock.bodies[0]["input"][0]["role"] == "developer"
