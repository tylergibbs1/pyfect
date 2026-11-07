"""Turning pyfect values into OpenTelemetry attribute values."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Final, cast

from opentelemetry.util.types import AttributeValue

from pyfect._version import VERSION
from pyfect.logger._text import to_string_unknown

PYFECT_VERSION: Final = VERSION
"""The instrumentation scope version of every tracer, logger and meter."""

_INT64_MIN: Final = -(2**63)
_INT64_MAX: Final = 2**63 - 1


def to_attribute_value(value: object) -> AttributeValue:
    """Effect's ``unknownToAttributeValue``: strings, numbers and booleans
    as they are (an integer too big for 64 bits as text, like Effect's
    ``bigint``), a list or tuple whose items are all strings, all booleans
    or all numbers as a list, and anything else as text
    (``toStringUnknown``)."""
    match value:
        case str() | bool() | float():
            return value
        case int():
            return value if _is_int64(value) else str(value)
        case list() | tuple():
            return _homogeneous(cast("Sequence[object]", value))
        case _:
            return to_string_unknown(value)


def _is_int64(value: int) -> bool:
    return _INT64_MIN <= value <= _INT64_MAX


def _kind(item: object) -> type | None:
    """The attribute kind of an array item (ints and floats are both
    numbers, as in JavaScript), or ``None`` if it cannot be in an array."""
    match item:
        case bool():
            return bool
        case str():
            return str
        case float():
            return float
        case int() if _is_int64(item):
            return float
        case _:
            return None


def _homogeneous(items: Sequence[object]) -> AttributeValue:
    kinds = {_kind(item) for item in items}
    if len(kinds) <= 1 and None not in kinds:
        return cast(AttributeValue, list(items))
    return to_string_unknown(items)


def to_attributes(record: Mapping[str, object]) -> dict[str, AttributeValue]:
    """Each value of ``record`` as an attribute value."""
    return {key: to_attribute_value(value) for key, value in record.items()}
