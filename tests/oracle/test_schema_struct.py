"""Ports of Effect's ``Schema.test.ts``: structs, records, key annotations
and the struct parse-option titles. Each test's docstring is the Effect test
title, prefixed by its ``describe`` block. ``TestSchema.Asserts`` is
``testing.SchemaAsserts``.

Python mappings: ``Schema.Struct({...})`` is ``S.Struct(TypedDict)``,
``optionalKey`` a ``NotRequired`` key, ``Struct.assign`` / ``pick`` /
``omit`` / ``partial`` / ``required`` a TypedDict made by inheritance,
``total=False`` or by hand; a struct accepts any ``Mapping`` and decodes to
a new ``dict``. Record keys are Python keys: an ``int`` key is a number, a
``str`` key a string.

Ported in part: "Struct / onExcessProperty / error" and "... / ignore strips
undeclared string and symbol properties" (string keys: no symbols),
"Record / recognizes numeric declared keys with an index signature" (a
string index signature for the symbol one).

Omitted:
- Symbols, ``undefined`` and JavaScript objects: "Struct / onExcessProperty /
  error ignores non-enumerable undeclared own properties without reading
  them", "... error validates non-enumerable declared string and symbol
  properties", "... error accepts Error internals in an open record",
  "Struct / should corectly handle __proto__", "Struct / Schema.optional:
  ...", "Record / Record(Symbol, Number)", "Record / index signatures select
  only enumerable string properties" / "... symbol properties", "Record /
  Record(Symbol.check, Number) ...", "Record / UniqueSymbol", "Record /
  Record(String, UndefinedOr(Number))", "Record / Literals keys /
  Record(Literals, optional(Number))".
- ``optionalKey`` / ``mutableKey`` as schema wrappers (a TypedDict key is
  ``NotRequired`` or ``ReadOnly``; a record key is a key): "Record /
  Record(String, optionalKey(Number)) should throw", "... optional(Number))
  should throw", "Record / Literals keys / Record(Literals,
  optionalKey(Number))", "... mutableKey(Number))", "...
  mutableKey(optionalKey(Number)))", the "requiredKey" and "required"
  titles.
- ``Struct.mapFields`` and its helpers (a TypedDict is the struct's type;
  inheritance and a new TypedDict spell them): "Struct / assign /
  overlapping fields" (a TypedDict cannot change an inherited key's type),
  "Struct / assign / Struct & check & unsafePreserveChecks: true", "Struct
  / pick / Struct", "Struct / omit / Struct", every "Struct.mapFields"
  title, "fieldsAssign".
- ``undefined`` and ``Schema.optional``: "Optional Fields / Optional
  Property", "... / Optional Property with Nullability", "... / Optional
  Property to Exact Optional Property", "... / Optional Property with
  Nullability to Optional Property".
- Ported in ``test_schema_template_literal.py``: "Record /
  Record(TemplateLiteral ...)", "Record / Record(`a${string}`, Number)".
- "Record / Record(Enum, Number)": an ``S.Enum`` decodes values to members,
  so as a record key it is a key pattern (values in, members out), not a
  required key per value.
- "annotateKey / ... / Tuple": ported in ``test_schema_composites.py``.
"""

import math
from typing import NotRequired, TypedDict

import pytest

import pyfect as fx
from pyfect import schema as S
from pyfect import testing
from pyfect.exit import Failure, Success
from pyfect.schema import getter as G
from pyfect.schema import transformation as T
from pyfect.testing import SchemaAsserts

# ------------------------------------------------------------------ Struct


class A(TypedDict):
    a: str


def test_allows_duplicate_property_signatures_in_the_low_level_ast_constructor():
    """Struct / allows duplicate property signatures in the low-level AST constructor"""
    node = S.ast.Objects(
        (
            S.ast.PropertySignature("a", S.String.ast),
            S.ast.PropertySignature("b", S.String.ast),
            S.ast.PropertySignature("a", S.Number.ast),
        )
    )
    assert [p.name for p in node.properties] == ["a", "b", "a"]


def test_on_excess_property_error():
    """Struct / onExcessProperty / error"""
    asserts = SchemaAsserts(S.Struct(A))
    asserts.decoding(on_excess_property="error").fail(
        {"a": "a", "b": "b"}, 'Expected no excess property\n  at ["b"]'
    )
    asserts.decoding(on_excess_property="error", errors="all").fail(
        {"a": "a", "b": "b", "c": "c"},
        'Expected no excess property\n  at ["b"]\nExpected no excess property\n  at ["c"]',
    )


def test_on_excess_property_ignore_strips_undeclared_properties():
    """Struct / onExcessProperty / ignore strips undeclared string and symbol properties"""
    asserts = SchemaAsserts(S.Struct(A))
    asserts.decoding(on_excess_property="ignore").succeed(
        {"a": "a", "b": "b", "c": "c"}, {"a": "a"}
    )


def test_on_excess_property_error_encodes_tagged_errors_carrying_runtime_internals():
    """Struct / onExcessProperty / error encodes tagged errors carrying runtime internals"""

    class NotFound(S.TaggedError):
        id: float

    error = NotFound(id=1)
    try:
        raise error
    except NotFound as raised:
        raised.add_note("runtime internals")
    asserts = SchemaAsserts(NotFound)
    asserts.encoding(on_excess_property="error").succeed(error, {"_tag": "NotFound", "id": 1})


def test_readonly_a_string():
    """Struct / { readonly "a": string }"""
    schema = S.Struct(A)
    asserts = SchemaAsserts(schema)

    # Should be able to access the fields
    assert schema.fields == {"a": S.String}

    make = asserts.make()
    make.succeed({"a": "a"})
    make.fail(None, "Expected object")

    decoding = asserts.decoding()
    decoding.succeed({"a": "a"})
    decoding.fail({}, 'Missing key\n  at ["a"]')
    decoding.fail({"a": 1}, 'Expected string\n  at ["a"]')

    encoding = asserts.encoding()
    encoding.succeed({"a": "a"})
    encoding.fail({}, 'Missing key\n  at ["a"]')
    encoding.fail({"a": 1}, 'Expected string\n  at ["a"]')


def test_should_use_the_identifier_annotation_as_the_expected_message():
    """Struct / should use the identifier annotation as the expected message"""
    asserts = SchemaAsserts(S.Struct(A).annotate(identifier="ID"))
    asserts.decoding().fail(None, "Expected ID")


def test_optional_key():
    """Struct / Schema.optionalKey: { readonly "a"?: string }"""

    class Optional(TypedDict):
        a: NotRequired[str]

    asserts = SchemaAsserts(S.Struct(Optional))

    make = asserts.make()
    make.succeed({"a": "a"})
    make.succeed({})

    decoding = asserts.decoding()
    decoding.succeed({"a": "a"})
    decoding.succeed({})
    decoding.fail({"a": 1}, 'Expected string\n  at ["a"]')

    encoding = asserts.encoding()
    encoding.succeed({"a": "a"})
    encoding.succeed({})
    encoding.fail({"a": 1}, 'Expected string\n  at ["a"]')


def test_parse_options_errors_all():
    """Struct / ParseOptions / { errors: "all" }"""

    class AB(TypedDict):
        a: str
        b: float

    asserts = SchemaAsserts(S.Struct(AB))
    both = 'Missing key\n  at ["a"]\nMissing key\n  at ["b"]'
    asserts.make(errors="all").fail({}, both)
    asserts.decoding(errors="all").fail({}, both)
    asserts.encoding(errors="all").fail({}, both)


def test_assign_struct():
    """Struct / assign / Struct"""

    class AB(A):
        b: str

    decoding = SchemaAsserts(S.Struct(AB)).decoding()
    decoding.succeed({"a": "a", "b": "b"})
    decoding.fail({"b": "b"}, 'Missing key\n  at ["a"]')
    decoding.fail({"a": "a"}, 'Missing key\n  at ["b"]')


# ------------------------------------------------------------- parse options


def test_applies_errors_to_nested_schemas_without_annotation_overrides():
    """parse options / applies errors to nested schemas without annotation overrides"""

    class CD(TypedDict):
        c: str
        d: str

    class Outer(TypedDict):
        a: str
        b: CD

    schema = S.Struct(Outer, b=S.Struct(CD).annotate(parse_options={"errors": "first"}))
    SchemaAsserts(schema).decoding(errors="all").fail(
        {"a": "a", "b": {}},
        'Missing key\n  at ["b"]["c"]\nMissing key\n  at ["b"]["d"]',
    )


def test_decoders_can_receive_options_when_they_are_created():
    """parse options / decoders can receive options when they are created"""
    decode = S.decode_unknown_exit(S.Struct(A), on_excess_property="error")
    assert isinstance(decode({"a": "a", "b": "b"}), Failure)
    assert decode({"a": "a", "b": "b"}, on_excess_property="ignore") == Success({"a": "a"})
    assert isinstance(decode({"a": "a", "b": "b"}), Failure)


def test_encoders_can_receive_options_when_they_are_created():
    """parse options / encoders can receive options when they are created"""
    encode = S.encode_unknown_exit(S.Struct(A), on_excess_property="error")
    assert isinstance(encode({"a": "a", "b": "b"}), Failure)
    assert encode({"a": "a", "b": "b"}, on_excess_property="ignore") == Success({"a": "a"})
    assert isinstance(encode({"a": "a", "b": "b"}), Failure)


# ----------------------------------------------------------------- Record


def test_record_string_number():
    """Record / Record(String, Number)"""
    asserts = SchemaAsserts(S.Record(S.String, S.Number))

    make = asserts.make()
    make.succeed({"a": 1})
    make.fail(None, "Expected object")

    decoding = asserts.decoding()
    decoding.succeed({"a": 1})
    decoding.fail(None, "Expected object")
    decoding.fail({"a": "b"}, 'Expected number\n  at ["a"]')

    encoding = asserts.encoding()
    encoding.succeed({"a": 1})
    encoding.fail({"a": "b"}, 'Expected number\n  at ["a"]')
    encoding.fail(None, "Expected object")


type Recursive = dict[str, Recursive]


def test_record_recursive_values_stay_lazy():
    """Record / recursive values stay lazy"""
    schema: S.Bottom[Recursive, object] = S.Record(S.String, S.suspend(lambda: schema))
    asserts = SchemaAsserts(schema)
    asserts.decoding().succeed({"a": {"b": {}}})
    asserts.encoding().succeed({"a": {"b": {}}})


def test_record_string_check_uses_the_key_checks_to_select_keys():
    """Record / Record(String.check, Number) should use the key checks to select keys"""
    schema = S.Record(S.String.check(S.is_pattern(r"^a")), S.Number)
    decoding = SchemaAsserts(schema).decoding()
    decoding.succeed({"a": 1, "ab": 2, "b": "ignored"}, {"a": 1, "ab": 2})
    decoding.fail({"a": "bad", "b": 1}, 'Expected number\n  at ["a"]')


def test_record_applies_excess_property_options_to_unmatched_own_keys():
    """Record / applies excess-property options to unmatched own keys"""
    schema = S.Record(S.String.check(S.is_pattern(r"^a")), S.Number)
    value = {"a": 1, "b": 2}
    assert S.decode_unknown_sync(schema)(value, on_excess_property="ignore") == {"a": 1}
    assert S.encode_unknown_sync(schema)(value, on_excess_property="ignore") == {"a": 1}
    with pytest.raises(S.SchemaError, match=r'^Expected no excess property\n  at \["b"\]$'):
        S.decode_unknown_sync(schema)(value, on_excess_property="error")
    with pytest.raises(S.SchemaError, match=r'^Expected no excess property\n  at \["b"\]$'):
        S.encode_unknown_sync(schema)(value, on_excess_property="error")


def test_record_a_key_failing_its_check_is_an_excess_property():
    """Not an Effect title: what Effect v4.0.6's ``Schema.Record`` does under Node with
    ``Record(String.check(isPattern(/^[a-z]+$/)), Number)`` nested in a struct (dogfood
    forge #5). A key failing its check is not an entry: it is dropped by default, and
    ``onExcessProperty: "error"`` reports it as an excess property, not with the key's
    own message; ``errors: "all"`` adds the value issues after it."""

    class Tasks(TypedDict):
        tasks: dict[str, float]

    records = S.Record(S.String.check(S.is_pattern(r"^[a-z]+$")), S.Number)
    schema = S.Struct(Tasks, tasks=records)
    value = {"tasks": {"ok": 1, "a b": 2}}
    assert S.decode_unknown_sync(schema)(value) == {"tasks": {"ok": 1}}
    assert S.encode_unknown_sync(schema)(value) == {"tasks": {"ok": 1}}
    excess = r'^Expected no excess property\n  at \["tasks"\]\["a b"\]$'
    with pytest.raises(S.SchemaError, match=excess):
        S.decode_unknown_sync(schema)(value, on_excess_property="error")
    with pytest.raises(S.SchemaError, match=excess):
        S.encode_unknown_sync(schema)(value, on_excess_property="error")
    bad_value = {"ok": "x", "a b": 2}
    with pytest.raises(S.SchemaError) as raised:
        S.decode_unknown_sync(records)(bad_value, on_excess_property="error", errors="all")
    assert raised.value.message == (
        'Expected no excess property\n  at ["a b"]\nExpected number\n  at ["ok"]'
    )


def test_record_recognizes_numeric_declared_keys_with_an_index_signature():
    """Record / recognizes numeric declared keys with an index signature"""
    schema = S.Record(S.Union(S.Literal(1), S.String), S.String)
    value = {1: "one", "s": "string"}
    assert S.decode_unknown_sync(schema)(value, on_excess_property="error") == value
    assert S.encode_unknown_sync(schema)(value, on_excess_property="error") == value


def test_record_literals_keys_deduplicates_repeated_literal_keys():
    """Record / Literals keys / deduplicates repeated literal keys"""
    schema = S.Record(S.Literals("a", "a", "b"), S.Number)
    node = schema.ast
    assert isinstance(node, S.ast.Objects)
    assert [p.name for p in node.properties] == ["a", "b"]


def test_record_literals_number():
    """Record / Literals keys / Record(Literals, Number)"""
    decoding = SchemaAsserts(S.Record(S.Literals("a", "b"), S.Number)).decoding()
    decoding.succeed({"a": 1, "b": 2})
    decoding.fail({"a": 1}, 'Missing key\n  at ["b"]')
    decoding.fail({"b": 2}, 'Missing key\n  at ["a"]')


# -------------------------------------------------------------- annotateKey


def test_annotate_key_message_missing_key_struct():
    """annotateKey / the messageMissingKey annotation should be used as a error message / Struct"""
    schema = S.Struct(A, a=S.String.annotate_key(message_missing_key="this field is required"))
    SchemaAsserts(schema).decoding().fail({}, 'this field is required\n  at ["a"]')


# ------------------------------------------------- transformations in structs


class _Finite(TypedDict):
    a: float


class _OptionalFinite(TypedDict):
    a: NotRequired[float]


class _OptionalNullableFinite(TypedDict):
    a: NotRequired[float | None]


def test_readonly_a_transformation():
    """Struct / { readonly "a": <transformation> }"""
    asserts = SchemaAsserts(S.Struct(_Finite, a=S.FiniteFromString))
    decoding = asserts.decoding()
    decoding.succeed({"a": "1"}, {"a": 1})
    decoding.fail({"a": "a"}, 'Expected a finite number\n  at ["a"]')
    encoding = asserts.encoding()
    encoding.succeed({"a": 1}, {"a": "1"})
    encoding.fail({"a": "a"}, 'Expected number\n  at ["a"]')


def test_readonly_a_optional_transformation():
    """Struct / { readonly "a"?: <transformation> }"""
    asserts = SchemaAsserts(S.Struct(_OptionalFinite, a=S.FiniteFromString))
    decoding = asserts.decoding()
    decoding.succeed({"a": "1"}, {"a": 1})
    decoding.succeed({})
    # Effect's ``{ a: undefined }``: ``None`` is not a string.
    decoding.fail({"a": None}, 'Expected string\n  at ["a"]')
    encoding = asserts.encoding()
    encoding.succeed({"a": 1}, {"a": "1"})
    encoding.succeed({})


class _AB(TypedDict):
    a: str
    b: str


def test_parse_options_applies_errors_with_encoding_checks():
    """Struct / parse options / applies errors with encoding checks"""
    schema = S.flip(S.flip(S.Struct(_AB)).check(S.is_max_properties(1)))
    node = schema.__codec__().ast
    assert isinstance(node, S.ast.Objects)
    assert node.checks is None
    assert node.encoding_checks is not None
    assert len(node.encoding_checks) == 1
    SchemaAsserts(schema).decoding(errors="all").fail(
        {}, 'Missing key\n  at ["a"]\nMissing key\n  at ["b"]'
    )


def test_optional_fields_exact_optional_property():
    """Optional Fields / Exact Optional Property"""
    asserts = SchemaAsserts(S.Struct(_OptionalFinite, a=S.FiniteFromString))
    decoding = asserts.decoding()
    decoding.succeed({"a": "1"}, {"a": 1})
    decoding.succeed({})
    encoding = asserts.encoding()
    encoding.succeed({"a": 1}, {"a": "1"})
    encoding.succeed({})


def test_optional_fields_exact_optional_property_with_nullability():
    """Optional Fields / Exact Optional Property with Nullability"""
    schema = S.Struct(_OptionalNullableFinite, a=S.NullOr(S.FiniteFromString))
    asserts = SchemaAsserts(schema)
    decoding = asserts.decoding()
    decoding.succeed({"a": "1"}, {"a": 1})
    decoding.succeed({})
    decoding.succeed({"a": None})
    encoding = asserts.encoding()
    encoding.succeed({"a": 1}, {"a": "1"})
    encoding.succeed({})
    encoding.succeed({"a": None})


# ------------------------------------------------- transformations in records


@testing.effect
def test_record_sequential_parsing_resumes_without_replaying_entries():
    """Record / sequential parsing resumes without replaying entries"""
    calls: list[str] = []

    def run(value: str, _: object) -> fx.Effect[str]:
        calls.append(value)
        return fx.yield_now().as_(value) if value == "b" else fx.succeed(value)

    value = S.String.pipe(S.decode(T.Transformation(G.transform_effect(run), G.passthrough())))
    input = {"a": "a", "b": "b", "c": "c"}
    assert (yield from S.decode_unknown_effect(S.Record(S.String, value))(input)) == input
    assert calls == ["a", "b", "c"]


def test_record_snake_to_camel_number_from_string():
    """Record / Record(SnakeToCamel, NumberFromString)"""
    snake_to_camel = S.String.pipe(S.decode(T.snake_to_camel()))
    asserts = SchemaAsserts(S.Record(snake_to_camel, S.NumberFromString))
    decoding = asserts.decoding()
    decoding.succeed({"a": "1"}, {"a": 1})
    decoding.succeed({"a_b": "1"}, {"aB": 1})
    decoding.succeed({"a_b": "1", "aB": "2"}, {"aB": 2})
    encoding = asserts.encoding()
    encoding.succeed({"a": 1}, {"a": "1"})
    encoding.succeed({"aB": 1}, {"a_b": "1"})
    encoding.succeed({"a_b": 1, "aB": 2}, {"a_b": "2"})


def test_record_number_string():
    """Record / Record(Number, String)"""
    # Python keys keep their type: a number key is a ``float`` or ``int``,
    # not its text (``NaN`` is left out: it is never equal to itself).
    decoding = SchemaAsserts(S.Record(S.Number, S.FiniteFromString)).decoding()
    decoding.succeed(
        {1: "1", 2.2: "2", math.inf: "3", -math.inf: "5"},
        {1: 1, 2.2: 2, math.inf: 3, -math.inf: 5},
    )
    decoding.fail({1: None}, "Expected string\n  at [1]")
    decoding.fail({1: "a"}, "Expected a finite number\n  at [1]")


def test_record_int_string():
    """Record / Record(Int, String)"""
    decoding = SchemaAsserts(S.Record(S.Int, S.FiniteFromString)).decoding()
    decoding.succeed({1: "1"}, {1: 1})
    decoding.succeed({1: "1", 1.1: "ignored", math.inf: "ignored"}, {1: 1})
    decoding.fail({1: None}, "Expected string\n  at [1]")
    decoding.fail({1: "a"}, "Expected a finite number\n  at [1]")


def test_record_union_number_a_finite_from_string():
    """Record / Record(Union(Number, "a"), FiniteFromString)"""
    schema = S.Record(S.Union(S.Number, S.Literal("a")), S.FiniteFromString)
    SchemaAsserts(schema).decoding().succeed(
        {"a": "-1", 1: "1", 2.2: "2", math.inf: "3", -math.inf: "5"},
        {"a": -1, 1: 1, 2.2: 2, math.inf: 3, -math.inf: 5},
    )
