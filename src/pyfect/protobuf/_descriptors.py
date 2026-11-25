"""The resolved descriptors that ``descriptor`` makes and ``message`` reads.

They refer to each other (a field to its message, a message to its file), so
``_resolve`` builds them in two passes and they compare by identity.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from dataclasses import field as dataclass_field
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from pyfect.protobuf.descriptor_proto import (
        DescriptorProto,
        EnumDescriptorProto,
        EnumValueDescriptorProto,
        FieldDescriptorProto,
        FileDescriptorProto,
        MethodDescriptorProto,
        OneofDescriptorProto,
        ServiceDescriptorProto,
    )

type EditionName = Literal["proto2", "proto3", "2023", "2024", "2026"]
"""The editions resolved. proto2 and proto3 files are the editions of their syntax."""

type ScalarType = Literal[
    "double",
    "float",
    "int64",
    "uint64",
    "int32",
    "fixed64",
    "fixed32",
    "bool",
    "string",
    "bytes",
    "uint32",
    "sfixed32",
    "sfixed64",
    "sint32",
    "sint64",
]

type JsType = Literal["bigint", "number", "string"]
"""How a 64-bit integer value is held, as ``[jstype = ...]`` asks: an ``int``
(Effect's ``bigint``), a ``float`` (``JS_NUMBER``) or a decimal ``str``
(``JS_STRING``)."""

type Presence = Literal["implicit", "explicit", "required"]
"""When a singular field is present: ``"implicit"`` when not its zero value
(proto3 without ``optional``), ``"explicit"`` when set, even to its zero
value, ``"required"`` always (proto2 ``required``)."""


@dataclass(frozen=True, slots=True)
class ScalarValueType:
    """A scalar value. ``js_type`` applies to 64-bit integers, ``validate_utf8``
    to strings."""

    scalar: ScalarType
    js_type: JsType
    validate_utf8: bool
    kind: Literal["scalar"] = "scalar"


@dataclass(frozen=True, slots=True, eq=False)
class EnumValueType:
    """An enum value, held as its number."""

    enum: EnumDescriptor
    kind: Literal["enum"] = "enum"


@dataclass(frozen=True, slots=True, eq=False)
class MessageValueType:
    """A message value; a ``delimited`` one is written as a group."""

    message: MessageDescriptor
    delimited: bool
    kind: Literal["message"] = "message"


type ValueType = ScalarValueType | EnumValueType | MessageValueType
"""The type of a singular field's value, a list's elements or a map's values."""


@dataclass(eq=False, repr=False)
class FileDescriptor:
    """A resolved ``.proto`` file."""

    name: str
    package: str
    edition: EditionName
    dependencies: Sequence[FileDescriptor]
    proto: FileDescriptorProto
    messages: list[MessageDescriptor] = field(default_factory=lambda: [])
    enums: list[EnumDescriptor] = field(default_factory=lambda: [])
    extensions: list[ExtensionDescriptor] = field(default_factory=lambda: [])
    services: list[ServiceDescriptor] = field(default_factory=lambda: [])

    def __repr__(self) -> str:
        return f"FileDescriptor({self.name!r})"


@dataclass(eq=False, repr=False)
class MessageDescriptor:
    """A message type. ``fields`` are in declaration order. Map entry
    messages are not among ``messages``: their map field describes them."""

    type_name: str
    name: str
    file: FileDescriptor
    parent: MessageDescriptor | None
    message_set_wire_format: bool
    """Whether its extensions are written as MessageSet items."""
    proto: DescriptorProto
    fields: list[FieldDescriptor] = field(default_factory=lambda: [])
    oneofs: list[OneofDescriptor] = field(default_factory=lambda: [])
    messages: list[MessageDescriptor] = field(default_factory=lambda: [])
    enums: list[EnumDescriptor] = field(default_factory=lambda: [])
    extensions: list[ExtensionDescriptor] = field(default_factory=lambda: [])
    layout: object = field(default=None, init=False)
    """``message``'s layout of the fields, worked out on first use."""

    def __repr__(self) -> str:
        return f"MessageDescriptor({self.type_name!r})"


@dataclass(frozen=True, eq=False, repr=False)
class _Field:
    name: str
    """The key of the field in a message value: its protobuf name, unchanged."""
    number: int
    parent: MessageDescriptor
    """The message the field belongs to, or the one an extension extends."""
    oneof: OneofDescriptor | None
    proto: FieldDescriptorProto

    def __repr__(self) -> str:
        return f"{type(self).__name__}({self.parent.type_name}.{self.name})"


@dataclass(frozen=True, eq=False, repr=False)
class SingularFieldDescriptor(_Field):
    """A field of one value, present as its ``presence`` says."""

    type: ValueType
    presence: Presence
    kind: Literal["singular"] = "singular"


@dataclass(frozen=True, eq=False, repr=False)
class ListFieldDescriptor(_Field):
    """A repeated field. ``packed`` decides how number, boolean and enum
    elements are written; both encodings are read."""

    type: ValueType
    packed: bool
    kind: Literal["list"] = "list"


@dataclass(frozen=True, eq=False, repr=False)
class MapFieldDescriptor(_Field):
    """A map field. ``key`` is a scalar other than a float, double or bytes."""

    key: ScalarValueType
    type: ValueType
    kind: Literal["map"] = "map"


type FieldDescriptor = SingularFieldDescriptor | ListFieldDescriptor | MapFieldDescriptor


@dataclass(eq=False, repr=False)
class OneofDescriptor:
    """A oneof. The synthetic oneofs of proto3 ``optional`` fields are not
    oneofs here: those fields have explicit presence."""

    name: str
    parent: MessageDescriptor
    proto: OneofDescriptorProto
    fields: list[FieldDescriptor] = field(default_factory=lambda: [])

    def __repr__(self) -> str:
        return f"OneofDescriptor({self.parent.type_name}.{self.name})"


@dataclass(eq=False, repr=False)
class EnumDescriptor:
    """An enum. An open enum holds any number; a closed one only its values,
    and decoding keeps other numbers as unknown fields."""

    type_name: str
    name: str
    file: FileDescriptor
    parent: MessageDescriptor | None
    open: bool
    proto: EnumDescriptorProto
    values: list[EnumValueDescriptor] = field(default_factory=lambda: [])
    numbers: frozenset[int] | None = field(default=None, init=False)
    """The numbers of ``values``, worked out on first use."""

    def __repr__(self) -> str:
        return f"EnumDescriptor({self.type_name!r})"


@dataclass(frozen=True, eq=False, repr=False)
class EnumValueDescriptor:
    """A resolved protobuf enum value: its name, number and enum."""

    name: str
    number: int
    parent: EnumDescriptor
    proto: EnumValueDescriptorProto

    def __repr__(self) -> str:
        return f"EnumValueDescriptor({self.parent.type_name}.{self.name})"


@dataclass(eq=False, repr=False)
class ExtensionDescriptor:
    """A field of ``extendee`` declared outside of it."""

    type_name: str
    name: str
    file: FileDescriptor
    parent: MessageDescriptor | None
    """The message the extension is declared in, if any."""
    extendee: MessageDescriptor
    field: SingularFieldDescriptor | ListFieldDescriptor
    proto: FieldDescriptorProto
    holder: MessageDescriptor | None = dataclass_field(default=None, init=False)
    """A message of ``field`` alone, which ``message`` decodes occurrences into."""

    def __repr__(self) -> str:
        return f"ExtensionDescriptor({self.type_name!r})"


@dataclass(eq=False, repr=False)
class ServiceDescriptor:
    """A resolved protobuf service: its name, file and methods."""

    type_name: str
    name: str
    file: FileDescriptor
    proto: ServiceDescriptorProto
    methods: list[MethodDescriptor] = field(default_factory=lambda: [])

    def __repr__(self) -> str:
        return f"ServiceDescriptor({self.type_name!r})"


@dataclass(frozen=True, eq=False, repr=False)
class MethodDescriptor:
    """A resolved protobuf service method: input and output messages and streaming."""

    name: str
    parent: ServiceDescriptor
    input: MessageDescriptor
    output: MessageDescriptor
    client_streaming: bool
    server_streaming: bool
    idempotency: Literal["unknown", "noSideEffects", "idempotent"]
    proto: MethodDescriptorProto

    def __repr__(self) -> str:
        return f"MethodDescriptor({self.parent.type_name}.{self.name})"


@dataclass(frozen=True, eq=False, repr=False)
class Registry:
    """The resolved files of a set of ``.proto`` files, and their types by
    full name, such as ``"acme.v1.User"``."""

    files: Sequence[FileDescriptor]
    _files: dict[str, FileDescriptor]
    _messages: dict[str, MessageDescriptor]
    _enums: dict[str, EnumDescriptor]
    _services: dict[str, ServiceDescriptor]
    _extensions: dict[str, ExtensionDescriptor]
    _by_extendee: dict[str, dict[int, ExtensionDescriptor]]

    def get_file(self, name: str) -> FileDescriptor | None:
        return self._files.get(name)

    def get_message(self, type_name: str) -> MessageDescriptor | None:
        return self._messages.get(type_name)

    def get_enum(self, type_name: str) -> EnumDescriptor | None:
        return self._enums.get(type_name)

    def get_service(self, type_name: str) -> ServiceDescriptor | None:
        return self._services.get(type_name)

    def get_extension(self, type_name: str) -> ExtensionDescriptor | None:
        return self._extensions.get(type_name)

    def find_extension(self, extendee: str, number: int) -> ExtensionDescriptor | None:
        """The extension of ``extendee`` (a full name) with field ``number``."""
        return self._by_extendee.get(extendee, {}).get(number)

    def __repr__(self) -> str:
        return f"Registry({', '.join(file.name for file in self.files)})"
