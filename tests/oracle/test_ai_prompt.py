"""Ports of Effect's ``test/ai/Prompt.test.ts``.

Each test's docstring is the Effect test title (with its ``describe``).
``Prompt.makePart("text", {...})`` is ``TextPart(...)``,
``Prompt.makeMessage("user", {...})`` is ``UserMessage(...)`` and
``Response.makePart(type, {...})`` is the response part's class.
``Prompt.concat(a, b)``, ``appendSystem`` and ``prependSystem`` are methods.
"""

from __future__ import annotations

from typing import Never, cast

import pyfect as fx
from pyfect import schema as S
from pyfect.ai import prompt as P
from pyfect.ai import response as R
from pyfect.encoding import schema_binary
from pyfect.http import url


def test_preserves_text_parts():
    """serialization / preserves text parts during serialization"""
    prompt = P.make(
        [
            {
                "role": "user",
                "content": [{"type": "text", "text": "first"}, {"type": "text", "text": "second"}],
            },
            {
                "role": "assistant",
                "content": [
                    {
                        "type": "text",
                        "text": "response",
                        "options": {"test": {"cache": "ephemeral"}},
                    }
                ],
            },
        ]
    )
    assert S.decode_sync(P.Prompt)(S.encode_sync(P.Prompt)(prompt)) == prompt


def test_part_schemas():
    """part schemas / exports schemas for all parts and message-specific parts"""
    parts: dict[str, dict[str, object]] = {
        "text": {"type": "text", "text": "hello"},
        "reasoning": {"type": "reasoning", "text": "thinking"},
        "file": {"type": "file", "mediaType": "text/plain", "data": "hello"},
        "tool_call": {"type": "tool-call", "id": "call-1", "name": "tool", "params": {}},
        "tool_result": {
            "type": "tool-result",
            "id": "call-1",
            "name": "tool",
            "isFailure": False,
            "result": "done",
        },
        "approval_response": {
            "type": "tool-approval-response",
            "approvalId": "approval-1",
            "approved": True,
        },
        "approval_request": {
            "type": "tool-approval-request",
            "approvalId": "approval-1",
            "toolCallId": "call-1",
        },
    }

    def ok(schema: S.Codec[object, object, Never, object], part: object) -> bool:
        return isinstance(S.decode_unknown_exit(schema)(part), fx.Success)

    assert all(ok(P.PART, part) for part in parts.values())
    assert all(ok(P.USER_MESSAGE_PART, parts[k]) for k in ("text", "file"))
    assistant = ("text", "file", "reasoning", "tool_call", "tool_result", "approval_request")
    assert all(ok(P.ASSISTANT_MESSAGE_PART, parts[k]) for k in assistant)
    assert all(ok(P.TOOL_MESSAGE_PART, parts[k]) for k in ("tool_result", "approval_response"))


def _call(
    id: str, name: str, *, params: object = None, provider_executed: bool = False
) -> R.ToolCallPart[str, object]:
    return R.ToolCallPart[str, object](
        id=id,
        name=name,
        params=dict[str, object]() if params is None else params,
        provider_executed=provider_executed,
    )


def _result(
    id: str,
    name: str,
    result: object,
    *,
    preliminary: bool = False,
    provider_executed: bool = False,
):
    return R.ToolResultSuccess(
        id=id,
        name=name,
        result=result,
        encoded_result=result,
        preliminary=preliminary,
        provider_executed=provider_executed,
    )


def test_binary_round_trips_file_data_forms():
    """binary codecs / round trips file data forms"""
    codec = schema_binary.to_codec(P.FilePart)
    for data in ("aGVsbG8=", b"\x01\x02\x03", url.parse("https://example.com/image.png")):
        part = P.FilePart(media_type="image/png", data=data)
        assert S.decode_sync(codec)(S.encode_sync(codec)(part)) == part


def test_keeps_tagged_json_encoding_for_file_data():
    """binary codecs / keeps the tagged JSON encoding for byte and URL file data"""

    def encode(data: bytes | url.Url) -> object:
        encoded = S.encode_sync(P.FilePart)(P.FilePart(media_type="image/png", data=data))
        return cast("dict[str, object]", encoded)["data"]

    assert encode(b"\x01\x02\x03") == {"_tag": "Uint8Array", "base64": "AQID"}
    assert encode(url.parse("https://example.com/image.png")) == {
        "_tag": "URL",
        "href": "https://example.com/image.png",
    }


def test_keeps_text_before_interleaved_tool_call():
    """fromResponseParts / keeps text before an interleaved tool call"""
    prompt = P.from_response_parts(
        [
            R.TextStartPart(id="t1"),
            R.TextDeltaPart(id="t1", delta="Hello"),
            _call("call-1", "get_weather"),
            R.TextEndPart(id="t1"),
        ]
    )
    assert prompt == P.make(
        [
            {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "Hello"},
                    {
                        "type": "tool-call",
                        "id": "call-1",
                        "name": "get_weather",
                        "params": dict[str, object](),
                        "providerExecuted": False,
                    },
                ],
            }
        ]
    )


def test_omits_unended_reasoning():
    """fromResponseParts / omits unended reasoning and empty unended text"""
    prompt = P.from_response_parts(
        [
            R.TextStartPart(id="t1"),
            R.ReasoningStartPart(id="r1"),
            R.ReasoningDeltaPart(id="r1", delta="Unsigned thinking"),
        ]
    )
    assert prompt == P.empty


def test_file_only_response():
    """fromResponseParts / preserves file-only responses as assistant messages"""
    file = R.FilePart(
        data=bytes([0, 127, 128, 255]),
        media_type="application/octet-stream",
        metadata={"example": {"id": "attachment-1", "generated": True}},
    )
    assert P.from_response_parts([file]) == P.make(
        [
            {
                "role": "assistant",
                "content": [
                    {
                        "type": "file",
                        "data": "AH+A/w==",
                        "mediaType": "application/octet-stream",
                        "options": {"example": {"id": "attachment-1", "generated": True}},
                    }
                ],
            }
        ]
    )


def test_folds_streamed_deltas():
    """fromResponseParts / folds streamed text and reasoning deltas into an assistant message"""
    parts = [
        R.TextStartPart(id="1"),
        R.TextDeltaPart(id="1", delta="Hello"),
        R.TextDeltaPart(id="1", delta=", "),
        R.TextDeltaPart(id="1", delta="World!"),
        R.TextEndPart(id="1"),
        R.ReasoningStartPart(id="2"),
        R.ReasoningDeltaPart(id="2", delta="I "),
        R.ReasoningDeltaPart(id="2", delta="am "),
        R.ReasoningDeltaPart(id="2", delta="thinking"),
        R.ReasoningEndPart(id="2"),
    ]
    assert P.from_response_parts(parts) == P.make(
        [
            {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "Hello, World!"},
                    {"type": "reasoning", "text": "I am thinking"},
                ],
            }
        ]
    )


def test_preserves_metadata_on_parts():
    """fromResponseParts / preserves metadata on non-streaming response parts"""
    parts = [
        R.TextPart(text="Hello", metadata={"test": {"value": "text"}}),
        R.ReasoningPart(
            text="Thinking", metadata={"openai": {"encryptedContent": "encrypted-reasoning"}}
        ),
        R.ToolCallPart(
            id="call-1",
            name="get_weather",
            params={"city": "London"},
            metadata={"google": {"thoughtSignature": "signed-call"}},
        ),
        R.ToolResultSuccess(
            id="call-1",
            name="get_weather",
            result={"temp": 20},
            encoded_result={"temp": 20},
            metadata={"test": {"value": "tool-result"}},
        ),
    ]
    assert P.from_response_parts(parts) == P.make(
        [
            {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "Hello", "options": {"test": {"value": "text"}}},
                    {
                        "type": "reasoning",
                        "text": "Thinking",
                        "options": {"openai": {"encryptedContent": "encrypted-reasoning"}},
                    },
                    {
                        "type": "tool-call",
                        "id": "call-1",
                        "name": "get_weather",
                        "params": {"city": "London"},
                        "providerExecuted": False,
                        "options": {"google": {"thoughtSignature": "signed-call"}},
                    },
                ],
            },
            {
                "role": "tool",
                "content": [
                    {
                        "type": "tool-result",
                        "id": "call-1",
                        "name": "get_weather",
                        "isFailure": False,
                        "result": {"temp": 20},
                        "providerExecuted": False,
                        "options": {"test": {"value": "tool-result"}},
                    }
                ],
            },
        ]
    )


def test_accumulates_streamed_metadata():
    """fromResponseParts / accumulates metadata across streamed text and reasoning parts"""
    parts = [
        R.TextStartPart(id="text-1", metadata={"testStart": {"value": "text-start"}}),
        R.TextDeltaPart(
            id="text-1", delta="Hello", metadata={"testDelta": {"value": "text-delta"}}
        ),
        R.TextEndPart(id="text-1", metadata={"testEnd": {"value": "text-end"}}),
        R.ReasoningStartPart(id="reasoning-1", metadata={"openai": {"itemId": "reasoning-item"}}),
        R.ReasoningDeltaPart(id="reasoning-1", delta="Thinking"),
        R.ReasoningDeltaPart(
            id="reasoning-1", delta="", metadata={"testDelta": {"value": "reasoning-delta"}}
        ),
        R.ReasoningEndPart(
            id="reasoning-1",
            metadata={
                "openai": {"encryptedContent": "encrypted-reasoning"},
                "testEnd": {"value": "reasoning-end"},
            },
        ),
    ]
    assert P.from_response_parts(parts) == P.make(
        [
            {
                "role": "assistant",
                "content": [
                    {
                        "type": "text",
                        "text": "Hello",
                        "options": {
                            "testStart": {"value": "text-start"},
                            "testDelta": {"value": "text-delta"},
                            "testEnd": {"value": "text-end"},
                        },
                    },
                    {
                        "type": "reasoning",
                        "text": "Thinking",
                        "options": {
                            "openai": {
                                "itemId": "reasoning-item",
                                "encryptedContent": "encrypted-reasoning",
                            },
                            "testDelta": {"value": "reasoning-delta"},
                            "testEnd": {"value": "reasoning-end"},
                        },
                    },
                ],
            }
        ]
    )


def test_tool_calls_and_results_messages():
    """fromResponseParts / places tool calls in assistant messages and tool results in tool messages"""  # noqa: E501
    prompt = P.from_response_parts(
        [
            _call("call-1", "get_weather", params={"city": "London"}),
            _result("call-1", "get_weather", {"temp": 20}),
        ]
    )
    assistant, tool = prompt.content
    assert isinstance(assistant, P.AssistantMessage)
    assert isinstance(tool, P.ToolMessage)
    assert [part.type for part in assistant.content] == ["tool-call"]
    assert [part.type for part in tool.content] == ["tool-result"]


def test_provider_executed_results_in_assistant_message():
    """fromResponseParts / places provider-executed tool results in the assistant message"""
    prompt = P.from_response_parts(
        [
            _call("ws-1", "web_search", provider_executed=True),
            _result("ws-1", "web_search", {"sources": 3}, provider_executed=True),
            _call("call-1", "get_weather", params={"city": "London"}),
            _result("call-1", "get_weather", {"temp": 20}),
        ]
    )
    assistant, tool = prompt.content
    assert isinstance(assistant, P.AssistantMessage)
    assert isinstance(tool, P.ToolMessage)
    assert len(assistant.content) == 3
    provider_result = assistant.content[1]
    assert isinstance(provider_result, P.ToolResultPart)
    assert (provider_result.id, provider_result.provider_executed) == ("ws-1", True)
    (local,) = tool.content
    assert isinstance(local, P.ToolResultPart)
    assert (local.id, local.provider_executed) == ("call-1", False)


def test_out_of_order_tool_results():
    """fromResponseParts / should handle out-of-order tool results (result before call in stream)"""
    prompt = P.from_response_parts(
        [
            _call("call-A", "tool_a"),
            _call("call-B", "tool_b"),
            _result("call-B", "tool_b", "result-B"),
            _result("call-A", "tool_a", "result-A"),
        ]
    )
    assistant, tool = prompt.content
    assert [cast_id(p) for p in assistant.content] == ["call-A", "call-B"]
    assert [cast_id(p) for p in tool.content] == ["call-B", "call-A"]


def cast_id(part: object) -> str:
    assert isinstance(part, P.ToolCallPart | P.ToolResultPart)
    return part.id


def test_keeps_only_final_tool_result():
    """fromResponseParts / keeps only the final non-preliminary tool result"""
    prompt = P.from_response_parts(
        [
            _call("call-1", "long_task"),
            _result("call-1", "long_task", {"progress": 50}, preliminary=True),
            _result("call-1", "long_task", {"progress": 100}, preliminary=True),
            _result("call-1", "long_task", {"done": True}),
        ]
    )
    assert len(prompt.content) == 2
    tool = prompt.content[1]
    assert isinstance(tool, P.ToolMessage)
    (result,) = tool.content
    assert isinstance(result, P.ToolResultPart)
    assert result.result == {"done": True}


def _messages(*texts: tuple[str, str]) -> list[P.Message]:
    return [
        P.UserMessage(content=[P.TextPart(text=text)])
        if role == "user"
        else P.AssistantMessage(content=[P.TextPart(text=text)])
        for role, text in texts
    ]


def test_concat():
    """merge / should sequentially combine the content of two Prompts"""
    left = _messages(("user", "a"), ("assistant", "b"))
    right = _messages(("user", "c"), ("assistant", "d"))
    merged = P.from_messages(left).concat(P.from_messages(right))
    assert merged == P.from_messages([*left, *right])


def test_concat_empty():
    """merge / returns Prompt.empty when both inputs have no messages"""
    assert P.empty.concat([]) == P.empty


def test_concat_raw_input():
    """merge / accepts raw message input when the left prompt is empty"""
    merged = P.empty.concat(
        [{"role": "user", "content": "a"}, {"role": "assistant", "content": "b"}]
    )
    assert merged == P.make(_messages(("user", "a"), ("assistant", "b")))


def test_concat_no_messages_keeps_prompt():
    """merge / returns the original prompt when the input has no messages"""
    prompt = P.from_messages(_messages(("user", "a"), ("assistant", "b")))
    assert prompt.concat([]) is prompt


_EXPERT = P.make(
    [
        {"role": "system", "content": "You are an expert in programming."},
        {"role": "user", "content": "Hello, world!"},
    ]
)
_HELLO = P.make([{"role": "user", "content": "Hello, world!"}])


def test_append_system():
    """appendSystem / appends text to the leading system message"""
    result = _EXPERT.append_system(" You are a helpful assistant.")
    assert result.content[0] == P.SystemMessage(
        content="You are an expert in programming. You are a helpful assistant."
    )


def test_append_system_creates():
    """appendSystem / creates a leading system message if none exists"""
    result = _HELLO.append_system("You are a helpful assistant.")
    assert result.content[0] == P.SystemMessage(content="You are a helpful assistant.")


def test_append_system_empty():
    """appendSystem / creates a system message for an empty prompt"""
    result = P.empty.append_system("You are a helpful assistant.")
    assert result.content[0] == P.SystemMessage(content="You are a helpful assistant.")


def test_prepend_system():
    """prependSystem / prepends text to the leading system message"""
    result = _EXPERT.prepend_system("You are a helpful assistant. ")
    assert result.content[0] == P.SystemMessage(
        content="You are a helpful assistant. You are an expert in programming."
    )


def test_prepend_system_creates():
    """prependSystem / creates a leading system message if none exists"""
    result = _HELLO.prepend_system("You are a helpful assistant.")
    assert result.content[0] == P.SystemMessage(content="You are a helpful assistant.")


def test_prepend_system_empty():
    """prependSystem / creates a system message for an empty prompt"""
    result = P.empty.prepend_system("You are a helpful assistant.")
    assert result.content[0] == P.SystemMessage(content="You are a helpful assistant.")
