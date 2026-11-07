"""Ports of the ``toEncoderXml`` section of Effect's ``test/schema/toCodec.test.ts``.

Omitted: "Symbol", "Record with Symbol Keys": a Python schema has no symbol."""
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false, reportUnknownLambdaType=false

from __future__ import annotations

from typing import Any, Literal, TypedDict

import pytest

import pyfect as fx
from pyfect import schema as S

_Spaced = TypedDict("_Spaced", {"a": float, "a b": float})


class _Profile(TypedDict):
    name: str
    age: float


class _Nested(TypedDict):
    user: _Profile
    tags: list[str]


class _Ab(TypedDict):
    a: float
    b: str


class _A1(TypedDict):
    a: float


class _Zam(TypedDict):
    z: float
    a: float
    m: float


class _Tree(TypedDict):
    value: float
    children: Any


def _assert_xml(schema: Any, value: object, expected: str) -> None:
    serializer: Any = S.to_encoder_xml(S.to_codec_string_tree(schema))
    assert fx.run_sync(serializer(value)) == expected


def _assert_failure(schema: Any, value: object, message: str) -> None:
    serializer: Any = S.to_encoder_xml(S.to_codec_string_tree(schema))
    exit = fx.run_sync_exit(serializer(value))
    assert isinstance(exit, fx.Failure)
    assert str(exit.cause.squash()) == message


def test_declaration() -> None:
    """toEncoderXml / Schemas without annotations / Declaration"""
    with pytest.raises(ValueError, match="Missing structural codec for StringTree"):
        S.to_encoder_xml(S.instance_of(complex))


def test_unknown() -> None:
    """toEncoderXml / Schemas without annotations / Unknown"""
    _assert_xml(S.Unknown, "value", "<root>value</root>")


def test_object_keyword() -> None:
    """toEncoderXml / Schemas without annotations / ObjectKeyword"""
    _assert_xml(S.Unknown, {"a": "value"}, "<root>\n  <a>value</a>\n</root>")


def test_identifier_root() -> None:
    """toEncoderXml / should use the identifier as the root name"""
    _assert_xml(S.String.annotate(identifier="a"), "value", "<a>value</a>")
    _assert_xml(S.String.annotate(identifier="a b"), "value", '<a_b data-name="a b">value</a_b>')
    _assert_xml(S.String.annotate(identifier="a", title="b"), "value", "<a>value</a>")


def test_title_root() -> None:
    """toEncoderXml / should use the title as the root name"""
    _assert_xml(S.String.annotate(title="a"), "value", "<a>value</a>")
    _assert_xml(S.String.annotate(title="a b"), "value", '<a_b data-name="a b">value</a_b>')


def test_escape_text() -> None:
    """toEncoderXml / should escape the text"""
    _assert_xml(S.String, "value&", "<root>value&amp;</root>")
    _assert_xml(S.String, "<value/>", "<root>&lt;value/&gt;</root>")


def test_escape_attributes() -> None:
    """toEncoderXml / should escape the attributes"""
    _assert_xml(S.String.annotate(title="value&"), "", '<value_ data-name="value&amp;"></value_>')
    _assert_xml(
        S.String.annotate(title="<value/>"),
        "",
        '<__value__ data-name="&lt;value/&gt;"></__value__>',
    )


def test_never() -> None:
    """toEncoderXml / Never"""
    _assert_failure(S.Never, "test", "Expected never")


def test_any() -> None:
    """toEncoderXml / Any"""
    _assert_xml(S.Any, "test", "<root>test</root>")
    _assert_xml(S.Any, 42, "<root>42</root>")
    _assert_xml(S.Any, {"a": 1}, "<root>\n  <a>1</a>\n</root>")


def test_void() -> None:
    """toEncoderXml / Void"""
    _assert_xml(S.Void, None, "<root/>")


def test_undefined() -> None:
    """toEncoderXml / Undefined"""
    _assert_xml(S.Undefined, None, "<root/>")


def test_null() -> None:
    """toEncoderXml / Null"""
    _assert_xml(S.Null, None, "<root>null</root>")


def test_number() -> None:
    """toEncoderXml / Number"""
    _assert_xml(S.Number, 1, "<root>1</root>")
    _assert_xml(S.Number, 0, "<root>0</root>")
    _assert_xml(S.Number, -1.5, "<root>-1.5</root>")
    _assert_xml(S.Number, float("inf"), "<root>Infinity</root>")
    _assert_xml(S.Number, float("-inf"), "<root>-Infinity</root>")
    _assert_xml(S.Number, float("nan"), "<root>NaN</root>")


def test_boolean() -> None:
    """toEncoderXml / Boolean"""
    _assert_xml(S.Boolean, True, "<root>true</root>")
    _assert_xml(S.Boolean, False, "<root>false</root>")


def test_big_int() -> None:
    """toEncoderXml / BigInt"""
    _assert_xml(S.BigInt, 42, "<root>42</root>")
    _assert_xml(S.BigInt, 0, "<root>0</root>")
    _assert_xml(S.BigInt, -123, "<root>-123</root>")


def test_template_literal() -> None:
    """toEncoderXml / TemplateLiteral"""
    schema = S.TemplateLiteral("Hello ", S.String, "!")
    _assert_xml(schema, "Hello World!", "<root>Hello World!</root>")


def test_struct() -> None:
    """toEncoderXml / Struct"""
    _assert_xml(
        S.Struct(_Spaced),
        {"a": 1, "a b": 2},
        '<root>\n  <a>1</a>\n  <a_b data-name="a b">2</a_b>\n</root>',
    )


def test_array() -> None:
    """toEncoderXml / Array"""
    _assert_xml(S.Array(S.Number), [], "<root/>")
    _assert_xml(
        S.Array(S.Number),
        [1, 2, 3],
        "<root>\n  <item>1</item>\n  <item>2</item>\n  <item>3</item>\n</root>",
    )


def test_array_with_custom_item_name() -> None:
    """toEncoderXml / Array with custom item name"""
    serializer: Any = S.to_encoder_xml(
        S.to_codec_string_tree(S.Array(S.Number)), array_item_name="number"
    )
    assert fx.run_sync(serializer((1, 2, 3))) == (
        "<root>\n  <number>1</number>\n  <number>2</number>\n  <number>3</number>\n</root>"
    )


def test_union() -> None:
    """toEncoderXml / Union"""
    _assert_xml(S.Union(S.String, S.Number), "test", "<root>test</root>")
    _assert_xml(S.Union(S.String, S.Number), 42, "<root>42</root>")


def test_tuple() -> None:
    """toEncoderXml / Tuple"""
    _assert_xml(S.Tuple(), [], "<root/>")
    _assert_xml(
        S.Tuple(S.String, S.Number, S.Boolean),
        ["a", 1, True],
        "<root>\n  <item>a</item>\n  <item>1</item>\n  <item>true</item>\n</root>",
    )


def test_record() -> None:
    """toEncoderXml / Record"""
    _assert_xml(S.Record(S.String, S.Number), {}, "<root/>")
    _assert_xml(
        S.Record(S.String, S.Number), {"a": 1, "b": 2}, "<root>\n  <a>1</a>\n  <b>2</b>\n</root>"
    )


def test_null_or() -> None:
    """toEncoderXml / NullOr"""
    _assert_xml(S.NullOr(S.String), "test", "<root>test</root>")
    _assert_xml(S.NullOr(S.String), None, "<root>null</root>")


class _A(TypedDict):
    _tag: Literal["A"]
    value: str


class _B(TypedDict):
    _tag: Literal["B"]
    value: float


def test_tagged_union() -> None:
    """toEncoderXml / TaggedUnion"""
    schema = S.Union(S.Struct(_A), S.Struct(_B))
    _assert_xml(
        schema,
        {"_tag": "A", "value": "test"},
        "<root>\n  <_tag>A</_tag>\n  <value>test</value>\n</root>",
    )
    _assert_xml(
        schema,
        {"_tag": "B", "value": 42},
        "<root>\n  <_tag>B</_tag>\n  <value>42</value>\n</root>",
    )


class _User(TypedDict):
    _tag: Literal["User"]
    name: str
    age: float


def test_tagged_struct() -> None:
    """toEncoderXml / TaggedStruct"""
    _assert_xml(
        S.Struct(_User),
        {"_tag": "User", "name": "John", "age": 30},
        "<root>\n  <_tag>User</_tag>\n  <age>30</age>\n  <name>John</name>\n</root>",
    )


def test_literals() -> None:
    """toEncoderXml / Literals"""
    schema = S.Literals("a", 1, True)
    _assert_xml(schema, "a", "<root>a</root>")
    _assert_xml(schema, 1, "<root>1</root>")
    _assert_xml(schema, True, "<root>true</root>")


def test_nested_structures() -> None:
    """toEncoderXml / Nested Structures"""
    _assert_xml(
        S.Struct(_Nested),
        {"user": {"name": "John", "age": 30}, "tags": ["admin", "user"]},
        "<root>\n  <tags>\n    <item>admin</item>\n    <item>user</item>\n  </tags>\n"
        "  <user>\n    <age>30</age>\n    <name>John</name>\n  </user>\n</root>",
    )


def test_special_characters_in_text() -> None:
    """toEncoderXml / Special Characters in Text"""
    _assert_xml(S.String, "&<>\"'", "<root>&amp;&lt;&gt;\"'</root>")
    _assert_xml(S.String, "line1\nline2", "<root>line1\nline2</root>")
    _assert_xml(S.String, "tab\there", "<root>tab\there</root>")


def test_special_characters_in_attributes() -> None:
    """toEncoderXml / Special Characters in Attributes"""
    _assert_xml(
        S.String.annotate(title="test&value"),
        "content",
        '<test_value data-name="test&amp;value">content</test_value>',
    )
    _assert_xml(
        S.String.annotate(title="test<value>"),
        "content",
        '<test_value_ data-name="test&lt;value&gt;">content</test_value_>',
    )
    _assert_xml(
        S.String.annotate(title='test"value'),
        "content",
        '<test_value data-name="test&quot;value">content</test_value>',
    )


def test_xml_reserved_names() -> None:
    """toEncoderXml / XML Reserved Names"""
    for title in ("xml", "XML", "xmlns"):
        _assert_xml(
            S.String.annotate(title=title),
            "content",
            f'<_{title} data-name="{title}">content</_{title}>',
        )


def test_invalid_xml_tag_names() -> None:
    """toEncoderXml / Invalid XML Tag Names"""
    _assert_xml(
        S.String.annotate(title="123invalid"),
        "content",
        '<_123invalid data-name="123invalid">content</_123invalid>',
    )
    _assert_xml(
        S.String.annotate(title="invalid name"),
        "content",
        '<invalid_name data-name="invalid name">content</invalid_name>',
    )


def test_empty_string() -> None:
    """toEncoderXml / Empty String"""
    _assert_xml(S.String, "", "<root></root>")


def test_whitespace_only_string() -> None:
    """toEncoderXml / Whitespace Only String"""
    _assert_xml(S.String, "   ", "<root>   </root>")
    _assert_xml(S.String, "\n\t", "<root>\n\t</root>")


def test_unicode_characters() -> None:
    """toEncoderXml / Unicode Characters"""
    _assert_xml(S.String, "Hello 世界", "<root>Hello 世界</root>")
    _assert_xml(S.String, "🚀🌟✨", "<root>🚀🌟✨</root>")
    _assert_xml(S.String, "αβγδε", "<root>αβγδε</root>")


def test_option_root_name() -> None:
    """toEncoderXml / XML Encoder Options - rootName"""
    serializer: Any = S.to_encoder_xml(S.to_codec_string_tree(S.String), root_name="custom")
    assert fx.run_sync(serializer("test")) == "<custom>test</custom>"


def test_option_pretty_false() -> None:
    """toEncoderXml / XML Encoder Options - pretty: false"""
    schema = S.to_codec_string_tree(S.Struct(_Ab))
    serializer: Any = S.to_encoder_xml(schema, pretty=False)
    assert fx.run_sync(serializer({"a": 1, "b": "test"})) == "<root><a>1</a><b>test</b></root>"


def test_option_custom_indent() -> None:
    """toEncoderXml / XML Encoder Options - custom indent"""
    schema = S.to_codec_string_tree(S.Struct(_A1))
    serializer: Any = S.to_encoder_xml(schema, indent="    ")
    assert fx.run_sync(serializer({"a": 1})) == "<root>\n    <a>1</a>\n</root>"


def test_option_sort_keys_false() -> None:
    """toEncoderXml / XML Encoder Options - sortKeys: false"""
    schema = S.to_codec_string_tree(S.Struct(_Zam))
    serializer: Any = S.to_encoder_xml(schema, sort_keys=False)
    assert fx.run_sync(serializer({"z": 3, "a": 1, "m": 2})) == (
        "<root>\n  <z>3</z>\n  <a>1</a>\n  <m>2</m>\n</root>"
    )


def test_circular_reference_detection() -> None:
    """toEncoderXml / Circular Reference Detection"""
    obj: dict[str, Any] = {"name": "test"}
    obj["self"] = obj
    serializer: Any = S.to_encoder_xml(S.to_codec_string_tree(S.Any))
    exit = fx.run_sync_exit(serializer(obj))
    assert isinstance(exit, fx.Failure)
    defect = exit.cause.squash()
    assert str(defect) == "Cycle detected while serializing to XML."


def test_shared_reference_is_no_cycle() -> None:
    """A value met twice but not inside itself is written twice, as ``seen.delete`` allows."""
    shared = {"a": "1"}
    serializer: Any = S.to_encoder_xml(S.to_codec_string_tree(S.Any))
    assert fx.run_sync(serializer({"x": shared, "y": shared})) == (
        "<root>\n  <x>\n    <a>1</a>\n  </x>\n  <y>\n    <a>1</a>\n  </y>\n</root>"
    )


def test_record_with_number_keys() -> None:
    """toEncoderXml / Record with Number Keys"""
    _assert_xml(
        S.Record(S.Number, S.String),
        {1: "one", 2: "two"},
        '<root>\n  <_1 data-name="1">one</_1>\n  <_2 data-name="2">two</_2>\n</root>',
    )


def test_tuple_with_rest() -> None:
    """toEncoderXml / Tuple with Rest"""
    _assert_xml(
        S.TupleWithRest(S.Tuple(S.String, S.Number), S.Boolean),
        ["test", 42, True, False],
        "<root>\n  <item>test</item>\n  <item>42</item>\n  <item>true</item>\n"
        "  <item>false</item>\n</root>",
    )


def test_suspend() -> None:
    """toEncoderXml / Suspend (Recursive Types)"""
    tree: Any = S.Struct(_Tree, children=S.Array(S.suspend(lambda: tree)))
    _assert_xml(
        tree,
        {
            "value": 1,
            "children": [{"value": 2, "children": []}, {"value": 3, "children": []}],
        },
        "<root>\n  <children>\n    <item>\n      <children/>\n      <value>2</value>\n"
        "    </item>\n    <item>\n      <children/>\n      <value>3</value>\n    </item>\n"
        "  </children>\n  <value>1</value>\n</root>",
    )
