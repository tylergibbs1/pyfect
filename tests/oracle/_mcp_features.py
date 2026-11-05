"""Effect's ``makeFeaturesServerLayer`` (McpConformanceFixtures.ts), with the
parts the multi round-trip, parameter-header and request-mode titles read, as
a ``Conformance`` over its own server."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

import pyfect as fx
from pyfect.ai import mcp_protocol as P
from pyfect.ai import mcp_schema as MS
from pyfect.ai import mcp_server as M
from pyfect.ai._mcp.core import PromptEntry, ToolEntry
from pyfect.context import Context
from pyfect.scope import Scope

from ._mcp_http import Conformance, Json, Mode, http_harness, server_layer

MRTR_TOOL = "MrtrTool"
MRTR_STATE_ONLY_TOOL = "MrtrStateOnlyTool"
MRTR_INVALID_STATE_TOOL = "MrtrInvalidStateTool"
MRTR_SAMPLING_TOOLS_TOOL = "MrtrSamplingToolsTool"
MRTR_SAMPLING_TOOL_CHOICE_TOOL = "MrtrSamplingToolChoiceTool"
MRTR_PROMPT = "MrtrPrompt"
MRTR_REQUEST_STATE = "opaque:+/=\u0000é"

APPROVAL_REQUEST: Any = {
    "method": "elicitation/create",
    "params": {
        "message": "Approve the operation",
        "requestedSchema": {
            "type": "object",
            "properties": {
                "approved": {"type": "boolean"},
                "color": {"type": "string", "enum": ["red", "blue"]},
                "titled": {
                    "type": "string",
                    "oneOf": [{"const": "red", "title": "Red"}, {"const": "blue", "title": "Blue"}],
                },
                "legacy": {"type": "string", "enum": ["red", "blue"], "enumNames": ["Red", "Blue"]},
            },
            "required": ["approved"],
        },
    },
}
SAMPLE_REQUEST: Any = {
    "method": "sampling/createMessage",
    "params": {
        "messages": [{"role": "user", "content": {"type": "text", "text": "Suggest a title"}}],
        "maxTokens": 20,
    },
}
USER_CONTEXT_REQUEST: Any = {
    "method": "elicitation/create",
    "params": {
        "message": "What context should the prompt use?",
        "requestedSchema": {
            "type": "object",
            "properties": {"context": {"type": "string"}},
            "required": ["context"],
        },
    },
}
_WEATHER_MESSAGE: Json = {"role": "user", "content": {"type": "text", "text": "Check the weather"}}

_MODERN: Context[Any] = Context.make(
    MS.EnabledWhen, lambda client: client.protocol_version == "2026-07-28"
)
_HEADER_TOOL_SCHEMA: Json = {
    "type": "object",
    "properties": {
        "region": {"type": "string", "x-mcp-header": "Region"},
        "shard": {"type": "integer", "x-mcp-header": "Shard"},
        "routing": {
            "type": "object",
            "properties": {"region": {"type": "string", "x-mcp-header": "Nested-Region"}},
        },
        "dryRun": {"type": "boolean", "x-mcp-header": "Dry-Run"},
    },
    "required": ["region"],
}


@dataclass
class Observations:
    tool_invocations: int = 0
    prompt_invocations: int = 0


def _add_tool(entry: ToolEntry) -> fx.Effect[None, Any, M.McpServer]:
    return M.McpServer().flat_map(lambda server: server.add_tool(entry))


def _mrtr_tool(_: object) -> fx.Effect[Any, Any, Any]:
    def decide(context: MS.RequestContext) -> Any:
        responses: Mapping[str, Any] = context.input_responses or {}
        approval = responses.get("approval")
        sample = responses.get("sample")
        roots = responses.get("roots")
        if (
            context.request_state == MRTR_REQUEST_STATE
            and approval is not None
            and approval.get("action") == "accept"
            and sample is not None
            and roots is not None
        ):
            text = json.dumps({"approval": approval["content"], "sample": sample, "roots": roots})
            return {"content": [{"type": "text", "text": text}]}
        return MS.InputRequired(
            input_requests={
                "approval": APPROVAL_REQUEST,
                "sample": SAMPLE_REQUEST,
                "roots": {"method": "roots/list"},
            },
            request_state=MRTR_REQUEST_STATE,
        )

    return MS.McpRequestContext().map(decide)


def _mrtr_prompt(_: object) -> fx.Effect[Any, Any, Any]:
    def decide(context: MS.RequestContext) -> Any:
        if (context.input_responses or {}).get("userContext") is None:
            return MS.InputRequired(
                input_requests={
                    "userContext": USER_CONTEXT_REQUEST,
                }
            )
        return {
            "messages": [{"role": "user", "content": {"type": "text", "text": "Prompt completed"}}]
        }

    return MS.McpRequestContext().map(decide)


def _sampling_tool(name: str, params: Json) -> fx.Effect[None, Any, M.McpServer]:
    request: Any = {"method": "sampling/createMessage", "params": params}
    outcome: Any = MS.InputRequired(input_requests={"sample": request})
    return _add_tool(
        ToolEntry(
            {"name": name, "inputSchema": {"type": "object"}},
            _MODERN,
            lambda _: fx.succeed(outcome),
        )
    )


def registrations(observations: Observations) -> fx.Effect[None, Any, M.McpServer]:
    """``makeHeaderToolLayer`` and ``mrtrToolLayer``, with the other kinds of
    registration the request-mode titles read."""

    def counted(_: object) -> fx.Effect[Any]:
        def count() -> Any:
            observations.tool_invocations += 1
            return {"content": []}

        return fx.sync(count)

    def echo_tool(arguments: Json | None) -> fx.Effect[Any]:
        observations.tool_invocations += 1
        text: Any = (arguments or {}).get("value", "")
        return fx.succeed({"content": [{"type": "text", "text": text}]})

    def test_prompt(_: object) -> fx.Effect[Any]:
        observations.prompt_invocations += 1
        message = {"role": "user", "content": {"type": "text", "text": "tested"}}
        return fx.succeed({"messages": [message]})

    @fx.gen
    def run():
        server = yield from M.McpServer()
        yield from _add_tool(
            ToolEntry(
                {
                    "name": "TestTool",
                    "description": "A test tool",
                    "inputSchema": {
                        "type": "object",
                        "properties": {"value": {"type": "string"}},
                        "required": ["value"],
                    },
                },
                Context.empty(),
                echo_tool,
            )
        )
        yield from _add_tool(
            ToolEntry({"name": "HeaderTool", "inputSchema": _HEADER_TOOL_SCHEMA}, _MODERN, counted)
        )
        yield from _add_tool(
            ToolEntry({"name": MRTR_TOOL, "inputSchema": {"type": "object"}}, _MODERN, _mrtr_tool)
        )
        state_only: Any = MS.InputRequired(request_state=MRTR_REQUEST_STATE)
        yield from _add_tool(
            ToolEntry(
                {"name": MRTR_STATE_ONLY_TOOL, "inputSchema": {"type": "object"}},
                _MODERN,
                lambda _: fx.succeed(state_only),
            )
        )
        yield from _add_tool(
            ToolEntry(
                {"name": MRTR_INVALID_STATE_TOOL, "inputSchema": {"type": "object"}},
                _MODERN,
                lambda _: fx.fail(MS.InvalidParams("requestState integrity check failed")),
            )
        )
        tools: Json = {"name": "weather", "inputSchema": {"type": "object"}}
        yield from _sampling_tool(
            MRTR_SAMPLING_TOOLS_TOOL,
            {"messages": [_WEATHER_MESSAGE], "maxTokens": 20, "tools": [tools]},
        )
        yield from _sampling_tool(
            MRTR_SAMPLING_TOOL_CHOICE_TOOL,
            {"messages": [_WEATHER_MESSAGE], "maxTokens": 20, "toolChoice": {"mode": "required"}},
        )
        yield from server.add_prompt(PromptEntry({"name": MRTR_PROMPT}, _MODERN, {}, _mrtr_prompt))
        yield from server.add_prompt(
            PromptEntry({"name": "TestPrompt"}, Context.empty(), {}, test_prompt)
        )
        yield from M.register_resource(
            uri="file:///test",
            name="TestResource",
            mime_type="text/plain",
            content=fx.succeed("test"),
        )

    return run


@dataclass
class FeaturesConformance(Conformance):
    """``McpConformance`` whose server is the features one."""

    observations: Observations = field(default_factory=Observations)

    @property
    def reset_observations(self) -> fx.Effect[None]:
        def reset() -> None:
            self.observations.tool_invocations = 0
            self.observations.prompt_invocations = 0

        return fx.sync(reset)


def features_conformance(
    protocol: P.AnyProtocolAdapter, mode: Mode = "server"
) -> fx.Effect[FeaturesConformance, Any, Scope]:
    observations = Observations()
    app = server_layer("McpConformance", (protocol,), registrations(observations), mode=mode)

    def build(harness: Any) -> FeaturesConformance:
        return FeaturesConformance(protocol, harness, observations)

    return http_harness(app).map(build)
