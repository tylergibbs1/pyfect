"""What 2026-07-28 accepts as input requests and input responses, and the form
it carries them in (Effect's ``mcpSchema/v2026_07_28`` schemas). Effect's suite
has no table of these; each expected value here is what a server of the same
shape answered under Node."""

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

from ._mcp_http import Conformance, Json, http_harness, read_message, server_layer

PROTOCOL = P.v2026_07_28
TEXT: Json = {"type": "text", "text": "t"}
MESSAGE: Json = {"role": "user", "content": TEXT}
FORM: Json = {"message": "m", "requestedSchema": {"type": "object", "properties": {}}}
CAPABILITIES: Json = {
    "elicitation": {"form": {}, "url": {}},
    "roots": {},
    "sampling": {"tools": {}, "context": {}},
}
ELICIT = "elicitation/create"
SAMPLE = "sampling/createMessage"
ROOTS = "roots/list"


def _sample(**params: Any) -> Json:
    return {"method": SAMPLE, "params": {"messages": [MESSAGE], "maxTokens": 5, **params}}


def _context_text(context: MS.RequestContext) -> str:
    return json.dumps({"responses": context.input_responses, "state": context.request_state})


def _registrations() -> fx.Effect[None, Any, M.McpServer]:
    @fx.gen
    def run():
        server = yield from M.McpServer()

        def ask(arguments: Any) -> fx.Effect[Any]:
            return fx.succeed(MS.InputRequired(input_requests=arguments["requests"]))

        def echo(_: object) -> fx.Effect[Any, Any, Any]:
            return MS.McpRequestContext().map(
                lambda c: {"content": [{"type": "text", "text": _context_text(c)}]}
            )

        def echo_prompt(_: object) -> fx.Effect[Any, Any, Any]:
            return MS.McpRequestContext().map(
                lambda c: {
                    "messages": [
                        {"role": "user", "content": {"type": "text", "text": _context_text(c)}}
                    ]
                }
            )

        tool: Any = {"name": "Ask", "inputSchema": {"type": "object"}}
        yield from server.add_tool(ToolEntry(tool, Context.empty(), ask))
        tool = {"name": "Echo", "inputSchema": {"type": "object"}}
        yield from server.add_tool(ToolEntry(tool, Context.empty(), echo))
        yield from server.add_prompt(
            PromptEntry({"name": "Echo"}, Context.empty(), {}, echo_prompt)
        )
        resource: Any = {"uri": "file:///echo", "name": "Echo"}
        read = MS.McpRequestContext().map(
            lambda c: {"contents": [{"uri": "file:///echo", "text": _context_text(c)}]}
        )
        yield from server.add_resource(ResourceEntry(resource, Context.empty(), cast_read(read)))

    return run


def cast_read(read: Any) -> Any:
    return read


def _server() -> fx.Effect[Conformance, Any, Any]:
    app = server_layer("Input", (PROTOCOL,), _registrations())
    return http_harness(app).map(lambda harness: Conformance(PROTOCOL, harness))


def _send(test: Conformance, method: str, params: Json) -> fx.Effect[Json]:
    @fx.gen
    def run():
        session = yield from test.initialize()
        body = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
        response = yield from test.send(session, body, client_capabilities=CAPABILITIES)
        return (yield from read_message(response))

    return run


CARRIED = [
    pytest.param(
        {"method": ELICIT, "params": {"mode": "url", "message": "m", "url": "https://x"}},
        {"method": ELICIT, "params": {"mode": "url", "message": "m", "url": "https://x"}},
        id="a url elicitation needs no elicitationId",
    ),
    pytest.param(
        {
            "method": ELICIT,
            "params": {"mode": "url", "message": "m", "url": "https://x", "elicitationId": "e"},
        },
        {"method": ELICIT, "params": {"mode": "url", "message": "m", "url": "https://x"}},
        id="a url elicitation drops elicitationId",
    ),
    pytest.param(
        {"method": ELICIT, "params": {**FORM, "_meta": {"a": 1}, "x": 1}},
        {"method": ELICIT, "params": FORM},
        id="a form drops _meta and other keys",
    ),
    pytest.param(
        {
            "method": ELICIT,
            "params": {
                "message": "m",
                "requestedSchema": {
                    "$schema": "s",
                    "type": "object",
                    "properties": {"a": {"type": "string", "extra": 1}},
                },
            },
        },
        {
            "method": ELICIT,
            "params": {
                "message": "m",
                "requestedSchema": {
                    "$schema": "s",
                    "type": "object",
                    "properties": {"a": {"type": "string"}},
                },
            },
        },
        id="a requested schema keeps $schema, a property drops other keys",
    ),
    pytest.param(
        {"method": ROOTS, "params": {"_meta": {"a": 1}, "x": 1}},
        {"method": ROOTS, "params": {"_meta": {"a": 1}}},
        id="roots keep only _meta",
    ),
    pytest.param(_sample(x=1, _meta={"a": 1}), _sample(), id="sampling drops _meta and other keys"),
    pytest.param(
        _sample(modelPreferences={"hints": [{"name": "h", "z": 1}], "costPriority": 0.5, "x": 2}),
        _sample(modelPreferences={"hints": [{"name": "h", "z": 1}], "costPriority": 0.5}),
        id="model preferences keep what a hint adds, and only known keys",
    ),
    pytest.param(
        {
            "method": SAMPLE,
            "params": {"messages": [{"role": "user", "content": [TEXT]}], "maxTokens": 5},
        },
        {
            "method": SAMPLE,
            "params": {"messages": [{"role": "user", "content": [TEXT]}], "maxTokens": 5},
        },
        id="a sampling message may carry several blocks",
    ),
    pytest.param(
        {
            "method": SAMPLE,
            "params": {
                "messages": [
                    {
                        "role": "user",
                        "content": {"type": "tool_result", "toolUseId": "1", "content": [TEXT]},
                    }
                ],
                "maxTokens": 5,
            },
        },
        {
            "method": SAMPLE,
            "params": {
                "messages": [
                    {
                        "role": "user",
                        "content": {"type": "tool_result", "toolUseId": "1", "content": [TEXT]},
                    }
                ],
                "maxTokens": 5,
            },
        },
        id="tool results are sampling content",
    ),
]


@pytest.mark.parametrize(("request_", "carried"), CARRIED)
@testing.effect
def test_an_input_request_goes_out_in_the_july_form(request_: Json, carried: Json):
    """An ``InputRequired`` request is decoded with 2026-07-28's schema."""
    test = yield from _server()
    params = {"name": "Ask", "arguments": {"requests": {"a": request_}}}
    message = yield from _send(test, "tools/call", params)
    assert message["result"]["inputRequests"] == {"a": carried}


REFUSED_REQUESTS = [
    pytest.param(
        {"method": ELICIT, "params": {"mode": "url", "message": "m"}}, id="a url without url"
    ),
    pytest.param(
        {
            "method": ELICIT,
            "params": {
                "message": "m",
                "requestedSchema": {"type": "object", "properties": {"a": {"type": "nope"}}},
            },
        },
        id="a property of no known type",
    ),
    pytest.param({"method": ROOTS, "params": None}, id="roots params null"),
    pytest.param({"method": ROOTS, "params": {"_meta": 1}}, id="roots _meta not an object"),
    pytest.param({"method": SAMPLE, "params": {"maxTokens": 5}}, id="sampling without messages"),
    pytest.param({"method": SAMPLE, "params": {"messages": [MESSAGE]}}, id="without maxTokens"),
    pytest.param(_sample(modelPreferences={"costPriority": 2}), id="a priority above 1"),
    pytest.param(_sample(includeContext="nope"), id="an unknown includeContext"),
    pytest.param(_sample(tools=[{"name": "w"}]), id="a tool without inputSchema"),
    pytest.param(
        {
            "method": SAMPLE,
            "params": {"messages": [{"role": "user", "content": {"type": "x"}}], "maxTokens": 5},
        },
        id="sampling content of no known type",
    ),
]


@pytest.mark.parametrize("request_", REFUSED_REQUESTS)
@testing.effect
def test_a_malformed_input_request_is_an_internal_error(request_: Json):
    """Effect's result schema refuses it: its handler's ``SchemaError`` has no
    protocol error of its own."""
    test = yield from _server()
    params = {"name": "Ask", "arguments": {"requests": {"a": request_}}}
    message = yield from _send(test, "tools/call", params)
    assert message["error"] == {"code": -32603, "message": "MCP feature handler failed"}


@pytest.mark.parametrize(
    "request_",
    [
        pytest.param({"method": "nope"}, id="an unknown method"),
        pytest.param({"params": {}}, id="no method"),
        pytest.param({"method": SAMPLE}, id="sampling without params"),
        pytest.param({"method": ELICIT}, id="elicitation without params"),
        pytest.param({"method": SAMPLE, "params": None}, id="sampling with null params"),
        pytest.param({"method": ELICIT, "params": None}, id="elicitation with null params"),
        pytest.param(5, id="a number"),
        pytest.param(None, id="null"),
        pytest.param("text", id="a string"),
        pytest.param([], id="a list"),
    ],
)
@testing.effect
def test_a_request_the_capability_check_cannot_read_is_a_defect(request_: Json):
    """The check runs before the result schema and throws on these (Match's
    exhaustive case, reading ``params`` of nothing), under any capabilities."""
    test = yield from _server()
    params = {"name": "Ask", "arguments": {"requests": {"a": request_}}}
    message = yield from _send(test, "tools/call", params)
    assert message["error"] == {"code": -32603, "message": "Internal error"}


@pytest.mark.parametrize(
    ("request_", "required"),
    [
        pytest.param({"method": ROOTS, "params": "x"}, {"roots": {}}, id="roots, odd params"),
        pytest.param({"method": ROOTS, "params": None}, {"roots": {}}, id="roots, null params"),
        pytest.param({"method": ROOTS}, {"roots": {}}, id="roots, no params"),
        pytest.param(
            {"method": SAMPLE, "params": {"maxTokens": 5}},
            {"sampling": {}},
            id="sampling without messages",
        ),
        pytest.param({"method": SAMPLE, "params": "x"}, {"sampling": {}}, id="sampling, a string"),
        pytest.param(
            {"method": ELICIT, "params": {"mode": "url", "message": "m"}},
            {"elicitation": {"url": {}}},
            id="a url without url",
        ),
        pytest.param(
            {"method": ELICIT, "params": "x"}, {"elicitation": {"form": {}}}, id="form, a string"
        ),
        pytest.param(
            _sample(tools=[{"name": "w"}]), {"sampling": {"tools": {}}}, id="a tool, malformed"
        ),
    ],
)
@testing.effect
def test_missing_capabilities_answer_before_a_malformed_request_is_refused(
    request_: Json, required: Json
):
    """Effect checks capabilities on the handler's raw requests, then decodes."""
    test = yield from _server()
    session = yield from test.initialize()
    params = {"name": "Ask", "arguments": {"requests": {"a": request_}}}
    body = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": params}
    response = yield from test.send(session, body, client_capabilities={})
    message = yield from read_message(response)
    assert response.status == 400
    assert message["error"]["code"] == -32021
    assert message["error"]["data"] == {"requiredCapabilities": required}


ACCEPTED_RESPONSES = [
    pytest.param(
        {"action": "accept", "content": {"a": 1.5, "b": True, "c": ["x"], "d": "s"}},
        {"action": "accept", "content": {"a": 1.5, "b": True, "c": ["x"], "d": "s"}},
        id="elicitation values",
    ),
    pytest.param({"action": "decline", "_meta": {"z": 1}}, {"action": "decline"}, id="no _meta"),
    pytest.param(
        {"action": "accept", "extra": 1}, {"action": "accept"}, id="elicitation drops other keys"
    ),
    pytest.param(
        {"roots": [{"uri": "u", "name": "n", "x": 1, "_meta": {"z": 1}}], "_meta": {"q": 1}},
        {"roots": [{"uri": "u", "name": "n", "_meta": {"z": 1}}]},
        id="roots, whose own _meta stays",
    ),
    pytest.param(
        {"role": "assistant", "content": [TEXT], "model": "m", "stopReason": "x"},
        {"role": "assistant", "content": [TEXT], "model": "m", "stopReason": "x"},
        id="sampling with several blocks",
    ),
    pytest.param(
        {
            "role": "assistant",
            "content": {"type": "tool_use", "id": "1", "name": "n", "input": {}},
            "model": "m",
        },
        {
            "role": "assistant",
            "content": {"type": "tool_use", "id": "1", "name": "n", "input": {}},
            "model": "m",
        },
        id="sampling with a tool use",
    ),
    pytest.param(
        {"role": "assistant", "content": TEXT, "model": "m", "_meta": {"a": 1}, "x": 1},
        {"role": "assistant", "content": TEXT, "model": "m", "_meta": {"a": 1}},
        id="sampling keeps _meta and drops other keys",
    ),
]


@pytest.mark.parametrize(
    ("method", "target"),
    [
        ("tools/call", {"name": "Echo"}),
        ("prompts/get", {"name": "Echo"}),
        ("resources/read", {"uri": "file:///echo"}),
    ],
    ids=["tools", "prompts", "resources"],
)
@pytest.mark.parametrize(("response", "given"), ACCEPTED_RESPONSES)
@testing.effect
def test_an_input_response_reaches_the_handler_in_the_july_form(
    method: str, target: Json, response: Json, given: Json
):
    """The context carries the responses as 2026-07-28's schema decoded them."""
    test = yield from _server()
    params = {**target, "inputResponses": {"k": response}}
    message = yield from _send(test, method, params)
    result = message["result"]
    text = {
        "tools/call": lambda: result["content"][0]["text"],
        "prompts/get": lambda: result["messages"][0]["content"]["text"],
        "resources/read": lambda: result["contents"][0]["text"],
    }[method]()
    assert json.loads(text)["responses"] == {"k": given}


REFUSED_RESPONSES = [
    pytest.param({"action": "accept", "content": {"a": {"b": 1}}}, id="a nested elicitation value"),
    pytest.param({"action": "accept", "content": {"a": None}}, id="a null elicitation value"),
    pytest.param({"action": "accept", "content": {"c": [1]}}, id="a list of numbers"),
    pytest.param({"action": "nope"}, id="an unknown action"),
    pytest.param({"role": "assistant", "content": {"type": "x"}, "model": "m"}, id="bad content"),
    pytest.param({"role": "assistant", "content": TEXT}, id="sampling without model"),
    pytest.param({"role": "x", "content": TEXT, "model": "m"}, id="an unknown role"),
    pytest.param({"roots": [{"uri": 1}]}, id="a root's uri not a string"),
    pytest.param({}, id="empty"),
    pytest.param(None, id="null"),
]


@pytest.mark.parametrize("response", REFUSED_RESPONSES)
@testing.effect
def test_a_malformed_input_response_is_invalid_params(response: Any):
    """Effect's payload schema refuses it before the handler runs."""
    test = yield from _server()
    params = {"name": "Echo", "inputResponses": {"k": response}}
    message = yield from _send(test, "tools/call", params)
    assert message["error"]["code"] == MS.INVALID_PARAMS_ERROR_CODE
