"""``S.Decimal``: a finite ``decimal.Decimal`` (Python-only; Effect's
``BigDecimal`` is ``S.BigDecimal``), written in JSON as its text, and the
schema of a ``decimal.Decimal`` annotation."""

from __future__ import annotations

import decimal

import pytest

import pyfect.schema as S
from pyfect.testing import SchemaAsserts


def test_decimal_accepts_finite_decimals_only():
    decoding = SchemaAsserts(S.Decimal).decoding()
    decoding.succeed(decimal.Decimal("1.10"))
    decoding.succeed(decimal.Decimal("-0"))
    for value in [decimal.Decimal("NaN"), decimal.Decimal("Infinity"), 1.5, 1, "1.5"]:
        decoding.fail(value, "Expected a finite Decimal")


@pytest.mark.parametrize("text", ["1.10", "-0", "1E+2", "0.000001", "12345678901234567890.5"])
def test_json_writes_a_decimal_as_its_text_and_reads_it_back_exactly(text: str):
    value = decimal.Decimal(text)
    codec = S.to_codec_json(S.Decimal)
    assert S.encode_sync(codec)(value) == str(value)
    decoded = S.decode_unknown_sync(codec)(str(value))
    assert decoded.as_tuple() == value.as_tuple()


@pytest.mark.parametrize("text", ["NaN", "Infinity", "1_0", " 1", "\u0661", "1.", ".5x", ""])
def test_json_refuses_text_that_is_not_a_plain_finite_decimal(text: str):
    with pytest.raises(S.SchemaError):
        S.decode_unknown_sync(S.to_codec_json(S.Decimal))(text)


def test_a_decimal_annotation_is_the_decimal_schema():
    class Price(S.Class):
        amount: decimal.Decimal

    assert Price.fields()["amount"] is S.Decimal
    json = S.to_codec_json(Price)
    assert S.encode_sync(json)(Price(amount=decimal.Decimal("9.99"))) == {"amount": "9.99"}
