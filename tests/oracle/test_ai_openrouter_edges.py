"""Edges of ``pyfect.ai.openrouter`` that Effect's own tests leave open,
each checked against Effect's ``@effect/ai-openrouter`` run under Node
(the expected values are Node's output): reasoning details sent once per
request, a message's cache breakpoint on its last text only, ``image/*``
sent as JPEG, the streamed request's usage option, reasoning details on
the first tool call only, streamed reasoning text details merged and
unfinished calls flushed in index order, an error chunk finishing with
``error``, the generated 429 body dropping an undocumented ``type`` (a
decisions 429 keeps it), an undocumented 409, and the tool schemas of each
model family, the URLs ``api_url`` gives. ``Config`` is pinned to the
generated request's keys."""

from __future__ import annotations

# pyright: reportUnknownVariableType=false, reportUnknownArgumentType=false
# pyright: reportUnknownMemberType=false, reportUnknownLambdaType=false
from typing import Any, NotRequired, TypedDict

import pytest

import pyfect as fx
from pyfect import schema as S
from pyfect import testing
from pyfect.ai import ai_error as E
from pyfect.ai import language_model as lm
from pyfect.ai import prompt as Pr
from pyfect.ai import tool as T
from pyfect.ai import toolkit as K
from pyfect.ai.openrouter import client, language_model
from pyfect.ai.openrouter.generated import types as GT
from pyfect.redacted import make as redact

from ._ai_http import MockHttp, json_response, mock_sse

GEMINI = "google/gemini-2.5-flash"


def _base(**overrides: Any) -> dict[str, Any]:
    return {
        "id": "gen-1",
        "created": 1234567890,
        "model": "m",
        "object": "chat.completion",
        "system_fingerprint": None,
        "choices": [
            {"finish_reason": "stop", "index": 0, "message": {"role": "assistant", "content": "Hi"}}
        ],
        **overrides,
    }


def _json(body: object, status: int = 200) -> MockHttp:
    headers = {"x-request-id": "req-1"}
    return MockHttp(
        lambda request: fx.succeed(json_response(request, body, status=status, headers=headers))
    )


def _provided(
    effect: fx.Effect[Any, Any, Any], http: MockHttp, model: str = GEMINI
) -> fx.Effect[Any, Any, Any]:
    return (
        effect.pipe(fx.provide(language_model.layer(model=model)))
        .pipe(fx.provide(client.layer(api_key=redact("k"))))
        .pipe(fx.provide(http.layer))
    )


def _chunk(delta: dict[str, Any], **extra: Any) -> dict[str, Any]:
    return {
        "id": "gen-s",
        "created": 1,
        "model": "m",
        "object": "chat.completion.chunk",
        "choices": [{"index": 0, "delta": delta, **extra}],
    }


_USAGE = {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3}


class A(TypedDict):
    a: float


class OptionalA(TypedDict):
    a: NotRequired[float]


_TOOL = T.make("T", parameters=S.Struct(A))
_OPTIONAL_TOOL = T.make("T", parameters=S.Struct(OptionalA))


def _tool_calls(parts: Any) -> list[Any]:
    """Each call's id, parameters and metadata, as JSON."""
    return [
        (part.id, _json_value(part.params), _json_value(part.metadata))
        for part in parts
        if part.type == "tool-call"
    ]


def _json_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _json_value(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_json_value(item) for item in value]
    return value


@testing.effect
def test_reasoning_details_sent_once_per_request():
    """A detail replayed by a later assistant turn is not sent again, and a
    text detail with neither text nor signature is never sent."""
    detail = {
        "type": "reasoning.text",
        "text": "think",
        "signature": "sig",
        "format": "anthropic-claude-v1",
    }
    keyless = {"type": "reasoning.text", "format": "x"}
    encrypted = {"type": "reasoning.encrypted", "data": "d1"}
    http = _json(_base())
    prompt = Pr.make(
        [
            Pr.UserMessage(content=[Pr.TextPart(text="q")]),
            Pr.AssistantMessage(
                content=[Pr.TextPart(text="a")],
                options={"openrouter": {"reasoningDetails": [detail, keyless, encrypted]}},
            ),
            Pr.UserMessage(content=[Pr.TextPart(text="q2")]),
            Pr.AssistantMessage(
                content=[Pr.TextPart(text="b")],
                options={"openrouter": {"reasoningDetails": [detail, {**encrypted, "id": "e2"}]}},
            ),
            Pr.UserMessage(content=[Pr.TextPart(text="q3")]),
        ]
    )
    yield from _provided(lm.generate_text(prompt), http)
    assistants = [m for m in http.bodies[0]["messages"] if m["role"] == "assistant"]
    assert [m.get("reasoning_details") for m in assistants] == [
        [detail, encrypted],
        [{**encrypted, "id": "e2"}],
    ]


@testing.effect
def test_user_cache_breakpoint_on_last_text_and_any_image_as_jpeg():
    """A user message's breakpoint goes on its last text part only; an
    ``image/*`` file is sent as ``image/jpeg``."""
    http = _json(_base())
    message = Pr.UserMessage(
        content=[
            Pr.TextPart(text="a"),
            Pr.FilePart(media_type="image/*", data=bytes([1, 2, 3])),
            Pr.TextPart(text="b"),
            Pr.FilePart(media_type="image/png", data=bytes([1])),
        ],
        options={"openrouter": {"cacheControl": {"type": "ephemeral"}}},
    )
    yield from _provided(lm.generate_text(Pr.make([message])), http)
    assert http.bodies[0]["messages"][0]["content"] == [
        {"type": "text", "text": "a"},
        {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,AQID"}},
        {"type": "text", "text": "b", "cache_control": {"type": "ephemeral"}},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,AQ=="}},
    ]


@testing.effect
def test_streamed_request_asks_for_usage():
    """A streamed request sets ``stream`` and ``stream_options.include_usage``."""
    http = mock_sse(["[DONE]"])
    yield from _provided(lm.stream_text(prompt="hi").run_drain(), http)
    body = http.bodies[0]
    assert (body["stream"], body["stream_options"]) == (True, {"include_usage": True})


@testing.effect
def test_reasoning_details_on_first_tool_call_only():
    """The reasoning details of a response go on its first tool call only."""
    details = [{"type": "reasoning.text", "text": "plan"}]
    calls = [
        {"id": "c1", "type": "function", "function": {"name": "T", "arguments": '{"a":1}'}},
        {"id": "c2", "type": "function", "function": {"name": "T", "arguments": '{"a":2}'}},
    ]
    message = {
        "role": "assistant",
        "content": None,
        "reasoning_details": details,
        "tool_calls": calls,
    }
    http = _json(_base(choices=[{"finish_reason": "tool_calls", "index": 0, "message": message}]))
    toolkit = K.make(_TOOL)
    response = yield from _provided(
        lm.generate_text(prompt="x", toolkit=toolkit, disable_tool_call_resolution=True), http
    )
    assert _tool_calls(response.content) == [
        ("c1", {"a": 1}, {"openrouter": {"reasoningDetails": details}}),
        ("c2", {"a": 2}, {}),
    ]


def _stream(events: list[Any], **options: Any) -> fx.Effect[list[Any], Any, Any]:
    return _provided(
        lm.stream_text(**options).run_collect().map(list), mock_sse([*events, "[DONE]"])
    )


@testing.effect
def test_streamed_unfinished_calls_flush_in_index_order():
    """Consecutive streamed text details merge; at a ``tool_calls`` finish the
    unfinished calls are sent by index with ``{}`` parameters, the merged
    details on the first only."""
    merged = {
        "format": "anthropic-claude-v1",
        "text": "hello",
        "type": "reasoning.text",
        "signature": "s1",
    }
    events = [
        _chunk(
            {
                "reasoning_details": [
                    {"type": "reasoning.text", "text": "he", "format": "anthropic-claude-v1"}
                ]
            }
        ),
        _chunk(
            {"reasoning_details": [{"type": "reasoning.text", "text": "llo", "signature": "s1"}]}
        ),
        _chunk(
            {
                "tool_calls": [
                    {
                        "index": 1,
                        "id": "c-one",
                        "type": "function",
                        "function": {"name": "T", "arguments": '{"a":'},
                    }
                ]
            }
        ),
        _chunk(
            {
                "tool_calls": [
                    {
                        "index": 0,
                        "id": "c-zero",
                        "type": "function",
                        "function": {"name": "T", "arguments": '{"a"'},
                    }
                ]
            }
        ),
        {**_chunk({}, finish_reason="tool_calls"), "usage": _USAGE},
    ]
    parts = yield from _stream(
        events, prompt="x", toolkit=K.make(_OPTIONAL_TOOL), disable_tool_call_resolution=True
    )
    assert _tool_calls(parts) == [
        ("c-zero", {}, {"openrouter": {"reasoningDetails": [merged]}}),
        ("c-one", {}, {}),
    ]
    end = next(part for part in parts if part.type == "reasoning-end")
    assert end.metadata == {"openrouter": {"reasoningDetails": [merged]}}


@testing.effect
def test_streamed_reasoning_details_on_first_tool_call_only():
    """Streamed calls finishing mid-stream carry the details on the first only."""
    events = [
        _chunk({"reasoning_details": [{"type": "reasoning.text", "text": "r"}]}),
        _chunk(
            {
                "tool_calls": [
                    {
                        "index": 0,
                        "id": "c0",
                        "type": "function",
                        "function": {"name": "T", "arguments": '{"a":1}'},
                    }
                ]
            }
        ),
        _chunk(
            {
                "tool_calls": [
                    {
                        "index": 1,
                        "id": "c1",
                        "type": "function",
                        "function": {"name": "T", "arguments": '{"a":2}'},
                    }
                ]
            }
        ),
        {**_chunk({}, finish_reason="tool_calls"), "usage": _USAGE},
    ]
    parts = yield from _stream(
        events, prompt="x", toolkit=K.make(_TOOL), disable_tool_call_resolution=True
    )
    assert _tool_calls(parts) == [
        (
            "c0",
            {"a": 1},
            {"openrouter": {"reasoningDetails": [{"text": "r", "type": "reasoning.text"}]}},
        ),
        ("c1", {"a": 2}, {}),
    ]


@testing.effect
def test_error_chunk_finishes_with_error():
    """A chunk carrying ``error`` emits an error part and finishes with ``error``."""
    error = {"code": 502, "message": "upstream"}
    last = {
        "id": "gen-s",
        "created": 1,
        "model": "m",
        "object": "chat.completion.chunk",
        "choices": [],
        "error": error,
        "usage": _USAGE,
    }
    parts = yield from _stream([_chunk({"content": "a"}), last], prompt="x")
    assert [part.error for part in parts if part.type == "error"] == [error]
    assert next(part for part in parts if part.type == "finish").reason == "error"


@testing.effect
def test_documented_429_drops_undocumented_type():
    """A chat completion 429 decodes by its generated schema, which has no
    ``type``: an ``insufficient_quota`` type alone is still a rate limit."""
    body = {"error": {"message": "no credits", "type": "insufficient_quota", "code": 429}}
    error = yield from _provided(lm.generate_text(prompt="x").flip(), _json(body, 429))
    assert isinstance(error.reason, E.RateLimitError)
    assert error.reason.metadata == {
        "openrouter": {
            "errorCode": 429,
            "errorType": None,
            "requestId": "req-1",
            "limit": None,
            "remaining": None,
            "resetRequests": None,
            "resetTokens": None,
        }
    }


@testing.effect
def test_undocumented_409_is_invalid_request():
    """A 409 (not a documented status) is an invalid request with the body's
    code."""
    body = {"error": {"message": "conflict", "code": "conflict"}}
    error = yield from _provided(lm.generate_text(prompt="x").flip(), _json(body, 409))
    assert isinstance(error.reason, E.InvalidRequestError)
    assert error.reason.metadata == {
        "openrouter": {"errorCode": "conflict", "errorType": None, "requestId": "req-1"}
    }
    assert error.reason.description == (
        "conflict (POST https://openrouter.ai/api/v1/chat/completions) "
        "[code: conflict] [requestId: req-1]"
    )


class Pair(TypedDict):
    """Effect's ``{ pair: Tuple([String, Number]), opt: optionalKey(String) }``."""

    pair: tuple[str, float]
    opt: NotRequired[str]


_REWRITTEN = {
    "type": "object",
    "properties": {
        "pair": {
            "type": "object",
            "properties": {
                "0": {"type": "string"},
                "1": {
                    "anyOf": [
                        {"type": "number"},
                        {"type": "string", "enum": ["Infinity", "-Infinity", "NaN"]},
                    ]
                },
            },
            "required": ["0", "1"],
            "additionalProperties": False,
            "description": "Tuple encoded as an object with numeric string keys ('0', '1', ...). "
            "If present, '__rest__' contains remaining elements",
        },
        "opt": {"anyOf": [{"type": "string"}, {"type": "null"}]},
    },
    "required": ["pair", "opt"],
    "additionalProperties": False,
}

_DEFAULT = {
    "type": "object",
    "properties": {
        "pair": {
            "type": "array",
            "prefixItems": [
                {"type": "string"},
                {
                    "anyOf": [
                        {"type": "number"},
                        {"type": "string", "enum": ["Infinity", "-Infinity", "NaN"]},
                    ]
                },
            ],
            "maxItems": 2,
            "minItems": 2,
        },
        "opt": {"type": "string"},
    },
    "required": ["pair"],
    "additionalProperties": True,
}


@pytest.mark.parametrize(
    ("model", "expected"),
    [
        ("anthropic/claude-sonnet-4.5", _REWRITTEN),
        ("claude-3", _REWRITTEN),
        (GEMINI, _DEFAULT),
        ("openai/gpt-4o", _REWRITTEN),
    ],
)
@testing.effect
def test_tool_schema_of_model_family(model: str, expected: dict[str, Any]):
    """Tool parameters are written for the model's family."""
    http = _json(_base())
    tool = T.make("D", parameters=S.Struct(Pair, pair=S.Tuple(S.String, S.Number)))
    yield from _provided(
        lm.generate_text(prompt="x", toolkit=K.make(tool), disable_tool_call_resolution=True),
        http,
        model,
    )
    assert http.bodies[0]["tools"][0]["function"]["parameters"] == expected


@testing.effect
def test_decisions_insufficient_quota_type_exhausts_quota():
    """A decisions 429 keeps the body's ``type``: ``insufficient_quota`` as the
    type alone is an exhausted quota."""
    body = {"error": {"message": "no credits", "type": "insufficient_quota", "code": 429}}
    sent = client.OpenRouterClient().flat_map(
        lambda c: c.create_decisions({"model": "m", "state": "s", "questions": {}}).flip()
    )
    error = yield from sent.pipe(fx.provide(client.layer(api_key=redact("k")))).pipe(
        fx.provide(_json(body, 429).layer)
    )
    assert error.method == "createDecisions"
    assert isinstance(error.reason, E.QuotaExhaustedError)
    assert error.reason.metadata == {
        "openrouter": {"errorCode": 429, "errorType": "insufficient_quota", "requestId": "req-1"}
    }


def test_config_has_every_chat_request_option():
    """``Config`` is Effect's ``Partial<Omit<ChatRequest, "messages" |
    "response_format" | "tools" | "tool_choice" | "stream" |
    "stream_options">>`` plus ``strict_json_schema``: a hand-written copy of
    the generated request, so this pins it to the generated keys."""
    omitted = {"messages", "response_format", "tools", "tool_choice", "stream", "stream_options"}
    chat_request = set(GT.ChatRequest.__annotations__) - omitted
    config = set(language_model.ConfigService.__annotations__)
    assert config == chat_request | {"strict_json_schema"}
    assert language_model.ConfigService.__required_keys__ == frozenset()


@pytest.mark.parametrize(
    ("api_url", "expected"),
    [
        (
            "https://proxy/v1/",
            ["https://proxy/v1/chat/completions", "https://proxy/alpha/decisions"],
        ),
        (
            "https://proxy/api",
            ["https://proxy/api/chat/completions", "https://proxy/api/alpha/decisions"],
        ),
    ],
)
@testing.effect
def test_api_url(api_url: str, expected: list[str]):
    """Decisions drop a trailing ``/v1`` (or ``/v1/``) of ``api_url``."""
    http = MockHttp(lambda request: fx.succeed(json_response(request, {}, status=500)))
    yield from _both_calls(api_url, http)
    assert [request.url for request in http.requests] == expected


def _both_calls(api_url: str, http: MockHttp) -> fx.Effect[Any, Any, Any]:
    sent = client.OpenRouterClient().flat_map(
        lambda c: fx.all(
            c.create_chat_completion({"messages": []}).flip(),
            c.create_decisions({"model": "m", "state": "s", "questions": {}}).flip(),
        )
    )
    return sent.pipe(fx.provide(client.layer(api_url=api_url))).pipe(fx.provide(http.layer))


@testing.effect
def test_empty_api_url_is_kept():
    """``api_url`` falls back with JavaScript's ``??``: an empty URL is kept,
    so the bare paths fail as invalid URLs (as under Node's fetch)."""
    http = MockHttp(lambda request: fx.succeed(json_response(request, {})))
    errors = yield from _both_calls("", http)
    reasons = [error.reason for error in errors]
    assert all(isinstance(r, E.NetworkError) and r.reason == "InvalidUrlError" for r in reasons)
    assert [r.request["url"] for r in reasons if isinstance(r, E.NetworkError)] == [
        "/chat/completions",
        "/alpha/decisions",
    ]
