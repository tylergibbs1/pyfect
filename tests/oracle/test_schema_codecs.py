"""Ports of Effect's ``Schema.test.ts``: the built-in string, binary,
date-time, ``ByteSize`` and URL codecs. Each test's docstring is the Effect
test title, prefixed by its ``describe`` block. ``TestSchema.Asserts`` is
``testing.SchemaAsserts``.

Python mappings: ``Uint8ArrayFromBase64`` / ``Uint8ArrayFromBase64Url`` /
``Uint8ArrayFromHex`` are ``BytesFromBase64`` / ``BytesFromBase64Url`` /
``BytesFromHex`` (``bytes``); a ``URL`` is a ``Url``; a UTC ``DateTime``
is an aware ``datetime``.

Omitted: "BooleanFromBit", "Uint8Array", "URL", "PropertyKey": they only
verify arbitrary generation (no arbitraries yet).
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from pyfect import byte_size
from pyfect import effect as fx
from pyfect import schema as S
from pyfect.http.url import Url
from pyfect.schema import transformation as T
from pyfect.schema.issue import Forbidden, Issue
from pyfect.testing import SchemaAsserts

_MAX_SAFE_INTEGER = 2**53 - 1


def test_uint8_array_from_base64():
    """Uint8ArrayFromBase64"""
    asserts = SchemaAsserts(S.BytesFromBase64)
    decoding = asserts.decoding()
    decoding.succeed("Zm9vYmFy", b"foobar")
    decoding.fail("Zm9vY", "Expected a valid Base64 string")
    decoding.fail("Zm9vYmF-", "Expected a valid Base64 string")
    decoding.fail("=Zm9vYmF", "Expected a valid Base64 string")
    asserts.encoding().succeed(b"foobar", "Zm9vYmFy")


def test_string_from_base64():
    """StringFromBase64"""
    asserts = SchemaAsserts(S.StringFromBase64)
    decoding = asserts.decoding()
    decoding.succeed("Zm9vYmFy", "foobar")
    decoding.fail("Zm9vY", "Expected a valid Base64 string")
    decoding.fail("Zm9vYmF-", "Expected a valid Base64 string")
    decoding.fail("=Zm9vYmF", "Expected a valid Base64 string")
    asserts.encoding().succeed("foobar", "Zm9vYmFy")


def test_string_from_base64_url():
    """StringFromBase64Url"""
    asserts = SchemaAsserts(S.StringFromBase64Url)
    decoding = asserts.decoding()
    decoding.succeed("Zm9vYmFy", "foobar")
    decoding.fail("Zm9vY", "Expected a valid Base64Url string")
    decoding.succeed("Pj8-ZD_Dnw", ">?>d?ß")
    decoding.fail("Pj8/ZD+Dnw", "Expected a valid Base64Url string")
    encoding = asserts.encoding()
    encoding.succeed("foobar", "Zm9vYmFy")
    encoding.succeed(">?>d?ß", "Pj8-ZD_Dnw")


def test_string_from_hex():
    """StringFromHex"""
    asserts = SchemaAsserts(S.StringFromHex)
    decoding = asserts.decoding()
    decoding.succeed("67", "g")
    decoding.fail("0", "Expected a valid hexadecimal string")
    decoding.fail("zd4aa", "Expected a valid hexadecimal string")
    decoding.fail("0\x01", "Expected a valid hexadecimal string")
    asserts.encoding().succeed("g", "67")


def test_string_from_uri_component():
    """StringFromUriComponent"""
    asserts = SchemaAsserts(S.StringFromUriComponent)
    decoding = asserts.decoding()
    decoding.succeed("%7B%22a%22%3A1%7D", '{"a":1}')
    decoding.succeed("%D1%88%D0%B5%D0%BB%D0%BB%D1%8B", "шеллы")
    decoding.succeed("hello%20world", "hello world")
    decoding.succeed("hello", "hello")
    decoding.fail("%ZZ", "Expected a valid URI component")
    encoding = asserts.encoding()
    encoding.succeed('{"a":1}', "%7B%22a%22%3A1%7D")
    encoding.succeed("hello world", "hello%20world")


def test_uint8_array_from_base64_url():
    """Uint8ArrayFromBase64Url"""
    asserts = SchemaAsserts(S.BytesFromBase64Url)
    decoding = asserts.decoding()
    decoding.succeed("Zm9vYmFy", b"foobar")
    decoding.fail("Zm9vY", "Expected a valid Base64Url string")
    decoding.succeed("Pj8-ZD_Dnw", ">?>d?ß".encode())
    decoding.fail("Pj8/ZD+Dnw", "Expected a valid Base64Url string")
    encoding = asserts.encoding()
    encoding.succeed(b"foobar", "Zm9vYmFy")
    encoding.succeed(">?>d?ß".encode(), "Pj8-ZD_Dnw")


def test_uint8_array_from_hex():
    """Uint8ArrayFromHex"""
    asserts = SchemaAsserts(S.BytesFromHex)
    decoding = asserts.decoding()
    decoding.succeed("0001020304050607", bytes([0, 1, 2, 3, 4, 5, 6, 7]))
    decoding.succeed("f0f1f2f3f4f5f6f7", bytes([0xF0, 0xF1, 0xF2, 0xF3, 0xF4, 0xF5, 0xF6, 0xF7]))
    decoding.succeed("67", b"g")
    decoding.fail("0", "Expected a valid hexadecimal string")
    decoding.fail("2d4aa", "Expected a valid hexadecimal string")
    decoding.fail("0\x01", "Expected a valid hexadecimal string")
    asserts.encoding().succeed(bytes([0, 1, 2, 3, 4, 5, 6, 7]), "0001020304050607")


_NEW_YEAR = datetime(2021, 1, 1, tzinfo=UTC)


def test_date_time_utc_from_string():
    """DateTimeUtcFromString"""
    asserts = SchemaAsserts(S.DateTimeUtcFromString)
    decoding = asserts.decoding()
    decoding.succeed("2021-01-01T00:00:00.000Z", _NEW_YEAR)
    decoding.fail("invalid", "Expected a valid UTC DateTime string")
    decoding.fail(None, "Expected string")
    asserts.encoding().succeed(_NEW_YEAR, "2021-01-01T00:00:00.000Z")


def test_date_time_utc_from_millis():
    """DateTimeUtcFromMillis"""
    asserts = SchemaAsserts(S.DateTimeUtcFromMillis)
    asserts.decoding().succeed(1609459200000, _NEW_YEAR)
    asserts.decoding().fail(None, "Expected number")
    asserts.encoding().succeed(_NEW_YEAR, 1609459200000)


def test_transformations_to_lower_case():
    """Transformations / toLowerCase"""
    schema = S.String.pipe(S.decode_to(S.String, T.to_lower_case()))
    decoding = SchemaAsserts(schema).decoding()
    decoding.succeed("A", "a")
    decoding.succeed("B", "b")


def test_transformations_to_upper_case():
    """Transformations / toUpperCase"""
    schema = S.String.pipe(S.decode_to(S.String, T.to_upper_case()))
    decoding = SchemaAsserts(schema).decoding()
    decoding.succeed("a", "A")
    decoding.succeed("b", "B")


def test_byte_size_from_string():
    """ByteSizeFromString"""
    asserts = SchemaAsserts(S.ByteSizeFromString)
    asserts.decoding().succeed("1.5 kB", byte_size.bytes(1500))
    asserts.decoding().fail("1 KB", "Expected a valid ByteSize string")
    asserts.encoding().succeed(byte_size.bytes(1500), "1500 bytes")


def test_byte_size_from_big_int():
    """ByteSizeFromBigInt"""
    asserts = SchemaAsserts(S.ByteSizeFromBigInt)
    asserts.decoding().succeed(9_007_199_254_740_993, byte_size.bytes(9_007_199_254_740_993))
    asserts.decoding().fail(-1, "Expected a non-negative bigint byte count")
    asserts.encoding().succeed(byte_size.bytes(9_007_199_254_740_993), 9_007_199_254_740_993)


def test_byte_size_from_number():
    """ByteSizeFromNumber"""
    asserts = SchemaAsserts(S.ByteSizeFromNumber)
    decoding = asserts.decoding()
    decoding.succeed(_MAX_SAFE_INTEGER, byte_size.bytes(_MAX_SAFE_INTEGER))
    for input in (-1, 0.5, _MAX_SAFE_INTEGER + 1):
        decoding.fail(input, "Expected a non-negative safe-integer byte count")
    encoding = asserts.encoding()
    encoding.succeed(byte_size.bytes(1500), 1500)
    encoding.fail(
        byte_size.bytes(_MAX_SAFE_INTEGER + 1),
        "Expected a ByteSize representable as a safe integer",
    )


def test_url_from_string():
    """URLFromString"""
    asserts = SchemaAsserts(S.URLFromString)
    asserts.decoding().succeed("https://effect.website", Url("https://effect.website"))
    asserts.decoding().fail("123", "Expected a valid URL string")
    asserts.encoding().succeed(Url("https://effect.website/"), "https://effect.website/")


def test_trim():
    """Trim"""
    asserts = SchemaAsserts(S.Trim)
    decoding = asserts.decoding()
    decoding.succeed("a")
    for input in ("a ", " a", " a ", "a\n"):
        decoding.succeed(input, "a")
    encoding = asserts.encoding()
    encoding.succeed("a")
    encoding.fail("a ", "Expected a string with no leading or trailing whitespace")


def _forbidding(value: str) -> Callable[[str, object], fx.Effect[str, Issue]]:
    def run(s: str, _: object) -> fx.Effect[str, Issue]:
        if s == value:
            return fx.fail(Forbidden({"message": f'input should not be "{value}"'}))
        return fx.succeed(s)

    return run


def test_transform_effect():
    """transformEffect"""
    transformation = T.transform_effect(decode=_forbidding("a"), encode=_forbidding("b"))
    asserts = SchemaAsserts(S.String.pipe(S.decode_to(S.String, transformation)))
    asserts.decoding().succeed("b")
    asserts.decoding().fail("a", 'input should not be "a"')
    asserts.encoding().succeed("a")
    asserts.encoding().fail("b", 'input should not be "b"')
