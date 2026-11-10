"""Ports of Effect's ``packages/ai/anthropic/test/AnthropicClient.test.ts``.
Each docstring is the Effect test title. Responses are recorded JSON
answered by a mocked ``HttpClient``."""

from __future__ import annotations

# pyright: reportUnknownVariableType=false, reportUnknownArgumentType=false
# pyright: reportUnknownMemberType=false, reportUnknownLambdaType=false
from datetime import timedelta
from typing import Any

import pytest

import pyfect as fx
from pyfect import testing
from pyfect.ai import ai_error as E
from pyfect.ai.anthropic import _errors, client
from pyfect.redacted import make as redact

from ._ai_http import MockHttp, mock_json, stringify_error

_PAYLOAD: dict[str, Any] = {
    "model": "claude-sonnet-5-5",
    "max_tokens": 1,
    "messages": [{"role": "user", "content": "hello"}],
}


def _create_error(mock: MockHttp) -> Any:
    def run(service: client.Service) -> Any:
        return service.create_message(_PAYLOAD).flip()

    return (
        client.AnthropicClient()
        .flat_map(run)
        .pipe(fx.provide(client.layer(api_key=redact("sk-test-key"))))
        .pipe(fx.provide(mock.layer))
    )


def _envelope(kind: str, message: str) -> dict[str, Any]:
    return {"type": "error", "error": {"type": kind, "message": message}, "request_id": None}


@testing.effect
def test_gateway_400():
    """maps a gateway 400 without an Anthropic error envelope"""
    error = yield from _create_error(
        mock_json({"error": {"message": "gateway rejected request"}}, status=400)
    )
    reason = error.reason
    assert isinstance(reason, E.InvalidRequestError)
    assert "HTTP 400" in (reason.description or "")
    assert "gateway rejected request" in (reason.description or "")
    assert reason.http is not None
    assert reason.http.get("response", {}).get("status") == 400


@testing.effect
def test_gateway_429_retry_after():
    """maps a gateway 429 without an Anthropic error envelope and preserves retry-after"""
    error = yield from _create_error(
        mock_json(
            {"error": {"message": "gateway rate limit"}}, status=429, headers={"retry-after": "3"}
        )
    )
    reason = error.reason
    assert isinstance(reason, E.RateLimitError)
    assert reason.retry_after == timedelta(seconds=3)
    assert reason.http is not None
    assert reason.http.get("response", {}).get("status") == 429


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        ("-5", None),
        ("Infinity", None),
        ("Thu, 01 Jan 1970 00:00:30 GMT", timedelta(seconds=30)),
    ],
    ids=[
        "ignores a negative Retry-After",
        "ignores a non-finite Retry-After",
        "honors an HTTP-date Retry-After",
    ],
)
@testing.effect
def test_retry_after_header(header: str, expected: timedelta | None):
    """$name (ignores a negative / non-finite Retry-After, honors an HTTP-date Retry-After)"""
    error = yield from _create_error(
        mock_json(
            {"error": {"message": "gateway rate limit"}},
            status=429,
            headers={"retry-after": header},
        )
    )
    reason = error.reason
    assert isinstance(reason, E.RateLimitError)
    assert reason.retry_after == expected


@testing.effect
def test_envelope_429_retry_after():
    """maps a 429 Anthropic error envelope with a non-rate-limit type and preserves
    retry-after"""
    body = {**_envelope("api_error", "gateway message"), "request_id": "req-test"}
    error = yield from _create_error(mock_json(body, status=429, headers={"retry-after": "3"}))
    reason = error.reason
    assert isinstance(reason, E.RateLimitError)
    assert reason.retry_after == timedelta(seconds=3)
    assert reason.http is not None
    assert reason.http.get("response", {}).get("status") == 429


@testing.effect
def test_redacts_api_key():
    """redacts the API key in AI error context"""
    mock = mock_json(_envelope("invalid_request_error", "Bad request"), status=400)
    error = yield from _create_error(mock)
    assert isinstance(error.reason, E.InvalidRequestError)
    assert "/v1/messages" in mock.requests[0].url
    assert "sk-test-key" not in stringify_error(error)


@testing.effect
def test_401_message():
    """surfaces the provider message on 401 AuthenticationError"""
    body = {**_envelope("authentication_error", "invalid x-api-key"), "request_id": "req_anthropic"}
    error = yield from _create_error(mock_json(body, status=401))
    reason = error.reason
    assert isinstance(reason, E.AuthenticationError)
    assert reason.kind == "InvalidKey"
    assert reason.metadata["anthropic"] == {
        "errorType": "authentication_error",
        "requestId": "req_anthropic",
    }
    assert reason.description == (
        "invalid x-api-key (POST https://api.anthropic.com/v1/messages?beta=true) "
        "[type: authentication_error] [requestId: req_anthropic]"
    )
    assert "invalid x-api-key" in reason.message


def test_fallback_body_truncated():
    """preserves and truncates a fallback HTTP response"""
    body = "a" * 200 + "b"
    reason = _errors.map_status_code_to_reason(
        status=400,
        now=0,
        headers={},
        message=None,
        metadata={"errorType": None, "requestId": None},
        method="POST",
        url="https://api.anthropic.com/v1/messages?beta=true",
        http={"body": body},
    )
    assert isinstance(reason, E.InvalidRequestError)
    assert reason.description == (
        f"HTTP 400 (POST https://api.anthropic.com/v1/messages?beta=true) Response: {'a' * 200}..."
    )


@testing.effect
def test_403_message():
    """surfaces the provider message on 403 AuthenticationError"""
    body = _envelope("permission_error", "claude-sonnet-5-5 is not available for this account")
    error = yield from _create_error(mock_json(body, status=403))
    reason = error.reason
    assert isinstance(reason, E.AuthenticationError)
    assert reason.kind == "InsufficientPermissions"
    assert "not available for this account" in (reason.description or "")
    assert "not available for this account" in reason.message
