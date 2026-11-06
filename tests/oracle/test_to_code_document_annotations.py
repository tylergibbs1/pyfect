"""``toCodeDocument.annotations.test.ts``, title by title, with the expected code in Python.

Omitted:

- "preserves optional Union option properties": a ``R.Union`` holds its ``mode`` alone, with no
  ``options`` object that could be empty or hold ``undefined``.
- "preserves explicit options on an empty union", "preserves explicit options on a single-literal
  Union": ported with ``mode="one_of"``, the only mode a Python document can tell from the default.
"""

import re
from collections.abc import Callable
from typing import Any

import pytest

from pyfect import schema as S
from pyfect.schema import representation as R


def _document(*roots: Any, references: dict[str, Any] | None = None) -> R.CodeDocument:
    return R.to_code_document(R.MultiDocument(tuple(roots), references or {}))


def _check_code(make: Callable[[R.CheckCodeInput], R.GeneratedCheck]) -> dict[str, object]:
    return {"to_code": make}


def _declaration_code(
    make: Callable[[R.DeclarationCodeInput], R.GeneratedDeclaration],
) -> dict[str, object]:
    return {"to_code": make}


_STRING = R.String()
_NUMBER = R.Number()
_REFS = (_STRING,)


def _ref_name(ref: str) -> str:
    return _document(_STRING, references={ref: _NUMBER}).references.non_recursives[0].identifier


def test_preserves_explicit_options_on_an_empty_union() -> None:
    """toCodeDocument annotations / preserves explicit options on an empty
    union"""
    assert _document(R.Union((), mode="one_of")).codes[0] == R.make_code(
        'S.Union([], mode="one_of")', "Never"
    )


def test_compiles_the_is_pattern_and_option_vertical_slice() -> None:
    """toCodeDocument annotations / compiles the isPattern and Option vertical
    slice"""
    out = R.to_code_document(
        R.to_representations((S.String.check(S.is_pattern(re.compile("^a+$"))), S.Option(S.String)))
    )
    assert out.codes[0].type == "str"
    assert out.codes[0].runtime.startswith('S.String.check(S.is_pattern(re.compile("^a+$", 32))')
    assert out.codes[1] == R.make_code(
        'S.Option(S.String).annotate(expected="Option")', "fx.Option[str]"
    )
    assert R.ImportArtifact("import re") in out.artifacts
    assert R.ImportArtifact("import pyfect as fx") in out.artifacts


def test_passes_compiled_dependencies_to_checks_and_deduplicates_imports() -> None:
    """toCodeDocument annotations / passes compiled dependencies to checks and
    deduplicates imports"""

    def check(name: str) -> R.Filter:
        return R.Filter(
            R.CheckRepresentationAnnotation(f"acme/schema/{name}", None, (_STRING,)),
            _check_code(
                lambda given: R.GeneratedCheck(
                    f"custom.{name}({given.schemas[0].runtime})", ("import acme.custom as custom",)
                )
            ),
        )

    out = _document(R.String(checks=(check("first"), check("second"))))
    assert out.codes[0].runtime == (
        "S.String.check(custom.first(S.String)).check(custom.second(S.String))"
    )
    assert out.artifacts == (R.ImportArtifact("import acme.custom as custom"),)


def test_emits_supported_annotation_trees_atomically() -> None:
    """toCodeDocument annotations / emits supported annotation trees atomically"""
    runtime = (
        R.to_code_document(
            R.to_representations(
                (
                    S.String.annotate(
                        emitted={
                            "bigint": 1,
                            "nan": float("nan"),
                            "positive": float("inf"),
                            "negative": float("-inf"),
                        },
                        omitted={"value": 1, "callback": lambda: 2},
                    ),
                )
            )
        )
        .codes[0]
        .runtime
    )
    assert '"bigint": 1' in runtime
    assert '"nan": float("nan")' in runtime
    assert '"positive": float("inf")' in runtime
    assert '"negative": float("-inf")' in runtime
    assert "omitted" not in runtime
    assert "callback" not in runtime


def test_preserves_fallback_identifiers() -> None:
    """toCodeDocument annotations / preserves fallback identifiers"""
    out = _document(R.String(annotations={"~identifier": "Person"}))
    assert '.annotate(**{"~identifier": "Person"})' in out.codes[0].runtime


def test_emits_tuple_element_and_property_annotations() -> None:
    """toCodeDocument annotations / emits tuple element and property annotations"""
    out = _document(
        R.Arrays(
            elements=(
                R.Element(
                    _STRING,
                    annotations={"element": {"value": 1}, "omitted": {"callback": lambda: 1}},
                ),
            )
        ),
        R.Objects(
            property_signatures=(
                R.PropertySignature("value", _NUMBER, annotations={"property": True}),
            )
        ),
    )
    assert out.codes[0] == R.make_code(
        'S.Tuple(S.String.annotate_key(element={"value": 1}))', "tuple[str]"
    )
    assert out.codes[1] == R.make_code(
        "S.Struct(_Struct, value=S.Number.annotate_key(property=True))", "_Struct"
    )


def test_uses_group_overrides_without_visiting_children_and_preserves_abort() -> None:
    """toCodeDocument annotations / uses group overrides without visiting
    children and preserves abort"""
    visits: list[int] = []

    def child_code(_: R.CheckCodeInput) -> R.GeneratedCheck:
        visits.append(1)
        return R.GeneratedCheck("custom.child()")

    child = R.Filter(annotations={"to_code": child_code}, aborted=True)
    out = _document(
        R.String(
            checks=(
                R.FilterGroup(
                    (child,), annotations=_check_code(lambda _: R.GeneratedCheck("custom.group()"))
                ),
            )
        ),
        R.String(checks=(R.FilterGroup((child,)),)),
    )
    assert len(visits) == 1
    assert out.codes[0].runtime == "S.String.check(custom.group())"
    assert out.codes[1].runtime == "S.String.check(S.make_filter_group(custom.child().abort()))"


def test_passes_type_parameters_to_declaration_callbacks() -> None:
    """toCodeDocument annotations / passes type parameters to declaration
    callbacks"""
    declaration = R.Declaration(
        annotations=_declaration_code(
            lambda given: R.GeneratedDeclaration(
                f"custom.box({given.type_parameters[0].runtime})",
                f"custom.Box[{given.type_parameters[0].type}]",
                ("import acme.custom as custom",),
            )
        ),
        type_parameters=(_STRING,),
        representation=R.RepresentationAnnotation("acme/schema/Box"),
    )
    assert _document(declaration).codes == (R.make_code("custom.box(S.String)", "custom.Box[str]"),)


def test_reports_missing_to_code_callbacks_and_preserves_callback_exceptions() -> None:
    """toCodeDocument annotations / reports missing toCode callbacks and
    preserves callback exceptions"""
    with pytest.raises(R.RepresentationError) as raised:
        _document(R.String(checks=(R.Filter(),)))
    assert str(raised.value) == (
        "Missing to_code callback\n"
        '  at ["representations"][0]["checks"][0]["annotations"]["to_code"]'
    )

    cause = ValueError("to_code callback")

    def throwing(_: R.CheckCodeInput) -> R.GeneratedCheck:
        raise cause

    with pytest.raises(ValueError) as caught:
        _document(R.String(checks=(R.Filter(annotations={"to_code": throwing}),)))
    assert caught.value is cause


def test_generates_content_media_types_optional_pre_rest_elements_and_numeric_properties() -> None:
    """toCodeDocument annotations / generates content media types, optional
    pre-rest elements and numeric properties: a generated struct's keys are strings, which
    ``test_a_non_string_property_name_has_no_typed_dict_key`` pins"""
    out = _document(
        R.String(annotations={"contentMediaType": "text/plain"}),
        R.Arrays(elements=(R.Element(_STRING, is_optional=True),), rest=(_NUMBER,)),
    )
    assert out.codes == (
        R.make_code('S.String.annotate(contentMediaType="text/plain")', "str"),
        R.make_code(
            "S.TupleWithRest(S.Tuple(S.optional_key(S.String)), S.Number)",
            "tuple[*tuple[str | float, ...]]",
        ),
    )
    assert out.artifacts == ()


def test_emits_references_that_are_not_reachable_from_a_root() -> None:
    """toCodeDocument annotations / emits references that are not reachable from
    a root"""
    assert _document(_STRING, references={"Unused": _NUMBER}).references == R.CodeReferences(
        (R.NamedCode("Unused", R.make_code("S.Number", "float")),), {}
    )


@pytest.mark.parametrize(
    ("ref", "identifier"),
    [
        ("abc", "Abc"),
        ("Abc", "Abc"),
        ("1a", "_1a"),
        ("a-b", "A_b"),
        ("café", "Caf_"),
        ("🤖", "_"),
        ("", "_"),
    ],
    ids=[
        "capitalizes a lowercase reference identifier",
        "preserves an uppercase reference identifier",
        "prefixes a numeric reference identifier",
        "replaces punctuation in a reference identifier",
        "replaces non-ASCII characters in a reference identifier",
        "replaces an emoji reference identifier",
        "uses an underscore for an empty reference identifier",
    ],
)
def test_reference_identifiers(ref: str, identifier: str) -> None:
    """toCodeDocument annotations / capitalizes a lowercase reference identifier,
    preserves an uppercase reference identifier, prefixes a numeric reference identifier, replaces
    punctuation in a reference identifier, replaces non-ASCII characters in a reference identifier,
    replaces an emoji reference identifier, uses an underscore for an empty reference identifier"""
    assert _ref_name(ref) == identifier


def test_preserves_a_lowercase_identifier_annotation() -> None:
    """toCodeDocument annotations / preserves a lowercase identifier annotation"""
    out = R.to_code_document(
        R.to_multi_document(R.to_representation(S.String.annotate(identifier="hello")))
    )
    assert out.references.non_recursives[0] == R.NamedCode(
        "Hello", R.make_code('S.String.annotate(identifier="hello")', "str")
    )


def test_makes_colliding_sanitized_reference_identifiers_unique() -> None:
    """toCodeDocument annotations / makes colliding sanitized reference
    identifiers unique"""
    out = _document(_STRING, references={"a-b": _NUMBER, "a_b": _STRING})
    assert [n.identifier for n in out.references.non_recursives] == ["A_b", "A_b1"]


def test_orders_definitions_after_dependencies_found_in_every_representation_position() -> None:
    """toCodeDocument annotations / orders definitions after dependencies found
    in every representation position"""
    ref = R.Reference
    check = R.Filter(
        R.CheckRepresentationAnnotation("acme/schema/filter", None, (ref("C"),)),
        _check_code(lambda _: R.GeneratedCheck("S.make_filter(lambda _: True)")),
    )
    references: dict[str, R.Representation] = {
        "I": R.Suspend(ref("H")),
        "H": R.Objects(
            property_signatures=(R.PropertySignature("value", ref("G")),),
            index_signatures=(R.IndexSignature(ref("A"), ref("B")),),
        ),
        "G": R.Arrays(elements=(R.Element(ref("F")),), rest=(ref("A"),)),
        "F": R.Union((ref("E"), ref("A"))),
        "E": R.TemplateLiteral((ref("D"),)),
        "D": R.Declaration(
            annotations=_declaration_code(lambda _: R.GeneratedDeclaration("S.String", "str")),
            checks=(R.FilterGroup((check,)),),
            type_parameters=(ref("A"),),
            representation=R.RepresentationAnnotation("acme/schema/declaration"),
        ),
        "C": R.Boolean(),
        "B": _NUMBER,
        "A": _STRING,
    }
    names = [
        n.identifier for n in _document(_STRING, references=references).references.non_recursives
    ]
    for dependency, dependent in zip("ABCDEFGH", "DHDEFGHI", strict=True):
        assert names.index(dependency) < names.index(dependent)


def test_orders_a_shared_dependency_referenced_from_multiple_representation_positions_once() -> (
    None
):
    """toCodeDocument annotations / orders a shared dependency referenced from
    multiple representation positions once"""
    shared = R.Reference("A")
    out = _document(
        _STRING,
        references={
            "A": _STRING,
            "B": R.Arrays(elements=(R.Element(shared),), rest=(shared,)),
            "C": R.Objects(index_signatures=(R.IndexSignature(shared, shared),)),
        },
    )
    assert [n.identifier for n in out.references.non_recursives] == ["A", "B", "C"]


def test_generates_a_struct_with_rest_without_fixed_properties() -> None:
    """toCodeDocument annotations / generates a StructWithRest without fixed
    properties"""
    out = _document(
        R.Objects(
            index_signatures=(
                R.IndexSignature(_STRING, _NUMBER),
                R.IndexSignature(R.TemplateLiteral((R.Literal("a"), _STRING)), R.Boolean()),
            )
        )
    )
    assert out.codes[0].runtime == (
        "S.StructWithRest(S.Struct(_Struct), S.Record(S.String, S.Number), "
        'S.Record(S.TemplateLiteral(S.Literal("a"), S.String), S.Boolean))'
    )


def test_preserves_explicit_options_on_a_single_literal_union() -> None:
    """toCodeDocument annotations / preserves explicit options on a single-literal
    Union"""
    out = _document(R.Union((R.Literal("a"),), mode="one_of"))
    assert out.codes[0] == R.make_code('S.Union([S.Literal("a")], mode="one_of")', 'Literal["a"]')


def test_emits_every_member_of_a_mutually_recursive_reference_cycle() -> None:
    """toCodeDocument annotations / emits every member of a mutually recursive
    reference cycle"""
    out = _document(R.Reference("A"), references={"A": R.Reference("B"), "B": R.Reference("A")})
    assert out.references == R.CodeReferences(
        (),
        {
            "A": R.make_code("S.suspend(lambda: B)", "BType"),
            "B": R.make_code("S.suspend(lambda: A)", "AType"),
        },
    )


def test_emits_a_non_recursive_definition_that_depends_on_a_recursive_definition() -> None:
    """toCodeDocument annotations / emits a non-recursive definition that depends
    on a recursive definition"""
    out = _document(R.Reference("B"), references={"A": R.Reference("A"), "B": R.Reference("A")})
    assert out.references == R.CodeReferences(
        (R.NamedCode("B", R.make_code("A", "AType")),),
        {"A": R.make_code("S.suspend(lambda: A)", "AType")},
    )


def test_reports_missing_references_with_their_document_path() -> None:
    """toCodeDocument annotations / reports missing references with their
    document path"""
    with pytest.raises(R.RepresentationError) as raised:
        _document(R.Reference("Missing"))
    assert str(raised.value) == 'Invalid reference Missing\n  at ["representations"][0]["ref"]'


def test_reports_a_missing_reference_from_a_definition() -> None:
    """toCodeDocument annotations / reports a missing reference from a definition"""
    with pytest.raises(R.RepresentationError) as raised:
        _document(_STRING, references={"Value": R.Reference("Missing")})
    assert str(raised.value) == 'Invalid reference Missing\n  at ["references"]["Value"]["ref"]'


def test_a_module_defines_a_reference_after_the_recursive_one_it_uses() -> None:
    """Python's ``to_code_module``: a definition runs at import, so a non-recursive reference to a
    recursive one comes after it, and that one after what it uses without suspending."""
    document = _document(
        R.Reference("Wrapper"),
        references={
            "Leaf": _STRING,
            "Tree": R.Objects(
                property_signatures=(
                    R.PropertySignature("value", R.Reference("Leaf")),
                    R.PropertySignature("next", R.Reference("Tree"), is_optional=True),
                )
            ),
            "Wrapper": R.Objects(
                property_signatures=(R.PropertySignature("tree", R.Reference("Tree")),)
            ),
        },
    )
    namespace: dict[str, Any] = {"__name__": "generated"}
    exec(R.to_code_module(document), namespace)
    assert S.is_(namespace["Schema0"])({"tree": {"value": "a", "next": {"value": "b"}}})
    assert not S.is_(namespace["Schema0"])({"tree": {"value": 1}})
