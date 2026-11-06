from __future__ import annotations

import datetime
import enum
import pyfect as fx
import re
import zoneinfo
from typing import Any, Literal, Never, NotRequired, TypedDict, cast
from pyfect import big_decimal
from pyfect import byte_size
from pyfect import cause
from pyfect import graph
from pyfect import semver
from pyfect import semver_range
from pyfect.http import url

from pyfect import schema as S

type PersonType = _Struct
type TreeType = _Struct1
type PongType = _Struct2
type PingType = _Struct3
type Schema0Type = str
type Schema1Type = float
type Schema2Type = float
type Schema3Type = bool
type Schema4Type = None
type Schema5Type = int
type Schema6Type = Never
type Schema7Type = object
type Schema8Type = Any
type Schema9Type = S.JsonValue
type Schema10Type = Literal["a"]
type Schema11Type = float
type Schema12Type = Literal[True]
type Schema13Type = Literal["a"] | Literal[1]
type Schema14Type = _Enum
type Schema15Type = str
type Schema16Type = tuple[str, ...]
type Schema17Type = tuple[str, float]
type Schema18Type = tuple[()]
type Schema19Type = tuple[str, *tuple[float, ...]]
type Schema20Type = tuple[str, *tuple[float, ...]]
type Schema21Type = tuple[str, *tuple[float, ...], bool]
type Schema22Type = dict[str, float]
type Schema23Type = dict[str, float]
type Schema24Type = _Struct4
type Schema25Type = _Struct5
type Schema26Type = str | float
type Schema27Type = str | Literal["a"]
type Schema28Type = fx.Option[str]
type Schema29Type = dict[str, float]
type Schema30Type = frozenset[str]
type Schema31Type = fx.Redacted[str]
type Schema32Type = bytes
type Schema33Type = datetime.datetime
type Schema34Type = str
type Schema35Type = str
type Schema36Type = str
type Schema37Type = str
type Schema38Type = str
type Schema39Type = str
type Schema40Type = str
type Schema41Type = float
type Schema42Type = str
type Schema43Type = int
type Schema44Type = float
type Schema45Type = float
type Schema46Type = str
type Schema47Type = dict[str, float]
type Schema48Type = dict[str, float]
type Schema49Type = tuple[float, ...]
type Schema50Type = str
type Schema51Type = str
type Schema52Type = str
type Schema53Type = str
type Schema54Type = str
type Schema55Type = str
type Schema56Type = str
type Schema57Type = str
type Schema58Type = str
type Schema59Type = str
type Schema60Type = str
type Schema61Type = str
type Schema62Type = str
type Schema63Type = str
type Schema64Type = str
type Schema65Type = str
type Schema66Type = str
type Schema67Type = tuple[float, ...]
type Schema68Type = tuple[float, ...]
type Schema69Type = tuple[float, ...]
type Schema70Type = dict[str, float]
type Schema71Type = dict[str, float]
type Schema72Type = tuple[tuple[str, float], ...]
type Schema73Type = float
type Schema74Type = float
type Schema75Type = float
type Schema76Type = float
type Schema77Type = float
type Schema78Type = datetime.datetime
type Schema79Type = datetime.datetime
type Schema80Type = datetime.datetime
type Schema81Type = datetime.datetime
type Schema82Type = datetime.datetime
type Schema83Type = int
type Schema84Type = int
type Schema85Type = int
type Schema86Type = int
type Schema87Type = fx.Result[str, float]
type Schema88Type = cause.Reason[str]
type Schema89Type = cause.Cause[str]
type Schema90Type = fx.Exit[str, float]
type Schema91Type = graph.Graph[str, float, Literal["directed"]]
type Schema92Type = S.ErrorInstance
type Schema93Type = S.ErrorInstance
type Schema94Type = re.Pattern[str]
type Schema95Type = url.Url
type Schema96Type = datetime.timedelta
type Schema97Type = byte_size.ByteSize
type Schema98Type = big_decimal.BigDecimal
type Schema99Type = semver.SemVer
type Schema100Type = semver_range.SemVerRange
type Schema101Type = datetime.timezone
type Schema102Type = zoneinfo.ZoneInfo
type Schema103Type = datetime.tzinfo
type Schema104Type = datetime.datetime
type Schema105Type = PersonType
type Schema106Type = TreeType
type Schema107Type = PingType
type Schema108Type = str
_Struct = TypedDict("_Struct", {"x": float, "y": NotRequired[float]})
_Struct1 = TypedDict("_Struct1", {"value": str, "children": tuple[TreeType, ...]})
_Struct2 = TypedDict("_Struct2", {"ping": NotRequired[PingType]})
_Struct3 = TypedDict("_Struct3", {"pong": NotRequired[PongType]})
_Enum = enum.Enum("_Enum", {"RED": "red", "BLUE": 2})
_Struct4 = TypedDict("_Struct4", {"x": float, "y": NotRequired[float]})
_Struct5 = TypedDict("_Struct5", {"x": float, "y": NotRequired[float]})
Person = S.Struct(_Struct, x=S.Number, y=S.Number).annotate(identifier="Person", title="A person")
Tree: S.Bottom[TreeType, Any, Any, Any] = S.Struct(_Struct1, value=S.String, children=S.Array(S.suspend(lambda: Tree))).annotate(identifier="Tree")
Pong: S.Bottom[PongType, Any, Any, Any] = S.Struct(_Struct2, ping=S.suspend(lambda: Ping)).annotate(identifier="Pong")
Ping: S.Bottom[PingType, Any, Any, Any] = S.Struct(_Struct3, pong=S.suspend(lambda: Pong)).annotate(identifier="Ping")
Schema0 = S.String
Schema1 = S.Number
Schema2 = S.Finite
Schema3 = S.Boolean
Schema4 = S.Null
Schema5 = S.BigInt
Schema6 = S.Never
Schema7 = S.Unknown
Schema8 = S.Any
Schema9 = S.Json.annotate(expected="JSON value")
Schema10 = S.Literal("a")
Schema11 = S.Literal(1.5)
Schema12 = S.Literal(True)
Schema13 = S.Literals(["a", 1])
Schema14 = S.Enum(_Enum)
Schema15 = S.TemplateLiteral(S.Literal("a"), S.String)
Schema16 = S.Array(S.String)
Schema17 = S.Tuple(S.String, S.Number)
Schema18 = S.Tuple()
Schema19 = S.Tuple(S.String, S.optional_key(S.Number))
Schema20 = S.TupleWithRest(S.Tuple(S.String), S.Number)
Schema21 = S.TupleWithRest(S.Tuple(S.String), S.Number, S.Boolean)
Schema22 = S.Record(S.String, S.Number)
Schema23 = S.Record(S.String.check(S.is_ecma_pattern("^a").annotate(expected="a string matching the RegExp ^a")), S.Number)
Schema24 = S.Struct(_Struct4, x=S.Number, y=S.Number)
Schema25 = S.StructWithRest(S.Struct(_Struct5, x=S.Number, y=S.Number), S.Record(S.String, S.Number))
Schema26 = S.Union([S.String, S.Number])
Schema27 = S.Union([S.String, S.Literal("a")], mode="one_of")
Schema28 = S.Option(S.String).annotate(expected="Option")
Schema29 = S.Map(S.String, S.Number).annotate(expected="Mapping")
Schema30 = S.FrozenSet(S.String).annotate(expected="frozenset")
Schema31 = S.Redacted(S.String, label="secret").annotate(expected="Redacted")
Schema32 = S.Bytes.annotate(expected="bytes")
Schema33 = S.DateTimeUtc.annotate(expected="DateTime.Utc")
Schema34 = S.String.annotate(title="t", description="d", examples=["a"])
Schema35 = S.String.annotate(**{"x-sensitive": True})
Schema36 = S.String.check(S.is_min_length(2).annotate(expected="a value with a length of at least 2"))
Schema37 = S.String.check(S.is_max_code_points(1).annotate(expected="a string with at most 1 code points"))
Schema38 = S.String.check(S.is_ecma_pattern("^a$").annotate(expected="a string matching the RegExp ^a$"))
Schema39 = S.String.check(S.is_pattern(re.compile("^a", 32)).annotate(expected="a string matching the RegExp ^a"))
Schema40 = S.String.check(S.is_uuid(4).annotate(expected="a UUID v4"))
Schema41 = S.Number.check(S.is_between(minimum=0, maximum=2, exclusive_maximum=True).annotate(expected="a value between 0 and 2 (excluded)"))
Schema42 = S.String.check(S.is_between_length(1, 2).annotate(expected="a value with a length between 1 and 2"))
Schema43 = S.BigInt.check(S.is_greater_than_big_int(3).annotate(expected="a value greater than 3n"))
Schema44 = S.Number.check(S.is_multiple_of(2).annotate(expected="a value that is a multiple of 2"))
Schema45 = S.Number.check(S.make_filter_group(S.is_greater_than(0).annotate(expected="a value greater than 0"), S.is_less_than(2).annotate(expected="a value less than 2")))
Schema46 = S.String.check(S.is_min_length(1).annotate(expected="a value with a length of at least 1").abort()).check(S.is_max_length(2).annotate(expected="a value with a length of at most 2"))
Schema47 = S.Record(S.String, S.Number).check(S.is_property_names(S.String.check(S.is_min_length(2).annotate(expected="a value with a length of at least 2"))).annotate(expected="an object with property names matching the schema"))
Schema48 = S.Record(S.String, S.Number).check(S.is_min_properties(1).annotate(expected="a value with at least 1 entry"))
Schema49 = S.Array(S.Number).check(S.is_unique().annotate(expected="an array with unique items"))
Schema50 = S.String.check(S.is_trimmed().annotate(expected="a string with no leading or trailing whitespace"))
Schema51 = S.String.check(S.is_string_finite().annotate(expected="a string representing a finite number"))
Schema52 = S.String.check(S.is_string_big_int().annotate(expected="a string representing a bigint"))
Schema53 = S.String.check(S.is_guid().annotate(expected="a GUID"))
Schema54 = S.String.check(S.is_ulid().annotate(expected="a string matching the RegExp ^[0-7][0-9A-HJKMNP-TV-Za-hjkmnp-tv-z]{25}$"))
Schema55 = S.String.check(S.is_base64().annotate(expected="a base64 encoded string"))
Schema56 = S.String.check(S.is_base64_url().annotate(expected="a base64url encoded string"))
Schema57 = S.String.check(S.is_uppercased().annotate(expected="a string with all characters in uppercase"))
Schema58 = S.String.check(S.is_lowercased().annotate(expected="a string with all characters in lowercase"))
Schema59 = S.String.check(S.is_capitalized().annotate(expected="a string with the first character in uppercase"))
Schema60 = S.String.check(S.is_uncapitalized().annotate(expected="a string with the first character in lowercase"))
Schema61 = S.String.check(S.is_starting_with("a").annotate(expected="a string starting with \"a\""))
Schema62 = S.String.check(S.is_ending_with("a").annotate(expected="a string ending with \"a\""))
Schema63 = S.String.check(S.is_including("a").annotate(expected="a string including \"a\""))
Schema64 = S.String.check(S.is_max_length(1).annotate(expected="a value with a length of at most 1"))
Schema65 = S.String.check(S.is_min_code_points(1).annotate(expected="a string with at least 1 code points"))
Schema66 = S.String.check(S.is_between_code_points(1, 2).annotate(expected="a string with between 1 and 2 code points"))
Schema67 = S.Array(S.Number).check(S.is_min_size(1).annotate(expected="a value with a size of at least 1"))
Schema68 = S.Array(S.Number).check(S.is_max_size(1).annotate(expected="a value with a size of at most 1"))
Schema69 = S.Array(S.Number).check(S.is_between_size(1, 2).annotate(expected="a value with a size between 1 and 2"))
Schema70 = S.Record(S.String, S.Number).check(S.is_max_properties(0).annotate(expected="a value with at most 0 entries"))
Schema71 = S.Record(S.String, S.Number).check(S.is_between_properties(1, 2).annotate(expected="a value with between 1 and 2 entries"))
Schema72 = S.Array(S.Tuple(S.String, S.Number)).check(S.is_unique_key().annotate(expected="an array with unique keys"))
Schema73 = S.Number.check(S.is_int().annotate(expected="an integer"))
Schema74 = S.Number.check(S.is_greater_than(1).annotate(expected="a value greater than 1"))
Schema75 = S.Number.check(S.is_greater_than_or_equal_to(1).annotate(expected="a value greater than or equal to 1"))
Schema76 = S.Number.check(S.is_less_than(1).annotate(expected="a value less than 1"))
Schema77 = S.Number.check(S.is_less_than_or_equal_to(1).annotate(expected="a value less than or equal to 1"))
Schema78 = S.DateTimeUtc.annotate(expected="DateTime.Utc").check(S.is_greater_than_date(S.decode_unknown_sync(S.to_codec_json(S.DateTimeUtc))("2026-01-01T00:00:00.000Z")).annotate(expected="a value greater than 2026-01-01T00:00:00.000Z"))
Schema79 = S.DateTimeUtc.annotate(expected="DateTime.Utc").check(S.is_greater_than_or_equal_to_date(S.decode_unknown_sync(S.to_codec_json(S.DateTimeUtc))("2026-01-01T00:00:00.000Z")).annotate(expected="a value greater than or equal to 2026-01-01T00:00:00.000Z"))
Schema80 = S.DateTimeUtc.annotate(expected="DateTime.Utc").check(S.is_less_than_date(S.decode_unknown_sync(S.to_codec_json(S.DateTimeUtc))("2026-01-01T00:00:00.000Z")).annotate(expected="a value less than 2026-01-01T00:00:00.000Z"))
Schema81 = S.DateTimeUtc.annotate(expected="DateTime.Utc").check(S.is_less_than_or_equal_to_date(S.decode_unknown_sync(S.to_codec_json(S.DateTimeUtc))("2026-01-01T00:00:00.000Z")).annotate(expected="a value less than or equal to 2026-01-01T00:00:00.000Z"))
Schema82 = S.DateTimeUtc.annotate(expected="DateTime.Utc").check(S.is_between_date(minimum=S.decode_unknown_sync(S.to_codec_json(S.DateTimeUtc))("2026-01-01T00:00:00.000Z"), maximum=S.decode_unknown_sync(S.to_codec_json(S.DateTimeUtc))("2026-01-01T00:00:00.000Z")).annotate(expected="a value between 2026-01-01T00:00:00.000Z and 2026-01-01T00:00:00.000Z"))
Schema83 = S.BigInt.check(S.is_greater_than_or_equal_to_big_int(3).annotate(expected="a value greater than or equal to 3n"))
Schema84 = S.BigInt.check(S.is_less_than_big_int(3).annotate(expected="a value less than 3n"))
Schema85 = S.BigInt.check(S.is_less_than_or_equal_to_big_int(3).annotate(expected="a value less than or equal to 3n"))
Schema86 = S.BigInt.check(S.is_between_big_int(minimum=1, maximum=3).annotate(expected="a value between 1n and 3n"))
Schema87 = S.Result(S.String, S.Number).annotate(expected="Result")
Schema88 = S.CauseReason(S.String, cast("Any", S.Json.annotate(expected="JSON value"))).annotate(expected="Cause.Reason")
Schema89 = S.Cause(S.String, cast("Any", S.Json.annotate(expected="JSON value"))).annotate(expected="Cause")
Schema90 = S.Exit(S.String, S.Number, cast("Any", S.Json.annotate(expected="JSON value"))).annotate(expected="Exit")
Schema91 = S.Graph("directed", S.String, S.Number).annotate(expected="an immutable directed Graph")
Schema92 = S.ErrorInstance.schema().annotate(expected="Error")
Schema93 = S.ErrorInstance.schema(include_stack=True).annotate(expected="Error")
Schema94 = S.RegExp.annotate(expected="RegExp")
Schema95 = S.URL.annotate(expected="URL")
Schema96 = S.Duration.annotate(expected="Duration")
Schema97 = S.ByteSize.annotate(expected="ByteSize")
Schema98 = S.BigDecimal.annotate(expected="BigDecimal")
Schema99 = S.SemVer.annotate(expected="SemVer")
Schema100 = S.SemVerRange.annotate(expected="SemVerRange")
Schema101 = S.TimeZoneOffset.annotate(expected="DateTime.TimeZone.Offset")
Schema102 = S.TimeZoneNamed.annotate(expected="DateTime.TimeZone.Named")
Schema103 = S.TimeZone.annotate(expected="DateTime.TimeZone")
Schema104 = S.DateTimeZoned.annotate(expected="DateTime.Zoned")
Schema105 = Person
Schema106 = Tree
Schema107 = Ping
Schema108 = S.suspend(lambda: S.String)
