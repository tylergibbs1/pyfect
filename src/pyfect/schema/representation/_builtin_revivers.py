"""The revivers of pyfect's built-in checks and declarations (Effect's
``isMinLengthReviver``, ``OptionReviver``, ...). None is installed
implicitly: pass the ones a document needs to ``from_representation``.

Payloads are Effect's (``{"minLength": 1}``), so documents written by
either side name the same checks; ``is_pattern``'s holds a Python ``re``
pattern (``flags`` are ``re`` flags, an ``int``) or an ECMAScript one
(JavaScript's flag letters, as ``is_ecma_pattern`` and Effect write).
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from typing import Any, NotRequired, TypedDict, TypeIs, cast

from pyfect import schema as S
from pyfect.graph import Kind
from pyfect.schema._ecma_pattern import EcmaPatternError, compile_ecma
from pyfect.schema._error_instance import error_schema
from pyfect.schema._schema import Codec, Top
from pyfect.schema.ast import Annotations, Filter
from pyfect.schema.representation._revivers import (
    CheckInput,
    DeclarationInput,
    DeclarationReviver,
    FilterReviver,
    make_reviver_declaration,
    make_reviver_filter,
)

type Payload = Mapping[str, Any]


def _keywords(annotations: Annotations | None) -> dict[str, object]:
    return dict(annotations or {})


def _payload(**fields: Top) -> S.Bottom[Payload, Any, Any, Any]:
    """A struct of ``fields``; a field written ``_optional`` suffix-free
    but given as ``Optional(...)`` is optional (see ``_optional``)."""
    keys: dict[str, Any] = {}
    for key in fields:
        keys[key] = NotRequired[Any] if key in _OPTIONAL else Any
    shape = TypedDict("Payload", keys)  # pyright: ignore[reportArgumentType, reportGeneralTypeIssues]
    return cast("S.Bottom[Payload, Any, Any, Any]", S.Struct(shape, **fields))


_OPTIONAL = frozenset({"exclusiveMinimum", "exclusiveMaximum"})
"""The payload keys that may be missing (``is_between``'s flags)."""


def _filter(id: str, make: Callable[[dict[str, object]], Filter[Any]]) -> FilterReviver[None]:
    return make_reviver_filter(
        f"effect/schema/{id}", S.Null, lambda input: make(_keywords(input.annotations))
    )


def _bound(
    id: str, key: str, value: Top, make: Callable[..., Filter[Any]]
) -> FilterReviver[Payload]:
    def revive(input: CheckInput[Payload]) -> Filter[Any]:
        return make(input.payload[key], **_keywords(input.annotations))

    return make_reviver_filter(f"effect/schema/{id}", _payload(**{key: value}), revive)


def _pair(id: str, value: Top, make: Callable[..., Filter[Any]]) -> FilterReviver[Payload]:
    def revive(input: CheckInput[Payload]) -> Filter[Any]:
        payload = input.payload
        return make(payload["minimum"], payload["maximum"], **_keywords(input.annotations))

    return make_reviver_filter(
        f"effect/schema/{id}", _payload(minimum=value, maximum=value), revive
    )


def _between(id: str, value: Top, make: Callable[..., Filter[Any]]) -> FilterReviver[Payload]:
    def revive(input: CheckInput[Payload]) -> Filter[Any]:
        payload = input.payload
        return make(
            minimum=payload["minimum"],
            maximum=payload["maximum"],
            exclusive_minimum=payload.get("exclusiveMinimum", False),
            exclusive_maximum=payload.get("exclusiveMaximum", False),
            **_keywords(input.annotations),
        )

    flag = S.Literal(True)
    payload = _payload(minimum=value, maximum=value, exclusiveMinimum=flag, exclusiveMaximum=flag)
    return make_reviver_filter(f"effect/schema/{id}", payload, revive)


# ------------------------------------------------------------------ strings

is_trimmed_reviver = _filter("isTrimmed", lambda a: S.is_trimmed(**a))


def _compiles(payload: Payload) -> bool:
    try:
        if isinstance(payload["flags"], str):
            compile_ecma(payload["source"], payload["flags"])
        else:
            re.compile(payload["source"], payload["flags"])
    except (re.error, EcmaPatternError, ValueError, TypeError):
        return False
    return True


def _revive_pattern(input: CheckInput[Payload]) -> Filter[Any]:
    source, flags = input.payload["source"], input.payload["flags"]
    if isinstance(flags, str):
        return S.is_ecma_pattern(source, flags, **_keywords(input.annotations))
    return S.is_pattern(re.compile(source, flags), **_keywords(input.annotations))


is_pattern_reviver = make_reviver_filter(
    "effect/schema/isPattern",
    _payload(source=S.String, flags=S.Union([S.Int, S.String])).check(S.make_filter(_compiles)),
    _revive_pattern,
)
is_string_finite_reviver = _filter("isStringFinite", lambda a: S.is_string_finite(**a))
is_string_big_int_reviver = _filter("isStringBigInt", lambda a: S.is_string_big_int(**a))


def _revive_uuid(input: CheckInput[Payload]) -> Filter[Any]:
    return S.is_uuid(input.payload["version"], **_keywords(input.annotations))


is_uuid_reviver = make_reviver_filter(
    "effect/schema/isUUID",
    _payload(version=S.NullOr(S.Literals(1, 2, 3, 4, 5, 6, 7, 8))),
    _revive_uuid,
)
is_guid_reviver = _filter("isGUID", lambda a: S.is_guid(**a))
is_ulid_reviver = _filter("isULID", lambda a: S.is_ulid(**a))
is_ascii_reviver = _filter("isAscii", lambda a: S.is_ascii(**a))
is_base64_reviver = _filter("isBase64", lambda a: S.is_base64(**a))
is_base64_url_reviver = _filter("isBase64Url", lambda a: S.is_base64_url(**a))
is_starting_with_reviver = _bound("isStartingWith", "startsWith", S.String, S.is_starting_with)
is_ending_with_reviver = _bound("isEndingWith", "endsWith", S.String, S.is_ending_with)
is_including_reviver = _bound("isIncluding", "includes", S.String, S.is_including)
is_uppercased_reviver = _filter("isUppercased", lambda a: S.is_uppercased(**a))
is_lowercased_reviver = _filter("isLowercased", lambda a: S.is_lowercased(**a))
is_capitalized_reviver = _filter("isCapitalized", lambda a: S.is_capitalized(**a))
is_uncapitalized_reviver = _filter("isUncapitalized", lambda a: S.is_uncapitalized(**a))

# ------------------------------------------------------------------ numbers

is_finite_reviver = _filter("isFinite", lambda a: S.is_finite(**a))
is_greater_than_reviver = _bound("isGreaterThan", "exclusiveMinimum", S.Finite, S.is_greater_than)
is_greater_than_or_equal_to_reviver = _bound(
    "isGreaterThanOrEqualTo", "minimum", S.Finite, S.is_greater_than_or_equal_to
)
is_less_than_reviver = _bound("isLessThan", "exclusiveMaximum", S.Finite, S.is_less_than)
is_less_than_or_equal_to_reviver = _bound(
    "isLessThanOrEqualTo", "maximum", S.Finite, S.is_less_than_or_equal_to
)
is_between_reviver = _between("isBetween", S.Finite, S.is_between)
is_multiple_of_reviver = _bound("isMultipleOf", "divisor", S.Finite, S.is_multiple_of)
is_int_reviver = _filter("isInt", lambda a: S.is_int(**a))

# ---------------------------------------------------------- lengths, sizes

is_min_length_reviver = _bound("isMinLength", "minLength", S.Natural, S.is_min_length)
is_max_length_reviver = _bound("isMaxLength", "maxLength", S.Natural, S.is_max_length)
is_between_length_reviver = _pair("isBetweenLength", S.Natural, S.is_between_length)
is_min_code_points_reviver = _bound(
    "isMinCodePoints", "minCodePoints", S.Natural, S.is_min_code_points
)
is_max_code_points_reviver = _bound(
    "isMaxCodePoints", "maxCodePoints", S.Natural, S.is_max_code_points
)
is_between_code_points_reviver = _pair("isBetweenCodePoints", S.Natural, S.is_between_code_points)
is_min_size_reviver = _bound("isMinSize", "minSize", S.Natural, S.is_min_size)
is_max_size_reviver = _bound("isMaxSize", "maxSize", S.Natural, S.is_max_size)
is_between_size_reviver = _pair("isBetweenSize", S.Natural, S.is_between_size)
is_min_properties_reviver = _bound(
    "isMinProperties", "minProperties", S.Natural, S.is_min_properties
)
is_max_properties_reviver = _bound(
    "isMaxProperties", "maxProperties", S.Natural, S.is_max_properties
)
is_between_properties_reviver = _pair("isBetweenProperties", S.Natural, S.is_between_properties)


def _revive_property_names(input: CheckInput[None]) -> Filter[Any]:
    return S.is_property_names(input.schemas[0], **_keywords(input.annotations))


is_property_names_reviver = make_reviver_filter(
    "effect/schema/isPropertyNames", S.Null, _revive_property_names
)
is_unique_reviver = _filter("isUnique", lambda a: S.is_unique(**a))
is_unique_key_reviver = _filter("isUniqueKey", lambda a: S.is_unique_key(**a))

# ------------------------------------------------------- dates and bigints

is_greater_than_date_reviver = _bound(
    "isGreaterThanDate", "exclusiveMinimum", S.DateTimeUtc, S.is_greater_than_date
)
is_greater_than_or_equal_to_date_reviver = _bound(
    "isGreaterThanOrEqualToDate", "minimum", S.DateTimeUtc, S.is_greater_than_or_equal_to_date
)
is_less_than_date_reviver = _bound(
    "isLessThanDate", "exclusiveMaximum", S.DateTimeUtc, S.is_less_than_date
)
is_less_than_or_equal_to_date_reviver = _bound(
    "isLessThanOrEqualToDate", "maximum", S.DateTimeUtc, S.is_less_than_or_equal_to_date
)
is_between_date_reviver = _between("isBetweenDate", S.DateTimeUtc, S.is_between_date)
is_greater_than_big_int_reviver = _bound(
    "isGreaterThanBigInt", "exclusiveMinimum", S.BigInt, S.is_greater_than_big_int
)
is_greater_than_or_equal_to_big_int_reviver = _bound(
    "isGreaterThanOrEqualToBigInt", "minimum", S.BigInt, S.is_greater_than_or_equal_to_big_int
)
is_less_than_big_int_reviver = _bound(
    "isLessThanBigInt", "exclusiveMaximum", S.BigInt, S.is_less_than_big_int
)
is_less_than_or_equal_to_big_int_reviver = _bound(
    "isLessThanOrEqualToBigInt", "maximum", S.BigInt, S.is_less_than_or_equal_to_big_int
)
is_between_big_int_reviver = _between("isBetweenBigInt", S.BigInt, S.is_between_big_int)

# ------------------------------------------------------------ declarations


def _annotated(schema: Top, annotations: Annotations | None) -> Top:
    return schema if annotations is None else schema.__codec__().annotate(**annotations)


def _declaration(id: str, make: Callable[[tuple[Any, ...]], Top]) -> DeclarationReviver[None]:
    def revive(input: DeclarationInput[None]) -> Top:
        return _annotated(make(input.type_parameters), input.annotations)

    return make_reviver_declaration(f"effect/schema/{id}", S.Null, revive)


def _fixed(id: str, schema: Top) -> DeclarationReviver[None]:
    return _declaration(id, lambda _: schema)


option_reviver = _declaration("Option", lambda ps: S.Option(ps[0]))
result_reviver = _declaration("Result", lambda ps: S.Result(ps[0], ps[1]))
cause_reason_reviver = _declaration("CauseReason", lambda ps: S.CauseReason(ps[0], ps[1]))
cause_reviver = _declaration("Cause", lambda ps: S.Cause(ps[0], ps[1]))
exit_reviver = _declaration("Exit", lambda ps: S.Exit(ps[0], ps[1], ps[2]))
map_reviver = _declaration("ReadonlyMap", lambda ps: S.Map(ps[0], ps[1]))
"""Effect's ``ReadonlyMapReviver``: revives ``S.Map``."""
frozen_set_reviver = _declaration("ReadonlySet", lambda ps: S.FrozenSet(ps[0]))
"""Effect's ``ReadonlySetReviver``: revives ``S.FrozenSet``."""


def _revive_graph(input: DeclarationInput[Kind]) -> Top:
    node, edge = input.type_parameters
    return _annotated(S.Graph(input.payload, node, edge), input.annotations)


graph_reviver = make_reviver_declaration(
    "effect/schema/Graph", S.Literals("directed", "undirected"), _revive_graph
)
"""Effect's ``GraphReviver``: revives ``S.Graph``, its kind the payload."""


def _options(**valid: Callable[[object], bool]) -> Codec[Payload | None, Any, Any, Any]:
    """``null`` or a non-empty object of the ``valid`` keys, each value
    accepted by its predicate (Effect's ``RedactedOptionsPayload`` /
    ``ErrorOptionsPayload``)."""

    def guard(input: object) -> TypeIs[Payload]:
        if not isinstance(input, dict) or not input:
            return False
        options = cast("dict[object, object]", input)
        return all(
            isinstance(key, str) and key in valid and valid[key](value)
            for key, value in options.items()
        )

    return S.NullOr(S.declare(guard))


def _is_true(value: object) -> bool:
    return value is True


def _revive_redacted(input: DeclarationInput[Payload | None]) -> Top:
    options = input.payload or {}
    schema = S.Redacted(
        input.type_parameters[0],
        label=options.get("label"),
        disallow_json_encode=options.get("disallowJsonEncode", False),
    )
    return _annotated(schema, input.annotations)


redacted_reviver = make_reviver_declaration(
    "effect/schema/Redacted",
    _options(label=lambda value: isinstance(value, str), disallowJsonEncode=_is_true),
    _revive_redacted,
)


def _revive_error(input: DeclarationInput[Payload | None]) -> Top:
    options = input.payload or {}
    schema = error_schema(options.get("includeStack", False), options.get("excludeCause", False))
    return _annotated(schema, input.annotations)


error_instance_reviver = make_reviver_declaration(
    "effect/schema/Error", _options(includeStack=_is_true, excludeCause=_is_true), _revive_error
)
reg_exp_reviver = _fixed("RegExp", S.RegExp)
url_reviver = _fixed("URL", S.URL)
duration_reviver = _fixed("Duration", S.Duration)
byte_size_reviver = _fixed("ByteSize", S.ByteSize)
big_decimal_reviver = _fixed("BigDecimal", S.BigDecimal)
sem_ver_reviver = _fixed("SemVer", S.SemVer)
sem_ver_range_reviver = _fixed("SemVerRange", S.SemVerRange)
bytes_reviver = _fixed("Uint8Array", S.Bytes)
"""Effect's ``Uint8ArrayReviver``: revives ``S.Bytes``."""
date_time_utc_reviver = _fixed("DateTimeUtc", S.DateTimeUtc)
time_zone_offset_reviver = _fixed("TimeZoneOffset", S.TimeZoneOffset)
time_zone_named_reviver = _fixed("TimeZoneNamed", S.TimeZoneNamed)
time_zone_reviver = _fixed("TimeZone", S.TimeZone)
date_time_zoned_reviver = _fixed("DateTimeZoned", S.DateTimeZoned)
json_reviver = _fixed("Json", S.Json)
mutable_json_reviver = _fixed("MutableJson", S.Json)
"""Effect's ``MutableJsonReviver``: Python's JSON values are mutable
already, so it revives ``S.Json``."""
