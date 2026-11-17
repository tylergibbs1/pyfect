"""Ports of Effect's ``test/ai/AgUiSchema.test.ts``.

Each test's docstring is the Effect test title (with its ``describe``).
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from pyfect import schema as S
from pyfect.ai import ag_ui_schema as A
from pyfect.exit import Success

_decode_input = S.decode_unknown_exit(A.RUN_AGENT_INPUT)


def _input(messages: list[Any]) -> dict[str, Any]:
    return {"threadId": "thread-1", "runId": "run-1", "messages": messages}


def test_drops_unrecognised_union_members() -> None:
    """AgUiSchema / RunAgentInput / drops unrecognised union members: AG-UI requires
    consumers to strip union members from newer protocol versions instead of rejecting the
    whole input"""
    exit = _decode_input(
        _input(
            [
                {"id": "1", "role": "narrator", "content": "Once upon a time"},
                {
                    "id": "2",
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Hi"},
                        {"type": "hologram", "uri": "holo://1"},
                        {"type": "image", "source": {"type": "ipfs", "value": "Qm123"}},
                    ],
                },
            ]
        )
    )
    assert isinstance(exit, Success)
    assert exit.value["messages"] == [
        {"id": "2", "role": "user", "content": [{"type": "text", "text": "Hi"}]}
    ]


def test_drops_entries_whose_closed_set_values_are_unrecognised() -> None:
    """AgUiSchema / RunAgentInput / drops entries whose closed-set values are unrecognised"""
    known = {
        "id": "call-1",
        "type": "function",
        "function": {"name": "GetWeather", "arguments": "{}"},
    }
    remote = {"id": "call-2", "type": "remote", "function": {"name": "GetTime", "arguments": "{}"}}
    exit = _decode_input(
        {
            **_input([{"id": "1", "role": "assistant", "toolCalls": [known, remote]}]),
            "resume": [
                {"interruptId": "interrupt-1", "status": "expired"},
                {"interruptId": "interrupt-2", "status": "resolved"},
            ],
        }
    )
    assert isinstance(exit, Success)
    assert exit.value["messages"] == [{"id": "1", "role": "assistant", "toolCalls": [known]}]
    assert exit.value.get("resume") == [{"interruptId": "interrupt-2", "status": "resolved"}]

    missing_id = _decode_input({**_input([]), "resume": [{"status": "resolved"}]})
    assert not isinstance(missing_id, Success)


@pytest.mark.parametrize(
    "content",
    [
        [{"type": "text"}],
        [{"source": {"type": "future"}}],
        [{"type": 123, "source": {"type": "future"}}],
    ],
    ids=json.dumps,
)
def test_rejects_a_malformed_recognised_union_member(content: list[Any]) -> None:
    """AgUiSchema / RunAgentInput / rejects a malformed recognised union member: a missing
    or non-string discriminator is malformed, even when a nested value is unrecognised"""
    exit = _decode_input(_input([{"id": "1", "role": "user", "content": content}]))
    assert not isinstance(exit, Success)


def test_tools_and_context_default_to_fresh_empty_lists() -> None:
    """A run input without ``tools`` or ``context`` decodes them as empty lists, a new one
    each time, and encoding keeps them."""
    first = S.decode_unknown_sync(A.RUN_AGENT_INPUT)(_input([]))
    second = S.decode_unknown_sync(A.RUN_AGENT_INPUT)(_input([]))
    assert first["tools"] == [] and first["context"] == []
    first["tools"].append({"name": "x", "description": "y"})
    assert second["tools"] == []
    assert S.encode_sync(A.RUN_AGENT_INPUT)(second)["tools"] == []


def test_events_round_trip_through_json() -> None:
    """Every event kind decodes from its JSON form and encodes back to it, ``from`` keys of
    JSON Patch operations included."""
    events: list[dict[str, Any]] = [
        {"type": "STATE_DELTA", "delta": [{"op": "move", "from": "/a", "path": "/b"}]},
        {
            "type": "RUN_FINISHED",
            "threadId": "t",
            "runId": "r",
            "outcome": {"type": "interrupt", "interrupts": [{"id": "i", "reason": "approve"}]},
            "usage": [{"inputTokens": 1}],
        },
        {
            "type": "REASONING_ENCRYPTED_VALUE",
            "subtype": "message",
            "entityId": "e",
            "encryptedValue": "x",
        },
        {"type": "SUBAGENT_FINISHED", "subagentRunId": "s", "outcome": {"type": "suspended"}},
    ]
    codec = S.from_json_string(A.EVENT)
    for event in events:
        decoded = S.decode_unknown_sync(codec)(json.dumps(event))
        assert decoded == event
        assert json.loads(S.encode_sync(codec)(decoded)) == event

    no_interrupts: dict[str, Any] = {
        **events[1],
        "outcome": {"type": "interrupt", "interrupts": []},
    }
    assert not isinstance(S.decode_unknown_exit(A.EVENT)(no_interrupts), Success)
    negative: dict[str, Any] = {**events[1], "usage": [{"inputTokens": -1}]}
    assert not isinstance(S.decode_unknown_exit(A.EVENT)(negative), Success)
