"""Reading the columns the SQL stores select: drivers type a row's values
as ``object``."""

from __future__ import annotations

from typing import cast


def column_int(value: object) -> int:
    """A count or a small integer column (some drivers give ``Decimal`` or
    text for ``COUNT(*)``)."""
    return value if isinstance(value, int) else int(str(value))


def column_bytes(value: object) -> bytes:
    """A ``BLOB`` / ``BYTEA`` column."""
    match value:
        case bytes():
            return value
        case bytearray() | memoryview():
            return bytes(cast("bytearray", value))
        case _:
            raise TypeError(f"expected a binary column value, got {type(value).__name__}")


def column_text(value: object) -> str:
    """A text column, or a ``VARBINARY`` one holding UTF-8 (a MySQL key)."""
    match value:
        case bytes() | bytearray() | memoryview():
            return bytes(cast("bytes", value)).decode()
        case _:
            return str(value)
