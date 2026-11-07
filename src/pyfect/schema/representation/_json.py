"""The JSON form of documents (Effect's ``toJson`` / ``fromJson``).

Keys are Effect's (``_tag``, ``propertySignatures``, ``isOptional``,
``$ref``), so a document persisted by either side reads in the other.
Values whose JSON type is ambiguous carry it: a literal, an enum value
and a property name are ``{"type": ..., "value": ...}`` (a non-finite
number's value is ``"NaN"`` / ``"Infinity"`` / ``"-Infinity"``, a bigint's
its digits). Annotations keep only their JSON values; a persisted check or
declaration must carry its ``representation``. A property is written
``"isMutable": false`` (pyfect has no mutable keys); on reading, the flag
is checked and dropped.

Errors raise ``RepresentationError`` with the path of the bad value.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any, cast

from pyfect.schema import ast
from pyfect.schema.issue import Path
from pyfect.schema.representation import _model as R
from pyfect.schema.representation._from import error_with_path

type Json = R.Json
type _Object = Mapping[str, object]


def to_json(document: R.Document, /) -> Json:
    """``document`` as JSON."""
    path: Path = ("representation",)
    return {
        "representation": _encode(document.representation, path),
        "references": _encode_references(document.references),
    }


def to_json_multi_document(document: R.MultiDocument, /) -> Json:
    """``document`` as JSON, its roots in order."""
    return {
        "representations": [
            _encode(r, ("representations", i)) for i, r in enumerate(document.representations)
        ],
        "references": _encode_references(document.references),
    }


def from_json(input: object, /) -> R.Document:
    """The document ``input`` (``to_json``'s output) holds."""
    document = _object(input, ())
    return R.Document(
        _decode(_key(document, "representation", ()), ("representation",)),
        _decode_references(document),
    )


def from_json_multi_document(input: object, /) -> R.MultiDocument:
    """The multi-document ``input`` (``to_json_multi_document``'s output) holds."""
    document = _object(input, ())
    roots = _array(_key(document, "representations", ()), ("representations",))
    if not roots:
        raise error_with_path("Missing key", ("representations", 0))
    first, *rest = (_decode(r, ("representations", i)) for i, r in enumerate(roots))
    return R.MultiDocument((first, *rest), _decode_references(document))


# ------------------------------------------------------------------ encoding


def _encode_references(references: R.References) -> dict[str, Json]:
    return {key: _encode(r, ("references", key)) for key, r in references.items()}


def _prune(annotations: R.Annotations | None) -> dict[str, Json] | None:
    if not annotations:
        return None
    out = {k: _plain(v) for k, v in annotations.items() if ast.is_json(v)}
    return out or None


def _plain(value: object) -> Json:
    if isinstance(value, list | tuple):
        return [_plain(v) for v in cast("Sequence[object]", value)]
    if isinstance(value, Mapping):
        return {k: _plain(v) for k, v in cast("Mapping[str, object]", value).items()}
    return cast("Json", value)


def _with_annotations(out: dict[str, Json], annotations: R.Annotations | None) -> dict[str, Json]:
    pruned = _prune(annotations)
    if pruned is not None:
        out["annotations"] = pruned
    return out


def _number(value: float) -> Json:
    if math.isnan(value):
        return "NaN"
    if math.isinf(value):
        return "Infinity" if value > 0 else "-Infinity"
    return value


def _typed(value: object, path: Path) -> Json:
    match value:
        case bool():
            return {"type": "boolean", "value": value}
        case str():
            return {"type": "string", "value": value}
        case int():
            return {"type": "number", "value": value}
        case float():
            return {"type": "number", "value": _number(value)}
        case _:
            raise error_with_path(f"Expected a string or a number, got {value!r}", path)


def _encode_checks(checks: Sequence[R.Check], path: Path) -> list[Json]:
    return [_encode_check(c, (*path, i)) for i, c in enumerate(checks)]


def _encode_check(check: R.Check, path: Path) -> Json:
    identity = check.representation
    out: dict[str, Json] = {"_tag": check.tag}
    if identity is not None:
        encoded: dict[str, Json] = {"id": _id(identity.id, (*path, "representation", "id"))}
        encoded["payload"] = _payload(identity.payload, (*path, "representation", "payload"))
        if identity.schemas is not None:
            at = (*path, "representation", "schemas")
            encoded["schemas"] = [_encode(s, (*at, i)) for i, s in enumerate(identity.schemas)]
        out["representation"] = encoded
    _with_annotations(out, check.annotations)
    if isinstance(check, R.Filter):
        if identity is None:
            raise error_with_path("Missing key", (*path, "representation"))
        out["aborted"] = check.aborted
    else:
        out["checks"] = _encode_checks(check.checks, (*path, "checks"))
    return out


def _id(id: str, path: Path) -> str:
    if not id:
        raise error_with_path("Expected a value with a length of at least 1", path)
    return id


def _payload(payload: object, path: Path) -> Json:
    if not ast.is_json(payload):
        raise error_with_path("Expected JSON value", path)
    return _plain(payload)


def _encode_all(nodes: Sequence[R.Representation], path: Path) -> list[Json]:
    return [_encode(n, (*path, i)) for i, n in enumerate(nodes)]


def _encode(node: R.Representation, path: Path) -> Json:  # noqa: PLR0912
    match node:
        case R.Reference(ref=ref):
            return {"_tag": "Reference", "$ref": _id(ref, (*path, "$ref"))}
        case R.Suspend(thunk=thunk, annotations=annotations):
            out: dict[str, Json] = {"_tag": "Suspend", "checks": []}
            out["thunk"] = _encode(thunk, (*path, "thunk"))
            return _with_annotations(out, annotations)
        case _:
            pass
    out = {"_tag": node.tag, "checks": _encode_checks(node.checks, (*path, "checks"))}
    _with_annotations(out, node.annotations)
    match node:
        case R.Declaration(representation=identity):
            if identity is None:
                raise error_with_path("Missing key", (*path, "representation"))
            at = (*path, "representation")
            out["representation"] = {
                "id": _id(identity.id, (*at, "id")),
                "payload": _payload(identity.payload, (*at, "payload")),
            }
            out["typeParameters"] = _encode_all(node.type_parameters, (*path, "typeParameters"))
        case R.String(content=content) if content is not None:
            held: dict[str, Json] = {"mediaType": content.media_type}
            if content.schema is not None:
                held["schema"] = _encode(content.schema, (*path, "content", "schema"))
            out["content"] = held
        case R.Literal(literal=literal):
            out["literal"] = _typed(literal, (*path, "literal"))
        case R.Enum(enums=enums):
            out["enums"] = [
                [name, _typed(value, (*path, "enums", i, 1))]
                for i, (name, value) in enumerate(enums)
            ]
        case R.TemplateLiteral(parts=parts):
            out["parts"] = _encode_all(parts, (*path, "parts"))
        case R.Arrays(elements=elements, rest=rest):
            out["elements"] = [
                _with_annotations(
                    {
                        "isOptional": e.is_optional,
                        "type": _encode(e.type, (*path, "elements", i, "type")),
                    },
                    e.annotations,
                )
                for i, e in enumerate(elements)
            ]
            out["rest"] = _encode_all(rest, (*path, "rest"))
        case R.Objects(property_signatures=properties, index_signatures=indexes):
            at = (*path, "propertySignatures")
            out["propertySignatures"] = [
                _with_annotations(
                    {
                        "name": _typed(p.name, (*at, i, "name")),
                        "type": _encode(p.type, (*at, i, "type")),
                        "isOptional": p.is_optional,
                        "isMutable": False,
                    },
                    p.annotations,
                )
                for i, p in enumerate(properties)
            ]
            at = (*path, "indexSignatures")
            out["indexSignatures"] = [
                {
                    "parameter": _encode(s.parameter, (*at, i, "parameter")),
                    "type": _encode(s.type, (*at, i, "type")),
                }
                for i, s in enumerate(indexes)
            ]
        case R.Union(types=types, mode=mode):
            out["types"] = _encode_all(types, (*path, "types"))
            if mode == "one_of":
                out["options"] = {"mode": "oneOf"}
        case _:
            pass
    return out


# ------------------------------------------------------------------ decoding


def _object(value: object, path: Path) -> _Object:
    if not isinstance(value, Mapping) or not all(
        isinstance(k, str) for k in cast("Mapping[object, object]", value)
    ):
        raise error_with_path("Expected object", path)
    return cast("_Object", value)


def _array(value: object, path: Path) -> Sequence[object]:
    if not isinstance(value, list | tuple):
        raise error_with_path("Expected array", path)
    return cast("Sequence[object]", value)


def _key(obj: _Object, key: str, path: Path) -> object:
    if key not in obj:
        raise error_with_path("Missing key", (*path, key))
    return obj[key]


def _string(value: object, path: Path, *, non_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise error_with_path("Expected string", path)
    if non_empty and not value:
        raise error_with_path("Expected a value with a length of at least 1", path)
    return value


def _boolean(value: object, path: Path) -> bool:
    if not isinstance(value, bool):
        raise error_with_path("Expected boolean", path)
    return value


def _decode_references(document: _Object) -> dict[str, R.Representation]:
    references = _object(_key(document, "references", ()), ("references",))
    return {key: _decode(r, ("references", key)) for key, r in references.items()}


def _decode_annotations(obj: _Object, path: Path) -> R.Annotations | None:
    if "annotations" not in obj:
        return None
    annotations = _object(obj["annotations"], (*path, "annotations"))
    for key, value in annotations.items():
        if not ast.is_json(value):
            raise error_with_path("Expected JSON value", (*path, "annotations", key))
    return dict(annotations)


def _decode_number(value: object, path: Path) -> float:
    match value:
        case "NaN":
            return math.nan
        case "Infinity":
            return math.inf
        case "-Infinity":
            return -math.inf
        case int() | float() if not isinstance(value, bool):
            return value
        case _:
            raise error_with_path("Expected number", path)


def _decode_typed(value: object, path: Path, types: frozenset[str]) -> Any:
    obj = _object(value, path)
    kind = _key(obj, "type", path)
    raw = _key(obj, "value", path)
    at = (*path, "value")
    if kind not in types:
        raise error_with_path(f"Expected {' | '.join(sorted(types))}", (*path, "type"))
    match kind:
        case "string":
            return _string(raw, at)
        case "boolean":
            return _boolean(raw, at)
        case "bigint":
            text = _string(raw, at)
            try:
                return int(text)
            except ValueError:
                raise error_with_path("Expected a string representing a bigint", at) from None
        case _:
            number = _decode_number(raw, at)
            if "bigint" in types and not math.isfinite(number):
                raise error_with_path("Expected a finite number", at)
            return number


_LITERAL_TYPES = frozenset({"string", "number", "bigint", "boolean"})
_VALUE_TYPES = frozenset({"string", "number"})


def _decode_checks(value: object, path: Path) -> tuple[R.Check, ...]:
    return tuple(_decode_check(c, (*path, i)) for i, c in enumerate(_array(value, path)))


def _decode_identity(obj: _Object, path: Path) -> R.CheckRepresentationAnnotation:
    at = (*path, "representation")
    identity = _object(obj["representation"], at)
    payload = _key(identity, "payload", at)
    if not ast.is_json(payload):
        raise error_with_path("Expected JSON value", (*at, "payload"))
    schemas = None
    if "schemas" in identity:
        schemas = _decode_all(identity["schemas"], (*at, "schemas"))
    return R.CheckRepresentationAnnotation(
        _string(_key(identity, "id", at), (*at, "id"), non_empty=True),
        cast("Json", payload),
        schemas,
    )


def _decode_check(value: object, path: Path) -> R.Check:
    obj = _object(value, path)
    tag = _key(obj, "_tag", path)
    annotations = _decode_annotations(obj, path)
    if tag == "Filter":
        if "representation" not in obj:
            raise error_with_path("Missing key", (*path, "representation"))
        identity = _decode_identity(obj, path)
        aborted = _boolean(_key(obj, "aborted", path), (*path, "aborted"))
        return R.Filter(identity, annotations, aborted)
    if tag == "FilterGroup":
        identity = _decode_identity(obj, path) if "representation" in obj else None
        checks = _decode_checks(_key(obj, "checks", path), (*path, "checks"))
        if not checks:
            raise error_with_path("Expected a value with a length of at least 1", (*path, "checks"))
        first, *rest = checks
        return R.FilterGroup((first, *rest), identity, annotations)
    raise error_with_path('Expected "Filter" | "FilterGroup"', (*path, "_tag"))


def _decode_all(value: object, path: Path) -> tuple[R.Representation, ...]:
    return tuple(_decode(n, (*path, i)) for i, n in enumerate(_array(value, path)))


_KEYWORDS: dict[
    str,
    type[
        R.Null
        | R.Undefined
        | R.Void
        | R.ObjectKeyword
        | R.Never
        | R.Unknown
        | R.Any
        | R.Number
        | R.Boolean
        | R.BigInt
    ],
] = {
    "Null": R.Null,
    "Undefined": R.Undefined,
    "Void": R.Void,
    "ObjectKeyword": R.ObjectKeyword,
    "Never": R.Never,
    "Unknown": R.Unknown,
    "Any": R.Any,
    "Number": R.Number,
    "Boolean": R.Boolean,
    "BigInt": R.BigInt,
}


def _decode(value: object, path: Path) -> R.Representation:  # noqa: PLR0911, PLR0912, PLR0915
    obj = _object(value, path)
    tag = _key(obj, "_tag", path)
    if tag == "Reference":
        return R.Reference(_string(_key(obj, "$ref", path), (*path, "$ref"), non_empty=True))
    annotations = _decode_annotations(obj, path)
    if tag == "Suspend":
        checks = _array(_key(obj, "checks", path), (*path, "checks"))
        if checks:
            raise error_with_path("Expected no excess property", (*path, "checks", 0))
        return R.Suspend(_decode(_key(obj, "thunk", path), (*path, "thunk")), annotations)
    checks = _decode_checks(_key(obj, "checks", path), (*path, "checks"))
    common: dict[str, Any] = {"annotations": annotations, "checks": checks}
    keyword = _KEYWORDS.get(tag) if isinstance(tag, str) else None
    if keyword is not None:
        return keyword(**common)
    match tag:
        case "String":
            content = None
            if "content" in obj:
                at = (*path, "content")
                held = _object(obj["content"], at)
                media_type = _string(_key(held, "mediaType", at), (*at, "mediaType"))
                schema = _decode(held["schema"], (*at, "schema")) if "schema" in held else None
                content = R.Content(media_type, schema)
            return R.String(**common, content=content)
        case "Declaration":
            if "representation" not in obj:
                raise error_with_path("Missing key", (*path, "representation"))
            identity = _decode_identity(obj, path)
            parameters = _decode_all(_key(obj, "typeParameters", path), (*path, "typeParameters"))
            return R.Declaration(
                parameters,
                **common,
                representation=R.RepresentationAnnotation(identity.id, identity.payload),
            )
        case "Literal":
            literal = _decode_typed(_key(obj, "literal", path), (*path, "literal"), _LITERAL_TYPES)
            if isinstance(literal, float) and not math.isfinite(literal):
                raise error_with_path("Expected a finite number", (*path, "literal", "value"))
            return R.Literal(literal, **common)
        case "Enum":
            at = (*path, "enums")
            enums: list[tuple[str, R.EnumValue]] = []
            for i, entry in enumerate(_array(_key(obj, "enums", path), at)):
                pair = _array(entry, (*at, i))
                if len(pair) != 2:
                    raise error_with_path("Expected a pair", (*at, i))
                name = _string(pair[0], (*at, i, 0))
                enums.append((name, _decode_typed(pair[1], (*at, i, 1), _VALUE_TYPES)))
            return R.Enum(tuple(enums), **common)
        case "TemplateLiteral":
            return R.TemplateLiteral(
                _decode_all(_key(obj, "parts", path), (*path, "parts")), **common
            )
        case "Arrays":
            return _decode_arrays(obj, path, common)
        case "Objects":
            return _decode_objects(obj, path, common)
        case "Union":
            types = _decode_all(_key(obj, "types", path), (*path, "types"))
            mode: ast.UnionMode = "any_of"
            if "options" in obj:
                options = _object(obj["options"], (*path, "options"))
                given = options.get("mode", "anyOf")
                if given not in ("anyOf", "oneOf"):
                    raise error_with_path('Expected "anyOf" | "oneOf"', (*path, "options", "mode"))
                mode = "one_of" if given == "oneOf" else "any_of"
            return R.Union(types, mode, **common)
        case _:
            raise error_with_path(f"Unknown representation tag {tag!r}", (*path, "_tag"))


def _decode_arrays(obj: _Object, path: Path, common: dict[str, Any]) -> R.Arrays:
    at = (*path, "elements")
    elements: list[R.Element] = []
    for i, entry in enumerate(_array(_key(obj, "elements", path), at)):
        element = _object(entry, (*at, i))
        elements.append(
            R.Element(
                _decode(_key(element, "type", (*at, i)), (*at, i, "type")),
                _boolean(_key(element, "isOptional", (*at, i)), (*at, i, "isOptional")),
                _decode_annotations(element, (*at, i)),
            )
        )
    rest = _decode_all(_key(obj, "rest", path), (*path, "rest"))
    return R.Arrays(tuple(elements), rest, **common)


def _decode_objects(obj: _Object, path: Path, common: dict[str, Any]) -> R.Objects:
    at = (*path, "propertySignatures")
    properties: list[R.PropertySignature] = []
    for i, entry in enumerate(_array(_key(obj, "propertySignatures", path), at)):
        p = _object(entry, (*at, i))
        here = (*at, i)
        _boolean(_key(p, "isMutable", here), (*here, "isMutable"))
        properties.append(
            R.PropertySignature(
                _decode_typed(_key(p, "name", here), (*here, "name"), _VALUE_TYPES),
                _decode(_key(p, "type", here), (*here, "type")),
                _boolean(_key(p, "isOptional", here), (*here, "isOptional")),
                _decode_annotations(p, here),
            )
        )
    at = (*path, "indexSignatures")
    indexes: list[R.IndexSignature] = []
    for i, entry in enumerate(_array(_key(obj, "indexSignatures", path), at)):
        s = _object(entry, (*at, i))
        indexes.append(
            R.IndexSignature(
                _decode(_key(s, "parameter", (*at, i)), (*at, i, "parameter")),
                _decode(_key(s, "type", (*at, i)), (*at, i, "type")),
            )
        )
    return R.Objects(tuple(properties), tuple(indexes), **common)
