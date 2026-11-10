"""Ports of Effect's ``DurationFromString``, ``DurationFromNanos``,
``DurationFromMillis``, ``DurationFromIsoString``, ``SemVer``, ``SemVerFromString``,
``SemVerRange`` and ``SemVerRangeFromString`` tests from ``schema/Schema.test.ts``.

Each test's docstring is the Effect test title.

Omitted, with the reason:

- ``verifyRoundTrip`` in ``SemVerFromString`` / ``SemVerRangeFromString``:
  ``SchemaAsserts`` has no property round trip; the encoding cases cover the
  canonical text.
"""

import math

from pyfect import duration, semver, semver_range
from pyfect import schema as S
from pyfect.testing import SchemaAsserts


def test_duration_from_string() -> None:
    """DurationFromString"""
    asserts = SchemaAsserts(S.DurationFromString)
    decoding = asserts.decoding()
    decoding.succeed("1000 millis", duration.millis(1000))
    decoding.succeed("1 second", duration.seconds(1))
    decoding.succeed("Infinity", duration.infinity)
    decoding.succeed("-Infinity", duration.negative_infinity)
    decoding.fail("value", "Expected a valid Duration string")
    encoding = asserts.encoding()
    encoding.succeed(duration.zero, "0 millis")
    encoding.succeed(duration.seconds(5), "5000 millis")
    encoding.succeed(duration.nanos(5000), "5000 nanos")
    encoding.succeed(duration.infinity, "Infinity")
    encoding.succeed(duration.negative_infinity, "-Infinity")


def test_duration_from_iso_string() -> None:
    """DurationFromIsoString"""
    asserts = SchemaAsserts(S.DurationFromIsoString)
    decoding = asserts.decoding()
    decoding.succeed("P1W2D", duration.days(9))
    decoding.succeed("PT1H30M", duration.minutes(90))
    decoding.succeed("-PT1.5S", duration.millis(-1500))
    decoding.succeed("PT0.000000001S", duration.nanos(1))
    expected = "Expected an ISO 8601 duration without years or months"
    for text in ("P1Y", "P1M", "1 second"):
        decoding.fail(text, expected)
    encoding = asserts.encoding()
    encoding.succeed(duration.zero, "PT0S")
    encoding.succeed(duration.weeks(1), "P7D")
    encoding.succeed(duration.nanos(-1), "-PT0.000000001S")
    encoding.fail(duration.infinity, "Expected a finite Duration")
    encoding.fail(duration.negative_infinity, "Expected a finite Duration")


def test_duration_from_nanos() -> None:
    """DurationFromNanos"""
    asserts = SchemaAsserts(S.DurationFromNanos)
    asserts.verify_generation()
    decoding = asserts.decoding()
    decoding.succeed(0, duration.zero)
    decoding.succeed(1000, duration.nanos(1000))
    decoding.succeed(-1000, duration.nanos(-1000))
    encoding = asserts.encoding()
    encoding.succeed(duration.millis(5), 5_000_000)
    encoding.succeed(duration.nanos(5000), 5000)
    encoding.succeed(duration.nanos(-5000), -5000)
    encoding.fail(duration.infinity, "Expected a Duration representable as a bigint")
    encoding.fail(duration.negative_infinity, "Expected a Duration representable as a bigint")


def test_duration_from_millis() -> None:
    """DurationFromMillis"""
    asserts = SchemaAsserts(S.DurationFromMillis)
    asserts.verify_generation()
    decoding = asserts.decoding()
    decoding.succeed(math.inf, duration.infinity)
    decoding.succeed(-math.inf, duration.negative_infinity)
    decoding.succeed(0, duration.millis(0))
    decoding.succeed(-1, duration.millis(-1))
    decoding.succeed(1000, duration.seconds(1))
    decoding.succeed(60 * 1000, duration.minutes(1))
    decoding.succeed(0.1, duration.millis(0.1))
    decoding.succeed(math.nan, duration.zero)
    encoding = asserts.encoding()
    encoding.succeed(duration.infinity, math.inf)
    encoding.succeed(duration.negative_infinity, -math.inf)
    encoding.succeed(duration.millis(math.nan), 0)
    encoding.succeed(duration.millis(-1), -1)
    encoding.succeed(duration.seconds(5), 5000)
    encoding.succeed(duration.millis(5000), 5000)
    encoding.succeed(duration.millis(0.1), 0.1)
    encoding.succeed(duration.nanos(5000), 0.005)


def test_semver() -> None:
    """SemVer"""
    SchemaAsserts(S.SemVer).verify_generation()
    SchemaAsserts(S.SemVer).decoding().fail("1.2.3", "Expected SemVer")
    json = SchemaAsserts(S.to_codec_json(S.SemVer))
    version = semver.parse_unsafe("1.2.3-rc.1+001")
    json.decoding().succeed("1.2.3-rc.1+001", version)
    json.encoding().succeed(version, "1.2.3-rc.1+001")


def test_semver_from_string() -> None:
    """SemVerFromString"""
    asserts = SchemaAsserts(S.SemVerFromString)
    text = "1.0.0-beta+exp.sha.5114f85"
    asserts.decoding().succeed(text, semver.parse_unsafe(text))
    asserts.decoding().fail(
        "v1.2.3",
        'Invalid SemVer "v1.2.3": major must be a non-negative integer without leading zeros, '
        'received "v1"',
    )
    asserts.encoding().succeed(semver.parse_unsafe("1.2.3+build"), "1.2.3+build")


def test_semver_range() -> None:
    """SemVerRange"""
    SchemaAsserts(S.SemVerRange).verify_generation()
    SchemaAsserts(S.SemVerRange).decoding().fail("^1.2.3", "Expected SemVerRange")
    json = SchemaAsserts(S.to_codec_json(S.SemVerRange))
    json.decoding().succeed("^1.2 || 2.x", semver_range.parse_unsafe("^1.2 || 2"))
    json.encoding().succeed(semver_range.parse_unsafe(">= 1.2.3 <2.x"), ">=1.2.3 <2")


def test_semver_range_from_string() -> None:
    """SemVerRangeFromString"""
    asserts = SchemaAsserts(S.SemVerRangeFromString)
    asserts.decoding().succeed("~1.2.3-beta.1", semver_range.parse_unsafe("~1.2.3-beta.1"))
    asserts.decoding().fail(
        "^v1",
        'Invalid SemVer range "^v1": major must be a non-negative integer without leading '
        'zeros, received "v1"',
    )
    asserts.encoding().succeed(semver_range.parse_unsafe("1.2.3 - 2.x"), "1.2.3 - 2")


def test_boolean_literals() -> None:
    """BooleanLiterals (internal in Schema.ts; Effect has no test of its own)"""
    asserts = SchemaAsserts(S.BooleanLiterals)
    for text in ("true", "yes", "on", "1", "y"):
        asserts.decoding().succeed(text, True)
    for text in ("false", "no", "off", "0", "n"):
        asserts.decoding().succeed(text, False)
    asserts.encoding().succeed(True, "true")
    asserts.encoding().succeed(False, "false")


def test_durations_round_to_nanoseconds() -> None:
    """Review: Effect rounds a duration to whole nanoseconds, ties away from zero (text
    exactly, milliseconds as ``Math.round(millis * 1e6)``), and keeps any length."""
    text = SchemaAsserts(S.DurationFromString).decoding()
    text.succeed("1.0000000001 seconds", duration.seconds(1))
    text.succeed("999.5 nanos", duration.nanos(1000))
    text.succeed("-999.5 nanos", duration.nanos(-1000))
    text.succeed("999.4 nanos", duration.nanos(999))
    millis = SchemaAsserts(S.DurationFromMillis).decoding()
    millis.succeed(1.0000001, duration.millis(1))
    millis.succeed(0.0000004, duration.zero)
    millis.succeed(-0.0000005, duration.nanos(-1))
    millis.succeed(10**400, duration.infinity)  # an int past float range


def test_long_durations_keep_every_nanosecond() -> None:
    """Review: a duration past what a ``timedelta`` holds, to the nanosecond, decodes and
    encodes exactly through nanoseconds and ISO 8601 text."""
    long = duration.nanos(10**30 + 1)
    SchemaAsserts(S.DurationFromNanos).decoding().succeed(10**30 + 1, long)
    assert S.encode_sync(S.DurationFromNanos)(long) == 10**30 + 1
    iso = S.encode_sync(S.DurationFromIsoString)(duration.nanos(123_456_789_012_345_678))
    assert iso == "P1428DT21H33M9.012345678S"
    assert S.decode_sync(S.DurationFromIsoString)(iso) == duration.nanos(123_456_789_012_345_678)


def test_fractional_milliseconds_are_held_in_nanoseconds() -> None:
    """Review: ``Duration.millis(1.5)`` is held as 1500000 nanoseconds, so its text and
    JSON forms are nanoseconds; a JSON ``Millis`` must be a safe integer (values printed
    by Effect 4.1.2 under Node)."""
    assert S.encode_sync(S.DurationFromString)(duration.millis(1.5)) == "1500000 nanos"
    assert S.encode_sync(S.DurationFromMillis)(duration.nanos(1)) == 0.000001
    json = SchemaAsserts(S.to_codec_json(S.Duration))
    json.encoding().succeed(duration.millis(1.5), {"_tag": "Nanos", "value": "1500000"})
    json.encoding().fail(duration.seconds(1e17), 'Expected an integer\n  at ["value"]')
    json.decoding().fail({"_tag": "Millis", "value": 1.5}, 'Expected an integer\n  at ["value"]')
