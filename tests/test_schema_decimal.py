"""``S.Decimal``: a finite ``decimal.Decimal`` (Python-only; Effect's
``BigDecimal`` is ``S.BigDecimal``), written in JSON as its text, and the
schema of a ``decimal.Decimal`` annotation."""

from __future__ import annotations

import decimal
from typing import Any

import pytest
from oracle._cli_env import test_layer

import pyfect as fx
import pyfect.schema as S
from pyfect import testing
from pyfect.cli import Argument, Config, command
from pyfect.cli.cli_error import ShowHelp
from pyfect.testing import SchemaAsserts, Services

cli_env = testing.layer_fixture(test_layer, scope="function")


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


D = decimal.Decimal


def test_the_decimal_order_checks_compare_decimals_exactly():
    positive = SchemaAsserts(S.Decimal.check(S.is_greater_than_decimal(D(0)))).decoding()
    positive.succeed(D("0.01"))
    positive.fail(D(0), "Expected a value greater than 0")
    positive.fail(D("-1"), "Expected a value greater than 0")

    at_least = SchemaAsserts(
        S.Decimal.check(S.is_greater_than_or_equal_to_decimal(D("0.10")))
    ).decoding()
    at_least.succeed(D("0.1"))
    at_least.fail(D("0.09"), "Expected a value greater than or equal to 0.10")

    below = SchemaAsserts(S.Decimal.check(S.is_less_than_decimal(D("1E+2")))).decoding()
    below.succeed(D("99.99"))
    below.fail(D(100), "Expected a value less than 1E+2")

    at_most = SchemaAsserts(S.Decimal.check(S.is_less_than_or_equal_to_decimal(D(1)))).decoding()
    at_most.succeed(D("1.000"))
    at_most.fail(D("1.0000000000000000000000001"), "Expected a value less than or equal to 1")


def test_is_between_decimal_includes_its_bounds_unless_told_otherwise():
    between = SchemaAsserts(
        S.Decimal.check(S.is_between_decimal(minimum=D(1), maximum=D(2)))
    ).decoding()
    between.succeed(D(1))
    between.succeed(D(2))
    between.fail(D("2.5"), "Expected a value between 1 and 2")

    exclusive = SchemaAsserts(
        S.Decimal.check(
            S.is_between_decimal(
                minimum=D(1), maximum=D(2), exclusive_minimum=True, exclusive_maximum=True
            )
        )
    ).decoding()
    exclusive.succeed(D("1.5"))
    exclusive.fail(D(1), "Expected a value between 1 (excluded) and 2 (excluded)")
    exclusive.fail(D(2), "Expected a value between 1 (excluded) and 2 (excluded)")


def test_checked_decimals_and_their_text_round_trip():
    positive = S.Decimal.check(S.is_between_decimal(minimum=D(0), maximum=D(1)))
    SchemaAsserts(positive).verify_round_trip(runs=30)
    SchemaAsserts(S.DecimalFromString).verify_round_trip(runs=30)


def test_decimal_from_string_reads_and_writes_a_decimals_text():
    decoding = SchemaAsserts(S.DecimalFromString).decoding()
    decoding.succeed("1.10", D("1.10"))
    decoding.succeed("-1E+2", D("-1E+2"))
    decoding.fail("NaN", "Expected a decimal number string")
    decoding.fail(1.5, "Expected string")
    assert S.encode_sync(S.DecimalFromString)(D("1.10")) == "1.10"
    value = S.decode_unknown_sync(S.DecimalFromString)("1.10")
    assert value.as_tuple() == D("1.10").as_tuple()


def test_decimal_from_string_with_a_check_rejects_what_the_check_does():
    positive = S.DecimalFromString.check(S.is_greater_than_decimal(D(0)))
    assert S.decode_unknown_sync(positive)("0.5") == D("0.5")
    with pytest.raises(S.SchemaError, match="Expected a value greater than 0"):
        S.decode_unknown_sync(positive)("-0.5")


class _Pay(Config):
    amount = Argument.string("amount").with_schema(
        S.DecimalFromString.check(S.is_greater_than_decimal(D(0)))
    )


@testing.effect
def test_a_cli_argument_reads_a_checked_decimal(cli_env: Services[Any]):
    seen: list[D] = []
    app = command.make("pay", _Pay, lambda config: fx.sync(lambda: seen.append(config.amount)))
    yield from command.run_with(app, version="1")(["12.50"])
    assert seen == [D("12.50")]
    error = yield from command.run_with(app, version="1")(["-1"]).flip()
    assert isinstance(error, ShowHelp)
    assert "Expected a value greater than 0" in str([e.message for e in error.errors])
