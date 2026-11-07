"""Ports of Effect's ``packages/ai/openai-compat/test/OpenAiClient.test.ts``
and ``openai-compat/test/OpenAiTelemetry.test.ts``. Each docstring is the Effect test title
(with its ``describe``). Responses are recorded JSON or Server-Sent Events
answered by a mocked ``HttpClient``."""

from __future__ import annotations

# pyright: reportUnknownVariableType=false, reportUnknownArgumentType=false
# pyright: reportUnknownMemberType=false, reportUnknownLambdaType=false
import json
from typing import Any

import pyfect as fx
from pyfect import testing
from pyfect.ai import _openai_errors as OE
from pyfect.ai import ai_error as E
from pyfect.ai.openai_compat import client, telemetry
from pyfect.redacted import make as redact
from pyfect.tracer import NativeSpan, current_span

from ._ai_http import MockHttp, body_json, mock_json, mock_raw_sse, mock_sse

_URL = "https://compat.example.test/v1"
_HELLO: dict[str, Any] = {
    "model": "gpt-4o-mini",
    "messages": [{"role": "user", "content": "hello"}],
}


def completion(**overrides: Any) -> dict[str, Any]:
    return {
        "id": "chatcmpl_test_1",
        "object": "chat.completion",
        "model": "gpt-4o-mini",
        "created": 1,
        "choices": [
            {
                "index": 0,
                "finish_reason": "stop",
                "message": {"role": "assistant", "content": "Hello"},
            }
        ],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        **overrides,
    }


def _with_client(mock: MockHttp, use: Any) -> fx.Effect[Any, Any, Any]:
    layer = client.layer(
        api_key=redact("sk-test-key"),
        api_url=_URL,
        organization_id=redact("org_123"),
        project_id=redact("proj_456"),
    )
    return client.OpenAiClient().flat_map(use).pipe(fx.provide(layer)).pipe(fx.provide(mock.layer))


def _stream(mock: MockHttp) -> fx.Effect[list[Any], Any, Any]:
    return _with_client(
        mock,
        lambda c: c.create_response_stream(_HELLO).flat_map(lambda sent: sent[1].run_collect()),
    )


def _error(mock: MockHttp) -> fx.Effect[Any, Any, Any]:
    return _with_client(mock, lambda c: c.create_response(_HELLO).flip())


def _chunk(id: str, **fields: Any) -> dict[str, Any]:
    return {
        "id": id,
        "object": "chat.completion.chunk",
        "model": "gpt-4o-mini",
        "created": 1,
        "choices": [{"index": 0, "delta": {"content": "Hello"}, "finish_reason": None}],
        **fields,
    }


# request behavior ----------------------------------------------------------------------


@testing.effect
def test_auth_headers():
    """request behavior / sets auth and OpenAI headers on /chat/completions requests"""
    mock = mock_json(completion())
    yield from _with_client(mock, lambda c: c.create_response(_HELLO))
    (request,) = mock.requests
    assert request.url.endswith("/chat/completions")
    assert request.url.startswith(_URL)
    assert request.headers["authorization"] == "Bearer sk-test-key"
    assert request.headers["openai-organization"] == "org_123"
    assert request.headers["openai-project"] == "proj_456"
    body = body_json(request)
    assert body["messages"][0] == {"role": "user", "content": "hello"}


@testing.effect
def test_custom_properties():
    """request behavior / passes custom chat-completions request properties through"""
    mock = mock_json(completion())
    yield from _with_client(
        mock, lambda c: c.create_response({**_HELLO, "provider_feature": {"enabled": True}})
    )
    assert mock.bodies[0]["provider_feature"] == {"enabled": True}


@testing.effect
def test_embeddings_path():
    """request behavior / uses /embeddings path and decodes permissive embedding payloads"""
    mock = mock_json(
        {
            "data": [
                {
                    "embedding": "YmFzZTY0LWRhdGE=",
                    "index": 0,
                    "object": "embedding",
                    "vendor_payload": {"future_field": True},
                }
            ],
            "model": "my-custom-embedding-model",
            "object": "list",
            "usage": {"prompt_tokens": 5, "total_tokens": 5},
            "unknown_top_level": True,
        }
    )
    embedding = yield from _with_client(
        mock,
        lambda c: c.create_embedding({"model": "my-custom-embedding-model", "input": "embed this"}),
    )
    assert mock.requests[0].url.endswith("/embeddings")
    assert embedding["model"] == "my-custom-embedding-model"
    assert embedding["data"][0]["index"] == 0
    assert isinstance(embedding["data"][0]["embedding"], str)


@testing.effect
def test_stream_true():
    """request behavior / sets stream=true for createResponseStream and returns chat chunks"""
    usage = {
        "prompt_tokens": 4,
        "completion_tokens": 2,
        "total_tokens": 6,
        "prompt_tokens_details": {"cached_tokens": 1},
        "completion_tokens_details": {"reasoning_tokens": 1},
    }
    mock = mock_sse(
        [
            _chunk("chatcmpl_test_1", future_provider_field={"accepted": True}),
            _chunk(
                "chatcmpl_test_1",
                usage=usage,
                choices=[{"index": 0, "delta": {}, "finish_reason": "stop"}],
            ),
            "[DONE]",
        ]
    )
    events = yield from _stream(mock)
    body = mock.bodies[0]
    assert body["stream"] is True
    assert body["stream_options"]["include_usage"] is True
    assert mock.requests[0].url.endswith("/chat/completions")
    assert events[0]["id"] == "chatcmpl_test_1"
    assert events[1]["id"] == "chatcmpl_test_1"
    assert events[2] == "[DONE]"


@testing.effect
def test_schema_mismatched_chunks():
    """request behavior / surfaces schema-mismatched chat chunks and continues streaming"""
    unknown = {
        "type": "provider.chat.completion.delta",
        "provider_payload": {"content": "provider-specific"},
    }
    events = yield from _stream(mock_sse([unknown, _chunk("chatcmpl_test_2"), "[DONE]"]))
    assert events[0] == client.UnknownEvent(unknown)
    assert events[1]["id"] == "chatcmpl_test_2"
    assert events[2] == "[DONE]"


@testing.effect
def test_invalid_json_dropped():
    """request behavior / drops invalid JSON and streams valid events until [DONE]"""
    body = "".join(
        [
            "data: {invalid-json\n\n",
            f"data: {json.dumps(_chunk('chatcmpl_test_3'))}\n\n",
            "data: [DONE]\n\n",
            'data: {"ignored":"after completion"}\n\n',
        ]
    )
    events = yield from _stream(mock_raw_sse(body))
    assert len(events) == 2
    assert events[0]["id"] == "chatcmpl_test_3"
    assert events[1] == "[DONE]"


@testing.effect
def test_tool_choice_unchanged():
    """request behavior / passes chat-completions tool_choice payload through unchanged"""
    mock = mock_json(completion())
    choice = {"type": "function", "function": {"name": "TestTool"}}
    tools = [
        {
            "type": "function",
            "function": {
                "name": "TestTool",
                "parameters": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {"input": {"type": "string"}},
                    "required": ["input"],
                },
            },
        }
    ]
    yield from _with_client(
        mock, lambda c: c.create_response({**_HELLO, "tool_choice": choice, "tools": tools})
    )
    assert mock.bodies[0]["tool_choice"] == choice


@testing.effect
def test_tool_history():
    """request behavior / accepts assistant tool-call and tool result chat history"""
    arguments = {
        "call_id": "patch_call_1",
        "operation": {"type": "delete_file", "path": "src/obsolete.ts"},
    }
    messages = [
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "patch_call_1",
                    "type": "function",
                    "function": {"name": "apply_patch", "arguments": json.dumps(arguments)},
                }
            ],
        },
        {"role": "tool", "tool_call_id": "patch_call_1", "content": "deleted"},
    ]
    mock = mock_json(completion())
    yield from _with_client(
        mock, lambda c: c.create_response({"model": "gpt-4o-mini", "messages": messages})
    )
    body = mock.bodies[0]
    patch = next(m for m in body["messages"] if m["role"] == "assistant")
    assert patch["tool_calls"][0]["id"] == "patch_call_1"
    assert json.loads(patch["tool_calls"][0]["function"]["arguments"]) == arguments
    output = next(m for m in body["messages"] if m["role"] == "tool")
    assert output["content"] == "deleted"


_BAD_REQUEST = {"error": {"message": "Bad request", "type": "invalid_request_error", "code": None}}


@testing.effect
def test_redacts_headers():
    """request behavior / redacts OpenAI-specific headers in AI error context"""
    error = yield from _error(mock_json(_BAD_REQUEST, status=400))
    assert isinstance(error.reason, E.InvalidRequestError)
    assert error.reason.http is not None
    headers = error.reason.http["request"]["headers"]
    assert headers["authorization"] == "<redacted>"
    assert headers["openai-organization"] == "<redacted>"
    assert headers["openai-project"] == "<redacted>"


# error mapping -------------------------------------------------------------------------


@testing.effect
def test_400():
    """error mapping / maps 400 responses to InvalidRequestError"""
    error = yield from _error(mock_json(_BAD_REQUEST, status=400))
    assert isinstance(error, E.AiError)
    assert error.method == "createResponse"
    assert isinstance(error.reason, E.InvalidRequestError)


@testing.effect
def test_401():
    """error mapping / surfaces the provider message on 401 AuthenticationError"""
    body = {
        "error": {
            "message": "Incorrect API key provided",
            "type": "invalid_request_error",
            "code": "invalid_api_key",
        }
    }
    error = yield from _error(
        mock_json(body, status=401, headers={"x-request-id": "req_openai_compat"})
    )
    reason = error.reason
    assert isinstance(reason, E.AuthenticationError)
    assert reason.kind == "InvalidKey"
    assert reason.description == (
        f"Incorrect API key provided (POST {_URL}/chat/completions) "
        "[code: invalid_api_key] [requestId: req_openai_compat]"
    )
    assert "Incorrect API key provided" in reason.message


def test_fallback_body_truncated():
    """error mapping / preserves and truncates a fallback HTTP response"""
    body = "a" * 200 + "b"
    reason = OE.map_status_code_to_reason(
        OE.COMPAT,
        status=400,
        now=0,
        headers={},
        message=None,
        metadata={"errorCode": None, "errorType": None, "requestId": None},
        http={
            "request": {
                "method": "POST",
                "url": f"{_URL}/chat/completions",
                "urlParams": [],
                "headers": {},
            },
            "body": body,
        },
    )
    assert isinstance(reason, E.InvalidRequestError)
    assert reason.description == (
        f"HTTP 400 (POST {_URL}/chat/completions) Response: {'a' * 200}..."
    )


@testing.effect
def test_403():
    """error mapping / surfaces the provider message on 403 AuthenticationError"""
    message = "Country, region, or territory not supported"
    body = {"error": {"message": message, "type": "permission_error", "code": None}}
    error = yield from _error(mock_json(body, status=403))
    reason = error.reason
    assert isinstance(reason, E.AuthenticationError)
    assert reason.kind == "InsufficientPermissions"
    assert message in (reason.description or "")
    assert message in reason.message


@testing.effect
def test_quota():
    """error mapping / maps insufficient quota errors to QuotaExhaustedError"""
    body = {
        "error": {
            "message": "You exceeded your current quota",
            "type": "insufficient_quota",
            "code": "insufficient_quota",
        }
    }
    error = yield from _error(mock_json(body, status=429))
    assert error.method == "createResponse"
    assert isinstance(error.reason, E.QuotaExhaustedError)


# OpenAiTelemetry -----------------------------------------------------------------------


@testing.effect
def test_telemetry_attribute_keys():
    """OpenAiTelemetry / writes current OpenAI GenAI attribute keys"""

    def body() -> Any:
        span = yield from current_span()
        telemetry.add_gen_ai_annotations(
            span,
            {
                "provider": {"name": "openai"},
                "openai": {
                    "request": {"service_tier": "auto"},
                    "response": {"service_tier": "default", "system_fingerprint": "fp_1"},
                },
            },
        )
        assert isinstance(span, NativeSpan)
        assert span.attributes == {
            "gen_ai.provider.name": "openai",
            "openai.request.service_tier": "auto",
            "openai.response.service_tier": "default",
            "openai.response.system_fingerprint": "fp_1",
        }

    yield from fx.gen(body).with_span("test")
