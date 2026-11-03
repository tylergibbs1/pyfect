"""Ports of Effect's ``toEquivalence.test.ts``. Each test's docstring is the
Effect test title, prefixed by its ``describe`` blocks.

Python mappings: ``Option.none()`` is ``None``, ``Result.succeed`` /
``fail`` are ``Ok`` / ``Err``, ``ReadonlySet`` / ``ReadonlyMap`` are
``FrozenSet`` / ``Map``, a ``Date``-like ``DateTimeUtc`` is an aware
``datetime``, a ``Duration`` a ``timedelta``, a zone a ``ZoneInfo`` or
``timezone``; ``optionalKey`` is a ``NotRequired`` key.

Omitted:
- ``optional`` / ``UndefinedOr`` (``undefined``), symbol keys and
  ``Record(Symbol, ...)``: no Python counterpart ("Tuple / optional
  elements", "Struct / optional fields", "Struct / symbol keys",
  "Record(String, UndefinedOr(Number))", "Record(Symbol, Number)").
- ``Date``, ``RegExp``, ``HashSet``, ``HashMap``, ``BigDecimal``: not ported
  schemas (every title naming them).
- "Duration": the infinity forms (``timedelta`` cannot be infinite); the
  finite cases are ported.
- "Class": the ``metadata`` attribute (a frozen dataclass takes none); the
  field comparison is ported.
"""

import re
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta, timezone
from typing import Literal, NotRequired, TypedDict, cast
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

import pytest

from pyfect import schema as S
from pyfect.http.url import Url
from pyfect.option import Some
from pyfect.redacted import Redacted
from pyfect.result import Err, Ok
from pyfect.schema import getter as G
from pyfect.schema import transformation as T
from pyfect.schema._to_equivalence import Equivalence


def _mod(n: int) -> Equivalence[float]:
    return lambda a, b: a % n == b % n


_MODULO_2 = S.Number.override_to_equivalence(lambda: _mod(2))
_MODULO_3 = S.Number.override_to_equivalence(lambda: _mod(3))


def test_never():
    """Never"""
    equivalence = S.to_equivalence(S.Never)
    value = object()
    assert equivalence(value, value)  # pyright: ignore[reportArgumentType]
    assert not equivalence({}, {})  # pyright: ignore[reportArgumentType]


def test_string():
    """String"""
    equivalence = S.to_equivalence(S.String)
    assert equivalence("a", "a")
    assert not equivalence("a", "b")


def test_tuple_non_array_inputs():
    """Tuple / should fail on non-array inputs"""
    equivalence = S.to_equivalence(S.Tuple(S.String, S.Number))
    assert not equivalence(("a", 1), None)  # pyright: ignore[reportArgumentType]


def test_tuple_empty():
    """Tuple / empty"""
    assert S.to_equivalence(S.Tuple())((), ())


def test_tuple_required_elements():
    """Tuple / required elements"""
    equivalence = S.to_equivalence(S.Tuple(S.String, S.Number))
    assert equivalence(("a", 1), ("a", 1))
    assert not equivalence(("a", 1), ("b", 1))


def test_tuple_optional_key_elements():
    """Tuple / optionalKey elements"""
    equivalence = S.to_equivalence(S.Tuple(S.String, S.optional_key(S.Number)))
    assert equivalence(("a", 1), ("a", 1))
    assert equivalence(("a",), ("a",))
    assert not equivalence(("a", 1), ("b", 1))
    assert not equivalence(("a",), ("b",))


def test_array():
    """Array"""
    equivalence = S.to_equivalence(S.Array(S.String))
    assert equivalence(("a", "b", "c"), ("a", "b", "c"))
    assert not equivalence(("a", "b", "c"), ("a", "b", "d"))
    assert not equivalence(("a", "b", "c"), ("a", "b"))
    assert not equivalence(("a", "b", "c"), ("a", "b", "c", "d"))


def test_tuple_with_rest():
    """TupleWithRest"""
    equivalence = S.to_equivalence(S.TupleWithRest(S.Tuple(S.String, S.Number), S.String, S.Number))
    assert equivalence(("a", 1, 2), ("a", 1, 2))
    assert equivalence(("a", 1, "b", 2), ("a", 1, "b", 2))
    assert not equivalence(("a", 1, 2), ("a", 2, 2))
    assert not equivalence(("a", 1, 2), ("a", 1, 3))
    assert not equivalence(("a", 1, "b", 2), ("c", 1, "b", 2))
    assert not equivalence(("a", 1, "b", 2), ("a", 1, "c", 2))
    assert not equivalence(("a", 1, "b", 2), ("a", 2, "b", 2))
    assert not equivalence(("a", 1, "b", 2), ("a", 1, "b", 3))


def test_tuple_with_rest_multiple_post_rest_elements():
    """TupleWithRest with multiple post-rest elements"""
    equivalence = S.to_equivalence(
        S.TupleWithRest(S.Tuple(S.String), S.String, S.Number, S.Boolean, S.String)
    )
    assert equivalence(("head", "tail", 1, True, "last"), ("head", "tail", 1, True, "last"))
    assert not equivalence(("head", "tail", 1, True, "A"), ("head", "tail", 1, True, "B"))


def _mod_schema(n: int) -> S.Bottom[float, float]:
    return S.Number.override_to_equivalence(lambda: _mod(n))


def test_rest_one_trailing_element():
    """rest elements / one trailing element after the rest element"""
    equivalence = S.to_equivalence(
        S.TupleWithRest(S.Tuple(_mod_schema(2)), _mod_schema(3), _mod_schema(5))
    )
    assert equivalence((2, 5), (4, 10))
    assert not equivalence((2, 5), (4, 7))
    assert equivalence((2, 3, 5), (4, 6, 10))
    assert not equivalence((2, 3, 5), (4, 7, 10))
    assert not equivalence((2, 3, 5), (4, 6, 7))
    assert equivalence((2, 3, 6, 5), (4, 6, 9, 10))
    assert not equivalence((2, 3, 6, 5), (4, 6, 10, 10))


def test_rest_multiple_trailing_elements():
    """rest elements / multiple trailing elements after the rest element"""
    equivalence = S.to_equivalence(
        S.TupleWithRest(S.Tuple(_mod_schema(2)), _mod_schema(3), _mod_schema(5), _mod_schema(7))
    )
    assert equivalence((2, 5, 7), (4, 10, 14))
    assert not equivalence((2, 5, 7), (4, 7, 14))
    assert not equivalence((2, 5, 7), (4, 10, 9))
    assert equivalence((2, 3, 5, 7), (4, 6, 10, 14))
    assert not equivalence((2, 3, 5, 7), (4, 7, 10, 14))


class _A(TypedDict):
    a: str


class _Empty(TypedDict):
    pass


class _AB(TypedDict):
    a: str
    b: float


class _OptionalB(TypedDict):
    a: str
    b: NotRequired[float]


def test_struct_non_record_inputs():
    """Struct / should fail on non-record inputs"""
    assert not S.to_equivalence(S.Struct(_A))({"a": "a"}, 1)  # pyright: ignore[reportArgumentType]


def test_struct_empty():
    """Struct / empty"""
    equivalence = S.to_equivalence(S.Struct(_Empty))
    a = _Empty()
    assert equivalence(a, a)
    assert equivalence(_Empty(), _Empty())


def test_struct_required_fields():
    """Struct / required fields"""
    equivalence = S.to_equivalence(S.Struct(_AB))
    assert equivalence({"a": "a", "b": 1}, {"a": "a", "b": 1})
    assert not equivalence({"a": "a", "b": 1}, {"a": "b", "b": 1})
    assert not equivalence({"a": "a", "b": 1}, {"a": "a", "b": 2})


def test_struct_optional_key_fields():
    """Struct / optionalKey fields"""
    equivalence = S.to_equivalence(S.Struct(_OptionalB))
    assert equivalence({"a": "a", "b": 1}, {"a": "a", "b": 1})
    assert equivalence({"a": "a"}, {"a": "a"})
    assert not equivalence({"a": "a"}, {"a": "b"})
    assert not equivalence({"a": "a", "b": 1}, {"a": "b", "b": 1})
    assert not equivalence({"a": "a", "b": 1}, {"a": "a", "b": 2})
    # A key present on one side only.
    assert not equivalence({"a": "a", "b": 1}, {"a": "a"})


def test_class():
    """Class"""

    class A(S.Class, identifier="A"):
        value: str

    equivalence = S.to_equivalence(A)
    assert equivalence(A(value="a"), A(value="a"))
    assert not equivalence(A(value="a"), A(value="b"))


def test_record_string_number():
    """Record / Record(String, Number)"""
    equivalence = S.to_equivalence(S.Record(S.String, S.Number))
    assert equivalence({"a": 1, "b": 2}, {"a": 1, "b": 2})
    assert not equivalence({"a": 1, "b": 2}, {"a": 1, "b": 3})
    assert not equivalence({"a": 1, "b": 2}, {"a": 2, "b": 2})
    assert not equivalence({"a": 1, "b": 2}, {"a": 1, "b": 2, "c": 3})
    assert not equivalence({"a": 1, "b": 2, "c": 3}, {"a": 1, "b": 2})


def test_record_key_checks_select_keys():
    """Record / Record(String.check, Number) should use the key checks to select keys"""
    equivalence = S.to_equivalence(
        S.Record(S.String.check(S.is_pattern(re.compile("^a"))), S.Number)
    )
    assert equivalence({"a": 1, "b": 1}, {"a": 1, "b": 2})
    assert not equivalence({"a": 1}, {"a": 2})


class _Tree(TypedDict):
    value: float
    children: tuple["_Tree", ...]


def test_suspend_reuses_the_compiled_recursive_body():
    """suspend / reuses the compiled recursive body for deeper values"""
    derivations = 0

    def strict() -> Equivalence[float]:
        nonlocal derivations
        derivations += 1
        return lambda a, b: a == b

    schema = S.Struct(_Tree, value=S.Number.override_to_equivalence(strict))

    def make(depth: int, leaf: float = 0) -> _Tree:
        return {
            "value": leaf if depth == 0 else depth,
            "children": () if depth == 0 else (make(depth - 1, leaf),),
        }

    equivalence = S.to_equivalence(schema)
    assert derivations == 1
    for depth in (1, 8, 32):
        assert equivalence(make(depth), make(depth))
        assert not equivalence(make(depth), make(depth, -1))
        assert derivations == 1


class _Recursive(TypedDict):
    a: str
    as_: tuple["_Recursive", ...]


def test_suspend_recursive_schema():
    """suspend / recursive schema"""
    equivalence = S.to_equivalence(S.Struct(_Recursive))
    assert equivalence({"a": "a", "as_": ()}, {"a": "a", "as_": ()})
    assert not equivalence({"a": "a", "as_": ()}, {"a": "b", "as_": ()})
    assert not equivalence({"a": "a", "as_": ({"a": "a", "as_": ()},)}, {"a": "a", "as_": ()})
    assert not equivalence({"a": "a", "as_": ()}, {"a": "a", "as_": ({"a": "a", "as_": ()},)})


class _Expression(TypedDict):
    type: Literal["expression"]
    value: "float | _Operation"


class _Operation(TypedDict):
    type: Literal["operation"]
    operator: Literal["+", "-"]
    left: _Expression
    right: _Expression


def _operation(operator: Literal["+", "-"] = "+", left: float = 1, right: float = 2) -> _Operation:
    return {
        "type": "operation",
        "operator": operator,
        "left": {"type": "expression", "value": left},
        "right": {"type": "expression", "value": right},
    }


def test_suspend_mutually_recursive_schemas():
    """suspend / mutually recursive schemas"""
    equivalence = S.to_equivalence(S.Struct(_Operation))
    assert equivalence(_operation(), _operation())
    assert not equivalence(_operation(), _operation(right=3))
    assert not equivalence(_operation(), _operation("-"))
    assert not equivalence(_operation(), _operation(left=2))


class _Tagged(TypedDict):
    tag: Literal["a"]
    value: str


def test_precompiles_union_members():
    """precompiles Union members"""
    derivations = 0

    def by_value() -> Equivalence[_Tagged]:
        nonlocal derivations
        derivations += 1
        return lambda a, b: a["value"] == b["value"]

    member = S.Struct(_Tagged).override_to_equivalence(by_value)
    equivalence = S.to_equivalence(S.Union(member, S.Never))
    assert derivations == 1
    assert equivalence({"tag": "a", "value": "a"}, {"tag": "a", "value": "a"})
    assert not equivalence({"tag": "a", "value": "a"}, {"tag": "a", "value": "b"})
    assert derivations == 1


class _Value(TypedDict):
    value: str


def test_selects_transformed_union_members_on_the_type_side():
    """selects transformed Union members on the Type side"""
    target = S.Struct(_Value).override_to_equivalence(lambda: lambda a, b: a["value"] == b["value"])

    def to_value(s: str) -> Mapping[str, object]:
        return {"value": s}

    def from_value(v: Mapping[str, object]) -> str:
        return cast("str", v["value"])

    transformed = S.String.pipe(
        S.decode_to(target, T.Transformation(G.transform(to_value), G.transform(from_value)))
    )
    equivalence = S.to_equivalence(S.Union(transformed, S.Boolean))
    assert equivalence({"value": "a"}, {"value": "a"})
    assert not equivalence({"value": "a"}, {"value": "b"})


def test_preserves_union_member_equivalence_annotations():
    """preserves Union member equivalence annotations"""
    flipped_twice = cast(
        "S.Bottom[str]", S.flip(S.flip(S.String).check(S.make_filter(lambda _: True)))
    )
    member = flipped_twice.override_to_equivalence(lambda: lambda a, b: a[0] == b[0])
    equivalence = S.to_equivalence(S.Union(member, S.Number))
    assert equivalence("ab", "ac")
    assert not equivalence("ab", "bc")


def _url(text: str) -> Url:
    return Url._make(urlsplit(text))


def test_url():
    """URL"""
    equivalence = S.to_equivalence(S.URL)
    assert equivalence(_url("https://example.com"), _url("https://example.com"))
    assert not equivalence(_url("https://example.com"), _url("https://example.org"))


def test_redacted_string():
    """Redacted(String)"""
    equivalence = S.to_equivalence(S.Redacted(S.String))
    assert equivalence(Redacted("a"), Redacted("a"))
    assert not equivalence(Redacted("a"), Redacted("b"))


def test_option_modulo_2():
    """Option(Modulo2)"""
    equivalence = S.to_equivalence(S.Option(_MODULO_2))
    assert equivalence(None, None)
    assert equivalence(Some(0), Some(2))
    assert equivalence(Some(1), Some(3))
    assert not equivalence(None, Some(0))
    assert not equivalence(Some(0), None)
    assert not equivalence(Some(0), Some(1))


def test_result_modulo_2_modulo_3():
    """Result(Modulo2, Modulo3)"""
    equivalence = S.to_equivalence(S.Result(_MODULO_2, _MODULO_3))
    assert equivalence(Ok(0), Ok(2))
    assert equivalence(Ok(1), Ok(3))
    assert equivalence(Err(0), Err(3))
    assert equivalence(Err(1), Err(4))
    assert equivalence(Err(2), Err(5))
    assert not equivalence(Ok(0), Err(2))
    assert not equivalence(Err(0), Ok(3))


def test_readonly_set_modulo_2():
    """ReadonlySet(Modulo2)"""
    equivalence = S.to_equivalence(S.FrozenSet(_MODULO_2))
    assert equivalence(frozenset(), frozenset())
    assert equivalence(frozenset([0]), frozenset([0]))
    assert equivalence(frozenset([0]), frozenset([2]))
    assert equivalence(frozenset([0, 1]), frozenset([1, 0]))
    assert equivalence(frozenset([0, 1]), frozenset([2, 3]))
    assert not equivalence(frozenset([0]), frozenset([1]))
    # Effect's ``new Set([2, 2])`` is a one-item set.
    assert not equivalence(frozenset([0, 1]), frozenset([2]))


@pytest.mark.parametrize("size", [0, 1])
def test_readonly_set_rejects_a_proper_subset(size: int):
    """ReadonlySet rejects a proper subset of size %i in both orders"""
    equivalence = S.to_equivalence(S.FrozenSet(_MODULO_2))
    subset = frozenset([0, 1][:size])
    superset = frozenset([0, 1])
    assert not equivalence(superset, subset)
    assert not equivalence(subset, superset)


def test_readonly_map_modulo_2_modulo_3():
    """ReadonlyMap(Modulo2, Modulo3)"""
    equivalence = S.to_equivalence(S.Map(_MODULO_2, _MODULO_3))
    assert equivalence({}, {})
    assert equivalence({0: 1}, {0: 1})
    assert equivalence({0: 1}, {2: 4})
    assert equivalence({0: 1, 1: 2}, {0: 1, 1: 2})
    assert equivalence({0: 1, 1: 2}, {1: 2, 0: 1})
    assert not equivalence({0: 1}, {1: 1})
    assert not equivalence({0: 1}, {0: 2})
    assert not equivalence({0: 1, 1: 2}, {0: 1, 1: 3})
    assert not equivalence({0: 1, 1: 2}, {0: 1, 2: 2})


@pytest.mark.parametrize("size", [0, 1])
def test_readonly_map_rejects_a_proper_subset(size: int):
    """ReadonlyMap rejects a proper subset of size %i in both orders"""
    equivalence = S.to_equivalence(S.Map(_MODULO_2, _MODULO_3))
    entries: list[tuple[float, float]] = [(0, 1), (1, 2)]
    subset = dict(entries[:size])
    superset = dict(entries)
    assert not equivalence(superset, subset)
    assert not equivalence(subset, superset)


def test_duration():
    """Duration"""
    equivalence = S.to_equivalence(S.Duration)
    assert equivalence(timedelta(milliseconds=1), timedelta(milliseconds=1))
    assert not equivalence(timedelta(milliseconds=1), timedelta(milliseconds=2))
    assert equivalence(timedelta(milliseconds=1), timedelta(microseconds=1000))


def test_date_time_utc():
    """DateTimeUtc"""
    equivalence = S.to_equivalence(S.DateTimeUtc)
    a = datetime(2021, 1, 1, tzinfo=UTC)
    assert equivalence(a, datetime(2021, 1, 1, tzinfo=UTC))
    assert not equivalence(a, a + timedelta(milliseconds=1))


def test_time_zone_offset():
    """TimeZoneOffset"""
    equivalence = S.to_equivalence(S.TimeZoneOffset)
    assert equivalence(timezone(timedelta(hours=3)), timezone(timedelta(hours=3)))
    assert not equivalence(timezone(timedelta(hours=3)), timezone(timedelta(hours=4)))


def test_time_zone_named():
    """TimeZoneNamed"""
    equivalence = S.to_equivalence(S.TimeZoneNamed)
    assert equivalence(ZoneInfo("Europe/London"), ZoneInfo("Europe/London"))
    assert not equivalence(ZoneInfo("Europe/London"), ZoneInfo("America/New_York"))


def test_time_zone():
    """TimeZone"""
    equivalence = S.to_equivalence(S.TimeZone)
    assert equivalence(timezone(timedelta(0)), timezone(timedelta(0)))
    assert not equivalence(timezone(timedelta(0)), timezone(timedelta(hours=3)))


def test_date_time_zoned():
    """DateTimeZoned"""
    equivalence = S.to_equivalence(S.DateTimeZoned)
    instant = datetime(2024, 1, 1, tzinfo=UTC)
    z1 = instant.astimezone(ZoneInfo("Europe/London"))
    same_instant = instant.astimezone(ZoneInfo("America/New_York"))
    z2 = (instant + timedelta(days=1)).astimezone(ZoneInfo("Europe/London"))
    assert equivalence(z1, z1)
    assert equivalence(z1, same_instant)
    assert not equivalence(z1, z2)


def test_override_string():
    """Annotations / overrideToEquivalence / String"""
    schema = S.String.override_to_equivalence(lambda: lambda a, b: a[:1] == b[:1])
    assert S.to_equivalence(schema)("ab", "ac")


def test_override_checked_string():
    """Annotations / overrideToEquivalence / String & isMinLength(1)"""
    schema = S.String.check(S.is_min_length(1)).override_to_equivalence(
        lambda: lambda a, b: a[:1] == b[:1]
    )
    assert S.to_equivalence(schema)("ab", "ac")


def test_override_a_compiler_owned_declaration():
    """Annotations / overrideToEquivalence / overrides a compiler-owned Declaration"""
    schema = S.Option(S.Number).override_to_equivalence(lambda: lambda a, b: True)
    assert S.to_equivalence(schema)(None, Some(1))
