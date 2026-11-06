"""``R.to_code_document`` (Effect's ``toCodeDocument``), which writes Python here.

Omitted: the titles of ``toCodeDocument.test.ts`` and
``toCodeDocument.annotations.test.ts``, whose expected strings are TypeScript. Each
node kind, check and declaration they cover is a case here, and is judged by what the
generated code does: it runs, it describes the same document, it accepts what the
source accepts, and pyright accepts it (``_generated_code_sample.py``).
"""

from pathlib import Path
from typing import Any, TypedDict, TypeIs

import pytest

from pyfect import json_schema as JS
from pyfect import schema as S
from pyfect.schema import representation as R

from ._code_document_cases import CASES, Point, sample_document, sample_document_representations

_SAMPLE = Path(__file__).with_name("_generated_code_sample.py")


def _module(schema: Any) -> dict[str, Any]:
    source = R.to_code_module(R.to_code_document(R.to_representations((schema,))))
    namespace: dict[str, Any] = {"__name__": "generated"}
    exec(source, namespace)
    return namespace


@pytest.mark.parametrize("name", CASES)
def test_generated_code_runs_and_round_trips(name: str) -> None:
    schema, accepted, rejected = CASES[name]
    generated = _module(schema)["Schema0"]
    is_source, is_generated = S.is_(schema), S.is_(generated)
    for value in accepted:
        assert is_source(value)
        assert is_generated(value)
    for value in rejected:
        assert not is_source(value)
        assert not is_generated(value)
    assert R.to_code_document(R.to_representations((generated,))) == R.to_code_document(
        R.to_representations((schema,))
    )


def test_the_checked_in_sample_is_what_the_generator_writes() -> None:
    """Pyright checks the sample with the rest of the project."""
    assert _SAMPLE.read_text() == R.to_code_module(sample_document())


def test_every_builtin_reviver_has_a_case() -> None:
    """A new built-in check or declaration has to be given source here too."""
    written = repr(sample_document_representations())
    missing = {reviver.id for reviver in R.BUILTIN_REVIVERS if reviver.id not in written}
    # ``S.Json`` is both ``Json`` and ``MutableJson``, which only a document can spell.
    assert missing == {"effect/schema/MutableJson"}


def _code(schema: Any) -> R.CodeDocument:
    return R.to_code_document(R.to_representations((schema,)))


@pytest.mark.parametrize(
    ("schema", "runtime", "type"),
    [
        (S.String, "S.String", "str"),
        (S.Number, "S.Number", "float"),
        (S.Finite, "S.Finite", "float"),
        (S.Null, "S.Null", "None"),
        (S.Literal("a"), 'S.Literal("a")', 'Literal["a"]'),
        (S.Literal(1.5), "S.Literal(1.5)", "float"),
        (S.Literals("a", "b"), 'S.Literals(["a", "b"])', 'Literal["a"] | Literal["b"]'),
        (S.Array(S.String), "S.Array(S.String)", "tuple[str, ...]"),
        (S.Tuple(S.String), "S.Tuple(S.String)", "tuple[str]"),
        (S.Tuple(), "S.Tuple()", "tuple[()]"),
        (
            S.Tuple(S.String, S.optional_key(S.Number)),
            "S.Tuple(S.String, S.optional_key(S.Number))",
            "tuple[str, *tuple[float, ...]]",
        ),
        (
            S.TupleWithRest(S.Tuple(S.String), S.Number, S.Boolean),
            "S.TupleWithRest(S.Tuple(S.String), S.Number, S.Boolean)",
            "tuple[str, *tuple[float, ...], bool]",
        ),
        (S.Record(S.String, S.Number), "S.Record(S.String, S.Number)", "dict[str, float]"),
        (S.Union([S.String, S.Number]), "S.Union([S.String, S.Number])", "str | float"),
        (
            S.Union([S.String, S.Number], mode="one_of"),
            'S.Union([S.String, S.Number], mode="one_of")',
            "str | float",
        ),
        (
            S.String.annotate(title="t", **{"x-a": True}),
            'S.String.annotate(title="t", **{"x-a": True})',
            "str",
        ),
        (
            S.String.check(S.is_min_length(1)),
            "S.String.check(S.is_min_length(1)"
            '.annotate(expected="a value with a length of at least 1"))',
            "str",
        ),
        (S.Option(S.String), 'S.Option(S.String).annotate(expected="Option")', "object"),
    ],
)
def test_code_of_each_node(schema: Any, runtime: str, type: str) -> None:
    code = _code(schema).codes[0]
    assert code == R.make_code(runtime, type)


def test_a_struct_is_a_typed_dict_artifact_with_its_fields_as_keywords() -> None:
    schema = R.from_json_schema_document(
        JS.from_schema_draft_2020_12(
            {
                "type": "object",
                "properties": {"a": {"type": "string"}, "b-c": {"type": "boolean"}, "class": {}},
                "required": ["a"],
                "additionalProperties": False,
            }
        )
    )
    document = _code(schema)
    assert document.codes[0].type == "_Struct"
    assert document.codes[0].runtime == (
        "S.Struct(_Struct, a=S.String, **{"
        '"b-c": S.Boolean, "class": S.Json.annotate(expected="JSON value")})'
    )
    artifact = next(a for a in document.artifacts if isinstance(a, R.TypedDictArtifact))
    assert artifact.code.runtime == (
        '_Struct = TypedDict("_Struct", {"a": str, "b-c": NotRequired[bool], '
        '"class": NotRequired[S.JsonValue]})'
    )


def test_references_come_in_dependency_order_with_sanitized_unique_names() -> None:
    inner = S.String.annotate(identifier="a-b")
    other = S.Number.annotate(identifier="a_b")
    outer = S.Array(inner).annotate(identifier="None")
    document = R.to_code_document(R.to_representations((outer, other)))
    assert [named.identifier for named in document.references.non_recursives] == [
        "A_b",
        "A_b1",
        "None1",
    ]
    assert document.references.non_recursives[2].code == R.make_code(
        'S.Array(A_b).annotate(identifier="None")', "tuple[A_bType, ...]"
    )
    assert document.codes == (R.make_code("None1", "None1Type"), R.make_code("A_b1", "A_b1Type"))


def test_a_recursive_reference_goes_through_suspend() -> None:
    document = _code(CASES["recursive"][0])
    assert document.references.non_recursives == ()
    assert "S.suspend(lambda: Tree)" in document.references.recursives["Tree"].runtime


def test_a_filter_without_source_is_an_error_naming_its_path() -> None:
    schema = S.String.check(S.make_filter(lambda s: len(s) > 0))
    with pytest.raises(R.RepresentationError) as caught:
        _code(schema)
    assert str(caught.value) == (
        "Missing to_code callback\n"
        '  at ["representations"][0]["checks"][0]["annotations"]["to_code"]'
    )


def test_a_to_code_annotation_gives_a_filter_its_source_and_imports() -> None:
    def to_code(_: R.CheckCodeInput) -> R.GeneratedCheck:
        return R.GeneratedCheck("my.check()", ("import my",))

    schema = S.String.check(S.make_filter(lambda s: len(s) > 0, to_code=to_code))
    document = _code(schema)
    assert document.codes[0].runtime == "S.String.check(my.check())"
    assert R.ImportArtifact("import my") in document.artifacts


def test_a_to_code_annotation_gives_a_declaration_its_source() -> None:
    def to_code(input: R.DeclarationCodeInput) -> R.GeneratedDeclaration:
        assert input.type_parameters == ()
        return R.GeneratedDeclaration("MySchema", "MyType")

    def is_anything(_: object) -> TypeIs[object]:
        return True

    schema = S.declare(is_anything, to_code=to_code)
    assert _code(schema).codes[0] == R.make_code("MySchema", "MyType")


def test_an_invalid_reference_is_an_error_naming_its_path() -> None:
    document = R.MultiDocument((R.Reference("Missing"),), {})
    with pytest.raises(R.RepresentationError) as caught:
        R.to_code_document(document)
    assert str(caught.value) == 'Invalid reference Missing\n  at ["representations"][0]["ref"]'


def test_a_non_string_property_name_has_no_typed_dict_key() -> None:
    document = R.MultiDocument(
        (R.Objects((R.PropertySignature(1, R.String(), False),), ()),),
        {},
    )
    with pytest.raises(R.RepresentationError):
        R.to_code_document(document)


def test_a_struct_from_a_module_keeps_decoding_through_the_generated_typed_dict() -> None:
    class Shape(TypedDict):
        a: str

    generated = _module(S.Struct(Shape))["Schema0"]
    assert S.decode_unknown_sync(generated)({"a": "x"}) == {"a": "x"}


@pytest.mark.parametrize(
    "field",
    [
        {"anyOf": [{"type": "null"}, {"type": "null"}]},
        {"anyOf": [{"type": "null"}, {"type": ["null", "string"]}]},
        {"anyOf": [{"type": ["null", "string"]}, {"type": "null"}]},
        {"type": "array", "prefixItems": [{"type": "null"}], "items": {"type": "null"}},
    ],
)
def test_a_type_met_twice_is_written_once(field: Any) -> None:
    """``None | None`` raises where a ``TypedDict`` evaluates it."""
    schema = R.from_json_schema_document(
        JS.from_schema_draft_2020_12(
            {"type": "object", "properties": {"a": field}, "additionalProperties": False}
        )
    )
    generated = _module(schema)["Schema0"]
    assert S.is_(generated)({"a": None}) == S.is_(schema)({"a": None})
    assert S.is_(generated)({})


def test_literal_types_are_written_once() -> None:
    assert _code(S.Literals(1.5, 2.5)).codes[0].type == "float"


@pytest.mark.parametrize("key", ["self", "cls"])
def test_an_annotation_may_have_any_name(key: str) -> None:
    schema = S.String.annotate(**{key: 1})
    assert schema.ast.annotations == {key: 1}
    assert (S.is_min_length(1).annotate(**{key: 1}).annotations or {})[key] == 1
    assert S.is_min_length(1).and_(S.is_max_length(2)).annotate(**{key: 1}).annotations == {key: 1}
    assert S.String.annotate_key(**{key: 1}) is not None
    assert _module(schema)["Schema0"].ast.annotations == {key: 1}


def test_a_reference_cannot_take_the_name_of_a_type_alias_or_of_a_root() -> None:
    alias = S.Tuple(
        S.String.annotate(identifier="A"), S.Number.annotate(identifier="AType")
    ).annotate(identifier="Pair")
    document = _code(alias)
    assert [named.identifier for named in document.references.non_recursives][:2] == [
        "A",
        "AType1",
    ]
    root = S.Array(S.Number.annotate(identifier="Schema0"))
    generated = _module(root)["Schema0"]
    assert S.is_(generated)((1,))
    assert not S.is_(generated)(1)


@pytest.mark.parametrize("names", [("A",), ("x", "x"), ("not a name",), ("class",), ("S",)])
def test_a_root_name_that_would_break_the_module_is_refused(names: tuple[str, ...]) -> None:
    document = R.to_code_document(
        R.to_representations((S.Array(S.String.annotate(identifier="A")), S.Number))
    )
    with pytest.raises(ValueError, match="root name"):
        R.to_code_module(document, names=names)


def test_a_module_imports_only_the_typing_names_it_uses() -> None:
    """Pyright's strict mode rejects an unused import. An index signature's types are not
    part of the struct's ``TypedDict``, so its ``Never`` and ``Literal`` are not written."""
    schema = S.StructWithRest(
        S.Struct(Point), S.Record(S.String, S.Union([S.Never, S.Literal("a")]))
    )
    source = R.to_code_module(R.to_code_document(R.to_representations((schema,))))
    assert "from typing import NotRequired, TypedDict\n" in source
