"""AI provider edges Effect's tests leave open. Each case was run under Node
against Effect's ``@effect/ai-openai-compat`` / ``@effect/ai-anthropic``
with a mocked ``HttpClient`` and pins what it printed."""

from __future__ import annotations

# pyright: reportUnknownVariableType=false, reportUnknownArgumentType=false
# pyright: reportUnknownMemberType=false, reportUnknownLambdaType=false
import json
from typing import Any, TypedDict, cast

import pytest
from oracle._ai_http import (
    MockHttp,
    json_response,
    mock_json,
    mock_raw_sse,
    mock_sse,
    text_response,
)

import pyfect as fx
from pyfect import schema as S
from pyfect import testing
from pyfect.ai import ai_error as E
from pyfect.ai import language_model as lm
from pyfect.ai import response as R
from pyfect.ai import tool as T
from pyfect.ai import toolkit as K
from pyfect.ai.anthropic import client as anthropic
from pyfect.ai.openai_compat import client as compat
from pyfect.ai.openai_compat import language_model as compat_lm
from pyfect.http.response import HttpClientResponse


def _compat_error(status: int, body: str) -> fx.Effect[E.AiError, Any, Any]:
    mock = MockHttp(
        lambda request: fx.succeed(
            text_response(request, body, status=status, content_type="application/json")
        )
    )
    return (
        compat.OpenAiClient()
        .flat_map(lambda c: c.create_response({"model": "m", "messages": []}).flip())
        .pipe(fx.provide(compat.layer()))
        .pipe(fx.provide(mock.layer))
    )


def _metadata(error: E.AiError) -> dict[str, Any]:
    reason: Any = error.reason
    return cast("dict[str, Any]", reason.metadata["openai-compat"])


@testing.effect
def test_compat_quota_error_type_substring():
    """A 429 whose error type contains ``exhausted`` (lower-cased) is a
    QuotaExhaustedError."""
    body = json.dumps({"error": {"message": "m", "type": "RESOURCE_EXHAUSTED"}})
    error = yield from _compat_error(429, body)
    assert isinstance(error.reason, E.QuotaExhaustedError)
    assert _metadata(error)["errorType"] == "resource_exhausted"


@testing.effect
def test_compat_server_error_keeps_empty_message():
    """An empty error message is the description; ``Server error`` is only
    for a missing one."""
    error = yield from _compat_error(500, json.dumps({"error": {"message": ""}}))
    assert isinstance(error.reason, E.InternalProviderError)
    assert error.reason.description == ""


@testing.effect
def test_compat_error_array_must_all_be_errors():
    """An array error body decodes only when every item is an error body."""
    body = json.dumps([{"error": {"message": "a", "type": "x"}}, {"nope": 1}])
    error = yield from _compat_error(429, body)
    assert isinstance(error.reason, E.RateLimitError)
    assert _metadata(error)["errorType"] is None


@testing.effect
def test_compat_error_empty_type_is_kept():
    """An empty error type is kept rather than replaced by ``status``."""
    body = json.dumps({"error": {"message": "a", "type": "", "status": "BAD"}})
    error = yield from _compat_error(400, body)
    assert isinstance(error.reason, E.InvalidRequestError)
    assert _metadata(error)["errorType"] == ""
    assert error.reason.description == "a (POST https://api.openai.com/v1/chat/completions)"


@testing.effect
def test_compat_error_body_is_response_text():
    """The error's body is the response text, even when empty."""
    error = yield from _compat_error(500, "")
    assert isinstance(error.reason, E.InternalProviderError)
    assert error.reason.description == "Server error"
    assert error.reason.http is not None
    assert error.reason.http.get("body") == ""


@testing.effect
def test_compat_stream_null_event_is_unknown():
    """A ``null`` SSE payload is an UnknownEvent; text that is not JSON is
    dropped."""
    mock = mock_raw_sse("data: null\n\ndata: nope\n\ndata: [DONE]\n\n")
    events = yield from (
        compat.OpenAiClient()
        .flat_map(
            lambda c: c.create_response_stream({"model": "m", "messages": []}).flat_map(
                lambda sent: sent[1].run_collect()
            )
        )
        .pipe(fx.provide(compat.layer()))
        .pipe(fx.provide(mock.layer))
    )
    assert list(events) == [compat.UnknownEvent(None), "[DONE]"]


@testing.effect
def test_compat_empty_prompt_sends_one_empty_user_message():
    """An empty prompt is sent as one empty user message."""
    completion = {
        "id": "c",
        "object": "chat.completion",
        "model": "m",
        "created": 1,
        "choices": [
            {"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": "x"}}
        ],
    }
    mock = mock_json(completion)
    yield from (
        lm.generate_text([])
        .pipe(fx.provide(compat_lm.layer(model="m")))
        .pipe(fx.provide(compat.layer()))
        .pipe(fx.provide(mock.layer))
    )
    assert mock.bodies == [{"model": "m", "messages": [{"role": "user", "content": ""}]}]


@pytest.mark.parametrize("status", [500, 529])
def test_anthropic_server_error_keeps_empty_message(status: int):
    """An empty Anthropic error message is the description of a 5xx."""

    def respond(request: Any) -> fx.Effect[HttpClientResponse, Any]:
        body = {
            "type": "error",
            "error": {"type": "api_error", "message": ""},
            "request_id": None,
        }
        return fx.succeed(json_response(request, body, status=status))

    program = (
        anthropic.AnthropicClient()
        .flat_map(
            lambda c: c.create_message({"model": "m", "max_tokens": 1, "messages": []}).flip()
        )
        .pipe(fx.provide(anthropic.layer()))
        .pipe(fx.provide(MockHttp(respond).layer))
    )
    error = fx.run_sync(program.or_die())
    assert isinstance(error.reason, E.InternalProviderError)
    assert error.reason.description == ""


class _Optional(TypedDict, total=False):
    x: str


def _chunk(**fields: Any) -> dict[str, Any]:
    return {"id": "c1", "object": "chat.completion.chunk", "model": "m", "created": 1, **fields}


def _call(index: int, id: str, name: str) -> dict[str, Any]:
    return {"index": index, "id": id, "function": {"name": name, "arguments": "{}"}}


@testing.effect
def test_compat_stream_ends_tool_calls_in_index_order():
    """Streamed tool calls end in the order of their indexes (Effect keeps
    them in a record keyed by index), and an empty tool call id is kept."""
    toolkit = K.make(*(T.make(name, parameters=S.Struct(_Optional)) for name in ("ta", "tb", "tc")))
    events: list[object] = [
        _chunk(
            choices=[
                {
                    "index": 0,
                    "delta": {"tool_calls": [_call(1, "b", "tb"), _call(0, "a", "ta")]},
                    "finish_reason": None,
                }
            ]
        ),
        _chunk(
            choices=[
                {
                    "index": 0,
                    "delta": {"tool_calls": [_call(2, "", "tc")]},
                    "finish_reason": "tool_calls",
                }
            ]
        ),
        "[DONE]",
    ]
    parts = yield from (
        lm.stream_text("hi", toolkit=toolkit, disable_tool_call_resolution=True)
        .run_collect()
        .pipe(fx.provide(compat_lm.layer(model="m")))
        .pipe(fx.provide(compat.layer()))
        .pipe(fx.provide(mock_sse(events).layer))
    )
    starts = [(p.id, p.name) for p in parts if isinstance(p, R.ToolParamsStartPart)]
    calls = [(p.id, p.name) for p in parts if isinstance(p, R.ToolCallPart)]
    assert starts == [("b", "tb"), ("a", "ta"), ("", "tc")]
    assert calls == [("a", "ta"), ("b", "tb"), ("", "tc")]
