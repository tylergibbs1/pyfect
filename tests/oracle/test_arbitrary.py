"""Ports of Effect's ``Arbitrary.test.ts``: the ``schema`` derivation, as
``S.to_strategy``. Each test's docstring is the Effect test title, prefixed
by its ``describe`` blocks.

Hypothesis is the runner: Effect's ``sampleEffect`` is a ``@given`` run
collecting values (``sample``), a ``checkEffect`` that always fails is
``hypothesis.find`` (``minimal``, the fully shrunk value), and a
``SampleError`` after too many discards is Hypothesis giving up
(``Unsatisfiable`` or a failed filter health check). ``Uint8Array`` is
``Bytes``, ``ReadonlySet`` / ``ReadonlyMap`` are ``FrozenSet`` / ``Map``,
a defect schema is ``S.Defect()`` (a ``Die`` holds an exception, so
Effect's ``String`` defects are not one); code-point bounds are lengths
(``len`` counts code points). Patterns end in ``\\Z`` where Effect's end
in ``$``: Python's ``$`` also matches before a final newline.

Omitted:
- ``Arbitrary.array``, ``.causes``, ``.composition``, ``.concurrency`` and
  ``.configuration.test.ts``: Effect's array/command combinators, shrink
  composition, concurrent checking and global configuration, all
  Hypothesis's job here.
- Effect's own runner, shrinker, replay and scheduling, which Hypothesis
  replaces: "mixed causes", "isArbitrary", every "combinators",
  "exhaustion", "formatCheckFailure" and "checkEffect" title, the custom
  shrinker titles ("uses a custom Schema shrinker" and the three after
  it), every title about shrinking or replaying a particular value ("keeps
  pattern constraints while shrinking strings", "shrinks ... toward ...",
  "structurally shrinks ...", "shrinks Record values before keys ...",
  "shrinks and replays fixed fields ...", "rejects key shrinks ...",
  "promotes valid shrink descendants ..."), interruption ("keeps
  asynchronous canonical codecs interruptible", "interrupts ..."), random
  streams and size scaling ("derives independent random streams ...",
  "scales ...", "grows size ...", "uses the same generated value ...",
  "uses the same recursive value ...", "starts progressive checks ..."),
  and distribution targets ("spreads ...", "targets ...", "reaches both
  integer parities ...", "biases broad character classes ...", "injects
  the approved JavaScript String edge corpus", "covers intermediate BigInt
  magnitudes ...", "generates BigInts across ...", "generates unbounded
  BigInts ...", "constructs one-sided BigInts ...", "explores strings
  around an unanchored match", "covers feasible regular-expression
  alternatives ...", "reaches longer pattern alternatives ...",
  "evaluates a residual filter once per generated value", "bounds
  residual-filter exhaustion").
- The ``TemplateLiteral`` titles are in ``test_schema_template_literal.py``.
- UTF-16 lengths, supplementary-plane pattern subtleties and JavaScript
  ``RegExp`` flags ("generates variable-length supplementary patterns ...",
  "generates variable-length patterns with code point bounds at size
  zero", "respects UTF-16 limits ...", "generates supplementary code
  points ...", "honors dot-all and sticky regular-expression flags").
- The BigDecimal shrinking titles ("shrinks BigDecimals by numeric value
  across representations", "shrinks BigDecimals toward ordinary thresholds
  between simple candidates"): Hypothesis shrinks its own choices, not the
  value by Effect's bisection; the shrunk value of the constructive title
  is checked.
- Schemas pyfect does not port: ``Date``,
  ``Symbol``, ``UniqueSymbol``, ``HashSet``, ``HashMap``, ``Chunk``,
  ``URLSearchParams``, ``File``, ``FormData``, ``MutableJson`` and
  ``StructWithRest`` (every title about them, the "indexed objects"
  block, "generates ordinary and null-prototype structural objects",
  "preserves special Record keys ...", "preserves null prototypes ...").
- "rejects integer bounds outside the safe range" (Python ints are
  unbounded and ``Int`` takes any of them) and "reaches NaN through a
  one-sided upper Number bound" (Python's ``NaN <= 0`` is false, so a
  bounded ``Number`` rejects ``NaN``).
- "constructively selects optional properties affordable by the recursion
  budget", "reserves the shared recursion budget ...", "does not assign
  recursive depth according to sibling order": Effect's size-zero budget
  accounting; the finite-path tests below cover recursion.
- "derives a five-thousand-node mutually recursive component without
  overflowing": its ten-thousand-node suspend chain form is ported.
"""

from __future__ import annotations

import enum
import re
from collections.abc import Callable, Sequence, Sized
from datetime import UTC, datetime, timedelta
from typing import Any, Literal, Never, NotRequired, TypedDict, TypeIs, cast

import pytest

pytest.importorskip("hypothesis")

from hypothesis import HealthCheck, find, given, settings
from hypothesis import strategies as st
from hypothesis.errors import FailedHealthCheck, Unsatisfiable

from pyfect import big_decimal as bd
from pyfect import schema as S
from pyfect.date_time._epoch import to_epoch_millis
from pyfect.option import Some
from pyfect.schema import ast
from pyfect.schema import transformation as T

GAVE_UP = (Unsatisfiable, FailedHealthCheck)
"""What Hypothesis raises where Effect reports a ``SampleError``."""


def _value_errors(_: tuple[Any, ...]) -> st.SearchStrategy[ValueError]:
    return st.text().map(ValueError)


DEFECTS = S.instance_of(ValueError, to_arbitrary=_value_errors)
"""Defects for ``Cause`` and ``Exit``: a declaration drawn through its
``to_arbitrary`` annotation."""


class RequiredOptional(TypedDict):
    required: str
    optional: NotRequired[float]


class ABC(TypedDict):
    a: NotRequired[str]
    b: NotRequired[str]
    c: NotRequired[str]


class Required(TypedDict):
    required: str


class Value(TypedDict):
    value: object


class OptionalValue(TypedDict):
    value: NotRequired[object]


class Structure(TypedDict):
    tuple: tuple[Any, ...]
    optional: NotRequired[str]
    record: dict[str, int]
    union: str | int


class Tree(TypedDict):
    value: str
    children: tuple[Tree, ...]


class A(TypedDict):
    _tag: Literal["A"]
    next: B | None


class B(TypedDict):
    _tag: Literal["B"]
    next: A | None


class Loop(TypedDict):
    next: Loop


def sample[T](schema: S.Codec[T, Any, Any, Any], count: int = 50) -> list[T]:
    """Up to ``count`` values ``to_strategy(schema)`` draws."""
    values: list[T] = []

    @settings(
        max_examples=count,
        database=None,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow],
    )
    @given(S.to_strategy(schema))
    def collect(value: T) -> None:
        values.append(value)

    collect()
    return values


def minimal[T](schema: S.Codec[T, Any, Any, Any]) -> T:
    """The value Hypothesis shrinks to when every value fails."""
    return find(S.to_strategy(schema), lambda _: True, settings=settings(database=None))


def verify_catalog(entries: Sequence[tuple[str, S.Codec[Any, Any, Any, Any]]]) -> None:
    for name, schema in entries:
        is_ = S.is_(schema)
        for value in sample(schema, 30):
            assert is_(value), (name, value)


def test_derives_primitive_and_structural_schemas():
    """Schema catalog / derives primitive and structural schemas"""

    class Fruit(enum.Enum):
        APPLE = "apple"
        BANANA = "banana"
        CANTALOUPE = 3

    class CatalogClass(S.Class):
        value: str

    verify_catalog(
        [
            ("Any", S.Any),
            ("Unknown", S.Unknown),
            ("Null", S.Null),
            ("String", S.String),
            ("Number", S.Number),
            ("Boolean", S.Boolean),
            ("BigInt", S.BigInt),
            ("Literals", S.Literals("a", 1, True)),
            ("Enum", S.Enum(Fruit)),
            ("Union", S.Union(S.String, S.Number)),
            ("Tuple", S.Tuple(S.String, S.optional_key(S.Number))),
            ("TupleWithRest", S.TupleWithRest(S.Tuple(S.Boolean), S.Number, S.String)),
            ("Array", S.Array(S.String)),
            (
                "Struct",
                S.Struct(RequiredOptional),
            ),
            ("Record(String)", S.Record(S.String, S.Number)),
            ("Class", CatalogClass),
        ]
    )


def test_derives_schemas_with_canonical_constraints():
    """Schema catalog / derives schemas with canonical constraints"""
    verify_catalog(
        [
            ("String length", S.String.check(S.is_min_length(2), S.is_max_length(4))),
            ("String starts with", S.String.check(S.is_starting_with("a.b"))),
            ("String ends with", S.String.check(S.is_ending_with("a+b"))),
            ("String includes", S.String.check(S.is_including("["))),
            ("Finite", S.Finite),
            ("Int32", S.Number.check(S.is_int32())),
            (
                "Int fractional bounds",
                S.Int.check(
                    S.is_between(
                        minimum=1.2, maximum=10.8, exclusive_minimum=True, exclusive_maximum=True
                    )
                ),
            ),
            (
                "BigInt bounds",
                S.BigInt.check(
                    S.is_between_big_int(
                        minimum=0, maximum=10, exclusive_minimum=True, exclusive_maximum=True
                    )
                ),
            ),
            (
                "Date bounds",
                S.DateTimeUtc.check(
                    S.is_between_date(
                        minimum=datetime(1970, 1, 1, tzinfo=UTC),
                        maximum=datetime(1970, 1, 1, 0, 0, 0, 10_000, tzinfo=UTC),
                        exclusive_minimum=True,
                        exclusive_maximum=True,
                    )
                ),
            ),
            ("Array length", S.Array(S.String).check(S.is_between_length(2, 4))),
            ("UniqueArray", S.UniqueArray(S.String).check(S.is_max_length(2))),
            (
                "Record properties",
                S.Record(S.String, S.Number).check(S.is_between_properties(2, 4)),
            ),
            (
                "Struct properties",
                S.Struct(ABC).check(S.is_between_properties(2, 2)),
            ),
            ("ReadonlyMap size", S.Map(S.String, S.Number).check(S.is_between_size(2, 4))),
        ]
    )


def test_derives_built_in_and_canonical_declarations():
    """Schema catalog / derives built-in and canonical declarations"""

    verify_catalog(
        [
            ("Json", S.Json),
            ("URL", S.URL),
            ("RegExp", S.RegExp),
            ("Duration", S.Duration),
            ("BigDecimal", S.BigDecimal),
            ("DateTimeUtc", S.DateTimeUtc),
            ("TimeZoneOffset", S.TimeZoneOffset),
            ("TimeZoneNamed", S.TimeZoneNamed),
            ("TimeZone", S.TimeZone),
            ("DateTimeZoned", S.DateTimeZoned),
            ("Uint8Array", S.Bytes),
            ("UnknownFromJsonString", S.UnknownFromJsonString),
            ("Option", S.Option(S.String)),
            ("Result", S.Result(S.Number, S.String)),
            ("ReadonlySet", S.FrozenSet(S.Number)),
            ("ReadonlyMap", S.Map(S.String, S.Number)),
            ("HashSet", S.HashSet(S.Number)),
            ("HashMap", S.HashMap(S.String, S.Number)),
            ("Redacted", S.Redacted(S.String, label="password")),
            ("CauseReason", S.CauseReason(S.String, S.Defect())),
            ("Cause", S.Cause(S.String, S.Defect())),
            ("ErrorInstance", S.ErrorInstance),
            ("Exit", S.Exit(S.Number, S.String, S.Defect())),
        ]
    )


def test_rejects_uninhabited_structural_schemas():
    """Schema catalog / rejects uninhabited structural schemas"""
    no_path = "Unable to derive an arbitrary for a schema without a finite generation path"
    with pytest.raises(ValueError, match=no_path):
        S.to_strategy(S.Never)
    with pytest.raises(ValueError, match=no_path):
        S.to_strategy(S.Struct(Value, value=S.Never))
    with pytest.raises(ValueError, match="Unable to derive an arbitrary for array constraints"):
        S.to_strategy(S.Array(S.String).check(S.is_min_length(2), S.is_max_length(1)))
    with pytest.raises(
        ValueError, match="Unable to derive an arbitrary for object property constraints"
    ):
        S.to_strategy(S.Struct(Required).check(S.is_max_properties(0)))


def test_generates_deterministic_samples_and_pushes_constraints_into_primitives():
    """schema / generates deterministic samples and pushes constraints into
    primitive constructors"""
    schema = S.String.check(S.is_min_length(8), S.is_max_length(8))
    strategy = S.to_strategy(schema)
    runs: list[list[str]] = []
    for _ in range(2):
        values: list[str] = []

        @settings(max_examples=20, database=None, derandomize=True)
        @given(strategy)
        def collect(value: str) -> None:
            values.append(value)  # noqa: B023

        collect()
        runs.append(values)
    assert runs[0] == runs[1]
    assert all(len(value) == 8 for value in runs[0])


def test_constructs_strings_for_the_regular_pattern_subset():
    """schema / constructs strings for the regular pattern subset"""
    for pattern in (
        r"^[A-Z]{3}[0-9]{3}$",
        r"^(?:foo|bar)-[^0-9]\s?\w+$",
        r"^a+?$",
        r"^\x41B$",
        "^\U0001f600{2}$",
        r"^effect$",
    ):
        schema = S.String.check(S.is_pattern(pattern))
        assert all(map(S.is_(schema), sample(schema, 20))), pattern


def test_constructs_strings_with_code_point_bounds():
    """schema / constructs strings with code point bounds and UTF-16 length
    bounds"""
    schemas = [
        S.String.check(S.is_min_code_points(128)),
        S.String.check(S.is_max_code_points(0)),
        S.String.check(S.is_between_code_points(2, 4)),
        S.String.check(S.is_min_code_points(3), S.is_min_code_points(4), S.is_max_code_points(4)),
        S.String.check(S.is_min_code_points(4), S.is_max_code_points(5), S.is_max_code_points(4)),
        S.String.check(S.is_between_length(4, 4), S.is_between_code_points(4, 4)),
        S.String.check(S.is_max_length(4), S.is_min_code_points(4)),
        S.String.check(S.is_pattern("^\U0001f600{4}$"), S.is_between_code_points(4, 4)),
    ]
    for schema in schemas:
        assert all(map(S.is_(schema), sample(schema, 20)))


def test_rejects_contradictory_code_point_and_length_constraints():
    """schema / rejects contradictory code point and UTF-16 length
    constraints"""
    for schema in (
        S.String.check(S.is_min_code_points(3), S.is_max_code_points(2)),
        S.String.check(S.is_min_code_points(3), S.is_max_length(2)),
        S.String.check(S.is_min_length(3), S.is_max_code_points(1)),
    ):
        with pytest.raises(ValueError, match=r"Unable to derive an arbitrary for .*constraints"):
            S.to_strategy(schema)


def test_combines_pattern_generation_with_string_length_constraints():
    """schema / combines constructive pattern generation with string length
    constraints"""
    schema = S.String.check(S.is_pattern(r"^(ab){3,10}\Z"), S.is_min_length(8), S.is_max_length(12))
    values = sample(schema)
    assert all(map(S.is_(schema), values))
    assert all(len(value) in (8, 10, 12) for value in values)


def test_uses_every_supported_pattern_as_a_candidate():
    """schema / uses every supported pattern as a candidate and validates
    against every pattern"""
    schema = S.String.check(S.is_pattern(r"^[^A-Z]*\Z"), S.is_pattern(r"^0x[0-9a-f]{40}\Z"))
    assert all(map(S.is_(schema), sample(schema, 20)))


def test_keeps_unsupported_patterns_as_residual_filters():
    """schema / keeps unsupported patterns as residual filters"""
    schema = S.String.check(S.is_pattern(r"^(?=a)a\Z"), S.is_pattern(r"^a\Z"))
    assert set(sample(schema, 20)) == {"a"}


def test_bounds_fallback_filtering_for_unsupported_constructs():
    """schema / bounds fallback filtering for unsupported regular expression
    constructs"""
    with pytest.raises(GAVE_UP):
        sample(S.String.check(S.is_pattern(r"^(?=a)b\Z")), 1)


def test_uses_generic_generation_for_permissive_unsupported_patterns():
    """schema / uses generic generation for permissive unsupported regular
    expressions"""
    schema = S.String.check(S.is_pattern(r"^(?=)[ -~]*\Z"))
    assert all(map(S.is_(schema), sample(schema, 20)))


def test_bounds_incompatible_pattern_and_length_constraints():
    """schema / bounds incompatible pattern and length constraints"""
    for schema in (
        S.String.check(S.is_pattern(r"^(aa)+\Z"), S.is_min_length(3), S.is_max_length(3)),
        S.String.check(S.is_pattern(r"^\Z"), S.is_min_length(1)),
    ):
        with pytest.raises(GAVE_UP):
            sample(schema, 1)


def test_constructs_strings_for_built_in_pattern_checks():
    """schema / constructs strings for built-in pattern checks"""
    for check in (
        S.is_trimmed(),
        S.is_uppercased(),
        S.is_lowercased(),
        S.is_capitalized(),
        S.is_uncapitalized(),
        S.is_starting_with("a.b"),
        S.is_ending_with("a.b"),
        S.is_including("a.b"),
    ):
        schema = S.String.check(check)
        assert all(map(S.is_(schema), sample(schema, 20)))


def test_generates_web_url_declarations_without_codec_filtering():
    """schema / generates and shrinks web URL declarations without codec
    filtering"""
    values = sample(S.URL, 100)
    assert {url.protocol for url in values} == {"http:", "https:"}
    assert any(url.pathname != "/" for url in values)
    assert minimal(S.URL).protocol in ("http:", "https:")


_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_TEN_MS = _EPOCH + timedelta(milliseconds=10)


def _within_ten_ms(schema: S.Bottom[datetime, Any, Any, Any]) -> S.Bottom[datetime, Any, Any, Any]:
    return schema.check(
        S.is_between_date(
            minimum=_EPOCH, maximum=_TEN_MS, exclusive_minimum=True, exclusive_maximum=True
        )
    )


def test_generates_date_time_utc_declarations_constructively():
    """schema / generates and shrinks DateTime.Utc declarations
    constructively"""
    assert all(map(S.is_(S.DateTimeUtc), sample(S.DateTimeUtc, 200)))
    constrained = _within_ten_ms(S.DateTimeUtc)
    values = sample(constrained, 100)
    assert all(map(S.is_(constrained), values))
    assert all(0 < to_epoch_millis(value) < 10 for value in values)
    assert to_epoch_millis(minimal(S.DateTimeUtc)) == 0


def test_generates_named_and_offset_time_zone_declarations():
    """schema / generates named and offset TimeZone declarations
    constructively"""
    named = sample(S.TimeZoneNamed, 100)
    zones = sample(S.TimeZone, 200)
    assert all(map(S.is_(S.TimeZoneNamed), named))
    assert len({str(zone) for zone in named}) > 1
    assert all(map(S.is_(S.TimeZone), zones))
    assert any(S.is_(S.TimeZoneNamed)(zone) for zone in zones)
    assert any(S.is_(S.TimeZoneOffset)(zone) for zone in zones)


def test_generates_date_time_zoned_declarations_constructively():
    """schema / generates and shrinks DateTime.Zoned declarations
    constructively"""
    values = sample(S.DateTimeZoned, 200)
    assert all(map(S.is_(S.DateTimeZoned), values))
    assert any(S.is_(S.TimeZoneNamed)(value.tzinfo) for value in values)
    assert any(S.is_(S.TimeZoneOffset)(value.tzinfo) for value in values)
    constrained = _within_ten_ms(S.DateTimeZoned)
    zoned = sample(constrained, 100)
    assert all(map(S.is_(constrained), zoned))
    assert all(0 < to_epoch_millis(value) < 10 for value in zoned)
    assert S.is_(S.DateTimeZoned)(minimal(S.DateTimeZoned))


def test_generates_uint8_array_declarations_through_array_semantics():
    """schema / generates and shrinks Uint8Array declarations through Array
    semantics"""
    schema = S.Bytes.check(S.is_min_length(2), S.is_max_length(10))
    values = sample(schema, 300)
    assert all(map(S.is_(schema), values))
    assert {len(value) for value in values} >= {2, 10}
    assert minimal(schema) == b"\x00\x00"


def test_supports_unique_collections():
    """schema / supports unique collections"""
    schema = S.UniqueArray(S.Int).check(S.is_min_length(4), S.is_max_length(4))
    assert all(len(value) == 4 == len(set(value)) for value in sample(schema, 20))


def test_uses_effect_equality_for_constructive_uniqueness():
    """schema / uses Effect equality for constructive uniqueness"""
    schema = S.UniqueArray(S.Struct(Value, value=S.Literal(1))).check(
        S.is_min_length(2), S.is_max_length(2)
    )
    with pytest.raises(GAVE_UP):
        sample(schema, 1)


def test_preserves_unique_collections_while_shrinking():
    """schema / preserves unique collections while shrinking"""
    schema = S.UniqueArray(S.Int).check(S.is_min_length(2), S.is_max_length(4))
    assert S.is_(schema)(minimal(schema))


def test_generates_optional_rest_record_and_union_structure():
    """schema / generates optional, rest, record, and union structure"""
    schema = S.Struct(
        Structure,
        tuple=S.TupleWithRest(S.Tuple(S.String, S.optional_key(S.Int)), S.Boolean),
        record=S.Record(S.String, S.Int).check(S.is_max_properties(3)),
        union=S.Union(S.String, S.Int),
    )
    assert all(map(S.is_(schema), sample(schema)))


def test_omits_optional_never_properties():
    """schema / omits optional Never properties"""
    schema = S.Struct(OptionalValue, value=S.Never)
    assert sample(schema, 5) == [{}]


def test_uses_inhabited_branches_around_never():
    """schema / uses inhabited branches around Never"""
    assert sample(S.Union(S.Never, S.Literal("value")), 5) == ["value"]
    assert sample(S.Array(S.Never), 5) == [()]


def test_validates_overlapping_one_of_union_members():
    """schema / validates overlapping oneOf Union members"""
    schema = S.Union(S.String, S.Literal("a"), mode="one_of")
    values = sample(schema, 100)
    assert all(map(S.is_(schema), values))
    assert "a" not in values


def test_bounds_exhaustion_for_an_uninhabited_one_of_union():
    """schema / bounds exhaustion for an uninhabited oneOf Union"""
    with pytest.raises(GAVE_UP):
        sample(S.Union(S.Literal("a"), S.Literal("a"), mode="one_of"), 1)


def test_generates_unknown_and_any_through_json():
    """schema / generates Unknown and Any through Json"""
    for schema in (S.Unknown, S.Any):
        assert all(map(S.is_(S.Json), sample(schema, 30)))


def test_derives_json_through_its_built_in_representation():
    """schema / derives Json through its built-in representation"""
    assert all(map(S.is_(S.Json), sample(S.Json, 30)))


def test_prefers_an_explicit_to_codec_arbitrary_over_a_built_in():
    """schema / prefers an explicit toCodecArbitrary over a built-in
    representation"""

    from pyfect.http.url import Url

    expected = "https://effect.website/custom"

    def custom(_: tuple[ast.AST, ...], __: S.ArbitraryConstraint) -> ast.Link:
        return ast.Link(
            S.Literal(expected).ast,
            T.transform(decode=Url, encode=lambda _: expected),
        )

    values: list[Url] = sample(S.URL.annotate(to_codec_arbitrary=custom), 10)
    assert {str(value) for value in values} == {expected}


def test_derives_canonical_declarations_through_their_codec():
    """schema / derives canonical declarations through their codec"""
    schema = S.Option(S.Int)
    values = sample(schema, 30)
    assert all(map(S.is_(schema), values))
    assert any(isinstance(value, Some) for value in values)
    assert None in values


def _same(value: float) -> float:
    return value


def _is_number(value: object) -> TypeIs[float]:
    return isinstance(value, int | float) and not isinstance(value, bool)


def test_prefers_to_codec_arbitrary_and_passes_normalized_constraints():
    """schema / prefers toCodecArbitrary and passes normalized constraints
    without Order"""
    received: list[S.ArbitraryConstraint] = []

    def to_codec(_: tuple[ast.AST, ...]) -> ast.Link:
        return ast.Link(S.Literal(99).ast, T.transform(decode=lambda n: n, encode=lambda _: 99))

    def to_codec_arbitrary(_: tuple[ast.AST, ...], constraint: S.ArbitraryConstraint) -> ast.Link:
        received.append(constraint)
        between = S.is_between(
            minimum=constraint.minimum,
            maximum=constraint.maximum,
            exclusive_minimum=constraint.exclusive_minimum,
            exclusive_maximum=constraint.exclusive_maximum,
        )
        return ast.Link(S.Int.check(between).ast, T.transform(decode=_same, encode=_same))

    declaration = S.declare(
        _is_number, to_codec=to_codec, to_codec_arbitrary=to_codec_arbitrary
    ).check(S.is_between(minimum=1, maximum=4, exclusive_minimum=True))
    values = sample(declaration, 100)
    assert received == [S.ArbitraryConstraint(minimum=1, maximum=4, exclusive_minimum=True)]
    assert all(1 < value <= 4 for value in values)


def test_rejects_contradictory_constraints_before_invoking_to_codec_arbitrary():
    """schema / rejects contradictory generation constraints before invoking
    toCodecArbitrary"""
    invoked: list[bool] = []

    def to_codec_arbitrary(_: tuple[ast.AST, ...], __: S.ArbitraryConstraint) -> ast.Link:
        invoked.append(True)
        return ast.Link(S.Number.ast, T.transform(decode=_same, encode=_same))

    def accept(_: float) -> bool:
        return True

    declaration = S.declare(_is_number, to_codec_arbitrary=to_codec_arbitrary).check(
        S.make_filter(accept, arbitrary_constraint=S.ArbitraryConstraint(min_length=2)),
        S.make_filter(accept, arbitrary_constraint=S.ArbitraryConstraint(max_length=1)),
    )
    with pytest.raises(ValueError, match="Unable to derive an arbitrary for constraints"):
        S.to_strategy(declaration)
    assert invoked == []


def test_derives_productive_structural_declarations_through_canonical_codecs():
    """schema / derives productive structural declarations through canonical
    codecs"""
    verify_catalog(
        [
            ("Result", S.Result(S.Number, S.String)),
            ("Redacted", S.Redacted(S.String)),
            ("ReadonlySet", S.FrozenSet(S.Int)),
            ("HashSet", S.HashSet(S.Int)),
            ("ReadonlyMap", S.Map(S.String, S.Int)),
            ("HashMap", S.HashMap(S.String, S.Int)),
            ("Duration", S.Duration),
            ("Cause", S.Cause(S.String, DEFECTS)),
            ("Exit", S.Exit(S.Int, S.String, DEFECTS)),
            ("TimeZoneOffset", S.TimeZoneOffset),
        ]
    )


def test_constructs_collection_cardinality_through_declaration_annotations():
    """schema / constructs collection cardinality through declaration
    annotations"""

    def three(value: Sized) -> bool:
        return len(value) == 3

    exactly_three = S.ArbitraryConstraint(min_size=3, max_size=3)
    hash_set = S.HashSet(S.Int).check(S.make_filter(three, arbitrary_constraint=exactly_three))
    keys = S.Literals("a", "b", "c")
    hash_map = S.HashMap(keys, S.Boolean).check(
        S.make_filter(three, arbitrary_constraint=exactly_three)
    )
    schemas: list[S.Bottom[Any, Any, Any, Any]] = [
        S.FrozenSet(S.Int).check(S.is_between_size(3, 3)),
        hash_set,
        S.Map(keys, S.Boolean).check(S.is_between_size(3, 3)),
        hash_map,
    ]
    for schema in schemas:
        assert all(len(value) == 3 for value in sample(schema, 30))


def test_preserves_map_key_uniqueness_while_shrinking():
    """schema / preserves Map key uniqueness while shrinking"""
    schema = S.Map(S.Literals("a", "b", "c"), S.Int).check(S.is_between_size(2, 3))
    assert len(minimal(schema)) == 2


def test_generates_recursive_schemas_with_a_finite_path():
    """schema / generates recursive schemas with a finite path"""
    node: S.Bottom[Tree, Any, Any, Any] = S.Struct(
        Tree, children=S.Array(S.suspend(lambda: node)).check(S.is_max_length(3))
    )
    assert all(map(S.is_(node), sample(node, 30)))


def test_generates_mutually_recursive_schemas():
    """schema / generates mutually recursive schemas"""
    a: S.Bottom[A, Any, Any, Any] = S.Struct(A, next=S.NullOr(S.suspend(lambda: b)))
    b: S.Bottom[B, Any, Any, Any] = S.Struct(B, next=S.NullOr(S.suspend(lambda: a)))
    values = sample(a, 50)
    assert all(map(S.is_(a), values))
    assert any(value["next"] is not None for value in values)


def test_derives_mutually_recursive_declarations_through_to_codec_arbitrary():
    """schema / derives mutually recursive declarations through
    toCodecArbitrary"""

    def is_tagged(tag: str) -> Callable[[object], TypeIs[Any]]:
        def guard(value: object) -> TypeIs[Any]:
            return isinstance(value, dict) and cast("dict[str, object]", value).get("_tag") == tag

        return guard

    def passthrough(struct: Callable[[], S.Bottom[Any, Any, Any, Any]]) -> Any:
        def to_codec_arbitrary(_: tuple[ast.AST, ...], __: S.ArbitraryConstraint) -> ast.Link:
            return ast.Link(struct().ast, T.transform(decode=_same, encode=_same))

        return to_codec_arbitrary

    a: S.Bottom[A, Any, Any, Any] = S.declare(
        is_tagged("A"),
        to_codec_arbitrary=passthrough(
            lambda: S.Struct(A, _tag=S.Literal("A"), next=S.NullOr(S.suspend(lambda: b)))
        ),
    )
    b: S.Bottom[B, Any, Any, Any] = S.declare(
        is_tagged("B"),
        to_codec_arbitrary=passthrough(
            lambda: S.Struct(B, _tag=S.Literal("B"), next=S.NullOr(S.suspend(lambda: a)))
        ),
    )
    values = sample(a, 100)
    assert all(map(S.is_(a), values))
    assert any(value["next"] is not None and value["next"]["_tag"] == "B" for value in values)


def _constant(schema: S.Bottom[Any, Any, Any, Any]) -> Callable[[], S.Bottom[Any, Any, Any, Any]]:
    return lambda: schema


def _suspend_chain(count: int) -> S.Bottom[Any, Any, Any, Any]:
    schema: S.Bottom[Any, Any, Any, Any] = S.Null
    for _ in range(count):
        schema = S.suspend(_constant(schema))
    return schema


def test_derives_and_samples_a_long_suspend_chain():
    """schema / derives and samples a ten-thousand-node suspend chain without
    overflowing"""
    assert sample(_suspend_chain(10_000), 3) == [None]


def test_discovers_a_recursive_finite_path_through_a_canonical_declaration():
    """schema / discovers a recursive finite path through a canonical
    declaration"""
    node: S.Bottom[Any, Any, Any, Any] = S.Option(S.suspend(lambda: node))
    assert all(map(S.is_(node), sample(node, 20)))


def test_fails_immediately_for_recursion_without_a_finite_path():
    """schema / fails immediately for recursion without a finite path"""
    node: S.Bottom[Loop, Any, Any, Any] = S.Struct(Loop, next=S.suspend(lambda: node))
    with pytest.raises(ValueError, match="without a finite generation path"):
        S.to_strategy(node)


def test_treats_unproductive_recursive_union_branches_as_empty():
    """schema / treats unproductive recursive union branches as empty"""
    loop: S.Bottom[Loop, Any, Any, Any] = S.Struct(Loop, next=S.suspend(lambda: loop))
    assert sample(S.Union(loop, S.Literal("base")), 5) == ["base"]


def test_fails_immediately_for_unsupported_declarations():
    """schema / fails immediately for unsupported declarations"""

    class Opaque:
        pass

    def is_opaque(value: object) -> TypeIs[Opaque]:
        return isinstance(value, Opaque)

    with pytest.raises(ValueError, match="unsupported Declaration"):
        S.to_strategy(S.declare(is_opaque))


def test_to_arbitrary_annotation():
    """(Python) a declaration's ``to_arbitrary`` annotation builds its
    strategy from its type parameters' strategies"""

    class Opaque:
        def __init__(self, n: int) -> None:
            self.n = n

    def is_opaque(value: object) -> TypeIs[Opaque]:
        return isinstance(value, Opaque)

    def make(_: tuple[Any, ...]) -> st.SearchStrategy[Opaque]:
        return st.integers(0, 3).map(Opaque)

    values = sample(S.declare(is_opaque, to_arbitrary=make), 20)
    assert {value.n for value in values} <= {0, 1, 2, 3}


def _bounded(
    minimum: float | None = None,
    maximum: float | None = None,
    *,
    exclusive_minimum: bool = False,
    exclusive_maximum: bool = False,
) -> S.Bottom[float, Any, Any, Any]:
    """``Number`` within a bound that may be infinite (Effect's
    ``makeIsBetween({ order: Order.Number })``): the check and its
    generation constraint."""

    def accepts(n: float) -> bool:
        low = minimum is None or (n > minimum if exclusive_minimum else n >= minimum)
        high = maximum is None or (n < maximum if exclusive_maximum else n <= maximum)
        return low and high

    constraint = S.ArbitraryConstraint(
        minimum=minimum,
        maximum=maximum,
        exclusive_minimum=exclusive_minimum,
        exclusive_maximum=exclusive_maximum,
    )
    return S.Number.check(S.make_filter(accepts, arbitrary_constraint=constraint))


def test_generates_the_sole_number_between_adjacent_exclusive_bounds():
    """schema / generates the sole Number between adjacent exclusive IEEE-754
    bounds"""
    minimum, unit = 2.0**100, 2.0**48
    schema = S.Number.check(
        S.is_between(
            minimum=minimum,
            maximum=minimum + unit * 2,
            exclusive_minimum=True,
            exclusive_maximum=True,
        )
    )
    assert set(sample(schema, 20)) == {minimum + unit}


def test_preserves_both_signed_zeros_in_an_inclusive_zero_interval():
    """schema / preserves both signed zeros in an inclusive zero interval"""
    import math

    values = sample(S.Number.check(S.is_between(minimum=0, maximum=0)), 50)
    assert all(value == 0 for value in values)
    assert {math.copysign(1, value) for value in values} == {-1.0, 1.0}


def test_generates_exact_subnormal_and_infinite_singleton_intervals():
    """schema / generates exact subnormal and infinite singleton intervals"""
    import math
    import sys

    expected = [
        -math.inf,
        -sys.float_info.max,
        -5e-324,
        5e-324,
        sys.float_info.max,
        math.inf,
    ]
    assert [sample(_bounded(v, v), 1)[0] for v in expected] == expected


def test_generates_infinity_from_one_sided_inclusive_bounds():
    """schema / generates infinity from one-sided inclusive bounds (NaN is
    not below a bound in Python, so only the infinities are asserted)"""
    import math

    assert sample(_bounded(minimum=math.inf), 1) == [math.inf]
    negatives = _bounded(maximum=-math.inf)
    assert set(sample(negatives, 20)) == {-math.inf}


def test_rejects_nan_numeric_bounds():
    """schema / rejects NaN numeric bounds"""
    import math

    with pytest.raises(ValueError, match="Unable to derive an arbitrary for number constraints"):
        S.to_strategy(_bounded(minimum=math.nan, maximum=1))
    with pytest.raises(ValueError, match="Unable to derive an arbitrary for integer constraints"):
        S.to_strategy(_bounded(minimum=0, maximum=math.nan).check(S.is_int()))


def test_rejects_infinite_intervals_excluded_by_a_finite_constraint():
    """schema / rejects infinite intervals excluded by a finite constraint"""
    import math

    with pytest.raises(ValueError, match="Unable to derive an arbitrary for number constraints"):
        S.to_strategy(_bounded(minimum=math.inf).check(S.is_finite()))


def test_rejects_empty_numeric_intervals():
    """(Python) an empty number, integer, bigint or enum domain raises when
    the strategy is derived, as Effect's ``validateConstraint``,
    ``numberBounds`` and ``BigInt`` / ``Enum`` cases do"""
    import math

    with pytest.raises(ValueError, match="for constraints"):
        S.to_strategy(S.Number.check(S.is_between(minimum=1, maximum=1, exclusive_minimum=True)))
    adjacent = S.is_between(
        minimum=1.0,
        maximum=math.nextafter(1.0, 2.0),
        exclusive_minimum=True,
        exclusive_maximum=True,
    )
    with pytest.raises(ValueError, match="for number constraints"):
        S.to_strategy(S.Number.check(adjacent))
    with pytest.raises(ValueError, match="for integer constraints"):
        S.to_strategy(S.Int.check(S.is_between(minimum=1.2, maximum=1.8)))
    with pytest.raises(ValueError, match="for bigint constraints"):
        S.to_strategy(
            S.BigInt.check(
                S.is_between_big_int(
                    minimum=1, maximum=2, exclusive_minimum=True, exclusive_maximum=True
                )
            )
        )

    class Empty(enum.Enum):
        pass

    with pytest.raises(ValueError, match="for an enum with no members"):
        S.to_strategy(S.Enum(Empty))


def test_draws_bounded_numbers():
    """(Python) a Number bounded on both sides draws values within the bounds"""
    schema = S.Number.check(S.is_between(minimum=-1.5, maximum=10))
    values = sample(schema, 50)
    assert all(map(S.is_(schema), values))
    assert any(isinstance(value, float) for value in values)


class Branch(TypedDict):
    left: Branch | None
    right: Branch | None


def _depth(tree: Branch | None) -> int:
    return 0 if tree is None else 1 + max(_depth(tree["left"]), _depth(tree["right"]))


def test_recursion_is_bounded_by_the_recursion_budget():
    """(Python) a value passes through a cyclic suspend at most
    ``RECURSION_DEPTH`` times, so recursive values stay small"""
    from pyfect.schema._strategy import RECURSION_DEPTH

    branch: S.Bottom[Branch, Any, Any, Any] = S.Struct(
        Branch,
        left=S.NullOr(S.suspend(lambda: branch)),
        right=S.NullOr(S.suspend(lambda: branch)),
    )
    values = sample(branch, 100)
    assert max(map(_depth, values)) <= RECURSION_DEPTH + 1


class Link(TypedDict):
    next: Any


def test_recursion_budget_grows_to_the_shortest_finite_path():
    """(Python) a recursive schema whose every value passes through more
    cyclic suspends than ``RECURSION_DEPTH`` still draws: the budget is the
    cost of its shortest finite path"""
    from pyfect.schema._strategy import RECURSION_DEPTH

    hops = RECURSION_DEPTH + 2
    chain: list[S.Bottom[Any, Any, Any, Any]] = []

    def hop(i: int) -> S.Bottom[Any, Any, Any, Any]:
        return S.suspend(lambda: chain[(i + 1) % hops])

    chain.extend(S.Struct(Link, next=hop(i)) for i in range(hops - 1))
    chain.append(S.NullOr(S.Struct(Link, next=hop(hops - 1))))
    values = sample(chain[0], 10)
    assert all(map(S.is_(chain[0]), values))


def test_generates_reg_exp_declarations_without_codec_filtering():
    """Built-in declarations / generates RegExp declarations without codec filtering"""
    values = sample(S.RegExp, 100)
    assert all(isinstance(value, re.Pattern) for value in values)
    assert len({value.pattern for value in values}) > 1
    assert len({value.flags for value in values}) > 1


_MAX_SAFE = 2**53 - 1


def _between(
    minimum: bd.BigDecimal, maximum: bd.BigDecimal, exclusive: bool = False
) -> S.Codec[bd.BigDecimal, bd.BigDecimal, Never, Never]:
    return S.BigDecimal.check(
        S.is_between_big_decimal(
            minimum=minimum,
            maximum=maximum,
            exclusive_minimum=exclusive,
            exclusive_maximum=exclusive,
        )
    )


def test_generates_and_shrinks_big_decimal_declarations_constructively():
    """Built-in declarations / generates and shrinks BigDecimal declarations constructively"""
    values = sample(S.BigDecimal, 500)
    assert all(map(S.is_(S.BigDecimal), values))
    assert len({value.scale for value in values}) > 1
    constrained = _between(bd.make(1_234, 3), bd.make(1_236, 3), exclusive=True)
    assert all(map(S.is_(constrained), sample(constrained, 500)))
    high_scale = _between(bd.make(-12_345, 22), bd.make(678_901, 24))
    assert all(map(S.is_(high_scale), sample(high_scale, 500)))
    assert minimal(S.BigDecimal) == bd.make(0, 0)


def test_covers_independent_big_decimal_precision_and_exponent_ranges():
    """Built-in declarations / covers independent BigDecimal precision and exponent ranges"""
    values = sample(S.BigDecimal, 1_000)
    assert any(abs(value.scale) > 20 for value in values)
    assert any(len(str(abs(value.value))) > 20 for value in values)


def test_constructs_big_decimals_in_narrow_and_extreme_scale_intervals():
    """Built-in declarations / constructs BigDecimals in narrow and extreme-scale intervals"""
    narrow = _between(bd.make(123_456_789, 1_000), bd.make(123_456_799, 1_000), exclusive=True)
    assert all(map(S.is_(narrow), sample(narrow, 200)))
    maximum_scale = _between(bd.make(0, _MAX_SAFE), bd.make(1, _MAX_SAFE))
    assert all(map(S.is_(maximum_scale), sample(maximum_scale, 50)))


def test_recognizes_equivalent_big_decimal_singleton_bounds():
    """Built-in declarations / recognizes equivalent BigDecimal singleton bounds"""
    for minimum, maximum in [
        (bd.make(1, 0), bd.make(10, 1)),
        (bd.make(10**4097, 0), bd.make(1, -4097)),
        (bd.make(-1, -4097), bd.make(-(10**4097), 0)),
        (bd.make(0, -_MAX_SAFE), bd.make(0, _MAX_SAFE)),
    ]:
        values = sample(_between(minimum, maximum), 20)
        assert values
        assert all(value == minimum for value in values)


def test_preserves_both_big_decimal_bounds_across_large_scale_differences():
    """Built-in declarations / preserves both BigDecimal bounds across large scale differences"""
    near = bd.make(10**4097 - 1, 0)
    far = bd.make(1, -4097)
    for minimum, maximum in [(near, far), (far.negate(), near.negate())]:
        for exclusive in (False, True):
            schema = _between(minimum, maximum, exclusive)
            values = sample(schema, 100)
            assert all(map(S.is_(schema), values))
            assert any(minimum < value < maximum for value in values)


def test_rejects_empty_big_decimal_intervals_at_the_maximum_scale():
    """Built-in declarations / rejects empty BigDecimal intervals at the maximum scale"""
    schema = _between(bd.make(0, _MAX_SAFE), bd.make(1, _MAX_SAFE), exclusive=True)
    with pytest.raises(
        ValueError, match="Unable to derive an arbitrary for BigDecimal constraints"
    ):
        S.to_strategy(schema)
