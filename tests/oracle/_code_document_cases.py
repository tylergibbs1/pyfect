"""The schemas ``test_to_code_document`` generates code for; ``sample_document`` is
the document behind ``_generated_code_sample.py``, which pyright checks."""

import enum
from datetime import UTC, datetime
from typing import Any, NotRequired, TypedDict

from pyfect import schema as S
from pyfect.hash_map import HashMap
from pyfect.hash_set import HashSet
from pyfect.schema import representation as R


class Color(enum.Enum):
    RED = "red"
    BLUE = 2


class Point(TypedDict):
    x: float
    y: NotRequired[float]


Person = S.Struct(Point).annotate(identifier="Person", title="A person")


class Tree(TypedDict):
    value: str
    children: tuple["Tree", ...]


def _tree() -> Any:
    return TreeSchema


TreeSchema: Any = S.Struct(Tree, children=S.Array(S.suspend(_tree))).annotate(identifier="Tree")


class Ping(TypedDict):
    pong: NotRequired["Pong"]


class Pong(TypedDict):
    ping: NotRequired[Ping]


def _ping() -> Any:
    return PingSchema


def _pong() -> Any:
    return PongSchema


PingSchema: Any = S.Struct(Ping, pong=S.suspend(_pong)).annotate(identifier="Ping")
PongSchema: Any = S.Struct(Pong, ping=S.suspend(_ping)).annotate(identifier="Pong")


_DATE = datetime(2026, 1, 1, tzinfo=UTC)

CASES: dict[str, tuple[Any, list[object], list[object]]] = {
    "string": (S.String, ["a"], [1]),
    "number": (S.Number, [1, 1.5], ["a"]),
    "finite": (S.Finite, [1.5], [float("inf")]),
    "boolean": (S.Boolean, [True], [1]),
    "null": (S.Null, [None], [0]),
    "big_int": (S.BigInt, [1], ["1"]),
    "never": (S.Never, [], [None, 1]),
    "unknown": (S.Unknown, [1, None], []),
    "any": (S.Any, [1, None], []),
    "json": (S.Json, [{"a": [1]}], [float("inf")]),
    "literal_string": (S.Literal("a"), ["a"], ["b"]),
    "literal_number": (S.Literal(1.5), [1.5], [2]),
    "literal_true": (S.Literal(True), [True], [False]),
    "literals": (S.Literals("a", 1), ["a", 1], ["b"]),
    "enum": (S.Enum(Color), [], ["red"]),
    "template_literal": (S.TemplateLiteral("a", S.String), ["ab"], ["b"]),
    "array": (S.Array(S.String), [("a",), ()], [(1,)]),
    "tuple": (S.Tuple(S.String, S.Number), [("a", 1)], [("a",)]),
    "empty_tuple": (S.Tuple(), [()], [(1,)]),
    "optional_element": (S.Tuple(S.String, S.optional_key(S.Number)), [("a",), ("a", 1)], [()]),
    "tuple_with_rest": (S.TupleWithRest(S.Tuple(S.String), S.Number), [("a", 1, 2)], [(1,)]),
    "tuple_with_post": (
        S.TupleWithRest(S.Tuple(S.String), S.Number, S.Boolean),
        [("a", 1, True)],
        [("a", 1)],
    ),
    "record": (S.Record(S.String, S.Number), [{"a": 1}], [{"a": "b"}]),
    "patterned_record": (
        S.Record(S.String.check(S.is_ecma_pattern("^a")), S.Number),
        [{"a": 1}],
        [{"a": "b"}],
    ),
    "struct": (S.Struct(Point), [{"x": 1}, {"x": 1, "y": 2}], [{"y": 2}]),
    "struct_with_rest": (
        S.StructWithRest(S.Struct(Point), S.Record(S.String, S.Number)),
        [{"x": 1, "z": 2}],
        [{"x": 1, "z": "a"}],
    ),
    "union": (S.Union([S.String, S.Number]), ["a", 1], [True]),
    "one_of": (S.Union([S.String, S.Literal("a")], mode="one_of"), ["b"], ["a"]),
    "option": (S.Option(S.String), [], [1]),
    "map": (S.Map(S.String, S.Number), [], [1]),
    "frozen_set": (S.FrozenSet(S.String), [frozenset({"a"})], [1]),
    "redacted": (S.Redacted(S.String, label="secret"), [], [1]),
    "bytes": (S.Bytes, [b"a"], ["a"]),
    "date_time_utc": (S.DateTimeUtc, [], [1]),
    "annotations": (S.String.annotate(title="t", description="d", examples=["a"]), ["a"], [1]),
    "custom_annotation": (S.String.annotate(**{"x-sensitive": True}), ["a"], [1]),
    "min_length": (S.String.check(S.is_min_length(2)), ["ab"], ["a"]),
    "code_points": (S.String.check(S.is_max_code_points(1)), ["😀"], ["ab"]),
    "ecma_pattern": (S.String.check(S.is_ecma_pattern("^a$")), ["a"], ["a\n"]),
    "python_pattern": (S.String.check(S.is_pattern("^a")), ["ab"], ["b"]),
    "uuid": (S.String.check(S.is_uuid(4)), [], ["a"]),
    "between": (
        S.Number.check(S.is_between(minimum=0, maximum=2, exclusive_maximum=True)),
        [0],
        [2],
    ),
    "between_length": (S.String.check(S.is_between_length(1, 2)), ["a"], [""]),
    "big_int_bound": (S.BigInt.check(S.is_greater_than_big_int(3)), [4], [3]),
    "multiple_of": (S.Number.check(S.is_multiple_of(2)), [4], [3]),
    "filter_group": (
        S.Number.check(S.make_filter_group(S.is_greater_than(0), S.is_less_than(2))),
        [1],
        [2],
    ),
    "aborted_filter": (S.String.check(S.is_min_length(1).abort(), S.is_max_length(2)), ["a"], [""]),
    "property_names": (
        S.Record(S.String, S.Number).check(S.is_property_names(S.String.check(S.is_min_length(2)))),
        [{"ab": 1}],
        [{"a": 1}],
    ),
    "min_properties": (
        S.Record(S.String, S.Number).check(S.is_min_properties(1)),
        [{"a": 1}],
        [{}],
    ),
    "unique": (S.Array(S.Number).check(S.is_unique()), [(1, 2)], [(1, 1)]),
    "trimmed": (S.String.check(S.is_trimmed()), ["a"], [" a"]),
    "string_finite": (S.String.check(S.is_string_finite()), ["1"], ["a"]),
    "string_big_int": (S.String.check(S.is_string_big_int()), ["1"], ["a"]),
    "guid": (S.String.check(S.is_guid()), [], ["a"]),
    "ulid": (S.String.check(S.is_ulid()), [], ["a"]),
    "ascii": (S.String.check(S.is_ascii()), ["a\x7f"], ["\u00e9"]),
    "base64": (S.String.check(S.is_base64()), ["YQ=="], ["!"]),
    "base64_url": (S.String.check(S.is_base64_url()), ["YQ"], ["!"]),
    "uppercased": (S.String.check(S.is_uppercased()), ["A"], ["a"]),
    "lowercased": (S.String.check(S.is_lowercased()), ["a"], ["A"]),
    "capitalized": (S.String.check(S.is_capitalized()), ["Ab"], ["ab"]),
    "uncapitalized": (S.String.check(S.is_uncapitalized()), ["aB"], ["Ab"]),
    "starting_with": (S.String.check(S.is_starting_with("a")), ["ab"], ["b"]),
    "ending_with": (S.String.check(S.is_ending_with("a")), ["ba"], ["b"]),
    "including": (S.String.check(S.is_including("a")), ["bab"], ["b"]),
    "max_length": (S.String.check(S.is_max_length(1)), ["a"], ["ab"]),
    "min_code_points": (S.String.check(S.is_min_code_points(1)), ["a"], [""]),
    "between_code_points": (S.String.check(S.is_between_code_points(1, 2)), ["a"], [""]),
    "min_size": (S.Array(S.Number).check(S.is_min_size(1)), [(1,)], [()]),
    "max_size": (S.Array(S.Number).check(S.is_max_size(1)), [(1,)], [(1, 2)]),
    "between_size": (S.Array(S.Number).check(S.is_between_size(1, 2)), [(1,)], [()]),
    "max_properties": (
        S.Record(S.String, S.Number).check(S.is_max_properties(0)),
        [{}],
        [{"a": 1}],
    ),
    "between_properties": (
        S.Record(S.String, S.Number).check(S.is_between_properties(1, 2)),
        [{"a": 1}],
        [{}],
    ),
    "unique_key": (
        S.Array(S.Tuple(S.String, S.Number)).check(S.is_unique_key()),
        [(("a", 1), ("b", 1))],
        [(("a", 1), ("a", 2))],
    ),
    "int": (S.Number.check(S.is_int()), [1], [1.5]),
    "greater_than": (S.Number.check(S.is_greater_than(1)), [2], [1]),
    "greater_or_equal": (S.Number.check(S.is_greater_than_or_equal_to(1)), [1], [0]),
    "less_than": (S.Number.check(S.is_less_than(1)), [0], [1]),
    "less_or_equal": (S.Number.check(S.is_less_than_or_equal_to(1)), [1], [2]),
    "greater_than_date": (S.DateTimeUtc.check(S.is_greater_than_date(_DATE)), [], [1]),
    "greater_or_equal_date": (
        S.DateTimeUtc.check(S.is_greater_than_or_equal_to_date(_DATE)),
        [],
        [1],
    ),
    "less_than_date": (S.DateTimeUtc.check(S.is_less_than_date(_DATE)), [], [1]),
    "less_or_equal_date": (S.DateTimeUtc.check(S.is_less_than_or_equal_to_date(_DATE)), [], [1]),
    "between_date": (S.DateTimeUtc.check(S.is_between_date(minimum=_DATE, maximum=_DATE)), [], [1]),
    "greater_or_equal_big_int": (
        S.BigInt.check(S.is_greater_than_or_equal_to_big_int(3)),
        [3],
        [2],
    ),
    "less_than_big_int": (S.BigInt.check(S.is_less_than_big_int(3)), [2], [3]),
    "less_or_equal_big_int": (S.BigInt.check(S.is_less_than_or_equal_to_big_int(3)), [3], [4]),
    "between_big_int": (S.BigInt.check(S.is_between_big_int(minimum=1, maximum=3)), [2], [4]),
    "result": (S.Result(S.String, S.Number), [], [1]),
    "cause_reason": (S.CauseReason(S.String, S.Defect()), [], [1]),
    "cause": (S.Cause(S.String, S.Defect()), [], [1]),
    "exit": (S.Exit(S.String, S.Number, S.Defect()), [], [1]),
    "graph": (S.Graph("directed", S.String, S.Number), [], [1]),
    "error": (S.ErrorInstance, [], [1]),
    "error_with_options": (S.ErrorInstance.schema(include_stack=True), [], [1]),
    "regexp": (S.RegExp, [], [1]),
    "url": (S.URL, [], [1]),
    "duration": (S.Duration, [], ["a"]),
    "byte_size": (S.ByteSize, [], ["a"]),
    "big_decimal": (S.BigDecimal, [], ["a"]),
    "sem_ver": (S.SemVer, [], [1]),
    "sem_ver_range": (S.SemVerRange, [], [1]),
    "time_zone_offset": (S.TimeZoneOffset, [], [1]),
    "time_zone_named": (S.TimeZoneNamed, [], [1]),
    "time_zone": (S.TimeZone, [], [1]),
    "date_time_zoned": (S.DateTimeZoned, [], [1]),
    "reference": (Person, [{"x": 1}], [{}]),
    "recursive": (TreeSchema, [{"value": "a", "children": ()}], [{"value": "a"}]),
    "mutually_recursive": (PingSchema, [{"pong": {"ping": {}}}], [{"pong": {"ping": 1}}]),
    "suspend": (S.suspend(lambda: S.String), ["a"], [1]),
    "hash_set": (S.HashSet(S.String), [HashSet.make("a")], [frozenset({"a"}), HashSet.make(1)]),
    "hash_map": (S.HashMap(S.String, S.Number), [HashMap.make(("a", 1.0))], [{"a": 1.0}]),
}


def sample_document_representations() -> R.MultiDocument:
    return R.to_representations(tuple(case[0] for case in CASES.values()))


def sample_document() -> R.CodeDocument:
    return R.to_code_document(sample_document_representations())
