"""Adding a check's JSON Schema to a node's (Effect's ``appendJsonSchema``):
inline when the keywords cannot change meaning on one schema object, else
under ``allOf``."""

from __future__ import annotations

from collections.abc import Sequence
from typing import cast

from pyfect.json_schema import JsonSchema

_INLINEABLE_CHECK_KEYWORDS = frozenset(
    {
        "type",
        "format",
        "pattern",
        "multipleOf",
        "minimum",
        "maximum",
        "exclusiveMinimum",
        "exclusiveMaximum",
        "minLength",
        "maxLength",
        "minItems",
        "maxItems",
        "uniqueItems",
        "minProperties",
        "maxProperties",
        "propertyNames",
    }
)
"""Keep it closed: applicators and dependent keywords can change meaning
when moved across schema objects."""

PROMOTABLE_ANNOTATION_KEYWORDS = frozenset(
    {"title", "description", "default", "examples", "readOnly", "writeOnly"}
)
"""``format`` and ``content*`` can affect validation: not pure annotations."""

INLINEABLE_CHECK_KEYWORDS = _INLINEABLE_CHECK_KEYWORDS
INLINEABLE_ANNOTATED_CHECK_KEYWORDS = _INLINEABLE_CHECK_KEYWORDS | PROMOTABLE_ANNOTATION_KEYWORDS

_LOWER_BOUNDS = frozenset({"minimum", "exclusiveMinimum", "minLength", "minItems", "minProperties"})
_UPPER_BOUNDS = frozenset({"maximum", "exclusiveMaximum", "maxLength", "maxItems", "maxProperties"})


def has_only_keywords(schema: JsonSchema, allowed: frozenset[str]) -> bool:
    return all(key in allowed for key in schema)


def is_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _number_type(schema: JsonSchema) -> str | None:
    kind = schema.get("type")
    return kind if kind in ("number", "integer") else None


def _extract_number_type(schema: JsonSchema) -> tuple[str | None, JsonSchema]:
    kind = _number_type(schema)
    out = schema
    if kind is not None:
        out = {k: v for k, v in schema.items() if k != "type"}
    all_of = out.get("allOf")
    if isinstance(all_of, list):
        members: list[JsonSchema] = []
        changed = False
        for member in cast("list[JsonSchema]", all_of):
            extracted_kind, extracted = _extract_number_type(member)
            if extracted_kind is not None:
                changed = True
                if kind is None or extracted_kind == "integer":
                    kind = extracted_kind
            if extracted:
                members.append(extracted)
        if changed:
            rest = {k: v for k, v in out.items() if k != "allOf"}
            out = rest if not members else {**rest, "allOf": members}
    return kind, out


def _is_number_encoding(schema: JsonSchema) -> bool:
    """``schema`` is a number's JSON form: a number, or ``"NaN"`` /
    ``"Infinity"`` / ``"-Infinity"``."""
    any_of = schema.get("anyOf")
    if not isinstance(any_of, list) or len(any_of) != 2:  # pyright: ignore[reportUnknownArgumentType]
        return False
    first, special = cast("list[JsonSchema]", any_of)
    if first.get("type") != "number" or special.get("type") != "string":
        return False
    enum = special.get("enum")
    return (
        isinstance(enum, list)
        and len(enum) == 3  # pyright: ignore[reportUnknownArgumentType]
        and set(cast("list[str]", enum)) == {"-Infinity", "Infinity", "NaN"}
    )


def _has_no_collisions(left: JsonSchema, right_keys: Sequence[str]) -> bool:
    return not isinstance(left.get("$ref"), str) and all(key not in left for key in right_keys)


def _merge_inline_check(
    left: JsonSchema, right: JsonSchema, right_keys: Sequence[str]
) -> JsonSchema | None:
    """Tighten repeated bounds; ``None`` for a ``$ref`` or a collision that
    is not a bound (the caller falls back to ``allOf``)."""
    if isinstance(left.get("$ref"), str):
        return None
    out = {**left, **right}
    for key in right_keys:
        if key not in left:
            continue
        a, b = left[key], right[key]
        if not is_number(a) or not is_number(b):
            return None
        if key in _LOWER_BOUNDS:
            out[key] = max(cast("float", a), cast("float", b))
        elif key in _UPPER_BOUNDS:
            out[key] = min(cast("float", a), cast("float", b))
        else:
            return None
    minimum, exclusive_minimum = out.get("minimum"), out.get("exclusiveMinimum")
    if is_number(minimum) and is_number(exclusive_minimum):
        keep_exclusive = cast("float", exclusive_minimum) >= cast("float", minimum)
        del out["minimum" if keep_exclusive else "exclusiveMinimum"]
    maximum, exclusive_maximum = out.get("maximum"), out.get("exclusiveMaximum")
    if is_number(maximum) and is_number(exclusive_maximum):
        keep_exclusive = cast("float", exclusive_maximum) <= cast("float", maximum)
        del out["maximum" if keep_exclusive else "exclusiveMaximum"]
    return out


def append_json_schema(
    left: JsonSchema, right: JsonSchema, inline_check: bool = False
) -> JsonSchema:
    if not left:
        return right
    if not right:
        return left
    number = _append_to_number(left, right, inline_check)
    if number is not None:
        return number
    if inline_check:
        merged = _merge_inline_check(left, right, list(right))
        if merged is not None:
            return merged
    return _append_all_of(left, right)


def _append_to_number(left: JsonSchema, right: JsonSchema, inline_check: bool) -> JsonSchema | None:
    """A number type in ``right`` refines ``left``'s (``integer`` wins)."""
    left_type = _number_type(left)
    is_number_encoding = _is_number_encoding(left)
    if left_type is None and not is_number_encoding:
        return None
    extracted_type, extracted = _extract_number_type(right)
    if extracted_type is None:
        return None
    kind = "integer" if "integer" in (left_type, extracted_type) else "number"
    base = {**left, "type": kind}
    if is_number_encoding:
        del base["anyOf"]
    if not extracted:
        return base
    if has_only_keywords(extracted, PROMOTABLE_ANNOTATION_KEYWORDS) and _has_no_collisions(
        base, list(extracted)
    ):
        return {**base, **extracted}
    return append_json_schema(base, extracted, inline_check)


def _append_all_of(left: JsonSchema, right: JsonSchema) -> JsonSchema:
    right_all_of = right.get("allOf")
    members: list[object] = (
        list(cast("list[object]", right_all_of))
        if isinstance(right_all_of, list) and len(right) == 1
        else [right]
    )
    left_all_of = left.get("allOf")
    if isinstance(left_all_of, list):
        return {**left, "allOf": [*cast("list[object]", left_all_of), *members]}
    if isinstance(left.get("$ref"), str):
        return {"allOf": [left, *members]}
    return {**left, "allOf": members}


def same_value(a: object, b: object) -> bool:
    """JavaScript's ``===`` on JSON values: ``True`` is not ``1``."""
    return type(a) is type(b) and a == b if isinstance(a, bool) or isinstance(b, bool) else a == b


def compact_enums(schemas: Sequence[JsonSchema]) -> JsonSchema | None:
    """Members that are each ``{"type": t, "enum": [...]}`` of one type, as
    one enum."""
    shared: object = None
    values: list[object] = []
    for schema in schemas:
        enum = schema.get("enum")
        if len(schema) != 2 or "type" not in schema or not isinstance(enum, list) or not enum:
            return None
        if shared is None:
            shared = schema["type"]
        elif schema["type"] != shared:
            return None
        for value in cast("list[object]", enum):
            if any(same_value(value, seen) for seen in values):
                return None
            values.append(value)
    return {"type": shared, "enum": values}
