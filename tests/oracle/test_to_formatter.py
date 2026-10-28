"""Ports of Effect's ``toFormatter.test.ts``. Each test's docstring is the
Effect test title, prefixed by its ``describe`` blocks.

Python mappings as in ``test_to_equivalence.py``. A value without a
formatter of its own is written by ``format_unknown`` (Effect's
``Formatter.format``): ``None`` is ``null``, an ``int`` has no ``n``
suffix (a ``BigInt`` is a Python ``int``), a ``timedelta`` is its ``str``
(``Duration`` has no formatter in Effect either: its text is the value's
own). ``FrozenSet`` / ``Map`` values are written under those names
(Effect's ``ReadonlySet`` / ``ReadonlyMap``); an enum member as its value.

Omitted:
- ``Void``, ``Undefined``, ``Symbol``, ``UniqueSymbol``, ``ObjectKeyword``,
  ``optional`` / ``UndefinedOr``, symbol keys, ``Literal(1n)``: no Python
  counterpart ("Void", "Symbol", "UniqueSymbol", "ObjectKeyword", "Literal
  / bigint", "Struct / required field with undefined", "Struct / optional
  field", "Record(Symbol, Option(Number))", "suspend / optional", "suspend /
  optional + Array", "ReadonlySet(Symbol)", "ReadonlyMap(Symbol, String)").
- "StructWithRest": ported in ``test_schema_struct_with_rest.py``.
- ``TemplateLiteral``, ``Date``, ``RegExp``,
  ``HashMap``, ``HashSet``, ``Chunk``, ``BigDecimal``: not ported schemas
  (every title naming them).
- "Duration": ``timedelta``'s own text instead (see above).
- "Enum / Const enum": a Python ``Enum`` is a class (the other enum titles
  are ported).
- "custom class": Effect writes an instance's fields as JSON; Python's
  ``format_unknown`` names the class the same way (ported), and "custom
  class with a toString() method" is ``__str__`` (ported).
"""

import enum
import re
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta, timezone
from typing import Any, Literal, NotRequired, TypedDict, cast
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from pyfect import schema as S
from pyfect.date_time import format_iso_zoned
from pyfect.option import Option, Some
from pyfect.redacted import Redacted
from pyfect.result import Err, Ok
from pyfect.schema import ast
from pyfect.schema import getter as G
from pyfect.schema import transformation as T
from pyfect.schema._to_formatter import Formatter


def test_never():
    """Never"""
    assert S.to_formatter(S.Never)(1) == "never"  # pyright: ignore[reportArgumentType]


def _check_unknown(format: Formatter[Any]) -> None:
    assert format(1) == "1"
    assert format("a") == '"a"'
    assert format(True) == "true"
    assert format(False) == "false"
    assert format(None) == "null"
    assert format({"a": 1}) == '{"a":1}'
    assert format([1, 2, 3]) == "[1,2,3]"


def test_any():
    """Any"""
    _check_unknown(S.to_formatter(S.Any))


def test_unknown():
    """Unknown"""
    _check_unknown(S.to_formatter(S.Unknown))


def test_null():
    """Null"""
    assert S.to_formatter(S.Null)(None) == "null"


def test_string():
    """String"""
    assert S.to_formatter(S.String)("a") == '"a"'


def test_number():
    """Number"""
    assert S.to_formatter(S.Number)(1) == "1"


def test_boolean():
    """Boolean"""
    format = S.to_formatter(S.Boolean)
    assert format(True) == "true"
    assert format(False) == "false"


def test_big_int():
    """BigInt"""
    # Python: an int has no ``n`` suffix.
    assert S.to_formatter(S.BigInt)(1) == "1"


def test_literal_string():
    """Literal / string"""
    assert S.to_formatter(S.Literal("a"))("a") == '"a"'


def test_literal_number():
    """Literal / number"""
    assert S.to_formatter(S.Literal(1))(1) == "1"


def test_literal_boolean():
    """Literal / boolean"""
    assert S.to_formatter(S.Literal(True))(True) == "true"


def test_literals():
    """Literals"""
    format = S.to_formatter(S.Literals("a", "b", "c"))
    assert format("a") == '"a"'
    assert format("b") == '"b"'
    assert format("c") == '"c"'


class _Numeric(enum.Enum):
    APPLE = 0
    BANANA = 1


class _Fruits(enum.Enum):
    APPLE = "apple"
    BANANA = "banana"
    CANTALOUPE = 0


def test_numeric_enum():
    """Enum / Numeric enum"""
    assert S.to_formatter(S.Enum(_Numeric))(_Numeric.APPLE) == "0"


def test_string_enum():
    """Enum / String enum"""
    assert S.to_formatter(S.Enum(_Fruits))(_Fruits.APPLE) == '"apple"'


def test_union():
    """Union"""
    format = S.to_formatter(S.Union(S.String, S.Number))
    assert format("a") == '"a"'
    assert format(1) == "1"


def test_precompiles_union_members():
    """precompiles Union members"""
    derivations = 0

    def upper() -> Formatter[str]:
        nonlocal derivations
        derivations += 1
        return str.upper

    string = S.String.override_to_formatter(upper)
    format = S.to_formatter(S.Union(string, S.Number, S.Never))
    assert derivations == 1
    assert format("a") == "A"
    assert format("b") == "B"
    assert derivations == 1


class _Value(TypedDict):
    value: str


def test_selects_transformed_union_members_on_the_type_side():
    """selects transformed Union members on the Type side"""
    target = S.Struct(_Value).override_to_formatter(lambda: lambda a: f"formatted:{a['value']}")

    def to_value(s: str) -> Mapping[str, object]:
        return {"value": s}

    def from_value(v: Mapping[str, object]) -> str:
        return cast("str", v["value"])

    transformed = S.String.pipe(
        S.decode_to(target, T.Transformation(G.transform(to_value), G.transform(from_value)))
    )
    assert S.to_formatter(S.Union(transformed, S.Boolean))({"value": "a"}) == "formatted:a"


def test_preserves_union_member_formatter_annotations():
    """preserves Union member formatter annotations"""
    flipped_twice = cast(
        "S.Bottom[str]", S.flip(S.flip(S.String).check(S.make_filter(lambda _: True)))
    )
    member = flipped_twice.override_to_formatter(lambda: str.upper)
    assert S.to_formatter(S.Union(member, S.Number))("a") == "A"


def test_preserves_union_member_encoding_metadata_for_on_before():
    """preserves Union member encoding metadata for onBefore"""

    def same(s: str) -> str:
        return s

    member = S.String.pipe(S.decode(T.Transformation(G.transform(same), G.transform(same))))

    def on_before(node: ast.AST, _: object) -> Formatter[Any] | None:
        return (lambda _: "transformed") if node.encoding is not None else None

    format = S.to_formatter(S.Union(member, S.Number), on_before=on_before)
    assert format("a") == "transformed"


def test_tuple_empty():
    """Tuple / empty"""
    assert S.to_formatter(S.Tuple())(()) == "[]"


def test_tuple_elements():
    """Tuple / elements"""
    format = S.to_formatter(S.Tuple(S.Option(S.String)))
    assert format((Some("a"),)) == '[some("a")]'
    assert format((None,)) == "[none()]"


def test_array():
    """Array"""
    format = S.to_formatter(S.Array(S.Option(S.String)))
    assert format((Some("a"),)) == '[some("a")]'
    assert format((None,)) == "[none()]"


def test_tuple_with_rest():
    """TupleWithRest"""
    format = S.to_formatter(
        S.TupleWithRest(S.Tuple(S.Option(S.Boolean)), S.Option(S.Number), S.Option(S.String))
    )
    assert format((Some(True), Some(1), Some("a"))) == '[some(true), some(1), some("a")]'
    assert format((None, None, Some("a"))) == '[none(), none(), some("a")]'


def test_tuple_with_rest_multiple_post_rest_elements():
    """TupleWithRest with multiple post-rest elements"""
    format = S.to_formatter(
        S.TupleWithRest(S.Tuple(S.String), S.String, S.Number, S.Boolean, S.String)
    )
    assert format(("head", "tail", 1, True, "last")) == '["head", "tail", 1, true, "last"]'


def _tagged(label: str) -> S.Bottom[str]:
    return S.String.override_to_formatter(lambda: lambda s: f"{label}:{s}")


def test_rest_one_trailing_element():
    """rest elements / one trailing element after the rest element"""
    format = S.to_formatter(S.TupleWithRest(S.Tuple(_tagged("A")), _tagged("B"), _tagged("C")))
    assert format(("x", "z")) == "[A:x, C:z]"
    assert format(("x", "y", "z")) == "[A:x, B:y, C:z]"
    assert format(("x", "y1", "y2", "z")) == "[A:x, B:y1, B:y2, C:z]"


def test_rest_multiple_trailing_elements():
    """rest elements / multiple trailing elements after the rest element"""
    format = S.to_formatter(
        S.TupleWithRest(S.Tuple(_tagged("A")), _tagged("B"), _tagged("C"), _tagged("D"))
    )
    assert format(("x", "z", "w")) == "[A:x, C:z, D:w]"
    assert format(("x", "y", "z", "w")) == "[A:x, B:y, C:z, D:w]"
    assert format(("x", "y1", "y2", "z", "w")) == "[A:x, B:y1, B:y2, C:z, D:w]"


class _Empty(TypedDict):
    pass


class _OptionA(TypedDict):
    a: Option[str]


class _OptionalOptionA(TypedDict):
    a: NotRequired[Option[str]]


def test_struct_empty():
    """Struct / empty"""
    format = S.to_formatter(S.Struct(_Empty))
    assert format({}) == "{}"
    _check_unknown(format)


def test_struct_required_fields():
    """Struct / required fields"""
    format = S.to_formatter(S.Struct(_OptionA, a=S.Option(S.String)))
    assert format({"a": Some("a")}) == '{ "a": some("a") }'
    assert format({"a": None}) == '{ "a": none() }'


def test_struct_optional_key_field():
    """Struct / optionalKey field"""
    format = S.to_formatter(S.Struct(_OptionalOptionA, a=S.Option(S.String)))
    assert format({"a": Some("a")}) == '{ "a": some("a") }'
    assert format({"a": None}) == '{ "a": none() }'
    assert format({}) == "{}"


def test_record_string_option_number():
    """Record / Record(String, Option(Number))"""
    format = S.to_formatter(S.Record(S.String, S.Option(S.Number)))
    assert format({"a": Some(1)}) == '{ "a": some(1) }'
    assert format({"a": None}) == '{ "a": none() }'


def test_record_key_checks_select_keys():
    """Record / Record(String.check, Option(Number)) should use the key checks to select keys"""
    format = S.to_formatter(
        S.Record(S.String.check(S.is_pattern(re.compile("^a"))), S.Option(S.Number))
    )
    assert format({"a": Some(1), "b": Some(2)}) == '{ "a": some(1) }'


def test_class():
    """Class"""

    class A(S.Class, identifier="A"):
        a: Option[str] = S.field(S.Option(S.String))

    format = S.to_formatter(A)
    assert format(A(a=Some("a"))) == 'A({ "a": some("a") })'
    assert format(A(a=None)) == 'A({ "a": none() })'


class _Tree(TypedDict):
    a: float
    as_: tuple["_Tree", ...]


def test_suspend_compiles_a_recursive_schema_once():
    """suspend / compiles a recursive schema once"""
    compiled = 0

    def text() -> Formatter[float]:
        nonlocal compiled
        compiled += 1
        return lambda n: str(int(n))

    format = S.to_formatter(S.Struct(_Tree, a=S.Number.override_to_formatter(text)))
    tree: _Tree = {"a": 1, "as_": ({"a": 2, "as_": ({"a": 3, "as_": ()},)},)}
    assert format(tree) == '{ "a": 1, "as_": [{ "a": 2, "as_": [{ "a": 3, "as_": [] }] }] }'
    assert compiled == 1


def test_suspend_tuple():
    """suspend / Tuple"""
    schema: S.Bottom[Any, Any] = S.Tuple(S.Number, S.NullOr(S.suspend(lambda: schema)))
    format = S.to_formatter(schema)
    assert format((1, None)) == "[1, null]"
    assert format((1, (2, None))) == "[1, [2, null]]"


def test_suspend_array():
    """suspend / Array"""
    schema: S.Bottom[Any, Any] = S.Array(S.Union(S.String, S.suspend(lambda: schema)))
    assert S.to_formatter(schema)(("a",)) == '["a"]'


class _Nested(TypedDict):
    a: str
    as_: tuple["_Nested", ...]


def test_suspend_struct():
    """suspend / Struct"""
    format = S.to_formatter(S.Struct(_Nested))
    value: _Nested = {"a": "a", "as_": ({"a": "b", "as_": ()}, {"a": "c", "as_": ()})}
    assert (
        format(value) == '{ "a": "a", "as_": [{ "a": "b", "as_": [] }, { "a": "c", "as_": [] }] }'
    )


def test_suspend_record():
    """suspend / Record"""
    schema: S.Bottom[Any, Any] = S.Record(S.String, S.suspend(lambda: schema))
    assert S.to_formatter(schema)({"a": {"a": {"a": {}}}}) == '{ "a": { "a": { "a": {} } } }'


class _Twice(TypedDict):
    a: tuple["_Twice", ...]
    b: tuple["_Twice", ...]


def test_suspend_array_and_array():
    """suspend / Array + Array"""
    format = S.to_formatter(S.Struct(_Twice))
    value: _Twice = {"a": ({"a": ({"a": (), "b": ()},), "b": ()},), "b": ({"a": (), "b": ()},)}
    expected = '{ "a": [{ "a": [{ "a": [], "b": [] }], "b": [] }], "b": [{ "a": [], "b": [] }] }'
    assert format(value) == expected


class _Expression(TypedDict):
    type: Literal["expression"]
    value: "float | _Operation"


class _Operation(TypedDict):
    type: Literal["operation"]
    operator: Literal["+", "-"]
    left: _Expression
    right: _Expression


def test_suspend_mutually_suspended_schemas():
    """suspend / mutually suspended schemas"""
    format = S.to_formatter(S.Struct(_Operation))
    value: _Operation = {
        "type": "operation",
        "operator": "+",
        "left": {"type": "expression", "value": 1},
        "right": {"type": "expression", "value": 2},
    }
    assert format(value) == (
        '{ "type": "operation", "operator": "+", "left": { "type": "expression", "value": 1 },'
        ' "right": { "type": "expression", "value": 2 } }'
    )


class _OptionTree(TypedDict):
    a: str
    as_: Option["_OptionTree"]


def test_suspend_option():
    """suspend / Option"""
    tree: S.Bottom[Any, Any] = S.Struct(_OptionTree, as_=S.Option(S.suspend(lambda: tree)))
    format = S.to_formatter(tree)
    value: _OptionTree = {"a": "a", "as_": Some({"a": "b", "as_": None})}
    assert format(value) == '{ "a": "a", "as_": some({ "a": "b", "as_": none() }) }'


def test_suspend_readonly_set():
    """suspend / ReadonlySet"""
    schema: S.Bottom[Any, Any] = S.FrozenSet(S.suspend(lambda: schema))
    format = S.to_formatter(schema)
    assert format(frozenset()) == "FrozenSet(0) {}"
    nested: frozenset[Any] = frozenset([frozenset([frozenset[Any]()])])
    assert format(nested) == "FrozenSet(1) { FrozenSet(1) { FrozenSet(0) {} } }"


def test_suspend_readonly_map():
    """suspend / ReadonlyMap"""
    schema: S.Bottom[Any, Any] = S.Map(S.String, S.suspend(lambda: schema))
    format = S.to_formatter(schema)
    assert format({}) == "Map(0) {}"
    assert format({"a": {"b": {}}}) == 'Map(1) { "a" => Map(1) { "b" => Map(0) {} } }'


def test_url():
    """URL"""
    # Python keeps the URL as written (``urlsplit`` does not add the "/").
    assert S.to_formatter(S.URL)(urlsplit("https://www.example.com/")) == "https://www.example.com/"


def test_option_string():
    """Option(String)"""
    format = S.to_formatter(S.Option(S.String))
    assert format(Some("a")) == 'some("a")'
    assert format(None) == "none()"


def test_result_number_string():
    """Result(Number, String)"""
    format = S.to_formatter(S.Result(S.Number, S.String))
    assert format(Ok(1)) == "success(1)"
    assert format(Err("a")) == 'failure("a")'


def test_readonly_map_string_option_number():
    """ReadonlyMap(String, Option(Number))"""
    format = S.to_formatter(S.Map(S.String, S.Option(S.Number)))
    assert format({"a": Some(1)}) == 'Map(1) { "a" => some(1) }'
    assert format({"a": None}) == 'Map(1) { "a" => none() }'


def test_redacted_string():
    """Redacted / Redacted(String)"""
    assert S.to_formatter(S.Redacted(S.String))(Redacted("a")) == "<redacted>"


def test_redacted_with_label():
    """Redacted / with label"""
    format = S.to_formatter(S.Redacted(S.String, label="password"))
    assert format(Redacted("a", label="password")) == "<redacted:password>"


def test_date_time_utc():
    """DateTimeUtc"""
    format = S.to_formatter(S.DateTimeUtc)
    assert format(datetime(2021, 1, 1, tzinfo=UTC)) == "DateTime.Utc(2021-01-01T00:00:00.000Z)"


def test_time_zone_offset():
    """TimeZoneOffset"""
    assert S.to_formatter(S.TimeZoneOffset)(timezone(timedelta(hours=3))) == "+03:00"


def test_time_zone_named():
    """TimeZoneNamed"""
    assert S.to_formatter(S.TimeZoneNamed)(ZoneInfo("Europe/London")) == "Europe/London"


def test_time_zone():
    """TimeZone"""
    format = S.to_formatter(S.TimeZone)
    assert format(timezone(timedelta(hours=3))) == "+03:00"
    assert format(ZoneInfo("Europe/London")) == "Europe/London"


def test_date_time_zoned():
    """DateTimeZoned"""
    zoned = datetime(2024, 1, 1, tzinfo=UTC).astimezone(ZoneInfo("Europe/London"))
    assert S.to_formatter(S.DateTimeZoned)(zoned) == format_iso_zoned(zoned)


class _Custom:
    def __init__(self, a: str) -> None:
        self.a = a


class _CustomWithStr(_Custom):
    def __str__(self) -> str:
        return f"A({self.a})"


def test_custom_class():
    """custom class"""
    assert S.to_formatter(S.instance_of(_Custom))(_Custom("a")) == '_Custom({"a":"a"})'


def test_custom_class_with_a_to_string_method():
    """custom class with a toString() method"""
    assert S.to_formatter(S.instance_of(_CustomWithStr))(_CustomWithStr("a")) == "A(a)"


def test_override_string():
    """Annotations / overrideToFormatter / String"""
    assert S.to_formatter(S.String.override_to_formatter(lambda: str.upper))("a") == "A"


def test_override_checked_string():
    """Annotations / overrideToFormatter / String & isMinLength(1)"""
    schema = S.String.check(S.is_min_length(1)).override_to_formatter(lambda: str.upper)
    assert S.to_formatter(schema)("a") == "A"


def test_ast_level_overrides():
    """should allow for ast-level overrides"""

    def on_before(node: ast.AST, _: object) -> Formatter[Any] | None:
        if isinstance(node, ast.Boolean):
            return lambda b: "True" if b else "False"
        return None

    assert S.to_formatter(S.Boolean, on_before=on_before)(True) == "True"
    schema = S.Tuple(S.String, S.Boolean)
    assert S.to_formatter(schema, on_before=on_before)(("a", True)) == '["a", True]'
