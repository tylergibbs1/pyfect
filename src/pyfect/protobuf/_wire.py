"""The wire types of protobuf tags, shared by the reader and the writer."""

from __future__ import annotations

from enum import IntEnum


class WireType(IntEnum):
    """The low three bits of a tag: how its field's value is written."""

    Varint = 0
    I64 = 1
    Len = 2
    StartGroup = 3
    EndGroup = 4
    I32 = 5
