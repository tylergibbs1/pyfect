"""Text Effect writes with JavaScript's rules, written the same by pyfect
(QA schema-data F07, F08, F09, F12, F13). Each expected value is Effect
4.0.6's output under node.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from hypothesis import given
from hypothesis import strategies as st

from pyfect import _json_text
from pyfect import schema as S
from pyfect.option import Some

_LONE_SURROGATE = "a\ud800b"


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("StringFromBase64", "Ye+/vWI="),
        ("StringFromBase64Url", "Ye-_vWI"),
        ("StringFromHex", "61efbfbd62"),
    ],
)
def test_a_lone_surrogate_is_encoded_as_text_encoder_writes_it(name: str, expected: str):
    """``TextEncoder`` writes U+FFFD for a lone surrogate (F07)."""
    assert S.encode_sync(getattr(S, name))(_LONE_SURROGATE) == expected


def test_an_int_past_4300_digits_is_written_in_full_in_an_error():
    """Python's ``str`` raises past 4300 digits; ``String(bigint)`` does not (F08)."""
    big = 10**5000
    with pytest.raises(S.SchemaError) as error:
        S.decode_unknown_sync(S.String, report_input=True)(big)
    assert str(error.value) == "Expected string, got 1" + "0" * 5000


def test_an_int_past_4300_digits_is_encoded_as_its_json_digits():
    assert S.encode_sync(S.to_codec_json(S.BigInt))(10**5000) == "1" + "0" * 5000


@pytest.mark.parametrize(
    ("schema", "value", "message"),
    [
        (S.String, 2.0, "Expected string, got 2"),
        (S.Literal(2.5), 1e-7, "Expected 2.5, got 1e-7"),
        (S.Number.check(S.is_greater_than(3)), 2.0, "Expected a value greater than 3, got 2"),
    ],
)
def test_floats_in_messages_are_written_as_javascript_writes_them(
    schema: S.Top, value: float, message: str
):
    """``String(number)``, not ``repr`` (F09)."""
    with pytest.raises(S.SchemaError) as error:
        S.decode_unknown_sync(schema, report_input=True)(value)  # pyright: ignore[reportArgumentType]
    assert str(error.value) == message


def test_formatters_write_floats_as_javascript_writes_them():
    assert S.to_formatter(S.Option(S.Number))(Some(1.0)) == "some(1)"
    assert S.to_formatter(S.Number)(-0.0) == "0"
    assert S.to_formatter(S.Array(S.Number))((2.0, 1e-7)) == "[2, 1e-7]"


@pytest.mark.parametrize(
    ("value", "text"),
    [
        (datetime(1970, 1, 1, 0, 1, 53, 4000, tzinfo=UTC), "1970-01-01T00:01:53.004+00:00"),
        (
            datetime(1970, 1, 1, tzinfo=timezone(timedelta(hours=1))),
            "1970-01-01T00:00:00.000+01:00",
        ),
        (
            datetime(2024, 7, 21, 20, 12, 34, tzinfo=ZoneInfo("Pacific/Auckland")),
            "2024-07-21T20:12:34.000+12:00[Pacific/Auckland]",
        ),
        (
            datetime(1900, 1, 1, tzinfo=ZoneInfo("Asia/Kolkata")),
            "1900-01-01T00:00:00.000+05:21[Asia/Kolkata]",
        ),
    ],
)
def test_a_zoned_date_time_is_written_as_format_iso_zoned_writes_it(value: datetime, text: str):
    """Milliseconds and a whole-minute offset, as Effect's ``formatIsoZoned`` (F12)."""
    assert S.encode_sync(S.to_codec_json(S.DateTimeZoned))(value) == text


def test_a_written_zoned_date_time_reads_back():
    value = datetime(2024, 7, 21, 20, 12, 34, 5000, tzinfo=ZoneInfo("Pacific/Auckland"))
    codec = S.to_codec_json(S.DateTimeZoned)
    assert S.decode_unknown_sync(codec)(S.encode_sync(codec)(value)) == value.replace(
        microsecond=5000
    )


def test_json_text_numbers_are_written_as_json_stringify_writes_them():
    """``JSON.stringify([1.0, 1e-7, 1e16, -0])`` (F13)."""
    encoded = S.encode_sync(S.UnknownFromJsonString)([1.0, 1e-7, 1e16, -0.0])
    assert encoded == "[1,1e-7,10000000000000000,0]"


@pytest.mark.parametrize(
    ("value", "text"),
    [
        ({"a": [1, 2.5, "x"], "b": {"c": None}}, '{"a":[1,2.5,"x"],"b":{"c":null}}'),
        ([1e21, 123456789012345680000.0, 5e-324], "[1e+21,123456789012345680000,5e-324]"),
        ("\u2028\x7f\ud83d", '"\u2028\x7f\\ud83d"'),
        ({"k": True, "e": "é"}, '{"k":true,"e":"é"}'),
    ],
)
def test_stringify_matches_json_stringify(value: object, text: str):
    assert _json_text.stringify(value) == text


def test_stringify_indents_as_json_stringify_with_a_space():
    assert _json_text.stringify({"a": [1.0], "b": {}}, indent=2) == (
        '{\n  "a": [\n    1\n  ],\n  "b": {}\n}'
    )


_JSON_VALUES = st.recursive(
    st.none()
    | st.booleans()
    | st.integers()
    | st.floats(allow_nan=False, allow_infinity=False)
    | st.text(),
    lambda children: (
        st.lists(children, max_size=4) | st.dictionaries(st.text(max_size=3), children, max_size=4)
    ),
    max_leaves=12,
)


@given(_JSON_VALUES)
def test_stringify_writes_every_value_as_its_reference_writer_does(value: object):
    """``stringify`` writes through ``json.dumps`` when that gives
    JavaScript's text (also after making whole floats ints); every way must
    agree with the writer that follows ``JSON.stringify`` step by step
    (checked against Node on 20,000 doubles)."""
    writer = _json_text._Writer(None, False, None)  # pyright: ignore[reportPrivateUsage]
    writer.write(value, 0)
    assert _json_text.stringify(value) == "".join(writer.out)
