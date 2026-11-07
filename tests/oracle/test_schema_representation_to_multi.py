"""Ports of Effect's ``schema/representation/toRepresentations.test.ts``,
``toMultiDocument.test.ts`` and ``makeCode.test.ts``. Each test's
docstring is the Effect test title, prefixed by its ``describe`` blocks.
See ``test_schema_representation_to.py`` for the Python mappings.

Omitted:
- ``mutableKey`` and ``SchemaAST.Context`` (pyfect keys have no mutability;
  a key context is ``ast.replace_context``, tested in ``test_schema_ast.py``):
  "root identity and sharing / shares copies of the same AST with the same
  Context", "... / preserves the original owner through repeated Context
  replacements". The "contextual projections with toType / toEncoded /
  flip" titles are ported below without their ``mutableKey`` fields.
- "reference policies / exposes the projected body and counts contextual
  copies together": needs ``S.optional_key(value)`` as a standalone schema
  (an element marker in pyfect).
- "keeps projected checks and value annotations distinct from the source":
  same reason.
"""

from collections.abc import Callable
from typing import NotRequired, TypedDict

import pytest

from pyfect import effect as fx
from pyfect import schema as S
from pyfect.schema import representation as R


class _Content(TypedDict):
    text: str


def test_preserves_root_order():
    """root identity and sharing / preserves root order"""
    assert R.to_representations((S.String, S.Number, S.Boolean)) == R.MultiDocument(
        (R.String(), R.Number(), R.Boolean()), {}
    )


def test_shares_a_named_reference_between_roots():
    """root identity and sharing / shares a named reference between roots"""
    shared = S.String.annotate(identifier="Shared")
    assert R.to_representations((shared, shared)) == R.MultiDocument(
        (R.Reference("Shared"), R.Reference("Shared")),
        {"Shared": R.String(annotations={"identifier": "Shared"})},
    )


def test_shares_a_fallback_reference_across_contextual_copies_of_the_same_encoded_ast():
    """root identity and sharing / shares a fallback reference across contextual copies of the same encoded AST"""  # noqa: E501
    content = S.Struct(_Content).annotate(identifier="Tool.Content")
    first = S.to_codec_json(S.from_json_string(content))
    second = S.to_codec_json(S.from_json_string(content))
    assert first.ast is not second.ast
    assert R.to_representations((first, second)) == R.MultiDocument(
        (R.Reference("Tool.ContentEncoded"), R.Reference("Tool.ContentEncoded")),
        {
            "Tool.Content": R.Objects(
                (R.PropertySignature("text", R.String()),),
                annotations={"identifier": "Tool.Content"},
            ),
            "Tool.ContentEncoded": R.String(
                annotations={
                    "expected": "a string that will be decoded as JSON",
                    "~identifier": "Tool.Content",
                },
                content=R.Content("application/json", R.Reference("Tool.Content")),
            ),
        },
    )


def test_keeps_strings_with_different_content_distinct():
    """root identity and sharing / keeps strings with different content distinct"""
    expected = {"expected": "a string that will be decoded as JSON"}
    document = R.to_representations((S.from_json_string(S.Boolean), S.from_json_string(S.String)))
    assert document == R.MultiDocument(
        (
            R.String(annotations=expected, content=R.Content("application/json", R.Boolean())),
            R.String(annotations=expected, content=R.Content("application/json", R.String())),
        ),
        {},
    )


def test_keeps_a_checked_derivative_distinct_from_its_identified_source():
    """root identity and sharing / keeps a checked derivative distinct from its identified source"""
    base = S.String.annotate(identifier="Text")
    refined = base.check(S.is_min_length(1))
    forward = R.to_representations((base, refined))
    reversed_ = R.to_representations((refined, base))
    assert forward.representations[0] == R.Reference("Text")
    second = forward.representations[1]
    assert isinstance(second, R.String)
    assert len(second.checks) == 1
    first = reversed_.representations[0]
    assert isinstance(first, R.String)
    assert len(first.checks) == 1
    assert reversed_.representations[1] == R.Reference("Text")
    assert forward.references == {"Text": R.String(annotations={"identifier": "Text"})}
    assert reversed_.references == forward.references


def _objects_policy(candidate: R.ReferenceCandidate) -> str | None:
    return f"{candidate.ast.tag}_" if candidate.occurrences > 1 else None


def test_supports_policies_based_on_occurrence_counts():
    """reference policies / supports policies based on occurrence counts"""

    class Value(TypedDict):
        value: str

    class Equivalent(TypedDict):
        value: str

    shared = S.Struct(Value)
    equivalent = S.Struct(Equivalent)
    single = R.to_representations((shared,), reference_policy=_objects_policy)
    distinct = R.to_representations(
        (shared, equivalent),
        reference_policy=lambda c: (
            "Objects_" if c.ast.tag == "Objects" and c.occurrences > 1 else None
        ),
    )
    repeated = R.to_representations((shared, shared), reference_policy=_objects_policy)
    assert single.references == {}
    assert distinct.references == {}
    assert repeated.representations == (R.Reference("Objects_"), R.Reference("Objects_"))
    assert list(repeated.references) == ["Objects_"]


def test_suffixes_policy_name_collisions():
    """reference policies / suffixes policy name collisions"""

    class First(TypedDict):
        first: str

    class Second(TypedDict):
        second: str

    document = R.to_representations(
        (S.Struct(First), S.Struct(Second)),
        reference_policy=lambda c: "Model" if c.ast.tag == "Objects" else None,
    )
    assert document.representations == (R.Reference("Model"), R.Reference("Model_1"))
    assert list(document.references) == ["Model", "Model_1"]


def test_distinguishes_identifiers_that_share_the_same_encoded_ast_owner():
    """reference policies / distinguishes identifiers that share the same encoded AST owner"""
    first = S.NumberFromString.annotate(identifier="First")
    second = S.NumberFromString.annotate(identifier="Second")
    inputs: list[R.ReferenceCandidate] = []

    def policy(candidate: R.ReferenceCandidate) -> str | None:
        inputs.append(candidate)
        return candidate.identifier

    document = R.to_representations((first, second), reference_policy=policy)
    assert document.representations == (R.Reference("FirstEncoded"), R.Reference("SecondEncoded"))
    assert list(document.references) == ["FirstEncoded", "SecondEncoded"]
    assert [(c.identifier, c.occurrences) for c in inputs] == [
        ("FirstEncoded", 1),
        ("SecondEncoded", 1),
    ]
    assert inputs[0].ast is inputs[1].ast


def test_suffixes_different_schemas_with_the_same_identifier():
    """identifier collisions / suffixes different schemas with the same identifier"""
    first = S.String.annotate(identifier="Value", description="first")
    second = S.Number.annotate(identifier="Value", description="second")
    assert R.to_representations((first, second)) == R.MultiDocument(
        (R.Reference("Value"), R.Reference("Value_1")),
        {
            "Value": R.String(annotations={"identifier": "Value", "description": "first"}),
            "Value_1": R.Number(annotations={"identifier": "Value_1", "description": "second"}),
        },
    )


def test_suffixes_referentially_distinct_asts_with_equal_representations():
    """identifier collisions / suffixes referentially distinct ASTs with equal representations"""
    first = S.String.annotate(identifier="Value")
    second = S.String.annotate(identifier="Value")
    assert R.to_representations((first, second)) == R.MultiDocument(
        (R.Reference("Value"), R.Reference("Value_1")),
        {
            "Value": R.String(annotations={"identifier": "Value"}),
            "Value_1": R.String(annotations={"identifier": "Value_1"}),
        },
    )


def test_suffixes_fallback_and_explicit_identifier_collisions_in_encounter_order():
    """identifier collisions / suffixes fallback and explicit identifier collisions in encounter order"""  # noqa: E501
    first = S.String.annotate(**{"~identifier": "Person"})
    second = S.Number.annotate(**{"~identifier": "Person"})
    explicit = S.Boolean.annotate(identifier="PersonEncoded")
    assert R.to_representations((first, second, explicit)) == R.MultiDocument(
        (
            R.Reference("PersonEncoded"),
            R.Reference("PersonEncoded_1"),
            R.Reference("PersonEncoded_2"),
        ),
        {
            "PersonEncoded": R.String(annotations={"~identifier": "Person"}),
            "PersonEncoded_1": R.Number(annotations={"~identifier": "Person"}),
            "PersonEncoded_2": R.Boolean(annotations={"identifier": "PersonEncoded_2"}),
        },
    )


def test_wraps_the_root_representation_and_preserves_references():
    """SchemaRepresentation.toMultiDocument / wraps the root representation and preserves references"""  # noqa: E501
    reference = R.String()
    out = R.to_multi_document(R.Document(R.Reference("Value"), {"Value": reference}))
    assert out == R.MultiDocument((R.Reference("Value"),), {"Value": reference})


def test_constructs_runtime_and_type_source():
    """SchemaRepresentation.makeCode / constructs runtime and type source"""
    assert R.make_code("S.String", "str") == R.Code("S.String", "str")


class _Shared(TypedDict):
    annotated: float
    defaulted: NotRequired[float]
    required: float


def test_shares_type_references_without_losing_key_annotations_or_constructor_defaults():
    """shares type references without losing key annotations or constructor defaults"""
    value = S.NumberFromString.annotate(identifier="Value")
    schema = S.to_type(
        S.Struct(
            _Shared,
            annotated=value.annotate_key(description="field"),
            defaulted=value.pipe(S.with_constructor_default(fx.succeed(1.0))),
            required=value,
        )
    )
    document = R.to_representation(schema)
    assert list(document.references) == ["Value"]
    assert isinstance(document.representation, R.Objects)
    assert document.representation.property_signatures[0] == R.PropertySignature(
        "annotated", R.Reference("Value"), annotations={"description": "field"}
    )
    made = schema.make({"annotated": 2, "required": 3})
    assert made == {"annotated": 2, "defaulted": 1, "required": 3}


class _Field(TypedDict):
    value: float


class _Fields(TypedDict):
    optional: NotRequired[object]
    required: object


def _to_type(node: S.ast.AST) -> S.ast.AST:
    return node.to_type()


def _flip(node: S.ast.AST) -> S.ast.AST:
    return node.flip()


_PROJECTIONS: dict[str, Callable[[S.ast.AST], S.ast.AST]] = {
    "toType": _to_type,
    "toEncoded": S.ast.to_encoded,
    "flip": _flip,
}
_CONTEXTUAL_SCHEMAS = {
    "primitive": lambda: S.NumberFromString.annotate_encoded(identifier="Wire"),
    "struct": lambda: S.Struct(_Field, value=S.NumberFromString),
    "array": lambda: S.Array(S.NumberFromString),
    "tuple": lambda: S.Tuple(S.NumberFromString, S.String),
    "union": lambda: S.Union(S.NumberFromString, S.Boolean),
    "declaration": lambda: S.Option(S.NumberFromString),
    "suspend": lambda: S.suspend(lambda: S.Struct(_Field, value=S.NumberFromString)),
    "encoding chain": lambda: S.String.pipe(S.decode_to(S.NumberFromString)).annotate_encoded(
        identifier="Wire"
    ),
}


@pytest.mark.parametrize("project", list(_PROJECTIONS))
@pytest.mark.parametrize("name", list(_CONTEXTUAL_SCHEMAS))
def test_contextual_projections_share_the_reference_while_preserving_each_fields_context(
    project: str, name: str
):
    """contextual projections with $name / shares the $name reference while preserving each field's context

    ``mutableKey`` fields are left out: pyfect keys have no mutability.
    """  # noqa: E501
    projection = _PROJECTIONS[project]
    value = _CONTEXTUAL_SCHEMAS[name]().annotate(identifier="Value")
    struct = S.Struct(_Fields, optional=value, required=value)
    expected = R.to_representation(S.Bottom(projection(value.ast)))
    document = R.to_representations(
        (S.Bottom(projection(struct.ast)), S.Bottom(projection(value.ast)))
    )

    assert document.references == expected.references
    assert document.representations == (
        R.Objects(
            (
                R.PropertySignature("optional", expected.representation, is_optional=True),
                R.PropertySignature("required", expected.representation),
            )
        ),
        expected.representation,
    )


def test_contextual_projections_share_recursive_references_across_contextual_copies():
    """contextual projections with $name / shares recursive references across contextual copies

    Effect's ``mutableKey(node)`` copy is a copy with a key annotation here.
    """
    for projection in _PROJECTIONS.values():

        def thunk() -> S.ast.AST:
            return S.ast.Objects(
                (
                    S.ast.PropertySignature("value", S.NumberFromString.ast),
                    S.ast.PropertySignature(
                        "next",
                        S.ast.optional_key(node),  # noqa: B023
                        optional=True,
                    ),
                )
            )

        node = S.ast.Suspend(thunk, annotations={"identifier": "Node"})
        contextual = S.ast.replace_context(node, key_annotations={"description": "a key"})
        document = R.to_representations(
            (S.Bottom(projection(contextual)), S.Bottom(projection(node)))
        )

        assert document.representations == (R.Reference("Node"), R.Reference("Node"))
        assert list(document.references) == ["Node"]
        representation = document.references["Node"]
        assert isinstance(representation, R.Suspend)
        assert isinstance(representation.thunk, R.Objects)
        assert representation.thunk.property_signatures[1] == R.PropertySignature(
            "next", R.Reference("Node"), is_optional=True
        )
