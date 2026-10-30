"""JSON nested deeper than Python's recursion limit, from a model, a
provider, an MCP peer: a typed failure (or an ignored event), never a
defect. ``json.loads`` raises ``RecursionError`` for it, which is not a
``ValueError``."""

from __future__ import annotations

# pyright: reportUnknownVariableType=false, reportUnknownArgumentType=false
# pyright: reportUnknownMemberType=false
from typing import Any, cast

import pytest
from oracle._ai_http import MockHttp
from test_ai_provider_limits import (
    Kit,
    _anthropic,  # pyright: ignore[reportPrivateUsage]
    _openai,  # pyright: ignore[reportPrivateUsage]
    _openai_chunk,  # pyright: ignore[reportPrivateUsage]
)
from test_mcp_http_sessions import URL, _http  # pyright: ignore[reportPrivateUsage]

import pyfect as fx
from pyfect import testing
from pyfect.ai import ai_error as E
from pyfect.ai import language_model as lm
from pyfect.ai import mcp_client as C
from pyfect.ai import mcp_client_error as CE
from pyfect.ai import mcp_protocol as P
from pyfect.ai.tool import unsafe_secure_json_parse
from pyfect.http import request as R
from pyfect.http import response as http_response
from pyfect.http.client import HttpClient
from pyfect.http.client import make as make_http_client
from pyfect.http.request import HttpClientRequest
from pyfect.result import Err, Ok

DEEP = "[" * 1_500_000 + "]" * 1_500_000  # past the C stack guard of json.loads


def test_secure_json_parse_refuses_deep_nesting_with_a_value_error():
    with pytest.raises(ValueError, match="nested"):
        unsafe_secure_json_parse(DEEP)


def _ai_reason(result: object) -> E.AnyReason:
    assert isinstance(result, Err), result
    error = cast("Any", result).error
    assert isinstance(error, E.AiError), error
    return error.reason


def _sse(request: HttpClientRequest, data: list[str]) -> Any:
    body = "".join(f"data: {d}\n\n" for d in data)
    return http_response.make(request, body, headers={"content-type": "text/event-stream"})


@testing.effect
def test_openai_streamed_tool_arguments_nested_too_deep():
    import json

    def call(arguments: str) -> str:
        entry = {
            "index": 0,
            "id": "call_1",
            "type": "function",
            "function": {"name": "Tool", "arguments": arguments},
        }
        return json.dumps(_openai_chunk({"tool_calls": [entry]}))

    events = [call(DEEP), json.dumps(_openai_chunk({}, "tool_calls")), "[DONE]"]
    mock = MockHttp(lambda request: fx.succeed(_sse(request, events)))
    run = lm.stream_text("hi", toolkit=Kit, disable_tool_call_resolution=True).run_collect()
    result = yield from _openai(run.result(), mock)
    assert isinstance(_ai_reason(result), E.ToolParameterValidationError)


@testing.effect
def test_openai_stream_event_nested_too_deep_is_skipped():
    import json

    events = [DEEP, json.dumps(_openai_chunk({"content": "ok"})), "[DONE]"]
    mock = MockHttp(lambda request: fx.succeed(_sse(request, events)))
    result = yield from _openai(lm.stream_text("hi").run_collect().result(), mock)
    assert isinstance(result, Ok), result


@testing.effect
def test_anthropic_streamed_tool_input_nested_too_deep():
    import json

    start = {
        "type": "message_start",
        "message": {
            "id": "msg_1",
            "type": "message",
            "role": "assistant",
            "model": "claude-sonnet-4-20250514",
            "content": [],
            "stop_reason": None,
            "stop_sequence": None,
            "usage": {"input_tokens": 1, "output_tokens": 0},
        },
    }
    block = {"type": "tool_use", "id": "toolu_1", "name": "Tool", "input": {}}
    delta = {"type": "input_json_delta", "partial_json": DEEP}
    events = [
        start,
        {"type": "content_block_start", "index": 0, "content_block": block},
        {"type": "content_block_delta", "index": 0, "delta": delta},
        {"type": "content_block_stop", "index": 0},
    ]
    mock = MockHttp(lambda request: fx.succeed(_sse(request, [json.dumps(e) for e in events])))
    run = lm.stream_text("hi", toolkit=Kit, disable_tool_call_resolution=True).run_collect()
    result = yield from _anthropic(run.result(), mock)
    assert isinstance(_ai_reason(result), E.ToolParameterValidationError)


@pytest.mark.parametrize("provide", [_anthropic, _openai], ids=["anthropic", "openai"])
@testing.effect
def test_provider_error_body_nested_too_deep(provide: Any):
    def handle(request: HttpClientRequest) -> Any:
        headers = {"content-type": "application/json"}
        return fx.succeed(http_response.make(request, DEEP, status=400, headers=headers))

    result = yield from provide(lm.generate_text("hi").result(), MockHttp(handle))
    _ai_reason(result)


@testing.effect
def test_mcp_server_answers_deep_nesting_with_a_parse_error():
    http = yield from _http()
    headers = {"accept": "application/json, text/event-stream"}
    request = R.post(URL).set_headers(headers).body_text(DEEP, "application/json")
    response = yield from http.execute(request)
    assert response.status == 400
    body: Any = yield from response.json
    assert body["error"]["code"] == -32700


@testing.effect
def test_mcp_client_refuses_deep_nesting_with_a_protocol_error():
    def handle(request: HttpClientRequest) -> fx.Effect[Any]:
        headers = {"content-type": "application/json"}
        return fx.succeed(http_response.make(request, DEEP, headers=headers))

    client = make_http_client(lambda request, _url, _signal, _fiber: handle(request))
    transport = yield from C.http(url="http://mcp.invalid/mcp", protocol=P.v2025_11_25).pipe(
        fx.provide_service(HttpClient, client)
    )
    request: Any = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
    result = yield from transport.request(request, None).result()
    assert isinstance(result, Err), result
    assert isinstance(result.error, CE.McpClientError), result.error
    assert isinstance(result.error.reason, CE.ProtocolError), result.error


def test_ai_parses_json_only_through_json_text():
    """Every JSON parse in ``pyfect.ai`` reads peer or model output, so it
    goes through ``_json_text.parse``, whose only failure is ``ValueError``."""
    import ast
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent / "src" / "pyfect" / "ai"
    offenders = [
        f"{path.relative_to(root)}:{node.lineno}"
        for path in sorted(root.rglob("*.py"))
        for node in ast.walk(ast.parse(path.read_text()))
        if isinstance(node, ast.Attribute)
        and node.attr in ("loads", "load")
        and isinstance(node.value, ast.Name)
        and node.value.id == "json"
    ]
    assert offenders == []
