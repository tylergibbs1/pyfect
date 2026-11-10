"""``toCodeDocument.test.ts``, title by title, with the expected code spelled in Python.

Omitted, because Python has no such schema (§4 of docs/PARITY.md):

- "Undefined", "Void", "Symbol", "ObjectKeyword": JavaScript's own types.
- "should create a Symbol artifact", "should create a global Symbol artifact",
  "struct with symbol property key": no symbols, so no ``Symbol`` artifact.
- "File", "FormData", "URLSearchParams": web globals, not ported.
- "mutable properties", "optional and mutable properties": no ``mutableKey``, a
  ``TypedDict`` has no readonly keys to relax.
- "bigint literal" (both): one ``int``, so this is "number literal".
- "Date" (both): no ``Date`` schema; its checks are here on ``S.DateTimeUtc``.
- "Date & check" is "isGreaterThanDate" below.
"""

import enum
import re
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any, NotRequired, TypedDict

import pytest

from pyfect import json_schema as JS
from pyfect import schema as S
from pyfect.brand import Brand
from pyfect.schema import representation as R

_EXPECTED = r'expected="(?:\\.|[^"\\])*"(?:, )?'


def _canonical(text: str) -> str:
    """Effect's ``canonicalizeGeneratedCode``: the derived ``expected`` annotations go."""
    return (
        re.sub(_EXPECTED, "", text, flags=re.ASCII).replace(", )", ")").replace(".annotate()", "")
    )


def _canonical_code(code: R.Code) -> R.Code:
    return R.make_code(_canonical(code.runtime), code.type)


def _artifacts(document: R.CodeDocument) -> tuple[R.Artifact, ...]:
    """The artifacts but ``typing``'s names, which a module writes only if it uses them."""
    return tuple(
        a
        for a in document.artifacts
        if not (isinstance(a, R.ImportArtifact) and a.declaration.startswith("from typing import"))
    )


def _assert_document(
    document: R.MultiDocument,
    codes: R.Code | Sequence[R.Code],
    *,
    non_recursives: Sequence[R.NamedCode] = (),
    recursives: dict[str, R.Code] | None = None,
    artifacts: Sequence[R.Artifact] = (),
) -> None:
    out = R.to_code_document(document)
    expected = (codes,) if isinstance(codes, R.Code) else tuple(codes)
    assert tuple(_canonical_code(c) for c in out.codes) == expected
    assert tuple(
        R.NamedCode(n.identifier, _canonical_code(n.code)) for n in out.references.non_recursives
    ) == tuple(non_recursives)
    assert {k: _canonical_code(v) for k, v in out.references.recursives.items()} == (
        recursives or {}
    )
    assert _artifacts(out) == tuple(artifacts)


def _assert_schema(schema: Any, codes: R.Code | Sequence[R.Code], **kwargs: Any) -> None:
    _assert_document(R.to_representations((schema,)), codes, **kwargs)


def _closed_objects(js: Any) -> Any:
    if js.get("type") == "object" and "additionalProperties" not in js:
        return {**js, "additionalProperties": False}
    return js


def _assert_json_schema(schema: Any, codes: R.Code, **kwargs: Any) -> None:
    imported = R.from_json_schema_document(
        JS.from_schema_draft_2020_12(schema), on_enter=_closed_objects
    )
    _assert_schema(imported, codes, **kwargs)


def _code(runtime: str, type: str) -> R.Code:
    return R.make_code(runtime, type)


def _typed_dict(identifier: str, entries: str) -> R.TypedDictArtifact:
    return R.TypedDictArtifact(
        identifier,
        _code(f'{identifier} = TypedDict("{identifier}", {{{entries}}})', f"type[{identifier}]"),
    )


_DEFECT: Any = S.ErrorInstance.schema()
_FX = R.ImportArtifact("import pyfect as fx")
_CAUSE = R.ImportArtifact("from pyfect import cause")


def _only_runtime(schema: Any) -> str:
    return _canonical(R.to_code_document(R.to_representations((schema,))).codes[0].runtime)


# ------------------------------------------------------------------ Declaration


def test_declaration_without_a_to_code_annotation() -> None:
    """toCodeDocument / Declaration / declaration without a toCode annotation"""

    class Thing:
        pass

    with pytest.raises(R.RepresentationError) as raised:
        R.to_code_document(R.to_representations((S.instance_of(Thing),)))
    assert str(raised.value) == (
        'Missing to_code callback\n  at ["representations"][0]["annotations"]["to_code"]'
    )


def test_requires_a_to_code_callback_for_a_named_content_declaration() -> None:
    """toCodeDocument / Declaration / requires a toCode callback for a named content declaration"""

    class Thing:
        pass

    content = S.instance_of(Thing).annotate(identifier="Content")
    document = R.to_representations((S.from_json_string(content),))
    with pytest.raises(R.RepresentationError) as raised:
        R.to_code_document(document)
    assert str(raised.value) == (
        'Missing to_code callback\n  at ["references"]["Content"]["annotations"]["to_code"]'
    )


@pytest.mark.parametrize(
    ("schema", "runtime"),
    [
        (S.ErrorInstance.schema(), "S.ErrorInstance.schema()"),
        (S.ErrorInstance.schema(include_stack=True), "S.ErrorInstance.schema(include_stack=True)"),
        (
            S.ErrorInstance.schema(exclude_cause=True),
            "S.ErrorInstance.schema(exclude_cause=True)",
        ),
    ],
    ids=["Error", "Error with stack", "Error with excluded cause"],
)
def test_error(schema: Any, runtime: str) -> None:
    """toCodeDocument / Declaration / Error, Error with stack, Error with excluded cause"""
    _assert_schema(schema, _code(runtime, "S.ErrorInstance"))


def test_regexp() -> None:
    """toCodeDocument / Declaration / RegExp"""
    _assert_schema(
        S.RegExp,
        _code("S.RegExp", "re.Pattern[str]"),
        artifacts=[R.ImportArtifact("import re")],
    )


def test_url() -> None:
    """toCodeDocument / Declaration / URL"""
    _assert_schema(
        S.URL,
        _code("S.URL", "url.Url"),
        artifacts=[R.ImportArtifact("from pyfect.http import url")],
    )


def test_uint8_array() -> None:
    """toCodeDocument / Declaration / Uint8Array"""
    _assert_schema(S.Bytes, _code("S.Bytes", "bytes"))


def test_option_string() -> None:
    """toCodeDocument / Declaration / Option(String)"""
    _assert_schema(
        S.Option(S.String), _code("S.Option(S.String)", "fx.Option[str]"), artifacts=[_FX]
    )


def test_result_string_number() -> None:
    """toCodeDocument / Declaration / Result(String, Number)"""
    _assert_schema(
        S.Result(S.String, S.Number),
        _code("S.Result(S.String, S.Number)", "fx.Result[str, float]"),
        artifacts=[_FX],
    )


def test_redacted_options() -> None:
    """toCodeDocument / Declaration / Redacted options"""
    _assert_schema(
        S.Redacted(S.String, label="password", disallow_json_encode=True),
        _code(
            'S.Redacted(S.String, label="password", disallow_json_encode=True)',
            "fx.Redacted[str]",
        ),
        artifacts=[_FX],
    )


@pytest.mark.parametrize(
    ("schema", "runtime", "type", "imported"),
    [
        (
            S.CauseReason(S.String, _DEFECT),
            'S.CauseReason(S.String, cast("Any", S.ErrorInstance.schema()))',
            "cause.Reason[str]",
            _CAUSE,
        ),
        (
            S.Cause(S.String, _DEFECT),
            'S.Cause(S.String, cast("Any", S.ErrorInstance.schema()))',
            "cause.Cause[str]",
            _CAUSE,
        ),
        (
            S.Exit(S.String, S.Number, _DEFECT),
            'S.Exit(S.String, S.Number, cast("Any", S.ErrorInstance.schema()))',
            "fx.Exit[str, float]",
            _FX,
        ),
    ],
    ids=["CauseReason(String, Number)", "Cause(String, Number)", "Exit(String, Number, String)"],
)
def test_cause_and_exit(schema: Any, runtime: str, type: str, imported: R.Artifact) -> None:
    """toCodeDocument / Declaration / CauseReason(String, Number), Cause(String, Number),
    Exit(String, Number, String): the defect is a schema of ``BaseException`` here"""
    _assert_schema(schema, _code(runtime, type), artifacts=[imported])


# --------------------------------------------------------------------- keywords


@pytest.mark.parametrize(
    ("schema", "runtime", "type"),
    [
        (S.Null, "S.Null", "None"),
        (S.Never, "S.Never", "Never"),
        (S.Unknown, "S.Unknown", "object"),
        (S.Any, "S.Any", "Any"),
        (S.Boolean, "S.Boolean", "bool"),
        (S.Number, "S.Number", "float"),
        (S.BigInt, "S.BigInt", "int"),
    ],
    ids=["Null", "Never", "Unknown", "Any", "Boolean", "Number", "BigInt"],
)
def test_keywords(schema: Any, runtime: str, type: str) -> None:
    """toCodeDocument / Null, Never, Unknown, Any, Boolean, Number / Number, BigInt / BigInt"""
    _assert_schema(schema, _code(runtime, type))
    _assert_schema(
        schema.annotate(description="a"), _code(f'{runtime}.annotate(description="a")', type)
    )
    _assert_schema(schema.annotate(), _code(runtime, type))


def test_string() -> None:
    """toCodeDocument / String / String"""
    _assert_schema(S.String, _code("S.String", "str"))


def test_string_and_identifier() -> None:
    """toCodeDocument / String / String & identifier"""
    _assert_schema(
        S.String.annotate(identifier="ID"),
        _code("ID", "IDType"),
        non_recursives=[R.NamedCode("ID", _code('S.String.annotate(identifier="ID")', "str"))],
    )


def test_renames_an_identifier_that_collides_with_the_schema_import() -> None:
    """toCodeDocument / String / renames an identifier that collides with the Schema import:
    the import is ``S`` here"""
    _assert_schema(
        S.String.annotate(identifier="S"),
        _code("S1", "S1Type"),
        non_recursives=[R.NamedCode("S1", _code('S.String.annotate(identifier="S")', "str"))],
    )


def test_string_and_annotations() -> None:
    """toCodeDocument / String / String & annotations"""
    _assert_schema(
        S.String.annotate(description="a"), _code('S.String.annotate(description="a")', "str")
    )


def test_string_and_check() -> None:
    """toCodeDocument / String / String & check"""
    _assert_schema(
        S.String.check(S.is_min_length(1)), _code("S.String.check(S.is_min_length(1))", "str")
    )


def test_string_and_annotations_and_check() -> None:
    """toCodeDocument / String / String & annotations & check"""
    _assert_schema(
        S.String.annotate(description="a").check(S.is_min_length(1)),
        _code('S.String.annotate(description="a").check(S.is_min_length(1))', "str"),
    )


@pytest.mark.parametrize(
    ("check", "code"),
    [
        (S.is_min_code_points(2), "S.is_min_code_points(2)"),
        (S.is_max_code_points(3), "S.is_max_code_points(3)"),
        (S.is_between_code_points(2, 3), "S.is_between_code_points(2, 3)"),
    ],
)
def test_string_and_code_point_checks(check: Any, code: str) -> None:
    """toCodeDocument / String / String & code point checks"""
    _assert_schema(S.String.check(check), _code(f"S.String.check({code})", "str"))


def test_string_and_check_plus_annotations() -> None:
    """toCodeDocument / String / String & check + annotations"""
    _assert_schema(
        S.String.check(S.is_min_length(1, description="a")),
        _code('S.String.check(S.is_min_length(1).annotate(description="a"))', "str"),
    )


def test_string_and_check_and_annotations() -> None:
    """toCodeDocument / String / String & check & annotations"""
    _assert_schema(
        S.String.check(S.is_min_length(1)).annotate(description="a"),
        _code('S.String.check(S.is_min_length(1).annotate(description="a"))', "str"),
    )


@pytest.mark.parametrize(
    ("check", "code"),
    [
        (S.is_starting_with("a"), 'S.is_starting_with("a")'),
        (S.is_ending_with("a"), 'S.is_ending_with("a")'),
        (S.is_including("a"), 'S.is_including("a")'),
    ],
    ids=["isStartingWith", "isEndingWith", "isIncluding"],
)
def test_string_checks(check: Any, code: str) -> None:
    """toCodeDocument / String / checks / isStartingWith, isEndingWith, isIncluding"""
    _assert_schema(S.String.check(check), _code(f"S.String.check({code})", "str"))


def test_is_guid_with_annotations() -> None:
    """toCodeDocument / String / checks / isGUID with annotations"""
    _assert_schema(
        S.String.check(S.is_guid(message="message")),
        _code('S.String.check(S.is_guid().annotate(message="message"))', "str"),
    )


def test_is_ascii() -> None:
    """toCodeDocument / String / checks / isAscii"""
    _assert_schema(S.String.check(S.is_ascii()), _code("S.String.check(S.is_ascii())", "str"))


def test_finite() -> None:
    """toCodeDocument / Number / Finite"""
    _assert_schema(S.Finite, _code("S.Finite", "float"))
    _assert_schema(
        S.Number.check(S.is_finite(), S.is_greater_than(0)),
        _code("S.Finite.check(S.is_greater_than(0))", "float"),
    )


def test_int() -> None:
    """toCodeDocument / Number / Int: a document does not tell ``S.Int``, which rejects ``1.0``,
    from ``S.Number.check(S.is_int())``, so the wider one is written (§4)"""
    _assert_schema(S.Int, _code("S.Number.check(S.is_int())", "float"))


@pytest.mark.parametrize(
    ("schema", "runtime"),
    [
        (
            S.Number.annotate(description="a").check(S.is_finite()),
            'S.Number.annotate(description="a").check(S.is_finite())',
        ),
        (
            S.Number.check(S.is_greater_than(0), S.is_finite()),
            "S.Number.check(S.is_greater_than(0)).check(S.is_finite())",
        ),
        (
            S.Number.check(S.is_finite(expected="a real number")),
            'S.Number.check(S.is_finite().annotate(expected="a real number"))',
        ),
        (S.Number.check(S.is_finite().abort()), "S.Number.check(S.is_finite().abort())"),
        (
            S.Number.check(S.make_filter_group(S.is_finite(), S.is_greater_than(0))),
            "S.Number.check(S.make_filter_group(S.is_finite(), S.is_greater_than(0)))",
        ),
    ],
)
def test_number_and_non_canonical_finite_check(schema: Any, runtime: str) -> None:
    """toCodeDocument / Number / Number & non-canonical finite check"""
    if "real number" in runtime:
        code = R.to_code_document(R.to_representations((schema,))).codes[0]
        assert code == _code(runtime, "float")
    else:
        _assert_schema(schema, _code(runtime, "float"))


def test_number_and_check() -> None:
    """toCodeDocument / Number / Number & check"""
    _assert_schema(
        S.Number.check(S.is_greater_than(10)),
        _code("S.Number.check(S.is_greater_than(10))", "float"),
    )


def test_big_int_and_check() -> None:
    """toCodeDocument / BigInt / BigInt & check"""
    _assert_schema(
        S.BigInt.check(S.is_greater_than_big_int(10)),
        _code("S.BigInt.check(S.is_greater_than_big_int(10))", "int"),
    )


@pytest.mark.parametrize(
    ("value", "literal", "type"),
    [
        ("a", '"a"', 'Literal["a"]'),
        (1, "1", "Literal[1]"),
        (True, "True", "Literal[True]"),
    ],
    ids=["string literal", "number literal", "boolean literal"],
)
def test_literal(value: Any, literal: str, type: str) -> None:
    """toCodeDocument / Literal / string literal, number literal, boolean literal"""
    _assert_schema(S.Literal(value), _code(f"S.Literal({literal})", type))
    _assert_schema(
        S.Literal(value).annotate(description="a"),
        _code(f'S.Literal({literal}).annotate(description="a")', type),
    )


@pytest.mark.parametrize(
    ("members", "rendered"),
    [
        ({"A": "a", "B": "b"}, '"A": "a", "B": "b"'),
        ({"One": 1, "Two": 2}, '"One": 1, "Two": 2'),
        ({"A": "a", "One": 1}, '"A": "a", "One": 1'),
    ],
    ids=["string values", "number values", "mixed values"],
)
def test_enum(members: dict[str, Any], rendered: str) -> None:
    """toCodeDocument / Enum / string values, number values, mixed values"""
    artifacts = [
        R.ImportArtifact("import enum"),
        R.EnumArtifact(
            "_Enum", _code(f'_Enum = enum.Enum("_Enum", {{{rendered}}})', "type[_Enum]")
        ),
    ]
    source = enum.Enum("E", members)
    _assert_schema(S.Enum(source), _code("S.Enum(_Enum)", "_Enum"), artifacts=artifacts)
    _assert_schema(
        S.Enum(source).annotate(description="a"),
        _code('S.Enum(_Enum).annotate(description="a")', "_Enum"),
        artifacts=artifacts,
    )


# -------------------------------------------------------------- TemplateLiteral


@pytest.mark.parametrize(
    ("parts", "runtime"),
    [
        ((), "S.TemplateLiteral()"),
        ((S.Literal("a"),), 'S.TemplateLiteral(S.Literal("a"))'),
        ((S.Literal(1),), "S.TemplateLiteral(S.Literal(1))"),
        (
            (S.Literal("a"), S.Literal("b"), S.Literal("c")),
            'S.TemplateLiteral(S.Literal("a"), S.Literal("b"), S.Literal("c"))',
        ),
        ((S.Literal("a b"), S.String), 'S.TemplateLiteral(S.Literal("a b"), S.String)'),
        ((S.Literal("\n"), S.String), 'S.TemplateLiteral(S.Literal("\\n"), S.String)'),
        ((S.String,), "S.TemplateLiteral(S.String)"),
        ((S.Number,), "S.TemplateLiteral(S.Number)"),
        ((S.BigInt,), "S.TemplateLiteral(S.BigInt)"),
        ((S.String, S.Number), "S.TemplateLiteral(S.String, S.Number)"),
        ((S.String, S.Literal("a")), 'S.TemplateLiteral(S.String, S.Literal("a"))'),
        ((S.BigInt, S.Literal("a")), 'S.TemplateLiteral(S.BigInt, S.Literal("a"))'),
        ((S.Literal("a"), S.String), 'S.TemplateLiteral(S.Literal("a"), S.String)'),
        ((S.Literal("a"), S.BigInt), 'S.TemplateLiteral(S.Literal("a"), S.BigInt)'),
        (
            (S.String, S.Literal("-"), S.Number),
            'S.TemplateLiteral(S.String, S.Literal("-"), S.Number)',
        ),
        (
            (S.Literal("a"), S.TemplateLiteral(S.String, S.Literals(["-", "+"]), S.Number)),
            'S.TemplateLiteral(S.Literal("a"), '
            'S.TemplateLiteral(S.String, S.Literals(["-", "+"]), S.Number))',
        ),
        (
            (S.Literal("a"), S.Union([S.String, S.Number])),
            'S.TemplateLiteral(S.Literal("a"), S.Union([S.String, S.Number]))',
        ),
        ((S.Literals(["a", "b"]), S.String), 'S.TemplateLiteral(S.Literals(["a", "b"]), S.String)'),
        (
            (S.Union([S.Literal("a"), S.Literal("b")]), S.String, S.Union([S.Number, S.BigInt])),
            'S.TemplateLiteral(S.Literals(["a", "b"]), S.String, S.Union([S.Number, S.BigInt]))',
        ),
    ],
    ids=[
        "empty template literal",
        "string literal",
        "number literal",
        "multiple consecutive literals",
        "special characters in literals (space)",
        "special characters in literals (newline)",
        "only schemas (string)",
        "only schemas (number)",
        "only schemas (bigint)",
        "only schemas (two)",
        "schema & literal",
        "schema & literal (bigint)",
        "literal & schema",
        "literal & schema (bigint)",
        "schema & literal & schema",
        "TemplateLiteral as part",
        "Union as part",
        "Literals as part",
        "multiple unions",
    ],
)
def test_template_literal(parts: tuple[Any, ...], runtime: str) -> None:
    """toCodeDocument / TemplateLiteral / empty template literal, string literal, number literal,
    multiple consecutive literals, special characters in literals, only schemas, schema & literal,
    literal & schema, schema & literal & schema, TemplateLiteral as part, Union as part,
    Literals as part, multiple unions: a Python type has no template, so each is ``str``"""
    _assert_schema(S.TemplateLiteral(*parts), _code(runtime, "str"))


@pytest.mark.parametrize("literal", ["`", "${number}", "\\"])
def test_special_characters_in_literals_are_read_back(literal: Any) -> None:
    """toCodeDocument / TemplateLiteral / special characters in literals"""
    runtime = _only_runtime(S.TemplateLiteral(S.Literal(literal)))
    namespace: dict[str, Any] = {"S": S}
    assert S.is_(eval(runtime, namespace))(literal)


def test_a_template_literal_annotated() -> None:
    """toCodeDocument / TemplateLiteral / schema & literal & schema (annotated)"""
    _assert_schema(
        S.TemplateLiteral(S.String, S.Literal("-"), S.Number).annotate(description="ad"),
        _code(
            'S.TemplateLiteral(S.String, S.Literal("-"), S.Number).annotate(description="ad")',
            "str",
        ),
    )


def test_omits_brands_from_parts() -> None:
    """toCodeDocument / TemplateLiteral / omits brands from parts"""
    string_part = Brand[str, Any].nominal()
    number_part = Brand[float, Any].nominal()
    schema = S.TemplateLiteral(
        S.String.pipe(S.from_brand(string_part)),
        S.Union(
            [S.Number.pipe(S.from_brand(number_part)), S.String.pipe(S.from_brand(string_part))]
        ),
    )
    _assert_schema(
        schema, _code("S.TemplateLiteral(S.String, S.Union([S.Number, S.String]))", "str")
    )


def test_uses_references_for_branded_parts() -> None:
    """toCodeDocument / TemplateLiteral / uses references for branded parts"""
    part = S.String.pipe(S.from_brand(Brand[str, Any].nominal())).annotate(identifier="Part")
    code = R.to_code_document(R.to_representations((S.TemplateLiteral(part),))).codes[0]
    assert code == _code("S.TemplateLiteral(Part)", "str")


def test_does_not_expand_combinations_of_unions() -> None:
    """toCodeDocument / TemplateLiteral / does not expand combinations of unions"""
    part = S.Literals(["a", "b"])
    code = R.to_code_document(R.to_representations((S.TemplateLiteral(*[part] * 20),))).codes[0]
    assert code.type == "str"
    assert len(code.runtime) < 500


# ------------------------------------------------------------------------ Tuple


def test_empty_tuple() -> None:
    """toCodeDocument / Tuple / empty tuple"""
    _assert_schema(S.Tuple(), _code("S.Tuple()", "tuple[()]"))
    _assert_schema(
        S.Tuple().annotate(description="a"),
        _code('S.Tuple().annotate(description="a")', "tuple[()]"),
    )


def test_required_element() -> None:
    """toCodeDocument / Tuple / required element"""
    _assert_schema(S.Tuple(S.String), _code("S.Tuple(S.String)", "tuple[str]"))
    _assert_schema(
        S.Tuple(S.String).annotate(description="a"),
        _code('S.Tuple(S.String).annotate(description="a")', "tuple[str]"),
    )


def test_optional_element() -> None:
    """toCodeDocument / Tuple / optional element: Python's tuple types have no optional element,
    so the optional ones are the unbounded tail"""
    _assert_schema(
        S.Tuple(S.optional_key(S.String)),
        _code("S.Tuple(S.optional_key(S.String))", "tuple[*tuple[str, ...]]"),
    )
    _assert_schema(
        S.Tuple(S.optional_key(S.String)).annotate(description="a"),
        _code(
            'S.Tuple(S.optional_key(S.String)).annotate(description="a")',
            "tuple[*tuple[str, ...]]",
        ),
    )


def test_optional_union_elements() -> None:
    """toCodeDocument / Tuple / optional union elements"""
    _assert_schema(
        S.Tuple(S.optional_key(S.Union([S.String, S.Number]))),
        _code(
            "S.Tuple(S.optional_key(S.Union([S.String, S.Number])))",
            "tuple[*tuple[str | float, ...]]",
        ),
    )
    _assert_schema(
        S.Tuple(S.optional_key(S.Literals(["a", "b"]))),
        _code(
            'S.Tuple(S.optional_key(S.Literals(["a", "b"])))',
            'tuple[*tuple[Literal["a"] | Literal["b"], ...]]',
        ),
    )


def test_optional_readonly_tuple_element() -> None:
    """toCodeDocument / Tuple / optional readonly tuple element"""
    _assert_schema(
        S.Tuple(S.optional_key(S.Tuple(S.String))),
        _code("S.Tuple(S.optional_key(S.Tuple(S.String)))", "tuple[*tuple[tuple[str], ...]]"),
    )


def test_optional_union_element_imported_from_json_schema() -> None:
    """toCodeDocument / Tuple / optional union element imported from JSON Schema"""
    _assert_json_schema(
        {
            "type": "array",
            "prefixItems": [{"anyOf": [{"type": "string"}, {"type": "number"}]}],
            "items": False,
        },
        _code(
            "S.Tuple(S.optional_key(S.Union([S.String, S.Finite])))",
            "tuple[*tuple[str | float, ...]]",
        ),
    )


def test_tuple_annotate_key() -> None:
    """toCodeDocument / Tuple / annotateKey"""
    _assert_schema(
        S.Tuple(S.String.annotate_key(description="a")),
        _code('S.Tuple(S.String.annotate_key(description="a"))', "tuple[str]"),
    )


def test_array() -> None:
    """toCodeDocument / Array"""
    _assert_schema(S.Array(S.String), _code("S.Array(S.String)", "tuple[str, ...]"))
    _assert_schema(
        S.Array(S.String).annotate(description="a"),
        _code('S.Array(S.String).annotate(description="a")', "tuple[str, ...]"),
    )


def test_tuple_with_rest() -> None:
    """toCodeDocument / TupleWithRest"""
    _assert_schema(
        S.TupleWithRest(S.Tuple(S.optional_key(S.Union([S.String, S.Number]))), S.Boolean),
        _code(
            "S.TupleWithRest(S.Tuple(S.optional_key(S.Union([S.String, S.Number]))), S.Boolean)",
            "tuple[*tuple[str | float | bool, ...]]",
        ),
    )
    _assert_schema(
        S.TupleWithRest(S.Tuple(S.String), S.Number),
        _code("S.TupleWithRest(S.Tuple(S.String), S.Number)", "tuple[str, *tuple[float, ...]]"),
    )
    _assert_schema(
        S.TupleWithRest(S.Tuple(S.String), S.Number).annotate(description="a"),
        _code(
            'S.TupleWithRest(S.Tuple(S.String), S.Number).annotate(description="a")',
            "tuple[str, *tuple[float, ...]]",
        ),
    )
    _assert_schema(
        S.TupleWithRest(S.Tuple(S.String), S.Number, S.Boolean),
        _code(
            "S.TupleWithRest(S.Tuple(S.String), S.Number, S.Boolean)",
            "tuple[str, *tuple[float, ...], bool]",
        ),
    )


# ----------------------------------------------------------------------- Struct


def _run(document: R.CodeDocument) -> dict[str, Any]:
    namespace: dict[str, Any] = {"__name__": "generated"}
    exec(R.to_code_module(document), namespace)
    return namespace


def test_preserves_a_required_proto_property_in_generated_code() -> None:
    """toCodeDocument / Struct / preserves a required __proto__ property in generated code"""
    Proto = TypedDict("Proto", {"__proto__": str})
    schema = S.Struct(Proto, __proto__=S.String)
    _assert_schema(
        schema,
        _code("S.Struct(_Struct, __proto__=S.String)", "_Struct"),
        artifacts=[_typed_dict("_Struct", '"__proto__": str')],
    )
    generated = _run(R.to_code_document(R.to_representations((schema,))))["Schema0"]
    assert S.is_(generated)({"__proto__": "value"})
    assert not S.is_(generated)({})
    assert not S.is_(generated)({"__proto__": 123})


def test_preserves_an_optional_proto_property_in_generated_code() -> None:
    """toCodeDocument / Struct / preserves an optional __proto__ property in generated code"""
    Proto = TypedDict("Proto", {"__proto__": NotRequired[str]})
    schema = S.Struct(Proto, __proto__=S.String)
    _assert_schema(
        schema,
        _code("S.Struct(_Struct, __proto__=S.String)", "_Struct"),
        artifacts=[_typed_dict("_Struct", '"__proto__": NotRequired[str]')],
    )
    generated = _run(R.to_code_document(R.to_representations((schema,))))["Schema0"]
    assert S.is_(generated)({})
    assert S.is_(generated)({"__proto__": "value"})
    assert not S.is_(generated)({"__proto__": 123})


class _Empty(TypedDict):
    pass


class _A(TypedDict):
    a: str


class _AB(TypedDict):
    a: str
    b: float


class _OptionalA(TypedDict):
    a: NotRequired[str]


class _NumberA(TypedDict):
    a: float


def test_empty_struct() -> None:
    """toCodeDocument / Struct / empty struct"""
    artifacts = [_typed_dict("_Struct", "")]
    _assert_schema(S.Struct(_Empty), _code("S.Struct(_Struct)", "_Struct"), artifacts=artifacts)
    _assert_schema(
        S.Struct(_Empty).annotate(description="a"),
        _code('S.Struct(_Struct).annotate(description="a")', "_Struct"),
        artifacts=artifacts,
    )


def test_required_properties() -> None:
    """toCodeDocument / Struct / required properties"""
    _assert_schema(
        S.Struct(_A, a=S.String),
        _code("S.Struct(_Struct, a=S.String)", "_Struct"),
        artifacts=[_typed_dict("_Struct", '"a": str')],
    )
    _assert_schema(
        S.Struct(_AB, a=S.String, b=S.Number),
        _code("S.Struct(_Struct, a=S.String, b=S.Number)", "_Struct"),
        artifacts=[_typed_dict("_Struct", '"a": str, "b": float')],
    )


def test_optional_properties() -> None:
    """toCodeDocument / Struct / optional properties"""
    _assert_schema(
        S.Struct(_OptionalA, a=S.String),
        _code("S.Struct(_Struct, a=S.String)", "_Struct"),
        artifacts=[_typed_dict("_Struct", '"a": NotRequired[str]')],
    )


def test_struct_annotate_key() -> None:
    """toCodeDocument / Struct / annotateKey"""
    _assert_schema(
        S.Struct(_A, a=S.String.annotate_key(description="a")),
        _code('S.Struct(_Struct, a=S.String.annotate_key(description="a"))', "_Struct"),
        artifacts=[_typed_dict("_Struct", '"a": str')],
    )


def test_record_string_number() -> None:
    """toCodeDocument / Record(String, Number)"""
    _assert_schema(
        S.Record(S.String, S.Number),
        _code("S.Record(S.String, S.Number)", "dict[str, float]"),
    )
    _assert_schema(
        S.Record(S.String, S.Number).annotate(description="a"),
        _code('S.Record(S.String, S.Number).annotate(description="a")', "dict[str, float]"),
    )


def test_struct_with_rest() -> None:
    """toCodeDocument / StructWithRest: a ``TypedDict`` has no index signature, so the type is the
    struct's (§4)"""
    schema = S.StructWithRest(S.Struct(_NumberA, a=S.Number), S.Record(S.String, S.Number))
    runtime = "S.StructWithRest(S.Struct(_Struct, a=S.Number), S.Record(S.String, S.Number))"
    artifacts = [_typed_dict("_Struct", '"a": float')]
    _assert_schema(schema, _code(runtime, "_Struct"), artifacts=artifacts)
    _assert_schema(
        schema.annotate(description="a"),
        _code(f'{runtime}.annotate(description="a")', "_Struct"),
        artifacts=artifacts,
    )


# ------------------------------------------------------------------------ Union


def test_union_with_any_of_mode_default() -> None:
    """toCodeDocument / Union / union with anyOf mode (default)"""
    _assert_schema(
        S.Union([S.String, S.Number]), _code("S.Union([S.String, S.Number])", "str | float")
    )
    _assert_schema(
        S.Union([S.String, S.Number]).annotate(description="z"),
        _code('S.Union([S.String, S.Number]).annotate(description="z")', "str | float"),
    )


def test_union_with_one_of_mode() -> None:
    """toCodeDocument / Union / union with oneOf mode"""
    _assert_schema(
        S.Union([S.String, S.Number], mode="one_of"),
        _code('S.Union([S.String, S.Number], mode="one_of")', "str | float"),
    )
    _assert_schema(
        S.Union([S.String, S.Number], mode="one_of").annotate(description="aa"),
        _code(
            'S.Union([S.String, S.Number], mode="one_of").annotate(description="aa")',
            "str | float",
        ),
    )


def test_union_with_multiple_types() -> None:
    """toCodeDocument / Union / union with multiple types"""
    _assert_schema(
        S.Union([S.String, S.Number, S.Boolean]),
        _code("S.Union([S.String, S.Number, S.Boolean])", "str | float | bool"),
    )
    _assert_schema(
        S.Union([S.String, S.Number, S.Boolean]).annotate(description="a"),
        _code(
            'S.Union([S.String, S.Number, S.Boolean]).annotate(description="a")',
            "str | float | bool",
        ),
    )


# ---------------------------------------------------------------------- suspend


def test_implicit_recursive_reference() -> None:
    """toCodeDocument / suspend / implicit recursive reference"""
    _assert_document(
        R.MultiDocument(
            (R.Reference("Category"),),
            {
                "Category": R.Objects(
                    property_signatures=(
                        R.PropertySignature("children", R.Arrays(rest=(R.Reference("Category"),))),
                    )
                )
            },
        ),
        _code("Category", "CategoryType"),
        recursives={
            "Category": _code(
                "S.Struct(_Struct, children=S.Array(S.suspend(lambda: Category)))", "_Struct"
            )
        },
        artifacts=[_typed_dict("_Struct", '"children": tuple[CategoryType, ...]')],
    )


def test_supports_proto_as_a_recursive_reference() -> None:
    """toCodeDocument / suspend / supports __proto__ as a recursive reference"""
    _assert_document(
        R.MultiDocument(
            (R.Reference("__proto__"),),
            {
                "__proto__": R.Objects(
                    property_signatures=(
                        R.PropertySignature("next", R.Reference("__proto__"), is_optional=True),
                    )
                )
            },
        ),
        _code("__proto__", "__proto__Type"),
        recursives={
            "__proto__": _code("S.Struct(_Struct, next=S.suspend(lambda: __proto__))", "_Struct")
        },
        artifacts=[_typed_dict("_Struct", '"next": NotRequired[__proto__Type]')],
    )


def test_non_recursive() -> None:
    """toCodeDocument / suspend / non-recursive"""
    _assert_schema(S.suspend(lambda: S.String), _code("S.suspend(lambda: S.String)", "str"))


class _Node(TypedDict):
    a: NotRequired["_Node"]


_NO_ID: Any = S.Struct(_Node, a=S.suspend(lambda: _NO_ID))
_OUTER: Any = S.Struct(_Node, a=S.suspend(lambda: _OUTER)).annotate(identifier="A")
_INNER: Any = S.Struct(_Node, a=S.suspend(lambda: _INNER.annotate(identifier="A")))
_SUSPENDED: Any = S.Struct(_Node, a=S.suspend(lambda: _SUSPENDED).annotate(identifier="A"))


def test_no_identifier_annotation() -> None:
    """toCodeDocument / suspend / no identifier annotation"""
    _assert_schema(
        _NO_ID,
        _code("Objects_", "Objects_Type"),
        recursives={
            "Objects_": _code("S.Struct(_Struct, a=S.suspend(lambda: Objects_))", "_Struct")
        },
        artifacts=[_typed_dict("_Struct", '"a": NotRequired[Objects_Type]')],
    )


def test_outer_identifier_annotation() -> None:
    """toCodeDocument / suspend / outer identifier annotation"""
    _assert_schema(
        _OUTER,
        _code("A", "AType"),
        recursives={
            "A": _code(
                'S.Struct(_Struct, a=S.suspend(lambda: A)).annotate(identifier="A")',
                "_Struct",
            )
        },
        artifacts=[_typed_dict("_Struct", '"a": NotRequired[AType]')],
    )


def test_inner_identifier_annotation() -> None:
    """toCodeDocument / suspend / inner identifier annotation"""
    _assert_schema(
        _INNER,
        _code("S.Struct(_Struct1, a=Suspend_)", "_Struct1"),
        recursives={
            "A": _code(
                'S.Struct(_Struct, a=S.suspend(lambda: Suspend_)).annotate(identifier="A")',
                "_Struct",
            ),
            "Suspend_": _code("S.suspend(lambda: A)", "AType"),
        },
        artifacts=[
            _typed_dict("_Struct", '"a": NotRequired[Suspend_Type]'),
            _typed_dict("_Struct1", '"a": NotRequired[Suspend_Type]'),
        ],
    )


def test_suspend_identifier_annotation() -> None:
    """toCodeDocument / suspend / suspend identifier annotation"""
    _assert_schema(
        _SUSPENDED,
        _code("Objects_", "Objects_Type"),
        recursives={
            "A": _code('S.suspend(lambda: Objects_).annotate(identifier="A")', "Objects_Type"),
            "Objects_": _code("S.Struct(_Struct, a=S.suspend(lambda: A))", "_Struct"),
        },
        artifacts=[_typed_dict("_Struct", '"a": NotRequired[AType]')],
    )


# ------------------------------------------------------------------------ brand


def test_omits_brands() -> None:
    """toCodeDocument / brand / omits brands"""
    schema = S.String.pipe(S.from_brand(Brand[str, Any].nominal())).pipe(
        S.from_brand(Brand[Any, Any].nominal())
    )
    _assert_schema(schema, _code("S.String", "str"))


def test_omits_brands_from_unions() -> None:
    """toCodeDocument / brand / omits brands from unions"""
    schema = S.Union([S.String, S.Number]).pipe(S.from_brand(Brand[Any, Any].nominal()))
    _assert_schema(schema, _code("S.Union([S.String, S.Number])", "str | float"))


def test_preserves_checks_added_by_from_brand() -> None:
    """toCodeDocument / brand / preserves checks added by fromBrand"""
    is_int = Brand[Any, Any].check(S.is_int())
    positive = Brand[Any, Any].check(S.is_greater_than(0))
    code = R.to_code_document(
        R.to_representations((S.Number.pipe(S.from_brand(is_int)).pipe(S.from_brand(positive)),))
    ).codes[0]
    assert code == _code(
        'S.Number.check(S.is_int().annotate(expected="an integer"))'
        '.check(S.is_greater_than(0).annotate(expected="a value greater than 0"))',
        "float",
    )


# ------------------------------------------------------------------- date checks


_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_LATER = datetime(1970, 1, 1, 0, 0, 1, tzinfo=UTC)


@pytest.mark.parametrize(
    "check",
    [
        S.is_greater_than_date(_EPOCH),
        S.is_greater_than_or_equal_to_date(_EPOCH),
        S.is_less_than_date(_EPOCH),
        S.is_less_than_or_equal_to_date(_EPOCH),
        S.is_between_date(minimum=_EPOCH, maximum=_LATER),
    ],
    ids=[
        "isGreaterThanDate",
        "isGreaterThanOrEqualToDate",
        "isLessThanDate",
        "isLessThanOrEqualToDate",
        "isBetweenDate",
    ],
)
def test_date_checks(check: Any) -> None:
    """toCodeDocument / Date / checks / isGreaterThanDate, isGreaterThanOrEqualToDate,
    isLessThanDate, isLessThanOrEqualToDate, isBetweenDate: on ``S.DateTimeUtc``, judged by the
    document the generated code gives back"""
    schema = S.DateTimeUtc.check(check)
    document = R.to_code_document(R.to_representations((schema,)))
    generated = _run(document)["Schema0"]
    assert R.to_code_document(R.to_representations((generated,))) == document
    assert S.is_(generated)(_EPOCH) == S.is_(schema)(_EPOCH)
    assert S.is_(generated)(_LATER) == S.is_(schema)(_LATER)


# ------------------------------------------------------------------ collections


def test_readonly_set_string() -> None:
    """toCodeDocument / ReadonlySet / ReadonlySet(String): ``S.FrozenSet``"""
    _assert_schema(S.FrozenSet(S.String), _code("S.FrozenSet(S.String)", "frozenset[str]"))


@pytest.mark.parametrize(
    ("check", "code"),
    [
        (S.is_min_size(2), "S.is_min_size(2)"),
        (S.is_max_size(2), "S.is_max_size(2)"),
        (S.is_between_size(2, 2), "S.is_between_size(2, 2)"),
    ],
    ids=["isMinSize", "isMaxSize", "isBetweenSize"],
)
def test_readonly_set_checks(check: Any, code: str) -> None:
    """toCodeDocument / ReadonlySet / checks / isMinSize, isMaxSize; ReadonlySet / isBetweenSize"""
    _assert_schema(
        S.FrozenSet(S.String).check(check),
        _code(f"S.FrozenSet(S.String).check({code})", "frozenset[str]"),
    )


def test_hash_map_string_number() -> None:
    """toCodeDocument / HashMap / HashMap(String, Number): ``S.Map``"""
    _assert_schema(
        S.Map(S.String, S.Number), _code("S.Map(S.String, S.Number)", "dict[str, float]")
    )


# ------------------------------------------------------------------------ allOf


def test_should_resolve_references() -> None:
    """toCodeDocument / allOf / should resolve references"""
    _assert_json_schema(
        {"allOf": [{"$ref": "#/$defs/A"}], "$defs": {"A": {"type": "string"}}},
        _code("A", "AType"),
        non_recursives=[R.NamedCode("A", _code('S.String.annotate(identifier="A")', "str"))],
    )


def test_should_resolve_references_in_definitions() -> None:
    """toCodeDocument / allOf / should resolve references in definitions"""
    _assert_json_schema(
        {
            "$ref": "#/$defs/A",
            "$defs": {
                "A": {
                    "allOf": [
                        {"$ref": "#/$defs/B"},
                        {
                            "type": "object",
                            "properties": {"a": {"type": "string"}, "b": {}},
                            "required": ["a"],
                        },
                    ]
                },
                "B": {
                    "type": "object",
                    "properties": {"b": {"type": "number"}, "a": {}},
                    "required": ["b"],
                },
            },
        },
        _code("A", "AType"),
        non_recursives=[
            R.NamedCode(
                "A",
                _code(
                    'S.Struct(_Struct, b=S.Finite, a=S.String).annotate(identifier="A")', "_Struct"
                ),
            )
        ],
        artifacts=[_typed_dict("_Struct", '"b": float, "a": str')],
    )
