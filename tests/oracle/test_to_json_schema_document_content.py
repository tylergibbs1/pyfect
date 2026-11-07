"""Ports of the "fromJsonString" titles of Effect's ``schema/toJsonSchemaDocument.test.ts``:
a JSON string's ``contentMediaType`` and ``contentSchema``. Each test's docstring is
the Effect test title, prefixed by its ``describe`` block; expected values are
Effect's, printed under Node where they differ from the test file (noted).

``Schema.flip(s).annotate(...)`` is ``S.flip(s).annotate(...)``; a reviver and a
replacer are Python functions of ``(key, value)``, a replacer may also be a list
of keys, as ``JSON.stringify``'s.
"""

from typing import Any, NotRequired, TypedDict, TypeIs

import pytest

from pyfect import schema as S
from pyfect.json_schema import JsonSchema
from pyfect.schema import transformation as T


def _check(
    schema: S.Top, expected: JsonSchema, definitions: dict[str, JsonSchema] | None = None
) -> None:
    document = S.to_json_schema_document(schema, on_excess_property="error")
    assert document.dialect == "draft-2020-12"
    assert document.schema == expected
    assert document.definitions == (definitions or {})


def _json(content: JsonSchema) -> JsonSchema:
    return {"type": "string", "contentMediaType": "application/json", "contentSchema": content}


class _Value(TypedDict):
    value: str


class _Flag(TypedDict):
    value: bool


_EVENT_DEFINITION: JsonSchema = {
    "type": "object",
    "properties": {"value": {"type": "string"}},
    "required": ["value"],
    "additionalProperties": False,
}


def test_uses_the_encoded_side_of_the_content_schema():
    """fromJsonString / uses the encoded side of the content schema"""
    _check(S.from_json_string(S.FiniteFromString), _json({"type": "string"}))


def test_preserves_the_content_schema_identifier_as_a_canonical_reference():
    """fromJsonString / preserves the content schema identifier as a canonical reference"""
    event = S.Struct(_Value).annotate(identifier="MyEvent")
    _check(
        S.from_json_string(event),
        {"$ref": "#/$defs/MyEventEncoded"},
        {"MyEvent": _EVENT_DEFINITION, "MyEventEncoded": _json({"$ref": "#/$defs/MyEvent"})},
    )


def test_respects_an_explicit_encoded_side_identifier():
    """fromJsonString / respects an explicit encoded-side identifier"""
    event = S.Struct(_Value).annotate(identifier="MyEvent")
    wire = S.flip(S.flip(S.from_json_string(event)).annotate(identifier="MyWireEvent"))
    _check(
        wire,
        {"$ref": "#/$defs/MyWireEvent"},
        {"MyEvent": _EVENT_DEFINITION, "MyWireEvent": _json({"$ref": "#/$defs/MyEvent"})},
    )


class _Number(TypedDict):
    value: float


class _Payload(TypedDict):
    payload: _Number


def test_nested_from_json_string():
    """fromJsonString / nested fromJsonString"""
    payload = S.from_json_string(S.Struct(_Number, value=S.FiniteFromString))
    _check(
        S.Struct(_Payload, payload=payload),
        {
            "type": "object",
            "properties": {
                "payload": _json(
                    {
                        "type": "object",
                        "properties": {"value": {"type": "string"}},
                        "required": ["value"],
                        "additionalProperties": False,
                    }
                )
            },
            "required": ["payload"],
            "additionalProperties": False,
        },
    )


class _Node(TypedDict):
    label: str
    next: NotRequired["_Node"]


def test_shares_references_through_recursive_content():
    """fromJsonString / shares references through recursive content"""
    node: Any = None
    node = S.Struct(_Node, next=S.suspend(lambda: S.from_json_string(node))).annotate(
        identifier="Node"
    )
    _check(
        S.from_json_string(node),
        {"$ref": "#/$defs/NodeEncoded"},
        {
            "Node": {
                "type": "object",
                "properties": {
                    "label": {"type": "string"},
                    "next": {"$ref": "#/$defs/NodeEncoded"},
                },
                "required": ["label"],
                "additionalProperties": False,
            },
            "NodeEncoded": _json({"$ref": "#/$defs/Node"}),
        },
    )


def test_nested_json_string_transformations():
    """fromJsonString / nested JSON string transformations"""
    _check(
        S.from_json_string(S.from_json_string(S.Boolean)),
        _json(_json({"type": "boolean"})),
    )


def test_unconstrained_content():
    """fromJsonString / unconstrained content"""
    _check(S.from_json_string(S.Unknown), _json({}))


def test_checks_added_after_from_json_string():
    """fromJsonString / checks added after fromJsonString"""
    # Effect writes ``minLength: 2``: a JavaScript length counts UTF-16 units, so
    # its bound is halved for JSON Schema's code points; a Python length counts
    # code points already, so the bound is exact.
    _check(
        S.from_json_string(S.String).check(S.is_min_length(3)),
        _json({"type": "string", "minLength": 3}),
    )


def test_omits_checks_that_cannot_describe_the_encoded_content():
    """fromJsonString / omits checks that cannot describe the encoded content"""
    _check(
        S.from_json_string(S.FiniteFromString).check(S.is_greater_than(0)),
        _json({"type": "string"}),
    )


def test_transformations_added_after_from_json_string():
    """fromJsonString / transformations added after fromJsonString"""
    yes_no = T.transform(
        decode=lambda value: "yes" if value else "no", encode=lambda value: value == "yes"
    )
    schema = S.from_json_string(S.Boolean).pipe(S.decode_to(S.Literals(["yes", "no"]), yes_no))
    _check(schema, _json({"type": "boolean"}))


def test_does_not_label_a_base64_encoded_source_as_json():
    """fromJsonString / does not label a base64 encoded source as JSON"""
    schema = S.StringFromBase64.pipe(S.decode_to(S.Unknown, T.from_json_string()))
    _check(schema, {"type": "string"})


def test_preserves_the_content_of_an_encoded_json_source():
    """fromJsonString / preserves the content of an encoded JSON source"""
    schema = S.from_json_string(S.String).pipe(S.decode_to(S.Unknown, T.from_json_string()))
    _check(schema, _json({"type": "string"}))


def _same(_: str, value: object) -> object:
    return value


def test_custom_json_parse_and_stringify_options():
    """fromJsonString / custom JSON parse and stringify options"""
    media_type_only: JsonSchema = {"type": "string", "contentMediaType": "application/json"}
    _check(S.from_json_string(S.Boolean, reviver=_same), media_type_only)
    _check(S.from_json_string(S.Boolean, replacer=_same), media_type_only)
    _check(S.from_json_string(S.Boolean, space=2), _json({"type": "boolean"}))


def test_reviver_and_replacer_run_as_json_parse_and_stringify_run_them():
    """The options themselves, against ``JSON.parse`` / ``JSON.stringify`` under Node."""
    doubled = S.from_json_string(S.Unknown, reviver=lambda _, v: v * 2 if isinstance(v, int) else v)
    assert S.decode_sync(doubled)('{"a":[1,2]}') == {"a": [2, 4]}
    picked = S.from_json_string(S.Unknown, replacer=["b", 0, "a"])
    value = {"a": 1, "b": {"a": 2, "c": 3}, "0": 4, "c": [{"a": 1, "z": 2}]}
    # node: JSON.stringify(value, ["b", 0, "a"])
    assert S.encode_sync(picked)(value) == '{"b":{"a":2},"0":4,"a":1}'

    def fail(_: str, __: object) -> object:
        raise ValueError("boom")

    # ``Effect.try`` turns what a reviver or replacer throws into the getter's issue.
    with pytest.raises(S.SchemaError, match="Expected a valid JSON string"):
        S.decode_sync(S.from_json_string(S.Unknown, reviver=fail))("1")
    with pytest.raises(S.SchemaError, match="Expected a JSON-serializable value"):
        S.encode_sync(S.from_json_string(S.Unknown, replacer=fail))(1)


_GENERATED = S.Struct(_Flag).annotate(identifier="GeneratedContent")
_GENERATED_DEFINITIONS: dict[str, JsonSchema] = {
    "GeneratedContent": {
        "type": "object",
        "properties": {"value": {"type": "boolean"}},
        "required": ["value"],
        "additionalProperties": False,
    },
    "GeneratedContentEncoded": _json({"$ref": "#/$defs/GeneratedContent"}),
}


@pytest.mark.parametrize(
    ("name", "annotations"),
    [
        (
            "ignores an explicit contentSchema annotation",
            {"contentSchema": {"type": "string", "format": "custom"}},
        ),
        (
            "preserves the generated schema for a matching explicit contentMediaType annotation",
            {"contentMediaType": "application/json"},
        ),
        (
            "ignores a different explicit contentMediaType annotation",
            {"contentMediaType": "text/plain"},
        ),
        (
            "ignores explicit contentMediaType and contentSchema annotations",
            {"contentMediaType": "text/plain", "contentSchema": {"type": "string"}},
        ),
    ],
)
def test_explicit_content_annotations(name: str, annotations: dict[str, object]):
    """fromJsonString / explicit content annotations: the generated content wins"""
    _check(
        S.from_json_string(_GENERATED).annotate_encoded(**annotations),
        {"$ref": "#/$defs/GeneratedContentEncoded"},
        _GENERATED_DEFINITIONS,
    )


def test_ignores_content_annotations_when_a_reviver_prevents_deriving_the_content_schema():
    """fromJsonString / ignores content annotations when a reviver prevents deriving the content schema"""  # noqa: E501
    schema = S.from_json_string(S.Boolean, reviver=_same).annotate_encoded(
        contentMediaType="text/plain", contentSchema={"type": "string"}
    )
    _check(schema, {"type": "string", "contentMediaType": "application/json"})


def test_to_encoded_removes_the_content_relationship():
    """fromJsonString / toEncoded removes the content relationship"""
    _check(S.to_encoded(S.from_json_string(S.Boolean)), {"type": "string"})


def test_flip_moves_the_content_string_to_the_type_side():
    """fromJsonString / flip moves the content string to the type side"""
    _check(
        S.flip(S.from_json_string(S.Struct(_Flag))),
        {
            "type": "object",
            "properties": {"value": {"type": "boolean"}},
            "required": ["value"],
            "additionalProperties": False,
        },
    )


def test_flip_writes_the_encoded_side_of_a_flipped_codec():
    """A flip's JSON form is its own encoded side (it used to be its owner's)."""
    _check(S.flip(S.FiniteFromString), {"type": "number"})


def _is_str(input: object) -> TypeIs[str]:
    return isinstance(input, str)


def test_uses_normal_approximation_rules_for_content():
    """fromJsonString / uses normal approximation rules for content"""
    opaque = S.declare(
        _is_str,
        representation={"id": "test/schema/fromJsonStringOpaqueString", "payload": None},
    )
    _check(S.from_json_string(opaque), _json({}))
