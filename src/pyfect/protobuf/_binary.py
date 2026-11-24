"""Encodes and decodes message values by their descriptors (Effect's
``protobuf/internal/binary``).

Decoding builds dicts and merges later occurrences into the value already
there; zero values are installed only when a message is made. A final walk
checks required fields and attaches the unknown fields each message kept,
and is skipped when there are neither. Each descriptor's layout (its fields
by number, in number order, its defaults) is worked out once.
"""

from __future__ import annotations

import math
import re
import struct
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Any, Final, NoReturn, cast

from pyfect._digits import is_digits
from pyfect._json_text import quote
from pyfect.protobuf._descriptors import (
    EnumDescriptor,
    EnumValueType,
    ExtensionDescriptor,
    FieldDescriptor,
    ListFieldDescriptor,
    MapFieldDescriptor,
    MessageDescriptor,
    MessageValueType,
    OneofDescriptor,
    ScalarType,
    ScalarValueType,
    SingularFieldDescriptor,
    ValueType,
)
from pyfect.protobuf._wire import WireType
from pyfect.protobuf.reader import ProtobufReader, ProtobufReaderError
from pyfect.protobuf.writer import ProtobufWriter


class UnknownFieldsKey(Enum):
    """The type of ``unknown_fields``, the one key of a message value that is
    not a field name."""

    unknown_fields = "effect/protobuf/ProtobufMessage/unknownFields"

    def __repr__(self) -> str:
        return "unknown_fields"


unknown_fields: Final = UnknownFieldsKey.unknown_fields

type Message = dict[str | UnknownFieldsKey, object]
type _Bytes = bytes | bytearray | memoryview

DEFAULT_MAX_DEPTH: Final = 100
_INT32_MIN: Final = -2147483648
_INT32_MAX: Final = 2147483647
_UINT32_MAX: Final = 4294967295
_FLOAT32_MAX: Final = 3.4028234663852886e38
_INT64_MIN: Final = -(1 << 63)
_INT64_MAX: Final = (1 << 63) - 1
_UINT64_MAX: Final = (1 << 64) - 1
_SAFE_INTEGER: Final = (1 << 53) - 1
_IDENTIFIER = re.compile(r"[A-Za-z_$][A-Za-z0-9_$]*")
_SIXTY_FOUR: Final = frozenset(("int64", "uint64", "sint64", "fixed64", "sfixed64"))
_UNSIGNED: Final = frozenset(("uint32", "fixed32", "uint64", "fixed64"))
_ABSENT: Final = object()


class Failure(Exception):
    """A message failure and its path, raised internally; the public
    functions return it as a ``ProtobufMessageError``."""

    def __init__(self, reason: str, path: list[str | int] | None = None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.path: list[str | int] = [] if path is None else path

    @property
    def message(self) -> str:
        return self.reason if not self.path else f"{format_path(self.path)}: {self.reason}"


def format_path(path: Sequence[str | int]) -> str:
    out = ""
    for key in path:
        if isinstance(key, int):
            out += f"[{key}]"
        elif _IDENTIFIER.fullmatch(key):
            out += key if out == "" else f".{key}"
        else:
            out += f"[{quote(key)}]"
    return out


def _fail(reason: str) -> NoReturn:
    raise Failure(reason)


def _rethrow(error: Exception, key: str | int) -> NoReturn:
    """``error`` with ``key`` before its path; a reader error becomes a failure."""
    if isinstance(error, Failure):
        error.path.insert(0, key)
        raise error
    if isinstance(error, ProtobufReaderError):
        raise Failure(error.message, [key]) from None
    raise error


def _is_decimal(text: str) -> bool:
    """An integer in decimal: ASCII digits after an optional ``-``."""
    return is_digits(text.removeprefix("-"))


def _is_bytes(value: object) -> bool:
    return isinstance(value, (bytes, bytearray, memoryview))


def _is_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _is_integer(value: object) -> bool:
    if isinstance(value, bool):
        return False
    return isinstance(value, int) or (isinstance(value, float) and value.is_integer())


def show(value: object) -> str:
    match value:
        case str():
            return quote(value)
        case bytes() | bytearray() | memoryview():
            return "bytes"
        case list() | tuple():
            return "a list"
        case Mapping():
            return "a dict"
        case bool() | int() | float() | None:
            return repr(value)
        case _:
            return f"a {type(value).__name__}"


def _expected(what: str, value: object) -> NoReturn:
    _fail(f"Expected {what}, got {show(value)}")


def _a(scalar: str) -> str:
    """``"a uint64"``, ``"an int64"``."""
    return f"an {scalar}" if scalar.startswith("int") else f"a {scalar}"


def _depth_limit(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        _fail("Expected max_depth to be a non-negative integer")
    return value


def _check_depth(depth: int, limit: int) -> None:
    if depth > limit:
        _fail(f"Expected messages nested at most {limit} deep")


def _scalar_zero(type: ScalarValueType) -> object:
    match type.scalar:
        case "bool":
            return False
        case "string":
            return ""
        case "bytes":
            return b""
        case "double" | "float":
            return 0.0
        case "int64" | "uint64" | "sint64" | "fixed64" | "sfixed64":
            return 0 if type.js_type == "bigint" else 0.0 if type.js_type == "number" else "0"
        case _:
            return 0


def _wire_type_of(type: ValueType) -> int:
    match type:
        case EnumValueType():
            return WireType.Varint
        case MessageValueType(delimited=delimited):
            return WireType.StartGroup if delimited else WireType.Len
        case ScalarValueType(scalar=scalar):
            if scalar in ("double", "fixed64", "sfixed64"):
                return WireType.I64
            if scalar in ("float", "fixed32", "sfixed32"):
                return WireType.I32
            if scalar in ("string", "bytes"):
                return WireType.Len
            return WireType.Varint


def _packable(type: ValueType) -> bool:
    return isinstance(type, EnumValueType) or (
        isinstance(type, ScalarValueType) and type.scalar not in ("string", "bytes")
    )


def _accepts_enum(descriptor: EnumDescriptor, value: object) -> bool:
    if descriptor.open:
        return True
    numbers = descriptor.numbers
    if numbers is None:
        numbers = frozenset(v.number for v in descriptor.values)
        descriptor.numbers = numbers
    return value in numbers


def _value_default(type: ValueType) -> object:
    match type:
        case MessageValueType():
            return {}
        case EnumValueType(enum=enum):
            return 0 if enum.open else enum.values[0].number
        case ScalarValueType():
            return _scalar_zero(type)


# --- layouts ---------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _ReadField:
    key: str
    wire: int
    packed: bool
    """A repeated field of numbers, booleans or enums, so read in either encoding."""
    field: FieldDescriptor


@dataclass(frozen=True, slots=True)
class _Layout:
    by_number: Mapping[int, _ReadField]
    ordered: tuple[FieldDescriptor, ...]
    oneofs: tuple[tuple[OneofDescriptor, frozenset[str]], ...]
    defaults: tuple[tuple[str, Callable[[], object]], ...]
    finish: tuple[FieldDescriptor, ...]
    """The fields the final walk visits: messages, and required fields."""
    required: bool


def _key(field: FieldDescriptor) -> str:
    return field.name if field.oneof is None else field.oneof.name


def _zero_of(field: FieldDescriptor) -> Callable[[], object]:
    if isinstance(field, ListFieldDescriptor):
        return lambda: []
    if isinstance(field, MapFieldDescriptor):
        return lambda: {}
    zero = _value_default(field.type)
    return lambda: zero


def _layout_of(descriptor: MessageDescriptor) -> _Layout:
    layout = descriptor.layout
    if isinstance(layout, _Layout):
        return layout
    by_number: dict[int, _ReadField] = {}
    defaults: list[tuple[str, Callable[[], object]]] = []
    finish: list[FieldDescriptor] = []
    required = False
    for f in descriptor.fields:
        wire = WireType.Len if isinstance(f, MapFieldDescriptor) else _wire_type_of(f.type)
        packed = isinstance(f, ListFieldDescriptor) and _packable(f.type)
        by_number[f.number] = _ReadField(_key(f), wire, packed, f)
        singular = isinstance(f, SingularFieldDescriptor)
        if f.oneof is None and (
            not isinstance(f, SingularFieldDescriptor)
            or (f.presence == "implicit" and not isinstance(f.type, MessageValueType))
        ):
            defaults.append((f.name, _zero_of(f)))
        is_required = isinstance(f, SingularFieldDescriptor) and f.presence == "required"
        required = required or is_required
        if isinstance(f.type, MessageValueType) or (singular and is_required):
            finish.append(f)
    layout = _Layout(
        by_number,
        tuple(sorted(descriptor.fields, key=lambda f: f.number)),
        tuple((o, frozenset(f.name for f in o.fields)) for o in descriptor.oneofs),
        tuple(defaults),
        tuple(finish),
        required,
    )
    descriptor.layout = layout
    return layout


# --- decoding --------------------------------------------------------------------------------


@dataclass(slots=True)
class _DecodeContext:
    input: _Bytes
    max_depth: int
    keep_unknown: bool
    needs_finish: bool = False
    unknown: dict[int, tuple[Message, list[_Bytes]]] = field(default_factory=lambda: {})
    """The unknown spans of each message, by its id (the message is kept, so its id
    is not reused): a replaced message's spans go with it."""


def _retain(context: _DecodeContext, message: Message, data: _Bytes) -> None:
    if not context.keep_unknown:
        return
    held = context.unknown.get(id(message))
    if held is None:
        context.unknown[id(message)] = (message, [data])
    else:
        held[1].append(data)


def _retain_occurrence(context: _DecodeContext, target: Message, start: int, end: int) -> None:
    if context.keep_unknown:
        _retain(context, target, context.input[start:end])


def _create_message(context: _DecodeContext, layout: _Layout) -> Message:
    target: Message = {key: zero() for key, zero in layout.defaults}
    if layout.required:
        context.needs_finish = True
    return target


def _decode_message(
    descriptor: MessageDescriptor,
    data: _Bytes,
    *,
    read_unknown_fields: bool = True,
    max_depth: object = DEFAULT_MAX_DEPTH,
) -> Message:
    context = _DecodeContext(data, _depth_limit(max_depth), read_unknown_fields)
    target = _read_fields(context, ProtobufReader(data), descriptor, None, 0)
    if context.needs_finish or context.unknown:
        _finish_message(context, descriptor, target)
    return target


def decode(
    descriptor: MessageDescriptor,
    data: _Bytes,
    *,
    read_unknown_fields: bool = True,
    max_depth: object = DEFAULT_MAX_DEPTH,
) -> Message:
    """Raises ``Failure``."""
    try:
        return _decode_message(
            descriptor, data, read_unknown_fields=read_unknown_fields, max_depth=max_depth
        )
    except ProtobufReaderError as error:
        raise Failure(error.message) from None


def _read_fields(  # noqa: PLR0917
    context: _DecodeContext,
    r: ProtobufReader,
    descriptor: MessageDescriptor,
    before: Message | None,
    depth: int,
    group: int | None = None,
) -> Message:
    _check_depth(depth, context.max_depth)
    layout = _layout_of(descriptor)
    target = before if before is not None else _create_message(context, layout)
    fields = layout.by_number
    while True:
        if group is None and r.is_done():
            return target
        start = r.offset
        tag = r.tag()
        number = tag >> 3
        actual = tag & 7
        if actual == WireType.EndGroup:
            if number == group:
                return target
            _fail(f"Expected a start group tag before the end group tag of field {number}")
        entry = fields.get(number)
        packed = actual == WireType.Len and entry is not None and entry.packed
        if entry is None or (actual != entry.wire and not packed):
            r.skip(tag, context.max_depth - depth)
            _retain_occurrence(context, target, start, r.offset)
            continue
        try:
            _read_entry(context, r, entry.field, target, depth, start, packed=packed)
        except (Failure, ProtobufReaderError) as error:
            _rethrow(error, entry.key)


def _read_entry(  # noqa: PLR0917
    context: _DecodeContext,
    r: ProtobufReader,
    f: FieldDescriptor,
    target: Message,
    depth: int,
    start: int,
    *,
    packed: bool,
) -> None:
    match f:
        case SingularFieldDescriptor(type=ScalarValueType() as type) if f.oneof is None:
            target[f.name] = _read_scalar(r, type)
        case SingularFieldDescriptor():
            _read_singular(context, r, f, target, depth, start)
        case ListFieldDescriptor() if packed:
            _read_packed(context, r, target, cast("list[object]", target[f.name]), f)
        case ListFieldDescriptor():
            _read_list(context, r, f, target, depth, start)
        case MapFieldDescriptor():
            _read_map(context, r, f, target, depth, start)


def _read_scalar(r: ProtobufReader, type: ScalarValueType, js_type: str | None = None) -> object:
    js = type.js_type if js_type is None else js_type
    scalar = type.scalar
    if scalar == "string":
        return r.string(validate_utf8=type.validate_utf8)
    if scalar == "bytes":
        return r.bytes()
    if scalar in _SIXTY_FOUR:
        if js == "number":
            return _NUMBER_READERS[scalar](r)
        value = _NUMERIC_READERS[scalar](r)
        return str(value) if js == "string" else value
    return _NUMERIC_READERS[scalar](r)


_NUMERIC_READERS: Final[Mapping[str, Callable[[ProtobufReader], object]]] = {
    "double": ProtobufReader.double,
    "float": ProtobufReader.float,
    "int32": ProtobufReader.int32,
    "uint32": ProtobufReader.uint32,
    "sint32": ProtobufReader.sint32,
    "fixed32": ProtobufReader.fixed32,
    "sfixed32": ProtobufReader.sfixed32,
    "bool": ProtobufReader.bool,
    "int64": ProtobufReader.int64,
    "uint64": ProtobufReader.uint64,
    "sint64": ProtobufReader.sint64,
    "fixed64": ProtobufReader.fixed64,
    "sfixed64": ProtobufReader.sfixed64,
}
_NUMBER_READERS: Final[Mapping[str, Callable[[ProtobufReader], float]]] = {
    "int64": ProtobufReader.int64_number,
    "uint64": ProtobufReader.uint64_number,
    "sint64": ProtobufReader.sint64_number,
    "fixed64": ProtobufReader.fixed64_number,
    "sfixed64": ProtobufReader.sfixed64_number,
}


def _read_value(  # noqa: PLR0917
    context: _DecodeContext,
    r: ProtobufReader,
    type: ValueType,
    number: int,
    before: object,
    depth: int,
) -> object:
    match type:
        case ScalarValueType():
            return _read_scalar(r, type)
        case EnumValueType():
            return r.int32()
        case MessageValueType(message=message, delimited=delimited):
            return _read_fields(
                context,
                r if delimited else r.delimited(),
                message,
                cast("Message | None", before),
                depth + 1,
                number if delimited else None,
            )


def _oneof_value(stored: object, name: str) -> object:
    """The value of a stored oneof whose case is ``name``, else ``None``."""
    if isinstance(stored, dict):
        case = cast("dict[str, object]", stored)
        if case.get("_tag") == name:
            return case.get("value")
    return None


def _read_singular(  # noqa: PLR0917
    context: _DecodeContext,
    r: ProtobufReader,
    f: SingularFieldDescriptor,
    target: Message,
    depth: int,
    start: int,
) -> None:
    key = _key(f)
    before: object = None
    if isinstance(f.type, MessageValueType):
        current = target.get(key)
        before = current if f.oneof is None else _oneof_value(current, f.name)
    value = _read_value(context, r, f.type, f.number, before, depth)
    # Classify the occurrence before changing the active oneof case.
    if isinstance(f.type, EnumValueType) and not _accepts_enum(f.type.enum, value):
        _retain_occurrence(context, target, start, r.offset)
        return
    target[key] = value if f.oneof is None else {"_tag": f.name, "value": value}


def _read_list(  # noqa: PLR0917
    context: _DecodeContext,
    r: ProtobufReader,
    f: ListFieldDescriptor,
    target: Message,
    depth: int,
    start: int,
) -> None:
    items = cast("list[object]", target[f.name])
    try:
        value = _read_value(context, r, f.type, f.number, None, depth)
        if isinstance(f.type, EnumValueType) and not _accepts_enum(f.type.enum, value):
            _retain_occurrence(context, target, start, r.offset)
        else:
            items.append(value)
    except (Failure, ProtobufReaderError) as error:
        _rethrow(error, len(items))


def _read_packed(
    context: _DecodeContext,
    r: ProtobufReader,
    target: Message,
    items: list[object],
    f: ListFieldDescriptor,
) -> None:
    type = f.type
    if isinstance(type, EnumValueType):
        child = r.delimited()
        unknown: ProtobufWriter | None = None
        try:
            while not child.is_done():
                value = child.int32()
                if _accepts_enum(type.enum, value):
                    items.append(value)
                elif context.keep_unknown:
                    unknown = unknown or ProtobufWriter()
                    unknown.tag(f.number, WireType.Varint).int32(value)
        except ProtobufReaderError as error:
            _rethrow(error, len(items))
        if unknown is not None:
            _retain(context, target, unknown.finish())
        return
    scalar = cast("ScalarValueType", type)
    if scalar.scalar in ("double", "float"):
        size = 8 if scalar.scalar == "double" else 4
        data = r.bytes_view()
        if len(data) % size != 0:
            complete = len(data) - len(data) % size
            raise Failure(
                f"Expected a complete value at offset {r.offset - len(data) + complete}",
                [len(items) + complete // size],
            )
        items.extend(v for (v,) in struct.iter_unpack("<d" if size == 8 else "<f", data))
        return
    child = r.delimited()
    try:
        while not child.is_done():
            items.append(_read_scalar(child, scalar))
    except ProtobufReaderError as error:
        _rethrow(error, len(items))


def _map_key_default(type: ScalarValueType) -> str:
    return "" if type.scalar == "string" else "false" if type.scalar == "bool" else "0"


def _map_key(value: object) -> str:
    """A key read from the wire as a string: ``"true"`` / ``"false"``, an integer in decimal."""
    if isinstance(value, bool):
        return "true" if value else "false"
    return value if isinstance(value, str) else str(value)


def _read_map(  # noqa: PLR0917
    context: _DecodeContext,
    r: ProtobufReader,
    f: MapFieldDescriptor,
    target: Message,
    depth: int,
    start: int,
) -> None:
    child = r.delimited()
    key = _map_key_default(f.key)
    value: object = _ABSENT
    key_wire = _wire_type_of(f.key)
    value_wire = _wire_type_of(f.type)
    # The whole entry is read before it replaces any value at its key.
    while not child.is_done():
        tag = child.tag()
        if tag >> 3 == 1 and tag & 7 == key_wire:
            key = _map_key(_read_scalar(child, f.key, "bigint"))
        elif tag >> 3 == 2 and tag & 7 == value_wire:
            try:
                before = None if value is _ABSENT else value
                value = _read_value(context, child, f.type, 2, before, depth)
            except (Failure, ProtobufReaderError) as error:
                _rethrow(error, key)
        else:
            child.skip(tag, context.max_depth - depth)
    value_type = f.type
    if (
        isinstance(value_type, EnumValueType)
        and value is not _ABSENT
        and not _accepts_enum(value_type.enum, value)
    ):
        _retain_occurrence(context, target, start, r.offset)
        return
    if value is _ABSENT:
        if isinstance(f.type, MessageValueType):
            try:
                _check_depth(depth + 1, context.max_depth)
            except Failure as error:
                _rethrow(error, key)
            value = _create_message(context, _layout_of(f.type.message))
        else:
            value = _value_default(f.type)
    cast("dict[str, object]", target[f.name])[key] = value


def _finish_message(  # noqa: PLR0912
    context: _DecodeContext, descriptor: MessageDescriptor, target: Message
) -> None:
    """Completes the surviving values: required fields are checked, and each
    message gets the unknown fields it kept."""
    for f in _layout_of(descriptor).finish:
        key = _key(f)
        stored = target.get(key)
        if f.oneof is not None:
            case = cast("dict[str, object]", stored) if isinstance(stored, dict) else None
            if case is None or case.get("_tag") != f.name:
                continue
            stored = case.get("value")
        try:
            if stored is None:
                if isinstance(f, SingularFieldDescriptor) and f.presence == "required":
                    _fail(f"Expected required field {f.name} of {descriptor.type_name}")
                continue
            if not isinstance(f.type, MessageValueType):
                continue
            message = f.type.message
            match f:
                case SingularFieldDescriptor():
                    _finish_message(context, message, cast("Message", stored))
                case ListFieldDescriptor():
                    for i, item in enumerate(cast("list[Message]", stored)):
                        try:
                            _finish_message(context, message, item)
                        except Failure as error:
                            _rethrow(error, i)
                case MapFieldDescriptor():
                    for entry, item in cast("dict[str, Message]", stored).items():
                        try:
                            _finish_message(context, message, item)
                        except Failure as error:
                            _rethrow(error, entry)
        except Failure as error:
            _rethrow(error, key)
    held = context.unknown.pop(id(target), None)
    if held is not None:
        target[unknown_fields] = b"".join(held[1])


# --- encoding --------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _EncodeContext:
    max_depth: int
    write_unknown: bool


def encode(
    descriptor: MessageDescriptor,
    message: object,
    *,
    write_unknown_fields: bool = True,
    max_depth: object = DEFAULT_MAX_DEPTH,
) -> bytes:
    """Raises ``Failure``."""
    w = ProtobufWriter()
    _write_fields(
        _EncodeContext(_depth_limit(max_depth), write_unknown_fields), w, descriptor, message, 0
    )
    return w.finish()


def _write_fields(
    context: _EncodeContext,
    w: ProtobufWriter,
    descriptor: MessageDescriptor,
    message: object,
    depth: int,
) -> None:
    _check_depth(depth, context.max_depth)
    if not isinstance(message, Mapping):
        _expected(f"an object for {descriptor.type_name}", message)
    target = cast("Mapping[object, object]", message)
    layout = _layout_of(descriptor)
    for oneof, cases in layout.oneofs:
        value = target.get(oneof.name)
        if value is None:
            continue
        case = cast("Mapping[str, object]", value) if isinstance(value, Mapping) else None
        tag = None if case is None else case.get("_tag")
        if tag not in cases:
            shown = show(cast("object", value) if tag is None else tag)
            raise Failure(f"Expected a case of oneof {oneof.name}, got {shown}", [oneof.name])
    for f in layout.ordered:
        try:
            _write_field(context, w, f, target, depth)
        except Failure as error:
            _rethrow(error, _key(f))
    if context.write_unknown:
        unknown = target.get(unknown_fields)
        if unknown is not None:
            if not _is_bytes(unknown):
                _expected("bytes of unknown fields", unknown)
            w.raw(cast("_Bytes", unknown))


def _write_field(  # noqa: PLR0912
    context: _EncodeContext,
    w: ProtobufWriter,
    f: FieldDescriptor,
    target: Mapping[object, object],
    depth: int,
) -> None:
    stored = target.get(_key(f))
    if f.oneof is not None:
        case = cast("Mapping[str, object]", stored) if isinstance(stored, Mapping) else None
        if case is None or case.get("_tag") != f.name:
            return
        value = case.get("value")
    else:
        value = stored
        if value is None:
            if isinstance(f, SingularFieldDescriptor) and f.presence == "required":
                _fail(f"Expected a value for required field {f.name}")
            return
    match f:
        case SingularFieldDescriptor():
            if f.presence != "implicit" or not _is_zero(f.type, value):
                _write_value(context, w, f.type, f.number, value, depth)
        case ListFieldDescriptor():
            if not isinstance(value, (list, tuple)):
                _expected("a list", value)
            items = cast("Sequence[object]", value)
            if not items:
                return
            if f.packed and _packable(f.type):
                _write_packed(w, f.type, f.number, items)
                return
            for i, item in enumerate(items):
                try:
                    _write_value(context, w, f.type, f.number, item, depth)
                except Failure as error:
                    _rethrow(error, i)
        case MapFieldDescriptor():
            if not isinstance(value, Mapping):
                _expected("a dict", value)
            for key, item in cast("Mapping[object, object]", value).items():
                try:
                    w.tag(f.number, WireType.Len).fork()
                    _write_map_key(w, f.key, key)
                    _write_value(context, w, f.type, 2, item, depth)
                    w.join()
                except Failure as error:
                    _rethrow(error, key if isinstance(key, (str, int)) else show(key))


def _write_value(  # noqa: PLR0917
    context: _EncodeContext,
    w: ProtobufWriter,
    type: ValueType,
    number: int,
    value: object,
    depth: int,
) -> None:
    tag = number * 8 + _wire_type_of(type)
    match type:
        case ScalarValueType(scalar=scalar):
            w.uint32(tag)
            _SCALAR_WRITERS[scalar](w, value)
        case EnumValueType():
            w.uint32(tag)
            _write_enum(w, type, value)
        case MessageValueType(message=message, delimited=True):
            w.uint32(tag)
            _write_fields(context, w, message, value, depth + 1)
            w.uint32(number * 8 + WireType.EndGroup)
        case MessageValueType(message=message):
            w.uint32(tag).fork()
            _write_fields(context, w, message, value, depth + 1)
            w.join()


def _is_zero(type: ValueType, value: object) -> bool:  # noqa: PLR0911
    match type:
        case MessageValueType():
            return False
        case EnumValueType():
            return _is_number(value) and value == _value_default(type)
        case ScalarValueType(scalar=scalar):
            if scalar in ("double", "float"):
                return (
                    _is_number(value) and value == 0 and math.copysign(1, cast("float", value)) > 0
                )
            if scalar == "bool":
                return value is False
            if scalar == "string":
                return value == ""
            if scalar == "bytes":
                return _is_bytes(value) and len(cast("_Bytes", value)) == 0
            if scalar in _SIXTY_FOUR and value == "0":
                return True
            return _is_number(value) and value == 0


def _int32(scalar: str, value: object) -> int:
    if _is_integer(value) and _INT32_MIN <= cast("float", value) <= _INT32_MAX:
        return int(cast("float", value))
    _expected(f"an integer for {_a(scalar)}", value)


def _uint32(scalar: str, value: object) -> int:
    if _is_integer(value) and 0 <= cast("float", value) <= _UINT32_MAX:
        return int(cast("float", value))
    _expected(f"a non-negative integer for {_a(scalar)}", value)


def _float(value: object) -> float:
    if _is_number(value):
        number = float(cast("float", value))
        if not (math.isfinite(number) and abs(number) > _FLOAT32_MAX):
            return number
    _expected("a number in the range of a float", value)


def _double(value: object) -> float:
    if _is_number(value):
        return float(cast("float", value))
    _expected("a number for a double", value)


def _out_of_range(scalar: str, value: object) -> NoReturn:
    _expected(f"{_a(scalar)} in range", value)


def _to_int64(scalar: str, value: object) -> int:
    """A 64-bit integer given as an ``int``, an integral ``float`` or a decimal
    ``str``, in the range of ``scalar``."""
    unsigned = scalar in _UNSIGNED
    if isinstance(value, bool):
        _expected(f"an integer or decimal string for {_a(scalar)}", value)
    if isinstance(value, float):
        if not value.is_integer():
            _expected(f"an integer for {_a(scalar)}", value)
        n = int(value)
    elif isinstance(value, int):
        n = value
    elif isinstance(value, str) and _is_decimal(value):
        if len(value) > 21:
            _out_of_range(scalar, value)
        n = int(value)
    else:
        _expected(f"an integer or decimal string for {_a(scalar)}", value)
    in_range = 0 <= n <= _UINT64_MAX if unsigned else _INT64_MIN <= n <= _INT64_MAX
    if not in_range:
        _out_of_range(scalar, value)
    return n


def _write_string(w: ProtobufWriter, value: object) -> None:
    if not isinstance(value, str):
        _expected("a string", value)
    w.string(value)


def _write_bytes(w: ProtobufWriter, value: object) -> None:
    if not _is_bytes(value):
        _expected("bytes", value)
    w.bytes(cast("_Bytes", value))


def _write_bool(w: ProtobufWriter, value: object) -> None:
    if not isinstance(value, bool):
        _expected("a boolean", value)
    w.bool(value)


_SCALAR_WRITERS: Final[Mapping[ScalarType, Callable[[ProtobufWriter, object], object]]] = {
    "string": _write_string,
    "bytes": _write_bytes,
    "double": lambda w, v: w.double(_double(v)),
    "float": lambda w, v: w.float(_float(v)),
    "int32": lambda w, v: w.int32(_int32("int32", v)),
    "uint32": lambda w, v: w.uint32(_uint32("uint32", v)),
    "sint32": lambda w, v: w.sint32(_int32("sint32", v)),
    "fixed32": lambda w, v: w.fixed32(_uint32("fixed32", v)),
    "sfixed32": lambda w, v: w.sfixed32(_int32("sfixed32", v)),
    "bool": _write_bool,
    "int64": lambda w, v: w.int64(_to_int64("int64", v)),
    "uint64": lambda w, v: w.uint64(_to_int64("uint64", v)),
    "sint64": lambda w, v: w.sint64(_to_int64("sint64", v)),
    "fixed64": lambda w, v: w.fixed64(_to_int64("fixed64", v)),
    "sfixed64": lambda w, v: w.sfixed64(_to_int64("sfixed64", v)),
}


def _write_enum(w: ProtobufWriter, type: EnumValueType, value: object) -> None:
    number = _int32("int32", value)
    if not _accepts_enum(type.enum, number):
        _expected(f"a value of {type.enum.type_name}", value)
    w.int32(number)


def _write_packed(w: ProtobufWriter, type: ValueType, number: int, items: Sequence[object]) -> None:
    w.tag(number, WireType.Len)
    wire = _wire_type_of(type)
    size = 8 if wire == WireType.I64 else 4 if wire == WireType.I32 else 0
    if size == 0:
        w.fork()
        _write_packed_values(w, type, items)
        w.join()
        return
    length = len(items) * size
    if length > _UINT32_MAX:
        _fail("Expected a packed field length of at most 4294967295 bytes")
    w.uint32(length)
    if not (isinstance(type, ScalarValueType) and type.scalar in ("double", "float")):
        _write_packed_values(w, type, items)
        return
    double = type.scalar == "double"
    for i, item in enumerate(items):
        try:
            if double:
                w.double(_double(item))
            else:
                w.float(_float(item))
        except Failure as error:
            _rethrow(error, i)


def _write_packed_values(w: ProtobufWriter, type: ValueType, items: Sequence[object]) -> None:
    for i, item in enumerate(items):
        try:
            if isinstance(type, EnumValueType):
                _write_enum(w, type, item)
            else:
                _SCALAR_WRITERS[cast("ScalarValueType", type).scalar](w, item)
        except Failure as error:
            _rethrow(error, i)


def _write_map_key(w: ProtobufWriter, type: ScalarValueType, key: object) -> None:
    w.tag(1, _wire_type_of(type))
    if not isinstance(key, str):
        _expected("a string key", key)
    match type.scalar:
        case "string":
            w.string(key)
        case "bool":
            if key not in ("true", "false"):
                _expected("a boolean key", key)
            w.bool(key == "true")
        case scalar:
            if not _is_decimal(key):
                _expected(f"an integer key for {_a(scalar)}", key)
            value: object = key if scalar in _SIXTY_FOUR or len(key) > 20 else int(key)
            _SCALAR_WRITERS[scalar](w, value)


# --- extensions ------------------------------------------------------------------------------

# A MessageSet item: `repeated group Item = 1 { required int32 type_id = 2;
# required bytes message = 3; }`.
_ITEM_START: Final = 1 * 8 + WireType.StartGroup
_ITEM_END: Final = 1 * 8 + WireType.EndGroup
_ITEM_TYPE_ID: Final = 2 * 8 + WireType.Varint
_ITEM_MESSAGE: Final = 3 * 8 + WireType.Len


@dataclass(frozen=True, slots=True)
class _Split:
    own: list[_Bytes]
    rest: list[_Bytes]


def _unknown_of(message: object) -> object:
    if not isinstance(message, Mapping):
        _expected("an object", message)
    return cast("Mapping[object, object]", message).get(unknown_fields)


def _split_extension(message: object, extension: ExtensionDescriptor) -> _Split:
    """The unknown fields of ``message``: the occurrences of ``extension`` and
    the rest. MessageSet occurrences are bare payloads; ordinary ones keep
    their tags, to decode into a holder."""
    data = _unknown_of(message)
    out = _Split([], [])
    if data is None:
        return out
    if not _is_bytes(data):
        _expected("bytes of unknown fields", data)
    view = cast("_Bytes", data)
    number = extension.field.number
    message_set = extension.extendee.message_set_wire_format
    r = ProtobufReader(view)
    while not r.is_done():
        start = r.offset
        tag = r.tag()
        if message_set and tag == _ITEM_START:
            payload = _read_item(r, number)
            if payload is None:
                out.rest.append(view[start : r.offset])
            else:
                out.own.append(payload)
            continue
        # MessageSet also accepts ordinary length-delimited extension fields. Both forms
        # are kept as bare payloads: its id may be past the range of tags.
        if message_set and tag >> 3 == number and tag & 7 == WireType.Len:
            out.own.append(r.bytes_view())
            continue
        r.skip(tag)
        # A field of an incompatible wire type stays unknown when the extension is set
        # or cleared, as it does when a message is decoded.
        type = extension.field.type
        actual = tag & 7
        packed = (
            isinstance(extension.field, ListFieldDescriptor)
            and actual == WireType.Len
            and _packable(type)
        )
        matches = (
            not message_set and tag >> 3 == number and (actual == _wire_type_of(type) or packed)
        )
        (out.own if matches else out.rest).append(view[start : r.offset])
    return out


def _read_item(r: ProtobufReader, type_id: int) -> _Bytes | None:
    """The rest of a MessageSet item after its start tag: its payload when its
    type id is ``type_id``. Only the first type id and payload count; an
    incomplete item sets no extension."""
    found: int | None = None
    payload: _Bytes | None = None
    while True:
        tag = r.tag()
        if tag == _ITEM_END:
            break
        if tag == _ITEM_TYPE_ID:
            value = r.uint32()
            if value == 0:
                _fail("Expected a nonzero MessageSet type id")
            found = value if found is None else found
        elif tag == _ITEM_MESSAGE:
            value = r.bytes_view()
            payload = value if payload is None else payload
        else:
            r.skip(tag)
    return payload if found == type_id else None


def _holder_of(extension: ExtensionDescriptor) -> MessageDescriptor:
    """A message of one field, an ordinary extension, its occurrences decode into."""
    descriptor = extension.holder
    if descriptor is None:
        descriptor = replace(extension.extendee, fields=[extension.field], oneofs=[])
        extension.holder = descriptor
    return descriptor


def _read_extension(extension: ExtensionDescriptor, occurrences: Sequence[_Bytes]) -> Message:
    return _decode_message(_holder_of(extension), b"".join(occurrences))


def _message_set_descriptor(extension: ExtensionDescriptor) -> MessageDescriptor:
    f = extension.field
    if not isinstance(f, SingularFieldDescriptor) or not isinstance(f.type, MessageValueType):
        _fail("Expected a singular message extension of a MessageSet")
    return f.type.message


def _read_message_set(extension: ExtensionDescriptor, occurrences: Sequence[_Bytes]) -> Message:
    """Merges at least one payload. Each reader is bounded to its occurrence;
    the merged value and its unknown fields last until the final walk."""
    descriptor = _message_set_descriptor(extension)
    context = _DecodeContext(occurrences[0], DEFAULT_MAX_DEPTH, True)
    target = _create_message(context, _layout_of(descriptor))
    for occurrence in occurrences:
        context.input = occurrence
        # The payload is nested one level inside the extended message.
        _read_fields(context, ProtobufReader(context.input), descriptor, target, 1)
    if context.needs_finish or context.unknown:
        _finish_message(context, descriptor, target)
    return target


def get_extension(message: object, extension: ExtensionDescriptor) -> object:
    """Raises ``Failure``."""
    try:
        own = _split_extension(message, extension).own
        f = extension.field
        if not own:
            return [] if isinstance(f, ListFieldDescriptor) else None
        if extension.extendee.message_set_wire_format:
            try:
                return _read_message_set(extension, own)
            except (Failure, ProtobufReaderError) as error:
                _rethrow(error, f.name)
        return _read_extension(extension, own).get(f.name)
    except ProtobufReaderError as error:
        raise Failure(error.message) from None


def set_extension(message: object, extension: ExtensionDescriptor, value: object) -> Message:
    """Raises ``Failure``."""
    try:
        return _set_extension(message, extension, value)
    except ProtobufReaderError as error:
        raise Failure(error.message) from None


def _set_extension(message: object, extension: ExtensionDescriptor, value: object) -> Message:
    split = _split_extension(message, extension)
    chunks: list[_Bytes] = list(split.rest)
    # Closed-enum numbers outside the descriptor are unknown data, even when they
    # share the extension's field number or a packed occurrence.
    type = extension.field.type
    if split.own and isinstance(type, EnumValueType) and not type.enum.open:
        unknown = _read_extension(extension, split.own).get(unknown_fields)
        if unknown is not None:
            chunks.append(cast("bytes", unknown))
    if value is not None:
        w = ProtobufWriter()
        context = _EncodeContext(DEFAULT_MAX_DEPTH, write_unknown=True)
        if extension.extendee.message_set_wire_format:
            w.tag(1, WireType.StartGroup).tag(2, WireType.Varint).uint32(
                extension.field.number
            ).tag(3, WireType.Len).fork()
            try:
                _write_fields(context, w, _message_set_descriptor(extension), value, 1)
            except Failure as error:
                _rethrow(error, extension.field.name)
            w.join().tag(1, WireType.EndGroup)
        else:
            holder = _holder_of(extension)
            _write_fields(context, w, holder, {extension.field.name: value}, 0)
        chunks.append(w.finish())
    out: Message = dict(cast("Mapping[str | UnknownFieldsKey, object]", message))
    if chunks:
        out[unknown_fields] = b"".join(chunks)
    else:
        out.pop(unknown_fields, None)
    return out


__all__ = [
    "DEFAULT_MAX_DEPTH",
    "Failure",
    "Message",
    "UnknownFieldsKey",
    "decode",
    "encode",
    "get_extension",
    "set_extension",
    "unknown_fields",
]

_ = Any
