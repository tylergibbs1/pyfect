"""``mcp_client.toolkit``: an MCP server's tools bound as a ``Toolkit``
(Effect's ``McpClient.toolkit``, ``RemoteTool`` and ``ToolDescriptor``)."""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING, Any, Literal, Never, cast, overload

from pyfect import _json_text
from pyfect import schema as S
from pyfect._core import Effect
from pyfect._js import or_default
from pyfect.ai import tool as Tool
from pyfect.ai import toolkit as Toolkit
from pyfect.ai._mcp.client_wire import failure, resource_link_text, to_text
from pyfect.ai.mcp_client_error import (
    MCP_CLIENT_ERROR,
    ConfigurationError,
    McpClientError,
    ToolError,
    ValidationError,
)
from pyfect.ai.mcp_schema import CALL_TOOL_RESULT, CallToolResult
from pyfect.ai.mcp_schema import Tool as McpTool
from pyfect.ai.prompt import FilePart, TextPart, ToolModelOutputPart
from pyfect.context import Context, Tag
from pyfect.duration import Duration
from pyfect.effect import fail, gen, provide_context, succeed

if TYPE_CHECKING:
    from pyfect.ai.mcp_client import McpClientService

_MODEL_TOOL_NAME = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")
_ARGUMENTS = S.Record(S.String, S.Unknown)

type ResultMode = Literal["text", "complete"]

type RemoteTool[SS = str, HE = McpClientError, RR = Never] = Tool.Tool[
    Any, object, SS, McpClientError, HE, RR
]
"""A tool bound to a remote MCP tool (Effect's ``RemoteTool``): its success
``SS`` is ``str`` (``result_mode="text"``) or ``CallToolResult``
(``"complete"``), its failure ``McpClientError``, raised (``HE`` =
``McpClientError``, ``failure_mode="error"``) or returned to the model
(``HE`` = ``Never``, ``"return"``), and ``RR`` what ``transform_tool``
added to its handler's requirements."""


class ToolDescriptor(Tag[McpTool], key="effect/ai/McpClient/ToolDescriptor"):
    """The annotation holding the remote descriptor a tool is bound to. The
    server wrote it: treat it as untrusted."""


type _Transform = Callable[[Any, McpTool], Tool.AnyTool]


@overload
def toolkit[RR = Never](
    client: McpClientService,
    prefix: str = "",
    *,
    tools: Sequence[McpTool] | None = None,
    result_mode: Literal["text"] = "text",
    failure_mode: Literal["error"] = "error",
    trust_annotations: bool = False,
    timeout: Duration | None = None,
    transform_tool: Callable[
        [RemoteTool[str, McpClientError], McpTool], RemoteTool[str, McpClientError, RR]
    ]
    | None = None,
) -> Effect[Toolkit.WithHandler[Any, Any, McpClientError, RR], McpClientError]: ...
@overload
def toolkit[RR = Never](
    client: McpClientService,
    prefix: str = "",
    *,
    tools: Sequence[McpTool] | None = None,
    result_mode: Literal["text"] = "text",
    failure_mode: Literal["return"],
    trust_annotations: bool = False,
    timeout: Duration | None = None,
    transform_tool: Callable[[RemoteTool[str, Never], McpTool], RemoteTool[str, Never, RR]]
    | None = None,
) -> Effect[Toolkit.WithHandler[Any, Any, Never, RR], McpClientError]: ...
@overload
def toolkit[RR = Never](
    client: McpClientService,
    prefix: str = "",
    *,
    tools: Sequence[McpTool] | None = None,
    result_mode: Literal["complete"],
    failure_mode: Literal["error"] = "error",
    trust_annotations: bool = False,
    timeout: Duration | None = None,
    transform_tool: Callable[
        [RemoteTool[CallToolResult, McpClientError], McpTool],
        RemoteTool[CallToolResult, McpClientError, RR],
    ]
    | None = None,
) -> Effect[Toolkit.WithHandler[Any, Any, McpClientError, RR], McpClientError]: ...
@overload
def toolkit[RR = Never](
    client: McpClientService,
    prefix: str = "",
    *,
    tools: Sequence[McpTool] | None = None,
    result_mode: Literal["complete"],
    failure_mode: Literal["return"],
    trust_annotations: bool = False,
    timeout: Duration | None = None,
    transform_tool: Callable[
        [RemoteTool[CallToolResult, Never], McpTool], RemoteTool[CallToolResult, Never, RR]
    ]
    | None = None,
) -> Effect[Toolkit.WithHandler[Any, Any, Never, RR], McpClientError]: ...
def toolkit(
    client: McpClientService,
    prefix: str = "",
    *,
    tools: Sequence[McpTool] | None = None,
    result_mode: ResultMode = "text",
    failure_mode: Tool.FailureMode = "error",
    trust_annotations: bool = False,
    timeout: Duration | None = None,
    transform_tool: _Transform | None = None,
) -> Effect[Toolkit.WithHandler[Any, Any, Any, Any], McpClientError]:
    """The server's tools (or the approved snapshot ``tools``, without
    listing) as a toolkit with handlers. A model tool's name is ``prefix``
    and the tool's name joined as they are (pass ``"docs__"``), 1 to 64
    letters, digits, ``_`` and ``-``. Remote JSON Schemas are sent as they
    are. Build a new toolkit to see remote changes.

    A result is its text (``result_mode="text"``), or the whole
    ``CallToolResult`` (``"complete"``), whose content the model gets as
    text and file parts. A tool error (``isError``) or a failed request
    fails the call (``failure_mode="error"``) or goes back to the model
    (``"return"``) as the ``McpClientError``; a ``ToolError`` keeps the
    result.

    ``timeout`` bounds each call. ``trust_annotations`` copies the server's
    hints into the tool's annotations (never its approval).
    ``transform_tool`` gets each annotated tool and its descriptor and
    returns a tool derived from it (``set_needs_approval``, ``annotate``,
    ``add_dependency``), keeping its name, schemas and failure mode."""
    complete = result_mode == "complete"

    @gen
    def run():
        descriptors: Sequence[McpTool] = (
            (yield from client.list_tools()) if tools is None else tools
        )
        bound: list[Tool.AnyTool] = []
        handlers: list[Tool.Handler[Any]] = []
        for descriptor in descriptors:
            name = f"{prefix}{descriptor['name']}"
            if _MODEL_TOOL_NAME.match(name) is None or any(t.name == name for t in bound):
                return (
                    yield from fail(
                        failure(
                            ConfigurationError(f"Invalid or duplicate MCP model tool name: {name}")
                        )
                    )
                )
            remote = _remote_tool(name, descriptor, complete, failure_mode, trust_annotations)
            bound.append(remote if transform_tool is None else transform_tool(remote, descriptor))
            handlers.append(remote.handler(_handler(client, descriptor, complete, timeout)))
        kit = Toolkit.make(*bound)
        context: Context[Any] = yield from kit.to_handlers(*handlers)
        built: Toolkit.WithHandler[Any, Any, Any, Any] = yield from cast(
            "Effect[Any, Never, Never]", kit
        ).pipe(provide_context(context))
        return built

    return run


def _remote_tool(
    name: str,
    descriptor: McpTool,
    complete: bool,
    failure_mode: Tool.FailureMode,
    trust_annotations: bool,
) -> Tool.AnyTool:
    remote: Tool.AnyTool = cast(
        "Tool.AnyTool",
        Tool.dynamic(
            cast("Any", name),
            parameters=cast("Any", descriptor["inputSchema"]),
            description=descriptor.get("description"),
            success=cast("Any", CALL_TOOL_RESULT if complete else S.String),
            failure=MCP_CLIENT_ERROR,
            failure_mode=cast("Any", failure_mode),
            to_model_output=cast("Any", to_model_output if complete else None),
        ),
    )
    remote = remote.annotate(Tool.Strict, False).annotate(ToolDescriptor, descriptor)
    hints = descriptor.get("annotations")
    if not trust_annotations or hints is None:
        return remote
    # A hint the server left out keeps the annotation's default, as in Effect.
    for hint, annotation in (
        ("readOnlyHint", Tool.Readonly),
        ("destructiveHint", Tool.Destructive),
        ("idempotentHint", Tool.Idempotent),
        ("openWorldHint", Tool.OpenWorld),
    ):
        value = hints.get(hint)
        if value is not None:
            remote = remote.annotate(annotation, cast("bool", value))
    title = hints.get("title")
    return remote if title is None else remote.annotate(Tool.Title, title)


def _handler(
    client: McpClientService, descriptor: McpTool, complete: bool, timeout: Duration | None
) -> Callable[[Any, Any], Effect[Any, McpClientError]]:
    decode_arguments = S.decode_unknown_effect(_ARGUMENTS)

    def finish(result: CallToolResult) -> Effect[Any, McpClientError]:
        if result.get("isError") is True:
            return fail(failure(ToolError(result)))
        return succeed(result) if complete else to_text(result)

    def handle(params: Any, _: Any) -> Effect[Any, McpClientError]:
        return (
            decode_arguments(params)
            .map_error(
                lambda cause: failure(
                    ValidationError("MCP tool arguments must be a JSON object", cause)
                )
            )
            .flat_map(lambda arguments: client.call_tool(descriptor, arguments, timeout=timeout))
            .flat_map(finish)
        )

    return handle


def to_model_output(result: CallToolResult) -> list[ToolModelOutputPart]:
    """A complete result as the model sees it: text parts for text, resource
    links and text resources, file parts for images, audio and blobs; the
    JSON of ``structuredContent`` when that gives no part."""
    parts: list[ToolModelOutputPart] = []
    for block in result["content"]:
        match block["type"]:
            case "text":
                parts.append(TextPart(text=block["text"]))
            case "image" | "audio":
                parts.append(FilePart(media_type=block["mimeType"], data=block["data"]))
            case "resource_link":
                parts.append(TextPart(text=resource_link_text(block)))
            case "resource":
                resource: dict[str, Any] = cast("Any", block["resource"])
                if "text" in resource:
                    parts.append(TextPart(text=resource["text"]))
                else:
                    media_type = or_default(resource.get("mimeType"), "application/octet-stream")
                    parts.append(FilePart(media_type=media_type, data=resource["blob"]))
    if not parts and "structuredContent" in result:
        parts.append(TextPart(text=_json_text.stringify(result["structuredContent"])))
    return parts


__all__: Sequence[str] = ()
