"""Ports of the direct-service and ``registerToolkit`` titles of Effect's
``test/ai/McpServer/McpServer.test.ts`` that ``test_mcp_server.py`` does
not hold.

Each test's docstring is the Effect test title (with its ``describe``).

Omitted, with the reason:

- ``publishes the definitions an inlined tool schema references by
  anchor``: it builds a filter whose ``toJsonSchema`` emits a ``$anchor``
  and a representation of another schema; pyfect's filters have no
  ``$anchor`` output, so no schema can reference a definition that way.
"""

from __future__ import annotations

import datetime
import json
from collections.abc import Sequence
from typing import Any, Never, NotRequired, TypedDict, cast

import pytest

import pyfect as fx
from pyfect import error_reporter, layer, redacted, testing
from pyfect import logger as L
from pyfect import schema as S
from pyfect.ai import ai_error as AiErr
from pyfect.ai import mcp_protocol as P
from pyfect.ai import mcp_schema as MS
from pyfect.ai import mcp_server as M
from pyfect.ai import tool as T
from pyfect.ai import toolkit as K
from pyfect.ai._mcp.core import ResourceEntry, ToolEntry
from pyfect.context import Context, Tag
from pyfect.redacted import Redacted

from ._mcp import StdioHarness, stdio_harness


def _client(client_id: int, name: str, protocol_version: str = "2025-06-18") -> MS.ServerClient:
    info: MS.Implementation = {"name": name, "version": "1"}
    return MS.ServerClient(
        client_id=client_id,
        protocol_version=protocol_version,
        client_capabilities={},
        client_info=info,
        initialize_payload={
            "protocolVersion": protocol_version,
            "capabilities": {},
            "clientInfo": cast("Any", info),
        },
        get_client=fx.die(RuntimeError("No reverse requests are needed")),
        request_metadata={"owner": name},
    )


DIRECT = _client(1, "TestClient")


def _direct[A, E](
    effect: fx.Effect[A, E, MS.McpServerClient], client: MS.ServerClient = DIRECT
) -> fx.Effect[A, E]:
    return effect.pipe(fx.provide_service(MS.McpServerClient, client))


def _text(result: MS.CallToolResult) -> str:
    [block] = result["content"]
    return cast("Any", block)["text"]


# --- direct service ------------------------------------------------------------------------


@testing.effect
def test_returns_from_completion_notification_when_the_protocol_does_not_support_it():
    """McpServer / should return from completion notification when the target protocol does not support it"""  # noqa: E501
    harness = yield from stdio_harness(P.v2025_06_18)
    yield from harness.initialize()
    yield from harness.server.notify_elicitation_complete(1, "unsupported")
    assert (yield from harness.send_request("ping", {}))["result"] == {}


class Profile(TypedDict):
    name: str


@testing.effect
def test_inlines_identified_elicitation_schemas():
    """McpServer / direct service / inlines identified elicitation schemas"""
    observed: list[MS.ElicitRequestParams] = []

    def elicit(request: MS.ElicitRequestParams) -> fx.Effect[MS.ElicitResult, Any]:
        observed.append(request)
        return fx.succeed(cast("MS.ElicitResult", {"action": "accept", "content": {"name": "Ada"}}))

    reverse = MS.ReverseClient(
        lambda: fx.die(RuntimeError("Not used")),
        lambda _: fx.die(RuntimeError("Not used")),
        elicit,
    )
    capabilities: MS.ClientCapabilities = {"elicitation": {"form": {}}}
    client = MS.ServerClient(
        client_id=1,
        protocol_version="2025-11-25",
        client_capabilities=capabilities,
        client_info={"name": "client", "version": "1"},
        initialize_payload={},
        get_client=fx.succeed(reverse),
    )
    result = yield from M.elicit(
        message="Profile", schema=S.Struct(Profile).annotate(identifier="Profile")
    ).pipe(fx.provide_service(MS.McpServerClient, client))
    assert result == {"name": "Ada"}
    [request] = observed
    assert request.get("mode") == "form"
    assert json.loads(json.dumps(request.get("requestedSchema"))) == {
        "type": "object",
        "properties": {"name": {"type": "string"}},
        "required": ["name"],
    }


class RegistrationLabel(Tag[str], key="test/RegistrationLabel"):
    pass


def _current_owner() -> fx.Effect[str, Never, MS.McpRequestContext | RegistrationLabel]:
    @fx.gen
    def run():
        request = yield from MS.McpRequestContext()
        label = yield from RegistrationLabel()
        info = request.client_info or {"name": "", "version": ""}
        owner = (request.request_metadata or {}).get("owner")
        return f"{label}:{request.client_id}:{info['name']}:{owner}"

    return run


class NameParams(TypedDict):
    name: str


_owner_tool = (
    T.make("owner", success=S.String)
    .add_dependency(MS.McpRequestContext)
    .add_dependency(RegistrationLabel)
)
_owner_kit = K.make(_owner_tool)


def _registered_server() -> fx.Effect[M.McpServerService, Any]:
    @fx.gen
    def run():
        server = yield from M.make()
        provide_label = M.middleware(
            lambda effect, _: effect.pipe(fx.provide_service(RegistrationLabel, "middleware")),
            provides=RegistrationLabel,
        )

        def register(_: object) -> fx.Effect[MS.CallToolResult, Any, Any]:
            @fx.gen
            def body():
                yield from M.register_resource(
                    uri="file:///owner", name="owner", content=_current_owner()
                )
                yield from M.register_resource_template(
                    M.uri_template("file:///owners/", S.String),
                    name="owners",
                    content=lambda _uri, _name: _current_owner(),
                    completion={"param0": lambda _v, _c: _current_owner().map(lambda o: [o])},
                )
                yield from M.register_prompt(
                    name="owner",
                    parameters=S.Struct(NameParams),
                    content=lambda _: _current_owner(),
                    completion={"name": lambda _v, _c: _current_owner().map(lambda o: [o])},
                )
                yield from M.register_toolkit(_owner_kit).pipe(
                    fx.provide(
                        _owner_kit.to_layer(_owner_tool.handler(lambda _, __: _current_owner()))
                    )
                )
                return cast("MS.CallToolResult", {"content": []})

            return (
                body.pipe(fx.provide(provide_label.layer))
                .pipe(fx.provide_service(M.McpServer, server))
                .pipe(fx.provide_service(RegistrationLabel, "registered"))
                .or_die()
            )

        yield from server.add_tool(
            ToolEntry(
                {"name": "register", "inputSchema": {"type": "object"}}, Context.empty(), register
            )
        )
        yield from _direct(server.call_tool({"name": "register"}), _client(1, "Alice"))
        return server

    return run


BOB = _client(2, "Bob")
EXPECTED_OWNER = "middleware:2:Bob:Bob"


def _as_bob[A, E](effect: fx.Effect[A, E, MS.McpServerClient]) -> fx.Effect[A, E]:
    return _direct(effect, BOB).pipe(fx.provide_service(RegistrationLabel, "invocation"))


@testing.effect
def test_uses_the_current_request_for_a_resource_registered_by_another_client():
    """McpServer / direct service / registration context / should use the current request when a resource was registered by another client"""  # noqa: E501
    server = yield from _registered_server()
    result = yield from _as_bob(server.find_resource("file:///owner"))
    assert result["contents"] == [{"uri": "file:///owner", "text": EXPECTED_OWNER}]


@testing.effect
def test_uses_the_current_request_for_a_resource_template_registered_by_another_client():
    """McpServer / direct service / registration context / should use the current request when a resource template was registered by another client"""  # noqa: E501
    server = yield from _registered_server()
    result = yield from _as_bob(server.find_resource("file:///owners/bob"))
    assert result["contents"] == [{"uri": "file:///owners/bob", "text": EXPECTED_OWNER}]


@testing.effect
def test_uses_the_current_request_for_a_prompt_registered_by_another_client():
    """McpServer / direct service / registration context / should use the current request when a prompt was registered by another client"""  # noqa: E501
    server = yield from _registered_server()
    result = yield from _as_bob(server.get_prompt_result("owner", {"name": "bob"}))
    assert result["messages"] == [
        {"role": "user", "content": {"type": "text", "text": EXPECTED_OWNER}}
    ]


@testing.effect
def test_uses_the_current_request_for_a_resource_completion_registered_by_another_client():
    """McpServer / direct service / registration context / should use the current request when a resource completion was registered by another client"""  # noqa: E501
    server = yield from _registered_server()
    result = yield from _as_bob(
        server.completion(
            {
                "ref": {"type": "ref/resource", "uri": "file:///owners/{param0}"},
                "argument": {"name": "param0", "value": "b"},
            }
        )
    )
    assert result["completion"]["values"] == [EXPECTED_OWNER]


@testing.effect
def test_uses_the_current_request_for_a_prompt_completion_registered_by_another_client():
    """McpServer / direct service / registration context / should use the current request when a prompt completion was registered by another client"""  # noqa: E501
    server = yield from _registered_server()
    result = yield from _as_bob(
        server.completion(
            {
                "ref": {"type": "ref/prompt", "name": "owner"},
                "argument": {"name": "name", "value": "b"},
            }
        )
    )
    assert result["completion"]["values"] == [EXPECTED_OWNER]


@testing.effect
def test_uses_the_current_request_for_a_toolkit_registered_by_another_client():
    """McpServer / direct service / registration context / should use the current request when a toolkit was registered by another client"""  # noqa: E501
    server = yield from _registered_server()
    result = yield from _as_bob(server.call_tool({"name": "owner"}))
    assert result.get("isError") is False
    assert result.get("structuredContent") == EXPECTED_OWNER


@testing.effect
def test_preserves_a_registered_resource_handlers_typed_failure():
    """McpServer / direct service / should preserve a registered resource handler's typed failure"""
    server = yield from M.make()
    failure = MS.InternalError("resource failed")
    yield from server.add_resource(
        ResourceEntry(
            {"uri": "file:///failure", "name": "failure"}, Context.empty(), fx.fail(failure)
        )
    )
    error = yield from _direct(server.find_resource("file:///failure")).flip()
    assert error is failure


# --- registerToolkit -----------------------------------------------------------------------


def _register(
    kit: K.Toolkit[Any, Any, Any, Any], *handlers: Any
) -> fx.Effect[tuple[M.McpServerService, fx.Exit[None, Any]]]:
    @fx.gen
    def run():
        server = yield from M.make()
        exit = yield from (
            M.register_toolkit(kit)
            .pipe(fx.provide_service(M.McpServer, server))
            .pipe(fx.provide(kit.to_layer(*handlers)))
            .exit()
        )
        return server, exit

    return cast("Any", run)


class Value(TypedDict):
    value: str


@testing.effect
def test_registers_non_strict_tools_with_identified_input_schemas():
    """McpServer / registerToolkit / registers non-strict tools with identified input schemas"""
    tool = T.make(
        "IdentifiedTool",
        parameters=S.Struct(Value).annotate(identifier="Input / ~ %"),
        success=S.String,
    )
    server, exit = yield from _register(
        K.make(tool), tool.handler(lambda p, _: fx.succeed(p["value"]))
    )
    assert isinstance(exit, fx.Success)
    input_schema = server.tools[0].tool["inputSchema"]
    assert input_schema["type"] == "object"
    assert input_schema.get("properties") == {"value": {"type": "string"}}
    assert input_schema.get("additionalProperties") is True
    result = yield from _direct(
        server.call_tool({"name": "IdentifiedTool", "arguments": {"value": "ok", "typo": True}})
    )
    assert result.get("structuredContent") == "ok"


class Event(S.Class):
    at: datetime.datetime = S.field(S.DateTimeUtc)


class Tree(TypedDict):
    children: Sequence[Tree]


TREE: S.Codec[Tree, Any, Any, Any] = S.Struct(
    Tree, children=S.Array(S.suspend(lambda: TREE))
).annotate(identifier="Tree")


@testing.effect
def test_registers_tools_with_identified_output_schemas():
    """McpServer / registerToolkit / registers tools with identified output schemas"""
    identified = T.make(
        "IdentifiedResultTool", success=S.Struct(Value).annotate(identifier="IdentifiedResult")
    )
    event = T.make("EventTool", success=Event)
    tree = T.make("TreeTool", success=TREE)
    server, exit = yield from _register(
        K.make(identified, event, tree),
        identified.handler(lambda _, __: fx.succeed(Value(value="ok"))),
        event.handler(
            lambda _, __: fx.succeed(Event(at=datetime.datetime.fromtimestamp(0, datetime.UTC)))
        ),
        tree.handler(lambda _, __: fx.succeed(Tree(children=[]))),
    )
    assert isinstance(exit, fx.Success)
    tree_schema = {
        "type": "object",
        "properties": {"children": {"type": "array", "items": {"$ref": "#/$defs/Tree"}}},
        "required": ["children"],
        "additionalProperties": True,
    }
    assert [entry.tool.get("outputSchema") for entry in server.tools] == [
        {
            "type": "object",
            "properties": {"value": {"type": "string"}},
            "required": ["value"],
            "additionalProperties": True,
        },
        {
            "type": "object",
            "properties": {"at": {"type": "string"}},
            "required": ["at"],
            "additionalProperties": True,
        },
        {**tree_schema, "$defs": {"Tree": tree_schema}},
    ]


class StrictInner(TypedDict):
    value: float


class StrictParams(TypedDict):
    config: StrictInner


StrictObjectTool = T.make(
    "StrictObjectTool",
    parameters=S.Struct(
        StrictParams, config=S.Struct(StrictInner, value=S.FiniteFromString)
    ).annotate(identifier="Strict / ~ % Input"),
    success=S.String,
    failure_mode="return",
).annotate(T.Strict, True)


def _strict_harness(invoked: list[bool]) -> fx.Effect[StdioHarness, Any, Any]:
    """A stdio client of ``StrictObjectTool`` on 2025-06-18 (Effect's
    ``makeToolkitTestClient``)."""

    def handle(params: StrictParams, _: object) -> fx.Effect[str]:
        invoked.append(True)
        return fx.succeed(f"{params['config']['value']:.0f}")

    kit = K.make(StrictObjectTool)
    registration = M.register_toolkit(kit).pipe(
        fx.provide(kit.to_layer(StrictObjectTool.handler(handle)))
    )

    @fx.gen
    def run():
        harness = yield from stdio_harness(P.v2025_06_18, None, registration)
        yield from harness.initialize()
        return harness

    return run


@testing.effect
def test_advertises_closed_strict_input_schemas_with_escaped_identifiers():
    """McpServer / registerToolkit / advertises closed strict input schemas with escaped identifiers"""  # noqa: E501
    harness = yield from _strict_harness([])
    [tool] = (yield from harness.send_request("tools/list", {}))["result"]["tools"]
    schema = tool["inputSchema"]
    assert schema["type"] == "object"
    assert schema.get("additionalProperties") is False
    assert schema["properties"]["config"] == {
        "type": "object",
        "properties": {"value": {"type": "string"}},
        "required": ["value"],
        "additionalProperties": False,
    }


@testing.effect
def test_validates_strict_return_mode_arguments_before_invoking_the_handler():
    """McpServer / registerToolkit / validates strict return-mode arguments before invoking the handler and decodes them once"""  # noqa: E501
    invoked: list[bool] = []
    harness = yield from _strict_harness(invoked)
    cases: list[MS.JsonObject] = [
        {"config": {"value": "1"}, "typo": True},
        {"config": {"value": "1", "typo": True}},
        {"config": {"value": 1}},
    ]
    for arguments in cases:
        error = (yield from _call(harness, "StrictObjectTool", arguments))["error"]
        assert invoked == []
        assert error["code"] == MS.INVALID_PARAMS_ERROR_CODE
        assert "Invalid parameters for tool 'StrictObjectTool'" in error["message"]
        for leaked in ("AiError", "ToolParameterValidationError", "Toolkit"):
            assert leaked not in error["message"]
    result = (yield from _call(harness, "StrictObjectTool", {"config": {"value": "1"}}))["result"]
    assert invoked == [True]
    assert _text(result) == "1"


@testing.effect
def test_reports_all_strict_parameter_errors_without_invoking_the_handler():
    """McpServer / registerToolkit / reports all strict parameter errors without invoking the handler"""  # noqa: E501
    invoked: list[bool] = []
    harness = yield from _strict_harness(invoked)
    configs: list[MS.JsonObject] = [{"value": "1"}, {"value": 1}, {}]
    for config in configs:
        arguments: MS.JsonObject = {
            "first": True,
            "second": True,
            "config": {**config, "third": True, "fourth": True},
        }
        error = (yield from _call(harness, "StrictObjectTool", arguments))["error"]
        message = error["message"]
        assert error["code"] == MS.INVALID_PARAMS_ERROR_CODE
        assert "Invalid parameters for tool 'StrictObjectTool'" in message
        for path in ('["first"]', '["second"]', '["config"]["third"]', '["config"]["fourth"]'):
            assert path in message
        if config.get("value") != "1":
            assert '["config"]["value"]' in message
        assert invoked == []


@testing.effect
def test_dies_on_strict_raw_json_schema_tools_before_registering_any():
    """McpServer / registerToolkit / dies on strict raw JSON Schema tools before registering any tools"""  # noqa: E501
    valid = T.make("ValidTool", success=S.String)
    dynamic = T.dynamic("DynamicTool", parameters={"type": "object"}, success=S.String).annotate(
        T.Strict, True
    )
    server, exit = yield from _register(
        K.make(valid, dynamic),
        valid.handler(lambda _, __: fx.succeed("ok")),
        dynamic.handler(lambda _, __: fx.succeed("ok")),
    )
    assert isinstance(exit, fx.Failure)
    assert exit.cause.has_dies
    assert "cannot strictly validate the raw JSON Schema for tool 'DynamicTool'" in str(
        exit.cause.squash()
    )
    assert server.tools == ()


@testing.effect
def test_preserves_existing_tools_when_a_later_toolkit_schema_is_invalid():
    """McpServer / registerToolkit / preserves existing tools when a later toolkit schema is invalid for MCP"""  # noqa: E501
    valid = T.make("ValidTool", success=S.String)
    invalid = T.make("InvalidTool", parameters=S.String, success=S.String).annotate(T.Strict, True)
    kit = K.make(valid, invalid)
    server = yield from M.make()
    yield from server.add_tool(
        ToolEntry(
            {"name": "ValidTool", "inputSchema": {"type": "object"}},
            Context.empty(),
            lambda _: fx.succeed(
                cast("MS.CallToolResult", {"content": [{"type": "text", "text": "existing"}]})
            ),
        )
    )
    exit = yield from (
        M.register_toolkit(kit)
        .pipe(fx.provide_service(M.McpServer, server))
        .pipe(
            fx.provide(
                kit.to_layer(
                    valid.handler(lambda _, __: fx.succeed("replacement")),
                    invalid.handler(lambda _, __: fx.succeed("invalid")),
                )
            )
        )
        .exit()
    )
    existing = yield from _direct(server.call_tool({"name": "ValidTool"}))
    assert isinstance(exit, fx.Failure)
    assert [entry.tool["name"] for entry in server.tools] == ["ValidTool"]
    assert existing["content"] == [{"type": "text", "text": "existing"}]


class EchoParams(TypedDict):
    text: str


class Empty(TypedDict):
    pass


def _not_object_rooted(invalid: T.AnyTool) -> fx.Effect[str]:
    echo = T.make("echo", parameters=S.Struct(EchoParams), success=S.String)
    kit = K.make(echo, cast("Any", invalid))

    def message(pair: tuple[M.McpServerService, fx.Exit[None, Any]]) -> str:
        server, exit = pair
        assert isinstance(exit, fx.Failure)
        assert exit.cause.has_dies
        assert server.tools == ()
        return str(exit.cause.squash())

    return _register(
        kit,
        echo.handler(lambda p, _: fx.succeed(p["text"])),
        cast("Any", invalid).handler(_always("ok")),
    ).map(message)


@testing.effect
def test_dies_when_parameters_are_an_empty_struct():
    """McpServer / registerToolkit / dies with a message naming the tool when parameters are not object-rooted / empty struct"""  # noqa: E501
    message = yield from _not_object_rooted(
        T.make("empty", parameters=S.Struct(Empty), success=S.String)
    )
    assert "cannot register tool 'empty'" in message
    assert "Tool.EMPTY_PARAMS" in message


@testing.effect
def test_dies_when_a_raw_json_schema_is_not_object_rooted():
    """McpServer / registerToolkit / dies with a message naming the tool when parameters are not object-rooted / raw JSON Schema"""  # noqa: E501
    message = yield from _not_object_rooted(
        T.dynamic(
            "raw",
            parameters={"anyOf": [{"type": "object"}, {"type": "string"}]},
            success=S.String,
        )
    )
    assert "cannot register tool 'raw': its raw JSON Schema must have an object root" in message


# The ``makeToolkitTestClient`` toolkit: tools behind a stdio server (Effect drives an
# HTTP RPC client; the results are the same), with the loggers and reporters recorded.


class OptionalSignature(TypedDict, total=False):
    signature: str


class Answer(TypedDict):
    answer: str


class Busy(TypedDict):
    reason: str
    retryAfter: float
    detail: NotRequired[object]


OptionalStringTool = T.make(
    "OptionalStringTool",
    parameters=S.Struct(OptionalSignature),
    success=S.String,
)
StructuredFailureTool = T.make(
    "StructuredFailureTool",
    success=S.Struct(Answer),
    failure=S.Struct(Busy, retryAfter=S.FiniteFromString),
)
InternalAiErrorTool = T.make("InternalAiErrorTool", success=S.String)
UnserializableResultTool = T.make("UnserializableResultTool", success=S.Unknown)
NullableResultTool = T.make("NullableResultTool", success=S.NullOr(S.Struct(Answer)))
ArrayResultTool = T.make("ArrayResultTool", success=S.Array(S.String))

INTERNAL_AI_ERROR = AiErr.make(
    module="TestToolkit", method="InternalAiErrorTool", reason=AiErr.RateLimitError()
)


class Unserializable:
    """A value JSON cannot hold (Effect's ``1n``)."""


TOOLKIT = K.make(
    OptionalStringTool,
    StructuredFailureTool,
    InternalAiErrorTool,
    UnserializableResultTool,
    NullableResultTool,
    ArrayResultTool,
)


def _always(value: object) -> Any:
    def handle(_params: Any, _context: Any) -> fx.Effect[Any]:
        return fx.succeed(value)

    return handle


def _failing(error: object) -> Any:
    def handle(_params: Any, _context: Any) -> fx.Effect[Never, Any]:
        return fx.fail(error)

    return handle


def _optional_signature(params: OptionalSignature, _context: Any) -> fx.Effect[str]:
    return fx.succeed(params.get("signature", "omitted"))


def _handlers(**overrides: Any) -> list[Any]:
    defaults: dict[str, Any] = {
        "OptionalStringTool": _optional_signature,
        "StructuredFailureTool": _failing({"reason": "busy", "retryAfter": 5.0}),
        "InternalAiErrorTool": _failing(INTERNAL_AI_ERROR),
        "UnserializableResultTool": _always(Unserializable()),
        "NullableResultTool": _always(None),
        "ArrayResultTool": _always(["first", "second"]),
    }
    defaults.update(overrides)
    tools: dict[str, Any] = {tool.name: tool for tool in TOOLKIT.tools.values()}
    return [tools[name].handler(fn) for name, fn in defaults.items()]


class Recorded(TypedDict):
    reported: list[fx.Cause[object]]
    logged: list[fx.Cause[object]]


def _toolkit_client(
    **overrides: Any,
) -> fx.Effect[tuple[Any, Recorded], Any, Any]:
    """A stdio client of the toolkit (Effect's ``makeToolkitTestClient``,
    initialized on an unsupported version so the first protocol is used)."""
    recorded: Recorded = {"reported": [], "logged": []}

    def log(options: L.Options) -> None:
        if options.log_level == L.LogLevel.ERROR:
            recorded["logged"].append(options.cause)

    observed = layer.merge(
        L.layer([L.Logger.make(log)]),
        error_reporter.layer(
            [error_reporter.make(lambda report: recorded["reported"].append(report.cause))]
        ),
    )
    registration = M.register_toolkit(TOOLKIT).pipe(
        fx.provide(TOOLKIT.to_layer(*_handlers(**overrides)))
    )

    @fx.gen
    def run():
        harness = yield from stdio_harness(P.v2025_06_18, None, registration)
        yield from harness.send_request(
            "initialize",
            {
                "protocolVersion": "9999-01-01",
                "capabilities": {},
                "clientInfo": {"name": "TestClient", "version": "1.0.0"},
            },
        )
        return harness, recorded

    return run.pipe(fx.provide(observed))


def _call(harness: Any, name: str, arguments: MS.JsonObject | None = None) -> fx.Effect[Any]:
    params: MS.JsonObject = {"name": name}
    if arguments is not None:
        params["arguments"] = arguments
    return harness.send_request("tools/call", params)


@testing.effect
def test_returns_concise_parameter_validation_errors_without_invoking_the_handler():
    """McpServer / registerToolkit / returns concise parameter-validation errors without invoking the handler"""  # noqa: E501
    invoked: list[bool] = []

    def handle(p: OptionalSignature, _: object) -> fx.Effect[str]:
        invoked.append(True)
        return fx.succeed(p.get("signature", "omitted"))

    harness, recorded = yield from _toolkit_client(OptionalStringTool=handle)
    reply = yield from _call(harness, "OptionalStringTool", {"signature": None})
    error = reply["error"]
    assert invoked == []
    assert error["code"] == MS.INVALID_PARAMS_ERROR_CODE
    assert "Invalid parameters for tool 'OptionalStringTool'" in error["message"]
    # Effect's ``Schema.optional`` admits ``undefined`` ("Expected string | undefined");
    # a ``NotRequired`` key is its ``optionalKey``, which Python's ``None`` cannot reach.
    assert "Expected string\n" in error["message"]
    assert 'at ["signature"]' in error["message"]
    [reported] = recorded["reported"]
    assert reported.has_fails
    squashed = reported.squash()
    assert isinstance(squashed, MS.McpError)
    assert squashed.code == MS.INVALID_PARAMS_ERROR_CODE
    assert str(squashed) == error["message"]


@testing.effect
def test_preserves_successful_results_when_optional_parameters_are_omitted():
    """McpServer / registerToolkit / preserves successful results when optional parameters are omitted"""  # noqa: E501
    invoked: list[bool] = []

    def handle(p: OptionalSignature, _: object) -> fx.Effect[str]:
        invoked.append(True)
        return fx.succeed(p.get("signature", "omitted"))

    harness, _ = yield from _toolkit_client(OptionalStringTool=handle)
    reply = yield from _call(harness, "OptionalStringTool", {})
    assert invoked == [True]
    assert reply["result"] == {"isError": False, "content": [{"type": "text", "text": "omitted"}]}


@testing.effect
def test_omits_structured_content_for_null_and_array_tool_results():
    """McpServer / registerToolkit / omits structured content for null and array tool results"""
    harness, _ = yield from _toolkit_client()
    null_result = (yield from _call(harness, "NullableResultTool", {}))["result"]
    assert "structuredContent" not in null_result
    assert null_result["content"] == [{"type": "text", "text": "null"}]
    array_result = (yield from _call(harness, "ArrayResultTool", {}))["result"]
    assert "structuredContent" not in array_result
    assert array_result["content"] == [{"type": "text", "text": '["first","second"]'}]


class NoteNotFound(S.TaggedError):
    id: str


class NoteParams(TypedDict):
    id: str


@testing.effect
def test_encodes_declared_error_failures_without_a_message():
    """McpServer / registerToolkit / encodes declared Error failures without a message"""
    get_note = T.make("GetNote", parameters=S.Struct(NoteParams), failure=NoteNotFound)
    server, exit = yield from _register(
        K.make(get_note), get_note.handler(lambda p, _: fx.fail(NoteNotFound(id=p["id"])))
    )
    assert isinstance(exit, fx.Success)
    result = yield from _direct(server.call_tool({"name": "GetNote", "arguments": {"id": "n1"}}))
    assert result.get("isError") is True
    assert "structuredContent" not in result
    assert _text(result) == '{"_tag":"NoteNotFound","id":"n1"}'


class VaultLocked(S.TaggedError):
    vault: str
    token: Redacted[str] = S.field(S.Redacted(S.String))


@testing.effect
def test_a_declared_failure_without_a_message_sends_its_json_codec_fields():
    """(pyfect) arpc_mcp_docs_gaps: a declared failure with no message is sent with its
    fields through its schema's JSON codec, as in Effect 4.1.2, which writes a
    ``Redacted`` field's value: a secret must not be in a declared failure."""
    vault = T.make("Vault", failure=VaultLocked)
    secret = "tok-hunter2"
    server, exit = yield from _register(
        K.make(vault),
        vault.handler(
            lambda _p, _: fx.fail(VaultLocked(vault="main", token=redacted.make(secret)))
        ),
    )
    assert isinstance(exit, fx.Success)
    result = yield from _direct(server.call_tool({"name": "Vault", "arguments": {}}))
    assert result.get("isError") is True
    assert json.loads(_text(result)) == {"_tag": "VaultLocked", "vault": "main", "token": secret}


@testing.effect
def test_scrubs_and_records_serialization_failures_in_declared_non_error_failures():
    """McpServer / registerToolkit / scrubs and records serialization failures in declared non-Error failures"""  # noqa: E501
    harness, recorded = yield from _toolkit_client(
        StructuredFailureTool=_failing(
            {"reason": "busy", "retryAfter": 5.0, "detail": Unserializable()}
        )
    )
    result = (yield from _call(harness, "StructuredFailureTool"))["result"]
    assert result["isError"] is True
    assert "structuredContent" not in result
    assert result["content"] == [{"type": "text", "text": M.INTERNAL_TOOL_ERROR_MESSAGE}]
    [reported] = recorded["reported"]
    error = reported.squash()
    assert isinstance(error, AiErr.AiError)
    assert isinstance(error.reason, AiErr.ToolResultEncodingError)
    [logged] = recorded["logged"]
    assert logged.squash() is reported.squash()


ORIGIN_CASES = [
    ("handler", "error"),
    ("handler", "return"),
    ("ToolResultEncodingError", "error"),
    ("InvalidToolResultError", "return"),
]


class ShortAnswer(TypedDict):
    answer: str


@pytest.mark.parametrize(("origin", "failure_mode"), ORIGIN_CASES)
@testing.effect
def test_distinguishes_failures_from_decoding_failures(origin: str, failure_mode: Any):
    """McpServer / registerToolkit / distinguishes ${origin} failures from decoding failures in ${failureMode} mode"""  # noqa: E501
    received: list[str] = []
    reported: list[fx.Cause[object]] = []
    logged: list[fx.Cause[object]] = []
    failure = AiErr.make(
        module="Toolkit",
        method="NestedTool.handle",
        reason=AiErr.ToolParameterValidationError(
            tool_name="NestedTool", description="Nested arguments failed validation"
        ),
    )
    tool = T.make(
        "OriginTool",
        parameters=S.Struct(Value),
        success=S.Struct(ShortAnswer, answer=S.String.check(S.is_min_length(10))),
        failure=AiErr.AiError,
        failure_mode=failure_mode,
    )

    def handle(params: Value, _: object) -> fx.Effect[Any, Any]:
        received.append(params["value"])
        if origin == "handler":
            return fx.fail(failure)
        if origin == "ToolResultEncodingError":
            return fx.succeed({"answer": "short"})
        decode = S.decode_unknown_effect(S.Struct(ShortAnswer))
        return cast("Any", decode)({"privateDetail": "invalid"}).flat_map(fx.die)

    def log(options: L.Options) -> None:
        if options.log_level == L.LogLevel.ERROR:
            logged.append(options.cause)

    kit = K.make(tool)
    server = yield from M.make()
    yield from (
        M.register_toolkit(kit)
        .pipe(fx.provide_service(M.McpServer, server))
        .pipe(fx.provide(kit.to_layer(tool.handler(cast("Any", handle)))))
        .pipe(
            fx.provide(
                error_reporter.layer([error_reporter.make(lambda r: reported.append(r.cause))])
            )
        )
        .pipe(fx.provide(L.layer([L.Logger.make(log)])))
    )
    result = yield from _direct(
        server.call_tool({"name": "OriginTool", "arguments": {"value": "valid"}})
    )
    assert received == ["valid"]
    assert result.get("isError") is True
    assert "structuredContent" not in result
    if origin == "handler":
        expected = (
            str(failure)
            if failure_mode == "error"
            else json.dumps(
                (yield from S.encode_effect(AiErr.AiError)(failure)),
                separators=(",", ":"),
            )
        )
        assert _text(result) == expected
        assert reported == []
        assert logged == []
    else:
        assert _text(result) == M.INTERNAL_TOOL_ERROR_MESSAGE
        [cause] = reported
        error = cause.squash()
        assert isinstance(error, AiErr.AiError)
        assert type(error.reason).__name__ == origin
        assert len(logged) == 1


@testing.effect
def test_returns_a_generic_message_for_non_validation_ai_error_failures():
    """McpServer / registerToolkit / returns a generic message for non-validation AiError failures"""  # noqa: E501
    harness, recorded = yield from _toolkit_client()
    result = (yield from _call(harness, "InternalAiErrorTool", {}))["result"]
    assert result["isError"] is True
    assert _text(result) == M.INTERNAL_TOOL_ERROR_MESSAGE
    [reported] = recorded["reported"]
    assert reported.has_fails
    assert reported.squash() is INTERNAL_AI_ERROR
    [logged] = recorded["logged"]
    assert logged.squash() is INTERNAL_AI_ERROR


@testing.effect
def test_reports_response_serialization_failures_before_a_generic_message():
    """McpServer / registerToolkit / reports response serialization failures before returning a generic message"""  # noqa: E501
    harness, recorded = yield from _toolkit_client()
    result = (yield from _call(harness, "UnserializableResultTool", {}))["result"]
    assert result["isError"] is True
    assert _text(result) == M.INTERNAL_TOOL_ERROR_MESSAGE
    [reported] = recorded["reported"]
    error = reported.squash()
    assert isinstance(error, AiErr.AiError)
    assert isinstance(error.reason, AiErr.ToolResultEncodingError)


@testing.effect
def test_logs_handler_defects_without_reporting_when_reporters_are_off():
    """McpServer / registerToolkit / logs handler defects with reportErrors=${reportErrors} and scrubs the client message"""  # noqa: E501
    defect = RuntimeError("private defect details")
    logged: list[fx.Cause[object]] = []
    defect_tool = T.make("DefectTool", success=S.String)
    kit = K.make(defect_tool)

    def log(options: L.Options) -> None:
        if options.log_level == L.LogLevel.ERROR:
            logged.append(options.cause)

    server = yield from M.make()
    yield from (
        M.register_toolkit(kit)
        .pipe(fx.provide_service(M.McpServer, server))
        .pipe(fx.provide(kit.to_layer(defect_tool.handler(lambda _, __: fx.die(defect)))))
        .pipe(fx.provide(error_reporter.layer([])))
        .pipe(fx.provide(L.layer([L.Logger.make(log)])))
    )
    result = yield from _direct(server.call_tool({"name": "DefectTool", "arguments": {}}))
    assert result.get("isError") is True
    assert _text(result) == M.INTERNAL_TOOL_ERROR_MESSAGE
    assert "structuredContent" not in result
    [cause] = logged
    assert cause.has_dies
    assert cause.squash() is defect
