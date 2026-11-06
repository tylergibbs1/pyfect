"""Ports of Effect's ``schema/representation/toJsonSchemaMultiDocument.test.ts``
and ``schemaToJsonSchemaDocument.test.ts``. Each test's docstring is the
Effect test title, prefixed by its ``describe`` blocks.

Omitted:
- "definition canonicalization / deduplicates fallback definitions that
  share a recursive dependency": pyfect's ``to_codec_json`` builds a fresh
  recursive copy per call, so the two roots do not share ``Objects_`` (a
  difference in ``to_codec_json``, not in the compiler).
"""

from collections.abc import Callable
from typing import Any, NotRequired, TypedDict, TypeIs

import pytest

from pyfect import json_schema as JS
from pyfect import schema as S
from pyfect.schema import representation as R
from pyfect.schema import transformation as T

from ._json_schema_validator import compile as compile_validator


def _always(_: object) -> bool:
    return True


def _is_str(value: object) -> TypeIs[str]:
    return isinstance(value, str)


def _const(out: Any) -> Callable[[S.CheckContext], Any]:
    def to_json_schema(_: S.CheckContext) -> Any:
        return out

    return to_json_schema


def _two_or_more(value: str) -> bool:
    return len(value) >= 2


STRING = R.String()
BOOLEAN = R.Boolean()


def _no_reference(_: R.ReferenceCandidate) -> None:
    return None


def _same(value: object) -> object:
    return value


def identity() -> Any:
    return T.transform(decode=_same, encode=_same)


class _Content(TypedDict):
    text: str


def multi(first: S.Top, *rest: S.Top) -> Any:
    return R.to_json_schema_multi_document(R.to_representations((first, *rest)))


def fragment(out: Any, **annotations: object) -> R.Filter:
    return R.Filter(annotations={**annotations, "to_json_schema": _const(out)})


# ---------------------------------------------------- definition canonicalization


def test_deduplicates_equivalent_fallback_definitions():
    """definition canonicalization / deduplicates equivalent fallback definitions"""
    content = S.Struct(_Content).annotate(identifier="Tool.Content")
    first = S.to_codec_json(S.from_json_string(content))
    second = S.to_codec_json(S.from_json_string(content))
    output = multi(first, second)
    assert output.schemas == (
        {"$ref": "#/$defs/Tool.ContentEncoded"},
        {"$ref": "#/$defs/Tool.ContentEncoded"},
    )
    assert output.definitions == {
        "Tool.Content": {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
            "additionalProperties": True,
        },
        "Tool.ContentEncoded": {
            "type": "string",
            "contentMediaType": "application/json",
            "contentSchema": {"$ref": "#/$defs/Tool.Content"},
        },
    }


def test_does_not_deduplicate_different_fallback_definitions():
    """definition canonicalization / does not deduplicate different fallback definitions"""
    content = S.String.annotate(identifier="Fallback")
    string = S.to_codec_json(S.String.pipe(S.decode_to(content, identity())))
    boolean = S.to_codec_json(
        S.Boolean.pipe(S.decode_to(content, T.transform(decode=str, encode=lambda v: v == "true")))
    )
    output = multi(string, boolean)
    assert output.schemas == (
        {"$ref": "#/$defs/FallbackEncoded"},
        {"$ref": "#/$defs/FallbackEncoded_1"},
    )
    assert output.definitions == {
        "FallbackEncoded": {"type": "string"},
        "FallbackEncoded_1": {"type": "boolean"},
    }


def test_does_not_deduplicate_explicit_identifiers():
    """definition canonicalization / does not deduplicate explicit identifiers"""
    output = multi(
        S.String.annotate(identifier="ExplicitA"), S.String.annotate(identifier="ExplicitB")
    )
    assert output.schemas == ({"$ref": "#/$defs/ExplicitA"}, {"$ref": "#/$defs/ExplicitB"})
    assert output.definitions == {
        "ExplicitA": {"type": "string"},
        "ExplicitB": {"type": "string"},
    }


def test_escapes_canonical_fallback_references():
    """definition canonicalization / escapes canonical fallback references"""
    content = S.String.annotate(identifier="Child/~")
    output = multi(
        S.to_codec_json(S.from_json_string(content)), S.to_codec_json(S.from_json_string(content))
    )
    assert output.schemas == (
        {"$ref": "#/$defs/Child~1~0Encoded"},
        {"$ref": "#/$defs/Child~1~0Encoded"},
    )
    assert output.definitions == {
        "Child/~": {"type": "string"},
        "Child/~Encoded": {
            "type": "string",
            "contentMediaType": "application/json",
            "contentSchema": {"$ref": "#/$defs/Child~1~0"},
        },
    }


def test_invokes_each_fallback_callback_once_before_deduplicating_equivalent_output():
    """definition canonicalization / invokes each fallback callback once before deduplicating equivalent output"""  # noqa: E501
    visits: list[None] = []
    content = S.String.annotate(identifier="Callback")

    def make(reverse: bool) -> S.Top:
        def to_json_schema(_: S.CheckContext) -> Any:
            visits.append(None)
            return (
                {"maxLength": 10, "minLength": 1} if reverse else {"minLength": 1, "maxLength": 10}
            )

        encoded = S.String.check(S.make_filter(_always, to_json_schema=to_json_schema))
        return S.to_codec_json(encoded.pipe(S.decode_to(content, identity())))

    output = multi(make(False), make(True))
    assert len(visits) == 2
    assert output.schemas == (
        {"$ref": "#/$defs/CallbackEncoded"},
        {"$ref": "#/$defs/CallbackEncoded"},
    )
    assert output.definitions == {
        "CallbackEncoded": {"type": "string", "minLength": 1, "maxLength": 10}
    }


def test_reuses_a_compiled_definition_when_extracting_an_index_signature_pattern():
    """definition canonicalization / reuses a compiled definition when extracting an index signature pattern"""  # noqa: E501
    visits: list[None] = []

    def to_json_schema(_: S.CheckContext) -> Any:
        visits.append(None)
        return {"pattern": "^key$"}

    key = S.String.check(S.make_filter(_always, identifier="Key", to_json_schema=to_json_schema))
    output = multi(S.Record(key, S.String))
    assert len(visits) == 1
    assert output.schemas == (
        {
            "type": "object",
            "patternProperties": {"^key$": {"type": "string"}},
            "additionalProperties": True,
        },
    )


# ------------------------------------------------------- multi-root compilation


def test_preserves_root_order_and_shared_named_definitions():
    """multi-root compilation / preserves root order and shared named definitions"""
    a = S.String.annotate(identifier="A", description="a")
    b = S.String.annotate(identifier="B", description="b")
    output = multi(a, b, S.Tuple(a, b))
    assert output.dialect == "draft-2020-12"
    assert output.schemas == (
        {"$ref": "#/$defs/A"},
        {"$ref": "#/$defs/B"},
        {
            "type": "array",
            "prefixItems": [{"$ref": "#/$defs/A"}, {"$ref": "#/$defs/B"}],
            "minItems": 2,
            "maxItems": 2,
        },
    )
    assert output.definitions == {
        "A": {"type": "string", "description": "a"},
        "B": {"type": "string", "description": "b"},
    }


def test_emits_standard_annotations_and_one_of_unions():
    """multi-root compilation / emits standard annotations and oneOf unions"""
    annotated = R.String(
        annotations={
            "format": "email",
            "content_encoding": "base64",
            "content_media_type": "application/json",
            "content_schema": {"type": "string"},
        }
    )
    output = R.to_json_schema_multi_document(
        R.MultiDocument((annotated, R.Union((STRING, BOOLEAN), "one_of")))
    )
    assert output.schemas == (
        {
            "type": "string",
            "format": "email",
            "contentEncoding": "base64",
            "contentMediaType": "application/json",
            "contentSchema": {"type": "string"},
        },
        {"oneOf": [{"type": "string"}, {"type": "boolean"}]},
    )


def test_resolves_one_of_exactness_through_recursive_references():
    """multi-root compilation / resolves oneOf exactness through recursive references"""
    approximate = R.String(checks=(fragment(({"minLength": 1}, True)),))
    output = R.to_json_schema_multi_document(
        R.MultiDocument(
            (R.Reference("Exact"), R.Reference("Approximate")),
            {
                "Exact": R.Union((R.Reference("Exact"), BOOLEAN), "one_of"),
                "Approximate": R.Union((R.Reference("Approximate"), approximate), "one_of"),
            },
        )
    )
    assert output.schemas == ({"$ref": "#/$defs/Exact"}, {"$ref": "#/$defs/Approximate"})
    assert output.definitions == {
        "Exact": {"oneOf": [{"$ref": "#/$defs/Exact"}, {"type": "boolean"}]},
        "Approximate": {
            "anyOf": [{"$ref": "#/$defs/Approximate"}, {"type": "string", "minLength": 1}]
        },
    }


def test_uses_group_overrides_without_visiting_children_and_otherwise_falls_back_to_all_of():
    """multi-root compilation / uses group overrides without visiting children and otherwise falls back to allOf"""  # noqa: E501
    visits: list[None] = []

    def counted(_: S.CheckContext) -> Any:
        visits.append(None)
        return {"minLength": 1}

    child = R.Filter(annotations={"to_json_schema": counted})
    override = R.FilterGroup(
        (child,),
        annotations={"description": "override", "to_json_schema": _const({"format": "custom"})},
    )
    fallback = R.FilterGroup((child, R.Filter()), annotations={"description": "fallback"})
    output = R.to_json_schema_multi_document(
        R.MultiDocument((R.String(checks=(override,)), R.String(checks=(fallback,))))
    )
    assert len(visits) == 1
    assert output.schemas == (
        {"type": "string", "allOf": [{"format": "custom", "description": "override"}]},
        {"type": "string", "allOf": [{"allOf": [{"minLength": 1}], "description": "fallback"}]},
    )


def test_preserves_unknown_references_returned_by_callbacks():
    """multi-root compilation / preserves unknown references returned by callbacks"""
    reference = {"$ref": "#/$defs/Unknown"}
    output = R.to_json_schema_multi_document(
        R.MultiDocument((R.String(checks=(fragment(reference),)),))
    )
    assert output.schemas == ({"type": "string", "allOf": [reference]},)


def test_preserves_unknown_references_in_annotation_values():
    """multi-root compilation / preserves unknown references in annotation values"""
    reference = {"$ref": "#/$defs/Unknown"}
    output = R.to_json_schema_multi_document(
        R.MultiDocument((R.String(annotations={"default": reference}),))
    )
    assert output.schemas == ({"type": "string", "default": reference},)


def _record(parameter: R.Representation) -> R.Objects:
    return R.Objects((), (R.IndexSignature(parameter, STRING),))


def test_resolves_referenced_index_signature_parameters_and_stops_cycles():
    """multi-root compilation / resolves referenced index-signature parameters and stops cycles"""
    pattern = R.String(checks=(fragment({"pattern": "^a"}),))
    output = R.to_json_schema_multi_document(
        R.MultiDocument(
            (_record(R.Reference("Pattern")), _record(R.Reference("Cycle"))),
            {"Pattern": pattern, "Cycle": R.Reference("Cycle")},
        )
    )
    assert output.schemas == (
        {
            "type": "object",
            "patternProperties": {"^a": {"type": "string"}},
            "additionalProperties": True,
        },
        {"type": "object", "additionalProperties": True},
    )
    with pytest.raises(R.RepresentationError) as error:
        R.to_json_schema_document(R.Document(_record(R.Reference("Missing"))))
    path = '["representation"]["index_signatures"][0]["parameter"]["$ref"]'
    assert str(error.value) == f"Invalid reference Missing\n  at {path}"


class _Child(TypedDict):
    child: str


def test_deduplicates_fallback_definitions_after_linking_their_dependencies():
    """definition canonicalization / deduplicates fallback definitions after linking their dependencies"""  # noqa: E501
    child = S.String.annotate(identifier="Child")
    parent = S.Struct(_Child, child=child).annotate(identifier="Parent")

    def make() -> S.Top:
        encoded = S.Struct(_Child, child=S.from_json_string(child))
        return S.to_codec_json(encoded.pipe(S.decode_to(parent, identity())))

    output = multi(make(), make())
    assert output.schemas == ({"$ref": "#/$defs/ParentEncoded"}, {"$ref": "#/$defs/ParentEncoded"})
    assert output.definitions == {
        "Child": {"type": "string"},
        "ChildEncoded": {
            "type": "string",
            "contentMediaType": "application/json",
            "contentSchema": {"$ref": "#/$defs/Child"},
        },
        "ParentEncoded": {
            "type": "object",
            "properties": {"child": {"$ref": "#/$defs/ChildEncoded"}},
            "required": ["child"],
            "additionalProperties": True,
        },
    }


def test_rewrites_callback_references_without_mutating_callback_output():
    """multi-root compilation / rewrites callback references without mutating callback output"""
    default = {"$ref": "#/$defs//properties/value"}
    reference = {"$ref": "#/$defs//properties/value", "default": default}
    definition = R.String(annotations={"~identifier": "Value"})
    output = R.to_json_schema_multi_document(
        R.MultiDocument(
            (R.String(annotations={"default": -0.0}, checks=(fragment(reference),)),),
            {"A": definition, "": definition},
        )
    )
    assert reference == {"$ref": "#/$defs//properties/value", "default": default}
    assert output.schemas == (
        {
            "type": "string",
            "default": -0.0,
            "allOf": [
                {
                    "$ref": "#/$defs/A/properties/value",
                    "default": {"$ref": "#/$defs//properties/value"},
                }
            ],
        },
    )
    assert output.definitions == {"A": {"type": "string"}}


class _RequiredNode(TypedDict):
    next: "_RequiredNode"


def test_does_not_deduplicate_fallback_definitions_with_distinct_recursive_dependencies():
    """definition canonicalization / does not deduplicate fallback definitions with distinct recursive dependencies"""  # noqa: E501
    content: S.Codec[Any, Any] = S.Struct(_RequiredNode, next=S.suspend(lambda: content)).annotate(
        identifier="Node"
    )

    def make() -> S.Top:
        encoded: S.Codec[Any, Any] = S.Struct(_RequiredNode, next=S.suspend(lambda: encoded))
        return S.to_codec_json(encoded.pipe(S.decode_to(content, identity())))

    output = multi(make(), make())
    assert output.schemas == ({"$ref": "#/$defs/NodeEncoded"}, {"$ref": "#/$defs/NodeEncoded_1"})

    def node(ref: str) -> dict[str, object]:
        return {
            "type": "object",
            "properties": {"next": {"$ref": f"#/$defs/{ref}"}},
            "required": ["next"],
            "additionalProperties": True,
        }

    assert output.definitions == {
        "Suspend_": node("Suspend_"),
        "NodeEncoded": node("Suspend_"),
        "Suspend_1": node("Suspend_1"),
        "NodeEncoded_1": node("Suspend_1"),
    }


# ------------------------------------------- schemaToJsonSchemaDocument.test.ts

EMPTY = {"type": "object"}
NON_FINITE_NUMBER = {
    "anyOf": [{"type": "number"}, {"type": "string", "enum": ["Infinity", "-Infinity", "NaN"]}]
}


class _Unknown(TypedDict):
    value: object


class _Value(TypedDict):
    value: str


def _document(schema: S.Top, **options: Any) -> tuple[object, object, object]:
    out = S.to_json_schema_document(schema, **options)
    return out.dialect, out.schema, out.definitions


def test_uses_the_encoded_side_for_representations_and_json_schema():
    """Schema.toJsonSchemaDocument / uses the encoded side for representations and JSON Schema"""
    assert R.to_representation(S.FiniteFromString).representation.tag == "String"
    assert R.to_representation(S.to_type(S.FiniteFromString)).representation.tag == "Number"
    assert _document(S.FiniteFromString) == ("draft-2020-12", {"type": "string"}, {})


def test_shares_a_named_definition_across_required_and_optional_keys():
    """Schema.toJsonSchemaDocument / shares a named definition across required and optional keys when JSON codec derivation rebuilds it"""  # noqa: E501

    class Fields(TypedDict):
        required: _Unknown
        optional: NotRequired[_Unknown]

    value = S.Struct(_Unknown).annotate(identifier="Value")
    document = S.to_json_schema_document(S.Struct(Fields, required=value, optional=value))
    assert list(document.definitions) == ["Value"]
    assert document.schema == {
        "type": "object",
        "properties": {
            "required": {"$ref": "#/$defs/Value"},
            "optional": {"$ref": "#/$defs/Value"},
        },
        "required": ["required"],
        "additionalProperties": True,
    }


def test_inlines_repeated_anonymous_schemas_by_default():
    """Schema.toJsonSchemaDocument / inlines repeated anonymous schemas by default"""

    class Fields(TypedDict):
        first: _Value
        second: _Value

    shared = S.Struct(_Value)
    inner = {
        "type": "object",
        "properties": {"value": {"type": "string"}},
        "required": ["value"],
        "additionalProperties": True,
    }
    assert _document(S.Struct(Fields, first=shared, second=shared)) == (
        "draft-2020-12",
        {
            "type": "object",
            "properties": {"first": inner, "second": inner},
            "required": ["first", "second"],
            "additionalProperties": True,
        },
        {},
    )


def test_forwards_the_reference_policy_to_representation_and_json_schema_generation():
    """Schema.toJsonSchemaDocument / forwards the reference policy to representation and JSON Schema generation"""  # noqa: E501
    shared = S.String.annotate(identifier="Shared")
    assert R.to_representation(shared, reference_policy=lambda _: None).references == {}
    assert _document(shared, reference_policy=_no_reference) == (
        "draft-2020-12",
        {"type": "string"},
        {},
    )
    inputs: list[R.ReferenceCandidate] = []

    def policy(candidate: R.ReferenceCandidate) -> None:
        inputs.append(candidate)

    S.to_json_schema_document(S.DateTimeUtc.annotate(identifier="Date"), reference_policy=policy)
    assert inputs[0].ast.tag == "String"
    assert inputs[0].identifier == "DateEncoded"


def test_projects_encoded_tuple_elements_for_json_schema():
    """Schema.toJsonSchemaDocument / projects encoded tuple elements for JSON Schema"""
    assert S.to_json_schema_document(S.Tuple(S.NumberFromString)).schema == {
        "type": "array",
        "prefixItems": [{"type": "string"}],
        "minItems": 1,
        "maxItems": 1,
    }


def test_does_not_project_checks_through_an_artificial_json_encoding():
    """Schema.toJsonSchemaDocument / does not project checks through an artificial JSON encoding"""
    assert _document(S.Number.check(S.is_greater_than(0))) == (
        "draft-2020-12",
        NON_FINITE_NUMBER,
        {},
    )


def test_preserves_checks_when_no_artificial_json_encoding_is_needed():
    """Schema.toJsonSchemaDocument / preserves checks when no artificial JSON encoding is needed"""
    schema = S.Number.check(S.is_finite(), S.is_greater_than(0))
    assert _document(schema) == (
        "draft-2020-12",
        {"type": "number", "exclusiveMinimum": 0},
        {},
    )


def test_does_not_project_annotations_through_an_artificial_json_encoding():
    """Schema.toJsonSchemaDocument / does not project annotations through an artificial JSON encoding"""  # noqa: E501
    schema = S.Number.annotate(description="source description")
    expected: tuple[object, ...] = ("draft-2020-12", NON_FINITE_NUMBER, {})
    assert _document(schema) == expected
    assert _document(S.to_codec_json(schema)) == expected


def test_preserves_output_references_and_generation_options():
    """Schema.toJsonSchemaDocument / preserves output, references and generation options"""

    class Fields(TypedDict):
        first: str
        second: str
        count: float

    shared = S.String.check(S.is_min_length(2)).annotate(
        identifier="Shared", description="shared text", **{"x-consumer": "kept"}
    )
    schema = S.Struct(Fields, first=shared, second=shared, count=S.FiniteFromString).annotate(
        description="root"
    )
    document = S.to_json_schema_document(
        schema,
        on_excess_property="ignore",
        generate_descriptions=True,
        include_annotation_key=lambda key: key == "x-consumer",
    )
    assert document.schema == {
        "type": "object",
        "properties": {
            "first": {"$ref": "#/$defs/Shared"},
            "second": {"$ref": "#/$defs/Shared"},
            "count": {
                "type": "string",
                "description": "a string that will be decoded as a finite number",
            },
        },
        "required": ["first", "second", "count"],
        "additionalProperties": True,
        "description": "root",
    }
    # Python's len counts code points: minLength is exact (Effect writes 1).
    assert document.definitions == {
        "Shared": {
            "type": "string",
            "allOf": [{"minLength": 2, "description": "shared text", "x-consumer": "kept"}],
        }
    }


def test_uses_custom_compiler_annotations_without_a_central_built_in_switch():
    """Schema.toJsonSchemaDocument / uses custom compiler annotations without a central built-in switch"""  # noqa: E501
    custom = S.String.check(
        S.make_filter(
            _two_or_more,
            representation={"id": "test/schema/minTwoCharacters", "payload": None},
            to_json_schema=_const({"minLength": 2}),
        )
    )
    assert _document(custom) == ("draft-2020-12", {"type": "string", "minLength": 2}, {})


def test_emits_json_content_media_types_after_encoded_projection():
    """Schema.toJsonSchemaDocument / emits JSON content media types after encoded projection"""

    class Fields(TypedDict):
        value: float

    schema = S.from_json_string(S.Struct(Fields, value=S.FiniteFromString))
    assert S.to_json_schema_document(schema).schema == {
        "type": "string",
        "contentMediaType": "application/json",
        "contentSchema": {
            "type": "object",
            "properties": {"value": {"type": "string"}},
            "required": ["value"],
            "additionalProperties": True,
        },
    }


def test_approximates_declarations_without_a_json_codec():
    """Schema.toJsonSchemaDocument / approximates declarations without a JSON codec"""
    schema = S.declare(
        _is_str,
        representation={"id": "test/schema/opaqueString", "payload": None},
    )
    assert _document(schema) == ("draft-2020-12", {}, {})


def _encoded_string(identifier: str) -> Any:
    content = S.String.annotate(identifier=identifier)
    return S.to_codec_json(
        S.String.check(S.is_min_length(1)).pipe(
            S.decode_to(content, T.transform(decode=_same, encode=_same))
        )
    )


def _callback(ref: str) -> Any:
    return S.Unknown.check(S.make_filter(_always, to_json_schema=_const({"$ref": ref})))


def _draft_07_validator(schema: Any, definitions: Any) -> Callable[[object], bool]:
    return compile_validator(
        JS.to_document_draft_07(JS.Document("draft-2020-12", schema, definitions))
    )


@pytest.mark.parametrize(
    ("identifier", "token"),
    [
        ("Rate", "Rate"),
        ("id~a/b", "id~0a~1b"),
        ("Rate%", "Rate%25"),
        ("Rate%2F", "Rate%252F"),
        ("Rate%25", "Rate%2525"),
    ],
)
def test_rewrites_callback_references_to_the_canonical_definition(
    identifier: str, token: str
) -> None:
    """multi-root compilation / rewrites callback references to the canonical ${identifier}
    definition"""
    first, second = _encoded_string(identifier), _encoded_string(identifier)
    callback = _callback(f"#/$defs/{token}Encoded_1")
    document = R.to_representations((first, second, callback))
    assert list(document.references) == [f"{identifier}Encoded", f"{identifier}Encoded_1"]
    output = R.to_json_schema_multi_document(document)
    assert list(output.definitions) == [f"{identifier}Encoded"]
    assert output.schemas[2] == {"$ref": f"#/$defs/{token}Encoded"}
    for restored in R.from_json_schema_multi_document(output):
        assert S.is_(restored)("value") is True
        assert S.is_(restored)(1) is False


def test_rewrites_callback_references_with_encoded_leading_separators() -> None:
    """multi-root compilation / rewrites callback references with encoded leading separators"""
    callback = _callback("#%2F$defs%2FRate%25Encoded_1")
    output = R.to_json_schema_multi_document(
        R.to_representations((_encoded_string("Rate%"), _encoded_string("Rate%"), callback))
    )
    assert list(output.definitions) == ["Rate%Encoded"]
    assert output.schemas[2] == {"$ref": "#/$defs/Rate%25Encoded"}
    R.from_json_schema_multi_document(output)


@pytest.mark.parametrize(
    "ref",
    ["#/$defs/Rate%Encoded_1", "#%2F$defs%2FRate%Encoded_1", "#/$defs/Rate#Encoded_1"],
)
def test_rejects_malformed_callback_reference(ref: str) -> None:
    """multi-root compilation / rejects malformed callback reference ${JSON.stringify($ref)}"""
    with pytest.raises(Exception, match="Invalid JSON Pointer URI fragment") as caught:
        R.to_json_schema_multi_document(R.to_representations((_callback(ref),)))
    assert str(caught.value) == f'Invalid JSON Pointer URI fragment "{ref}"'


class _Box(TypedDict):
    valueEncoded_1: bool


@pytest.mark.parametrize("separator", ["/", "%2F", "%2f", "~1", "%7E1"])
def test_distinguishes_pointer_separators_from_escaped_slashes(separator: str) -> None:
    """multi-root compilation / distinguishes pointer separators from escaped slashes in
    ${separator} callback references"""
    identifier = "Box/properties/value"
    box = S.Struct(_Box).annotate(identifier="Box")
    ref = f"#/$defs/Box{separator}properties{separator}valueEncoded_1"
    output = R.to_json_schema_multi_document(
        R.to_representations(
            (_encoded_string(identifier), _encoded_string(identifier), box, _callback(ref))
        )
    )
    validate = _draft_07_validator(output.schemas[3], output.definitions)
    is_name = separator in {"~1", "%7E1"}
    assert validate(True) is (not is_name)
    assert validate("value") is is_name
    assert output.schemas[3]["$ref"] == (
        "#/$defs/Box~1properties~1valueEncoded" if is_name else ref
    )


def test_preserves_an_encoded_pointer_suffix_when_rewriting_a_percent_named_alias() -> None:
    """multi-root compilation / preserves an encoded pointer suffix when rewriting a
    percent-named alias"""
    definition = R.Objects(
        (R.PropertySignature("value%2F", R.Boolean(), False),),
        (),
        annotations={"~identifier": "Box%"},
    )
    ref = "#/$defs/Box%25_1%2Fproperties%2Fvalue%252F"
    reference = {"$ref": ref, "default": {"$ref": ref}}
    output = R.to_json_schema_multi_document(
        R.MultiDocument(
            (R.Unknown(checks=(fragment(reference),)),),
            {"Box%": definition, "Box%_1": definition},
        )
    )
    assert output.schemas[0]["$ref"] == "#/$defs/Box%25%2Fproperties%2Fvalue%252F"
    assert output.schemas[0]["default"] == {"$ref": ref}
    assert reference["$ref"] == ref
    validate = _draft_07_validator(output.schemas[0], output.definitions)
    assert validate(True) is True
    assert validate("value") is False
