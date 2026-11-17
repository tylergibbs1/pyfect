"""Ports of Effect's ``Rational`` and ``RationalFromString`` tests from
``schema/Schema.test.ts``.

Each test's docstring is the Effect test title.
"""

from pyfect import big_decimal, rational
from pyfect import schema as S
from pyfect.testing import SchemaAsserts


def test_rational_from_string() -> None:
    """RationalFromString"""
    asserts = SchemaAsserts(S.RationalFromString)
    asserts.verify_generation()

    decoding = asserts.decoding()
    decoding.succeed("6/5", rational.make_unsafe(6, 5))
    decoding.succeed("-4/-6", rational.make_unsafe(2, 3))
    decoding.succeed("3", rational.from_big_int(3))
    decoding.fail("1/0", "Expected a valid Rational string")
    decoding.fail("1.5", "Expected a valid Rational string")

    encoding = asserts.encoding()
    encoding.succeed(rational.make_unsafe(6, 5), "6/5")
    encoding.succeed(rational.from_big_int(0), "0/1")
    encoding.fail("6/5", "Expected Rational")


def test_rational() -> None:
    """Rational"""
    asserts = SchemaAsserts(S.Rational)
    asserts.verify_generation()

    asserts.decoding().succeed(rational.make_unsafe(1, 3))
    asserts.decoding().fail(big_decimal.from_big_int(1), "Expected Rational")

    json = SchemaAsserts(S.to_codec_json(S.Rational))
    json.decoding().succeed("1/3", rational.make_unsafe(1, 3))
    json.encoding().succeed(rational.make_unsafe(1, 3), "1/3")
