"""Ports of Effect's ``protobuf/ProtobufDescriptor.test.ts``.

Each test's docstring is the Effect test title. ``descriptorFile`` is
``descriptor_proto.DESCRIPTOR_FILE``, and the check of the built-in
definitions runs ``scripts/gen_protobuf_descriptor.py --check``.
"""

from __future__ import annotations

import importlib.util
import math
from pathlib import Path
from typing import Any

import pytest

from pyfect.protobuf import descriptor, descriptor_proto
from pyfect.protobuf import message as protobuf_message
from pyfect.protobuf.descriptor import (
    EnumValueType,
    FieldDescriptor,
    FileDescriptorProto,
    ListFieldDescriptor,
    MapFieldDescriptor,
    MessageValueType,
    ScalarValueType,
    SingularFieldDescriptor,
)
from pyfect.protobuf.descriptor_proto import DescriptorProto
from pyfect.result import Err, Ok

from ._protobuf_descriptors import T, field, message, registry

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests" / "fixtures" / "protobuf" / "descriptor-set.binpb"


def field_of(type_name: str, name: str) -> FieldDescriptor:
    found = next((f for f in message(type_name).fields if f.name == name), None)
    if found is None:
        raise LookupError(f"no field {type_name}.{name}")
    return found


def resolved(f: FieldDescriptor) -> dict[str, object]:
    """The properties of a field that its syntax or edition and features decide."""
    out: dict[str, object] = {"kind": f.kind}
    if isinstance(f, SingularFieldDescriptor):
        out["presence"] = f.presence
    if isinstance(f, ListFieldDescriptor):
        out["packed"] = f.packed
    match f.type:
        case ScalarValueType(validate_utf8=validate_utf8, js_type=js_type):
            out |= {"validate_utf8": validate_utf8, "js_type": js_type}
        case MessageValueType(delimited=delimited):
            out["delimited"] = delimited
        case EnumValueType(enum=enum):
            out["open"] = enum.open
    return out


STRING = {"validate_utf8": True, "js_type": "bigint"}
LEGACY = {"validate_utf8": False, "js_type": "bigint"}
FIELDS: list[tuple[str, str, dict[str, object]]] = [
    ("test.Scalars", "int32", {"kind": "singular", "presence": "implicit", **STRING}),
    ("test.Optional", "a", {"kind": "singular", "presence": "explicit", **STRING}),
    ("test.Shape", "origin", {"kind": "singular", "presence": "explicit", "delimited": False}),
    ("test.Shape", "label", {"kind": "singular", "presence": "explicit", **STRING}),
    ("test.Shape", "ids", {"kind": "list", "packed": True, **STRING}),
    ("test.Shape", "tags", {"kind": "list", "packed": False, **STRING}),
    ("test.Shape", "color", {"kind": "singular", "presence": "implicit", "open": True}),
    (
        "test.Js",
        "as_string",
        {"kind": "singular", "presence": "implicit", "validate_utf8": True, "js_type": "string"},
    ),
    (
        "test.Js",
        "as_number",
        {"kind": "singular", "presence": "implicit", "validate_utf8": True, "js_type": "number"},
    ),
    ("legacy.Legacy", "id", {"kind": "singular", "presence": "required", **LEGACY}),
    ("legacy.Legacy", "name", {"kind": "singular", "presence": "explicit", **LEGACY}),
    ("legacy.Legacy", "values", {"kind": "list", "packed": False, **LEGACY}),
    ("legacy.Legacy", "item", {"kind": "singular", "presence": "explicit", "delimited": True}),
    ("legacy.Legacy", "mode", {"kind": "singular", "presence": "explicit", "open": False}),
    ("legacy.Legacy", "modes", {"kind": "list", "packed": True, "open": False}),
    ("editions.E", "a", {"kind": "singular", "presence": "explicit", **STRING}),
    ("editions.E", "b", {"kind": "singular", "presence": "implicit", **STRING}),
    ("editions.E", "c", {"kind": "list", "packed": True, **STRING}),
    ("editions.E", "d", {"kind": "singular", "presence": "explicit", "delimited": True}),
    ("editions.E", "e", {"kind": "singular", "presence": "explicit", "open": False}),
]


@pytest.mark.parametrize(
    ("type_name", "name", "expected"), FIELDS, ids=[f"{t}.{n}" for t, n, _ in FIELDS]
)
def test_resolves_fields(type_name: str, name: str, expected: dict[str, object]) -> None:
    """ProtobufDescriptor / resolves fields / %s"""
    assert resolved(field_of(type_name, name)) == expected


def test_resolves_map_fields_and_hides_their_entry_messages() -> None:
    """ProtobufDescriptor / resolves map fields, and hides their entry messages"""
    counts = field_of("test.Shape", "counts")
    assert isinstance(counts, MapFieldDescriptor)
    assert counts.key.scalar == "string"
    assert isinstance(counts.type, ScalarValueType)
    assert counts.type.scalar == "int32"
    assert registry.get_message("test.Shape.CountsEntry") is None
    assert message("test.Shape").messages == []


def test_keeps_oneofs_but_not_the_synthetic_oneofs_of_proto3_optional_fields() -> None:
    """ProtobufDescriptor / keeps oneofs, but not the synthetic oneofs of proto3 optional fields"""
    shape = message("test.Shape")
    assert [(o.name, [f.name for f in o.fields]) for o in shape.oneofs] == [
        ("kind", ["label", "center"])
    ]
    assert message("test.Optional").oneofs == []
    assert field_of("test.Optional", "a").oneof is None


def test_preserves_original_field_and_oneof_names() -> None:
    """ProtobufDescriptor / preserves original field and oneof names"""
    assert [f.name for f in message("test.Names").fields] == ["constructor", "foo_bar"]
    assert [f.name for f in message("legacy.OriginalNames").fields] == [
        "bar",
        "bar_",
        "constructor",
        "__proto__",
        "toString",
    ]
    oneof = message("test.NamedOneof").oneofs[0]
    assert oneof.name == "__proto__"
    assert [f.name for f in oneof.fields] == ["child_value", "toString"]


def test_resolves_services_extensions_and_enums() -> None:
    """ProtobufDescriptor / resolves services, extensions and enums"""
    service = registry.get_service("test.Shapes")
    assert service is not None
    assert [
        (m.name, m.input.type_name, m.output.type_name, m.server_streaming, m.idempotency)
        for m in service.methods
    ] == [
        ("Get", "test.Point", "test.Shape", False, "noSideEffects"),
        ("Watch", "test.Point", "test.Shape", True, "unknown"),
    ]
    priority = registry.get_extension("legacy.priority")
    assert priority is not None
    assert registry.find_extension("legacy.Legacy", 100) is priority
    assert priority.extendee is message("legacy.Legacy")
    member = registry.get_extension("legacy.SetMember.member")
    assert member is not None
    assert member.parent is message("legacy.SetMember")
    assert member.extendee.message_set_wire_format
    mode = registry.get_enum("legacy.Mode")
    assert mode is not None
    assert [(v.name, v.number) for v in mode.values] == [("A", 1), ("B", 2)]


def test_uses_the_larger_extension_number_range_only_for_message_set() -> None:
    """ProtobufDescriptor / uses the larger extension-number range only for MessageSet"""
    for message_set, number, valid in [
        (False, 536870911, True),
        (False, 536870912, False),
        (True, 536870912, True),
        (True, 2147483646, True),
        (True, 2147483647, False),
    ]:
        result = descriptor.make(
            [
                {
                    "name": "extensions.proto",
                    "syntax": "proto2",
                    "message_type": [
                        {
                            "name": "Container",
                            "options": {"message_set_wire_format": message_set},
                            "extension_range": [
                                {"start": 4, "end": 2147483647 if message_set else 536870912}
                            ],
                        },
                        {"name": "Payload", "field": [field("value", 1, "int32")]},
                    ],
                    "extension": [field("payload", number, ".Payload", extendee=".Container")],
                }
            ]
        )
        if valid:
            registry_ = result.get_or_raise()
            extension = registry_.get_extension("payload")
            assert extension is not None
            assert extension.field.number == number
            assert registry_.find_extension("Container", number) is extension
        else:
            assert isinstance(result, Err)


def test_rejects_field_numbers_that_cannot_be_represented_by_a_tag() -> None:
    """ProtobufDescriptor / fails to resolve / rejects field numbers that cannot be represented by a
    tag"""
    for number in [0, -1, 1.5, 536870912, math.nan, math.inf]:
        result = descriptor.make(
            [
                {
                    "name": "bad.proto",
                    "message_type": [{"name": "Bad", "field": [field("x", number, "int32")]}],
                }
            ]
        )
        assert isinstance(result, Err), number


def test_rejects_duplicate_fields_and_invalid_oneof_membership() -> None:
    """ProtobufDescriptor / fails to resolve / rejects duplicate fields and invalid oneof membership
    ProtobufDescriptor / fails to resolve / rejects duplicate fields and invalid oneof membership"""
    cases: list[DescriptorProto] = [
        {"name": "Bad", "field": [field("x", 1, "int32"), field("x", 2, "int32")]},
        {"name": "Bad", "field": [field("x", 1, "int32"), field("y", 1, "int32")]},
        {"name": "Bad", "field": [field("x", 1, "int32", oneof_index=0)]},
        {
            "name": "Bad",
            "oneof_decl": [{"name": "choice"}],
            "field": [field("x", 1, "int32", oneof_index=-1)],
        },
        {
            "name": "Bad",
            "oneof_decl": [{"name": "choice"}],
            "field": [field("x", 1, "int32", oneof_index=0, label=3)],
        },
        {"name": "Bad", "oneof_decl": [{"name": "choice"}], "field": [field("choice", 1, "int32")]},
        {"name": "Bad", "oneof_decl": [{"name": "choice"}, {"name": "choice"}]},
    ]
    for case in cases:
        assert isinstance(descriptor.make([{"name": "bad.proto", "message_type": [case]}]), Err), (
            case
        )


def test_rejects_non_integral_numeric_and_bytes_map_keys() -> None:
    """ProtobufDescriptor / fails to resolve / rejects non-integral numeric and bytes map keys"""
    for type in [T["float"], T["double"], T["bytes"]]:
        result = descriptor.make(
            [
                {
                    "name": "bad.proto",
                    "message_type": [
                        {
                            "name": "Bad",
                            "field": [field("items", 1, ".Bad.Entry", label=3)],
                            "nested_type": [
                                {
                                    "name": "Entry",
                                    "options": {"map_entry": True},
                                    "field": [
                                        {"name": "key", "number": 1, "label": 1, "type": type},
                                        field("value", 2, "int32"),
                                    ],
                                }
                            ],
                        }
                    ],
                }
            ]
        )
        assert isinstance(result, Err), type


_POINT: DescriptorProto = {"name": "Point", "field": [field("x", 1, "int32")]}
FAILURES: list[tuple[str, list[FileDescriptorProto], str]] = [
    (
        "a missing dependency",
        [{"name": "a.proto", "dependency": ["b.proto"]}],
        "a.proto imports b.proto, which is missing",
    ),
    (
        "an import cycle",
        [
            {"name": "a.proto", "dependency": ["b.proto"]},
            {"name": "b.proto", "dependency": ["a.proto"]},
        ],
        "a.proto is part of an import cycle",
    ),
    (
        "an undefined type",
        [
            {
                "name": "a.proto",
                "message_type": [{"name": "A", "field": [field("f", 1, ".x.Missing")]}],
            }
        ],
        "A.f: message x.Missing is not defined",
    ),
    (
        "a relative type name",
        [
            {
                "name": "a.proto",
                "message_type": [
                    {
                        "name": "A",
                        "field": [
                            {
                                "name": "f",
                                "number": 1,
                                "label": 1,
                                "type": T["message"],
                                "type_name": "Point",
                            }
                        ],
                    },
                    _POINT,
                ],
            }
        ],
        "A.f: expected a fully qualified type name, got Point",
    ),
    (
        "an unsupported edition",
        [
            {
                "name": "a.proto",
                "syntax": "editions",
                "edition": descriptor_proto.Edition.EDITION_MAX,
            }
        ],
        "a.proto: edition 2147483647 is not supported",
    ),
    (
        "a type defined twice",
        [
            {"name": "a.proto", "message_type": [_POINT]},
            {"name": "b.proto", "message_type": [_POINT]},
        ],
        "Point is defined twice",
    ),
]


@pytest.mark.parametrize(("name", "files", "expected"), FAILURES, ids=[f[0] for f in FAILURES])
def test_fails_to_resolve(name: str, files: list[FileDescriptorProto], expected: str) -> None:
    """ProtobufDescriptor / fails to resolve / %s"""
    result = descriptor.make(files)
    assert isinstance(result, Err), name
    assert result.error.message == expected


# `protoc --descriptor_set_out --include_source_info` of protoc 36.2, for
# google/protobuf/descriptor.proto and google/protobuf/compiler/plugin.proto.
@pytest.fixture(scope="module")
def descriptor_set() -> bytes:
    return FIXTURE.read_bytes()


def test_has_reproducible_built_in_definitions() -> None:
    """ProtobufDescriptor / descriptor sets / has reproducible built-in definitions"""
    spec = importlib.util.spec_from_file_location(
        "gen_protobuf_descriptor", ROOT / "scripts" / "gen_protobuf_descriptor.py"
    )
    assert spec is not None
    assert spec.loader is not None
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)
    assert script.main(["--check"]) == 0


def test_resolves_the_files_of_a_descriptor_set(descriptor_set: bytes) -> None:
    """ProtobufDescriptor / descriptor sets / resolves the files of a descriptor set"""
    registry_ = descriptor.from_file_descriptor_set(descriptor_set).get_or_raise()
    assert [(f.name, f.edition) for f in registry_.files] == [
        ("google/protobuf/descriptor.proto", "proto2"),
        ("google/protobuf/compiler/plugin.proto", "proto2"),
    ]
    request = registry_.get_message("google.protobuf.compiler.CodeGeneratorRequest")
    assert request is not None
    assert [
        f.type.message.type_name
        if isinstance(f, SingularFieldDescriptor) and isinstance(f.type, MessageValueType)
        else f.name
        for f in request.fields
    ] == [
        "file_to_generate",
        "parameter",
        "proto_file",
        "source_file_descriptors",
        "google.protobuf.compiler.Version",
    ]


def test_encodes_a_decoded_descriptor_set_to_the_same_bytes(descriptor_set: bytes) -> None:
    """ProtobufDescriptor / descriptor sets / encodes a decoded descriptor set to the same bytes"""
    decoded = protobuf_message.decode(descriptor_proto.FILE_DESCRIPTOR_SET)(
        descriptor_set
    ).get_or_raise()
    files: Any = decoded["file"]
    comments = [
        loc for loc in files[0]["source_code_info"]["location"] if "leading_comments" in loc
    ]
    assert comments
    encoded = protobuf_message.encode(descriptor_proto.FILE_DESCRIPTOR_SET)(decoded)  # pyright: ignore[reportArgumentType]
    assert encoded == Ok(descriptor_set)


def test_has_descriptor_proto_as_protoc_describes_it(descriptor_set: bytes) -> None:
    """ProtobufDescriptor / descriptor sets / has descriptor.proto as protoc describes it"""
    # Equal encodings also mean that `DESCRIPTOR_FILE` describes every field of
    # protoc's descriptor.proto: fields it lacks would be decoded as unknown
    # fields of `protoc` and written back.
    encode = protobuf_message.encode(descriptor_proto.FILE_DESCRIPTOR_PROTO)
    decoded = protobuf_message.decode(descriptor_proto.FILE_DESCRIPTOR_SET)(
        descriptor_set
    ).get_or_raise()
    files: Any = decoded["file"]
    protoc = {k: v for k, v in files[0].items() if k != "source_code_info"}
    ours: Any = descriptor_proto.DESCRIPTOR_FILE.proto
    assert encode(ours).get_or_raise() == encode(protoc).get_or_raise()


def test_fails_for_malformed_bytes() -> None:
    """ProtobufDescriptor / descriptor sets / fails for malformed bytes"""
    result = descriptor.from_file_descriptor_set(bytes([0x0A, 0x05]))
    assert isinstance(result, Err)
    assert result.error.message == "file[0]: Expected a complete value at offset 2"
