"""Encoded values with no Python form are a ``SchemaError``, never a defect
(QA schema-data F03). Effect's ``TimeZone.Offset`` is not bounded; ``timezone``
offsets lie strictly inside a day, so pyfect rejects the rest as invalid values
(PARITY §4). A ``Duration`` holds any length, as Effect's does.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from pyfect import duration
from pyfect import schema as S


def _decode_json(schema: Any, value: object) -> object:
    return S.decode_unknown_sync(S.to_codec_json(schema))(value)


@pytest.mark.parametrize(
    ("schema", "value", "message"),
    [
        (
            S.Duration,
            {"_tag": "Millis", "value": 10**20},
            f'Expected an integer, got {10**20}\n  at ["value"]',
        ),
        (
            S.TimeZoneOffset,
            86400000,
            "Expected an offset strictly between -24 and +24 hours, got 86400000",
        ),
    ],
)
def test_an_out_of_range_json_value_is_a_schema_error(schema: Any, value: object, message: str):
    with pytest.raises(S.SchemaError) as error:
        S.decode_unknown_sync(S.to_codec_json(schema), report_input=True)(value)
    assert str(error.value) == message


def test_a_duration_of_any_length_decodes_from_json():
    assert _decode_json(S.Duration, {"_tag": "Nanos", "value": "9" * 30}) == duration.nanos(
        10**30 - 1
    )


def test_the_largest_offset_inside_a_day_still_decodes():
    zone: Any = _decode_json(S.TimeZoneOffset, 86399999)
    assert zone.utcoffset(None).total_seconds() == 86399.999


_HOSTILE_NUMBERS: list[object] = [
    10**20,
    -(10**20),
    10**400,
    1e308,
    -1e308,
    5e-324,
    "9" * 30,
    "-" + "9" * 30,
    "9" * 5000,
    2**63,
    86400000,
    -86400000,
]


def _hostile_values() -> list[object]:
    values: list[object] = list(_HOSTILE_NUMBERS)
    for number in _HOSTILE_NUMBERS:
        values += [{"_tag": tag, "value": number} for tag in ("Millis", "Nanos", "Infinity")]
        values += [[number], {"a": number}, {"epoch_millis": number, "zone": number}]
    return values


def _catalog() -> list[tuple[str, Any]]:
    return [(name, value) for name in dir(S) if isinstance(value := getattr(S, name), S.Bottom)]


_CODECS: list[tuple[str, Callable[[Any], Any]]] = [
    ("json", S.to_codec_json),
    ("string tree", S.to_codec_string_tree),
]


@pytest.mark.parametrize(("codec_name", "to_codec"), _CODECS)
def test_no_catalog_codec_dies_on_out_of_range_input(
    codec_name: str, to_codec: Callable[[Any], Any]
):
    """The guard: every public schema's codec turns huge numbers, digit
    strings and tagged forms into a ``SchemaError`` or a value, never a
    defect (an ``OverflowError`` from a Python constructor, say)."""
    defects: list[str] = []
    for name, schema in _catalog():
        try:
            decode = S.decode_unknown_sync(to_codec(schema))
        except (TypeError, ValueError):
            continue  # no such codec for this schema
        for value in _hostile_values():
            try:
                decode(value)
            except S.SchemaError:
                pass
            except Exception as defect:
                defects.append(f"{codec_name} {name} {repr(value)[:40]}: {defect.__cause__!r}")
    assert defects == []
