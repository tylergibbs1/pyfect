"""The JSON Schema of each built-in check, by its ``representation`` id
(Effect's ``toJsonSchema`` check annotations).

A check gives a fragment that holds exactly when the check does, or
``(fragment, True)``: a looser fragment (an approximation). A check without
one (``make_filter``, ...) is left out, an approximation too. A user check
says its own with a ``to_json_schema`` annotation.

Python differs from JavaScript in one place: ``len`` of a ``str`` counts
code points, as JSON Schema's ``minLength`` does (exact here, approximate
in Effect). JSON Schema cannot carry a Python ``re`` pattern,
so ``is_pattern`` is left out (``is_ecma_pattern``'s is written).
"""

from __future__ import annotations

import math
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal, cast

from pyfect.json_schema import JsonSchema

MAX_SAFE_INTEGER = 2**53 - 1

type CheckOutput = JsonSchema | tuple[JsonSchema, Literal[True]]


@dataclass(frozen=True, slots=True)
class CheckContext:
    """What a check's ``to_json_schema`` annotation is given: the JSON type
    of the node it checks (if one), and the JSON Schemas of the schemas
    its ``representation`` names (``is_property_names``'s key schema)."""

    type: str | None
    schemas: Sequence[JsonSchema]


type ToJsonSchema = Callable[[CheckContext], CheckOutput]

type _Payload = Mapping[str, Any]
type _Builtin = Callable[[_Payload, CheckContext], CheckOutput]

_APPROXIMATE: CheckOutput = ({}, True)

_TRIMMED = r"^\S[\s\S]*\S$|^\S$|^$"
_UPPERCASED = "^[^a-z]*$"
_LOWERCASED = "^[^A-Z]*$"
_CAPITALIZED = r"^(?:[^a-z][\s\S]*)?$"
_UNCAPITALIZED = r"^(?:[^A-Z][\s\S]*)?$"
_FINITE_PATTERN = r"[+-]?(?:\d+(?:\.\d+)?|\.\d+)(?:[Ee][+-]?\d+)?"
_BASE64 = "^([0-9a-zA-Z+/]{4})*(([0-9a-zA-Z+/]{2}==)|([0-9a-zA-Z+/]{3}=))?$"
_BASE64_URL = "^([0-9a-zA-Z-_]{4})*(([0-9a-zA-Z-_]{2}(==)?)|([0-9a-zA-Z-_]{3}(=)?))?$"
_ANY_UUID = (
    "^([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-8][0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}"
    "|00000000-0000-0000-0000-000000000000|[fF]{8}-[fF]{4}-[fF]{4}-[fF]{4}-[fF]{12})$"
)
_GUID = "^([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})$"
_ULID = "^[0-7][0-9A-HJKMNP-TV-Za-hjkmnp-tv-z]{25}$"
NUMBER_KEY_PATTERN = f"^(?:{_FINITE_PATTERN}|Infinity|-Infinity|NaN)$"
"""The text of any number: a key of a number-keyed mapping."""

_REGEXP_SPECIAL = re.compile(r"[/\\^$*+?.()|[\]{}]")


def escape_regexp(text: str) -> str:
    """``text`` as a literal in a JavaScript pattern (Effect's ``RegExp.escape``)."""
    return _REGEXP_SPECIAL.sub(lambda m: "\\" + m.group(0), text)


def _uuid(payload: _Payload, _: CheckContext) -> CheckOutput:
    version = payload.get("version")
    if version is None:
        return {"pattern": _ANY_UUID, "format": "uuid"}
    pattern = (
        f"^([0-9a-fA-F]{{8}}-[0-9a-fA-F]{{4}}-{version}[0-9a-fA-F]{{3}}"
        "-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12})$"
    )
    return {"pattern": pattern, "format": "uuid"}


def _literal(key: str, anchor: Callable[[str], str]) -> _Builtin:
    def fragment(payload: _Payload, _: CheckContext) -> CheckOutput:
        text = cast("str", payload[key])
        return {} if not text else {"pattern": anchor(escape_regexp(text))}

    return fragment


def _pattern(pattern: str, approximate: bool = False) -> _Builtin:
    def fragment(_: _Payload, __: CheckContext) -> CheckOutput:
        return ({"pattern": pattern}, True) if approximate else {"pattern": pattern}

    return fragment


def _bound(keyword: str, key: str) -> _Builtin:
    def fragment(payload: _Payload, _: CheckContext) -> CheckOutput:
        bound = payload[key]
        if isinstance(bound, float) and not math.isfinite(bound):
            return _APPROXIMATE
        return {keyword: bound}

    return fragment


def _between(payload: _Payload, _: CheckContext) -> CheckOutput:
    low = "exclusiveMinimum" if payload.get("exclusiveMinimum") else "minimum"
    high = "exclusiveMaximum" if payload.get("exclusiveMaximum") else "maximum"
    return {low: payload["minimum"], high: payload["maximum"]}


def _sized(
    string: Callable[[_Payload], JsonSchema], array: Callable[[_Payload], JsonSchema]
) -> _Builtin:
    """A length check: on a string's code points, an array's items."""

    def fragment(payload: _Payload, context: CheckContext) -> CheckOutput:
        match context.type:
            case "string":
                return string(payload)
            case "array":
                return array(payload)
            case None:
                return ({**string(payload), **array(payload)}, True)
            case _:
                return _APPROXIMATE

    return fragment


def _properties(make: Callable[[_Payload, CheckContext], JsonSchema]) -> _Builtin:
    def fragment(payload: _Payload, context: CheckContext) -> CheckOutput:
        schema = make(payload, context)
        return schema if context.type == "object" else (schema, True)

    return fragment


def _approximate(_: _Payload, __: CheckContext) -> CheckOutput:
    return _APPROXIMATE


def _regexp(payload: _Payload, _: CheckContext) -> CheckOutput:
    """An ECMAScript pattern is JSON Schema's own; a Python one is not."""
    return {"pattern": payload["source"]} if payload["flags"] == "u" else _APPROXIMATE


BUILTINS: Mapping[str, _Builtin] = {
    "isFinite": lambda _, __: {"type": "number"},
    "isInt": lambda _, __: {
        "type": "integer",
        "minimum": -MAX_SAFE_INTEGER,
        "maximum": MAX_SAFE_INTEGER,
    },
    "isGreaterThan": _bound("exclusiveMinimum", "exclusiveMinimum"),
    "isGreaterThanOrEqualTo": _bound("minimum", "minimum"),
    "isLessThan": _bound("exclusiveMaximum", "exclusiveMaximum"),
    "isLessThanOrEqualTo": _bound("maximum", "maximum"),
    "isBetween": _between,
    "isMultipleOf": lambda payload, _: {"multipleOf": payload["divisor"]},
    **dict.fromkeys(
        (
            "isGreaterThanDate",
            "isGreaterThanOrEqualToDate",
            "isLessThanDate",
            "isLessThanOrEqualToDate",
            "isBetweenDate",
            "isGreaterThanBigInt",
            "isGreaterThanOrEqualToBigInt",
            "isLessThanBigInt",
            "isLessThanOrEqualToBigInt",
            "isBetweenBigInt",
            "isMinSize",
            "isMaxSize",
            "isBetweenSize",
        ),
        _approximate,
    ),
    "isPattern": _regexp,
    "isMinLength": _sized(
        lambda p: {"minLength": p["minLength"]}, lambda p: {"minItems": p["minLength"]}
    ),
    "isMaxLength": _sized(
        lambda p: {"maxLength": p["maxLength"]}, lambda p: {"maxItems": p["maxLength"]}
    ),
    "isBetweenLength": _sized(
        lambda p: {"minLength": p["minimum"], "maxLength": p["maximum"]},
        lambda p: {"minItems": p["minimum"], "maxItems": p["maximum"]},
    ),
    "isMinCodePoints": lambda payload, _: {"minLength": payload["minCodePoints"]},
    "isMaxCodePoints": lambda payload, _: {"maxLength": payload["maxCodePoints"]},
    "isBetweenCodePoints": lambda payload, _: {
        "allOf": [{"minLength": payload["minimum"]}, {"maxLength": payload["maximum"]}]
    },
    "isMinProperties": _properties(lambda p, _: {"minProperties": p["minProperties"]}),
    "isMaxProperties": _properties(lambda p, _: {"maxProperties": p["maxProperties"]}),
    "isBetweenProperties": _properties(
        lambda p, _: {"minProperties": p["minimum"], "maxProperties": p["maximum"]}
    ),
    "isPropertyNames": _properties(lambda _, context: {"propertyNames": context.schemas[0]}),
    "isUnique": lambda _, __: {"uniqueItems": True},
    "isTrimmed": _pattern(_TRIMMED),
    "isStringFinite": _pattern(f"^{_FINITE_PATTERN}$"),
    "isStringBigInt": _pattern(r"^-?\d+$"),
    "isUUID": _uuid,
    "isGUID": _pattern(_GUID),
    "isULID": _pattern(_ULID),
    "isBase64": _pattern(_BASE64),
    "isBase64Url": _pattern(_BASE64_URL),
    "isStartingWith": _literal("startsWith", lambda escaped: f"^{escaped}"),
    "isEndingWith": _literal("endsWith", lambda escaped: f"{escaped}$"),
    "isIncluding": _literal("includes", lambda escaped: escaped),
    "isUppercased": _pattern(_UPPERCASED, approximate=True),
    "isLowercased": _pattern(_LOWERCASED, approximate=True),
    "isCapitalized": _pattern(_CAPITALIZED, approximate=True),
    "isUncapitalized": _pattern(_UNCAPITALIZED, approximate=True),
}
"""By the id after ``effect/schema/``."""


def exporter(annotations: Mapping[str, object] | None) -> ToJsonSchema | None:
    """The check's ``to_json_schema`` annotation, else its built-in one."""
    if not annotations:
        return None
    custom = annotations.get("to_json_schema")
    if callable(custom):
        return cast("ToJsonSchema", custom)
    representation = annotations.get("representation")
    if not isinstance(representation, Mapping):
        return None
    representation = cast("Mapping[str, object]", representation)
    id = representation.get("id")
    builtin = (
        BUILTINS.get(id.removeprefix("effect/schema/"))
        if isinstance(id, str) and id.startswith("effect/schema/")
        else None
    )
    if builtin is None:
        return None
    payload = representation.get("payload")
    data: _Payload = cast("_Payload", payload) if isinstance(payload, Mapping) else {}
    return lambda context: builtin(data, context)


def schemas_of(annotations: Mapping[str, object] | None) -> Sequence[object]:
    """The schemas a check's ``representation`` names."""
    representation = (annotations or {}).get("representation")
    if not isinstance(representation, Mapping):
        return ()
    schemas = cast("Mapping[str, object]", representation).get("schemas")
    return cast("Sequence[object]", schemas) if isinstance(schemas, tuple | list) else ()
