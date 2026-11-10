"""The tools and tool choice of an Anthropic request (Effect's
``prepareTools``)."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from pyfect.ai import _provider as P
from pyfect.ai import _provider_tools as PT
from pyfect.ai import language_model as lm
from pyfect.ai import tool as T
from pyfect.ai._provider_tools import UnsupportedInput
from pyfect.ai.ai_error import InvalidUserInputError
from pyfect.ai.anthropic.tool import DeferLoading
from pyfect.ai.anthropic_structured_output import to_codec_anthropic
from pyfect.ai.tool import NameMapper
from pyfect.json_schema import JsonSchema
from pyfect.schema import Top

type Block = dict[str, Any]


@dataclass(frozen=True)
class Capabilities:
    max_output_tokens: int
    supports_structured_output: bool
    supports_mid_conversation_system_messages: bool


@dataclass(frozen=True)
class Prepared:
    tools: list[Block] | None
    tool_choice: Block | None


MODULE = "AnthropicLanguageModel"


def _error(method: str, reason: Any) -> UnsupportedInput:
    return PT.unsupported(MODULE, method, reason)


def json_schema(schema: Any, method: str) -> Block:
    return PT.json_schema(MODULE, schema, method, transformer=to_codec_anthropic)


def to_codec_lenient(schema: Top) -> tuple[Top, JsonSchema]:
    """Anthropic's codec, or the plain JSON one for a schema Anthropic's
    strict mode cannot express (recursion): its restrictions only apply to
    strict tools."""
    try:
        return to_codec_anthropic(schema)
    except Exception:
        return lm.default_codec_transformer(schema)


def tool_json_schema(tool: T.AnyTool, strict: bool) -> Block:
    transformer = to_codec_anthropic if strict else to_codec_lenient
    return PT.tool_json_schema(MODULE, tool, require_object=True, transformer=transformer)


def _computer(args: Mapping[str, Any], name: str, type_: str) -> Block:
    return {
        "name": name,
        "type": type_,
        "display_height_px": args.get("displayHeightPx"),
        "display_width_px": args.get("displayWidthPx"),
        "display_number": args.get("displayNumber"),
    }


def _user_location(args: Mapping[str, Any]) -> Block | None:
    location = args.get("userLocation")
    if location is None:
        return None
    return {
        "type": location.get("type"),
        "region": location.get("region"),
        "city": location.get("city"),
        "country": location.get("country"),
        "timezone": location.get("timezone"),
    }


def _plain(name: str, type_: str) -> Callable[[Mapping[str, Any]], Block]:
    return lambda _args: {"name": name, "type": type_}


_PROVIDER_TOOLS: dict[str, tuple[str | None, Callable[[Mapping[str, Any]], Block]]] = {
    "anthropic.bash_20241022": ("computer-use-2024-10-22", _plain("bash", "bash_20241022")),
    "anthropic.bash_20250124": ("computer-use-2025-01-24", _plain("bash", "bash_20250124")),
    "anthropic.code_execution_20250522": (
        "code-execution-2025-05-22",
        _plain("code_execution", "code_execution_20250522"),
    ),
    "anthropic.code_execution_20250825": (
        "code-execution-2025-08-25",
        _plain("code_execution", "code_execution_20250825"),
    ),
    "anthropic.computer_use_20241022": (
        "computer-use-2024-10-22",
        lambda args: _computer(args, "computer", "computer_20241022"),
    ),
    "anthropic.computer_20250124": (
        "computer-use-2025-01-24",
        lambda args: _computer(args, "computer", "computer_20250124"),
    ),
    "anthropic.computer_20251124": (
        "computer-use-2025-11-24",
        lambda args: {
            **_computer(args, "computer", "computer_20251124"),
            "enable_zoom": args.get("enableZoom", False),
        },
    ),
    "anthropic.memory_20250818": (
        "context-management-2025-06-27",
        _plain("memory", "memory_20250818"),
    ),
    "anthropic.text_editor_20241022": (
        "computer-use-2024-10-22",
        _plain("str_replace_editor", "text_editor_20241022"),
    ),
    "anthropic.text_editor_20250124": (
        "computer-use-2025-01-24",
        _plain("str_replace_editor", "text_editor_20250124"),
    ),
    "anthropic.text_editor_20250429": (
        "computer-use-2025-01-24",
        _plain("str_replace_based_edit_tool", "text_editor_20250429"),
    ),
    "anthropic.text_editor_20250728": (
        None,
        lambda args: {
            "name": "str_replace_based_edit_tool",
            "type": "text_editor_20250728",
            "max_characters": args.get("max_characters"),
        },
    ),
    "anthropic.tool_search_tool_bm25_20251119": (
        "advanced-tool-use-2025-11-20",
        _plain("tool_search_tool_bm25", "tool_search_tool_bm25_20251119"),
    ),
    "anthropic.tool_search_tool_regex_20251119": (
        None,
        _plain("tool_search_tool_regex", "tool_search_tool_regex_20251119"),
    ),
    "anthropic.web_search_20250305": (
        None,
        lambda args: {
            "name": "web_search",
            "type": "web_search_20250305",
            "max_uses": args.get("maxUses"),
            "allowed_domains": args.get("allowedDomains"),
            "blocked_domains": args.get("blockedDomains"),
            "user_location": _user_location(args),
        },
    ),
    "anthropic.web_fetch_20250910": (
        "web-fetch-2025-09-10",
        lambda args: {
            "name": "web_fetch",
            "type": "web_fetch_20250910",
            "max_uses": args.get("maxUses"),
            "allowed_domains": args.get("allowedDomains"),
            "blocked_domains": args.get("blockedDomains"),
            "citations": args.get("citations"),
            "max_content_tokens": args.get("maxContentTokens"),
        },
    ),
}


def _provider_tool(
    tool: T.ProviderDefined[Any, Any, Any, Any, Any, Any], betas: dict[str, None]
) -> Block:
    entry = _PROVIDER_TOOLS.get(tool.provider_id)
    if entry is None:
        raise _error(
            "prepareTools",
            InvalidUserInputError(
                description=f"Received request to call unknown provider-defined tool '{tool.name}'"
            ),
        )
    beta, build = entry
    if beta is not None:
        betas[beta] = None
    return build(P.obj(tool.args))


def _user_tool(
    tool: T.AnyTool, capabilities: Capabilities, strict_default: bool | None, betas: dict[str, None]
) -> Block:
    strict: bool | None = None
    if capabilities.supports_structured_output:
        own = T.get_strict_mode(tool)
        strict = own if own is not None else (strict_default is not False)
    block: Block = {"name": tool.name, "input_schema": tool_json_schema(tool, strict is True)}
    description = T.get_description(tool)
    if description is not None:
        block["description"] = description
    if strict is not None:
        block["strict"] = strict
        betas["structured-outputs-2025-11-13"] = None
    if tool.annotations.get_unsafe(DeferLoading):
        block["defer_loading"] = True
    return block


def _tool_choice(choice: lm.ToolChoice, names: NameMapper) -> Block:
    """The tools a ``one_of`` choice names are already the request's only
    tools."""
    if choice == "auto":
        return {"type": "auto"}
    if choice == "required":
        return {"type": "any"}
    if isinstance(choice, dict) and "tool" in choice:
        return {"type": "tool", "name": names.get_provider_name(choice["tool"])}
    assert isinstance(choice, dict)
    return {"type": "any" if choice.get("mode") == "required" else "auto"}


def prepare_tools(
    options: lm.ProviderOptions,
    capabilities: Capabilities,
    config: Mapping[str, Any],
    betas: dict[str, None],
    names: NameMapper,
) -> Prepared:
    """Raises ``UnsupportedInput`` for a schema or tool Anthropic cannot
    take."""
    response_format = options.response_format
    if isinstance(response_format, lm.JsonFormat) and not capabilities.supports_structured_output:
        schema = json_schema(response_format.schema, "prepareTools")
        user_description = PT.schema_description(response_format.schema)
        prefix = f"{user_description} - " if user_description is not None else ""
        return Prepared(
            [
                {
                    "name": response_format.object_name,
                    "description": f"{prefix}You MUST respond with a JSON object.",
                    "input_schema": schema,
                }
            ],
            {
                "type": "tool",
                "name": response_format.object_name,
                "disable_parallel_tool_use": True,
            },
        )
    if not options.tools or options.tool_choice == "none":
        return Prepared(None, None)
    user_tools: list[Block] = []
    provider_tools: list[Block] = []
    for tool in options.tools:
        if isinstance(tool, T.ProviderDefined):
            provider_tools.append(_provider_tool(tool, betas))
        else:
            user_tools.append(
                _user_tool(tool, capabilities, config.get("strict_json_schema"), betas)
            )
    choice = _tool_choice(options.tool_choice, names)
    disable = config.get("disable_parallel_tool_calls")
    if disable is not None and choice["type"] != "none":
        choice["disable_parallel_tool_use"] = disable
    return Prepared([*user_tools, *provider_tools], choice)
