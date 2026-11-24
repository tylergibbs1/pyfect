"""Ports of Effect's ``protobuf/ProtobufMessage.test.ts``.

Each test's docstring is the Effect test title. A ``bigint`` is an ``int``,
a ``Uint8Array`` ``bytes``, ``undefined`` ``None`` and the ``unknownFields``
symbol ``message.unknown_fields``. Error messages show values as Python
writes them (``-1`` for ``-1n``, ``None`` for ``null``).
"""

from __future__ import annotations

import math
from typing import Any

import pytest

from pyfect.protobuf import descriptor, descriptor_proto
from pyfect.protobuf import message as protobuf_message
from pyfect.protobuf.descriptor import ExtensionDescriptor, MessageDescriptor
from pyfect.protobuf.descriptor_proto import FileDescriptorProto
from pyfect.protobuf.message import Message, ProtobufMessageError, unknown_fields
from pyfect.result import Err, Ok, Result

from ._protobuf_descriptors import T, editions, field, message, registry

U = unknown_fields


def hexb(text: str) -> bytes:
    return bytes.fromhex(text.replace(" ", ""))


def encode(type_name: str, value: Any, **options: Any) -> str:
    return protobuf_message.encode(message(type_name), **options)(value).get_or_raise().hex()


def decode(type_name: str, hex_text: str, **options: Any) -> Message:
    return protobuf_message.decode(message(type_name), **options)(hexb(hex_text)).get_or_raise()


def failure(result: Result[object, ProtobufMessageError]) -> dict[str, object]:
    assert isinstance(result, Err), result
    return {"message": result.error.message, "path": list(result.error.path)}


def get_extension(
    value: Any, extension: ExtensionDescriptor
) -> Result[object, ProtobufMessageError]:
    return protobuf_message.get_extension(value, extension)


def set_extension(
    value: Any, extension: ExtensionDescriptor, item: object
) -> Result[Message, ProtobufMessageError]:
    return protobuf_message.set_extension(value, extension, item)


def _extension(type_name: str) -> ExtensionDescriptor:
    found = registry.get_extension(type_name)
    assert found is not None
    return found


SCALAR_ZEROS: dict[str, object] = {
    "double": 0.0,
    "float": 0.0,
    "int64": 0,
    "uint64": 0,
    "int32": 0,
    "fixed64": 0,
    "fixed32": 0,
    "bool": False,
    "string": "",
    "bytes": b"",
    "uint32": 0,
    "sfixed32": 0,
    "sfixed64": 0,
    "sint32": 0,
    "sint64": 0,
}

SHAPE_ZEROS: dict[str, object] = {
    "name": "",
    "points": [],
    "ids": [],
    "weights": [],
    "tags": [],
    "counts": {},
    "by_id": {},
    "flags": {},
    "color": 0,
    "colors": [],
    "floats": [],
}

LEGACY_ZEROS: dict[str, object] = {"values": [], "modes": [], "mode_by_name": {}}
JS_ZEROS: dict[str, object] = {"as_string": "0", "as_number": 0.0}
EDITION_ZEROS: dict[str, object] = {"b": 0, "c": []}


def test_encodes_and_decodes_the_largest_valid_field_number() -> None:
    """ProtobufMessage / encodes and decodes the largest valid field number"""
    large = descriptor.make(
        [
            {
                "name": "large.proto",
                "syntax": "proto3",
                "message_type": [
                    {
                        "name": "Large",
                        "field": [{"name": "value", "number": 536870911, "label": 1, "type": 5}],
                    }
                ],
            }
        ]
    ).get_or_raise()
    found = large.get_message("Large")
    assert found is not None
    encoded = hexb("f8ffffff0f01")
    assert protobuf_message.encode(found)({"value": 1}) == Ok(encoded)
    assert protobuf_message.decode(found)(encoded) == Ok({"value": 1})


# Each case encodes to its bytes, and decodes back to its value, with the
# zero values of the other fields.
ROUND_TRIPS: list[tuple[str, str, dict[str, object], str, dict[str, object]]] = [
    ("double 1.5", "test.Scalars", {"double": 1.5}, "09 000000000000f83f", SCALAR_ZEROS),
    (
        "double -0, which is written",
        "test.Scalars",
        {"double": -0.0},
        "09 0000000000000080",
        SCALAR_ZEROS,
    ),
    ("float 1.5", "test.Scalars", {"float": 1.5}, "15 0000c03f", SCALAR_ZEROS),
    ("int64 -1", "test.Scalars", {"int64": -1}, "18 ffffffffffffffffff01", SCALAR_ZEROS),
    ("uint64 max", "test.Scalars", {"uint64": 2**64 - 1}, "20 ffffffffffffffffff01", SCALAR_ZEROS),
    (
        "int32 -2, as ten bytes",
        "test.Scalars",
        {"int32": -2},
        "28 feffffffffffffffff01",
        SCALAR_ZEROS,
    ),
    ("fixed64 1", "test.Scalars", {"fixed64": 1}, "31 0100000000000000", SCALAR_ZEROS),
    ("fixed32 max", "test.Scalars", {"fixed32": 4294967295}, "3d ffffffff", SCALAR_ZEROS),
    ("bool", "test.Scalars", {"bool": True}, "40 01", SCALAR_ZEROS),
    ("string", "test.Scalars", {"string": "é"}, "4a 02 c3a9", SCALAR_ZEROS),
    ("bytes", "test.Scalars", {"bytes": bytes([1, 2])}, "62 02 0102", SCALAR_ZEROS),
    ("uint32 150", "test.Scalars", {"uint32": 150}, "68 9601", SCALAR_ZEROS),
    ("sfixed32 -2", "test.Scalars", {"sfixed32": -2}, "7d feffffff", SCALAR_ZEROS),
    ("sfixed64 -2", "test.Scalars", {"sfixed64": -2}, "8101 feffffffffffffff", SCALAR_ZEROS),
    ("sint32 -1", "test.Scalars", {"sint32": -1}, "8801 01", SCALAR_ZEROS),
    ("sint64 -1", "test.Scalars", {"sint64": -1}, "9001 01", SCALAR_ZEROS),
    ("an int64 as a string", "test.Js", {"as_string": "-1"}, "08 ffffffffffffffffff01", JS_ZEROS),
    ("an int64 as a number", "test.Js", {"as_number": 2.0**53}, "10 8080808080808010", JS_ZEROS),
    ("an explicit zero", "test.Optional", {"a": 0}, "0800", {}),
    ("a message", "test.Shape", {"origin": {"x": 1, "y": 0}}, "12 02 0801", SHAPE_ZEROS),
    (
        "repeated messages",
        "test.Shape",
        {"points": [{"x": 1, "y": 0}, {"x": 0, "y": 2}]},
        "1a02 0801 1a02 1002",
        SHAPE_ZEROS,
    ),
    (
        "a oneof case",
        "test.Shape",
        {"kind": {"_tag": "label", "value": "hi"}},
        "22 02 6869",
        SHAPE_ZEROS,
    ),
    (
        "a oneof message",
        "test.Shape",
        {"kind": {"_tag": "center", "value": {"x": 1, "y": 0}}},
        "2a 02 0801",
        SHAPE_ZEROS,
    ),
    ("packed integers", "test.Shape", {"ids": [1, 2, 300]}, "32 04 0102ac02", SHAPE_ZEROS),
    ("packed doubles", "test.Shape", {"weights": [0.5]}, "3a 08 000000000000e03f", SHAPE_ZEROS),
    ("packed floats", "test.Shape", {"floats": [1.0, -2.0]}, "72 08 0000803f000000c0", SHAPE_ZEROS),
    ("repeated strings", "test.Shape", {"tags": ["a", "b"]}, "42 01 61 42 01 62", SHAPE_ZEROS),
    ("a map of strings", "test.Shape", {"counts": {"a": 1}}, "4a 05 0a0161 1001", SHAPE_ZEROS),
    (
        "a map of int64 keys",
        "test.Shape",
        {"by_id": {"-5": "x"}},
        "52 0e 08fbffffffffffffffff01 120178",
        SHAPE_ZEROS,
    ),
    (
        "a map of messages",
        "test.Shape",
        {"flags": {"true": {"x": 1, "y": 0}}},
        "5a 06 0801 12020801",
        SHAPE_ZEROS,
    ),
    ("an enum", "test.Shape", {"color": 1}, "60 01", SHAPE_ZEROS),
    ("packed enums", "test.Shape", {"colors": [1, 0]}, "6a 02 0100", SHAPE_ZEROS),
    ("a required field", "legacy.Legacy", {"id": 1}, "0801", LEGACY_ZEROS),
    ("an explicit empty string", "legacy.Legacy", {"id": 1, "name": ""}, "0801 1200", LEGACY_ZEROS),
    (
        "proto2 repeated fields, expanded",
        "legacy.Legacy",
        {"id": 1, "values": [1, 2]},
        "0801 1801 1802",
        LEGACY_ZEROS,
    ),
    ("a group", "legacy.Legacy", {"id": 1, "item": {"x": 1}}, "0801 23 2801 24", LEGACY_ZEROS),
    ("a closed enum", "legacy.Legacy", {"id": 1, "mode": 2}, "0801 3002", LEGACY_ZEROS),
    (
        "packed closed enums",
        "legacy.Legacy",
        {"id": 1, "modes": [1, 2]},
        "0801 3a02 0102",
        LEGACY_ZEROS,
    ),
    (
        "a map of a closed enum",
        "legacy.Legacy",
        {"id": 1, "mode_by_name": {"a": 1}},
        "0801 4205 0a0161 1001",
        LEGACY_ZEROS,
    ),
    ("explicit presence by default in editions", "editions.E", {"a": 0}, "0800", EDITION_ZEROS),
    (
        "packed by default in editions",
        "editions.E",
        {"b": 1, "c": [1, 2]},
        "1001 1a020102",
        EDITION_ZEROS,
    ),
    ("delimited messages in editions", "editions.E", {"d": {"x": 1}}, "23 0801 24", EDITION_ZEROS),
]


@pytest.mark.parametrize(
    ("name", "type_name", "value", "hex_text", "zeros"),
    ROUND_TRIPS,
    ids=[c[0] for c in ROUND_TRIPS],
)
def test_encodes_and_decodes(
    name: str, type_name: str, value: dict[str, object], hex_text: str, zeros: dict[str, object]
) -> None:
    """ProtobufMessage / encodes and decodes / %s"""
    assert encode(type_name, value) == hex_text.replace(" ", ""), name
    decoded = decode(type_name, hex_text)
    assert decoded == {**zeros, **value}
    if name == "double -0, which is written":
        assert math.copysign(1, decoded["double"]) < 0  # pyright: ignore[reportArgumentType]


VERSIONS: list[tuple[str, str, int | None]] = [
    ("proto2", "proto2", None),
    ("proto3", "proto3", None),
    ("2023", "editions", descriptor_proto.Edition.EDITION_2023),
    ("2024", "editions", descriptor_proto.Edition.EDITION_2024),
    ("2026", "editions", descriptor_proto.Edition.EDITION_2026),
]


@pytest.mark.parametrize(("version", "syntax", "edition"), VERSIONS, ids=[v[0] for v in VERSIONS])
def test_uses_binary_defaults_from_a_descriptor_set(
    version: str, syntax: str, edition: int | None
) -> None:
    """ProtobufMessage / syntax and edition compatibility / uses %s binary defaults from a
    descriptor set"""
    file: FileDescriptorProto = {
        "name": "version.proto",
        "syntax": syntax,
        "message_type": [
            {
                "name": "Example",
                "field": [
                    field("id", 1, "int32"),
                    field("values", 2, "int32", label=3),
                    field("text", 3, "string"),
                    field("kind", 4, ".Kind", type=T["enum"]),
                    field("child", 5, ".Example"),
                ],
            }
        ],
        "enum_type": [{"name": "Kind", "value": [{"name": "ZERO", "number": 0}]}],
    }
    if edition is not None:
        file["edition"] = edition
    encoded_set = protobuf_message.encode(descriptor_proto.FILE_DESCRIPTOR_SET)(
        {"file": [file]}
    ).get_or_raise()
    registry_ = descriptor.from_file_descriptor_set(encoded_set).get_or_raise()
    found_file = registry_.get_file("version.proto")
    assert found_file is not None
    assert found_file.edition == version
    example = registry_.get_message("Example")
    assert example is not None
    encode_ = protobuf_message.encode(example)
    decode_ = protobuf_message.decode(example)
    assert decode_(b"").get_or_raise() == (
        {"id": 0, "values": [], "text": "", "kind": 0} if version == "proto3" else {"values": []}
    )
    assert encode_({"id": 0}).get_or_raise() == hexb("" if version == "proto3" else "0800")
    assert encode_({"values": [1, 2], "child": {}}).get_or_raise() == hexb(
        "1001 1002 2a00" if version == "proto2" else "12020102 2a00"
    )
    unknown_enum = decode_(hexb("2007")).get_or_raise()
    if version == "proto2":
        assert "kind" not in unknown_enum
        assert unknown_enum[U] == hexb("2007")
    else:
        assert unknown_enum["kind"] == 7
        assert U not in unknown_enum
    invalid_utf8 = decode_(hexb("1a01ff"))
    if version == "proto2":
        assert invalid_utf8.get_or_raise()["text"] == "�"
    else:
        assert isinstance(invalid_utf8, Err)


@pytest.mark.parametrize(
    ("version", "edition"),
    [(v, e) for v, _, e in VERSIONS if e is not None],
    ids=["2023", "2024", "2026"],
)
def test_applies_feature_overrides_in_edition(version: str, edition: int) -> None:
    """ProtobufMessage / syntax and edition compatibility / applies feature overrides in edition %s
    ProtobufMessage / syntax and edition compatibility / applies feature overrides in edition %s"""
    messages: list[Any] = [
        {
            **m,
            "field": [
                *m.get("field", []),
                field("text", 6, "string"),
                field("checked_text", 7, "string", options={"features": {"utf8_validation": 2}}),
            ],
        }
        for m in editions.get("message_type", [])
    ]
    registry_ = descriptor.make(
        [
            {
                **editions,
                "edition": edition,
                "options": {"features": {"repeated_field_encoding": 2, "utf8_validation": 3}},
                "message_type": messages,
            }
        ]
    ).get_or_raise()
    e = registry_.get_message("editions.E")
    assert e is not None, version
    value = {"a": 0, "b": 0, "c": [1, 2], "d": {"x": 1}, "e": 1}
    wire = hexb("0800 1801 1802 23 0801 24 2801")
    assert protobuf_message.encode(e)(value).get_or_raise() == wire
    assert protobuf_message.decode(e)(wire).get_or_raise() == value
    unknown_enum = protobuf_message.decode(e)(hexb("2807")).get_or_raise()
    assert "e" not in unknown_enum
    assert unknown_enum[U] == hexb("2807")
    assert protobuf_message.decode(e)(hexb("3201ff")).get_or_raise()["text"] == "�"
    assert isinstance(protobuf_message.decode(e)(hexb("3a01ff")), Err)


def test_leaves_out_implicit_zero_values() -> None:
    """ProtobufMessage / leaves out implicit zero values"""
    assert encode("test.Scalars", SCALAR_ZEROS) == ""
    assert encode("test.Shape", SHAPE_ZEROS) == ""
    assert encode("test.Shape", {}) == ""


def test_takes_64_bit_integers_as_a_bigint_number_or_decimal_string() -> None:
    """ProtobufMessage / takes 64-bit integers as a bigint, number or decimal string"""
    for int64 in [-1, -1.0, "-1"]:
        assert encode("test.Scalars", {"int64": int64}) == "18ffffffffffffffffff01"


def test_rounds_a_js_number_int64_outside_the_safe_integers_as_number_does() -> None:
    """ProtobufMessage / rounds a JS_NUMBER int64 outside the safe integers, as Number does"""
    assert decode("test.Js", "10 8180808080808010")["as_number"] == 2.0**53


def test_round_trips_names_that_would_collide_after_camel_casing() -> None:
    """ProtobufMessage / original names / round-trips names that would collide after camel casing"""
    value = decode("legacy.OriginalNames", "08011002")
    assert value == {"bar": 1, "bar_": 2}
    assert encode("legacy.OriginalNames", value) == "08011002"


def test_preserves_implicit_field_names_including_object_prototype_names() -> None:
    """ProtobufMessage / original names / preserves implicit field names, including Object.prototype
    names"""
    assert decode("test.Names", "") == {"constructor": 0, "foo_bar": 0}
    value = {"constructor": 1, "foo_bar": 2}
    assert encode("test.Names", value) == "08011002"
    assert decode("test.Names", "08011002") == value
    assert encode("test.Names", {}) == ""


def test_stores_and_merges_explicit_fields_as_own_properties() -> None:
    """ProtobufMessage / original names / stores and merges explicit fields as own properties"""
    value = decode("legacy.OriginalNames", "1a0208011a02100222020803220210042805")
    assert value == {"constructor": {"x": 1, "y": 2}, "__proto__": {"x": 3, "y": 4}, "toString": 5}
    assert type(value) is dict
    assert encode("legacy.OriginalNames", value) == "1a04080110022204080310042805"
    assert decode("legacy.OriginalNames", "") == {}
    assert encode("legacy.OriginalNames", {}) == ""


def test_preserves_oneof_names_and_case_tags_without_changing_the_object_prototype() -> None:
    """ProtobufMessage / original names / preserves oneof names and case tags without changing the
    object prototype"""
    value = {"__proto__": {"_tag": "child_value", "value": {"x": 1, "y": 2}}}
    assert decode("test.NamedOneof", "0a0208010a021002") == value
    assert encode("test.NamedOneof", value) == "0a0408011002"
    replaced = decode("test.NamedOneof", "0a001003")
    assert replaced == {"__proto__": {"_tag": "toString", "value": 3}}
    assert type(replaced) is dict
    assert encode("test.NamedOneof", {}) == ""


def test_preserves_repeated_field_map_field_and_map_key_names() -> None:
    """ProtobufMessage / original names / preserves repeated field, map field and map key names"""
    value = {"__proto__": ["a"], "constructor": {"__proto__": {"x": 1, "y": 0}}}
    decoded = decode("test.NamedCollections", encode("test.NamedCollections", value))
    assert decoded == value
    assert decode("test.NamedCollections", "") == {"__proto__": [], "constructor": {}}
    assert encode("test.NamedCollections", {}) == ""


def test_does_not_satisfy_required_fields_with_inherited_properties() -> None:
    """ProtobufMessage / original names / does not satisfy required fields with inherited properties
    ProtobufMessage / original names / does not satisfy required fields with inherited properties"""
    assert isinstance(protobuf_message.decode(message("legacy.RequiredName"))(b""), Err)
    assert isinstance(protobuf_message.encode(message("legacy.RequiredName"))({}), Err)
    assert decode("legacy.RequiredName", "0801") == {"constructor": 1}


COMPLETED: list[tuple[str, str, dict[str, object]]] = [
    ("replaced oneof", "0a001001", {"kind": {"_tag": "other_value", "value": 1}}),
    ("replaced ancestor", "0a04080112001001", {"kind": {"_tag": "other_value", "value": 1}}),
    ("merged oneof", "0a000a020801", {"kind": {"_tag": "child_value", "value": {"n": 1}}}),
    (
        "empty merged occurrence",
        "0a0208010a00",
        {"kind": {"_tag": "child_value", "value": {"n": 1}}},
    ),
    ("merged singular message", "1a001a020801", {"singular": {"n": 1}}),
    ("replaced map entry", "2a050a016112002a070a016112020801", {"items": {"a": {"n": 1}}}),
    ("replaced default map value", "2a030a01612a070a016112020801", {"items": {"a": {"n": 1}}}),
    ("merged map value", "2a090a0161120012020801", {"items": {"a": {"n": 1}}}),
]


@pytest.mark.parametrize(("name", "hex_text", "expected"), COMPLETED, ids=[c[0] for c in COMPLETED])
def test_validates_the_completed_message(
    name: str, hex_text: str, expected: dict[str, object]
) -> None:
    """ProtobufMessage / validates the completed message / %s"""
    value = decode("legacy.RequiredContainer", hex_text)
    assert value == {"children": [], "items": {}, **expected}, name
    assert decode("legacy.RequiredContainer", encode("legacy.RequiredContainer", value)) == value


INVALID: list[tuple[str, str, list[str | int]]] = [
    ("active oneof", "0a00", ["kind", "n"]),
    ("oneof switched back", "0a02080110010a00", ["kind", "n"]),
    ("singular message", "1a00", ["singular", "n"]),
    ("nested message", "1a0408011200", ["singular", "child", "n"]),
    ("repeated element", "220022020801", ["children", 0, "n"]),
    ("default map value", "2a030a0161", ["items", "a", "n"]),
    ("explicit empty map value", "2a050a01611200", ["items", "a", "n"]),
    ("replacement map value", "2a070a0161120208012a030a0161", ["items", "a", "n"]),
]


@pytest.mark.parametrize(("name", "hex_text", "path"), INVALID, ids=[c[0] for c in INVALID])
def test_rejects_with_the_missing_field_path(
    name: str, hex_text: str, path: list[str | int]
) -> None:
    """ProtobufMessage / validates the completed message / rejects %s with the missing field path"""
    error = failure(protobuf_message.decode(message("legacy.RequiredContainer"))(hexb(hex_text)))
    assert error["path"] == path, name
    assert "Expected required field n of legacy.RequiredChild" in str(error["message"])


def test_applies_max_depth_to_unknown_groups_inside_known_messages() -> None:
    """ProtobufMessage / applies maxDepth to unknown groups inside known messages"""
    value = "12 04 0b0b0c0c"
    assert isinstance(protobuf_message.decode(message("test.Shape"), max_depth=2)(hexb(value)), Err)
    assert decode("test.Shape", value, max_depth=3)["origin"] == {
        "x": 0,
        "y": 0,
        U: hexb("0b0b0c0c"),
    }


def test_applies_max_depth_to_both_explicit_and_default_map_message_values() -> None:
    """ProtobufMessage / applies maxDepth to both explicit and default map message values"""
    for hex_text in ["5a020801", "5a0408011200"]:
        error = failure(protobuf_message.decode(message("test.Shape"), max_depth=0)(hexb(hex_text)))
        assert error["path"] == ["flags", "true"]
        assert decode("test.Shape", hex_text, max_depth=1)["flags"] == {"true": {"x": 0, "y": 0}}


def test_rejects_invalid_nesting_limits_consistently() -> None:
    """ProtobufMessage / rejects invalid nesting limits consistently"""
    for max_depth in [-1, 0.5, math.nan, math.inf]:
        point = message("test.Point")
        assert isinstance(protobuf_message.decode(point, max_depth=max_depth)(b""), Err)  # pyright: ignore[reportArgumentType]
        assert isinstance(protobuf_message.encode(point, max_depth=max_depth)({}), Err)  # pyright: ignore[reportArgumentType]


DECODES: list[tuple[str, str, str, dict[Any, object]]] = [
    (
        "merged occurrences of a message",
        "test.Shape",
        "12020801 12021002",
        {**SHAPE_ZEROS, "origin": {"x": 1, "y": 2}},
    ),
    (
        "the last occurrence of a scalar",
        "test.Shape",
        "0a0161 0a0162",
        {**SHAPE_ZEROS, "name": "b"},
    ),
    (
        "the last case of a oneof",
        "test.Shape",
        "22026869 2a020801",
        {**SHAPE_ZEROS, "kind": {"_tag": "center", "value": {"x": 1, "y": 0}}},
    ),
    (
        "merged occurrences of a oneof message",
        "test.Shape",
        "2a020801 2a021002",
        {**SHAPE_ZEROS, "kind": {"_tag": "center", "value": {"x": 1, "y": 2}}},
    ),
    ("a packed field written unpacked", "test.Shape", "3001 3002", {**SHAPE_ZEROS, "ids": [1, 2]}),
    (
        "an unpacked field written with mixed encodings",
        "legacy.Legacy",
        "0801 1801 1a020203 1804",
        {**LEGACY_ZEROS, "id": 1, "values": [1, 2, 3, 4]},
    ),
    (
        "map entries without a value or key",
        "test.Shape",
        "4a03 0a0161 4a02 1001",
        {**SHAPE_ZEROS, "counts": {"a": 0, "": 1}},
    ),
    (
        "a field of another wire type, as an unknown field",
        "test.Shape",
        "0d00000000",
        {**SHAPE_ZEROS, U: hexb("0d00000000")},
    ),
    (
        "an undeclared field, as an unknown field",
        "test.Point",
        "f80701",
        {"x": 0, "y": 0, U: hexb("f80701")},
    ),
    (
        "an unknown number of a closed enum, as an unknown field",
        "legacy.Legacy",
        "0801 3007",
        {**LEGACY_ZEROS, "id": 1, U: hexb("3007")},
    ),
    (
        "unknown numbers of a packed closed enum, as unpacked fields",
        "legacy.Legacy",
        "0801 3a03 010702",
        {**LEGACY_ZEROS, "id": 1, "modes": [1, 2], U: hexb("3807")},
    ),
    (
        "a map entry with an unknown closed enum number, as an unknown field",
        "legacy.Legacy",
        "0801 4205 0a0161 1007",
        {**LEGACY_ZEROS, "id": 1, U: hexb("4205 0a0161 1007")},
    ),
    (
        "an unknown number of a closed enum in editions",
        "editions.E",
        "2807",
        {**EDITION_ZEROS, U: hexb("2807")},
    ),
    (
        "invalid UTF-8 without validation",
        "legacy.Legacy",
        "0801 1201ff",
        {**LEGACY_ZEROS, "id": 1, "name": "�"},
    ),
]


@pytest.mark.parametrize(
    ("name", "type_name", "hex_text", "value"), DECODES, ids=[c[0] for c in DECODES]
)
def test_decodes(name: str, type_name: str, hex_text: str, value: dict[Any, object]) -> None:
    """ProtobufMessage / decodes / %s"""
    assert decode(type_name, hex_text) == value, name


def test_writes_unknown_fields_back_last() -> None:
    """ProtobufMessage / writes unknown fields back, last"""
    value = decode("test.Shape", "0a0161 f80701 1a00")
    assert encode("test.Shape", value) == "0a01611a00f80701"


def test_owns_decoded_byte_fields_and_retained_unknown_bytes() -> None:
    """ProtobufMessage / owns decoded byte fields and retained unknown bytes"""
    data = bytearray(hexb("62020102f80701"))
    value = protobuf_message.decode(message("test.Scalars"))(data).get_or_raise()
    data[:] = bytes(len(data))
    assert value["bytes"] == hexb("0102")
    assert value[U] == hexb("f80701")


def test_owns_bytes_in_repeated_fields_maps_and_oneofs_after_finalization() -> None:
    """ProtobufMessage / owns bytes in repeated fields, maps and oneofs after finalization"""
    data = bytearray(hexb("0a010112060a01611201021a0103"))
    value = protobuf_message.decode(message("test.ByteCollections"))(data).get_or_raise()
    data[:] = bytes(len(data))
    assert value == {
        "items": [hexb("01")],
        "values": {"a": hexb("02")},
        "kind": {"_tag": "selected", "value": hexb("03")},
    }


def test_distinguishes_omitted_fields_from_explicit_zero_values_when_merging_messages() -> None:
    """ProtobufMessage / distinguishes omitted fields from explicit zero values when merging
    messages"""
    assert decode("test.Shape", "120208011200")["origin"] == {"x": 1, "y": 0}
    assert decode("test.Shape", "1202080112020800")["origin"] == {"x": 0, "y": 0}
    assert decode("legacy.RequiredContainer", "0a000a020800")["kind"] == {
        "_tag": "child_value",
        "value": {"n": 0},
    }


def test_keeps_unknown_spans_with_the_message_that_owns_them() -> None:
    """ProtobufMessage / keeps unknown spans with the message that owns them"""
    merged = decode("test.Shape", "120408011801120410022002")
    assert merged["origin"] == {"x": 1, "y": 2, U: hexb("18012002")}
    replaced = decode("legacy.RequiredContainer", "0a040801180110017803")
    assert replaced["kind"] == {"_tag": "other_value", "value": 1}
    assert replaced[U] == hexb("7803")


def test_does_not_change_a_oneof_case_when_a_closed_enum_occurrence_is_unknown() -> None:
    """ProtobufMessage / does not change a oneof case when a closed-enum occurrence is unknown"""
    result = protobuf_message.decode(message("legacy.RequiredContainer"))(hexb("0a003007"))
    assert failure(result)["path"] == ["kind", "n"]
    value = decode("legacy.RequiredContainer", "0a0208013007")
    assert value["kind"] == {"_tag": "child_value", "value": {"n": 1}}
    assert value[U] == hexb("3007")
    assert decode("legacy.RequiredContainer", "0a003001")["kind"] == {
        "_tag": "mode_value",
        "value": 1,
    }


def test_does_not_replace_a_map_entry_with_an_unknown_closed_enum_value() -> None:
    """ProtobufMessage / does not replace a map entry with an unknown closed-enum value"""
    value = decode("legacy.Legacy", "080142050a0161100142050a01611007")
    assert value["mode_by_name"] == {"a": 1}
    assert value[U] == hexb("42050a01611007")


def test_classifies_closed_enum_map_entries_by_their_final_value() -> None:
    """ProtobufMessage / classifies closed-enum map entries by their final value"""
    known = decode("legacy.Legacy", "0801 4207 0a0161 1007 1001")
    assert known["mode_by_name"] == {"a": 1}
    assert U not in known
    unknown = decode("legacy.Legacy", "0801 4207 0a0161 1001 1007")
    assert unknown["mode_by_name"] == {}
    assert unknown[U] == hexb("4207 0a0161 1001 1007")


def test_retains_large_packed_closed_enum_fields_without_exceeding_argument_limits() -> None:
    """ProtobufMessage / retains large packed closed-enum fields without exceeding argument limits
    ProtobufMessage / retains large packed closed-enum fields without exceeding argument limits"""
    count = 150000
    # id = 1, followed by 150000 packed occurrences of the unknown enum number 7.
    data = bytes([0x08, 0x01, 0x3A, 0xF0, 0x93, 0x09]) + bytes([7]) * count
    value = protobuf_message.decode(message("legacy.Legacy"))(data).get_or_raise()
    assert value["modes"] == []
    assert value[U] == bytes([0x38, 7]) * count
    dropped = protobuf_message.decode(message("legacy.Legacy"), read_unknown_fields=False)(
        data
    ).get_or_raise()
    assert U not in dropped


def test_drops_unknown_fields_with_read_unknown_fields_false_and_write_unknown_fields_false() -> (
    None
):
    """ProtobufMessage / drops unknown fields with readUnknownFields: false and writeUnknownFields:
    false"""
    assert decode("test.Point", "f80701", read_unknown_fields=False) == {"x": 0, "y": 0}
    assert encode("test.Point", {U: hexb("f80701")}, write_unknown_fields=False) == ""


def test_rejects_malformed_bytes_even_if_a_later_occurrence_would_replace_the_value() -> None:
    """ProtobufMessage / fails to decode / rejects malformed bytes even if a later occurrence would
    replace the value"""
    for hex_text in ["0a01081001", "2a040a0161122a070a016112020801"]:
        assert isinstance(
            protobuf_message.decode(message("legacy.RequiredContainer"))(hexb(hex_text)), Err
        )


DECODE_FAILURES: list[tuple[str, str, str, str, list[str | int]]] = [
    ("a truncated varint", "test.Point", "08", "x: Expected a complete value at offset 1", ["x"]),
    ("invalid UTF-8", "test.Shape", "0a01ff", "name: Expected valid UTF-8 at offset 2", ["name"]),
    (
        "a value past the end of its message",
        "test.Shape",
        "1201 0801",
        "origin.x: Expected a complete value at offset 3",
        ["origin", "x"],
    ),
    (
        "a list element",
        "test.Shape",
        "1a02 0801 1a01 08",
        "points[1].x: Expected a complete value at offset 7",
        ["points", 1, "x"],
    ),
    (
        "a partial packed double",
        "test.Shape",
        "3a09 000000000000f03f 01",
        "weights[1]: Expected a complete value at offset 10",
        ["weights", 1],
    ),
    (
        "a missing required field",
        "legacy.Legacy",
        "1200",
        "id: Expected required field id of legacy.Legacy",
        ["id"],
    ),
    (
        "a stray end group tag",
        "test.Point",
        "3c",
        "Expected a start group tag before the end group tag of field 7",
        [],
    ),
]


@pytest.mark.parametrize(
    ("name", "type_name", "hex_text", "expected", "path"),
    DECODE_FAILURES,
    ids=[c[0] for c in DECODE_FAILURES],
)
def test_fails_to_decode(
    name: str, type_name: str, hex_text: str, expected: str, path: list[str | int]
) -> None:
    """ProtobufMessage / fails to decode / %s"""
    result = protobuf_message.decode(message(type_name))(hexb(hex_text))
    assert failure(result) == {"message": expected, "path": path}, name


def test_messages_nested_deeper_than_max_depth() -> None:
    """ProtobufMessage / fails to decode / messages nested deeper than maxDepth"""
    tree: dict[str, Any] = {"children": [{"children": [{"children": []}]}]}
    tree_descriptor = message("test.Tree")
    encoded = protobuf_message.encode(tree_descriptor)(tree).get_or_raise()
    assert protobuf_message.encode(tree_descriptor, max_depth=2)(tree) == Ok(encoded)
    expected = {
        "message": "children[0].children[0]: Expected messages nested at most 1 deep",
        "path": ["children", 0, "children", 0],
    }
    assert failure(protobuf_message.encode(tree_descriptor, max_depth=1)(tree)) == expected
    assert failure(protobuf_message.decode(tree_descriptor, max_depth=1)(encoded)) == expected


def test_enforces_closed_enums_for_singular_packed_and_map_values() -> None:
    """ProtobufMessage / fails to encode / enforces closed enums for singular, packed and map values
    ProtobufMessage / fails to encode / enforces closed enums for singular, packed and map values"""
    for value in [
        {"id": 1, "mode": 7},
        {"id": 1, "modes": [1, 7]},
        {"id": 1, "mode_by_name": {"a": 7}},
    ]:
        assert isinstance(protobuf_message.encode(message("legacy.Legacy"))(value), Err)
    open_ = {**SHAPE_ZEROS, "color": 7, "colors": [7]}
    assert decode("test.Shape", encode("test.Shape", open_)) == open_


ENCODE_FAILURES: list[tuple[str, str, object, str, list[str | int]]] = [
    (
        "a value of another type",
        "test.Shape",
        {"name": 1},
        "name: Expected a string, got 1",
        ["name"],
    ),
    (
        "a list element",
        "test.Shape",
        {"points": [{"x": 1}, {"x": 1.5}]},
        "points[1].x: Expected an integer for an int32, got 1.5",
        ["points", 1, "x"],
    ),
    (
        "a packed element",
        "test.Shape",
        {"ids": [1, "2"]},
        'ids[1]: Expected an integer for an int32, got "2"',
        ["ids", 1],
    ),
    (
        "an unknown oneof case",
        "test.Shape",
        {"kind": {"_tag": "nope", "value": 1}},
        'kind: Expected a case of oneof kind, got "nope"',
        ["kind"],
    ),
    (
        "a map value",
        "test.Shape",
        {"counts": {"a": "x"}},
        'counts.a: Expected an integer for an int32, got "x"',
        ["counts", "a"],
    ),
    (
        "a map key",
        "test.Shape",
        {"by_id": {"x": "a"}},
        'by_id.x: Expected an integer key for an int64, got "x"',
        ["by_id", "x"],
    ),
    (
        "a uint64 out of range",
        "test.Scalars",
        {"uint64": -1},
        "uint64: Expected a uint64 in range, got -1",
        ["uint64"],
    ),
    (
        "a float out of range",
        "test.Scalars",
        {"float": 1e39},
        "float: Expected a number in the range of a float, got 1e+39",
        ["float"],
    ),
    (
        "a missing required field",
        "legacy.Legacy",
        {},
        "id: Expected a value for required field id",
        ["id"],
    ),
    (
        "something other than an object",
        "test.Point",
        None,
        "Expected an object for test.Point, got None",
        [],
    ),
]


@pytest.mark.parametrize(
    ("name", "type_name", "value", "expected", "path"),
    ENCODE_FAILURES,
    ids=[c[0] for c in ENCODE_FAILURES],
)
def test_fails_to_encode(
    name: str, type_name: str, value: Any, expected: str, path: list[str | int]
) -> None:
    """ProtobufMessage / fails to encode / %s"""
    result = protobuf_message.encode(message(type_name))(value)
    assert failure(result) == {"message": expected, "path": path}, name


def test_validates_message_extensions_after_all_occurrences_have_merged() -> None:
    """ProtobufMessage / extensions / validates message extensions after all occurrences have merged
    ProtobufMessage / extensions / validates message extensions after all occurrences have merged"""
    extension = _extension("legacy.required_child")

    def read(hex_text: str) -> Result[object, ProtobufMessageError]:
        return get_extension({U: hexb(hex_text)}, extension)

    assert read("b20600b206020801") == Ok({"n": 1})
    assert failure(read("b20600"))["path"] == ["required_child", "n"]


def test_sets_replaces_and_clears_an_extension_in_the_unknown_fields() -> None:
    """ProtobufMessage / extensions / sets, replaces and clears an extension in the unknown fields
    ProtobufMessage / extensions / sets, replaces and clears an extension in the unknown fields"""
    priority = _extension("legacy.priority")
    set_ = set_extension({"id": 1}, priority, 3).get_or_raise()
    assert encode("legacy.Legacy", set_) == "0801a00603"
    assert get_extension(set_, priority) == Ok(3)
    replaced = set_extension(set_, priority, 4).get_or_raise()
    assert replaced[U] == hexb("a00604")
    cleared = set_extension(replaced, priority, None).get_or_raise()
    assert U not in cleared
    assert get_extension(cleared, priority) == Ok(None)


def test_reads_an_extension_of_decoded_bytes() -> None:
    """ProtobufMessage / extensions / reads an extension of decoded bytes"""
    assert get_extension(
        decode("legacy.Legacy", "0801 a00603"), _extension("legacy.priority")
    ) == Ok(3)


def test_reads_and_writes_a_repeated_extension() -> None:
    """ProtobufMessage / extensions / reads and writes a repeated extension"""
    labels = _extension("legacy.labels")
    assert get_extension({"id": 1}, labels) == Ok([])
    set_ = set_extension({"id": 1}, labels, ["a", "b"]).get_or_raise()
    assert set_[U] == hexb("aa060161 aa060162")
    assert get_extension(set_, labels) == Ok(["a", "b"])


def test_writes_the_extensions_of_a_message_set_as_items() -> None:
    """ProtobufMessage / extensions / writes the extensions of a MessageSet as items"""
    member = _extension("legacy.SetMember.member")
    set_ = set_extension({}, member, {"text": "a"}).get_or_raise()
    assert set_[U] == hexb("0b 10e807 1a030a0161 0c")
    assert get_extension(set_, member) == Ok({"text": "a"})


@pytest.mark.parametrize(
    ("number", "type_id"),
    [(536870912, "8080808002"), (536870913, "8180808002"), (2147483646, "feffffff07")],
    ids=["536870912", "536870913", "2147483646"],
)
def test_reads_writes_replaces_and_clears_message_set_extension(number: int, type_id: str) -> None:
    """ProtobufMessage / extensions / reads, writes, replaces and clears MessageSet extension %s"""
    descriptors = descriptor.make(
        [
            {
                "name": "message-set.proto",
                "message_type": [
                    {
                        "name": "Container",
                        "options": {"message_set_wire_format": True},
                        "extension_range": [{"start": 4, "end": 2147483647}],
                    },
                    {
                        "name": "Payload",
                        "field": [
                            {"name": "x", "number": 1, "type": 5, "label": 2},
                            {"name": "y", "number": 2, "type": 5, "label": 1},
                        ],
                    },
                ],
                "extension": [
                    {
                        "name": "payload",
                        "number": number,
                        "type": 11,
                        "type_name": ".Payload",
                        "label": 1,
                        "extendee": ".Container",
                    }
                ],
            }
        ]
    ).get_or_raise()
    extension = descriptors.get_extension("payload")
    container = descriptors.get_message("Container")
    assert extension is not None
    assert isinstance(container, MessageDescriptor)
    other = "0b 10e807 1a030a0161 0c"
    wire = hexb(f"{other} 0b 10{type_id} 1a020807 0c")
    decoded = protobuf_message.decode(container)(wire).get_or_raise()
    assert get_extension(decoded, extension) == Ok({"x": 7})
    set_ = set_extension({U: hexb(other)}, extension, {"x": 7}).get_or_raise()
    assert protobuf_message.encode(container)(set_) == Ok(wire)  # pyright: ignore[reportArgumentType]
    assert get_extension(set_, extension) == Ok({"x": 7})
    replaced = set_extension(decoded, extension, {"x": 8}).get_or_raise()
    assert replaced[U] == hexb(f"{other} 0b 10{type_id} 1a020808 0c")
    cleared = set_extension(replaced, extension, None).get_or_raise()
    assert cleared[U] == hexb(other)
    assert get_extension(cleared, extension) == Ok(None)

    # MessageSet payloads merge before required fields are checked.
    merged = {U: hexb(f"0b 10{type_id} 1a021009 0c 0b 10{type_id} 1a020807 0c")}
    assert get_extension(merged, extension) == Ok({"x": 7, "y": 9})
    empty = {U: hexb(f"0b 10{type_id} 1a00 0c")}
    assert failure(get_extension(empty, extension))["path"] == ["payload", "x"]
    assert failure(set_extension({}, extension, {"x": "bad"}))["path"] == ["payload", "x"]


def test_reads_message_set_extensions_encoded_as_ordinary_message_fields() -> None:
    """ProtobufMessage / extensions / reads MessageSet extensions encoded as ordinary message fields
    ProtobufMessage / extensions / reads MessageSet extensions encoded as ordinary message fields"""
    member = _extension("legacy.SetMember.member")
    set_ = {U: hexb("c23e030a0161")}
    assert get_extension(set_, member) == Ok({"text": "a"})
    assert U not in set_extension(set_, member, None).get_or_raise()


def test_uses_the_first_type_id_and_payload_within_each_message_set_item() -> None:
    """ProtobufMessage / extensions / uses the first type id and payload within each MessageSet item
    ProtobufMessage / extensions / uses the first type id and payload within each MessageSet item"""
    member = _extension("legacy.SetMember.member")
    for hex_text in [
        "0b 10e807 1a030a0161 1a030a0162 0c",
        "0b 10e807 1a030a0161 10e907 0c",
        "0b 10e807 10e907 1a030a0161 0c",
        "0b 1a030a0161 1a030a0162 10e807 0c",
        "0b 1a030a0161 10e807 10e907 0c",
    ]:
        set_ = {U: hexb(hex_text)}
        assert get_extension(set_, member) == Ok({"text": "a"}), hex_text
        assert U not in set_extension(set_, member, None).get_or_raise()


def test_ignores_incomplete_message_set_items_and_rejects_zero_type_ids() -> None:
    """ProtobufMessage / extensions / ignores incomplete MessageSet items and rejects zero type ids
    ProtobufMessage / extensions / ignores incomplete MessageSet items and rejects zero type ids"""
    member = _extension("legacy.SetMember.member")
    for hex_text in ["0b 10e807 0c", "0b 1a030a0161 0c"]:
        set_ = {U: hexb(hex_text)}
        assert get_extension(set_, member) == Ok(None)
        assert set_extension(set_, member, None) == Ok(set_)
    for hex_text in ["0b 1000 1a030a0161 0c", "0b 10e807 1a030a0161 1000 0c"]:
        assert isinstance(get_extension({U: hexb(hex_text)}, member), Err)


def test_validates_the_first_message_set_payload_even_when_a_later_payload_is_valid() -> None:
    """ProtobufMessage / extensions / validates the first MessageSet payload even when a later
    payload is valid"""
    set_ = {U: hexb("0b 10e807 1a020a02 1a030a0161 0c")}
    assert failure(get_extension(set_, _extension("legacy.SetMember.member")))["path"] == [
        "member",
        "text",
    ]


def test_rejects_field_values_split_across_message_set_payloads() -> None:
    """ProtobufMessage / extensions / rejects field values split across MessageSet payloads"""
    # The payloads 0a02 and 6162 only form a valid string field when joined.
    for hex_text in [
        "0b10e8071a020a020c0b10e8071a0261620c",
        "c23e020a02c23e026162",
        "0b10e8071a020a020cc23e026162",
    ]:
        result = get_extension({U: hexb(hex_text)}, _extension("legacy.SetMember.member"))
        assert failure(result)["path"] == ["member", "text"], hex_text


def test_retains_owned_unknown_fields_from_every_merged_message_set_payload() -> None:
    """ProtobufMessage / extensions / retains owned unknown fields from every merged MessageSet
    payload"""
    data = bytearray(hexb("0b10e8071a0210010cc23e050a01611802"))
    value = get_extension({U: data}, _extension("legacy.SetMember.member")).get_or_raise()
    data[:] = bytes(len(data))
    assert value == {"text": "a", U: hexb("10011802")}


def test_preserves_incompatible_wire_types_when_replacing_extensions() -> None:
    """ProtobufMessage / extensions / preserves incompatible wire types when replacing extensions"""
    priority = _extension("legacy.priority")
    unknown = {U: hexb("a2060178")}
    assert get_extension(unknown, priority) == Ok(None)
    set_ = set_extension(unknown, priority, 3).get_or_raise()
    assert set_[U] == hexb("a2060178a00603")
    assert get_extension(set_, priority) == Ok(3)
    cleared = set_extension(set_, priority, None).get_or_raise()
    assert cleared[U] == unknown[U]


def test_preserves_unknown_closed_enum_numbers_when_replacing_extensions() -> None:
    """ProtobufMessage / extensions / preserves unknown closed-enum numbers when replacing
    extensions"""
    extension = _extension("legacy.mode_ext")
    original = {U: hexb("b80607b80601")}
    assert get_extension(original, extension) == Ok(1)
    set_ = set_extension(original, extension, 2).get_or_raise()
    assert set_[U] == hexb("b80607b80602")
    cleared = set_extension(set_, extension, None).get_or_raise()
    assert cleared[U] == hexb("b80607")
    assert get_extension(cleared, extension) == Ok(None)


def test_preserves_unknown_numbers_from_packed_closed_enum_extensions() -> None:
    """ProtobufMessage / extensions / preserves unknown numbers from packed closed-enum extensions
    ProtobufMessage / extensions / preserves unknown numbers from packed closed-enum extensions"""
    extension = _extension("legacy.modes_ext")
    original = {U: hexb("c20603010702")}
    assert get_extension(original, extension) == Ok([1, 2])
    set_ = set_extension(original, extension, [2]).get_or_raise()
    assert set_[U] == hexb("c00607c2060102")
    cleared = set_extension(set_, extension, None).get_or_raise()
    assert cleared[U] == hexb("c00607")
    assert get_extension(cleared, extension) == Ok([])


def test_fails_for_a_value_of_another_type() -> None:
    """ProtobufMessage / extensions / fails for a value of another type"""
    assert failure(set_extension({}, _extension("legacy.priority"), "x")) == {
        "message": 'priority: Expected an integer for an int32, got "x"',
        "path": ["priority"],
    }
