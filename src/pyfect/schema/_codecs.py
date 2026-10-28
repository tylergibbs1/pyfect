"""The built-in codecs of Effect's ``Schema``: strings decoded to numbers,
dates, zones, URLs, bytes and JSON, ``Option`` from ``None`` or a missing
key, ``Redacted`` from a value.

Python mappings (``docs/PARITY.md``): bytes are ``bytes`` (``Uint8Array``),
a URL a ``urllib.parse.SplitResult``, a UTC date-time an aware ``datetime``
in UTC, an ``Option`` ``Some | None``.
"""

from __future__ import annotations

from datetime import datetime, tzinfo
from typing import Any, Literal
from urllib.parse import SplitResult
from zoneinfo import ZoneInfo

from pyfect import redacted as _redacted
from pyfect.byte_size import ByteSize as _ByteSize
from pyfect.date_time._epoch import to_epoch_millis
from pyfect.option import Option as _Option
from pyfect.option import Some as _Some
from pyfect.redacted import Redacted as _Redacted
from pyfect.schema import _arbitrary_links as _arb
from pyfect.schema import ast
from pyfect.schema import transformation as T
from pyfect.schema._arrays import optional_key
from pyfect.schema._checks_string import is_string_big_int
from pyfect.schema._data import Option, Redacted
from pyfect.schema._declare import instance_of
from pyfect.schema._instances import URL_INSTANCES
from pyfect.schema._literals import Literals, LiteralsSchema, Union
from pyfect.schema._primitives import (
    BigInt,
    Boolean,
    Finite,
    Int,
    Null,
    Number,
    String,
    Trimmed,
    Unknown,
)
from pyfect.schema._schema import Bottom, Codec
from pyfect.schema._transform import DecodeToSchema, decode_to, to_type
from pyfect.schema._value_codecs import string_codec
from pyfect.schema._values import (
    ByteSize,
    DateTimeUtc,
    DateTimeZoned,
    TimeZone,
    TimeZoneNamed,
)
from pyfect.schema.getter import (
    date_time_utc_from_input,
    decode_base64_url,
    decode_hex,
    encode_base64_url,
    encode_hex,
    forbidden,
    transform,
    transform_optional,
)

URL: Bottom[SplitResult] = instance_of(
    SplitResult,
    expected="URL",
    to_codec_arbitrary=_arb.url,
    to_codec_json=string_codec(T.url_from_string),
    **URL_INSTANCES,
)
"""A parsed URL, a ``urllib.parse.SplitResult`` (Effect's ``URL``)."""

_BASE64_STRING = ast.annotate(ast.string, {"format": "byte", "content_encoding": "base64"})


def _bytes_codec(_: tuple[ast.AST, ...]) -> ast.Link:
    return ast.Link(_BASE64_STRING, T.bytes_from_base64_string)


Bytes: Bottom[bytes] = instance_of(
    bytes, to_codec_json=_bytes_codec, to_codec_arbitrary=_arb.bytes_
)
"""``bytes`` (Effect's ``Uint8Array``)."""


def _expecting(expected: str) -> Bottom[str]:
    return String.annotate(expected=expected)


NumberFromString: DecodeToSchema[float, str] = _expecting(
    "a string that will be decoded as a number"
).pipe(decode_to(Number, T.number_from_string))
"""A number from its text, as JavaScript's ``Number`` reads it (``NaN``
for what is not a number)."""

FiniteFromString: DecodeToSchema[float, str] = _expecting(
    "a string that will be decoded as a finite number"
).pipe(decode_to(Finite, T.number_from_string))

BigIntFromString: DecodeToSchema[int, str] = String.check(
    is_string_big_int(expected="a string representing a bigint")
).pipe(decode_to(BigInt, T.big_int_from_string))

Trim: DecodeToSchema[str, str] = _expecting(
    "a string that will be decoded as a trimmed string"
).pipe(decode_to(Trimmed, T.trim()))
"""A string, trimmed when decoding."""

StringFromBase64: DecodeToSchema[str, str] = _expecting(
    "a base64 encoded string that will be decoded as a UTF-8 string"
).pipe(decode_to(String, T.string_from_base64_string))
StringFromBase64Url: DecodeToSchema[str, str] = _expecting(
    "a base64 (URL) encoded string that will be decoded as a UTF-8 string"
).pipe(decode_to(String, T.string_from_base64_url_string))
StringFromHex: DecodeToSchema[str, str] = _expecting(
    "a hex encoded string that will be decoded as a UTF-8 string"
).pipe(decode_to(String, T.string_from_hex_string))
StringFromUriComponent: DecodeToSchema[str, str] = _expecting(
    "a URI component encoded string that will be decoded as a UTF-8 string"
).pipe(decode_to(String, T.string_from_uri_component))

BytesFromBase64: DecodeToSchema[bytes, str] = String.annotate(
    expected="a base64 encoded string that will be decoded as Uint8Array",
    format="byte",
    content_encoding="base64",
).pipe(decode_to(Bytes, T.bytes_from_base64_string))
"""Bytes from Base64 text (Effect's ``Uint8ArrayFromBase64``)."""

BytesFromBase64Url: DecodeToSchema[bytes, str] = _expecting(
    "a base64 (URL) encoded string that will be decoded as a Uint8Array"
).pipe(decode_to(Bytes, T.Transformation(decode_base64_url(), encode_base64_url())))
BytesFromHex: DecodeToSchema[bytes, str] = _expecting(
    "a hex encoded string that will be decoded as a Uint8Array"
).pipe(decode_to(Bytes, T.Transformation(decode_hex(), encode_hex())))

URLFromString: DecodeToSchema[SplitResult, str] = _expecting(
    "a string that will be decoded as a URL"
).pipe(decode_to(URL, T.url_from_string))


def _from_bit(bit: Literal[0, 1]) -> bool:
    return bit == 1


def _to_bit(value: bool) -> Literal[0, 1]:
    return 1 if value else 0


_BITS: LiteralsSchema[Literal[0, 1]] = Literals(0, 1)
BooleanFromBit: DecodeToSchema[bool, int] = _BITS.pipe(
    decode_to(Boolean, T.transform(decode=_from_bit, encode=_to_bit))
)
"""``0`` / ``1`` as ``False`` / ``True``."""

DateTimeUtcFromString: DecodeToSchema[datetime, str] = _expecting(
    "a string that will be decoded as a DateTime.Utc"
).pipe(decode_to(DateTimeUtc, T.date_time_utc_from_string))
"""A UTC ``datetime`` from ISO 8601 (or RFC 2822) text; encodes as
``DateTime.formatIso`` (milliseconds, ``Z``)."""


DateTimeUtcFromMillis: DecodeToSchema[datetime, int] = Int.pipe(
    decode_to(DateTimeUtc, T.Transformation(date_time_utc_from_input(), transform(to_epoch_millis)))
)
"""A UTC ``datetime`` from epoch milliseconds."""


DateTimeZonedFromString: DecodeToSchema[datetime, str] = _expecting(
    "a zoned DateTime string (e.g. 2024-01-01T00:00:00.000+00:00[Europe/London])"
).pipe(decode_to(DateTimeZoned, T.date_time_zoned_from_string))

TimeZoneNamedFromString: DecodeToSchema[ZoneInfo, str] = _expecting(
    "an IANA time zone identifier"
).pipe(decode_to(TimeZoneNamed, T.time_zone_named_from_string))

TimeZoneFromString: DecodeToSchema[tzinfo, str] = _expecting(
    "a time zone string (IANA identifier or offset like +03:00)"
).pipe(decode_to(TimeZone, T.time_zone_from_string))

ByteSizeFromString: DecodeToSchema[_ByteSize, str] = _expecting(
    "a string that will be decoded as a ByteSize"
).pipe(decode_to(ByteSize, T.byte_size_from_string))
ByteSizeFromBigInt: DecodeToSchema[_ByteSize, int] = BigInt.pipe(
    decode_to(ByteSize, T.byte_size_from_big_int)
)
ByteSizeFromNumber: DecodeToSchema[_ByteSize, float] = Number.pipe(
    decode_to(ByteSize, T.byte_size_from_number)
)

_JSON_STRING = _expecting("a string that will be decoded as JSON")


def from_json_string[A, I, RD, RE](
    schema: Codec[A, I, RD, RE], /, *, space: int | str | None = None
) -> DecodeToSchema[A, str, RD, RE]:
    """JSON text, parsed then decoded by ``schema`` (Effect's
    ``fromJsonString``); encoding indents by ``space``."""
    transformation: T.Transformation[Any, str] = T.from_json_string(space=space)
    return _JSON_STRING.pipe(decode_to(schema, transformation))


UnknownFromJsonString: DecodeToSchema[object, str] = from_json_string(Unknown)
"""Any JSON value, from its text."""


def NullOr[A, I, RD, RE](schema: Codec[A, I, RD, RE], /) -> Bottom[A | None, I | None, RD, RE]:
    """``schema``'s values or ``None`` (Effect's ``NullOr``)."""
    return Union(schema, Null)


def OptionFromNullOr[A, I, RD, RE](
    schema: Codec[A, I, RD, RE], /
) -> DecodeToSchema[_Option[A], I | None, RD, RE]:
    """``None`` decoded as an empty ``Option``, a value as ``Some(value)``
    (Effect's ``OptionFromNullOr``)."""
    return NullOr(schema).pipe(decode_to(Option(to_type(schema)), T.option_from_null_or()))


def OptionFromOptionalKey[A, I, RD, RE](
    schema: Codec[A, I, RD, RE], /
) -> DecodeToSchema[_Option[A], I, RD, RE]:
    """A missing struct key decoded as ``None``, a present one as
    ``Some(value)``; ``None`` encodes to a missing key (Effect's
    ``OptionFromOptionalKey``)."""
    return optional_key(schema).pipe(
        decode_to(Option(to_type(schema)), T.option_from_optional_key())
    )


def _some_unless_null(input: _Option[object]) -> _Option[_Option[object]]:
    return _Some(None if input is None or input.value is None else input)


def _flatten(option: _Option[_Option[object]]) -> _Option[object]:
    return None if option is None else option.value


def _null_unless_some(option: _Option[_Option[object]]) -> _Option[object]:
    return _Some(None if option is None or option.value is None else option.value.value)


def OptionFromOptionalNullOr[A, I, RD, RE](
    schema: Codec[A, I, RD, RE], /, *, on_none_encoding: Literal["omit"] | None = "omit"
) -> DecodeToSchema[_Option[A], I | None, RD, RE]:
    """A missing struct key or ``None`` decoded as an empty ``Option``, a
    value as ``Some(value)``; an empty ``Option`` encodes to a missing key,
    or to ``None`` with ``on_none_encoding=None`` (Effect's
    ``OptionFromOptionalNullOr``)."""
    encode = _flatten if on_none_encoding == "omit" else _null_unless_some
    transformation: T.Transformation[Any, Any] = T.Transformation(
        transform_optional(_some_unless_null), transform_optional(encode)
    )
    return optional_key(NullOr(schema)).pipe(decode_to(Option(to_type(schema)), transformation))


def _cannot_encode(input: _Option[_Redacted[object]]) -> str:
    label = None if input is None else input.value.label
    return "Cannot encode Redacted" + ("" if label is None else f' with label: "{label}"')


def RedactedFromValue[A, I, RD, RE](
    value: Codec[A, I, RD, RE], /, *, label: str | None = None, disallow_encode: bool = False
) -> DecodeToSchema[_Redacted[A], I, RD, RE]:
    """A value decoded as a ``Redacted`` of it (with ``label``); encoding
    reveals it unless ``disallow_encode`` (Effect's ``RedactedFromValue``)."""
    encode: Any = forbidden(_cannot_encode) if disallow_encode else transform(_redacted.value)

    def wrap(secret: A) -> _Redacted[A]:
        return _redacted.make(secret, label=label)

    target = Redacted(to_type(value), label=label)
    return value.__codec__().pipe(decode_to(target, T.Transformation(transform(wrap), encode)))
