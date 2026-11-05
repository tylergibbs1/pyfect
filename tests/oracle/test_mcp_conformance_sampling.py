"""Ports of Effect's MCP conformance sampling titles
(test/ai/McpServer/McpConformance/SamplingTest.ts) for each stateful revision,
as its per-revision files run them.

Effect's peer has a ``wireClient`` below the reverse client; pyfect's peer is
a real client of a session, so every title goes through the reverse client
(all of them advertise ``sampling``, which is what ``wireClient`` skips).

Omitted: none.
"""

from __future__ import annotations

import json
from typing import Any, cast

import pytest

import pyfect as fx
from pyfect import testing
from pyfect.ai import mcp_protocol as P
from pyfect.ai import mcp_schema as MS

from ._mcp import Json
from ._mcp_peer import Handler, Peer, peer, reverse_client

STATEFUL = [P.v2024_11_05, P.v2025_03_26, P.v2025_06_18, P.v2025_11_25]
METHOD = "sampling/createMessage"
TEXT_RESPONSE: Json = {
    "role": "assistant",
    "content": {"type": "text", "text": "sampled"},
    "model": "test-model",
    "stopReason": "endTurn",
}
REQUEST: Json = {
    "messages": [{"role": "user", "content": {"type": "text", "text": "sample"}}],
    "maxTokens": 64,
    "metadata": {},
}
REQUEST_WITH_OPTIONS: Json = {
    "messages": [
        {"role": "user", "content": {"type": "text", "text": "first"}},
        {"role": "assistant", "content": {"type": "text", "text": "second"}},
    ],
    "modelPreferences": {
        "hints": [{"name": "test-model"}],
        "costPriority": 0.2,
        "speedPriority": 0.4,
        "intelligencePriority": 0.8,
    },
    "systemPrompt": "System",
    "includeContext": "thisServer",
    "maxTokens": 64,
    "stopSequences": ["STOP"],
    "metadata": {"request": "metadata"},
}


def _id(protocol: P.AnyProtocolAdapter) -> str:
    return protocol.protocol_version


def _answers(result: Json) -> dict[str, Handler]:
    return {METHOD: lambda _: fx.succeed(result)}


def _create(made: Peer, request: Json) -> fx.Effect[fx.Exit[MS.CreateMessageResult, Any]]:
    params = cast("MS.CreateMessageParams", request)
    return made.run(reverse_client().flat_map(lambda client: client.create_message(params)))


def _result_of(exit_: fx.Exit[MS.CreateMessageResult, Any]) -> Json:
    assert isinstance(exit_, fx.exit.Success), exit_
    return cast("Json", exit_.value)


@pytest.mark.parametrize("protocol", STATEFUL, ids=_id)
@testing.effect
def test_must_send_sampling_requests_when_the_client_advertises_sampling(
    protocol: P.AnyProtocolAdapter,
):
    """Mcp Conformance / Sampling / Capabilities / MUST send sampling requests when the client advertises sampling"""  # noqa: E501
    made = yield from peer(protocol, {"sampling": {}}, _answers(TEXT_RESPONSE))
    _result_of((yield from _create(made, REQUEST)))
    assert made.requests[0]["method"] == METHOD


@testing.effect
def test_should_reject_context_enabled_requests_without_sampling_context():
    """Mcp Conformance (2025-11-25) / Sampling / Capabilities / SHOULD reject context-enabled requests before sending without sampling.context"""  # noqa: E501
    made = yield from peer(P.v2025_11_25, {"sampling": {}})
    exit_ = yield from _create(made, {**REQUEST, "includeContext": "thisServer"})
    assert isinstance(exit_, fx.exit.Failure)
    assert made.requests == []


_TOOL_SHAPES: list[tuple[str, Json]] = [
    (
        "tools",
        {
            "messages": [{"role": "user", "content": {"type": "text", "text": "Weather?"}}],
            "tools": [{"name": "weather", "inputSchema": {"type": "object"}}],
            "maxTokens": 64,
        },
    ),
    (
        "toolChoice",
        {
            "messages": [{"role": "user", "content": {"type": "text", "text": "Weather?"}}],
            "toolChoice": {"mode": "required"},
            "maxTokens": 64,
        },
    ),
    (
        "tool_use content",
        {
            "messages": [
                {
                    "role": "assistant",
                    "content": {
                        "type": "tool_use",
                        "id": "call-1",
                        "name": "weather",
                        "input": {"city": "Zurich"},
                    },
                }
            ],
            "maxTokens": 64,
        },
    ),
    (
        "tool_result content",
        {
            "messages": [
                {
                    "role": "user",
                    "content": {
                        "type": "tool_result",
                        "toolUseId": "call-1",
                        "content": [{"type": "text", "text": "Sunny"}],
                    },
                }
            ],
            "maxTokens": 64,
        },
    ),
]


@testing.effect
def test_must_reject_every_tool_enabled_request_shape_without_sampling_tools():
    """Mcp Conformance (2025-11-25) / Sampling / Capabilities / MUST reject every tool-enabled request shape before sending without sampling.tools"""  # noqa: E501
    for name, request in _TOOL_SHAPES:
        made = yield from peer(P.v2025_11_25, {"sampling": {}})
        exit_ = yield from _create(made, request)
        assert isinstance(exit_, fx.exit.Failure), name
        assert made.requests == [], name


@testing.effect
def test_must_allow_text_only_content_arrays_without_sampling_tools():
    """Mcp Conformance (2025-11-25) / Sampling / Capabilities / MUST allow text-only content arrays without sampling.tools"""  # noqa: E501
    blocks = [{"type": "text", "text": "First"}, {"type": "text", "text": "Second"}]
    made = yield from peer(
        P.v2025_11_25,
        {"sampling": {}},
        _answers({"role": "assistant", "content": blocks, "model": "text-model"}),
    )
    exit_ = yield from _create(
        made, {"messages": [{"role": "user", "content": blocks}], "maxTokens": 64}
    )
    assert _result_of(exit_)["content"] == blocks
    assert len(made.requests) == 1


@testing.effect
def test_rejects_unexpected_tool_enabled_responses_when_sampling_tools_was_not_advertised():
    """Mcp Conformance (2025-11-25) / Sampling / Capabilities / SCENARIO rejects unexpected tool-enabled responses when sampling.tools was not advertised"""  # noqa: E501
    made = yield from peer(
        P.v2025_11_25,
        {"sampling": {}},
        _answers(
            {
                "role": "assistant",
                "content": {"type": "tool_use", "id": "call-1", "name": "weather", "input": {}},
                "model": "tool-model",
                "stopReason": "toolUse",
            }
        ),
    )
    exit_ = yield from _create(made, REQUEST)
    assert isinstance(exit_, fx.exit.Failure)
    assert len(made.requests) == 1


@pytest.mark.parametrize("protocol", STATEFUL, ids=_id)
@testing.effect
def test_must_preserve_message_order_and_sampling_request_options(protocol: P.AnyProtocolAdapter):
    """Mcp Conformance / Sampling / Creating Messages / MUST preserve message order and sampling request options"""  # noqa: E501
    sampling: Json = {"context": {}} if protocol is P.v2025_11_25 else {}
    made = yield from peer(protocol, {"sampling": sampling}, _answers(TEXT_RESPONSE))
    _result_of((yield from _create(made, REQUEST_WITH_OPTIONS)))
    payload = made.requests[0]["payload"]
    assert [(m["role"], m["content"]["text"]) for m in payload["messages"]] == [
        ("user", "first"),
        ("assistant", "second"),
    ]
    assert payload["systemPrompt"] == "System"
    assert payload["modelPreferences"] == REQUEST_WITH_OPTIONS["modelPreferences"]
    assert payload["maxTokens"] == 64
    assert payload["stopSequences"] == ["STOP"]
    assert payload["metadata"] == {"request": "metadata"}
    assert payload["includeContext"] == "thisServer"


@pytest.mark.parametrize("protocol", STATEFUL, ids=_id)
@testing.effect
def test_must_accept_and_decode_text_sampling_content(protocol: P.AnyProtocolAdapter):
    """Mcp Conformance / Sampling / Creating Messages / MUST accept and decode text sampling content"""  # noqa: E501
    made = yield from peer(protocol, {"sampling": {}}, _answers(TEXT_RESPONSE))
    result = _result_of((yield from _create(made, REQUEST)))
    assert result["role"] == "assistant"
    assert result["model"] == "test-model"
    assert result["stopReason"] == "endTurn"
    assert result["content"] == {"type": "text", "text": "sampled"}


@pytest.mark.parametrize("protocol", STATEFUL, ids=_id)
@testing.effect
def test_must_accept_image_sampling_content(protocol: P.AnyProtocolAdapter):
    """Mcp Conformance / Sampling / Creating Messages / MUST accept image sampling content"""
    image = {"type": "image", "data": "AQID", "mimeType": "image/png"}
    made = yield from peer(
        protocol,
        {"sampling": {}},
        _answers({"role": "assistant", "content": image, "model": "vision-model"}),
    )
    assert _result_of((yield from _create(made, REQUEST)))["content"] == image


@pytest.mark.parametrize("protocol", STATEFUL[1:], ids=_id)
@testing.effect
def test_must_accept_audio_sampling_content(protocol: P.AnyProtocolAdapter):
    """Mcp Conformance / Sampling / Creating Messages / MUST accept audio sampling content"""
    audio = {"type": "audio", "data": "BAUG", "mimeType": "audio/wav"}
    made = yield from peer(
        protocol,
        {"sampling": {}},
        _answers({"role": "assistant", "content": audio, "model": "audio-model"}),
    )
    assert _result_of((yield from _create(made, REQUEST)))["content"] == audio


@pytest.mark.parametrize("protocol", STATEFUL, ids=_id)
@testing.effect
def test_must_surface_sampling_errors_returned_by_the_client(protocol: P.AnyProtocolAdapter):
    """Mcp Conformance / Sampling / Creating Messages / MUST surface sampling errors returned by the client"""  # noqa: E501
    failing: dict[str, Handler] = {
        METHOD: lambda _: fx.fail({"code": MS.INTERNAL_ERROR_CODE, "message": "Sampling failed"})
    }
    made = yield from peer(protocol, {"sampling": {}}, failing)
    exit_ = yield from _create(made, REQUEST)
    assert isinstance(exit_, fx.exit.Failure)
    error: Any = exit_.cause.squash()
    assert isinstance(error, MS.McpReverseOperationError)
    assert error.cause == {"code": MS.INTERNAL_ERROR_CODE, "message": "Sampling failed"}


@testing.effect
def test_must_round_trip_tool_enabled_sampling_requests_and_results():
    """Mcp Conformance (2025-11-25) / Sampling / Creating Messages / MUST round-trip tool-enabled sampling requests and results"""  # noqa: E501
    response: Json = {
        "role": "assistant",
        "content": [
            {"type": "tool_use", "id": "call-2", "name": "weather", "input": {"city": "Geneva"}}
        ],
        "model": "tool-model",
        "stopReason": "toolUse",
    }
    request: Json = {
        "messages": [
            {
                "role": "assistant",
                "content": {
                    "type": "tool_use",
                    "id": "call-1",
                    "name": "weather",
                    "input": {"city": "Zurich"},
                },
            },
            {
                "role": "user",
                "content": {
                    "type": "tool_result",
                    "toolUseId": "call-1",
                    "content": [{"type": "text", "text": "Sunny"}],
                    "structuredContent": {"temperature": 24},
                },
            },
        ],
        "tools": [
            {
                "name": "weather",
                "description": "Get weather",
                "inputSchema": {
                    "type": "object",
                    "properties": {"city": {"type": "string"}},
                    "required": ["city"],
                },
            }
        ],
        "toolChoice": {"mode": "required"},
        "maxTokens": 64,
    }
    made = yield from peer(P.v2025_11_25, {"sampling": {"tools": {}}}, _answers(response))
    result = _result_of((yield from _create(made, request)))
    recorded = made.requests[0]
    assert recorded["method"] == METHOD
    assert recorded["payload"] == request
    assert json.loads(json.dumps(result)) == response


@pytest.mark.parametrize("protocol", STATEFUL[:3], ids=_id)
@testing.effect
def test_tool_use_requests_are_not_representable_before_2025_11_25(protocol: P.AnyProtocolAdapter):
    """Not an Effect title: before 2025-11-25 (Effect's strict ``transcode``)
    a request using tools has no wire shape, so nothing is sent."""
    made = yield from peer(protocol, {"sampling": {"tools": {}}})
    for name, request in _TOOL_SHAPES:
        exit_ = yield from _create(made, request)
        assert isinstance(exit_, fx.exit.Failure), name
        error = exit_.cause.squash()
        assert isinstance(error, MS.McpReverseOperationUnsupported), name
        assert error.reason == "Request is not representable by this protocol", name
    assert made.requests == []
