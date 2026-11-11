"""OpenAI's ``allOf`` normalization (Effect's ``normalizeAllOf`` in
``OpenAiStructuredOutput``): OpenAI takes no ``allOf``, so its members are
merged into the schema where that keeps their meaning. Patterns are
combined into one of lookaheads, numeric and item-count bounds into the
tightest, and a few other keywords kept when every member agrees; the
others (``properties``, ``required``, ...) are dropped, never merged with
another meaning."""

from __future__ import annotations

from typing import cast

from pyfect.ai import _structured_output_json as J
from pyfect.json_schema import JsonSchema
from pyfect.schema._jsonschema._merge import same_value

_NORMALIZABLE = frozenset({"$ref", "title", "enum", "anyOf", "format", "multipleOf"})


def normalize_all_of(schema: JsonSchema) -> JsonSchema:
    members = schema.get("allOf")
    if not isinstance(members, list):
        return schema
    out: JsonSchema = {}
    patterns: list[str] = []
    base = {key for key in schema if key != "allOf"}
    for key, value in schema.items():
        if key == "allOf":
            continue
        if key == "pattern" and isinstance(value, str):
            patterns.append(value)
        else:
            out[key] = value
    merge = _Merge(out, patterns, base)
    for member in cast("list[object]", members):
        if J.is_json_schema(member):
            for key, value in member.items():
                merge.keyword(key, value)
    unique = list(dict.fromkeys(patterns))
    if len(unique) == 1:
        out["pattern"] = unique[0]
    elif unique:
        out["pattern"] = "^" + "".join(f"(?=[\\s\\S]*?(?:{source}))" for source in unique)
    return out


class _Merge:
    def __init__(self, out: JsonSchema, patterns: list[str], base: set[str]) -> None:
        self.out = out
        self.patterns = patterns
        self.base = base
        self.members: set[str] = set()
        self.ambiguous: set[str] = set()

    def keyword(self, key: str, value: object) -> None:
        out = self.out
        match key:
            case "description":
                if isinstance(value, str):
                    J.append_description(out, value)
            case "pattern":
                if isinstance(value, str):
                    self.patterns.append(value)
            case "minimum" | "exclusiveMinimum":
                _merge_bound(out, key, value, lower=True)
            case "maximum" | "exclusiveMaximum":
                _merge_bound(out, key, value, lower=False)
            case "minItems":
                _merge_count(out, key, value, lower=True)
            case "maxItems":
                _merge_count(out, key, value, lower=False)
            case _:
                if key not in _NORMALIZABLE or key in self.base or key in self.ambiguous:
                    return
                if key not in self.members:
                    out[key] = value
                    self.members.add(key)
                elif not _strictly_equal(out[key], value):
                    del out[key]
                    self.members.discard(key)
                    self.ambiguous.add(key)


def _strictly_equal(a: object, b: object) -> bool:
    """JavaScript's ``===`` on JSON values: two lists or objects are equal
    only when they are the same one."""
    if isinstance(a, (list, dict)) or isinstance(b, (list, dict)):
        return a is b
    return same_value(a, b)


def _is_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _merge_count(schema: JsonSchema, key: str, value: object, *, lower: bool) -> None:
    if not _is_number(value):
        return
    current = schema.get(key)
    number = cast("float", value)
    if not _is_number(current) or (
        number > cast("float", current) if lower else number < cast("float", current)
    ):
        schema[key] = value


def _merge_bound(schema: JsonSchema, key: str, value: object, *, lower: bool) -> None:
    """The tighter of the schema's bound and ``value``, an exclusive one
    winning a tie."""
    if not _is_number(value):
        schema.setdefault(key, value)
        return
    inclusive, exclusive = (
        ("minimum", "exclusiveMinimum") if lower else ("maximum", "exclusiveMaximum")
    )

    def tighter(a: float, b: float) -> bool:
        return a > b if lower else a < b

    current: tuple[float, bool] | None = None
    if _is_number(schema.get(inclusive)):
        current = (cast("float", schema[inclusive]), False)
    found = schema.get(exclusive)
    if _is_number(found):
        bound = cast("float", found)
        if current is None or bound == current[0] or tighter(bound, current[0]):
            current = (bound, True)
    candidate = (cast("float", value), key == exclusive)
    if (
        current is None
        or tighter(candidate[0], current[0])
        or (candidate[0] == current[0] and candidate[1])
    ):
        current = candidate
    schema.pop(inclusive, None)
    schema.pop(exclusive, None)
    schema[exclusive if current[1] else inclusive] = current[0]
