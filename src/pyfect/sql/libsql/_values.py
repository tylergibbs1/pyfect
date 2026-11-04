"""Statement arguments as libSQL values (``@libsql/client``'s
``valueToSql``): ``bool`` is 0 / 1, integers must fit 64 bits, floats
must be finite, bytes-like values are blobs; anything else is a
``TypeError``."""

from __future__ import annotations

import math
from collections.abc import Sequence

from pyfect.sql.libsql.sdk import Value

_MIN_INTEGER = -(2**63)
_MAX_INTEGER = 2**63 - 1


def to_value(value: object) -> Value:
    match value:
        case None | str() | bytes():
            return value
        case bool():
            return int(value)
        case int():
            if not _MIN_INTEGER <= value <= _MAX_INTEGER:
                raise OverflowError(
                    "integer is too large to be represented as a 64-bit integer "
                    "and passed as argument"
                )
            return value
        case float():
            if not math.isfinite(value):
                raise ValueError(
                    "Only finite numbers (not Infinity or NaN) can be passed as arguments"
                )
            return value
        case bytearray() | memoryview():
            return bytes(value)  # pyright: ignore[reportUnknownArgumentType]
        case _:
            raise TypeError(f"Unsupported type of value: {type(value).__name__}")


def to_values(args: Sequence[object]) -> tuple[Value, ...]:
    return tuple(to_value(arg) for arg in args)


__all__ = ["to_value", "to_values"]
