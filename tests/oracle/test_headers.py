"""Ports of Effect's ``http/Headers.test.ts``.

Each test's docstring is the Effect test title. ``Headers`` is a read-only
``Mapping``; ``get`` gives ``None`` for a missing name. Dates are aware UTC
``datetime`` values; Retry-After durations are ``Seconds``.

Omitted, with the reason:

- ``serializer annotation``: it reads through ``Schema.toIso``, which is
  not ported (docs/PARITY.md section 4). The HTTP schemas are
  ``pyfect.http.schema``.
- ``does not expose inspectable prototype methods during for..in
  iteration``, ``works with for..in based headers polyfills``: JavaScript
  prototype enumeration; iterating a ``Headers`` gives its names (checked
  in ``remove``).
- ``preserves caller-owned stateful pattern cursors``, ``checks each header
  independently with a sticky pattern``: Python patterns keep no
  ``lastIndex``; ``redacts each header independently with a global
  pattern`` covers matching several names with one pattern.
- ``parses every RFC 9110 format as UTC, whatever the process time zone``
  is ported without changing ``TZ``: parsing never reads the local zone.
"""

import math
import re
from datetime import UTC, datetime

import pytest

from pyfect import schema as S
from pyfect.duration import Seconds
from pyfect.http import headers as h
from pyfect.http import schema as HS
from pyfect.redacted import Redacted
from pyfect.result import Err, Ok, Result

HTTP_DATE = datetime(1994, 11, 6, 8, 49, 37, tzinfo=UTC)
HTTP_DATE_MILLIS = 784_111_777_000


def _ok[A](result: Result[A, h.HeaderParseError]) -> A:
    match result:
        case Ok(value):
            return value
        case Err(error):
            raise AssertionError(error)


def test_remove() -> None:
    """remove"""
    headers = h.from_input({"foo": "bar", "baz": "qux", "hello": "world"})
    assert dict(headers.remove("baz")) == {"foo": "bar", "hello": "world"}
    assert list(headers) == ["foo", "baz", "hello"]


def test_remove_many() -> None:
    """removeMany deletes multiple headers"""
    headers = h.from_input({"foo": "bar", "baz": "qux", "hello": "world"})
    assert dict(headers.remove_many(["baz", "hello"])) == {"foo": "bar"}


def test_remove_many_lowercase() -> None:
    """removeMany normalizes keys to lowercase"""
    headers = h.from_input({"Content-Type": "text/plain", "X-Custom": "value", "keep": "me"})
    assert dict(headers.remove_many(["Content-Type", "X-CUSTOM"])) == {"keep": "me"}


def test_is_redacted_name_case_insensitive() -> None:
    """isRedactedName compares string patterns case-insensitively"""
    assert h.is_redacted_name("Authorization", ["authorization"])


def test_get() -> None:
    """get returns Option"""
    headers = h.from_input({"foo": "bar"})
    assert headers.get("foo") == "bar"
    assert headers.get("missing") is None


def test_redact_global_pattern() -> None:
    """redacts each header independently with a global pattern"""
    result = h.from_input({"x-secret-one": "one", "x-secret-two": "two"}).redact(
        re.compile("^x-secret-")
    )
    assert isinstance(result["x-secret-one"], Redacted)
    assert isinstance(result["x-secret-two"], Redacted)


def test_parse_http_date_formats() -> None:
    """parses every RFC 9110 format as UTC, whatever the process time zone"""
    for text in (
        "Sun, 06 Nov 1994 08:49:37 GMT",
        "Sunday, 06-Nov-94 08:49:37 GMT",
        "Sun Nov  6 08:49:37 1994",
    ):
        assert _ok(h.parse_http_date(text)) == HTTP_DATE, text


def test_parse_http_date_rejects() -> None:
    """rejects values that are not HTTP dates"""
    for text in ("1994-11-06T08:49:37Z", "120", "", "Sun, 06 Nov 1994 08:49:37 PST"):
        match h.parse_http_date(text):
            case Err(error):
                assert error.reason.tag == "InvalidHttpDate", text
            case Ok(_):
                pytest.fail(text)


def test_parse_http_date_error() -> None:
    """fails with a HeaderParseError"""
    match h.parse_http_date("tomorrow"):
        case Err(error):
            assert isinstance(error, h.HeaderParseError)
            assert error.message == 'InvalidHttpDate: "tomorrow"'
        case Ok(_):
            pytest.fail("parsed")


def test_rfc850_pivot() -> None:
    """reads RFC 850 two-digit years with a fixed pivot: 70-99 as 19xx, 00-69 as 20xx"""

    def year(text: str) -> int:
        return _ok(h.parse_http_date(text)).year

    assert year("Thursday, 01-Jan-70 00:00:00 GMT") == 1970
    assert year("Wednesday, 31-Dec-69 23:59:59 GMT") == 2069
    assert year("Saturday, 01-Jan-00 00:00:00 GMT") == 2000


def test_leap_second() -> None:
    """reads a leap second as the following second"""
    leap = _ok(h.parse_http_date("Sat, 31 Dec 2016 23:59:60 GMT"))
    assert leap == datetime(2017, 1, 1, tzinfo=UTC)


def test_format_http_date() -> None:
    """formats as IMF-fixdate"""
    assert h.format_http_date(HTTP_DATE) == "Sun, 06 Nov 1994 08:49:37 GMT"


def test_retry_after_seconds() -> None:
    """parses whole seconds"""
    value = _ok(h.parse_retry_after("120"))
    assert isinstance(value, h.RetryAfterDuration)
    assert value.duration == 120
    assert h.format_retry_after(value) == "120"


def test_retry_after_date() -> None:
    """parses an HTTP date"""
    value = _ok(h.parse_retry_after("Sun Nov  6 08:49:37 1994"))
    assert isinstance(value, h.RetryAfterDateTime)
    assert value.date_time == HTTP_DATE
    assert h.format_retry_after(value) == "Sun, 06 Nov 1994 08:49:37 GMT"


def test_retry_after_rejects() -> None:
    """rejects negative, fractional, exponent and non-finite seconds"""
    for text in ("-5", "1.5", "1e3", "Infinity", "", "soon"):
        match h.parse_retry_after(text):
            case Err(error):
                assert error.reason.tag == "InvalidRetryAfter", text
            case Ok(_):
                pytest.fail(text)


def test_retry_after_large() -> None:
    """parses and formats seconds beyond the safe integer range exactly"""
    text = "1000000000000000000000"
    value = _ok(h.parse_retry_after(text))
    assert h.retry_after_delay(value, 0) == 10**21
    assert h.format_retry_after(value) == text


def test_retry_after_duration() -> None:
    """retryAfterDuration rounds fractions up on the wire, clamps negatives and rejects infinity"""
    fractional = h.retry_after_duration(1.5)
    assert h.format_retry_after(fractional) == "2"
    assert h.retry_after_delay(fractional, 0) == 1.5
    negative = h.retry_after_duration(-5.0)
    assert h.format_retry_after(negative) == "0"
    assert h.retry_after_delay(negative, 0) == 0
    with pytest.raises(ValueError, match="infinite"):
        h.retry_after_duration(math.inf)


def test_retry_after_delay() -> None:
    """delay is measured from now and never negative"""
    seconds = _ok(h.parse_retry_after("120"))
    assert h.retry_after_delay(seconds, HTTP_DATE_MILLIS) == 120
    date = _ok(h.parse_retry_after("Sun, 06 Nov 1994 08:49:37 GMT"))
    assert h.retry_after_delay(date, HTTP_DATE_MILLIS - 30_000) == 30
    assert h.retry_after_delay(date, HTTP_DATE_MILLIS + 30_000) == 0


def test_schema_date_time_utc_from_http_date_decodes_any_format_and_encodes_imf_fixdate() -> None:
    """Schema.DateTimeUtcFromHttpDate decodes any format and encodes IMF-fixdate"""
    decoded = S.decode_sync(HS.DateTimeUtcFromHttpDate)("Sun Nov  6 08:49:37 1994")
    assert decoded.timestamp() * 1000 == HTTP_DATE_MILLIS
    assert S.encode_sync(HS.DateTimeUtcFromHttpDate)(decoded) == "Sun, 06 Nov 1994 08:49:37 GMT"
    with pytest.raises(S.SchemaError):
        S.decode_sync(HS.DateTimeUtcFromHttpDate)("tomorrow")


def test_schema_retry_after_from_string_round_trips_and_rejects_invalid_values() -> None:
    """Schema.RetryAfterFromString round trips and rejects invalid values"""
    decoded = S.decode_sync(HS.RetryAfterFromString)("120")
    assert decoded.tag == "Duration"
    assert S.encode_sync(HS.RetryAfterFromString)(decoded) == "120"
    with pytest.raises(S.SchemaError):
        S.decode_sync(HS.RetryAfterFromString)("-5")


def test_schema_retry_after_accepts_only_finite_non_negative_durations() -> None:
    """Schema.RetryAfter accepts only finite, non-negative durations"""
    is_retry_after = S.is_(HS.RetryAfter)
    assert is_retry_after(h.retry_after_duration(5))
    assert not is_retry_after(h.RetryAfterDuration(Seconds(-5.0)))
    assert not is_retry_after(h.RetryAfterDuration(Seconds(math.inf)))
