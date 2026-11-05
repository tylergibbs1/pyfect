"""What a server writes for one protocol revision: the canonical values
with the fields the revision's schema lacks left out."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast

from pyfect import _json_text
from pyfect.ai.mcp_protocol import AnyProtocolAdapter
from pyfect.ai.mcp_schema import (
    Annotations,
    CallToolResult,
    ClientCapabilities,
    ContentBlock,
    GetPromptResult,
    Implementation,
    Prompt,
    Resource,
    ResourceTemplate,
    Tool,
)

type Wire = dict[str, Any]


def _without(value: Mapping[str, Any], *keys: str) -> Wire:
    return {k: v for k, v in value.items() if k not in keys}


def implementation(protocol: AnyProtocolAdapter, info: Implementation) -> Wire:
    if protocol.supports_icons:
        return dict(info)
    drop = ("icons", "description", "websiteUrl")
    return (
        _without(info, *drop)
        if protocol.supports_structured_content
        else _without(info, *drop, "title")
    )


def client_capabilities(
    protocol: AnyProtocolAdapter, capabilities: ClientCapabilities
) -> ClientCapabilities:
    """What ``protocol``'s schema keeps of what a client advertises: nothing
    of elicitation before 2025-06-18."""
    if protocol.supports_structured_content:
        return capabilities
    return cast("ClientCapabilities", _without(capabilities, "elicitation"))


def annotations_of(protocol: AnyProtocolAdapter, value: Annotations) -> Wire:
    return dict(value) if protocol.supports_icons else _without(value, "lastModified")


def _described(
    protocol: AnyProtocolAdapter, value: Mapping[str, Any], *, core_annotations: bool = True
) -> Wire:
    """A tool, resource, template or prompt: titles from 2025-06-18, icons
    from 2025-11-25, core annotations as the revision has them."""
    out = dict(value)
    if not protocol.supports_icons:
        out.pop("icons", None)
    if not protocol.supports_structured_content:
        out.pop("title", None)
        out.pop("_meta", None)
    if core_annotations and "annotations" in out:
        out["annotations"] = annotations_of(protocol, out["annotations"])
    return out


def resource(protocol: AnyProtocolAdapter, value: Resource) -> Wire:
    return _described(protocol, value)


def resource_template(protocol: AnyProtocolAdapter, value: ResourceTemplate) -> Wire:
    return _described(protocol, value)


def prompt(protocol: AnyProtocolAdapter, value: Prompt) -> Wire:
    out = _described(protocol, value)
    if not protocol.supports_structured_content and "arguments" in out:
        out["arguments"] = [_without(a, "title") for a in out["arguments"]]
    return out


def _is_object_schema(schema: object) -> bool:
    if not isinstance(schema, Mapping):
        return False
    shape = cast("Mapping[str, object]", schema)
    properties = shape.get("properties")
    required = shape.get("required")
    return (
        shape.get("type") == "object"
        and (
            properties is None
            or (
                isinstance(properties, Mapping)
                and all(
                    isinstance(p, Mapping)
                    for p in cast("Mapping[str, object]", properties).values()
                )
            )
        )
        and (
            required is None
            or (
                isinstance(required, list)
                and all(isinstance(r, str) for r in cast("list[object]", required))
            )
        )
    )


def _legacy_input_schema(schema: Mapping[str, Any]) -> Wire:
    """``type``, ``properties`` and ``required``, all the schema of a revision
    before 2025-06-18 has, with boolean property schemas as the objects they
    mean."""
    out: Wire = {k: schema[k] for k in ("type", "properties", "required") if k in schema}
    properties = out.get("properties")
    if isinstance(properties, Mapping):
        out["properties"] = {
            name: ({} if s else {"not": {}}) if isinstance(s, bool) else s
            for name, s in cast("Mapping[str, object]", properties).items()
        }
    return out


WRAP_RESULT = "x-fastmcp-wrap-result"
"""Marks an output schema whose result is wrapped as ``{"result": ...}``
(FastMCP's key, which its clients unwrap too)."""


def wraps_result(protocol: AnyProtocolAdapter, value: Tool) -> bool:
    """Whether ``value``'s result goes as ``{"result": ...}`` on
    ``protocol``: a revision whose ``structuredContent`` must be an object,
    and a result that is not one, nor nothing, nor a string (whose text is
    all of it). Effect drops these results' structured form, leaving only
    their JSON text; other MCP SDKs wrap them."""
    schema = value.get("outputSchema")
    return (
        protocol.supports_structured_content
        and not protocol.supports_any_structured_content
        and isinstance(schema, Mapping)
        and not _is_object_schema(schema)
        and cast("Mapping[str, object]", schema).get("type") not in ("null", "string")
    )


_HINT_DEFAULTS: Wire = {
    "readOnlyHint": False,
    "destructiveHint": True,
    "idempotentHint": False,
    "openWorldHint": True,
}
"""A tool annotation left out means this (``ToolAnnotations``' defaults)."""


def _tool_annotations(protocol: AnyProtocolAdapter, value: Tool) -> Wire | None:
    """2025-06-18 on has the title beside the annotations; 2025-03-26 only in
    them, where the canonical title wins; 2024-11-05 has no annotations."""
    if not protocol.supports_audio:
        return None
    annotations = value.get("annotations")
    title = value.get("title") or (annotations or {}).get("title")
    if protocol.supports_structured_content:
        return None if annotations is None else {**_HINT_DEFAULTS, **annotations}
    if annotations is None and title is None:
        return None
    merged = {**_HINT_DEFAULTS, **(annotations or {})}
    return merged if title is None else {**merged, "title": title}


def tool(protocol: AnyProtocolAdapter, value: Tool) -> Wire:
    # A tool's canonical title is its own, else its annotations' (Effect's ``addTool``).
    title = value.get("title") or (value.get("annotations") or {}).get("title")
    titled = value if title is None else {**value, "title": title}
    out = _described(protocol, titled, core_annotations=False)
    if not protocol.supports_structured_content:
        out.pop("outputSchema", None)
        out["inputSchema"] = _legacy_input_schema(out["inputSchema"])
    elif wraps_result(protocol, value):
        out["outputSchema"] = {
            "type": "object",
            "properties": {"result": out["outputSchema"]},
            "required": ["result"],
            WRAP_RESULT: True,
        }
    elif (
        "outputSchema" in out
        and not protocol.supports_any_structured_content
        and not _is_object_schema(out["outputSchema"])
    ):
        out.pop("outputSchema")
    annotations = _tool_annotations(protocol, value)
    if annotations is None:
        out.pop("annotations", None)
    else:
        out["annotations"] = annotations
    out.pop("execution", None)
    return out


def unsupported_content(protocol: AnyProtocolAdapter, blocks: list[ContentBlock]) -> str | None:
    """Why ``protocol``'s schema cannot hold ``blocks``, if it cannot."""
    for block in blocks:
        kind = block["type"]
        if (kind == "audio" and not protocol.supports_audio) or (
            kind == "resource_link" and not protocol.supports_structured_content
        ):
            return f"{kind} tool content is not supported by MCP {protocol.protocol_version}"
    return None


def content(protocol: AnyProtocolAdapter, block: ContentBlock) -> Wire:
    out: Wire = dict(block)
    if "annotations" in out:
        out["annotations"] = annotations_of(protocol, out["annotations"])
    if not protocol.supports_structured_content:
        out.pop("_meta", None)
        if "resource" in out:
            out["resource"] = _without(out["resource"], "_meta")
    return out


def _unwrap_string(result: CallToolResult) -> list[ContentBlock]:
    """The text mirror of a string ``structuredContent``, unquoted (the
    wire drops a string ``structuredContent``)."""
    structured = result.get("structuredContent")
    blocks = result["content"]
    if not isinstance(structured, str) or len(blocks) != 1:
        return blocks
    block = blocks[0]
    if block["type"] == "text" and block["text"] == _json_text.stringify(structured):
        return [{**block, "text": structured}]
    return blocks


def call_tool_result(
    protocol: AnyProtocolAdapter, result: CallToolResult, wrap: bool = False
) -> Wire:
    """``result`` on ``protocol``'s wire; ``wrap`` (``wraps_result``)
    sends a successful result's ``structuredContent`` as ``{"result": ...}``."""
    structured = result.get("structuredContent")
    if protocol.supports_any_structured_content:
        out: Wire = {"content": [content(protocol, b) for b in result["content"]]}
        if structured is not None:
            out["structuredContent"] = structured
    else:
        out = {"content": [content(protocol, b) for b in _unwrap_string(result)]}
        if wrap and result.get("isError") is not True:
            out["structuredContent"] = {"result": structured}
        elif protocol.supports_structured_content and isinstance(structured, Mapping):
            out["structuredContent"] = structured
    if "isError" in result:
        out["isError"] = result["isError"]
    if "_meta" in result:
        out["_meta"] = result["_meta"]
    return out


def notification(protocol: AnyProtocolAdapter, method: str, params: Mapping[str, Any]) -> Wire:
    """A notification's params on ``protocol``'s wire: progress messages
    start at 2025-03-26."""
    if method == "notifications/progress" and not protocol.supports_audio:
        return _without(params, "message")
    return dict(params)


def get_prompt_result(protocol: AnyProtocolAdapter, result: GetPromptResult) -> Wire:
    out: Wire = {
        "messages": [
            {"role": m["role"], "content": content(protocol, m["content"])}
            for m in result["messages"]
        ]
    }
    if "description" in result:
        out["description"] = result["description"]
    if "_meta" in result:
        out["_meta"] = result["_meta"]
    return out
