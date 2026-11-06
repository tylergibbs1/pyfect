"""Ports of Effect's ``test/ai/AiError.test.ts``.

Each test's docstring is the Effect test title (with its ``describe``).
Fields are snake_case (``tool_name``, ``retry_after``); their wire keys stay
camelCase. ``JSON.stringify(error)`` is the error's encoded form.

The ``should have _tag set correctly`` cases are one parametrized test, a
case per reason.
"""

from __future__ import annotations

# pyright: reportPrivateUsage=false
import json
import re
from datetime import timedelta
from typing import Any, Never, TypedDict

import pytest

import pyfect as fx
from pyfect import redacted
from pyfect import schema as S
from pyfect.ai import ai_error as E
from pyfect.http import error as http_error
from pyfect.http import request as http_request


class Named(TypedDict):
    name: str


def _schema_error(schema: S.Codec[object, object, Never, object], value: object) -> S.SchemaError:
    exit = fx.run_blocking_exit(S.decode_unknown_effect(schema)(value))
    assert isinstance(exit, fx.Failure)
    error = exit.cause.failures[0]
    assert isinstance(error, S.SchemaError)
    return error


def _roundtrip(schema: Any, value: object) -> Any:
    return S.decode_unknown_sync(schema)(S.encode_unknown_sync(schema)(value))


def test_network_error_preserves_redacted_query_params():
    """NetworkError / preserves redacted query params from request errors"""
    request = http_request.get("https://example.com").set_url_param(
        "remote", redacted.make("param-secret")
    )
    error = E.NetworkError.from_request_error(http_error.TransportError(request=request))
    output = json.dumps(S.encode_unknown_sync(E.NetworkError)(error), default=str)
    assert "remote" in output
    assert "param-secret" not in output


@pytest.mark.parametrize(
    ("reason", "retryable"),
    [
        pytest.param(E.RateLimitError(), True, id="RateLimitError / should be retryable"),
        pytest.param(
            E.QuotaExhaustedError(), False, id="QuotaExhaustedError / should not be retryable"
        ),
        pytest.param(
            E.AuthenticationError(kind="InvalidKey"),
            False,
            id="AuthenticationError / should not be retryable",
        ),
        pytest.param(
            E.ContentPolicyError(description="hate speech detected"),
            False,
            id="ContentPolicyError / should not be retryable",
        ),
        pytest.param(
            E.InvalidRequestError(parameter="temperature", constraint="must be between 0 and 2"),
            False,
            id="InvalidRequestError / should not be retryable",
        ),
        pytest.param(
            E.InternalProviderError(description="Server error"),
            True,
            id="InternalProviderError / should be retryable",
        ),
        pytest.param(
            E.InvalidOutputError(description="Invalid JSON structure"),
            True,
            id="InvalidOutputError / should be retryable",
        ),
        pytest.param(E.UnknownError(), False, id="UnknownError / should not be retryable"),
        pytest.param(
            E.ToolNotFoundError(tool_name="UnknownTool", available_tools=["GetWeather"]),
            True,
            id="ToolNotFoundError / should be retryable",
        ),
        pytest.param(
            E.ToolParameterValidationError(tool_name="GetWeather", description="Expected string"),
            True,
            id="ToolParameterValidationError / should be retryable",
        ),
        pytest.param(
            E.InvalidToolResultError(tool_name="GetWeather", description="missing"),
            False,
            id="InvalidToolResultError / should not be retryable",
        ),
        pytest.param(
            E.ToolResultEncodingError(
                tool_name="GetWeather", tool_result={"temp": 72}, description="Cannot encode"
            ),
            False,
            id="ToolResultEncodingError / should not be retryable",
        ),
        pytest.param(
            E.ToolConfigurationError(tool_name="OpenAiCodeInterpreter", description="Invalid"),
            False,
            id="ToolConfigurationError / should not be retryable",
        ),
        pytest.param(
            E.StructuredOutputError(description="Invalid JSON", response_text='{"invalid":}'),
            True,
            id="StructuredOutputError / should be retryable",
        ),
        pytest.param(
            E.UnsupportedSchemaError(description="Unions are not supported"),
            False,
            id="UnsupportedSchemaError / should not be retryable",
        ),
    ],
)
def test_retryable(reason: E.AiErrorReason, retryable: bool):
    """<reason> / should (not) be retryable"""
    assert reason.is_retryable is retryable


@pytest.mark.parametrize(
    "cls", E.REASONS, ids=lambda c: f"{c.__name__} / should have _tag set correctly"
)
def test_tag(cls: type[E.AiErrorReason]):
    """<reason> / should have _tag set correctly"""
    assert cls._tag == cls.__name__


@pytest.mark.parametrize(
    ("reason", "patterns"),
    [
        pytest.param(
            E.RateLimitError(retry_after=timedelta(seconds=60)),
            ["Retry after"],
            id="RateLimitError / should format message with retryAfter",
        ),
        pytest.param(
            E.QuotaExhaustedError(),
            ["Quota exhausted"],
            id="QuotaExhaustedError / should format message correctly",
        ),
        pytest.param(
            E.ContentPolicyError(description="Input contains prohibited content"),
            ["Content policy violation", "Input contains prohibited content"],
            id="ContentPolicyError / should format message with description",
        ),
        pytest.param(
            E.InvalidRequestError(
                parameter="temperature",
                constraint="must be between 0 and 2",
                description="Value 5 is invalid",
            ),
            ["parameter 'temperature'", "must be between 0 and 2", "Value 5 is invalid"],
            id="InvalidRequestError / should format message with parameter details",
        ),
        pytest.param(
            E.InternalProviderError(description="Unexpected server failure"),
            ["Internal provider error", "Unexpected server failure"],
            id="InternalProviderError / should format message with description",
        ),
        pytest.param(
            E.InvalidOutputError(description="Expected string but got number"),
            ["Invalid output", "Expected string but got number"],
            id="InvalidOutputError / should format message with description",
        ),
        pytest.param(
            E.ToolNotFoundError(tool_name="UnknownTool", available_tools=["GetWeather", "GetTime"]),
            ["Tool 'UnknownTool' not found", "Available tools: GetWeather, GetTime"],
            id="ToolNotFoundError / should format message with available tools",
        ),
        pytest.param(
            E.ToolNotFoundError(tool_name="UnknownTool", available_tools=[]),
            ["Available tools: none"],
            id="ToolNotFoundError / should format message with no available tools",
        ),
        pytest.param(
            E.ToolParameterValidationError(tool_name="GetWeather", description="Expected string"),
            ["Invalid parameters for tool 'GetWeather'"],
            id="ToolParameterValidationError / should format message with tool name",
        ),
        pytest.param(
            E.ToolParameterValidationError(
                tool_name="GetWeather", description="Expected string, got number"
            ),
            ["Expected string, got number"],
            id="ToolParameterValidationError / should format message with validation message",
        ),
        pytest.param(
            E.ToolParameterValidationError(
                tool_name="GetWeather", description='Expected finite number, got NaN at ["city"]'
            ),
            ["NaN"],
            id="ToolParameterValidationError / should construct when validated params contain "
            "non-JSON values",
        ),
        pytest.param(
            E.InvalidToolResultError(tool_name="GetWeather", description="missing required field"),
            ["Tool 'GetWeather' returned invalid result"],
            id="InvalidToolResultError / should format message with tool name",
        ),
        pytest.param(
            E.InvalidToolResultError(
                tool_name="GetWeather", description="missing 'temperature' field"
            ),
            ["missing 'temperature' field"],
            id="InvalidToolResultError / should format message with description",
        ),
        pytest.param(
            E.ToolResultEncodingError(
                tool_name="GetWeather", tool_result={"temp": 72}, description="Cannot encode"
            ),
            ["Failed to encode result for tool 'GetWeather'"],
            id="ToolResultEncodingError / should format message with tool name",
        ),
        pytest.param(
            E.ToolResultEncodingError(
                tool_name="GetWeather",
                tool_result={"circular": "ref"},
                description="Cannot encode circular reference",
            ),
            ["Cannot encode circular reference"],
            id="ToolResultEncodingError / should format message with validation message",
        ),
        pytest.param(
            E.ToolConfigurationError(
                tool_name="OpenAiCodeInterpreter", description="Invalid container ID format"
            ),
            ["Invalid configuration for tool 'OpenAiCodeInterpreter'"],
            id="ToolConfigurationError / should format message with tool name",
        ),
        pytest.param(
            E.ToolConfigurationError(
                tool_name="OpenAiWebSearch",
                description="search_context_size must be between 1 and 10",
            ),
            ["search_context_size must be between 1 and 10"],
            id="ToolConfigurationError / should format message with description",
        ),
        pytest.param(
            E.StructuredOutputError(
                description="Expected a valid JSON object", response_text='{"test":true}'
            ),
            ["Structured output validation failed", "Expected a valid JSON object"],
            id="StructuredOutputError / should format message with description",
        ),
        pytest.param(
            E.UnsupportedSchemaError(
                description="Unions are not supported in Anthropic structured output"
            ),
            ["Unsupported schema", "Unions are not supported in Anthropic structured output"],
            id="UnsupportedSchemaError / should format message with description",
        ),
    ],
)
def test_message(reason: E.AiErrorReason, patterns: list[str]):
    """<reason> / should format message ..."""
    for pattern in patterns:
        assert re.search(re.escape(pattern), reason.message), (pattern, reason.message)


def test_authentication_message_based_on_kind():
    """AuthenticationError / should format message based on kind"""
    for kind in ("InvalidKey", "ExpiredKey", "MissingKey", "InsufficientPermissions"):
        assert kind in E.AuthenticationError(kind=kind).message


def test_authentication_description_after_suggestion():
    """AuthenticationError / should render the description after the kind suggestion when present"""
    error = E.AuthenticationError(
        kind="InsufficientPermissions",
        description="anthropic.claude-sonnet-5 is not available for this account",
    )
    assert error.message == (
        "InsufficientPermissions: Your API key lacks required permissions. "
        "anthropic.claude-sonnet-5 is not available for this account"
    )


def test_authentication_message_without_description():
    """AuthenticationError / should render the message unchanged when description is absent"""
    error = E.AuthenticationError(kind="InsufficientPermissions")
    assert error.message == "InsufficientPermissions: Your API key lacks required permissions"
    assert error.description is None


def test_authentication_description_roundtrip():
    """AuthenticationError / should round-trip the description through the schema"""
    error = E.AuthenticationError(
        kind="ExpiredKey", description="The security token included in the request is expired"
    )
    decoded = _roundtrip(E.AuthenticationError, error)
    assert decoded.description == "The security token included in the request is expired"


def test_invalid_output_from_schema_error():
    """InvalidOutputError / should create from SchemaError"""
    error = E.InvalidOutputError.from_schema_error(_schema_error(S.Struct(Named), {"name": 123}))
    assert error._tag == "InvalidOutputError"
    assert isinstance(error.description, str)


class Choices(TypedDict):
    choices: tuple[str, ...]


_HTTP: E.HttpContext = {
    "request": {
        "method": "POST",
        "url": "https://api.example.com/v1/chat",
        "urlParams": [],
        "headers": {},
    },
    "response": {"status": 200, "headers": {"x-request-id": "req_123"}},
    "body": '{"choices":"none"}',
}


def test_invalid_response_from_schema_error():
    """InvalidResponseError / should create from SchemaError"""
    schema_error = _schema_error(S.Struct(Choices, choices=S.Array(S.String)), {"choices": "none"})
    error = E.InvalidResponseError.from_schema_error(schema_error)
    assert error.description == schema_error.message
    assert error.is_retryable is False
    assert E.make(module="Test", method="test", reason=error).is_retryable is False
    assert E.is_ai_error_reason(error)


def test_invalid_response_roundtrip():
    """InvalidResponseError / should preserve classification and HTTP context through schema round trip"""  # noqa: E501
    error = E.InvalidResponseError(description="Unexpected response envelope", http=_HTTP)
    decoded = _roundtrip(E.AI_ERROR_REASON, error)
    assert isinstance(decoded, E.InvalidResponseError)
    assert decoded.is_retryable is False
    assert decoded.http == {**_HTTP, "request": {**_HTTP["request"], "urlParams": ()}}


def test_unknown_message_with_description():
    """UnknownError / should format message with description"""
    error = E.UnknownError(description="Something unexpected happened")
    assert error.message == "Something unexpected happened"


def test_unknown_default_message():
    """UnknownError / should use default message without description"""
    assert E.UnknownError().message == "Unknown error"


def test_structured_output_from_schema_error():
    """StructuredOutputError / should create from SchemaError"""
    schema_error = _schema_error(S.Struct(Named), {"name": 123})
    error = E.StructuredOutputError.from_schema_error(schema_error, '{"name":123}')
    assert error._tag == "StructuredOutputError"
    assert isinstance(error.description, str)
    assert error.response_text == '{"name":123}'


def test_delegates_is_retryable():
    """delegation / should delegate isRetryable to reason"""
    retryable = E.AiError(module="OpenAI", method="completion", reason=E.RateLimitError())
    assert retryable.is_retryable
    other = E.AiError(
        module="OpenAI", method="completion", reason=E.AuthenticationError(kind="InvalidKey")
    )
    assert not other.is_retryable


def test_delegates_retry_after():
    """delegation / should delegate retryAfter to reason"""
    with_retry = E.AiError(
        module="OpenAI",
        method="completion",
        reason=E.RateLimitError(retry_after=timedelta(seconds=60)),
    )
    assert with_retry.retry_after is not None
    without = E.AiError(
        module="OpenAI", method="completion", reason=E.AuthenticationError(kind="InvalidKey")
    )
    assert without.retry_after is None


def test_message_with_module_and_method():
    """delegation / should format message with module, method, and reason"""
    error = E.AiError(module="OpenAI", method="completion", reason=E.RateLimitError())
    assert "OpenAI.completion:" in error.message
    assert "Rate limit exceeded" in error.message


def test_ai_error_tag():
    """delegation / should have _tag set correctly"""
    error = E.AiError(module="Test", method="test", reason=E.UnknownError())
    assert error._tag == "AiError"


def test_make():
    """constructors / make / should create AiError"""
    error = E.make(module="OpenAI", method="completion", reason=E.RateLimitError())
    assert error._tag == "AiError"
    assert (error.module, error.method, error.reason._tag) == (
        "OpenAI",
        "completion",
        "RateLimitError",
    )


@pytest.mark.parametrize(
    ("status", "tag"),
    [
        pytest.param(400, "InvalidRequestError", id="should map 400 to InvalidRequestError"),
        pytest.param(429, "RateLimitError", id="should map 429 to RateLimitError"),
        pytest.param(418, "UnknownError", id="should map unknown status to UnknownError"),
    ],
)
def test_reason_from_http_status(status: int, tag: str):
    """reasonFromHttpStatus / should map <status> to <reason>"""
    assert E.reason_from_http_status(status=status)._tag == tag


def test_reason_from_401():
    """reasonFromHttpStatus / should map 401 to AuthenticationError with InvalidKey"""
    reason = E.reason_from_http_status(status=401)
    assert isinstance(reason, E.AuthenticationError)
    assert reason.kind == "InvalidKey"


def test_reason_from_403():
    """reasonFromHttpStatus / should map 403 to AuthenticationError with InsufficientPermissions"""
    reason = E.reason_from_http_status(status=403)
    assert isinstance(reason, E.AuthenticationError)
    assert reason.kind == "InsufficientPermissions"


def test_reason_from_403_description():
    """reasonFromHttpStatus / should thread the description into 401/403 AuthenticationError"""
    description = "User is not authorized to perform: bedrock:InvokeModel"
    reason = E.reason_from_http_status(status=403, description=description)
    assert isinstance(reason, E.AuthenticationError)
    assert reason.description == description
    assert description in reason.message


def test_reason_from_5xx():
    """reasonFromHttpStatus / should map 5xx to InternalProviderError"""
    for status in (500, 502, 503):
        assert E.reason_from_http_status(status=status)._tag == "InternalProviderError"


def test_is_ai_error():
    """isAiError / should return true for AiError"""
    assert E.is_ai_error(E.AiError(module="Test", method="test", reason=E.UnknownError()))


def test_is_ai_error_false():
    """isAiError / should return false for non-AiError values"""
    for value in (Exception("regular error"), None, {"_tag": "FakeError"}):
        assert not E.is_ai_error(value)


def test_is_ai_error_false_for_reasons():
    """isAiError / should return false for reason types"""
    request: E.HttpRequestDetails = {
        "method": "GET",
        "url": "https://example.com",
        "urlParams": [],
        "headers": {},
    }
    assert not E.is_ai_error(E.NetworkError(reason="TransportError", request=request))


def test_provider_metadata_roundtrip():
    """ProviderMetadata / should encode and decode roundtrip"""
    metadata = {
        "name": "OpenAI",
        "errorCode": "rate_limit_exceeded",
        "errorType": "rate_limit",
        "requestId": "req_123abc",
    }
    assert _roundtrip(E.PROVIDER_METADATA, metadata) == metadata


def test_usage_info_roundtrip():
    """UsageInfo / should encode and decode roundtrip"""
    usage = {"promptTokens": 100, "completionTokens": 50, "totalTokens": 150}
    assert _roundtrip(E.USAGE_INFO, usage) == usage


def test_http_context_roundtrip():
    """HttpContext / should encode and decode roundtrip"""
    context = {
        "request": {
            "method": "POST",
            "url": "https://api.example.com/v1/chat",
            "urlParams": (("model", "gpt-4"),),
            "headers": {"Content-Type": "application/json"},
        },
        "response": {"status": 200, "headers": {"Content-Type": "application/json"}},
        "body": '{"result": "success"}',
    }
    assert _roundtrip(E.HTTP_CONTEXT, context) == context


def test_rate_limit_roundtrip():
    """schema roundtrip / RateLimitError roundtrip"""
    decoded = _roundtrip(E.RateLimitError, E.RateLimitError(retry_after=timedelta(seconds=60)))
    assert decoded._tag == "RateLimitError"
    assert decoded.retry_after is not None


def test_reason_union_roundtrip():
    """schema roundtrip / AiErrorReason union roundtrip"""
    assert _roundtrip(E.AI_ERROR_REASON, E.RateLimitError())._tag == "RateLimitError"
    auth = _roundtrip(E.AI_ERROR_REASON, E.AuthenticationError(kind="ExpiredKey"))
    assert auth._tag == "AuthenticationError"


def test_ai_error_roundtrip():
    """schema roundtrip / AiError roundtrip"""
    error = E.AiError(module="OpenAI", method="completion", reason=E.RateLimitError())
    decoded = _roundtrip(E.AiError, error)
    assert (decoded._tag, decoded.module, decoded.method, decoded.reason._tag) == (
        "AiError",
        "OpenAI",
        "completion",
        "RateLimitError",
    )


@pytest.mark.parametrize(
    "reason",
    [
        pytest.param(
            E.ToolNotFoundError(tool_name="UnknownTool", available_tools=("GetWeather", "GetTime")),
            id="ToolNotFoundError roundtrip",
        ),
        pytest.param(
            E.ToolParameterValidationError(tool_name="GetWeather", description="Expected string"),
            id="ToolParameterValidationError roundtrip",
        ),
        pytest.param(
            E.InvalidToolResultError(tool_name="GetWeather", description="missing required field"),
            id="InvalidToolResultError roundtrip",
        ),
        pytest.param(
            E.ToolResultEncodingError(
                tool_name="GetWeather", tool_result={"temp": 72}, description="Circular reference"
            ),
            id="ToolResultEncodingError roundtrip",
        ),
        pytest.param(
            E.ToolConfigurationError(
                tool_name="OpenAiCodeInterpreter", description="Invalid container ID format"
            ),
            id="ToolConfigurationError roundtrip",
        ),
        pytest.param(
            E.StructuredOutputError(
                description="Invalid JSON structure", response_text='{"invalid":}'
            ),
            id="StructuredOutputError roundtrip",
        ),
        pytest.param(
            E.UnsupportedSchemaError(description="Unions are not supported"),
            id="UnsupportedSchemaError roundtrip",
        ),
    ],
)
def test_reason_roundtrip(reason: E.AiErrorReason):
    """schema roundtrip / <reason> roundtrip"""
    decoded = _roundtrip(type(reason), reason)
    assert decoded == reason
    assert _roundtrip(E.AI_ERROR_REASON, reason) == reason


def test_reason_union_with_tool_errors_roundtrip():
    """schema roundtrip / AiErrorReason union with tool errors roundtrip"""
    decoded = _roundtrip(
        E.AI_ERROR_REASON, E.ToolNotFoundError(tool_name="Unknown", available_tools=("A", "B"))
    )
    assert decoded._tag == "ToolNotFoundError"
    param = E.ToolParameterValidationError(tool_name="Test", description="Invalid")
    assert _roundtrip(E.AI_ERROR_REASON, param)._tag == "ToolParameterValidationError"
