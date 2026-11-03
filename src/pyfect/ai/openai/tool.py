"""OpenAI's provider-defined tools (Effect's ``OpenAiTool``).

Each constant is a tool's constructor: call it with the tool's arguments
to put it in a toolkit. Tools OpenAI runs (code interpreter, file search,
image generation, MCP, web search) need no handler; apply patch, shell and
local shell run on your side, so they do::

    kit = toolkit.make(tool.WebSearch(search_context_size="low"), tool.Shell())

Arguments, parameters and results use OpenAI's snake_case JSON, with the
fields of the generated schemas (``pyfect.ai.openai.generated``).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Literal, NotRequired, TypedDict, cast

from pyfect import schema as S
from pyfect.ai import tool as T
from pyfect.ai.openai import generated as G
from pyfect.ai.openai._generated_support import struct
from pyfect.ai.openai.generated import types as GT
from pyfect.schema import ast
from pyfect.schema._struct import StructSchema


def _pick[TD](
    _type: type[TD], source: StructSchema[Any, Any, Any], *keys: str, **extra: S.Top
) -> S.Codec[TD, Any, Any, Any]:
    """A struct of ``source``'s fields named ``keys`` (each optional as it
    is there) and the ``extra`` ones (Effect's ``Schema.Struct({ key:
    Generated.X.fields.key })``)."""
    node = cast("ast.Objects", source.ast)
    optional = {p.name for p in node.properties if p.optional}
    fields: dict[str, Any] = {key: source.fields[key] for key in keys}
    fields.update(extra)
    picked = tuple(key for key in keys if key in optional)
    return cast("S.Codec[TD, Any, Any, Any]", struct(None, fields, picked))


def _not_completed(schema: object) -> S.Top:
    """``schema``'s literals but ``completed``."""
    literals: tuple[Any, ...] = cast("Any", schema).literals
    return S.Literals([status for status in literals if status != "completed"])


_COMPLETED = S.Literal("completed")

# Effect leaves these tools' parameters as ``Schema.Void``, which accepts
# whatever the response carries (``{}``); ``S.Null`` would reject it.
_NO_PARAMETERS = S.Unknown

# Apply patch -------------------------------------------------------------------------------


class ApplyPatchParameters(TypedDict):
    call_id: str
    operation: (
        GT.ApplyPatchCreateFileOperation
        | GT.ApplyPatchDeleteFileOperation
        | GT.ApplyPatchUpdateFileOperation
    )


class ApplyPatchResult(TypedDict):
    status: GT.ApplyPatchCallOutputStatus
    output: NotRequired[str | None]


ApplyPatch = T.provider_defined(
    id="openai.apply_patch",
    custom_name="OpenAiApplyPatch",
    provider_name="apply_patch",
    requires_handler=True,
    parameters=_pick(ApplyPatchParameters, G.ApplyPatchToolCall, "call_id", "operation"),
    success=_pick(ApplyPatchResult, G.ApplyPatchToolCallOutput, "status", "output"),
)

# Code interpreter --------------------------------------------------------------------------


class CodeInterpreterArgs(TypedDict):
    container: str | GT.AutoCodeInterpreterToolParam


class CodeInterpreterParameters(TypedDict):
    code: str | None
    container_id: str


type _CodeInterpreterOutputs = (
    Sequence[GT.CodeInterpreterOutputLogs | GT.CodeInterpreterOutputImage] | None
)


class CodeInterpreterSuccess(TypedDict):
    status: Literal["completed"]
    outputs: _CodeInterpreterOutputs


class CodeInterpreterFailure(TypedDict):
    status: Literal["in_progress", "incomplete", "interpreting", "failed"]
    outputs: _CodeInterpreterOutputs


_CODE_CALL = G.CodeInterpreterToolCall

CodeInterpreter = T.provider_defined(
    id="openai.code_interpreter",
    custom_name="OpenAiCodeInterpreter",
    provider_name="code_interpreter",
    args=_pick(CodeInterpreterArgs, G.CodeInterpreterTool, "container"),
    parameters=_pick(CodeInterpreterParameters, _CODE_CALL, "code", "container_id"),
    success=_pick(CodeInterpreterSuccess, _CODE_CALL, "outputs", status=_COMPLETED),
    failure=_pick(
        CodeInterpreterFailure,
        _CODE_CALL,
        "outputs",
        status=_not_completed(_CODE_CALL.fields["status"]),
    ),
)

# File search -------------------------------------------------------------------------------


class FileSearchArgs(TypedDict):
    vector_store_ids: Sequence[str]
    filters: NotRequired[GT.Filters | None]
    max_num_results: NotRequired[float]
    ranking_options: NotRequired[GT.RankingOptions]


type _FileSearchResults = Sequence[GT.FileSearchToolCall__results__0__item] | None


class FileSearchSuccess(TypedDict):
    status: Literal["completed"]
    queries: Sequence[str]
    results: _FileSearchResults


class FileSearchFailure(TypedDict):
    status: Literal["in_progress", "searching", "incomplete", "failed"]
    queries: Sequence[str]
    results: _FileSearchResults


_FILE_CALL = G.FileSearchToolCall
_FILE_RESULTS = _FILE_CALL.fields["results"]

FileSearch = T.provider_defined(
    id="openai.file_search",
    custom_name="OpenAiFileSearch",
    provider_name="file_search",
    args=_pick(
        FileSearchArgs,
        G.FileSearchTool,
        "filters",
        "max_num_results",
        "ranking_options",
        "vector_store_ids",
    ),
    parameters=_NO_PARAMETERS,
    success=_pick(
        FileSearchSuccess, _FILE_CALL, "queries", status=_COMPLETED, results=_FILE_RESULTS
    ),
    failure=_pick(
        FileSearchFailure,
        _FILE_CALL,
        "queries",
        status=_not_completed(_FILE_CALL.fields["status"]),
        results=_FILE_RESULTS,
    ),
)

# Image generation --------------------------------------------------------------------------


class ImageGenerationSuccess(TypedDict):
    result: str | None


class ImageGenerationFailure(TypedDict):
    status: Literal["in_progress", "generating", "failed"]
    result: str | None


_IMAGE_CALL = G.ImageGenToolCall

ImageGeneration = T.provider_defined(
    id="openai.image_generation",
    custom_name="OpenAiImageGeneration",
    provider_name="image_generation",
    args=_pick(
        dict[str, object],
        G.ImageGenTool,
        "background",
        "input_fidelity",
        "input_image_mask",
        "model",
        "moderation",
        "output_compression",
        "output_format",
        "partial_images",
        "quality",
        "size",
    ),
    parameters=_NO_PARAMETERS,
    success=_pick(ImageGenerationSuccess, _IMAGE_CALL, "result"),
    failure=_pick(
        ImageGenerationFailure,
        _IMAGE_CALL,
        "result",
        status=_not_completed(_IMAGE_CALL.fields["status"]),
    ),
)

# Local shell -------------------------------------------------------------------------------


class LocalShellParameters(TypedDict):
    action: GT.LocalShellExecAction


class LocalShellResult(TypedDict):
    output: str


LocalShell = T.provider_defined(
    id="openai.local_shell",
    custom_name="OpenAiLocalShell",
    provider_name="local_shell",
    requires_handler=True,
    parameters=_pick(LocalShellParameters, G.LocalShellToolCall, "action"),
    success=_pick(LocalShellResult, G.LocalShellToolCallOutput, "output"),
)

# MCP ---------------------------------------------------------------------------------------


class McpSuccess(TypedDict):
    type: Literal["mcp_call"]
    name: str
    arguments: str
    output: NotRequired[str | None]
    server_label: str


class McpFailure(McpSuccess):
    error: str


_MCP_RESULT = ("type", "name", "arguments", "output", "server_label")

Mcp = T.provider_defined(
    id="openai.mcp",
    custom_name="OpenAiMcp",
    provider_name="mcp",
    args=_pick(
        dict[str, object],
        G.MCPTool,
        "allowed_tools",
        "authorization",
        "connector_id",
        "require_approval",
        "server_description",
        "server_label",
        "server_url",
    ),
    parameters=S.Unknown,
    success=_pick(McpSuccess, G.MCPToolCall, *_MCP_RESULT),
    failure=_pick(McpFailure, G.MCPToolCall, *_MCP_RESULT, error=S.String),
)

# Shell -------------------------------------------------------------------------------------


class ShellParameters(TypedDict):
    action: GT.FunctionShellAction


class ShellResult(TypedDict):
    output: Sequence[GT.FunctionShellCallOutputContent]


Shell = T.provider_defined(
    id="openai.shell",
    custom_name="OpenAiShell",
    provider_name="shell",
    requires_handler=True,
    parameters=_pick(ShellParameters, G.FunctionShellCall, "action"),
    success=_pick(ShellResult, G.FunctionShellCallOutput, "output"),
)

# Web search --------------------------------------------------------------------------------

type _WebSearchAction = (
    GT.WebSearchActionSearch | GT.WebSearchActionOpenPage | GT.WebSearchActionFind
)


class WebSearchParameters(TypedDict):
    action: NotRequired[_WebSearchAction]


class WebSearchSuccess(TypedDict):
    action: NotRequired[_WebSearchAction]
    status: Literal["completed"]


class WebSearchFailure(TypedDict):
    action: NotRequired[_WebSearchAction]
    status: Literal["in_progress", "searching", "failed", "incomplete"]


_WEB_CALL = G.WebSearchToolCall
_WEB_SUCCESS = _pick(WebSearchSuccess, _WEB_CALL, "action", status=_COMPLETED)
_WEB_FAILURE = _pick(
    WebSearchFailure, _WEB_CALL, "action", status=_not_completed(G.WebSearchCallStatus)
)

WebSearch = T.provider_defined(
    id="openai.web_search",
    custom_name="OpenAiWebSearch",
    provider_name="web_search",
    args=_pick(
        dict[str, object], G.WebSearchTool, "filters", "user_location", "search_context_size"
    ),
    parameters=_pick(WebSearchParameters, _WEB_CALL, "action"),
    success=_WEB_SUCCESS,
    failure=_WEB_FAILURE,
)

WebSearchPreview = T.provider_defined(
    id="openai.web_search_preview",
    custom_name="OpenAiWebSearchPreview",
    provider_name="web_search_preview",
    args=_pick(dict[str, object], G.WebSearchPreviewTool, "user_location", "search_context_size"),
    parameters=_NO_PARAMETERS,
    success=_WEB_SUCCESS,
    failure=_WEB_FAILURE,
)

NAMES = frozenset(
    {
        "OpenAiApplyPatch",
        "OpenAiCodeInterpreter",
        "OpenAiFileSearch",
        "OpenAiImageGeneration",
        "OpenAiLocalShell",
        "OpenAiMcp",
        "OpenAiShell",
        "OpenAiWebSearch",
        "OpenAiWebSearchPreview",
    }
)
"""The custom names of OpenAI's provider-defined tools."""

__all__ = [
    "NAMES",
    "ApplyPatch",
    "ApplyPatchParameters",
    "ApplyPatchResult",
    "CodeInterpreter",
    "CodeInterpreterArgs",
    "CodeInterpreterFailure",
    "CodeInterpreterParameters",
    "CodeInterpreterSuccess",
    "FileSearch",
    "FileSearchArgs",
    "FileSearchFailure",
    "FileSearchSuccess",
    "ImageGeneration",
    "ImageGenerationFailure",
    "ImageGenerationSuccess",
    "LocalShell",
    "LocalShellParameters",
    "LocalShellResult",
    "Mcp",
    "McpFailure",
    "McpSuccess",
    "Shell",
    "ShellParameters",
    "ShellResult",
    "WebSearch",
    "WebSearchFailure",
    "WebSearchParameters",
    "WebSearchPreview",
    "WebSearchSuccess",
]
