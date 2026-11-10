"""The built-in transformations of Effect's ``SchemaTransformation``.

Python mappings: bytes are ``bytes`` (Effect's ``Uint8Array``), a URL is a
``Url`` (JavaScript's ``URL``), a UTC date-time an aware ``datetime`` in UTC,
a zone a ``ZoneInfo`` / ``timezone``, an ``Option`` is ``Some | None``.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta, timezone, tzinfo
from typing import Any
from zoneinfo import ZoneInfo

from pyfect import big_decimal, byte_size
from pyfect._url import Url
from pyfect.date_time import (
    format_iso,
    format_iso_zoned,
    make_zoned_from_string,
    zone_from_string,
    zone_named,
    zone_to_string,
)
from pyfect.exit import Exit, Success
from pyfect.exit import fail as fail_exit
from pyfect.option import Option, Some
from pyfect.schema._options import ParseOptions
from pyfect.schema.getter import (
    JsonReplacer,
    JsonReviver,
    big_int,
    camel_to_snake,
    decode_base64,
    decode_base64_string,
    decode_base64_url_string,
    decode_hex_string,
    decode_uri_component,
    encode_base64,
    encode_base64_url,
    encode_hex,
    encode_uri_component,
    join_key_value,
    number,
    parse_json,
    string,
    stringify_json,
)
from pyfect.schema.getter import (
    capitalize as capitalize_getter,
)
from pyfect.schema.getter import (
    passthrough as passthrough_getter,
)
from pyfect.schema.getter import (
    snake_to_camel as snake_to_camel_getter,
)
from pyfect.schema.getter import (
    split_key_value as split_key_value_getter,
)
from pyfect.schema.getter import (
    to_lower_case as to_lower_case_getter,
)
from pyfect.schema.getter import (
    to_upper_case as to_upper_case_getter,
)
from pyfect.schema.getter import (
    transform_optional as transform_optional_getter,
)
from pyfect.schema.getter import (
    trim as trim_getter,
)
from pyfect.schema.getter import (
    uncapitalize as uncapitalize_getter,
)
from pyfect.schema.getter._coerce import to_utc
from pyfect.schema.issue import InvalidValue, Issue, reported
from pyfect.schema.transformation._transformation import (
    Content,
    Transformation,
    transform,
    transform_effect,
)


def _decoded_only(decode: Any) -> Transformation[str, str]:
    return Transformation(decode, passthrough_getter())


def trim() -> Transformation[str, str]:
    """Trims when decoding, keeps the value when encoding."""
    return _decoded_only(trim_getter())


def snake_to_camel() -> Transformation[str, str]:
    """``snake_case`` to ``camelCase``, and back."""
    return Transformation(snake_to_camel_getter(), camel_to_snake())


def to_lower_case() -> Transformation[str, str]:
    return _decoded_only(to_lower_case_getter())


def to_upper_case() -> Transformation[str, str]:
    return _decoded_only(to_upper_case_getter())


def capitalize() -> Transformation[str, str]:
    return _decoded_only(capitalize_getter())


def uncapitalize() -> Transformation[str, str]:
    return _decoded_only(uncapitalize_getter())


def split_key_value(
    *,
    separator: str = ",",
    key_value_separator: str = "=",
    trim: bool = False,
    keep_empty_values: bool = False,
) -> Transformation[dict[str, str], str]:
    """``"a=1,b=2"`` and ``{"a": "1", "b": "2"}``; ``trim`` and ``keep_empty_values`` as
    ``G.split_key_value``. It round-trips when keys and values hold no separator and,
    with ``trim``, no surrounding whitespace."""
    split = split_key_value_getter(
        separator=separator,
        key_value_separator=key_value_separator,
        trim=trim,
        keep_empty_values=keep_empty_values,
    )
    join = join_key_value(separator=separator, key_value_separator=key_value_separator)
    return Transformation(split, join)


number_from_string: Transformation[float, str] = Transformation(number(), string())
"""JavaScript's ``Number(text)`` and ``String(number)``."""

big_int_from_string: Transformation[int, str] = Transformation(big_int(), string())
"""JavaScript's ``BigInt(text)`` and ``String(bigint)``."""


def _invalid[A](expected: str, input: object, options: ParseOptions) -> Exit[A, Issue]:
    return fail_exit(InvalidValue({"expected": expected}, reported(input, options)))


def _parsed[A](
    parse: Callable[[str], A | None], expected: str
) -> Callable[[str, ParseOptions], Exit[A, Issue]]:
    def run(text: str, options: ParseOptions) -> Exit[A, Issue]:
        out = parse(text)
        return _invalid(expected, text, options) if out is None else Success(out)

    return run


def _done[A](f: Callable[[Any], A]) -> Callable[[Any, ParseOptions], Exit[A, Issue]]:
    return lambda value, _: Success(f(value))


url_from_string: Transformation[Url, str] = transform_effect(
    decode=_parsed(Url.parse, "a valid URL string"), encode=_done(Url.to_json)
)
"""A URL and its text (Effect's ``urlFromString``)."""


def _format_big_decimal(value: big_decimal.BigDecimal) -> str:
    return value.format()


big_decimal_from_string: Transformation[big_decimal.BigDecimal, str] = transform_effect(
    decode=_parsed(big_decimal.from_string, "a valid BigDecimal string"),
    encode=_done(_format_big_decimal),
)
"""A ``BigDecimal`` and its text (Effect's ``bigDecimalFromString``)."""


def _utc_from_string(text: str) -> datetime | None:
    return to_utc(text)


date_time_utc_from_string: Transformation[datetime, str] = transform_effect(
    decode=_parsed(_utc_from_string, "a valid UTC DateTime string"), encode=_done(format_iso)
)
"""A UTC ``datetime`` and its ISO 8601 text, in milliseconds as
``DateTime.formatIso`` (Effect's ``dateTimeUtcFromString``)."""

date_time_zoned_from_string: Transformation[datetime, str] = transform_effect(
    decode=_parsed(make_zoned_from_string, "a valid Zoned DateTime string"),
    encode=_done(format_iso_zoned),
)
"""A zoned ``datetime`` and its RFC 9557 text (Effect's
``dateTimeZonedFromString``)."""


def _zone_id(zone: ZoneInfo) -> str:
    return zone.key


time_zone_named_from_string: Transformation[ZoneInfo, str] = transform_effect(
    decode=_parsed(zone_named, "a valid IANA time zone"), encode=_done(_zone_id)
)
"""A named zone and its IANA identifier (Effect's ``timeZoneNamedFromString``)."""


time_zone_from_string: Transformation[tzinfo, str] = transform_effect(
    decode=_parsed(zone_from_string, "a valid time zone"), encode=_done(zone_to_string)
)
"""A zone and its text: an IANA identifier or an offset like ``+03:00``
(Effect's ``timeZoneFromString``)."""


_DAY_MS = 86_400_000


def _offset_of(millis: int) -> timezone | None:
    # Python's offsets are strictly inside a day (Effect's are not bounded).
    return timezone(timedelta(milliseconds=millis)) if abs(millis) < _DAY_MS else None


def _offset_millis(zone: timezone) -> int:
    return (zone.utcoffset(None) // timedelta(microseconds=1)) // 1000


def _decode_offset(millis: int, options: ParseOptions) -> Exit[timezone, Issue]:
    out = _offset_of(millis)
    expected = "an offset strictly between -24 and +24 hours"
    return _invalid(expected, millis, options) if out is None else Success(out)


time_zone_offset_from_number: Transformation[timezone, int] = transform_effect(
    decode=_decode_offset, encode=_done(_offset_millis)
)
"""A fixed-offset zone and its offset in milliseconds (Effect's
``timeZoneOffsetFromNumber``); the offset is strictly inside a day."""


def _byte_size_text(size: int) -> str:
    return f"{size} {'byte' if size == 1 else 'bytes'}"


byte_size_from_string: Transformation[byte_size.ByteSize, str] = transform_effect(
    decode=_parsed(byte_size.from_string, "a valid ByteSize string"),
    encode=_done(_byte_size_text),
)
"""A ``ByteSize`` and its text, ``"1 byte"`` / ``"<n> bytes"``."""

byte_size_from_big_int: Transformation[byte_size.ByteSize, int] = transform_effect(
    decode=lambda n, options: _sized(n, "a non-negative bigint byte count", options),
    encode=_done(int),
)
"""A ``ByteSize`` and its count, an ``int``."""

_MAX_SAFE_INTEGER = 2**53 - 1


def _sized(value: float, expected: str, options: ParseOptions) -> Exit[byte_size.ByteSize, Issue]:
    out = byte_size.from_input(value)
    return _invalid(expected, value, options) if out is None else Success(out)


def _safe_count(size: byte_size.ByteSize, options: ParseOptions) -> Exit[float, Issue]:
    if size > _MAX_SAFE_INTEGER:
        return _invalid("a ByteSize representable as a safe integer", size, options)
    return Success(size)


def _sized_number(value: float, options: ParseOptions) -> Exit[byte_size.ByteSize, Issue]:
    # A Python ``int`` is also a JavaScript number here: only a safe one counts.
    if isinstance(value, int) and value > _MAX_SAFE_INTEGER:
        return _invalid("a non-negative safe-integer byte count", value, options)
    return _sized(value, "a non-negative safe-integer byte count", options)


byte_size_from_number: Transformation[byte_size.ByteSize, float] = transform_effect(
    decode=_sized_number, encode=_safe_count
)
"""A ``ByteSize`` and its count as a number (a safe integer)."""

bytes_from_base64_string: Transformation[bytes, str] = Transformation(
    decode_base64(), encode_base64()
)
"""Bytes and their Base64 text (Effect's ``uint8ArrayFromBase64String``)."""

string_from_base64_string: Transformation[str, str] = Transformation(
    decode_base64_string(), encode_base64()
)
string_from_base64_url_string: Transformation[str, str] = Transformation(
    decode_base64_url_string(), encode_base64_url()
)
string_from_hex_string: Transformation[str, str] = Transformation(decode_hex_string(), encode_hex())
string_from_uri_component: Transformation[str, str] = Transformation(
    decode_uri_component(), encode_uri_component()
)


def from_json_string(
    *,
    reviver: JsonReviver | None = None,
    replacer: JsonReplacer | None = None,
    space: int | str | None = None,
) -> Transformation[object, str]:
    """A JSON value and its text: parsed with ``reviver``, written through
    ``replacer`` and indented by ``space`` (Effect's ``fromJsonString``).
    With a ``reviver`` or ``replacer`` the text's content no longer has the
    decoded side's schema, so JSON Schema says only its media type."""
    decode = parse_json() if reviver is None else parse_json(reviver=reviver)
    content = Content("application/json", preserve_schema=reviver is None and replacer is None)
    return Transformation(decode, stringify_json(replacer=replacer, space=space), content)


def option_from_null_or[T]() -> Transformation[Option[T], T | None]:
    """``None`` is an empty ``Option``; a value is ``Some``. Python's one
    ``None`` makes the decoded side ``Some(value)`` or ``None``."""
    return transform(decode=_some_unless_none, encode=_value_or_none)


def _some_unless_none[T](value: T | None) -> Option[T]:
    return None if value is None else Some(value)


def _value_or_none[T](option: Option[T]) -> T | None:
    return None if option is None else option.value


def option_from_optional_key[T]() -> Transformation[Option[T], T]:
    """A missing key is ``None``, a present one ``Some(value)``; encoding
    leaves the key out for ``None`` (Effect's ``optionFromOptionalKey``)."""
    return Transformation(transform_optional_getter(Some), transform_optional_getter(_flatten))


def _flatten[T](option: Option[Option[T]]) -> Option[T]:
    return None if option is None else option.value
