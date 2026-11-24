"""Encodes and decodes protobuf messages by their descriptors (Effect's
``protobuf/ProtobufMessage``).

A message value is a ``dict`` keyed by field names, as ``.proto`` files spell
them. A oneof is one key, the oneof's name, holding ``{"_tag": field,
"value": value}``. A map's keys are strings (``"true"``, ``"42"``). A 64-bit
integer is an ``int``, or a ``float`` or a decimal ``str`` when its field's
``jstype`` asks. Decoding keeps the fields it does not know as bytes under
``unknown_fields``, and encoding writes them back.

The bytes ``decode`` reads are untrusted: messages nest at most ``max_depth``
deep (100 by default), and ``max_size`` bounds the input's length.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

from pyfect._public import publish
from pyfect.errors import TaggedError
from pyfect.protobuf import _binary
from pyfect.protobuf._binary import DEFAULT_MAX_DEPTH, Message, UnknownFieldsKey, unknown_fields
from pyfect.protobuf._descriptors import ExtensionDescriptor, MessageDescriptor
from pyfect.result import Err, Ok, Result

type _Bytes = bytes | bytearray | memoryview


@dataclass(eq=False)
class ProtobufMessageError(TaggedError):
    """A message that does not decode or encode. ``path`` leads to the value
    that failed: field names, list indexes and map keys."""

    message: str
    path: Sequence[str | int]


def _error(failure: _binary.Failure) -> Err[ProtobufMessageError]:
    return Err(ProtobufMessageError(failure.message, tuple(failure.path)))


def decode(
    descriptor: MessageDescriptor,
    *,
    read_unknown_fields: bool = True,
    max_depth: int = DEFAULT_MAX_DEPTH,
    max_size: int | None = None,
) -> Callable[[_Bytes], Result[Message, ProtobufMessageError]]:
    """A decoder of messages of ``descriptor``. With ``read_unknown_fields=False``
    unknown fields are dropped; ``max_size`` fails input longer than that many
    bytes."""

    def run(data: _Bytes) -> Result[Message, ProtobufMessageError]:
        if max_size is not None and len(data) > max_size:
            return Err(
                ProtobufMessageError(f"Expected at most {max_size} bytes, got {len(data)}", ())
            )
        try:
            return Ok(
                _binary.decode(
                    descriptor, data, read_unknown_fields=read_unknown_fields, max_depth=max_depth
                )
            )
        except _binary.Failure as failure:
            return _error(failure)

    return run


def encode(
    descriptor: MessageDescriptor,
    *,
    write_unknown_fields: bool = True,
    max_depth: int = DEFAULT_MAX_DEPTH,
) -> Callable[[Mapping[str, object]], Result[bytes, ProtobufMessageError]]:
    """An encoder of messages of ``descriptor``, writing fields in number order."""

    def run(message: Mapping[str, object]) -> Result[bytes, ProtobufMessageError]:
        try:
            return Ok(
                _binary.encode(
                    descriptor,
                    message,
                    write_unknown_fields=write_unknown_fields,
                    max_depth=max_depth,
                )
            )
        except _binary.Failure as failure:
            return _error(failure)

    return run


def get_extension(
    message: Mapping[str, object], extension: ExtensionDescriptor
) -> Result[object, ProtobufMessageError]:
    """The value of ``extension``, read from the unknown fields of ``message``:
    ``None`` (or ``[]`` for a repeated extension) when it is not set."""
    try:
        return Ok(_binary.get_extension(message, extension))
    except _binary.Failure as failure:
        return _error(failure)


def set_extension(
    message: Mapping[str, object], extension: ExtensionDescriptor, value: object
) -> Result[Message, ProtobufMessageError]:
    """A copy of ``message`` with ``extension`` set to ``value`` in its unknown
    fields, or cleared when ``value`` is ``None``."""
    try:
        return Ok(_binary.set_extension(message, extension, value))
    except _binary.Failure as failure:
        return _error(failure)


__all__ = [
    "Message",
    "ProtobufMessageError",
    "UnknownFieldsKey",
    "decode",
    "encode",
    "get_extension",
    "set_extension",
    "unknown_fields",
]

publish(globals())
