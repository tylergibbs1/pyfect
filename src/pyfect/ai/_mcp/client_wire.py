"""What the MCP client transports share: message encoding and parsing
within the size limit, answers to server requests, routing headers and
the text a tool result shows a model."""

from __future__ import annotations

import base64
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, cast

from pyfect import _json_text
from pyfect._core import Effect
from pyfect._js import or_default, text_encode
from pyfect._json_text import parse as parse_json_text
from pyfect.ai.mcp_client_error import (
    AnyReason,
    LimitError,
    McpClientError,
    ProtocolError,
    TransportError,
    UnsupportedError,
    ValidationError,
)
from pyfect.ai.mcp_schema import (
    METHOD_NOT_FOUND_ERROR_CODE,
    CallToolResult,
    JsonObject,
    RequestId,
    ResourceLink,
    Tool,
)
from pyfect.effect import fail, succeed

BASE64_PREFIX = "=?base64?"
BASE64_SUFFIX = "?="
_HEADER_TOKEN = re.compile(r"^[!#$%&'*+\-.^_`|~0-9A-Za-z]+$")
_VISIBLE_ASCII = re.compile(r"^[\x20-\x7e]*$")

_SCHEMA_KEYWORDS = frozenset(
    {
        "additionalProperties",
        "unevaluatedProperties",
        "propertyNames",
        "items",
        "additionalItems",
        "unevaluatedItems",
        "contains",
        "not",
        "if",
        "then",
        "else",
        "contentSchema",
    }
)
_SCHEMA_MAP_KEYWORDS = frozenset(
    {"properties", "patternProperties", "$defs", "definitions", "dependentSchemas", "dependencies"}
)
_SCHEMA_ARRAY_KEYWORDS = frozenset({"allOf", "anyOf", "oneOf", "prefixItems", "items"})


def failure(reason: AnyReason) -> McpClientError:
    return McpClientError(reason)


def limit_error(description: str) -> McpClientError:
    return failure(LimitError(description))


def encode_message(message: Mapping[str, Any], max_bytes: int) -> Effect[str, McpClientError]:
    try:
        text = _json_text.stringify(message)
    except (TypeError, ValueError) as cause:
        return fail(failure(TransportError("Cannot encode MCP message", cause)))
    if len(text_encode(text)) > max_bytes:
        return fail(limit_error("MCP message exceeds maxMessageBytes"))
    return succeed(text)


def _is_message(value: object) -> bool:
    if not isinstance(value, dict):
        return False
    body = cast("dict[str, object]", value)
    if body.get("jsonrpc") != "2.0":
        return False
    if "method" in body:
        return isinstance(body["method"], str)
    return "result" in body or "error" in body


def parse_message(text: str, max_bytes: int) -> Effect[JsonObject, McpClientError]:
    if len(text_encode(text)) > max_bytes:
        return fail(limit_error("MCP message exceeds maxMessageBytes"))
    try:
        parsed: object = parse_json_text(text)
    except ValueError as cause:
        return fail(failure(ProtocolError(description="Invalid MCP JSON", cause=cause)))
    if not _is_message(parsed):
        return fail(failure(ProtocolError(description="Invalid JSON-RPC message")))
    return succeed(cast("JsonObject", parsed))


def is_request(message: Mapping[str, Any]) -> bool:
    return "method" in message and "id" in message


def is_response(message: Mapping[str, Any]) -> bool:
    return "method" not in message


def reply_to_server(request: Mapping[str, Any]) -> JsonObject:
    """The client advertises no capabilities: it answers pings and
    declines every other server request."""
    id = request.get("id")
    if request.get("method") == "ping":
        return {"jsonrpc": "2.0", "id": id, "result": {}}
    return {
        "jsonrpc": "2.0",
        "id": id,
        "error": {
            "code": METHOD_NOT_FOUND_ERROR_CODE,
            "message": f"Unsupported MCP method: {request.get('method')}",
        },
    }


def cancelled(id: RequestId) -> JsonObject:
    return {"jsonrpc": "2.0", "method": "notifications/cancelled", "params": {"requestId": id}}


def header_value(value: str) -> str:
    """``value`` as a header: as is when plain visible ASCII, else Base64
    between ``=?base64?`` and ``?=``."""
    plain = (
        _VISIBLE_ASCII.match(value) is not None
        and value.strip() == value
        and not (value.startswith(BASE64_PREFIX) and value.endswith(BASE64_SUFFIX))
    )
    if plain:
        return value
    return f"{BASE64_PREFIX}{base64.b64encode(text_encode(value)).decode('ascii')}{BASE64_SUFFIX}"


@dataclass(frozen=True, slots=True)
class HeaderParameter:
    path: tuple[str, ...]
    header: str
    type: str


def header_parameters(tool: Tool) -> list[HeaderParameter] | None:
    """The ``x-mcp-header`` annotations along chains of ``properties``, or
    ``None`` when one is invalid or found anywhere else."""
    parameters: list[HeaderParameter] = []
    return parameters if _visit_headers(tool["inputSchema"], (), parameters, set()) else None


def _visit_headers(
    schema: object,
    path: tuple[str, ...] | None,
    parameters: list[HeaderParameter],
    names: set[str],
) -> bool:
    if not isinstance(schema, dict):
        return True
    node = cast("dict[str, object]", schema)
    name = node.get("x-mcp-header")
    if name is not None:
        kind = node.get("type")
        if (
            not path
            or not isinstance(name, str)
            or _HEADER_TOKEN.match(name) is None
            or name.lower() in names
            or kind not in ("string", "integer", "boolean")
        ):
            return False
        names.add(name.lower())
        parameters.append(HeaderParameter(path, f"mcp-param-{name.lower()}", cast("str", kind)))
    for keyword, value in node.items():
        if keyword in _SCHEMA_MAP_KEYWORDS and isinstance(value, dict):
            children = cast("dict[str, object]", value)
            for key, child in children.items():
                child_path = (*path, key) if keyword == "properties" and path is not None else None
                if not _visit_headers(child, child_path, parameters, names):
                    return False
        elif isinstance(value, list):
            if keyword in _SCHEMA_ARRAY_KEYWORDS and not all(
                _visit_headers(child, None, parameters, names)
                for child in cast("list[object]", value)
            ):
                return False
        elif keyword in _SCHEMA_KEYWORDS and not _visit_headers(value, None, parameters, names):
            return False
    return True


def routing_headers(
    message: Mapping[str, Any], tool: Tool | None
) -> Effect[dict[str, str], McpClientError]:
    """The 2026-07-28 HTTP routing headers of a request."""
    method = message.get("method")
    if not isinstance(method, str):
        return succeed({})
    headers = {"mcp-method": method}
    params = cast("Mapping[str, Any]", message.get("params") or {})
    name = params.get("uri") if method == "resources/read" else params.get("name")
    if isinstance(name, str) and method in ("tools/call", "prompts/get", "resources/read"):
        headers["mcp-name"] = header_value(name)
    if method != "tools/call":
        return succeed(headers)
    parameters = None if tool is None else header_parameters(tool)
    if parameters is None:
        return fail(failure(UnsupportedError("Tool has invalid x-mcp-header annotations")))
    for parameter in parameters:
        value: object = params.get("arguments")
        for key in parameter.path:
            value = cast("dict[str, object]", value).get(key) if isinstance(value, dict) else None
        if value is None:
            continue
        valid = (
            isinstance(value, int) and not isinstance(value, bool)
            if parameter.type == "integer"
            else isinstance(value, bool)
            if parameter.type == "boolean"
            else isinstance(value, str)
        )
        if not valid:
            return fail(
                failure(
                    ValidationError(f"Invalid value for MCP header parameter {parameter.header}")
                )
            )
        text = ("true" if value else "false") if isinstance(value, bool) else str(value)
        headers[parameter.header] = header_value(text)
    return succeed(headers)


def resource_link_text(link: ResourceLink) -> str:
    """A resource link as a model reads it: its title (else name), URI and
    description."""
    label = or_default(link.get("title"), link["name"])
    description = link.get("description")
    return f"{label}: {link['uri']}" + ("" if description is None else f"\n{description}")


def to_text(result: CallToolResult) -> Effect[str, McpClientError]:
    """What a model sees of a tool result: its text, resource links and
    text resources, or the JSON of ``structuredContent`` when it has none."""

    def unsupported(content: str) -> Effect[str, McpClientError]:
        return fail(
            failure(
                UnsupportedError(f"MCP {content} requires an application text converter", result)
            )
        )

    parts: list[str] = []
    for block in result["content"]:
        if block["type"] == "text":
            parts.append(block["text"])
        elif block["type"] == "resource_link":
            parts.append(resource_link_text(block))
        elif block["type"] == "resource":
            resource = block["resource"]
            if "text" not in resource:
                return unsupported("binary resources")
            parts.append(cast("Any", resource)["text"])
        else:
            return unsupported(f"{block['type']} content")
    if not parts and "structuredContent" in result:
        return succeed(_json_text.stringify(result["structuredContent"]))
    return succeed("\n".join(parts))


def requires_tasks(tool: object) -> bool:
    if not isinstance(tool, dict):
        return False
    execution = cast("dict[str, object]", tool).get("execution")
    return (
        isinstance(execution, dict)
        and cast("dict[str, object]", execution).get("taskSupport") == "required"
    )


def media_type(headers: Mapping[str, str]) -> str | None:
    content_type = headers.get("content-type")
    return None if content_type is None else content_type.split(";", 1)[0].strip().lower()


__all__: Sequence[str] = ()
