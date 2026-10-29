"""Ports of Effect's ``test/ai/McpSchema.test.ts``.

Each test's docstring is the Effect test title. MCP values are TypedDicts
in their JSON wire form, so a schema's decode and encode are inverses on
plain dicts.
"""

from __future__ import annotations

from typing import Any

import pytest

from pyfect import schema as S
from pyfect.ai import mcp_schema as M


def _round_trip(schema: Any, value: object) -> object:
    return S.encode_unknown_sync(schema)(S.decode_unknown_sync(schema)(value))


def test_round_trips_tool_schemas_with_object_or_boolean_properties():
    """should round-trip tool schemas when properties contain object or boolean schemas"""
    input_schema = {
        "type": "object",
        "properties": {"forbidden": False, "anything": True, "text": {"type": "string"}},
    }
    assert _round_trip(M.TOOL_JSON, input_schema) == input_schema
    with pytest.raises(S.SchemaError):
        S.decode_unknown_sync(M.TOOL_JSON)({"type": "object", "properties": {"invalid": None}})


def test_preserves_custom_request_metadata():
    """should preserve custom metadata when a request is decoded and encoded"""
    progresses: list[dict[str, object]] = [
        {},
        {"progressToken": "progress-1"},
        {"progressToken": 1},
    ]
    for progress in progresses:
        request = {
            "_meta": {
                **progress,
                "marker": "request",
                "custom": {"values": [None, True, 42, "value"]},
            }
        }
        assert _round_trip(M.REQUEST_META, request) == request


def test_create_message_metadata_may_be_omitted():
    """allows create-message metadata to be omitted"""
    S.decode_unknown_sync(M.CREATE_MESSAGE.payload_schema)({"messages": [], "maxTokens": 1})


def test_create_message_metadata_must_be_an_object():
    """requires create-message metadata to be an object"""
    with pytest.raises(S.SchemaError):
        S.decode_unknown_sync(M.CREATE_MESSAGE.payload_schema)(
            {"messages": [], "maxTokens": 1, "metadata": "invalid"}
        )


def test_preserves_every_elicitation_enum_form():
    """should preserve every November elicitation enum form when decoding a form request"""
    properties = {
        "untitled": {"type": "string", "enum": ["one", "two"]},
        "titled": {"type": "string", "oneOf": [{"const": "one", "title": "One"}]},
        "legacy": {"type": "string", "enum": ["one"], "enumNames": ["One"]},
    }
    decoded: Any = S.decode_unknown_sync(M.ELICIT_REQUEST_FORM_PARAMS)(
        {
            "mode": "form",
            "message": "Choose values",
            "requestedSchema": {"type": "object", "properties": properties},
        }
    )
    assert decoded["requestedSchema"]["properties"] == properties


def test_round_trips_an_implementation_with_icons():
    """round-trips an implementation with icons"""
    implementation = {
        "name": "server",
        "version": "1.0.0",
        "icons": [{"src": "https://example.com/icon.png"}],
    }
    assert _round_trip(M.IMPLEMENTATION, implementation) == implementation
