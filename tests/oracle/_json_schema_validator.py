"""A small Draft 2020-12 validator standing in for Ajv in ports of Effect's round-trip
tests (no third-party dependency): the keywords those documents use, with JSON's
number rules (a boolean is not a number) and code point string lengths."""

from collections.abc import Callable, Mapping
from typing import Any, cast

from pyfect.json_pointer import parse_uri_fragment
from pyfect.json_schema import Document
from pyfect.schema import compile_ecma


def _is_type(value: object, name: str) -> bool:  # noqa: PLR0911
    match name:
        case "null":
            return value is None
        case "boolean":
            return isinstance(value, bool)
        case "string":
            return isinstance(value, str)
        case "number":
            return isinstance(value, int | float) and not isinstance(value, bool)
        case "integer":
            return _is_type(value, "number") and float(cast("float", value)).is_integer()
        case "array":
            return isinstance(value, list | tuple)
        case "object":
            return isinstance(value, Mapping)
        case _:
            raise ValueError(name)


def _equal(left: object, right: object) -> bool:
    if isinstance(left, bool) != isinstance(right, bool):
        return False
    if isinstance(left, list | tuple) and isinstance(right, list | tuple):
        a, b = cast("list[object]", left), cast("list[object]", right)
        return len(a) == len(b) and all(_equal(x, y) for x, y in zip(a, b, strict=True))
    if isinstance(left, Mapping) and isinstance(right, Mapping):
        a, b = cast("Mapping[str, object]", left), cast("Mapping[str, object]", right)
        return a.keys() == b.keys() and all(_equal(a[k], b[k]) for k in a)
    return left == right


class _Validator:
    def __init__(self, root: Any, definitions: Mapping[str, Any]) -> None:
        self.root = root
        self.definitions = definitions

    def resolve(self, ref: str) -> Any:
        path = parse_uri_fragment(ref)
        assert path is not None
        assert path[0] in {"$defs", "definitions"}
        node: Any = self.definitions
        for token in path[1:]:
            node = cast("Any", node[int(token)] if isinstance(node, list) else node[token])
        return node

    def valid(self, schema: Any, value: Any) -> bool:
        if schema is True:
            return True
        if schema is False:
            return False
        return all(
            check(self, schema[key], value, schema)
            for key, check in _KEYWORDS.items()
            if key in schema
        )


type _Check = Callable[[_Validator, Any, Any, Any], bool]


def _for_type(name: str, check: Callable[[Any, Any], bool]) -> _Check:
    return lambda _, keyword, value, __: not _is_type(value, name) or check(keyword, value)


def _type(_: _Validator, keyword: Any, value: Any, __: Any) -> bool:
    names = cast("list[str]", keyword if isinstance(keyword, list) else [keyword])
    return any(_is_type(value, name) for name in names)


def _unique(keyword: Any, value: Any) -> bool:
    items = list(value)
    return not keyword or not any(
        _equal(items[i], items[j]) for i in range(len(items)) for j in range(i)
    )


def _prefix_items(v: _Validator, keyword: Any, value: Any, _: Any) -> bool:
    if not _is_type(value, "array"):
        return True
    return all(v.valid(s, x) for s, x in zip(keyword, value, strict=False))


def _items(v: _Validator, keyword: Any, value: Any, schema: Any) -> bool:
    if not _is_type(value, "array"):
        return True
    return all(v.valid(keyword, x) for x in list(value)[len(schema.get("prefixItems", ())) :])


def _properties(v: _Validator, keyword: Any, value: Any, _: Any) -> bool:
    if not _is_type(value, "object"):
        return True
    return all(v.valid(s, value[k]) for k, s in keyword.items() if k in value)


def _pattern_properties(v: _Validator, keyword: Any, value: Any, _: Any) -> bool:
    if not _is_type(value, "object"):
        return True
    return all(
        v.valid(s, x)
        for pattern, s in keyword.items()
        for k, x in value.items()
        if compile_ecma(pattern).search(k)
    )


def _additional_properties(v: _Validator, keyword: Any, value: Any, schema: Any) -> bool:
    if not _is_type(value, "object"):
        return True
    named = schema.get("properties", {})
    patterns = schema.get("patternProperties", {})
    return all(
        v.valid(keyword, x)
        for k, x in value.items()
        if k not in named and not any(compile_ecma(p).search(k) for p in patterns)
    )


_KEYWORDS: dict[str, _Check] = {
    "type": _type,
    "const": lambda _, keyword, value, __: _equal(keyword, value),
    "enum": lambda _, keyword, value, __: any(_equal(m, value) for m in keyword),
    "$ref": lambda v, keyword, value, _: v.valid(v.resolve(keyword), value),
    "allOf": lambda v, keyword, value, _: all(v.valid(s, value) for s in keyword),
    "anyOf": lambda v, keyword, value, _: any(v.valid(s, value) for s in keyword),
    "oneOf": lambda v, keyword, value, _: sum(v.valid(s, value) for s in keyword) == 1,
    "not": lambda v, keyword, value, _: not v.valid(keyword, value),
    "minLength": _for_type("string", lambda n, s: len(s) >= n),
    "maxLength": _for_type("string", lambda n, s: len(s) <= n),
    "pattern": _for_type("string", lambda p, s: compile_ecma(p).search(s) is not None),
    "minimum": _for_type("number", lambda n, x: x >= n),
    "maximum": _for_type("number", lambda n, x: x <= n),
    "exclusiveMinimum": _for_type("number", lambda n, x: x > n),
    "exclusiveMaximum": _for_type("number", lambda n, x: x < n),
    "multipleOf": _for_type("number", lambda n, x: float(x / n).is_integer()),
    "minItems": _for_type("array", lambda n, x: len(x) >= n),
    "maxItems": _for_type("array", lambda n, x: len(x) <= n),
    "uniqueItems": _for_type("array", _unique),
    "prefixItems": _prefix_items,
    "items": _items,
    "required": _for_type("object", lambda names, x: all(k in x for k in names)),
    "minProperties": _for_type("object", lambda n, x: len(x) >= n),
    "maxProperties": _for_type("object", lambda n, x: len(x) <= n),
    "properties": _properties,
    "patternProperties": _pattern_properties,
    "additionalProperties": _additional_properties,
    "propertyNames": lambda v, keyword, value, _: (
        not _is_type(value, "object") or all(v.valid(keyword, k) for k in value)
    ),
}


def compile(document: Document[Any]) -> Callable[[object], bool]:
    validator = _Validator(document.schema, document.definitions)
    return lambda value: validator.valid(document.schema, value)
