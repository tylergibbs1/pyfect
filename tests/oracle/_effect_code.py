"""A schema's representation written as Effect's ``toCodeDocument`` writes it, so
ports of its importer tests compare with Effect's own expected strings, unchanged.
This is a test instrument: ``R.to_code_document`` writes Python."""

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, cast

from pyfect._js import js_number
from pyfect.schema import representation as R
from pyfect.schema.representation._code_sort import topological_sort
from pyfect.schema.representation._model import Check, Filter

_KEYS = {
    "read_only": "readOnly",
    "write_only": "writeOnly",
    "content_encoding": "contentEncoding",
    "content_media_type": "contentMediaType",
    "content_schema": "contentSchema",
}
_EXCLUDED = {
    "representation",
    "to_codec_json",
    "to_codec_string_tree",
    "to_json_schema",
    "to_equivalence",
    "to_formatter",
}
_CANONICAL = {
    'Schema.isFinite().annotate({ "expected": "a finite number" })': "Schema.Finite",
    "Schema.isInt()": "Schema.Int",
    'Schema.isInt().annotate({ "expected": "an integer" })': "Schema.Int",
}


def _text(value: str) -> str:
    out = ['"']
    for char in value:
        code = ord(char)
        if char in '"\\':
            out.append("\\" + char)
        elif char == "\n":
            out.append("\\n")
        elif char == "\t":
            out.append("\\t")
        elif code < 0x20 or 0xD800 <= code <= 0xDFFF:
            out.append(f"\\u{code:04x}")
        else:
            out.append(char)
    out.append('"')
    return "".join(out)


def _format(value: object) -> str | None:  # noqa: PLR0911
    match value:
        case None:
            return "null"
        case bool():
            return "true" if value else "false"
        case str():
            return _text(value)
        case int() | float():
            return js_number(value)
        case list() | tuple():
            items = [_format(v) for v in cast("list[object]", value)]
            return f"[{', '.join(cast('list[str]', items))}]"
        case Mapping():
            entries = [
                f"{_text(k)}: {_format(v)}" for k, v in cast("Mapping[str, object]", value).items()
            ]
            return f"{{ {', '.join(entries)} }}" if entries else "{}"
        case _:
            return None


def _annotations(annotations: Mapping[str, object] | None, method: str = "annotate") -> str:
    entries: list[str] = []
    for key, value in (annotations or {}).items():
        if key in _EXCLUDED:
            continue
        rendered = _format(value)
        if rendered is not None:
            entries.append(f"{_text(_KEYS.get(key, key))}: {rendered}")
    return f".{method}({{ {', '.join(entries)} }})" if entries else ""


def _method_name(id: str) -> str:
    return id.removeprefix("effect/schema/")


@dataclass
class _Writer:
    references: R.References
    sorted_recursives: Mapping[str, object]
    compiling_recursive: bool = False
    explicit_suspends: int = 0
    identifiers: dict[str, str] = field(default_factory=dict[str, str])

    def identifier(self, ref: str) -> str:
        known = self.identifiers.get(ref)
        if known is not None:
            return known
        out = re.sub(r"[^A-Za-z0-9_$]", "_", ref) or "_"
        if out[0].islower():
            out = out[0].upper() + out[1:]
        elif out[0].isdecimal():
            out = "_" + out
        candidate, suffix = out, 0
        while candidate == "Schema" or candidate in self.identifiers.values():
            suffix += 1
            candidate = f"{out}{suffix}"
        self.identifiers[ref] = candidate
        return candidate

    def filter_runtime(self, check: Filter, path: tuple[object, ...]) -> str:
        identity = check.representation
        assert identity is not None
        name = _method_name(identity.id)
        payload = cast("Mapping[str, Any]", identity.payload or {})
        if name == "isPattern":
            return (
                f"Schema.isPattern(new globalThis.RegExp({_text(payload['source'])}, "
                f"{_text(payload['flags'])}))"
            )
        if name == "isPropertyNames":
            type = self.recur(identity.schemas[0], path)[0]  # type: ignore[index]
            return f"Schema.isPropertyNames({type})"
        return (
            f"Schema.{name}({', '.join(cast('list[str]', [_format(v) for v in payload.values()]))})"
        )

    def check(self, check: Check, path: tuple[object, ...]) -> str:
        if isinstance(check, Filter):
            return self.filter_runtime(check, path) + _annotations(check.annotations)
        children = ", ".join(self.check(c, path) for c in check.checks)
        return f"Schema.makeFilterGroup([{children}])" + _annotations(check.annotations)

    def recur(self, node: R.Representation, path: tuple[object, ...]) -> tuple[str, str]:
        if isinstance(node, R.Reference):
            identifier = self.identifier(node.ref)
            if (
                self.compiling_recursive
                and not self.explicit_suspends
                and node.ref in self.sorted_recursives
            ):
                return f"Schema.suspend((): Schema.Codec<{identifier}> => {identifier})", identifier
            return identifier, identifier
        runtime, type = self.on(node, path)
        runtime += _annotations(node.annotations)
        for check in getattr(node, "checks", ()):
            compiled = self.check(check, path)
            runtime = (
                _CANONICAL[compiled]
                if runtime == "Schema.Number" and compiled in _CANONICAL
                else f"{runtime}.check({compiled})"
            )
        return runtime, type

    def on(self, node: R.Representation, path: tuple[object, ...]) -> tuple[str, str]:  # noqa: PLR0911, PLR0912
        match node:
            case R.Declaration():
                assert node.representation is not None
                name = _method_name(node.representation.id)
                return f"Schema.{name}", f"Schema.{name}"
            case R.Suspend(thunk=thunk):
                self.explicit_suspends += 1
                runtime, type = self.recur(thunk, path)
                self.explicit_suspends -= 1
                return f"Schema.suspend((): Schema.Codec<{type}> => {runtime})", type
            case R.Null():
                return "Schema.Null", "null"
            case R.Never():
                return "Schema.Never", "never"
            case R.Unknown():
                return "Schema.Unknown", "unknown"
            case R.String():
                return "Schema.String", "string"
            case R.Number():
                return "Schema.Number", "number"
            case R.Boolean():
                return "Schema.Boolean", "boolean"
            case R.Literal(literal=literal):
                text = cast("str", _format(literal))
                return f"Schema.Literal({text})", text
            case R.Arrays():
                return self.arrays(node, path)
            case R.Objects():
                return self.objects(node, path)
            case R.Union():
                return self.union(node, path)
            case _:
                raise AssertionError(node)

    def arrays(self, node: R.Arrays, path: tuple[object, ...]) -> tuple[str, str]:
        elements: list[tuple[str, str]] = []
        for element in node.elements:
            runtime, type = self.recur(element.type, path)
            if element.is_optional:
                elements.append((f"Schema.optionalKey({runtime})", f"({type})?"))
            else:
                elements.append((runtime, type))
        runtimes = ", ".join(e[0] for e in elements)
        types = ", ".join(e[1] for e in elements)
        if not node.rest:
            return f"Schema.Tuple([{runtimes}])", f"readonly [{types}]"
        rest = [self.recur(r, path) for r in node.rest]
        item_runtime, item_type = rest[0]
        if not elements and len(rest) == 1:
            return f"Schema.Array({item_runtime})", f"ReadonlyArray<{item_type}>"
        return (
            f"Schema.TupleWithRest(Schema.Tuple([{runtimes}]), [{', '.join(r[0] for r in rest)}])",
            f"readonly [{types}, ...Array<{item_type}>]",
        )

    def objects(self, node: R.Objects, path: tuple[object, ...]) -> tuple[str, str]:
        properties: list[tuple[str, str]] = []
        for p in node.property_signatures:
            name = _text(cast("str", p.name))
            runtime, type = self.recur(p.type, path)
            if p.is_optional:
                runtime = f"Schema.optionalKey({runtime})"
            runtime += _annotations(p.annotations, "annotateKey")
            runtime_name = f"[{name}]" if p.name == "__proto__" else name
            optional = "?" if p.is_optional else ""
            properties.append((f"{runtime_name}: {runtime}", f"readonly {name}{optional}: {type}"))
        runtimes = ", ".join(p[0] for p in properties)
        types = ", ".join(p[1] for p in properties)
        indexes = [
            (self.recur(i.parameter, path), self.recur(i.type, path)) for i in node.index_signatures
        ]
        if not indexes:
            return f"Schema.Struct({{ {runtimes} }})", f"{{ {types} }}"
        records = [f"Schema.Record({k[0]}, {v[0]})" for k, v in indexes]
        index_types = [f"readonly [x: {k[1]}]: {v[1]}" for k, v in indexes]
        if not properties and len(indexes) == 1:
            return records[0], f"{{ {index_types[0]} }}"
        return (
            f"Schema.StructWithRest(Schema.Struct({{ {runtimes} }}), [{', '.join(records)}])",
            " & ".join([f"{{ {types} }}", *(f"{{ {t} }}" for t in index_types)]),
        )

    def union(self, node: R.Union, path: tuple[object, ...]) -> tuple[str, str]:
        one_of = node.mode == "one_of"
        if not one_of and not node.types:
            return "Schema.Never", "never"
        if not one_of and all(
            isinstance(t, R.Literal) and not t.checks and t.annotations is None for t in node.types
        ):
            literals = [cast("str", _format(cast("R.Literal", t).literal)) for t in node.types]
            if len(literals) == 1:
                return f"Schema.Literal({literals[0]})", literals[0]
            return f"Schema.Literals([{', '.join(literals)}])", " | ".join(literals)
        types = [self.recur(t, path) for t in node.types]
        options = ', { mode: "oneOf" }' if one_of else ""
        return (
            f"Schema.Union([{', '.join(t[0] for t in types)}]{options})",
            " | ".join(t[1] for t in types) or "never",
        )


def effect_code(document: R.MultiDocument) -> dict[str, Any]:
    """Effect's ``toCodeDocument(document)``, without artifacts."""
    sorted = topological_sort(document.references)
    writer = _Writer(document.references, sorted.recursives)
    for key, _ in sorted.non_recursives:
        writer.identifier(key)
    for key in sorted.recursives:
        writer.identifier(key)
    non_recursives = [
        {"$ref": writer.identifier(key), "code": R.make_code(*writer.recur(node, ()))}
        for key, node in sorted.non_recursives
    ]
    recursives: dict[str, R.Code] = {}
    for key, node in sorted.recursives.items():
        writer.compiling_recursive = True
        recursives[writer.identifier(key)] = R.make_code(*writer.recur(node, ()))
        writer.compiling_recursive = False
    return {
        "codes": [R.make_code(*writer.recur(r, ())) for r in document.representations],
        "references": {"nonRecursives": non_recursives, "recursives": recursives},
    }
