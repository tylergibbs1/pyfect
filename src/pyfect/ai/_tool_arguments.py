"""Tool arguments as the ``gen_ai.tool.call.arguments`` span attribute (Effect's
``stringifyToolArguments``), shared by the toolkit and the MCP server's spans."""

from __future__ import annotations

from pyfect import _json_text


def stringify_tool_arguments(params: object) -> str:
    """Their JSON text (``JSON.stringify``), or ``str`` of a value JSON has no form for."""
    try:
        return _json_text.stringify(params)
    except (TypeError, ValueError):
        return str(params)


__all__ = ["stringify_tool_arguments"]
