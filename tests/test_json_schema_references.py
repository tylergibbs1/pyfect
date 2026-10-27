"""Definition allocation in ``S.to_json_schema_document`` /
``S.to_json_schema_multi_document``: Effect's ``toRepresentations``
reference titles, checked through the JSON Schema they produce.

Every expected value was printed by Effect under Node with
``SchemaRepresentation.toJsonSchemaMultiDocument(toRepresentations(...))``
over ``toCodecJson`` of the same schemas.
"""

from typing import TypedDict

from pyfect import schema as S
from pyfect.json_schema import JsonSchema
from pyfect.schema import ReferenceCandidate


class _Value(TypedDict):
    value: str


class _OtherValue(TypedDict):
    value: str


class _First(TypedDict):
    first: str


class _Second(TypedDict):
    second: str


class _Cat(TypedDict):
    name: str
    kids: tuple["_Cat", ...]


_VALUE: JsonSchema = {
    "type": "object",
    "properties": {"value": {"type": "string"}},
    "required": ["value"],
    "additionalProperties": True,
}


def _cat(ref: str) -> JsonSchema:
    return {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "kids": {"type": "array", "items": {"$ref": ref}},
        },
        "required": ["name", "kids"],
        "additionalProperties": True,
    }


def _repeated_policy(candidate: ReferenceCandidate) -> str | None:
    return f"{candidate.ast.tag}_" if candidate.occurrences > 1 else None


def test_occurrence_policy_single_root():
    """reference policies / supports policies based on occurrence counts (single)"""
    document = S.to_json_schema_multi_document(
        (S.Struct(_Value),), reference_policy=_repeated_policy
    )
    assert document.schemas == (_VALUE,)
    assert document.definitions == {}


def test_occurrence_policy_distinct_roots():
    """reference policies / supports policies based on occurrence counts (distinct):
    the shared ``String`` leaf is the repeated candidate"""
    document = S.to_json_schema_multi_document(
        (S.Struct(_Value), S.Struct(_OtherValue)), reference_policy=_repeated_policy
    )
    shared: JsonSchema = {
        "type": "object",
        "properties": {"value": {"$ref": "#/$defs/String_"}},
        "required": ["value"],
        "additionalProperties": True,
    }
    assert document.schemas == (shared, shared)
    assert document.definitions == {"String_": {"type": "string"}}


def test_occurrence_policy_repeated_root():
    """reference policies / supports policies based on occurrence counts (repeated)"""
    value = S.Struct(_Value)
    document = S.to_json_schema_multi_document((value, value), reference_policy=_repeated_policy)
    assert document.schemas == ({"$ref": "#/$defs/Objects_"}, {"$ref": "#/$defs/Objects_"})
    assert document.definitions == {"Objects_": _VALUE}


def test_repeated_root_needing_a_json_encoding_is_one_definition():
    """A root whose JSON form differs from it (a ``Number`` field) is derived
    once for the whole document, so repeating it repeats one candidate."""

    class Point(TypedDict):
        x: float

    point = S.Struct(Point)
    document = S.to_json_schema_multi_document(
        (point, point),
        reference_policy=lambda c: "Point" if c.ast.tag == "Objects" else None,
    )
    assert document.schemas == ({"$ref": "#/$defs/Point"}, {"$ref": "#/$defs/Point"})
    assert list(document.definitions) == ["Point"]


def test_policy_name_collisions_are_suffixed():
    """reference policies / suffixes policy name collisions"""
    document = S.to_json_schema_multi_document(
        (S.Struct(_First), S.Struct(_Second)),
        reference_policy=lambda c: "Model" if c.ast.tag == "Objects" else None,
    )
    assert document.schemas == ({"$ref": "#/$defs/Model"}, {"$ref": "#/$defs/Model_1"})
    assert list(document.definitions) == ["Model", "Model_1"]


def test_policy_names_ending_in_underscore_take_no_second_underscore():
    """A requested ``Model_`` collides into ``Model_1``, not ``Model__1``."""
    document = S.to_json_schema_multi_document(
        (S.Struct(_First), S.Struct(_Second)),
        reference_policy=lambda c: "Model_" if c.ast.tag == "Objects" else None,
    )
    assert document.schemas == ({"$ref": "#/$defs/Model_"}, {"$ref": "#/$defs/Model_1"})


def test_identifiers_sharing_an_encoded_owner():
    """reference policies / distinguishes identifiers that share the same encoded AST owner"""
    seen: list[tuple[str | None, int, str]] = []

    def policy(candidate: ReferenceCandidate) -> str | None:
        seen.append((candidate.identifier, candidate.occurrences, candidate.ast.tag))
        return candidate.identifier

    document = S.to_json_schema_multi_document(
        (
            S.NumberFromString.annotate(identifier="First"),
            S.NumberFromString.annotate(identifier="Second"),
        ),
        reference_policy=policy,
    )
    assert document.schemas == ({"$ref": "#/$defs/FirstEncoded"}, {"$ref": "#/$defs/SecondEncoded"})
    assert document.definitions == {
        "FirstEncoded": {"type": "string"},
        "SecondEncoded": {"type": "string"},
    }
    assert seen == [("FirstEncoded", 1, "String"), ("SecondEncoded", 1, "String")]


def test_a_policy_inlining_everything_keeps_identifiers_out():
    document = S.to_json_schema_multi_document(
        (S.String.annotate(identifier="V"),), reference_policy=lambda _: None
    )
    assert document.schemas == ({"type": "string"},)
    assert document.definitions == {}


def test_an_unnamed_recursive_schema_is_a_definition_keyed_by_its_kind():
    """A recursive node is a definition even without an identifier."""
    document = S.to_json_schema_document(S.Struct(_Cat))
    assert document.schema == {"$ref": "#/$defs/Objects_"}
    assert document.definitions == {"Objects_": _cat("#/$defs/Objects_")}


def test_a_repeated_recursive_root_is_one_definition():
    """A recursive root given twice, with a policy inlining everything, is
    still one definition (it is derived once for the document)."""
    cat = S.Struct(_Cat)
    document = S.to_json_schema_multi_document((cat, cat), reference_policy=lambda _: None)
    assert document.schemas == ({"$ref": "#/$defs/Objects_"}, {"$ref": "#/$defs/Objects_"})
    assert document.definitions == {"Objects_": _cat("#/$defs/Objects_")}


def test_an_identified_struct_referring_to_its_base():
    """A recursive TypedDict refers to its own (unannotated) struct, so an
    ``identifier`` on the annotated one names the root; the cycle through
    the array is a definition keyed by its kind (as Effect does for
    ``Base.annotate(...)`` over ``Array(suspend(() => Base))``)."""
    document = S.to_json_schema_document(S.Struct(_Cat).annotate(identifier="Cat"))
    kids: JsonSchema = {"$ref": "#/$defs/Arrays_"}
    assert document.schema == {"$ref": "#/$defs/Cat"}
    assert document.definitions == {
        "Arrays_": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"name": {"type": "string"}, "kids": kids},
                "required": ["name", "kids"],
                "additionalProperties": True,
            },
        },
        "Cat": {
            "type": "object",
            "properties": {"name": {"type": "string"}, "kids": kids},
            "required": ["name", "kids"],
            "additionalProperties": True,
        },
    }
