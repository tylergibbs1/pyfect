"""Ports of Effect's MCP conformance elicitation titles
(test/ai/McpServer/McpConformance/ElicitationTest.ts), for 2025-06-18 and
2025-11-25, the revisions whose files run the suite.

The HTTP titles read the tool call's event stream as the server writes it.
The others run on Effect's ``McpTestPeer``, ported as ``_mcp_peer.Peer``: a
client of a real session, whose reverse client the effect under test
uses. Effect's ``wireClient`` (the raw ``elicitation/create`` RPC) is that
reverse client here; it sends the request as given.

Omitted: none.
"""

from __future__ import annotations

import json
from typing import Any, TypedDict

import pytest

import pyfect as fx
from pyfect import schema as S
from pyfect import testing
from pyfect.ai import mcp_protocol as P
from pyfect.ai import mcp_schema as MS
from pyfect.ai import mcp_server as M
from pyfect.ai import tool as T
from pyfect.ai import toolkit as TK
from pyfect.exit import Failure

from ._mcp_http import HttpHarness, Json, http_harness, read_message, server_layer, sse_reader
from ._mcp_peer import Handler, peer, reverse_client

ELICITING = [P.v2025_06_18, P.v2025_11_25]
LATEST = P.v2025_11_25

REQUEST: Json = {
    "message": "Please provide your profile",
    "requestedSchema": {
        "type": "object",
        "properties": {
            "name": {"type": "string", "title": "Name"},
            "age": {"type": "integer", "minimum": 0},
            "subscribed": {"type": "boolean", "default": False},
        },
        "required": ["name"],
    },
}
URL_REQUEST: Json = {
    "mode": "url",
    "message": "Authorize access",
    "url": "https://example.com/authorize",
    "elicitationId": "authorization-1",
}


class Approval(TypedDict):
    approved: bool


class Name(TypedDict):
    name: str


class Profile(TypedDict):
    name: str
    age: float


class Value(TypedDict):
    value: str


class Nested(TypedDict):
    nested: Value


def _id(protocol: P.AnyProtocolAdapter) -> str:
    return protocol.protocol_version


def _answer(result: Json) -> dict[str, Handler]:
    return {"elicitation/create": lambda _request: fx.succeed(result)}


def _elicit(params: Any) -> fx.Effect[Any, Any, MS.McpServerClient]:
    return reverse_client().flat_map(lambda client: client.elicit(params))


def _run_elicitation(schema: S.Codec[Any, Any]) -> fx.Effect[Any, Any, MS.McpServerClient]:
    return M.elicit(message=REQUEST["message"], schema=schema)


# --- over HTTP ------------------------------------------------------------------------------

_APPROVE = T.make("Approve", success=S.Struct(Approval)).add_dependency(MS.McpServerClient)
_APPROVE_KIT = TK.make(_APPROVE)


def _approval_server(name: str, protocol: P.AnyProtocolAdapter) -> Any:
    approve = M.elicit(message="Approve this operation", schema=S.Struct(Approval))
    registration = M.register_toolkit(_APPROVE_KIT).pipe(
        fx.provide(_APPROVE_KIT.to_layer(_APPROVE.handler(lambda _, __: approve.or_die())))
    )
    return server_layer(name, (protocol,), registration)


def _initialize(harness: HttpHarness, protocol: P.AnyProtocolAdapter) -> fx.Effect[str]:
    @fx.gen
    def run():
        response = yield from harness.post(
            {
                "jsonrpc": "2.0",
                "id": "initialize",
                "method": "initialize",
                "params": {
                    "protocolVersion": protocol.protocol_version,
                    "capabilities": {"elicitation": {}},
                    "clientInfo": {"name": "approval-client", "version": "1.0.0"},
                },
            }
        )
        yield from read_message(response)
        session: str | None = response.headers.get("mcp-session-id")
        assert session is not None
        yield from harness.post(
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"Mcp-Session-Id": session, "Mcp-Protocol-Version": protocol.protocol_version},
        )
        return session

    return run


_CALL_APPROVE: Json = {
    "jsonrpc": "2.0",
    "id": "approval-tool",
    "method": "tools/call",
    "params": {"name": "Approve", "arguments": {}},
}


@pytest.mark.parametrize("protocol", ELICITING, ids=_id)
@testing.effect
def test_must_cancel_the_pending_http_elicitation_when_its_tool_call_is_cancelled(
    protocol: P.AnyProtocolAdapter,
):
    """Mcp Conformance / Elicitation / MUST cancel the pending HTTP elicitation when its tool call is cancelled"""  # noqa: E501
    harness = yield from http_harness(
        _approval_server("ElicitationCancellationConformance", protocol)
    )
    session = yield from _initialize(harness, protocol)
    headers = {"Mcp-Session-Id": session, "Mcp-Protocol-Version": protocol.protocol_version}
    response = yield from harness.post(_CALL_APPROVE, headers)
    stream = yield from sse_reader(response)
    reverse = yield from stream.take()
    assert reverse["method"] == "elicitation/create"
    assert "id" in reverse
    cancelled = yield from harness.post(
        {
            "jsonrpc": "2.0",
            "method": "notifications/cancelled",
            "params": {"requestId": "approval-tool"},
        },
        headers,
    )
    assert cancelled.status == 202
    remaining = yield from stream.drain().timeout("1 second")
    assert [message.get("method") for message in remaining] == ["notifications/cancelled"]
    assert remaining[0]["params"]["requestId"] == reverse["id"]
    assert not any(str(m.get("method", "")).startswith("@effect/rpc/") for m in remaining)


@pytest.mark.parametrize("response_session", ["missing", "unknown", "unrelated", "owner"])
@pytest.mark.parametrize("protocol", ELICITING, ids=_id)
@testing.effect
def test_must_preserve_elicitation_response_ownership(
    protocol: P.AnyProtocolAdapter, response_session: str
):
    """Mcp Conformance / Elicitation / MUST preserve elicitation response ownership with a ${responseSession} HTTP session"""  # noqa: E501
    harness = yield from http_harness(_approval_server("ElicitationSessionConformance", protocol))
    version = protocol.protocol_version
    owner = yield from _initialize(harness, protocol)
    other = (yield from _initialize(harness, protocol)) if response_session == "unrelated" else None
    response = yield from harness.post(
        _CALL_APPROVE, {"Mcp-Session-Id": owner, "Mcp-Protocol-Version": version}
    )
    stream = yield from sse_reader(response)
    reverse = yield from stream.take()
    assert reverse["method"] == "elicitation/create"
    assert "id" in reverse
    session = {"owner": owner, "unknown": "unknown", "unrelated": other, "missing": None}[
        response_session
    ]
    injected = yield from harness.post(
        {
            "jsonrpc": "2.0",
            "id": reverse["id"],
            "result": {"action": "accept", "content": {"approved": True}},
        },
        {} if session is None else {"Mcp-Session-Id": session, "Mcp-Protocol-Version": version},
    )
    if response_session != "owner":
        legitimate = yield from harness.post(
            {
                "jsonrpc": "2.0",
                "id": reverse["id"],
                "result": {"action": "accept", "content": {"approved": False}},
            },
            {"Mcp-Session-Id": owner, "Mcp-Protocol-Version": version},
        )
        assert legitimate.status == 202
    completed = yield from stream.take()
    assert completed["id"] == "approval-tool"
    assert completed["result"]["content"] == [
        {
            "type": "text",
            "text": json.dumps({"approved": response_session == "owner"}, separators=(",", ":")),
        }
    ]
    expected_status = {"missing": 400, "unknown": 404, "owner": 202}.get(response_session)
    if expected_status is not None:
        assert injected.status == expected_status


# --- Capabilities ---------------------------------------------------------------------------


@testing.effect
def test_must_treat_an_empty_elicitation_capability_as_form_support():
    """Mcp Conformance / Elicitation / Capabilities / MUST treat an empty elicitation capability as form support"""  # noqa: E501
    client = yield from peer(
        LATEST, {"elicitation": {}}, _answer({"action": "accept", "content": {"name": "Ada"}})
    )
    params = yield from S.decode_unknown_effect(MS.ELICIT.payload_schema)(REQUEST)
    yield from client.run(_elicit(params))
    assert client.requests[0]["payload"] == REQUEST


@pytest.mark.parametrize("protocol", ELICITING, ids=_id)
@testing.effect
def test_must_send_elicitation_requests_when_the_client_advertises_elicitation(
    protocol: P.AnyProtocolAdapter,
):
    """Mcp Conformance / Elicitation / Capabilities / MUST send elicitation requests when the client advertises elicitation"""  # noqa: E501
    client = yield from peer(
        protocol, {"elicitation": {}}, _answer({"action": "accept", "content": {"name": "Ada"}})
    )
    yield from client.run(_elicit(REQUEST))
    assert client.requests[0]["method"] == "elicitation/create"


@testing.effect
def test_must_gate_form_and_url_modes_on_their_independent_nested_capabilities():
    """Mcp Conformance / Elicitation / Capabilities / MUST gate form and URL modes on their independent nested capabilities"""  # noqa: E501
    form_only = yield from peer(LATEST, {"elicitation": {"form": {}}})
    url_only = yield from peer(LATEST, {"elicitation": {"url": {}}})
    form_on_url_only = yield from url_only.run(_elicit(REQUEST))
    url_on_form_only = yield from form_only.run(_elicit(URL_REQUEST))
    assert isinstance(form_on_url_only, Failure)
    assert isinstance(url_on_form_only, Failure)
    assert form_only.requests == []
    assert url_only.requests == []


# --- Form Mode ------------------------------------------------------------------------------


@pytest.mark.parametrize("protocol", ELICITING, ids=_id)
@testing.effect
def test_must_send_the_message_and_requested_primitive_form_schema(
    protocol: P.AnyProtocolAdapter,
):
    """Mcp Conformance / Elicitation / Form Mode / MUST send the message and requested primitive form schema"""  # noqa: E501
    content = {"name": "Ada", "age": 37, "subscribed": True}
    client = yield from peer(
        protocol, {"elicitation": {}}, _answer({"action": "accept", "content": content})
    )
    result = yield from client.run(_elicit(REQUEST))
    payload = client.requests[0]["payload"]
    assert payload["message"] == REQUEST["message"]
    assert payload["requestedSchema"] == REQUEST["requestedSchema"]
    assert isinstance(result, fx.exit.Success)
    assert result.value["action"] == "accept"
    assert result.value["content"] == content


@testing.effect
def test_must_preserve_omitted_and_explicit_form_modes():
    """Mcp Conformance / Elicitation / Form Mode / MUST preserve omitted and explicit form modes"""
    client = yield from peer(
        LATEST,
        {"elicitation": {"form": {}}},
        _answer({"action": "accept", "content": {"name": "Ada"}}),
    )
    decode = S.decode_unknown_effect(MS.ELICIT.payload_schema)
    yield from client.run(_elicit((yield from decode(REQUEST))))
    yield from client.run(_elicit((yield from decode({**REQUEST, "mode": "form"}))))
    assert [r["payload"] for r in client.requests] == [REQUEST, {**REQUEST, "mode": "form"}]


@pytest.mark.parametrize("protocol", ELICITING, ids=_id)
@testing.effect
def test_must_decode_accepted_content_against_the_requested_schema(
    protocol: P.AnyProtocolAdapter,
):
    """Mcp Conformance / Elicitation / Form Mode / MUST decode accepted content against the requested schema"""  # noqa: E501
    client = yield from peer(
        protocol,
        {"elicitation": {}},
        _answer({"action": "accept", "content": {"name": "Ada", "age": "37"}}),
    )
    schema = S.Struct(Profile, age=S.NumberFromString)
    result = yield from client.run(_run_elicitation(schema))
    assert isinstance(result, fx.exit.Success)
    assert result.value == {"name": "Ada", "age": 37}


@pytest.mark.parametrize("protocol", ELICITING, ids=_id)
@testing.effect
def test_must_reject_schemas_outside_the_elicitation_subset_before_sending(
    protocol: P.AnyProtocolAdapter,
):
    """Mcp Conformance / Elicitation / Form Mode / MUST reject schemas outside the elicitation subset before sending"""  # noqa: E501
    client = yield from peer(protocol, {"elicitation": {}})
    exit_ = yield from client.run(_run_elicitation(S.Struct(Nested)))
    assert isinstance(exit_, Failure)
    assert exit_.cause.has_dies
    assert client.requests == []


@pytest.mark.parametrize("protocol", ELICITING, ids=_id)
@testing.effect
def test_scenario_returns_a_typed_failure_when_the_user_declines(protocol: P.AnyProtocolAdapter):
    """Mcp Conformance / Elicitation / Form Mode / SCENARIO returns a typed failure when the user declines"""  # noqa: E501
    client = yield from peer(protocol, {"elicitation": {}}, _answer({"action": "decline"}))
    exit_ = yield from client.run(_run_elicitation(S.Struct(Name)))
    assert isinstance(exit_, Failure)
    assert isinstance(exit_.cause.squash(), MS.ElicitationDeclined)


@pytest.mark.parametrize("protocol", ELICITING, ids=_id)
@testing.effect
def test_scenario_interrupts_the_operation_when_the_user_cancels(protocol: P.AnyProtocolAdapter):
    """Mcp Conformance / Elicitation / Form Mode / SCENARIO interrupts the operation when the user cancels"""  # noqa: E501
    client = yield from peer(protocol, {"elicitation": {}}, _answer({"action": "cancel"}))
    exit_ = yield from client.run(_run_elicitation(S.Struct(Name)))
    assert isinstance(exit_, Failure)
    assert exit_.cause.has_interrupts


@pytest.mark.parametrize("protocol", ELICITING, ids=_id)
@testing.effect
def test_must_reject_accepted_content_that_does_not_match_the_requested_schema(
    protocol: P.AnyProtocolAdapter,
):
    """Mcp Conformance / Elicitation / Form Mode / MUST reject accepted content that does not match the requested schema"""  # noqa: E501
    client = yield from peer(
        protocol, {"elicitation": {}}, _answer({"action": "accept", "content": {"name": 123}})
    )
    exit_ = yield from client.run(_run_elicitation(S.Struct(Name)))
    assert isinstance(exit_, Failure)
    assert exit_.cause.has_dies


# --- URL Mode -------------------------------------------------------------------------------


@testing.effect
def test_must_round_trip_url_elicitation():
    """Mcp Conformance / Elicitation / URL Mode / MUST round-trip URL elicitation"""
    client = yield from peer(LATEST, {"elicitation": {"url": {}}}, _answer({"action": "accept"}))
    params = yield from S.decode_unknown_effect(MS.ELICIT.payload_schema)(URL_REQUEST)
    result = yield from client.run(_elicit(params))
    assert client.requests[0]["payload"] == URL_REQUEST
    assert isinstance(result, fx.exit.Success)
    assert result.value["action"] == "accept"


# --- Not Effect test titles: v2025_06_18.ts's elicit projection ------------------------------


@testing.effect
def test_form_elicitation_on_2025_06_18_is_sent_without_its_mode():
    """Python-only: Effect's 2025-06-18 ``elicit`` omits ``mode: "form"``, which its schema lacks."""  # noqa: E501
    client = yield from peer(
        P.v2025_06_18, {"elicitation": {}}, _answer({"action": "accept", "content": {"name": "x"}})
    )
    yield from client.run(_run_elicitation(S.Struct(Name)))
    assert "mode" not in client.requests[0]["payload"]


@testing.effect
def test_url_elicitation_is_not_representable_on_2025_06_18():
    """Python-only: Effect's 2025-06-18 ``elicit`` refuses a URL-mode request before sending."""
    client = yield from peer(P.v2025_06_18, {"elicitation": {}})
    exit_ = yield from client.run(_elicit(URL_REQUEST))
    assert isinstance(exit_, Failure)
    error = exit_.cause.squash()
    assert isinstance(error, MS.McpReverseOperationUnsupported)
    assert error.reason == "Request is not representable by this protocol"
    assert client.requests == []
