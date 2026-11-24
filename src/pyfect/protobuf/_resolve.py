"""Resolves ``FileDescriptorProto`` s into descriptors: types by full name,
field kinds, and the features of each file's syntax or edition applied to
every field and enum (Effect's ``protobuf/internal/resolve``).

Descriptors refer to each other, so they are built in two passes: first
every message and enum, by full name, then the fields, extensions and
services that refer to them.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any, Final, Literal, NoReturn

from pyfect.protobuf._descriptors import (
    EditionName,
    EnumDescriptor,
    EnumValueDescriptor,
    EnumValueType,
    ExtensionDescriptor,
    FieldDescriptor,
    FileDescriptor,
    ListFieldDescriptor,
    MapFieldDescriptor,
    MessageDescriptor,
    MessageValueType,
    MethodDescriptor,
    OneofDescriptor,
    Presence,
    Registry,
    ScalarType,
    ScalarValueType,
    ServiceDescriptor,
    SingularFieldDescriptor,
    ValueType,
)

if TYPE_CHECKING:
    from pyfect.protobuf.descriptor_proto import (
        DescriptorProto,
        EnumDescriptorProto,
        FieldDescriptorProto,
        FileDescriptorProto,
    )


class ResolveError(Exception):
    """Descriptors that do not resolve; ``descriptor.make`` returns it as a
    ``ProtobufDescriptorError``."""


def _fail(message: str) -> NoReturn:
    raise ResolveError(message)


# --- features --------------------------------------------------------------------------------

_EDITION_2023: Final = 1000
_EDITION_2024: Final = 1001
_EDITION_2026: Final = 1002

_LABEL_OPTIONAL: Final = 1
_LABEL_REQUIRED: Final = 2
_LABEL_REPEATED: Final = 3
_TYPE_GROUP: Final = 10
_TYPE_MESSAGE: Final = 11
_TYPE_ENUM: Final = 14
_MAX_FIELD_NUMBER: Final = 536870911
_MAX_MESSAGE_SET_NUMBER: Final = 2147483646

_SCALARS: Final[Mapping[int, ScalarType]] = {
    1: "double",
    2: "float",
    3: "int64",
    4: "uint64",
    5: "int32",
    6: "fixed64",
    7: "fixed32",
    8: "bool",
    9: "string",
    12: "bytes",
    13: "uint32",
    15: "sfixed32",
    16: "sfixed64",
    17: "sint32",
    18: "sint64",
}


@dataclass(frozen=True, slots=True)
class _Features:
    """The resolved features that decide how fields are encoded."""

    field_presence: Presence
    enum_type: Literal["open", "closed"]
    repeated_field_encoding: Literal["packed", "expanded"]
    utf8_validation: bool
    delimited: bool


# The `edition_defaults` of the features in descriptor.proto.
_PROTO2: Final = _Features("explicit", "closed", "expanded", utf8_validation=False, delimited=False)
_PROTO3: Final = _Features("implicit", "open", "packed", utf8_validation=True, delimited=False)
# Editions 2023, 2024 and 2026 share these binary defaults. Naming, visibility and
# definition-size features have source retention and are enforced by protoc.
_EDITIONS: Final = _Features("explicit", "open", "packed", utf8_validation=True, delimited=False)


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _edition_of(file: FileDescriptorProto) -> EditionName:
    syntax = file.get("syntax")
    name = file.get("name")
    match syntax:
        case None | "" | "proto2":
            return "proto2"
        case "proto3":
            return "proto3"
        case "editions":
            edition = file.get("edition")
            if edition == _EDITION_2023:
                return "2023"
            if edition == _EDITION_2024:
                return "2024"
            if edition == _EDITION_2026:
                return "2026"
            _fail(f"{name}: edition {edition} is not supported")
        case _:
            _fail(f"{name}: syntax {syntax} is not supported")


def _merge(features: _Features, options: Mapping[str, Any] | None) -> _Features:
    """``features`` with those that ``options`` ' ``FeatureSet`` sets (each a
    number of its enum in descriptor.proto; 0 is unset)."""
    feature_set: Mapping[str, Any] | None = None if options is None else options.get("features")
    if feature_set is None:
        return features
    presence = feature_set.get("field_presence")
    enum_type = feature_set.get("enum_type")
    encoding = feature_set.get("repeated_field_encoding")
    utf8 = feature_set.get("utf8_validation")
    message = feature_set.get("message_encoding")
    presences: dict[object, Presence] = {1: "explicit", 2: "implicit", 3: "required"}
    return _Features(
        presences.get(presence, features.field_presence),
        "open" if enum_type == 1 else "closed" if enum_type == 2 else features.enum_type,
        "packed"
        if encoding == 1
        else "expanded"
        if encoding == 2
        else features.repeated_field_encoding,
        True if utf8 == 2 else False if utf8 == 3 else features.utf8_validation,
        False if message == 1 else True if message == 2 else features.delimited,
    )


def _field_features(
    edition: EditionName, parent: _Features, field: FieldDescriptorProto
) -> _Features:
    """The features of a field, from those of its parent. proto2 and proto3
    spell some features with their own syntax."""
    options = field.get("options")
    features = _merge(parent, options)
    is_group = field.get("type") == _TYPE_GROUP
    if edition not in ("proto2", "proto3"):
        return replace(features, delimited=True) if is_group else features
    packed = None if options is None else options.get("packed")
    presence: Presence = (
        "required"
        if field.get("label") == _LABEL_REQUIRED
        else "explicit"
        if field.get("proto3_optional") is True
        else features.field_presence
    )
    return replace(
        features,
        field_presence=presence,
        repeated_field_encoding="packed"
        if packed is True
        else "expanded"
        if packed is False
        else features.repeated_field_encoding,
        delimited=is_group,
    )


def _type_ref(name: str | None, at: str) -> str:
    """``.acme.v1.User`` to ``acme.v1.User``."""
    if name is None or not name.startswith("."):
        _fail(f"{at}: expected a fully qualified type name, got {name}")
    return name[1:]


def _scoped(scope: str, name: str) -> str:
    return name if scope == "" else f"{scope}.{name}"


@dataclass(frozen=True, slots=True)
class _Pending:
    message: MessageDescriptor
    features: _Features


class _Resolver:
    def __init__(self, protos: Iterable[FileDescriptorProto]) -> None:
        self.by_name: dict[str, FileDescriptorProto] = {}
        for proto in protos:
            name = proto.get("name")
            if name is None:
                _fail("a file without a name")
            if name in self.by_name:
                _fail(f"{name}: the file is given twice")
            self.by_name[name] = proto
        self.files: dict[str, FileDescriptor] = {}
        self.messages: dict[str, MessageDescriptor] = {}
        self.enums: dict[str, EnumDescriptor] = {}
        self.services: dict[str, ServiceDescriptor] = {}
        self.extensions: dict[str, ExtensionDescriptor] = {}
        self.by_extendee: dict[str, dict[int, ExtensionDescriptor]] = {}
        self.pending: list[_Pending] = []
        self.pending_extensions: list[
            tuple[FileDescriptor, MessageDescriptor | None, FieldDescriptorProto, _Features]
        ] = []
        # Map entry messages, by full name, which map fields read.
        self.entries: dict[str, _Pending] = {}
        self.visiting: set[str] = set()

    def define(self, type_name: str) -> None:
        if type_name in self.messages or type_name in self.enums or type_name in self.services:
            _fail(f"{type_name} is defined twice")

    def add_enum(
        self,
        file: FileDescriptor,
        parent: MessageDescriptor | None,
        scope: str,
        proto: EnumDescriptorProto,
        features: _Features,
    ) -> EnumDescriptor:
        name = proto.get("name")
        if name is None:
            _fail(f"{scope}: an enum without a name")
        type_name = _scoped(scope, name)
        self.define(type_name)
        out = EnumDescriptor(
            type_name,
            name,
            file,
            parent,
            open=_merge(features, proto.get("options")).enum_type == "open",
            proto=proto,
        )
        for value in proto.get("value") or ():
            value_name = value.get("name")
            if value_name is None:
                _fail(f"{type_name}: a value without a name")
            number = value.get("number")
            if number is None:
                _fail(f"{type_name}.{value_name}: a value without a number")
            out.values.append(EnumValueDescriptor(value_name, number, out, value))
        if not out.values:
            _fail(f"{type_name}: an enum without values")
        self.enums[type_name] = out
        return out

    def add_message(
        self,
        file: FileDescriptor,
        parent: MessageDescriptor | None,
        scope: str,
        proto: DescriptorProto,
        parent_features: _Features,
    ) -> MessageDescriptor:
        name = proto.get("name")
        if name is None:
            _fail(f"{scope}: a message without a name")
        type_name = _scoped(scope, name)
        self.define(type_name)
        options = proto.get("options")
        features = _merge(parent_features, options)
        out = MessageDescriptor(
            type_name,
            name,
            file,
            parent,
            message_set_wire_format=options is not None
            and options.get("message_set_wire_format") is True,
            proto=proto,
        )
        self.messages[type_name] = out
        entry = _Pending(out, features)
        if options is not None and options.get("map_entry") is True:
            self.entries[type_name] = entry
        else:
            self.pending.append(entry)
        for nested in proto.get("nested_type") or ():
            message = self.add_message(file, out, type_name, nested, features)
            nested_options = nested.get("options")
            if nested_options is None or nested_options.get("map_entry") is not True:
                out.messages.append(message)
        for nested in proto.get("enum_type") or ():
            out.enums.append(self.add_enum(file, out, type_name, nested, features))
        for extension in proto.get("extension") or ():
            self.pending_extensions.append((file, out, extension, features))
        return out

    def add_files(self, name: str) -> None:
        """Adds ``name`` after its imports, depth first. The stack is explicit: an
        import chain is as long as its input."""
        stack: list[tuple[str, str | None, bool]] = [(name, None, False)]
        while stack:
            current, importer, expanded = stack.pop()
            if current in self.files:
                continue
            proto = self.by_name.get(current)
            if proto is None:
                _fail(
                    f"{current} is missing"
                    if importer is None
                    else f"{importer} imports {current}, which is missing"
                )
            dependencies = proto.get("dependency") or ()
            if expanded:
                self.visiting.discard(current)
                self.add_file(current, proto, [self.files[d] for d in dependencies])
                continue
            if current in self.visiting:
                _fail(f"{current} is part of an import cycle")
            self.visiting.add(current)
            stack.append((current, importer, True))
            stack.extend((d, current, False) for d in reversed(dependencies))

    def add_file(
        self, name: str, proto: FileDescriptorProto, dependencies: list[FileDescriptor]
    ) -> FileDescriptor:
        edition = _edition_of(proto)
        base = _PROTO2 if edition == "proto2" else _PROTO3 if edition == "proto3" else _EDITIONS
        features = _merge(base, proto.get("options"))
        scope = proto.get("package") or ""
        file = FileDescriptor(name, scope, edition, dependencies, proto)
        self.files[name] = file
        for message in proto.get("message_type") or ():
            file.messages.append(self.add_message(file, None, scope, message, features))
        for enum in proto.get("enum_type") or ():
            file.enums.append(self.add_enum(file, None, scope, enum, features))
        for extension in proto.get("extension") or ():
            self.pending_extensions.append((file, None, extension, features))
        for service in proto.get("service") or ():
            service_name = service.get("name")
            if service_name is None:
                _fail(f"{name}: a service without a name")
            type_name = _scoped(scope, service_name)
            self.define(type_name)
            out = ServiceDescriptor(type_name, service_name, file, service)
            self.services[type_name] = out
            file.services.append(out)
        return file

    def value_type(self, proto: FieldDescriptorProto, features: _Features, at: str) -> ValueType:
        type = proto.get("type")
        if type is None:
            _fail(f"{at}: a field without a type")
        if type in (_TYPE_MESSAGE, _TYPE_GROUP):
            type_name = _type_ref(proto.get("type_name"), at)
            message = self.messages.get(type_name)
            if message is None:
                _fail(f"{at}: message {type_name} is not defined")
            return MessageValueType(message, delimited=features.delimited)
        if type == _TYPE_ENUM:
            type_name = _type_ref(proto.get("type_name"), at)
            enum = self.enums.get(type_name)
            if enum is None:
                _fail(f"{at}: enum {type_name} is not defined")
            return EnumValueType(enum)
        scalar = _SCALARS.get(type)
        if scalar is None:
            _fail(f"{at}: field type {type} is not supported")
        options = proto.get("options")
        jstype = None if options is None else options.get("jstype")
        return ScalarValueType(
            scalar,
            "string" if jstype == 1 else "number" if jstype == 2 else "bigint",
            features.utf8_validation,
        )

    def field(
        self,
        parent: MessageDescriptor,
        oneof: OneofDescriptor | None,
        proto: FieldDescriptorProto,
        features: _Features,
        at: str,
    ) -> FieldDescriptor:
        name = proto.get("name")
        if name is None:
            _fail(f"{at}: a field without a name")
        where = f"{at}.{name}"
        number = proto.get("number")
        if number is None:
            _fail(f"{where}: a field without a number")
        # MessageSet extension ids are written as values, not as field tags.
        max_number = (
            _MAX_MESSAGE_SET_NUMBER
            if proto.get("extendee") is not None and parent.message_set_wire_format
            else _MAX_FIELD_NUMBER
        )
        if not _is_int(number) or not 1 <= number <= max_number:
            _fail(f"{where}: expected a field number from 1 through {max_number}")
        label = proto.get("label")
        if label is not None and label not in (_LABEL_OPTIONAL, _LABEL_REQUIRED, _LABEL_REPEATED):
            _fail(f"{where}: invalid field label {label}")
        if label == _LABEL_REPEATED:
            if proto.get("type") == _TYPE_MESSAGE:
                entry = self.entries.get(_type_ref(proto.get("type_name"), where))
                if entry is not None:
                    return self.map_field(parent, oneof, proto, name, number, entry, where)
            type = self.value_type(proto, features, where)
            # Only numbers, booleans and enums can be packed.
            packable = isinstance(type, EnumValueType) or (
                isinstance(type, ScalarValueType) and type.scalar not in ("string", "bytes")
            )
            return ListFieldDescriptor(
                name,
                number,
                parent,
                oneof,
                proto,
                type,
                packed=packable and features.repeated_field_encoding == "packed",
            )
        type = self.value_type(proto, features, where)
        # Messages and the fields of oneofs always have explicit presence.
        presence: Presence = (
            "required"
            if features.field_presence == "required"
            else "explicit"
            if isinstance(type, MessageValueType) or oneof is not None
            else features.field_presence
        )
        return SingularFieldDescriptor(name, number, parent, oneof, proto, type, presence)

    def map_field(  # noqa: PLR0917
        self,
        parent: MessageDescriptor,
        oneof: OneofDescriptor | None,
        proto: FieldDescriptorProto,
        name: str,
        number: int,
        entry: _Pending,
        where: str,
    ) -> MapFieldDescriptor:
        entry_proto = entry.message.proto
        edition = entry.message.file.edition
        fields = entry_proto.get("field") or ()
        key = next((f for f in fields if f.get("number") == 1), None)
        if key is None:
            _fail(f"{where}: a map entry without a key")
        value = next((f for f in fields if f.get("number") == 2), None)
        if value is None:
            _fail(f"{where}: a map entry without a value")
        key_type = self.value_type(key, _field_features(edition, entry.features, key), where)
        if not isinstance(key_type, ScalarValueType) or key_type.scalar in (
            "bytes",
            "float",
            "double",
        ):
            _fail(f"{where}: expected a string, boolean or integer map key")
        value_features = _field_features(edition, entry.features, value)
        # Map values are never written as groups.
        value_type = self.value_type(value, replace(value_features, delimited=False), where)
        return MapFieldDescriptor(name, number, parent, oneof, proto, key_type, value_type)

    def resolve_fields(self, pending: _Pending) -> None:
        message, features = pending.message, pending.features
        proto = message.proto
        at = message.type_name
        names: set[str] = set()
        numbers: set[int] = set()
        fields = proto.get("field") or ()
        oneofs: list[OneofDescriptor | None] = []
        for index, decl in enumerate(proto.get("oneof_decl") or ()):
            # A synthetic oneof holds only a proto3 `optional` field.
            members = [f for f in fields if f.get("oneof_index") == index]
            if members and all(f.get("proto3_optional") is True for f in members):
                oneofs.append(None)
                continue
            name = decl.get("name")
            if name is None:
                _fail(f"{at}: a oneof without a name")
            if name in names:
                _fail(f"{at}: {name} is defined twice")
            names.add(name)
            oneof = OneofDescriptor(name, message, decl)
            oneofs.append(oneof)
            message.oneofs.append(oneof)
        for f in fields:
            index = f.get("oneof_index")
            if index is not None and (not _is_int(index) or not 0 <= index < len(oneofs)):
                _fail(f"{at}.{f.get('name')}: invalid oneof index {index}")
            label = f.get("label")
            if index is not None and label is not None and label != _LABEL_OPTIONAL:
                _fail(f"{at}.{f.get('name')}: a oneof member must be optional")
            oneof = None if index is None else oneofs[index]
            inherited = features if oneof is None else _merge(features, oneof.proto.get("options"))
            out = self.field(
                message, oneof, f, _field_features(message.file.edition, inherited, f), at
            )
            if out.name in names:
                _fail(f"{at}: {out.name} is defined twice")
            if out.number in numbers:
                _fail(f"{at}: field number {out.number} is defined twice")
            names.add(out.name)
            numbers.add(out.number)
            message.fields.append(out)
            if oneof is not None:
                oneof.fields.append(out)

    def resolve_extension(
        self,
        file: FileDescriptor,
        parent: MessageDescriptor | None,
        proto: FieldDescriptorProto,
        features: _Features,
    ) -> None:
        scope = parent.type_name if parent is not None else file.package
        name = proto.get("name")
        if name is None:
            _fail(f"{scope}: an extension without a name")
        type_name = _scoped(scope, name)
        if type_name in self.extensions:
            _fail(f"{type_name} is defined twice")
        extendee_name = _type_ref(proto.get("extendee"), type_name)
        extendee = self.messages.get(extendee_name)
        if extendee is None:
            _fail(f"{type_name}: message {extendee_name} is not defined")
        resolved = self.field(
            extendee, None, proto, _field_features(file.edition, features, proto), scope
        )
        if isinstance(resolved, MapFieldDescriptor):
            _fail(f"{type_name}: an extension cannot be a map")
        # Extensions always have explicit presence.
        if isinstance(resolved, SingularFieldDescriptor) and resolved.presence == "implicit":
            resolved = replace(resolved, presence="explicit")
        out = ExtensionDescriptor(type_name, name, file, parent, extendee, resolved, proto)
        self.extensions[type_name] = out
        (parent if parent is not None else file).extensions.append(out)
        by_number = self.by_extendee.setdefault(extendee_name, {})
        if resolved.number in by_number:
            _fail(f"{type_name}: {extendee_name} has two extensions {resolved.number}")
        by_number[resolved.number] = out

    def resolve_methods(self, service: ServiceDescriptor) -> None:
        for method in service.proto.get("method") or ():
            at = f"{service.type_name}.{method.get('name')}"
            input_name = _type_ref(method.get("input_type"), at)
            output_name = _type_ref(method.get("output_type"), at)
            options = method.get("options")
            level = None if options is None else options.get("idempotency_level")
            name = method.get("name")
            if name is None:
                _fail(f"{service.type_name}: a method without a name")
            input = self.messages.get(input_name)
            if input is None:
                _fail(f"{at}: message {input_name} is not defined")
            output = self.messages.get(output_name)
            if output is None:
                _fail(f"{at}: message {output_name} is not defined")
            service.methods.append(
                MethodDescriptor(
                    name,
                    service,
                    input,
                    output,
                    client_streaming=method.get("client_streaming") is True,
                    server_streaming=method.get("server_streaming") is True,
                    idempotency="noSideEffects"
                    if level == 1
                    else "idempotent"
                    if level == 2
                    else "unknown",
                    proto=method,
                )
            )

    def resolve(self) -> Registry:
        for name in self.by_name:
            self.add_files(name)
        for pending in [*self.pending, *self.entries.values()]:
            self.resolve_fields(pending)
        for file, parent, proto, features in self.pending_extensions:
            self.resolve_extension(file, parent, proto, features)
        # Every message descriptor exists before service methods resolve.
        for service in self.services.values():
            self.resolve_methods(service)
        visible = {k: v for k, v in self.messages.items() if k not in self.entries}
        return Registry(
            list(self.files.values()),
            self.files,
            visible,
            self.enums,
            self.services,
            self.extensions,
            self.by_extendee,
        )


def resolve(protos: Iterable[FileDescriptorProto]) -> Registry:
    """Raises ``ResolveError`` for descriptors that do not resolve."""
    return _Resolver(protos).resolve()
