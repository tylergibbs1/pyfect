"""Ports of Effect's ``packages/ai/openrouter/test/OpenRouterClient.test.ts``.
Each docstring is the Effect test title (with its ``describe``). Responses
are recorded JSON answered by a mocked ``HttpClient``.

Effect's unserializable ``bigint`` state is a ``set`` here: neither
encodes as JSON."""

from __future__ import annotations

# pyright: reportUnknownVariableType=false, reportUnknownArgumentType=false
# pyright: reportUnknownMemberType=false, reportUnknownLambdaType=false
from collections.abc import Callable
from typing import Any

import pyfect as fx
from pyfect import testing
from pyfect.ai import ai_error as E
from pyfect.ai.openrouter import _errors, client
from pyfect.exit import Failure
from pyfect.redacted import make as redact
from pyfect.result import Ok

from ._ai_http import MockHttp, mock_json, stringify_error

_CHAT: client.ChatRequest = {
    "model": "openai/gpt-4o-mini",
    "messages": [{"role": "user", "content": "hello"}],
}


def _run(use: Callable[[client.Service], fx.Effect[Any, Any, Any]], mock: MockHttp) -> Any:
    layer = client.layer(api_key=redact("sk-test-key"))
    return (
        client.OpenRouterClient().flat_map(use).pipe(fx.provide(layer)).pipe(fx.provide(mock.layer))
    )


def _chat_error(mock: MockHttp) -> fx.Effect[E.AiError, Any, Any]:
    return _run(lambda c: c.create_chat_completion(_CHAT).flip(), mock)


@testing.effect
def test_unserializable_decision_state():
    """OpenRouterClient / rejects unserializable bigint decision state with a typed error before
    making an HTTP call"""
    mock = mock_json({})
    exit = yield from _run(
        lambda c: c.create_decisions(
            {
                "model": "test-model",
                "state": {"n": {1}},
                "questions": {
                    "urgent": {
                        "type": "noul",
                        "instructions": "Is this urgent?",
                        "criteria": {"false": "Not urgent", "true": "Urgent"},
                    }
                },
            }
        ).exit(),
        mock,
    )
    assert mock.requests == []
    assert isinstance(exit, Failure)
    assert not exit.cause.has_dies
    found = exit.cause.find_error()
    assert isinstance(found, Ok)
    error = found.value
    assert isinstance(error, E.AiError)
    assert error.module == "OpenRouterClient"
    assert error.method == "createDecisions"
    assert isinstance(error.reason, E.InvalidRequestError)


@testing.effect
def test_redacts_api_key():
    """OpenRouterClient / redacts the API key in AI error context"""
    mock = mock_json({"error": {"code": 400, "message": "Bad request"}}, status=400)
    error = yield from _chat_error(mock)
    assert isinstance(error.reason, E.InvalidRequestError)
    assert "/chat/completions" in mock.requests[0].url
    assert "sk-test-key" not in stringify_error(error)


@testing.effect
def test_401_message():
    """OpenRouterClient / surfaces the provider message on 401 AuthenticationError"""
    mock = mock_json(
        {"error": {"code": 401, "message": "No auth credentials found"}},
        status=401,
        headers={"x-request-id": "req_openrouter"},
    )
    error = yield from _chat_error(mock)
    assert isinstance(error.reason, E.AuthenticationError)
    assert error.reason.kind == "InvalidKey"
    assert error.reason.description == (
        "No auth credentials found (POST https://openrouter.ai/api/v1/chat/completions) "
        "[code: 401] [requestId: req_openrouter]"
    )
    assert "No auth credentials found" in error.reason.message


def test_fallback_body_truncated():
    """OpenRouterClient / preserves and truncates a fallback HTTP response"""
    body = "a" * 200 + "b"
    reason = _errors.map_status_code_to_reason(
        now=0,
        status=400,
        headers={},
        message=None,
        metadata={"errorCode": None, "errorType": None, "requestId": None},
        method="POST",
        url="https://openrouter.ai/api/v1/chat/completions",
        http={"body": body},
    )
    assert isinstance(reason, E.InvalidRequestError)
    assert reason.description == (
        f"HTTP 400 (POST https://openrouter.ai/api/v1/chat/completions) Response: {'a' * 200}..."
    )


@testing.effect
def test_403_message():
    """OpenRouterClient / surfaces the provider message on 403 AuthenticationError"""
    mock = mock_json(
        {"error": {"code": 403, "message": "Key does not have permission"}}, status=403
    )
    error = yield from _chat_error(mock)
    assert isinstance(error.reason, E.AuthenticationError)
    assert error.reason.kind == "InsufficientPermissions"
    assert "Key does not have permission" in (error.reason.description or "")
    assert "Key does not have permission" in error.reason.message
