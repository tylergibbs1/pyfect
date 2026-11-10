"""Anthropic server tool blocks survive a chat: decoded, then sent back unchanged.

A response's ``server_tool_use`` block and its result block
must decode against the toolkit and come back in the assistant message of the
next request, exactly as received. Effect 4.1.2 fails this for code execution
20250825 (its sub-tool calls match no tool) and replays the code execution,
web fetch and MCP results as user ``tool_result`` blocks, which Anthropic
rejects with 400 "unexpected tool_use_id" (docs/PARITY.md section 4).

``test_every_server_result_block_has_a_case`` keeps the cases complete: a
result block the decoder learns must get a case here.
"""

# pyright: reportUnknownVariableType=false, reportUnknownArgumentType=false
# pyright: reportUnknownMemberType=false
from __future__ import annotations

import json
from typing import Any, cast

import pytest

import pyfect as fx
from pyfect import testing
from pyfect.ai import chat, toolkit
from pyfect.ai import prompt as Pr
from pyfect.ai.anthropic import _response, client
from pyfect.ai.anthropic import language_model as alm
from pyfect.ai.anthropic import tool as AT
from pyfect.ai.tool import NameMapper
from pyfect.http import client as http_client
from pyfect.http import response as http_response
from pyfect.http.request import HttpClientRequest
from pyfect.redacted import make as redact

from ._ai_http import sse_body

_SERVER = "srvtoolu_1"


def _use(name: str, input: dict[str, Any]) -> dict[str, Any]:
    return {"type": "server_tool_use", "id": _SERVER, "name": name, "input": input}


def _result(kind: str, content: object) -> dict[str, Any]:
    return {"type": kind, "tool_use_id": _SERVER, "content": content}


_BASH_OK = {"type": "bash_code_execution_result", "stdout": "a\n", "stderr": "", "return_code": 0}
_VIEW_ERROR = {
    "type": "text_editor_code_execution_tool_result_error",
    "error_code": "unavailable",
    "error_message": "Tool response parsing error",
}
_RUN_OK = {"type": "code_execution_result", "stdout": "391\n", "stderr": "", "return_code": 0}
_SEARCH_HIT = {
    "type": "web_search_result",
    "url": "https://example.com/a",
    "title": "A",
    "encrypted_content": "e",
    "page_age": None,
}
_FETCH_OK = {
    "type": "web_fetch_result",
    "url": "https://example.com/a",
    "content": {
        "type": "document",
        "source": {"type": "text", "media_type": "text/plain", "data": "hi"},
        "title": "A",
    },
}
_REFERENCES = {
    "type": "tool_search_tool_search_result",
    "tool_references": [{"type": "tool_reference", "tool_name": "get_weather"}],
}

# (label, toolkit, the blocks of one response)
_CASES: list[tuple[str, toolkit.Toolkit[Any, Any, Any, Any], list[dict[str, Any]]]] = [
    (
        "bash 20250825",
        toolkit.make(AT.CodeExecution_20250825()),
        [
            _use("bash_code_execution", {"command": "ls"}),
            _result("bash_code_execution_tool_result", {**_BASH_OK, "content": []}),
        ],
    ),
    (
        "text editor 20250825 error",
        toolkit.make(AT.CodeExecution_20250825()),
        [
            _use("text_editor_code_execution", {"command": "view", "path": "/tmp/x"}),
            _result("text_editor_code_execution_tool_result", _VIEW_ERROR),
        ],
    ),
    (
        "code execution 20250522",
        toolkit.make(AT.CodeExecution_20250522()),
        [
            _use("code_execution", {"code": "print(391)"}),
            _result("code_execution_tool_result", {**_RUN_OK, "content": []}),
        ],
    ),
    (
        "code execution 20250522 error",
        toolkit.make(AT.CodeExecution_20250522()),
        [
            _use("code_execution", {"code": "print(391)"}),
            _result(
                "code_execution_tool_result",
                {"type": "code_execution_tool_result_error", "error_code": "unavailable"},
            ),
        ],
    ),
    (
        "web search",
        toolkit.make(AT.WebSearch_20250305({})),
        [_use("web_search", {"query": "a"}), _result("web_search_tool_result", [_SEARCH_HIT])],
    ),
    (
        "web fetch",
        toolkit.make(AT.WebFetch_20250910({})),
        [
            _use("web_fetch", {"url": "https://example.com/a"}),
            _result("web_fetch_tool_result", _FETCH_OK),
        ],
    ),
    (
        "tool search",
        toolkit.make(AT.ToolSearchRegex_20251119()),
        [
            _use("tool_search_tool_regex", {"pattern": "weather"}),
            _result("tool_search_tool_result", _REFERENCES),
        ],
    ),
]


def test_every_server_result_block_has_a_case():
    covered = {block["type"] for _, _, blocks in _CASES for block in blocks[1:]}
    # An MCP call names no toolkit tool, so a response holding one fails to
    # decode (as in Effect); `test_mcp_result_is_provider_executed` covers it.
    assert covered | {"mcp_tool_result"} == set(_response.SERVER_RESULT_BLOCKS)


def test_mcp_result_is_provider_executed():
    results = _response.ServerResults(NameMapper([]), [])
    call = {"type": "mcp_tool_use", "id": _SERVER, "name": "echo", "server_name": "s", "input": {}}
    results.mcp_call(cast(Any, call))
    block = {"type": "mcp_tool_result", "tool_use_id": _SERVER, "is_error": False, "content": []}
    (part,) = results.mcp_result(cast(Any, block))
    assert part["providerExecuted"] is True


def _message(content: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "id": "msg_1",
        "type": "message",
        "role": "assistant",
        "model": "claude-haiku-4-5",
        "content": content,
        "stop_reason": "end_turn",
        "stop_sequence": None,
        "usage": {"input_tokens": 1, "output_tokens": 1},
    }


def _events(content: list[dict[str, Any]]) -> list[object]:
    """``content`` as a stream: a tool use's input arrives as one delta."""
    events: list[object] = [
        {"type": "message_start", "message": {**_message([]), "stop_reason": None}}
    ]
    for index, block in enumerate(content):
        if block["type"] == "server_tool_use":
            start = {**block, "input": {}}
            delta = {"type": "input_json_delta", "partial_json": json.dumps(block["input"])}
            events.append({"type": "content_block_start", "index": index, "content_block": start})
            events.append({"type": "content_block_delta", "index": index, "delta": delta})
        elif block["type"] == "text":
            start = {"type": "text", "text": ""}
            delta = {"type": "text_delta", "text": block["text"]}
            events.append({"type": "content_block_start", "index": index, "content_block": start})
            events.append({"type": "content_block_delta", "index": index, "delta": delta})
        else:
            events.append({"type": "content_block_start", "index": index, "content_block": block})
        events.append({"type": "content_block_stop", "index": index})
    events.append(
        {
            "type": "message_delta",
            "delta": {"stop_reason": "end_turn", "stop_sequence": None},
            "usage": {"output_tokens": 1},
        }
    )
    events.append({"type": "message_stop"})
    return events


@pytest.mark.parametrize("streaming", [False, True], ids=["generate", "stream"])
@pytest.mark.parametrize(("label", "tools", "blocks"), _CASES, ids=[c[0] for c in _CASES])
@testing.effect
def test_server_tool_blocks_are_sent_back_unchanged(
    label: str,
    tools: toolkit.Toolkit[Any, Any, Any, Any],
    blocks: list[dict[str, Any]],
    streaming: bool,
):
    sent: list[dict[str, Any]] = []
    first = [*blocks, {"type": "text", "text": "ok"}]

    def messages_api(request: HttpClientRequest):
        body: Any = request.body
        sent.append(json.loads(body.body))
        if len(sent) == 1 and streaming:
            return fx.succeed(
                http_response.make(
                    request, sse_body(_events(first)), headers={"content-type": "text/event-stream"}
                )
            )
        reply = first if len(sent) == 1 else [{"type": "text", "text": "done"}]
        return fx.succeed(http_response.make(request, json.dumps(_message(reply))))

    @fx.fn
    def program():
        session = yield from chat.from_prompt(Pr.empty)
        if streaming:
            yield from session.stream_text("go", toolkit=tools).run_drain()
        else:
            yield from session.generate_text("go", toolkit=tools)
        yield from session.generate_text("next", toolkit=tools)

    yield from (
        program()
        .pipe(fx.provide(tools.to_layer()))
        .pipe(fx.provide(alm.model("claude-haiku-4-5").layer))
        .pipe(fx.provide(client.layer(api_key=redact("sk-test"))))
        .pipe(fx.provide(http_client.layer_test(messages_api)))
    )
    replayed = sent[1]["messages"]
    assert [m["role"] for m in replayed] == ["user", "assistant", "user"], label
    kept = [
        {k: v for k, v in block.items() if k != "cache_control"} for block in replayed[1]["content"]
    ]
    assert kept == first
