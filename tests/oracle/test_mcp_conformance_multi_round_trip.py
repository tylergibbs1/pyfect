"""Ports of Effect's multi round-trip titles (McpConformance/MultiRoundTripTest.ts,
for both modes as LayerHttpRequestScoped.test.ts runs it), the "Multi round-trip
request capabilities" of v2026_07_28.test.ts and the two of
ProtocolAdapters.test.ts.

Omitted: none.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

import pyfect as fx
from pyfect import testing
from pyfect.ai import mcp_protocol as P
from pyfect.ai import mcp_schema as MS
from pyfect.ai import mcp_server as M
from pyfect.ai._mcp.core import PromptEntry, ResourceEntry, ToolEntry
from pyfect.context import Context

from ._mcp_features import (
    APPROVAL_REQUEST,
    MRTR_INVALID_STATE_TOOL,
    MRTR_PROMPT,
    MRTR_REQUEST_STATE,
    MRTR_SAMPLING_TOOL_CHOICE_TOOL,
    MRTR_SAMPLING_TOOLS_TOOL,
    MRTR_STATE_ONLY_TOOL,
    MRTR_TOOL,
    SAMPLE_REQUEST,
    USER_CONTEXT_REQUEST,
    features_conformance,
)
from ._mcp_http import (
    Conformance,
    Json,
    http_harness,
    initialize_session,
    read_message,
    server_layer,
)

MODERN = P.v2026_07_28
MODES = ["server", "request"]

_INPUT_RESPONSES: Json = {
    "approval": {"action": "accept", "content": {"approved": True}},
    "sample": {
        "role": "assistant",
        "content": {"type": "text", "text": "Suggested title", "_meta": {}},
        "model": "fixture-model",
        "_meta": {},
    },
    "roots": {"roots": [{"uri": "file:///workspace"}]},
}


def _call(id: object, name: str, **params: Any) -> Json:
    return {
        "jsonrpc": "2.0",
        "id": id,
        "method": "tools/call",
        "params": {"name": name, "arguments": {}, **params},
    }


def _get_prompt(id: object, **params: Any) -> Json:
    return {
        "jsonrpc": "2.0",
        "id": id,
        "method": "prompts/get",
        "params": {"name": MRTR_PROMPT, "arguments": {}, **params},
    }


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("include_context", ["thisServer", "allServers"])
@testing.effect
def test_should_require_context_capability_when_sampling_requests_include_server_context(
    mode: Any, include_context: str
):
    """Mcp Conformance / Multi round-trip requests / should require context capability when sampling requests include server context"""  # noqa: E501
    sample: Any = {
        "method": "sampling/createMessage",
        "params": {
            "messages": [
                {"role": "user", "content": {"type": "text", "text": "Summarize context"}}
            ],
            "includeContext": include_context,
            "maxTokens": 20,
        },
    }
    outcome: Any = MS.InputRequired(input_requests={"sample": sample})
    entry = ToolEntry(
        {"name": "Context", "inputSchema": {"type": "object"}},
        Context.empty(),
        lambda _: fx.succeed(outcome),
    )
    registration = M.McpServer().flat_map(lambda server: server.add_tool(entry))
    harness = yield from http_harness(
        server_layer("SamplingContext", (MODERN,), registration, mode=mode)
    )
    for supported in (False, True):
        response = yield from harness.post(
            _call(
                "supported" if supported else "unsupported",
                "Context",
                _meta={
                    "io.modelcontextprotocol/protocolVersion": MODERN.protocol_version,
                    "io.modelcontextprotocol/clientCapabilities": {
                        "sampling": {"context": {}} if supported else {}
                    },
                },
            ),
            {
                "Mcp-Protocol-Version": MODERN.protocol_version,
                "Mcp-Method": "tools/call",
                "Mcp-Name": "Context",
            },
        )
        message = yield from read_message(response)
        if supported:
            assert response.status == 200
            assert message["result"]["resultType"] == "input_required"
            assert message["result"]["inputRequests"] == {"sample": sample}
        else:
            assert response.status == 400
            assert message["error"]["code"] == -32021
            assert message["error"]["data"] == {
                "requiredCapabilities": {"sampling": {"context": {}}}
            }


@pytest.mark.parametrize("mode", MODES)
@testing.effect
def test_should_return_input_required_and_then_complete_when_prompts_get_is_retried_with_client_input(  # noqa: E501
    mode: Any,
):
    """Mcp Conformance / Multi round-trip requests / should return input_required and then complete when prompts/get is retried with client input"""  # noqa: E501
    test = yield from features_conformance(MODERN, mode)
    session = yield from test.initialize()
    first = yield from test.decode_result((yield from test.send(session, _get_prompt(30))))
    assert first["result"]["resultType"] == "input_required"
    assert first["result"]["inputRequests"]["userContext"] == USER_CONTEXT_REQUEST
    completed = yield from test.decode_result(
        (
            yield from test.send(
                session,
                _get_prompt(
                    31,
                    inputResponses={
                        "userContext": {"action": "accept", "content": {"context": "test context"}}
                    },
                ),
            )
        )
    )
    assert completed["result"]["resultType"] == "complete"
    assert completed["result"]["messages"] == [
        {"role": "user", "content": {"type": "text", "text": "Prompt completed"}}
    ]


@pytest.mark.parametrize("mode", MODES)
@testing.effect
def test_should_reject_prompt_input_requests_when_the_client_omits_their_required_capabilities(
    mode: Any,
):
    """Mcp Conformance / Multi round-trip requests / should reject prompt input requests when the client omits their required capabilities"""  # noqa: E501
    test = yield from features_conformance(MODERN, mode)
    session = yield from test.initialize()
    response = yield from test.send(session, _get_prompt(32), client_capabilities={})
    error = yield from test.decode_error(response)
    assert response.status == 400
    assert error["error"]["code"] == -32021
    assert error["error"]["data"] == {"requiredCapabilities": {"elicitation": {"form": {}}}}


@pytest.mark.parametrize("mode", MODES)
@testing.effect
def test_should_return_supported_keyed_input_requests_and_resume_when_matching_responses_are_supplied(  # noqa: E501
    mode: Any,
):
    """Mcp Conformance / Multi round-trip requests / should return supported keyed input requests and resume when matching responses are supplied"""  # noqa: E501
    test = yield from features_conformance(MODERN, mode)
    session = yield from test.initialize()
    first = yield from test.decode_result((yield from test.send(session, _call(1, MRTR_TOOL))))
    assert first["result"]["resultType"] == "input_required"
    assert first["result"]["requestState"] == MRTR_REQUEST_STATE
    assert first["result"]["inputRequests"] == {
        "approval": APPROVAL_REQUEST,
        "sample": SAMPLE_REQUEST,
        "roots": {"method": "roots/list"},
    }
    completed = yield from test.decode_result(
        (
            yield from test.send(
                session,
                _call(
                    3,
                    MRTR_TOOL,
                    inputResponses=_INPUT_RESPONSES,
                    requestState=first["result"]["requestState"],
                ),
            )
        )
    )
    assert completed["result"]["resultType"] == "complete"
    assert json.loads(completed["result"]["content"][0]["text"]) == {
        "approval": {"approved": True},
        "sample": _INPUT_RESPONSES["sample"],
        "roots": _INPUT_RESPONSES["roots"],
    }


@pytest.mark.parametrize("mode", MODES)
@testing.effect
def test_should_return_a_retry_state_without_requesting_client_input(mode: Any):
    """Mcp Conformance / Multi round-trip requests / should return a retry state without requesting client input"""  # noqa: E501
    test = yield from features_conformance(MODERN, mode)
    session = yield from test.initialize()
    message = yield from test.decode_result(
        (yield from test.send(session, _call(2, MRTR_STATE_ONLY_TOOL)))
    )
    assert message["result"]["resultType"] == "input_required"
    assert message["result"]["requestState"] == MRTR_REQUEST_STATE
    assert "inputRequests" not in message["result"]


@pytest.mark.parametrize("mode", MODES)
@testing.effect
def test_should_remain_input_required_when_continuation_keys_or_request_state_do_not_match(
    mode: Any,
):
    """Mcp Conformance / Multi round-trip requests / should remain input-required when continuation keys or request state do not match"""  # noqa: E501
    test = yield from features_conformance(MODERN, mode)
    session = yield from test.initialize()
    cases: list[Json] = [
        {
            "inputResponses": {"other": {"action": "accept", "content": {"approved": True}}},
            "requestState": MRTR_REQUEST_STATE,
        },
        {"inputResponses": _INPUT_RESPONSES, "requestState": f"{MRTR_REQUEST_STATE}:mismatch"},
    ]
    for index, continuation in enumerate(cases):
        message = yield from test.decode_result(
            (yield from test.send(session, _call(index + 10, MRTR_TOOL, **continuation)))
        )
        assert message["result"]["resultType"] == "input_required"
        assert message["result"]["requestState"] == MRTR_REQUEST_STATE


@pytest.mark.parametrize("mode", MODES)
@testing.effect
def test_should_reject_a_continuation_when_its_input_responses_or_request_state_are_malformed(
    mode: Any,
):
    """Mcp Conformance / Multi round-trip requests / should reject a continuation when its input responses or request state are malformed"""  # noqa: E501
    test = yield from features_conformance(MODERN, mode)
    session = yield from test.initialize()
    cases: list[Json] = [
        {"inputResponses": {"approval": "accepted"}, "requestState": MRTR_REQUEST_STATE},
        {"inputResponses": _INPUT_RESPONSES, "requestState": 42},
    ]
    for index, continuation in enumerate(cases):
        response = yield from test.send(session, _call(index + 20, MRTR_TOOL, **continuation))
        error = yield from test.decode_error(response)
        assert error["error"]["code"] == MS.INVALID_PARAMS_ERROR_CODE


# --- v2026_07_28.test.ts ---------------------------------------------------------------------


@testing.effect
def test_should_return_invalid_params_when_a_resumed_tool_rejects_its_request_state():
    """Multi round-trip request capabilities / should return InvalidParams when a resumed tool rejects its requestState"""  # noqa: E501
    test = yield from features_conformance(MODERN)
    session = yield from test.initialize()
    response = yield from test.send(
        session,
        _call(
            37,
            MRTR_INVALID_STATE_TOOL,
            inputResponses={"approval": {"action": "accept", "content": {"approved": True}}},
            requestState="tampered",
        ),
    )
    error = yield from test.decode_error(response)
    assert response.status == 200
    assert error["error"]["code"] == MS.INVALID_PARAMS_ERROR_CODE


@testing.effect
def test_should_reject_tool_enabled_sampling_when_the_client_omits_sampling_tools():
    """Multi round-trip request capabilities / should reject tool-enabled sampling when the client omits sampling.tools"""  # noqa: E501
    test = yield from features_conformance(MODERN)
    session = yield from test.initialize()
    for index, name in enumerate((MRTR_SAMPLING_TOOLS_TOOL, MRTR_SAMPLING_TOOL_CHOICE_TOOL)):
        response = yield from test.send(
            session, _call(index + 38, name), client_capabilities={"sampling": {}}
        )
        error = yield from test.decode_error(response)
        assert response.status == 400
        assert error["error"]["code"] == -32021
        assert error["error"]["data"] == {"requiredCapabilities": {"sampling": {"tools": {}}}}


@testing.effect
def test_should_treat_an_empty_elicitation_capability_as_form_support():
    """Multi round-trip request capabilities / should treat an empty elicitation capability as form support"""  # noqa: E501
    test = yield from features_conformance(MODERN)
    session = yield from test.initialize()
    response = yield from test.send(
        session,
        _call(39, MRTR_TOOL),
        client_capabilities={"elicitation": {}, "sampling": {}, "roots": {}},
    )
    message = yield from test.decode_result(response)
    assert message["result"]["resultType"] == "input_required"
    assert message["result"]["inputRequests"]["approval"] == APPROVAL_REQUEST


@testing.effect
def test_should_reject_input_requests_when_the_client_omits_their_required_capabilities():
    """Multi round-trip request capabilities / should reject input requests when the client omits their required capabilities"""  # noqa: E501
    test = yield from features_conformance(MODERN)
    session = yield from test.initialize()
    response = yield from test.send(session, _call(40, MRTR_TOOL), client_capabilities={})
    error = yield from test.decode_error(response)
    assert response.status == 400
    assert error["error"]["code"] == -32021
    assert error["error"]["data"] == {
        "requiredCapabilities": {"elicitation": {"form": {}}, "sampling": {}, "roots": {}}
    }


# --- ProtocolAdapters.test.ts ----------------------------------------------------------------


@testing.effect
def test_should_expose_continuation_input_to_modern_resource_and_prompt_handlers():
    """should expose continuation input to modern resource and prompt handlers"""
    continuation: Json = {
        "inputResponses": {"roots": {"roots": [{"uri": "file:///workspace"}]}},
        "requestState": "round-2",
    }

    def seen() -> fx.Effect[str, Any, Any]:
        def text(context: MS.RequestContext) -> str:
            return json.dumps(
                {
                    "inputResponses": context.input_responses,
                    "requestState": context.request_state,
                }
            )

        return MS.McpRequestContext().map(text)

    @fx.gen
    def register():
        server = yield from M.McpServer()
        yield from server.add_resource(
            ResourceEntry(
                {"uri": "file:///input-context.txt", "name": "input-context"},
                Context.empty(),
                seen().map(
                    lambda text: {"contents": [{"uri": "file:///input-context.txt", "text": text}]}
                ),
            )
        )
        yield from server.add_prompt(
            PromptEntry(
                {"name": "input-context"},
                Context.empty(),
                {},
                lambda _: seen().map(
                    lambda text: {
                        "messages": [{"role": "user", "content": {"type": "text", "text": text}}]
                    }
                ),
            )
        )

    harness = yield from http_harness(server_layer("Continuation", (MODERN,), register))
    meta: Json = {
        "io.modelcontextprotocol/protocolVersion": MODERN.protocol_version,
        "io.modelcontextprotocol/clientCapabilities": {},
    }
    resource = yield from harness.post(
        {
            "jsonrpc": "2.0",
            "id": 30,
            "method": "resources/read",
            "params": {"uri": "file:///input-context.txt", **continuation, "_meta": meta},
        },
        {
            "Mcp-Protocol-Version": MODERN.protocol_version,
            "Mcp-Method": "resources/read",
            "Mcp-Name": "file:///input-context.txt",
        },
    )
    message = yield from read_message(resource)
    assert json.loads(message["result"]["contents"][0]["text"]) == continuation
    prompt = yield from harness.post(
        {
            "jsonrpc": "2.0",
            "id": 31,
            "method": "prompts/get",
            "params": {"name": "input-context", **continuation, "_meta": meta},
        },
        {
            "Mcp-Protocol-Version": MODERN.protocol_version,
            "Mcp-Method": "prompts/get",
            "Mcp-Name": "input-context",
        },
    )
    message = yield from read_message(prompt)
    assert json.loads(message["result"]["messages"][0]["content"]["text"]) == continuation


@testing.effect
def test_should_reject_client_input_when_the_selected_protocol_cannot_encode_it():
    """should reject client input when the selected protocol cannot encode it"""
    legacy = P.v2025_11_25
    outcome: Any = MS.InputRequired(input_requests={"roots": {"method": "roots/list"}})
    entry = ToolEntry(
        {"name": MRTR_TOOL, "inputSchema": {"type": "object"}},
        Context.empty(),
        lambda _: fx.succeed(outcome),
    )
    registration = M.McpServer().flat_map(lambda server: server.add_tool(entry))
    harness = yield from http_harness(server_layer("Legacy", (legacy,), registration))
    headers = yield from initialize_session(harness, legacy)
    response = yield from harness.post(_call(2, MRTR_TOOL), headers)
    message = yield from read_message(response)
    assert message["error"]["code"] == MS.INVALID_PARAMS_ERROR_CODE
    assert "Client input is not supported" in message["error"]["message"]


@pytest.mark.parametrize(
    "continuation",
    [
        {"requestState": "tampered"},
        {"inputResponses": {"approval": {"action": "accept"}}},
    ],
    ids=["state alone", "responses alone"],
)
@testing.effect
def test_either_half_of_a_continuation_keeps_a_refused_retry_a_protocol_error(continuation: Json):
    """Effect's ``continuation`` test is on either field."""
    test = yield from features_conformance(MODERN)
    session = yield from test.initialize()
    response = yield from test.send(session, _call(1, MRTR_INVALID_STATE_TOOL, **continuation))
    error = yield from test.decode_error(response)
    assert error["error"]["code"] == MS.INVALID_PARAMS_ERROR_CODE


@testing.effect
def test_a_refused_first_call_is_a_tool_error_result():
    """Without a continuation, a tool's ``InvalidParams`` is reported as its result."""
    test = yield from features_conformance(MODERN)
    session = yield from test.initialize()
    response = yield from test.send(session, _call(1, MRTR_INVALID_STATE_TOOL))
    message = yield from read_message(response)
    assert "error" not in message


@testing.effect
def test_a_prompt_asking_for_input_on_a_session_revision_is_an_internal_error():
    """Effect's ``UnsupportedByProtocol`` for "prompt input requirements" has no
    protocol error of its own."""
    legacy = P.v2025_11_25
    outcome: Any = MS.InputRequired(input_requests={"roots": {"method": "roots/list"}})
    entry = PromptEntry({"name": MRTR_PROMPT}, Context.empty(), {}, lambda _: fx.succeed(outcome))
    registration = M.McpServer().flat_map(lambda server: server.add_prompt(entry))
    harness = yield from http_harness(server_layer("Legacy", (legacy,), registration))
    headers = yield from initialize_session(harness, legacy)
    message = yield from read_message((yield from harness.post(_get_prompt(2), headers)))
    assert message["error"] == {"code": -32603, "message": "MCP feature handler failed"}


@testing.effect
def test_a_url_elicitation_requires_the_url_capability():
    """The capability named is the one the request's mode needs."""
    request: Any = {
        "method": "elicitation/create",
        "params": {"mode": "url", "message": "m", "url": "https://x"},
    }
    outcome: Any = MS.InputRequired(input_requests={"go": request})
    entry = ToolEntry(
        {"name": "Go", "inputSchema": {"type": "object"}},
        Context.empty(),
        lambda _: fx.succeed(outcome),
    )
    registration = M.McpServer().flat_map(lambda server: server.add_tool(entry))
    harness = yield from http_harness(server_layer("Url", (MODERN,), registration))
    test = Conformance(MODERN, harness)
    session = yield from test.initialize()
    response = yield from test.send(
        session, _call(1, "Go"), client_capabilities={"elicitation": {"form": {}}}
    )
    error = yield from test.decode_error(response)
    assert error["error"]["data"]["requiredCapabilities"] == {"elicitation": {"url": {}}}
