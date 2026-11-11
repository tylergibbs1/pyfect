"""2026-07-28's ``Mcp-Param-*`` headers: a tool parameter annotated with
``x-mcp-header`` is mirrored in a header, which must match the argument
before the tool runs."""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any, cast

from pyfect._js import trim
from pyfect.ai._mcp.routing_header import decode_routing_header
from pyfect.schema.getter._coerce import to_number

_MAX_SAFE_INTEGER = 2**53 - 1


def _header_matches(header: str | None, argument: object) -> bool:  # noqa: PLR0911
    if argument is None:
        return header is None
    if header is None:
        return False
    decoded = decode_routing_header(header)
    if decoded is None:
        return False
    if isinstance(argument, str):
        return decoded == argument
    if isinstance(argument, bool):
        return decoded == ("true" if argument else "false")
    if isinstance(argument, (int, float)):
        safe = abs(argument) <= _MAX_SAFE_INTEGER and float(argument).is_integer()
        if not safe or not trim(decoded):
            return False
        number = to_number(decoded)
        return not math.isnan(number) and number == argument
    return False


def _object(value: object) -> Mapping[str, Any] | None:
    return cast("Mapping[str, Any]", value) if isinstance(value, dict) else None


def mismatch(input_schema: object, arguments: object, headers: Mapping[str, str]) -> str | None:
    """Why ``headers`` do not mirror ``arguments``, if so. Only ``properties``
    paths may mirror a header; composition, arrays and references do not."""
    pending: list[tuple[object, object, str]] = [(input_schema, arguments, "")]
    while pending:
        schema, argument, path = pending.pop()
        node = _object(schema)
        if node is None:
            continue
        annotation = node.get("x-mcp-header")
        if isinstance(annotation, str):
            name = f"mcp-param-{annotation.lower()}"
            if not _header_matches(headers.get(name), argument):
                return f"{name} does not match argument '{path}'"
        properties = _object(node.get("properties"))
        if properties is None:
            continue
        values = _object(argument) or {}
        for key, property in properties.items():
            pending.append((property, values.get(key), key if not path else f"{path}.{key}"))
    return None
