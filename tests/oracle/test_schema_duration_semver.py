"""Ports of Effect's ``DurationFromString``, ``DurationFromNanos``,
``DurationFromMillis``, ``SemVer``, ``SemVerFromString``, ``SemVerRange`` and
``SemVerRangeFromString`` tests from ``schema/Schema.test.ts``.

Each test's docstring is the Effect test title. pyfect's ``Duration`` schema
is a ``timedelta``, which holds neither infinities nor sub-microsecond
durations: those cases decode to ``Expected a duration a timedelta can
hold`` here (each such case is marked), and the encoding cases that start
from an infinite ``Duration`` have no ``timedelta`` to start from.

Omitted, with the reason:

- ``verifyRoundTrip`` in ``SemVerFromString`` / ``SemVerRangeFromString``:
  ``SchemaAsserts`` has no property round trip; the encoding cases cover the
  canonical text.
"""

from datetime import timedelta

from pyfect import schema as S
from pyfect import semver, semver_range
from pyfect.testing import SchemaAsserts

_HOLDS = "Expected a duration a timedelta can hold"


def test_duration_from_string() -> None:
    """DurationFromString"""
    asserts = SchemaAsserts(S.DurationFromString)
    decoding = asserts.decoding()
    decoding.succeed("1000 millis", timedelta(milliseconds=1000))
    decoding.succeed("1 second", timedelta(seconds=1))
    decoding.fail("Infinity", _HOLDS)  # no infinite timedelta
    decoding.fail("1 nano", _HOLDS)  # Python: below a microsecond
    decoding.fail("value", "Expected a valid Duration string")
    encoding = asserts.encoding()
    encoding.succeed(timedelta(0), "0 millis")
    encoding.succeed(timedelta(seconds=5), "5000 millis")
    encoding.succeed(timedelta(microseconds=5), "5000 nanos")


def test_duration_from_nanos() -> None:
    """DurationFromNanos"""
    asserts = SchemaAsserts(S.DurationFromNanos)
    asserts.verify_generation()
    decoding = asserts.decoding()
    decoding.succeed(0, timedelta(0))
    decoding.succeed(1000, timedelta(microseconds=1))
    decoding.succeed(-1000, timedelta(microseconds=-1))
    decoding.fail(1, _HOLDS)  # Python: below a microsecond
    encoding = asserts.encoding()
    encoding.succeed(timedelta(milliseconds=5), 5_000_000)
    encoding.succeed(timedelta(microseconds=5), 5000)
    encoding.succeed(timedelta(microseconds=-5), -5000)


def test_duration_from_millis() -> None:
    """DurationFromMillis"""
    asserts = SchemaAsserts(S.DurationFromMillis)
    asserts.verify_generation()
    decoding = asserts.decoding()
    decoding.fail(float("inf"), _HOLDS)  # no infinite timedelta
    decoding.succeed(0, timedelta(0))
    decoding.succeed(-1, timedelta(milliseconds=-1))
    decoding.succeed(1000, timedelta(seconds=1))
    decoding.succeed(60 * 1000, timedelta(minutes=1))
    decoding.succeed(0.1, timedelta(microseconds=100))
    decoding.succeed(float("nan"), timedelta(0))
    encoding = asserts.encoding()
    encoding.succeed(timedelta(milliseconds=-1), -1)
    encoding.succeed(timedelta(seconds=5), 5000)
    encoding.succeed(timedelta(milliseconds=5000), 5000)
    encoding.succeed(timedelta(microseconds=100), 0.1)
    encoding.succeed(timedelta(microseconds=5), 0.005)


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


def test_durations_round_to_nanoseconds_before_they_are_held() -> None:
    """Review: Effect rounds a duration to whole nanoseconds, ties away
    from zero (text exactly, milliseconds as ``Math.round(millis * 1e6)``),
    so these are whole microseconds there (values printed by Effect under
    Node); ``"-Infinity"`` is infinite like ``"Infinity"``."""
    text = SchemaAsserts(S.DurationFromString).decoding()
    text.succeed("1.0000000001 seconds", timedelta(seconds=1))
    text.succeed("999.5 nanos", timedelta(microseconds=1))
    text.succeed("-999.5 nanos", timedelta(microseconds=-1))
    text.fail("999.4 nanos", _HOLDS)
    text.fail("-Infinity", _HOLDS)
    text.fail("1" + "0" * 5000 + " nanos", _HOLDS)  # past ``int``'s digit limit
    text.succeed("1." + "0" * 5000 + " seconds", timedelta(seconds=1))
    millis = SchemaAsserts(S.DurationFromMillis).decoding()
    millis.succeed(1.0000001, timedelta(milliseconds=1))
    millis.succeed(0.0000004, timedelta(0))
    millis.fail(-0.0000005, _HOLDS)
    millis.fail(10**400, _HOLDS)  # an int past float range


def test_every_encoded_timedelta_decodes_from_millis() -> None:
    """Review: a long ``timedelta`` with microseconds encodes to a float
    whose product with ``1e6`` is not whole microseconds; reading the
    float's text keeps it decodable."""
    asserts = SchemaAsserts(S.DurationFromMillis)
    duration = timedelta(days=104, microseconds=1)
    millis = S.encode_sync(S.DurationFromMillis)(duration)
    asserts.decoding().succeed(millis, duration)


def test_a_timedelta_milliseconds_cannot_hold_fails_to_encode() -> None:
    """Review: past about 285 years a float of milliseconds has no room
    for the microseconds, so encoding fails rather than writing a
    different duration."""
    encoding = SchemaAsserts(S.DurationFromMillis).encoding()
    encoding.fail(
        timedelta(days=237254, microseconds=775114),
        "Expected a duration a number of milliseconds can hold exactly",
    )
    encoding.succeed(timedelta(days=237254), 237254 * 86_400_000)
