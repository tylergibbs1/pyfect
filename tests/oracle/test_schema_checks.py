"""Ports of Effect's ``schema/Schema.test.ts``: literals, enums, unions of
primitives, checks, ``fromBrand`` and ``resolveAnnotations``. Each test's
docstring is the Effect test title, prefixed by its ``describe`` block.
``TestSchema.Asserts`` is ``testing.SchemaAsserts``.

Python mappings: an Effect ``enum`` is an ``enum.Enum`` whose members decode
from their values; ``bigint`` is ``int`` (``5n`` prints as ``5n`` only through
the ``*_big_int`` checks); ``RangeError`` is ``ValueError``; ``Schema.Int`` is
an ``int`` schema; ``fromBrand(name, brand)`` takes no name (a brand is a
``NewType``).

Omitted:
- "FiniteFromString &
  isGreaterThan", "Checks / check / object-level checks are validated against
  the decoded value when encoding", "Checks / check / suspended checks are not
  supported": need ``transform``, ``decodeTo``, ``Struct`` or ``suspend``.
- "Checks / Record checks / isMinProperties with symbol keys", "... /
  isMaxProperties with symbol keys", "... / isBetweenProperties with symbol
  keys": Python has no symbols.
- "Check / isStringFinite / rejects long digit runs in linear time" (its
  record half), "Union / Void", "Union / Void | String", "Literals.mapMembers
  / evolve": need ``Void`` or a struct made from a literal member; the size
  and key checks they use are covered on mappings in
  tests/test_schema_checks.py.
- "Checks / refine", "Checks / Array checks / UniqueArray",
  "Union.mapMembers / evolve", "Union.mapMembers / Array", "Union / should
  exclude members based on failed sentinels / string | tuple", "... /
  tagged tuple union": ported in ``test_schema_composites.py``.
- "Check / isStringSymbol": Python has no symbols.
- "Literal / transform", "Literals / transform" and the "brand / ..." titles:
  ported in ``test_schema_leftovers.py``.
- "Checks / String checks / isPattern with stateful RegExp flags": a Python
  pattern keeps no ``lastIndex``.
- "Finite": only verifies arbitrary generation (no arbitraries yet).
- "Union / mode: "oneOf" with Void", "Union / preserves member order after
  sentinel dispatch", "... recovering members during runtime type /
  sentinel dispatch": need ``Void`` or transformations.
- "Union / does not start later members after an asynchronous success",
  "... starts the next member only after an asynchronous failure", "...
  mode: "oneOf" succeeds on each execution of the same suspended decode
  effect", "... "anyOf" does not reuse a previous success ...", "...
  "oneOf" detects asynchronous successes in member order", "checkEffect /
  ...": need effectful decoding (``checkEffect`` / ``decodeTo``).
- "BigDecimal checks / ...": no BigDecimal module yet.
"""

import enum
from collections.abc import Callable
from typing import Literal, Never, NewType, TypedDict

import pytest

import pyfect as fx
from pyfect import schema as S
from pyfect import testing
from pyfect.brand import Brand
from pyfect.cause import Fail
from pyfect.deferred import Deferred
from pyfect.effect import Effect, suspend
from pyfect.exit import Failure, succeed
from pyfect.option import Option, Some
from pyfect.result import Ok
from pyfect.run import run_blocking_exit
from pyfect.schema import getter as G
from pyfect.schema import transformation as T
from pyfect.schema.issue import AnyOf, Forbidden, Issue, OneOf
from pyfect.testing import SchemaAsserts

# --------------------------------------------------------------- Literal


@pytest.mark.parametrize(
    ("value", "text"),
    [(float("inf"), "Infinity"), (float("-inf"), "-Infinity"), (float("nan"), "NaN")],
)
def test_literal_should_throw_an_error_if_the_literal_is_not_a_finite_number(
    value: float, text: str
):
    """Literal / should throw an error if the literal is not a finite number"""
    with pytest.raises(ValueError, match=f"^A numeric literal must be finite, got {text}$"):
        S.Literal(value)


def test_literal_should_expose_the_literal():
    """Literal / should expose the literal"""
    schema = S.Literal("a")
    assert schema.literal == "a"
    assert schema.annotate().literal == "a"


def test_literal_a():
    """Literal / "a\""""
    asserts = SchemaAsserts(S.Literal("a"))
    make = asserts.make()
    make.succeed("a")
    make.fail(None, 'Expected "a"')
    decoding = asserts.decoding()
    decoding.succeed("a")
    decoding.fail(1, 'Expected "a"')
    encoding = asserts.encoding()
    encoding.succeed("a")
    encoding.fail(1, 'Expected "a"')


def test_literal_1():
    """Literal / 1"""
    asserts = SchemaAsserts(S.Literal(1))
    make = asserts.make()
    make.succeed(1)
    make.fail(None, "Expected 1")
    decoding = asserts.decoding()
    decoding.succeed(1)
    decoding.fail("1", "Expected 1")
    encoding = asserts.encoding()
    encoding.succeed(1)
    encoding.fail("1", "Expected 1")


def test_literal_accepts_either_signed_zero_and_preserves_the_input_sign():
    """Literal / accepts either signed zero and preserves the input sign"""
    for literal in (0.0, -0.0):
        schema = S.Literal(literal)
        for input in (0.0, -0.0):
            assert str(S.decode_unknown_sync(schema)(input)) == str(input)
            assert str(S.encode_unknown_sync(schema)(input)) == str(input)


# -------------------------------------------------------------- Literals


def test_literals_red_green_blue():
    """Literals / red, green, blue"""
    schema = S.Literals("red", "green", "blue")
    assert schema.literals == ("red", "green", "blue")
    make = SchemaAsserts(schema).make()
    make.succeed("red")
    make.succeed("green")
    make.succeed("blue")
    make.fail("yellow", 'Expected "red" | "green" | "blue"')


def test_literals_pick():
    """Literals / pick"""
    assert S.Literals("a", "b", "c").pick("a", "b").literals == ("a", "b")


# ----------------------------------------------------------------- Union


def test_union_empty():
    """Union / empty"""
    SchemaAsserts(S.Union()).decoding().fail(None, "Expected never")


def test_union_string():
    """Union / String"""
    decoding = SchemaAsserts(S.Union(S.String)).decoding()
    decoding.succeed("a")
    decoding.fail(None, "Expected string")


def test_union_string_or_number():
    """Union / String | Number"""
    schema = S.Union(S.String, S.Number)
    assert schema.members == (S.String, S.Number)
    decoding = SchemaAsserts(schema).decoding()
    decoding.succeed("a")
    decoding.succeed(1)
    decoding.fail(None, "Expected string | number")


def test_union_string_or_never():
    """Union / String | Never"""
    decoding = SchemaAsserts(S.Union(S.String, S.Never)).decoding()
    decoding.succeed("a")
    decoding.fail(None, "Expected string | never")


def test_union_string_is_min_length_or_number_is_greater_than():
    """Union / String & isMinLength(1) | number & isGreaterThan(0)"""
    schema = S.Union(S.NonEmptyString, S.Number.check(S.is_greater_than(0)))
    decoding = SchemaAsserts(schema).decoding()
    decoding.succeed("a")
    decoding.succeed(1)
    decoding.fail("", "Expected a value with a length of at least 1")
    decoding.fail(-1, "Expected a value greater than 0")


def test_union_mode_one_of_counts_repeated_literal_occurrences():
    """Union / mode: "oneOf" counts repeated literal occurrences"""
    member = S.Literal("a")
    schema = S.Union(member, member, mode="one_of")
    SchemaAsserts(schema).decoding().fail("a", "Expected exactly one member to match")


class _A(TypedDict):
    a: str


class _B(TypedDict):
    b: float


def test_union_mode_one_of():
    '''Union / mode: "oneOf"'''
    schema = S.Union(S.Struct(_A), S.Struct(_B), mode="one_of")
    decoding = SchemaAsserts(schema).decoding()
    decoding.succeed({"a": "a"})
    decoding.succeed({"b": 1})
    decoding.fail({"a": "a", "b": 1}, "Expected exactly one member to match")


def test_union_mode_one_of_with_different_sentinel_keys():
    """Union / mode: "oneOf" with different sentinel keys"""

    class Kind(TypedDict):
        kind: Literal["a"]
        value: str

    class Status(TypedDict):
        status: Literal["ready"]
        value: str

    schema = S.Union(S.Struct(Kind), S.Struct(Status), mode="one_of")
    SchemaAsserts(schema).decoding().fail(
        {"kind": "a", "status": "ready", "value": "value"}, "Expected exactly one member to match"
    )


def test_union_mode_one_of_counts_repeated_member_occurrences():
    """Union / mode: "oneOf" counts repeated member occurrences"""

    class Kind(TypedDict):
        kind: Literal["a"]

    member = S.Struct(Kind)
    schema = S.Union(member, member, mode="one_of")
    SchemaAsserts(schema).decoding().fail({"kind": "a"}, "Expected exactly one member to match")


class _TaggedA(TypedDict):
    _tag: Literal["a"]
    a: str


class _TaggedB(TypedDict):
    _tag: Literal["b"]
    b: float


def test_union_should_exclude_members_based_on_failed_sentinels_string_struct():
    """Union / should exclude members based on failed sentinels / string | struct"""
    schema = S.Union(S.String, S.Struct(_TaggedA))
    SchemaAsserts(schema).decoding().fail({}, 'Expected string | { readonly "_tag": "a", ... }')


def test_union_should_exclude_members_based_on_failed_sentinels_tagged_struct_union():
    """Union / should exclude members based on failed sentinels / tagged struct union"""
    schema = S.Union(S.Struct(_TaggedA), S.Struct(_TaggedB))
    decoding = SchemaAsserts(schema).decoding()
    decoding.fail({"_tag": "a"}, 'Missing key\n  at ["a"]')
    decoding.fail({"_tag": "b"}, 'Missing key\n  at ["b"]')
    decoding.fail(
        {"_tag": "c"}, 'Expected { readonly "_tag": "a", ... } | { readonly "_tag": "b", ... }'
    )


def test_union_mode_one_of_with_nested_and_contradicted_sentinels():
    """Union / mode: "oneOf" with nested and contradicted sentinels"""

    class AX(TypedDict):
        kind: Literal["a"]
        variant: Literal["x"]

    class AY(TypedDict):
        kind: Literal["a"]
        variant: Literal["y"]

    class B(TypedDict):
        kind: Literal["b"]

    class Block(TypedDict):
        block: object

    nested = S.Union(S.Struct(AX), S.Struct(AY))
    schema = S.Struct(Block, block=S.Union(nested, S.Struct(B), mode="one_of"))
    decoding = SchemaAsserts(schema).decoding()
    decoding.succeed({"block": {"kind": "a", "variant": "x"}})
    expected = (
        'Expected { readonly "kind": "a", readonly "variant": "x", ... }'
        ' | { readonly "kind": "a", readonly "variant": "y", ... }\n  at ["block"]'
    )
    decoding.fail({"block": {"kind": "a", "variant": "z"}}, expected)
    # Effect's ``variant: undefined``.
    decoding.fail({"block": {"kind": "a", "variant": None}}, expected)


type _Str = S.Codec[str, str, Never, Never]


def _counting(schema: _Str) -> tuple[_Str, list[int]]:
    evaluations = [0]

    def make() -> _Str:
        evaluations[0] += 1
        return schema

    return S.suspend(make), evaluations


def test_union_keeps_suspended_members_lazy_during_candidate_selection():
    """Union / keeps suspended members lazy during candidate selection"""
    suspended, decoding_evaluations = _counting(S.String)
    decoding = SchemaAsserts(S.Union(S.Literal("a"), suspended)).decoding()
    decoding.succeed("a", "a")
    assert decoding_evaluations == [0]
    decoding.succeed("b", "b")
    decoding.succeed("c", "c")
    assert decoding_evaluations == [1]

    suspended, encoding_evaluations = _counting(S.String)
    SchemaAsserts(S.Union(S.Literal("a"), suspended)).encoding().succeed("a", "a")
    assert encoding_evaluations == [0]

    suspended, one_of_evaluations = _counting(S.String)
    one_of = SchemaAsserts(S.Union(S.Literal("a"), suspended, mode="one_of")).decoding()
    one_of.fail("a", "Expected exactly one member to match")
    assert one_of_evaluations == [1]


def test_union_does_not_force_a_recursive_suspended_member_after_an_earlier_success():
    """Union / does not force a recursive suspended member after an earlier success"""
    evaluations = [0]
    recursive: list[_Str] = []

    def make() -> _Str:
        evaluations[0] += 1
        return recursive[0]

    recursive.append(S.Union(S.Literal("end"), S.suspend(make)))
    SchemaAsserts(recursive[0]).decoding().succeed("end", "end")
    assert evaluations == [0]


def _fallback[T](value: T) -> Callable[[Issue], Effect[Option[T], Issue]]:
    return lambda _: fx.succeed(Some(value))


def test_union_preserves_recovering_members_during_runtime_type_dispatch():
    """Union / preserves recovering members during runtime type dispatch"""
    decoding_fallback = S.String.pipe(S.catch_decoding(_fallback("fallback")))
    encoding_fallback = S.String.pipe(S.catch_encoding(_fallback("fallback")))
    transformed_fallback = S.NumberFromString.pipe(S.catch_decoding(_fallback(0.0)))
    nested_fallback = S.Union(decoding_fallback, S.Number)
    literal_fallback = S.Literal("a").pipe(S.catch_decoding(_fallback("a")))
    record = S.Record(decoding_fallback, S.String)

    SchemaAsserts(S.Union(decoding_fallback, S.Null)).decoding().succeed(None, "fallback")
    SchemaAsserts(S.Union(transformed_fallback, S.Null)).decoding().succeed(None, 0)
    SchemaAsserts(S.Union(nested_fallback, S.Null)).decoding().succeed(None, "fallback")
    SchemaAsserts(S.Union(record, S.Null)).decoding().succeed(None, None)
    SchemaAsserts(S.Union(literal_fallback, S.Literal("b"))).decoding().succeed("b", "a")
    SchemaAsserts(S.Union(decoding_fallback, S.Null, mode="one_of")).decoding().fail(
        None, "Expected exactly one member to match"
    )
    SchemaAsserts(S.Union(encoding_fallback, S.Null)).encoding().succeed(None, "fallback")
    SchemaAsserts(S.Union(encoding_fallback, S.Null, mode="one_of")).encoding().fail(
        None, "Expected exactly one member to match"
    )


class _KindA(TypedDict):
    kind: Literal["a"]


class _KindB(TypedDict):
    kind: Literal["b"]


def test_union_preserves_recovering_members_during_sentinel_dispatch():
    """Union / preserves recovering members during sentinel dispatch"""
    decoding_tag = S.Literal("a").pipe(S.catch_decoding(_fallback("a")))
    encoding_tag = S.Literal("a").pipe(S.catch_encoding(_fallback("a")))
    decoding_first = S.Struct(_KindA, kind=decoding_tag)
    encoding_first = S.Struct(_KindA, kind=encoding_tag)
    decoding_root = S.Struct(_KindA).pipe(S.catch_decoding(_fallback(_KindA(kind="a"))))
    second = S.Struct(_KindB)
    input = {"kind": "b"}

    SchemaAsserts(S.Union(decoding_first, second)).decoding().succeed(input, {"kind": "a"})
    SchemaAsserts(S.Union(decoding_root, second)).decoding().succeed(input, {"kind": "a"})
    SchemaAsserts(S.Union(decoding_first, second, mode="one_of")).decoding().fail(
        input, "Expected exactly one member to match"
    )
    SchemaAsserts(S.Union(encoding_first, second)).encoding().succeed(input, {"kind": "a"})
    SchemaAsserts(S.Union(encoding_first, second, mode="one_of")).encoding().fail(
        input, "Expected exactly one member to match"
    )


def test_union_any_of_does_not_reuse_a_previous_success_when_all_members_now_fail():
    """Union / mode: "anyOf" does not reuse a previous success when all members now fail"""
    succeeds = [True]

    def first_run(value: str, _: object) -> Effect[str, Issue]:
        return suspend(
            lambda: (
                fx.succeed(value)
                if succeeds[0]
                else fx.fail(Forbidden({"message": "first failed"}))
            )
        )

    first = S.String.pipe(
        S.decode(T.Transformation(G.transform_effect(first_run), G.passthrough()))
    )
    effect = S.decode_unknown_effect(S.Union(first, S.String.check(S.is_min_length(5))))("a")
    assert run_blocking_exit(effect) == succeed("a")
    succeeds[0] = False
    exit = run_blocking_exit(effect)
    assert isinstance(exit, Failure)
    match exit.cause.find_error():
        case Ok(error):
            assert isinstance(error.issue, AnyOf)
        case other:
            raise AssertionError(other)


@testing.effect
def test_union_one_of_detects_asynchronous_successes_in_member_order():
    """Union / mode: "oneOf" detects asynchronous successes in member order"""
    first_started = yield from Deferred[None].make()
    first_latch = yield from Deferred[None].make()
    second_calls = [0]

    def first_run(_: str, __: object) -> Effect[str]:
        return first_started.succeed(None).and_then(first_latch.wait()).as_("first")

    def second_run(_: str) -> str:
        second_calls[0] += 1
        return "second"

    first = S.String.pipe(
        S.decode(T.Transformation(G.transform_effect(first_run), G.passthrough()))
    )
    second = S.String.pipe(S.decode(T.Transformation(G.transform(second_run), G.passthrough())))
    union = S.Union(first, second, mode="one_of")
    fiber = yield from S.decode_unknown_effect(union)("value").exit().fork()

    yield from first_started.wait()
    yield from fx.yield_now()
    assert second_calls == [0]
    yield from first_latch.succeed(None)
    exit = yield from fiber.join()
    assert second_calls == [1]
    assert isinstance(exit, Failure)
    reason = exit.cause.reasons[0]
    assert isinstance(reason, Fail)
    issue = reason.error.issue
    assert isinstance(issue, OneOf)
    assert issue.successes == (first.ast, second.ast)


# ----------------------------------------------------------- Record checks


def test_checks_record_checks_is_min_properties():
    """Checks / Record checks / isMinProperties"""
    schema = S.Record(S.String, S.Finite).check(S.is_min_properties(1))
    decoding = SchemaAsserts(schema).decoding()
    decoding.succeed({"a": 1, "b": 2})
    decoding.fail({}, "Expected a value with at least 1 entry")


def test_checks_record_checks_is_max_properties():
    """Checks / Record checks / isMaxProperties"""
    schema = S.Record(S.String, S.Finite).check(S.is_max_properties(2))
    decoding = SchemaAsserts(schema).decoding()
    decoding.succeed({"a": 1, "b": 2})
    decoding.fail({"a": 1, "b": 2, "c": 3}, "Expected a value with at most 2 entries")


def test_checks_record_checks_is_between_properties():
    """Checks / Record checks / isBetweenProperties"""
    schema = S.Record(S.String, S.Number).check(S.is_between_properties(2, 2))
    decoding = SchemaAsserts(schema).decoding()
    decoding.succeed({"a": 1, "b": 2})
    decoding.succeed({"__proto__": 0, "": 0})
    decoding.fail({"a": 1}, "Expected a value with exactly 2 entries")
    decoding.fail({"a": 1, "b": 2, "c": 3}, "Expected a value with exactly 2 entries")


def test_checks_record_checks_is_property_names():
    """Checks / Record checks / isPropertyNames"""
    schema = S.Record(S.String, S.Finite).check(
        S.is_property_names(S.String.check(S.is_pattern(r"^[A-Z]")))
    )
    decoding = SchemaAsserts(schema).decoding()
    decoding.succeed({"Ab": 1})
    decoding.fail({"ab": 1}, 'Expected a string matching the RegExp ^[A-Z]\n  at ["ab"]')


def test_checks_record_checks_is_property_names_with_never():
    """Checks / Record checks / isPropertyNames with Never"""
    schema = S.Record(S.String, S.Finite).check(S.is_property_names(S.Never))
    decoding = SchemaAsserts(schema).decoding()
    decoding.succeed({})
    decoding.fail({"a": 1}, 'Expected never\n  at ["a"]')


def test_union_options_preserves_union_options_through_public_derivations():
    """Union options / preserves Union options through public derivations"""
    schema = S.Union(S.String, S.Number, mode="one_of")
    mapped = schema.map_members(lambda members: (*members, S.Boolean))
    assert isinstance(mapped.ast, S.ast.Union)
    assert mapped.ast.mode == "one_of"
    flipped = schema.ast.flip()
    assert isinstance(flipped, S.ast.Union)
    assert flipped.mode == "one_of"


def test_union_map_members_append_element():
    """Union.mapMembers / appendElement"""
    schema = S.Union(S.String, S.Number).map_members(lambda members: (*members, S.Boolean))
    assert schema.members == (S.String, S.Number, S.Boolean)
    assert isinstance(schema.ast, S.ast.Union)
    assert schema.ast.types == (S.String.ast, S.Number.ast, S.Boolean.ast)


# ------------------------------------------------------------------ Enum


@pytest.mark.parametrize(
    ("value", "text"),
    [(float("nan"), "NaN"), (float("inf"), "Infinity"), (float("-inf"), "-Infinity")],
)
def test_enum_rejects_non_finite_numeric_values(value: float, text: str):
    """Enum / rejects non-finite numeric values"""
    with pytest.raises(ValueError, match=f"^A numeric enum value must be finite, got {text}$"):
        S.Enum(enum.Enum("E", {"value": value}))


class Fruits(enum.Enum):
    APPLE = 0
    BANANA = 1


def test_enum_enums_should_be_exposed():
    """Enum / enums should be exposed"""
    schema = S.Enum(Fruits)
    assert schema.enums.APPLE.value == 0
    assert schema.enums.BANANA.value == 1


def test_enum_numeric_enum():
    """Enum / Numeric enum"""
    asserts = SchemaAsserts(S.Enum(Fruits))
    decoding = asserts.decoding()
    decoding.succeed(Fruits.APPLE)
    decoding.succeed(Fruits.BANANA)
    decoding.succeed(0, Fruits.APPLE)
    decoding.succeed(1, Fruits.BANANA)
    decoding.fail(3, "Expected 0 | 1")
    encoding = asserts.encoding()
    encoding.succeed(Fruits.APPLE, 0)
    encoding.succeed(Fruits.BANANA, 1)


class MixedFruits(enum.Enum):
    APPLE = "apple"
    BANANA = "banana"
    CANTALOUPE = 0


def test_enum_string_enum():
    """Enum / String enum"""
    asserts = SchemaAsserts(S.Enum(MixedFruits))
    decoding = asserts.decoding()
    decoding.succeed(MixedFruits.APPLE)
    decoding.succeed(MixedFruits.CANTALOUPE)
    decoding.succeed("apple", MixedFruits.APPLE)
    decoding.succeed("banana", MixedFruits.BANANA)
    decoding.succeed(0, MixedFruits.CANTALOUPE)
    decoding.fail("Cantaloupe", 'Expected "apple" | "banana" | 0')
    encoding = asserts.encoding()
    encoding.succeed(MixedFruits.APPLE, "apple")
    encoding.succeed(MixedFruits.BANANA, "banana")
    encoding.succeed(MixedFruits.CANTALOUPE, 0)


def test_enum_const_enum():
    """Enum / Const enum"""
    # A ``const`` object is a functional-API enum in Python.
    fruits = enum.Enum("Fruits", {"Apple": "apple", "Banana": "banana", "Cantaloupe": 3})
    asserts = SchemaAsserts(S.Enum(fruits))
    decoding = asserts.decoding()
    decoding.succeed("apple", fruits["Apple"])
    decoding.succeed("banana", fruits["Banana"])
    decoding.succeed(3, fruits["Cantaloupe"])
    decoding.fail("Cantaloupe", 'Expected "apple" | "banana" | 3')
    encoding = asserts.encoding()
    encoding.succeed(fruits["Apple"], "apple")
    encoding.succeed(fruits["Banana"], "banana")
    encoding.succeed(fruits["Cantaloupe"], 3)


# --------------------------------------------------- primitives with checks


def test_trimmed():
    """Trimmed"""
    decoding = SchemaAsserts(S.Trimmed).decoding()
    decoding.succeed("a")
    decoding.fail(" a ", "Expected a string with no leading or trailing whitespace")


def test_int():
    """Int"""
    asserts = SchemaAsserts(S.Int)
    decoding = asserts.decoding()
    decoding.succeed(1)
    for value in (1.1, float("nan"), float("inf"), float("-inf")):
        decoding.fail(value, "Expected an integer")
    encoding = asserts.encoding()
    encoding.succeed(1)
    encoding.fail(1.1, "Expected an integer")


def test_natural():
    """Natural"""
    asserts = SchemaAsserts(S.Natural)
    decoding = asserts.decoding()
    decoding.succeed(0)
    decoding.succeed(1)
    decoding.fail(-1, "Expected a value greater than or equal to 0")
    decoding.fail(1.1, "Expected an integer")
    encoding = asserts.encoding()
    encoding.succeed(0)
    encoding.fail(-1, "Expected a value greater than or equal to 0")


def test_parse_options_does_not_interpret_custom_parse_options_metadata():
    """parse options / does not interpret custom parseOptions metadata"""
    schema = S.Number.check(S.is_greater_than(0), S.is_int()).annotate(
        parse_options={"errors": "all"}
    )
    SchemaAsserts(schema).decoding().fail(-1.2, "Expected a value greater than 0")


# ---------------------------------------------------------------- Checks


def test_checks_check_single_check():
    """Checks / check / single check"""
    decoding = SchemaAsserts(S.String.check(S.is_min_length(3))).decoding()
    decoding.succeed("abc")
    decoding.fail("ab", "Expected a value with a length of at least 3")


def test_checks_check_multiple_checks():
    """Checks / check / multiple checks"""
    asserts = SchemaAsserts(S.String.check(S.is_min_length(3), S.is_including("c")))
    decoding = asserts.decoding()
    decoding.succeed("abc")
    decoding.fail("ab", "Expected a value with a length of at least 3")
    asserts.decoding(errors="all").fail(
        "ab", 'Expected a value with a length of at least 3\nExpected a string including "c"'
    )


def test_checks_check_aborting_checks():
    """Checks / check / aborting checks"""
    schema = S.String.check(S.is_min_length(2).abort(), S.is_including("b"))
    SchemaAsserts(schema).decoding().fail("a", "Expected a value with a length of at least 2")


def test_checks_check_make_filter_group():
    """Checks / check / makeFilterGroup"""
    username = S.make_filter_group(
        S.is_min_length(3),
        S.is_pattern(
            r"^[a-zA-Z0-9]+$",
            title="alphanumeric",
            description="must contain only letters and numbers",
        ),
        S.is_trimmed(),
        title="username",
        description="a valid username",
    )
    decoding = SchemaAsserts(S.String.check(username)).decoding()
    decoding.succeed("abc")
    decoding.fail("", "Expected a value with a length of at least 3")


STRING_CHECKS: list[tuple[str, S.Check[str], list[str], str, str]] = [
    ("isPattern", S.is_pattern("^a"), ["a"], "b", "Expected a string matching the RegExp ^a"),
    ("isStartingWith", S.is_starting_with("a"), ["a"], "b", 'Expected a string starting with "a"'),
    ("isEndingWith", S.is_ending_with("a"), ["a"], "b", 'Expected a string ending with "a"'),
    (
        "isLowercased",
        S.is_lowercased(),
        ["a"],
        "A",
        "Expected a string with all characters in lowercase",
    ),
    (
        "isUppercased",
        S.is_uppercased(),
        ["A"],
        "a",
        "Expected a string with all characters in uppercase",
    ),
    ("isMinLength", S.is_min_length(1), ["a"], "", "Expected a value with a length of at least 1"),
]


@pytest.mark.parametrize(
    ("check", "accepted", "rejected", "message"),
    [row[1:] for row in STRING_CHECKS],
    ids=[row[0] for row in STRING_CHECKS],
)
def test_checks_string_checks(
    check: S.Check[str], accepted: list[str], rejected: str, message: str
):
    """Checks / String checks / isPattern, isStartingWith, isEndingWith,
    isLowercased, isUppercased, isMinLength"""
    asserts = SchemaAsserts(S.String.check(check))
    for direction in (asserts.decoding(), asserts.encoding()):
        for value in accepted:
            direction.succeed(value)
        direction.fail(rejected, message)


def test_checks_string_checks_is_capitalized():
    """Checks / String checks / isCapitalized"""
    asserts = SchemaAsserts(S.String.check(S.is_capitalized()))
    decoding = asserts.decoding()
    for value in ("", "Abc", "𐐀bc"):
        decoding.succeed(value)
    for value in ("abc", "𐐨bc"):
        decoding.fail(value, "Expected a string with the first character in uppercase")
    encoding = asserts.encoding()
    encoding.succeed("Abc")
    encoding.fail("abc", "Expected a string with the first character in uppercase")


def test_checks_string_checks_is_uncapitalized():
    """Checks / String checks / isUncapitalized"""
    asserts = SchemaAsserts(S.String.check(S.is_uncapitalized()))
    decoding = asserts.decoding()
    for value in ("", "aBC", "𐐨BC"):
        decoding.succeed(value)
    for value in ("ABC", "𐐀BC"):
        decoding.fail(value, "Expected a string with the first character in lowercase")
    encoding = asserts.encoding()
    encoding.succeed("aBC")
    encoding.fail("ABC", "Expected a string with the first character in lowercase")


NUMBER_CHECKS: list[tuple[str, S.Check[float], list[float], float, str]] = [
    ("isGreaterThan", S.is_greater_than(1), [2], 1, "Expected a value greater than 1"),
    (
        "isGreaterThanOrEqualTo",
        S.is_greater_than_or_equal_to(1),
        [1],
        0,
        "Expected a value greater than or equal to 1",
    ),
    ("isLessThan", S.is_less_than(1), [0], 1, "Expected a value less than 1"),
    (
        "isLessThanOrEqualTo",
        S.is_less_than_or_equal_to(1),
        [1],
        2,
        "Expected a value less than or equal to 1",
    ),
    ("isMultipleOf", S.is_multiple_of(2), [4], 3, "Expected a value that is a multiple of 2"),
    (
        "isMultipleOf normalizes negative divisors",
        S.is_multiple_of(-2),
        [4],
        3,
        "Expected a value that is a multiple of 2",
    ),
]


@pytest.mark.parametrize(
    ("check", "accepted", "rejected", "message"),
    [row[1:] for row in NUMBER_CHECKS],
    ids=[row[0] for row in NUMBER_CHECKS],
)
def test_checks_number_checks(
    check: S.Check[float], accepted: list[float], rejected: float, message: str
):
    """Checks / Number checks / isGreaterThan, isGreaterThanOrEqualTo,
    isLessThan, isLessThanOrEqualTo, isMultipleOf, isMultipleOf normalizes
    negative divisors"""
    asserts = SchemaAsserts(S.Number.check(check))
    for direction in (asserts.decoding(), asserts.encoding()):
        for value in accepted:
            direction.succeed(value)
        direction.fail(rejected, message)


def test_checks_number_checks_is_multiple_of_rejects_nonzero_subnormal_remainders():
    """Checks / Number checks / isMultipleOf rejects nonzero subnormal remainders"""
    assert not S.is_(S.Number.check(S.is_multiple_of(1e-323)))(1.042e-321)


@pytest.mark.parametrize(
    ("divisor", "text"),
    [
        (0, "0"),
        (-0.0, "0"),
        (float("nan"), "NaN"),
        (float("inf"), "Infinity"),
        (float("-inf"), "-Infinity"),
    ],
)
def test_checks_number_checks_is_multiple_of_rejects_invalid_divisors(divisor: float, text: str):
    """Checks / Number checks / isMultipleOf rejects invalid divisors"""
    with pytest.raises(ValueError, match=f"^Expected a finite non-zero number, got {text}$"):
        S.is_multiple_of(divisor)


@pytest.mark.parametrize(
    ("exclusive_minimum", "exclusive_maximum", "accepted", "rejected", "text"),
    [
        (False, False, [1, 3], [0, 4], "1 and 3"),
        (False, True, [1], [3, 0, 4], "1 and 3 (excluded)"),
        (True, False, [3], [1, 0, 4], "1 (excluded) and 3"),
        (True, True, [2], [1, 3, 0, 4], "1 (excluded) and 3 (excluded)"),
    ],
    ids=[
        "included & included",
        "included & excluded",
        "excluded & included",
        "excluded & excluded",
    ],
)
def test_checks_number_checks_is_between(
    exclusive_minimum: bool,
    exclusive_maximum: bool,
    accepted: list[int],
    rejected: list[int],
    text: str,
):
    """Checks / Number checks / isBetween / included & included, included &
    excluded, excluded & included, excluded & excluded"""
    check = S.is_between(
        minimum=1,
        maximum=3,
        exclusive_minimum=exclusive_minimum,
        exclusive_maximum=exclusive_maximum,
    )
    asserts = SchemaAsserts(S.Int.check(check))
    for direction in (asserts.decoding(), asserts.encoding()):
        for value in accepted:
            direction.succeed(value)
        for value in rejected:
            direction.fail(value, f"Expected a value between {text}")


def test_checks_number_checks_is_int():
    """Checks / Number checks / isInt"""
    asserts = SchemaAsserts(S.Number.check(S.is_int()))
    decoding = asserts.decoding()
    decoding.succeed(1)
    for value in (1.1, float("nan"), float("inf"), float("-inf")):
        decoding.fail(value, "Expected an integer")
    encoding = asserts.encoding()
    encoding.succeed(1)
    encoding.fail(1.1, "Expected an integer")


MAX_SAFE_INTEGER = 2**53 - 1


def test_checks_number_checks_is_int32():
    """Checks / Number checks / isInt32"""
    asserts = SchemaAsserts(S.Number.check(S.is_int32()))
    decoding = asserts.decoding()
    decoding.succeed(1)
    for value in (1.1, float(MAX_SAFE_INTEGER + 1), float(-MAX_SAFE_INTEGER - 1)):
        decoding.fail(value, "Expected an integer")
    asserts.decoding(errors="all").fail(
        float(MAX_SAFE_INTEGER + 1),
        "Expected an integer\nExpected a value between -2147483648 and 2147483647",
    )
    encoding = asserts.encoding()
    encoding.succeed(1)
    encoding.fail(1.1, "Expected an integer")
    encoding.fail(float(MAX_SAFE_INTEGER + 1), "Expected an integer")


def _format_big_int(value: int) -> str:
    return f"{value}n"


is_between_big = S.make_is_between(formatter=_format_big_int)
BIG_INT_CHECKS: list[tuple[str, S.Check[int], list[int], int, str]] = [
    (
        "isBetween",
        is_between_big(minimum=5, maximum=10),
        [5, 7, 10],
        4,
        "Expected a value between 5n and 10n",
    ),
    (
        "isGreaterThan",
        S.make_is_greater_than(formatter=_format_big_int)(5),
        [6],
        5,
        "Expected a value greater than 5n",
    ),
    (
        "isGreaterThanOrEqualTo",
        S.make_is_greater_than_or_equal_to(formatter=_format_big_int)(5),
        [5, 6],
        4,
        "Expected a value greater than or equal to 5n",
    ),
    (
        "isLessThan",
        S.make_is_less_than(formatter=_format_big_int)(5),
        [4],
        5,
        "Expected a value less than 5n",
    ),
    (
        "isLessThanOrEqualTo",
        S.make_is_less_than_or_equal_to(formatter=_format_big_int)(5),
        [5, 4],
        6,
        "Expected a value less than or equal to 5n",
    ),
]


@pytest.mark.parametrize(
    ("check", "accepted", "rejected", "message"),
    [row[1:] for row in BIG_INT_CHECKS],
    ids=[row[0] for row in BIG_INT_CHECKS],
)
def test_checks_big_int_checks(
    check: S.Check[int], accepted: list[int], rejected: int, message: str
):
    """Checks / BigInt Checks / isBetween, isGreaterThan,
    isGreaterThanOrEqualTo, isLessThan, isLessThanOrEqualTo"""
    decoding = SchemaAsserts(S.BigInt.check(check)).decoding()
    for value in accepted:
        decoding.succeed(value)
    decoding.fail(rejected, message)


# ----------------------------------------------------------------- Check


def _representation(schema: S.Top) -> object:
    annotations = S.resolve_annotations(schema)
    assert annotations is not None
    return annotations.get("representation")


def test_check_is_string_finite_representation():
    """Check / isStringFinite / representation"""
    schema = S.String.check(S.is_string_finite())
    assert _representation(schema) == {"id": "effect/schema/isStringFinite", "payload": None}


def test_check_is_string_finite_accepts_finite_number_strings():
    """Check / isStringFinite / accepts finite number strings"""
    is_finite = S.is_(S.String.check(S.is_string_finite()))
    for s in ("1", "-1", "+01", "1.5", ".5", "1e5", "-.5E+5"):
        assert is_finite(s), s
    for s in ("", ".", "1.", "1..5", "1e", "e5", "1.e5", " 1", "Infinity", "NaN"):
        assert not is_finite(s), s


def test_check_is_string_finite_rejects_long_digit_runs_in_linear_time():
    """Check / isStringFinite / rejects long digit runs in linear time"""
    is_finite = S.is_(S.String.check(S.is_string_finite()))
    digits = "1" * 100_000
    for s in (f"{digits}x", f"{digits}.", f"{digits}e", f"-{digits}x"):
        assert not is_finite(s)
    assert is_finite(digits)


def test_check_is_string_big_int():
    """Check / isStringBigInt"""
    schema = S.String.check(S.is_string_big_int())
    assert _representation(schema) == {"id": "effect/schema/isStringBigInt", "payload": None}


def test_check_is_uuid():
    """Check / isUUID"""
    schema = S.String.check(S.is_uuid())
    assert _representation(schema) == {"id": "effect/schema/isUUID", "payload": {"version": None}}
    decoding = SchemaAsserts(schema).decoding()
    decoding.succeed("00000000-0000-0000-0000-000000000000")
    decoding.succeed("ffffffff-ffff-ffff-ffff-ffffffffffff")
    decoding.succeed("FFFFFFFF-FFFF-FFFF-FFFF-FFFFFFFFFFFF")
    decoding.succeed("00000000-0000-4000-8000-000000000001")
    decoding.fail("00000000-0000-0000-0000-000000000001", "Expected a UUID")


def test_check_is_uuid_version_specific_checks_reject_nil_and_max_uuids():
    """Check / isUUID version-specific checks reject nil and max UUIDs"""
    decoding = SchemaAsserts(S.String.check(S.is_uuid(4))).decoding()
    decoding.succeed("00000000-0000-4000-8000-000000000001")
    decoding.fail("00000000-0000-0000-0000-000000000000", "Expected a UUID v4")
    decoding.fail("ffffffff-ffff-ffff-ffff-ffffffffffff", "Expected a UUID v4")


def test_check_is_guid():
    """Check / isGUID"""
    schema = S.String.check(S.is_guid())
    assert _representation(schema) == {"id": "effect/schema/isGUID", "payload": None}
    decoding = SchemaAsserts(schema).decoding()
    decoding.succeed("00000000-0000-0000-0000-000000000001")
    decoding.succeed("FFFFFFFF-FFFF-FFFF-FFFF-FFFFFFFFFFFF")
    decoding.fail("not-a-guid", "Expected a GUID")


def test_check_is_ulid():
    """Check / isULID"""
    schema = S.String.check(S.is_ulid())
    assert _representation(schema) == {"id": "effect/schema/isULID", "payload": None}
    decoding = SchemaAsserts(schema).decoding()
    decoding.succeed("01H4PGGGJVN2DKP2K1H7EH996V")
    decoding.succeed("7" + "z" * 25)
    message = "Expected a string matching the RegExp ^[0-7][0-9A-HJKMNP-TV-Za-hjkmnp-tv-z]{25}$"
    decoding.fail("80000000000000000000000000", message)
    decoding.fail("", message)


def test_check_is_ascii():
    """Check / isAscii"""
    schema = S.String.check(S.is_ascii())
    SchemaAsserts(schema).verify_generation()
    assert _representation(schema) == {"id": "effect/schema/isAscii", "payload": None}
    decoding = SchemaAsserts(schema).decoding()
    decoding.succeed("")
    decoding.succeed("\x00a\x7f")
    decoding.fail("a\x80", "Expected an ASCII string")


def test_check_is_base64():
    """Check / isBase64"""
    schema = S.String.check(S.is_base64())
    assert _representation(schema) == {"id": "effect/schema/isBase64", "payload": None}
    decoding = SchemaAsserts(schema).decoding()
    for value in ("", "Zm9v+/==", "Zm8=", "A" * 8_000_000):
        decoding.succeed(value)
    for value in ("Zm8", "Zg=", "Zm9v-_=="):
        decoding.fail(value, "Expected a base64 encoded string")


def test_check_is_base64_url():
    """Check / isBase64Url"""
    schema = S.String.check(S.is_base64_url())
    assert _representation(schema) == {"id": "effect/schema/isBase64Url", "payload": None}
    decoding = SchemaAsserts(schema).decoding()
    for value in ("", "Zm9v-_", "Zg==", "A" * 8_000_000):
        decoding.succeed(value)
    for value in ("Zm9vZ", "Zg=", "Zm9v+/"):
        decoding.fail(value, "Expected a base64url encoded string")


Int = NewType("Int", float)
Positive = NewType("Positive", float)


def test_check_from_brand_nominal():
    """Check / fromBrand / nominal"""
    Name = NewType("Name", str)
    schema = S.String.pipe(S.from_brand(Brand[str, Name].nominal()))
    decoding = SchemaAsserts(schema).decoding()
    decoding.succeed("a")
    decoding.fail(1, "Expected string")
    assert schema.ast is S.String.ast


def test_check_from_brand_single_brand():
    """Check / fromBrand / single brand"""
    schema = S.Number.pipe(S.from_brand(Brand[float, Int].check(S.is_int())))
    decoding = SchemaAsserts(schema).decoding()
    decoding.succeed(1)
    decoding.fail("a", "Expected number")
    decoding.fail(1.2, "Expected an integer")


def test_check_from_brand_multiple_brands():
    """Check / fromBrand / multiple brands"""
    to_int = Brand[float, Int].check(S.is_int())
    to_positive = Brand[float, Positive].check(S.is_greater_than(0))
    schema = S.Number.pipe(S.from_brand(to_int)).pipe(S.from_brand(to_positive))
    decoding = SchemaAsserts(schema).decoding()
    decoding.succeed(1)
    decoding.fail("a", "Expected number")
    decoding.fail(1.2, "Expected an integer")
    decoding.fail(-1, "Expected a value greater than 0")


# ---------------------------------------------------- resolveAnnotations


def test_resolve_annotations_returns_undefined_for_a_schema_without_annotations():
    """resolveAnnotations / returns undefined for a schema without annotations"""
    assert S.resolve_annotations(S.String) is None


def test_resolve_annotations_returns_annotations_from_the_base_schema():
    """resolveAnnotations / returns annotations from the base schema"""
    schema = S.String.annotate(title="my string")
    assert S.resolve_annotations(schema) == {"title": "my string"}


def test_resolve_annotations_returns_annotations_from_the_last_check():
    """resolveAnnotations / returns annotations from the last check"""
    schema = S.String.annotate(title="base").check(S.is_non_empty().annotate(title="check"))
    annotations = S.resolve_annotations(schema)
    assert annotations is not None
    assert annotations["title"] == "check"


# ------------------------------------------------- resolveAnnotationsKey


def test_resolve_annotations_key_returns_undefined_for_a_schema_without_key_annotations():
    """resolveAnnotationsKey / returns undefined for a schema without key annotations"""
    assert S.resolve_annotations_key(S.String) is None


def test_resolve_annotations_key_returns_key_annotations():
    """resolveAnnotationsKey / returns key annotations"""
    schema = S.String.annotate_key(message_missing_key="required")
    assert S.resolve_annotations_key(schema) == {"message_missing_key": "required"}


# ------------------------------------------------------ Schema.makeFilter


def test_make_filter_returns_undefined():
    """Schema.makeFilter / returns undefined"""
    SchemaAsserts(S.String.check(S.make_filter(lambda _: None))).decoding().succeed("a")


def test_make_filter_returns_true():
    """Schema.makeFilter / returns true"""
    SchemaAsserts(S.String.check(S.make_filter(lambda _: True))).decoding().succeed("a")


def test_make_filter_returns_false():
    """Schema.makeFilter / returns false"""
    decoding = SchemaAsserts(S.String.check(S.make_filter(lambda _: False))).decoding()
    decoding.fail("a", "Expected <filter>")


def test_make_filter_returns_string():
    """Schema.makeFilter / returns string"""
    decoding = SchemaAsserts(S.String.check(S.make_filter(lambda _: "error message"))).decoding()
    decoding.fail("a", "error message")


@pytest.mark.parametrize(
    ("abort", "expected"), [(False, "error message 1\nerror message 2"), (True, "error message 1")]
)
def test_make_filter_returns_issue(abort: bool, expected: str):
    """Schema.makeFilter / returns issue / abort: false, abort: true"""
    schema = S.String.check(
        S.make_filter(
            lambda _: S.issue.InvalidValue({"message": "error message 1"}),
            abort=abort,
            title="filter title 1",
        ),
        S.make_filter(lambda _: False, title="filter title 2", message="error message 2"),
    )
    SchemaAsserts(schema).decoding(errors="all").fail("a", expected)


@pytest.mark.parametrize(
    ("abort", "expected"),
    [
        (False, 'error message 1\n  at ["a"]\nerror message 2'),
        (True, 'error message 1\n  at ["a"]'),
    ],
)
def test_make_filter_returns_object(abort: bool, expected: str):
    """Schema.makeFilter / returns object / abort: false, abort: true"""
    schema = S.String.check(
        S.make_filter(lambda _: (("a",), "error message 1"), abort=abort, title="filter title 1"),
        S.make_filter(lambda _: False, title="filter title 2", message="error message 2"),
    )
    SchemaAsserts(schema).decoding(errors="all").fail("a", expected)


def test_make_filter_returns_object_issue():
    """Schema.makeFilter / returns object / issue: Issue"""
    schema = S.String.check(
        S.make_filter(
            lambda _: (("a",), S.issue.InvalidValue({"message": "custom issue"})),
            title="filter title",
        )
    )
    SchemaAsserts(schema).decoding().fail("a", 'custom issue\n  at ["a"]')


def test_make_filter_returns_array_empty_array_is_treated_as_success():
    """Schema.makeFilter / returns array / empty array is treated as success"""
    SchemaAsserts(S.String.check(S.make_filter(lambda _: []))).decoding().succeed("a")


def test_make_filter_returns_array_single_element_array_collapses_to_the_element():
    """Schema.makeFilter / returns array / single-element array collapses to the element"""
    schema = S.String.check(
        S.make_filter(lambda _: [(("a",), "error message 1")], title="filter title")
    )
    SchemaAsserts(schema).decoding().fail("a", 'error message 1\n  at ["a"]')


def test_make_filter_returns_array_multi_element_array_groups_into_a_composite():
    """Schema.makeFilter / returns array / multi-element array groups into a Composite"""
    schema = S.String.check(
        S.make_filter(
            lambda _: [(("a",), "error message 1"), (("b",), "error message 2")],
            title="filter title",
        )
    )
    SchemaAsserts(schema).decoding(errors="all").fail(
        "a", 'error message 1\n  at ["a"]\nerror message 2\n  at ["b"]'
    )


def test_make_filter_returns_array_mixing_string_issue_and_path_issue():
    """Schema.makeFilter / returns array / array mixing string, Issue, and { path, issue }"""
    schema = S.String.check(
        S.make_filter(
            lambda _: [
                "top-level message",
                S.issue.InvalidValue({"message": "direct issue"}),
                (("a",), "pointed message"),
            ],
            title="filter title",
        )
    )
    SchemaAsserts(schema).decoding(errors="all").fail(
        "a", 'top-level message\ndirect issue\npointed message\n  at ["a"]'
    )
