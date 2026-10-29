"""The body of a Chat Completions request (Effect's ``prepareTools``,
``prepareResponseFormat`` and ``toChatCompletionsRequest``). The
configuration is Responses-style (``max_output_tokens``, ``text``); keys
the Responses API does not know pass through as provider extras."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pyfect.ai import _provider as P
from pyfect.ai import _provider_tools as PT
from pyfect.ai import language_model as lm
from pyfect.ai import tool as T
from pyfect.ai.openai_compat._prompt import MODULE, Block
from pyfect.ai.tool import NameMapper

_KNOWN = frozenset(
    {
        "metadata",
        "top_logprobs",
        "temperature",
        "top_p",
        "user",
        "safety_identifier",
        "prompt_cache_key",
        "service_tier",
        "prompt_cache_retention",
        "previous_response_id",
        "model",
        "reasoning",
        "background",
        "max_output_tokens",
        "max_tool_calls",
        "text",
        "tools",
        "tool_choice",
        "truncation",
        "input",
        "include",
        "parallel_tool_calls",
        "store",
        "instructions",
        "stream",
        "conversation",
        "modalities",
        "seed",
    }
)
LIBRARY_KEYS = frozenset({"file_id_prefixes", "strict_json_schema"})
_COPIED = (
    ("temperature", "temperature"),
    ("top_p", "top_p"),
    ("max_output_tokens", "max_tokens"),
    ("user", "user"),
    ("seed", "seed"),
    ("parallel_tool_calls", "parallel_tool_calls"),
    ("service_tier", "service_tier"),
    ("reasoning", "reasoning"),
)


def _function(name: str, description: str | None, parameters: Any, strict: bool) -> Block:
    function: Block = {"name": name, "description": description, "parameters": parameters}
    function["strict"] = strict
    return {"type": "function", "function": function}


def _tools(options: lm.ProviderOptions, config: Mapping[str, Any]) -> list[Block]:
    allowed = options.tools
    choice = options.tool_choice
    if isinstance(choice, dict) and "one_of" in choice:
        names = set(choice["one_of"])
        allowed = [tool for tool in allowed if tool.name in names]
    default_strict = config.get("strict_json_schema")
    tools: list[Block] = []
    for tool in allowed:
        description = T.get_description(tool)
        if isinstance(tool, T.ProviderDefined):
            schema = T.get_json_schema(tool)
            strict = default_strict if default_strict is not None else True
            tools.append(_function(tool.provider_name, description, schema, strict))
        else:
            schema = PT.tool_json_schema(MODULE, tool, require_object=True)
            mode = T.get_strict_mode(tool)
            strict = mode if mode is not None else default_strict
            tools.append(
                _function(tool.name, description, schema, strict if strict is not None else True)
            )
    return tools


def _tool_choice(choice: lm.ToolChoice, names: NameMapper) -> Any:
    if isinstance(choice, str):
        return choice
    if "tool" not in choice:
        return "required" if choice.get("mode") == "required" else "auto"
    tool = choice["tool"]
    provider = names.get_provider_name(tool)
    name = provider if provider in names.provider_names else tool
    return {"type": "function", "function": {"name": name}}


def _response_format(options: lm.ProviderOptions, config: Mapping[str, Any]) -> Block | None:
    response_format = options.response_format
    if not isinstance(response_format, lm.JsonFormat):
        return None
    schema = PT.json_schema(MODULE, response_format.schema, "prepareResponseFormat")
    strict = config.get("strict_json_schema")
    return {
        "type": "json_schema",
        "json_schema": {
            "name": response_format.object_name,
            "schema": schema,
            "description": P.or_default(
                PT.schema_description(response_format.schema), "Response with a JSON object"
            ),
            "strict": strict if strict is not None else True,
        },
    }


def chat_request(
    config: Mapping[str, Any],
    options: lm.ProviderOptions,
    messages: list[Block],
    names: NameMapper,
) -> Block:
    """Raises ``UnsupportedInput`` for a schema that has no JSON Schema."""
    request: Block = {
        key: value for key, value in config.items() if key not in _KNOWN and key not in LIBRARY_KEYS
    }
    request["model"] = P.or_default(config.get("model"), "")
    request["messages"] = messages or [{"role": "user", "content": ""}]
    for source, target in _COPIED:
        if source in config:
            request[target] = config[source]
    response_format = _response_format(options, config)
    if response_format is not None:
        request["response_format"] = response_format
    if options.tools:
        tools = _tools(options, config)
        if tools:
            request["tools"] = tools
        request["tool_choice"] = _tool_choice(options.tool_choice, names)
    return request
