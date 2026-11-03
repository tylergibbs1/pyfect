"""Tools, tool choice and response format of a Responses API request
(Effect's ``prepareTools`` and ``prepareResponseFormat``). Provider-defined
tools are sent as OpenAI's own tool types with their decoded arguments;
the others as functions, strict unless the tool or ``strict_json_schema``
says otherwise."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from pyfect import schema as S
from pyfect.ai import _provider as P
from pyfect.ai import _provider_tools as PT
from pyfect.ai import language_model as lm
from pyfect.ai import tool as T
from pyfect.ai.ai_error import InvalidRequestError, ToolConfigurationError, describe_schema_error
from pyfect.ai.openai._prompt import MODULE, AnyProviderDefined, Item
from pyfect.ai.tool import NameMapper

_TYPES = {
    "OpenAiApplyPatch": "apply_patch",
    "OpenAiCodeInterpreter": "code_interpreter",
    "OpenAiFileSearch": "file_search",
    "OpenAiImageGeneration": "image_generation",
    "OpenAiLocalShell": "local_shell",
    "OpenAiMcp": "mcp",
    "OpenAiShell": "shell",
    "OpenAiWebSearch": "web_search",
    "OpenAiWebSearchPreview": "web_search_preview",
}
_WITHOUT_ARGS = frozenset({"OpenAiApplyPatch", "OpenAiLocalShell", "OpenAiShell"})


@dataclass(frozen=True)
class Tools:
    tools: list[Item] | None
    tool_choice: Any


def _provider_defined(tool: AnyProviderDefined) -> Item:
    kind = _TYPES.get(tool.name)
    if kind is None:
        raise PT.unsupported(
            MODULE,
            "prepareTools",
            InvalidRequestError(description=f"Unknown provider-defined tool '{tool.name}'"),
        )
    if tool.name in _WITHOUT_ARGS:
        return {"type": kind}
    try:
        args = P.wire_parse_sync(tool.args_schema, object)(tool.args)
    except S.SchemaError as error:
        raise PT.unsupported(
            MODULE,
            "prepareTools",
            ToolConfigurationError(tool_name=tool.name, description=describe_schema_error(error)),
        ) from error
    return {**P.obj(args), "type": kind}


def _function(tool: T.AnyTool, config: Mapping[str, Any]) -> Item:
    mode = T.get_strict_mode(tool)
    default = config.get("strict_json_schema")
    strict = mode if mode is not None else (default if default is not None else True)
    item: Item = {
        "type": "function",
        "name": tool.name,
        "parameters": PT.tool_json_schema(MODULE, tool, require_object=True),
        "strict": strict,
    }
    description = T.get_description(tool)
    if description is not None:
        item["description"] = description
    return item


def prepare_tools(
    config: Mapping[str, Any], options: lm.ProviderOptions, names: NameMapper
) -> Tools:
    """Raises ``UnsupportedInput`` for a tool the API cannot take."""
    if not options.tools:
        return Tools(None, None)
    choice = options.tool_choice
    allowed = options.tools
    tool_choice: Any = None
    # OpenAI's provider-defined tools have no name to allow them by, so
    # the toolkit is narrowed here.
    if isinstance(choice, dict) and "one_of" in choice:
        allowed_names = set(choice["one_of"])
        allowed = [tool for tool in options.tools if tool.name in allowed_names]
        tool_choice = "required" if choice.get("mode") == "required" else "auto"
    tools = [
        _provider_defined(tool) if isinstance(tool, T.ProviderDefined) else _function(tool, config)
        for tool in allowed
    ]
    if isinstance(choice, str):
        tool_choice = choice
    elif "tool" in choice:
        provider_name = names.get_provider_name(choice["tool"])
        if provider_name in names.provider_names:
            tool_choice = {"type": provider_name}
        else:
            tool_choice = {"type": "function", "name": choice["tool"]}
    return Tools(tools, tool_choice)


def prepare_response_format(config: Mapping[str, Any], options: lm.ProviderOptions) -> Item:
    """Raises ``UnsupportedInput`` for a schema without a JSON Schema."""
    response_format = options.response_format
    if not isinstance(response_format, lm.JsonFormat):
        return {"type": "text"}
    strict = config.get("strict_json_schema")
    return {
        "type": "json_schema",
        "name": response_format.object_name,
        "description": P.or_default(
            PT.schema_description(response_format.schema), "Response with a JSON object"
        ),
        "schema": PT.json_schema(MODULE, response_format.schema, "prepareResponseFormat"),
        "strict": strict if strict is not None else True,
    }
