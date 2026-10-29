"""Ports of Effect's ``test/ai/Response.test.ts``.

Each test's docstring is the Effect test title (with its ``describe``).
``Response.AllParts(toolkit)`` is ``all_parts(toolkit)``,
``Response.makePart("tool-result", ...)`` is ``tool_result_part(...)`` and
``JSON.parse(JSON.stringify(x))`` is a ``json`` round trip. A handler is
``tool.handler(fn)`` given to ``toolkit.to_layer``.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any, Literal, TypedDict

import pytest

import pyfect as fx
from pyfect import schema as S
from pyfect import testing
from pyfect.ai import ai_error as E
from pyfect.ai import response as R
from pyfect.ai import tool as T
from pyfect.ai import toolkit as K


def _json(value: object) -> Any:
    return json.loads(json.dumps(value))


class Denied(TypedDict):
    type: Literal["execution-denied"]
    reason: str
    detail: str


_FAILURE = {"type": "execution-denied", "reason": "r", "detail": "IMPORTANT"}


def _handle(
    toolkit: K.AnyToolkit, handler: T.Handler[Any], name: str
) -> fx.Effect[Sequence[K.HandlerResult], Any, Any]:
    return (
        toolkit.flat_map(lambda kit: kit.handle(name, {}))
        .flat_map(lambda stream: stream.run_collect())
        .pipe(fx.provide(toolkit.to_layer(handler)))
    )


@pytest.mark.parametrize(
    "failure_schema",
    [
        pytest.param(S.Struct(Denied), id="preserves user failure fields with the struct schema"),
        pytest.param(S.Unknown, id="preserves user failure fields with the unknown schema"),
        pytest.param(
            S.Record(S.String, S.Unknown), id="preserves user failure fields with the record schema"
        ),
    ],
)
@testing.effect
def test_preserves_user_failure_fields(failure_schema: S.Top):
    """preserves user failure fields with the <name> schema"""
    tool = T.make("UserFailure", success=S.Finite, failure=failure_schema, failure_mode="return")
    toolkit = K.make(tool)
    results = yield from _handle(toolkit, tool.handler(lambda _, __: fx.fail(_FAILURE)), tool.name)
    assert results == [K.HandlerResult(_FAILURE, _FAILURE, True, False, "handler")]

    schema = R.all_parts(toolkit)
    decoded = yield from S.decode_unknown_effect(schema)(
        {
            "type": "tool-result",
            "id": "tool-123",
            "name": tool.name,
            "isFailure": True,
            "result": _FAILURE,
        }
    )
    assert isinstance(decoded, R.ToolResultFailure)
    assert decoded.result == _FAILURE
    assert decoded.encoded_result == _FAILURE
    encoded = yield from S.encode_effect(schema)(decoded)
    assert encoded["type"] == "tool-result"
    assert encoded["result"] == _FAILURE


@testing.effect
def test_round_trips_returned_ai_error():
    """round trips a returned AiError through Toolkit and AllParts JSON with an unknown failure schema"""  # noqa: E501
    tool = T.make("FrameworkFailure", success=S.Finite, failure=S.Unknown, failure_mode="return")
    toolkit = K.make(tool)
    failure = E.AiError(module="Test", method="FrameworkFailure", reason=E.RateLimitError())
    results = yield from _handle(toolkit, tool.handler(lambda _, __: fx.fail(failure)), tool.name)
    encoded_failure = yield from S.encode_effect(E.AiError)(failure)
    assert results == [K.HandlerResult(failure, encoded_failure, True, False, "handler")]

    part = R.tool_result_part(
        id="tool-123",
        name=tool.name,
        is_failure=True,
        result=results[0].result,
        encoded_result=results[0].encoded_result,
    )
    schema = R.all_parts(toolkit)
    encoded = yield from S.encode_effect(schema)(part)
    decoded = yield from S.decode_unknown_effect(schema)(_json(encoded))
    assert isinstance(decoded, R.ToolResultFailure)
    result = decoded.result
    assert isinstance(result, E.AiError)
    assert isinstance(result.reason, E.RateLimitError)
    assert (result.module, result.method) == (failure.module, failure.method)
    assert decoded.encoded_result == encoded_failure


_PROVIDER_TOOL = T.provider_defined(
    id="test.provider_tool",
    custom_name="ProviderTool",
    provider_name="provider_tool",
    success=S.Unknown,
)()


@pytest.mark.parametrize(
    "result",
    [
        pytest.param(
            {"type": "execution-denied", "reason": "User declined"},
            id="round trips execution-denied through AllParts JSON",
        ),
        pytest.param(
            {
                "type": "execution-interrupted",
                "reason": "Tool call execution was interrupted because the response finished "
                'with reason "length"',
            },
            id="round trips execution-interrupted through AllParts JSON",
        ),
    ],
)
@testing.effect
def test_provider_defined_execution_failures(result: dict[str, str]):
    """provider-defined tool execution failures / round trips <type> through AllParts JSON"""
    schema = R.all_parts(K.make(_PROVIDER_TOOL))
    part = R.tool_result_part(
        id="tool-123",
        name=_PROVIDER_TOOL.name,
        is_failure=True,
        result=result,
        encoded_result=result,
    )
    encoded = yield from S.encode_unknown_effect(schema)(part)
    decoded = yield from S.decode_unknown_effect(schema)(_json(encoded))
    assert decoded == part


_OVERLAP = T.make(
    "ResultEncoding", success=S.Finite, failure=S.FiniteFromString, failure_mode="return"
)
_OVERLAP_SCHEMA = R.tool_result_part_schema(
    _OVERLAP.name, _OVERLAP.success_schema, _OVERLAP.failure_schema
)


def _overlap_part(is_failure: bool, encoded_result: object) -> Any:
    return R.tool_result_part(
        id="tool-123",
        name="ResultEncoding",
        is_failure=is_failure,
        result=404,
        encoded_result=encoded_result,
    )


@pytest.mark.parametrize(
    ("is_failure", "encoded_result"),
    [
        pytest.param(False, 404, id="encodes a success with the success schema"),
        pytest.param(True, "404", id="encodes a failure with the failure schema"),
    ],
)
@testing.effect
def test_encodes_branch(is_failure: bool, encoded_result: object):
    """tool results with overlapping success and failure types / encodes a <branch> with the <branch> schema"""  # noqa: E501
    encoded = yield from S.encode_effect(_OVERLAP_SCHEMA)(_overlap_part(is_failure, encoded_result))
    assert encoded == {
        "type": "tool-result",
        "id": "tool-123",
        "name": "ResultEncoding",
        "isFailure": is_failure,
        "result": encoded_result,
        "providerExecuted": False,
        "preliminary": False,
        "metadata": {},
    }


@pytest.mark.parametrize(
    ("is_failure", "wrong", "expected"),
    [
        pytest.param(
            False,
            "404",
            "Expected number",
            id="rejects an encodedResult from the other branch for a success",
        ),
        pytest.param(
            True,
            404,
            "Expected string",
            id="rejects an encodedResult from the other branch for a failure",
        ),
    ],
)
def test_rejects_other_branch(is_failure: bool, wrong: object, expected: str):
    """tool results with overlapping success and failure types / rejects an encodedResult from the other branch for a <branch>"""  # noqa: E501
    exit = S.encode_unknown_exit(_OVERLAP_SCHEMA)(_overlap_part(is_failure, wrong))
    assert isinstance(exit, fx.Failure)
    error = exit.cause.failures[0]
    assert isinstance(error, S.SchemaError)
    assert error.message == f'{expected}\n  at ["encodedResult"]'


@pytest.mark.parametrize(
    ("is_failure", "encoded_result"),
    [
        pytest.param(
            False, 404, id="preserves a success encodedResult through an AllParts JSON round trip"
        ),
        pytest.param(
            True, "404", id="preserves a failure encodedResult through an AllParts JSON round trip"
        ),
    ],
)
@testing.effect
def test_preserves_encoded_result(is_failure: bool, encoded_result: object):
    """tool results with overlapping success and failure types / preserves a <branch> encodedResult through an AllParts JSON round trip"""  # noqa: E501
    schema = R.all_parts(K.make(_OVERLAP))
    part = _overlap_part(is_failure, encoded_result)
    encoded = yield from S.encode_effect(schema)(part)
    decoded = yield from S.decode_unknown_effect(schema)(_json(encoded))
    assert decoded == part


_ANY_PARTS = [
    R.ToolCallPart(id="call-1", name="UnknownTool", params={"path": "a.ts", "options": [1, None]}),
    R.tool_result_part(
        id="call-1",
        name="UnknownTool",
        is_failure=False,
        result={"content": "hello"},
        encoded_result={"content": "hello"},
    ),
]


@pytest.mark.parametrize(
    "make_schema",
    [
        pytest.param(
            R.all_parts, id="AllParts round trips tool parts with any tool name through JSON"
        ),
        pytest.param(R.part, id="Part round trips tool parts with any tool name through JSON"),
        pytest.param(
            R.stream_part, id="StreamPart round trips tool parts with any tool name through JSON"
        ),
    ],
)
@testing.effect
def test_schemas_without_toolkit(make_schema: Any):
    """schemas without a toolkit / <name> round trips tool parts with any tool name through JSON"""
    schema = make_schema()
    for part in _ANY_PARTS:
        encoded = yield from S.encode_unknown_effect(schema)(part)
        decoded = yield from S.decode_unknown_effect(schema)(_json(encoded))
        assert decoded == part


@testing.effect
def test_decodes_response_metadata_with_omitted_fields():
    """decodes response metadata with omitted optional fields"""
    decoded = yield from S.decode_unknown_effect(R.ResponseMetadataPart)(
        {"type": "response-metadata"}
    )
    assert decoded == R.ResponseMetadataPart()


@testing.effect
def test_round_trips_response_metadata():
    """round trips response metadata with undefined optional fields through JSON"""
    part = R.ResponseMetadataPart(id=None, model_id=None, timestamp=None, request=None)
    encoded = yield from S.encode_effect(R.ResponseMetadataPart)(part)
    data = _json(encoded)
    decoded = yield from S.decode_unknown_effect(R.ResponseMetadataPart)(data)
    assert data == {"metadata": {}, "type": "response-metadata"}
    assert decoded == R.ResponseMetadataPart()


@testing.effect
def test_round_trips_http_request_details():
    """round trips HTTP request details with an undefined hash through JSON"""
    request: E.HttpRequestDetails = {
        "method": "POST",
        "url": "https://example.com/v1/responses",
        "urlParams": [],
        "headers": {},
    }
    encoded = yield from S.encode_unknown_effect(E.HTTP_REQUEST_DETAILS)(request)
    data = _json(encoded)
    decoded = yield from S.decode_unknown_effect(E.HTTP_REQUEST_DETAILS)(data)
    assert data == {
        "method": "POST",
        "url": "https://example.com/v1/responses",
        "urlParams": [],
        "headers": {},
    }
    assert decoded == {**data, "urlParams": ()}


@testing.effect
def test_round_trips_finish_part():
    """round trips a finish part with undefined optional fields through JSON"""
    part = R.FinishPart(reason="stop", usage=R.Usage(R.InputTokens(), R.OutputTokens()))
    encoded = yield from S.encode_effect(R.FinishPart)(part)
    data = _json(encoded)
    decoded = yield from S.decode_unknown_effect(R.FinishPart)(data)
    assert data == {
        "metadata": {},
        "type": "finish",
        "reason": "stop",
        "usage": {"inputTokens": {}, "outputTokens": {}},
    }
    assert decoded == R.FinishPart(reason="stop", usage=R.Usage())
