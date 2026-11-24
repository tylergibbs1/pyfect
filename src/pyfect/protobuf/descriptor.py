"""Resolved protobuf descriptors (Effect's ``protobuf/ProtobufDescriptor``).

``make`` resolves ``FileDescriptorProto`` s, as ``protoc`` writes them, into a
``Registry`` of message, enum, extension and service descriptors, which
``pyfect.protobuf.message`` encodes and decodes by. ``from_file_descriptor_set``
reads the output of ``protoc --descriptor_set_out``. The types and
descriptors of ``google/protobuf/descriptor.proto`` itself are in
``pyfect.protobuf.descriptor_proto``.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import cast

from pyfect._public import publish
from pyfect.errors import TaggedError
from pyfect.protobuf import _binary, _resolve
from pyfect.protobuf._descriptors import (
    EditionName,
    EnumDescriptor,
    EnumValueDescriptor,
    EnumValueType,
    ExtensionDescriptor,
    FieldDescriptor,
    FileDescriptor,
    JsType,
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
from pyfect.protobuf.descriptor_proto import (
    FILE_DESCRIPTOR_SET,
    FileDescriptorProto,
    FileDescriptorSet,
)
from pyfect.result import Err, Ok, Result


@dataclass(eq=False)
class ProtobufDescriptorError(TaggedError):
    """Descriptors that do not resolve: a missing type or import, a name
    defined twice, an unsupported edition."""

    message: str


def make(files: Iterable[FileDescriptorProto]) -> Result[Registry, ProtobufDescriptorError]:
    """Resolves ``files`` together; each file's imports must be among them."""
    try:
        return Ok(_resolve.resolve(files))
    except _resolve.ResolveError as error:
        return Err(ProtobufDescriptorError(str(error)))


def from_file_descriptor_set(
    data: bytes | bytearray | memoryview,
) -> Result[Registry, ProtobufDescriptorError]:
    """Resolves the files of an encoded ``FileDescriptorSet``."""
    try:
        decoded = _binary.decode(FILE_DESCRIPTOR_SET, data)
    except _binary.Failure as failure:
        return Err(ProtobufDescriptorError(failure.message))
    return make(cast("FileDescriptorSet", decoded).get("file", []))


__all__ = [
    "EditionName",
    "EnumDescriptor",
    "EnumValueDescriptor",
    "EnumValueType",
    "ExtensionDescriptor",
    "FieldDescriptor",
    "FileDescriptor",
    "JsType",
    "ListFieldDescriptor",
    "MapFieldDescriptor",
    "MessageDescriptor",
    "MessageValueType",
    "MethodDescriptor",
    "OneofDescriptor",
    "Presence",
    "ProtobufDescriptorError",
    "Registry",
    "ScalarType",
    "ScalarValueType",
    "ServiceDescriptor",
    "SingularFieldDescriptor",
    "ValueType",
    "from_file_descriptor_set",
    "make",
]

publish(globals())
