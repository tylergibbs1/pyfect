"""Ports of Effect's ``Schema.ObjectKeyword`` titles: ``schema/Schema.test.ts``,
``schema/toCodec.test.ts`` (JSON, string tree, XML), ``schema/toFormatter.test.ts``,
``schema/toJsonSchemaDocument.test.ts`` and ``effect/test/Config.test.ts``; and of the
``ObjectKeyword``, ``Void`` and ``Undefined`` nodes in ``schema/representation/*.test.ts``.

``{ a: 1n }``, which is no JSON, is ``{"a": object()}`` here, as a Python ``int`` is JSON.
"""

from typing import Any, cast

import pytest

import pyfect as fx
from pyfect import config
from pyfect import schema as S
from pyfect.exit import Success
from pyfect.schema import representation as R
from pyfect.testing import SchemaAsserts

_EXPECTED = "Expected object | array | function"


def test_object_keyword() -> None:
    """ObjectKeyword (schema/Schema.test.ts)"""
    asserts = SchemaAsserts(S.ObjectKeyword)
    make = asserts.make()
    make.succeed({})
    make.succeed([])
    make.fail(None, _EXPECTED)
    decoding = asserts.decoding()
    decoding.succeed({})
    decoding.succeed([])
    decoding.fail("1", _EXPECTED)
    encoding = asserts.encoding()
    encoding.succeed({})
    encoding.succeed([])
    encoding.fail("1", _EXPECTED)


def test_object_keyword_takes_any_object_javascript_would() -> None:
    # Node: Schema.is(ObjectKeyword) of a Uint8Array and a function are true.
    is_object = S.is_(S.ObjectKeyword)
    assert is_object(b"a")
    assert is_object(print)
    assert not is_object(True)


def test_object_keyword_to_codec_json() -> None:
    """toCodecJson: ObjectKeyword"""
    asserts = SchemaAsserts(S.to_codec_json(S.ObjectKeyword))
    encoding = asserts.encoding()
    encoding.succeed({"a": "a", "b": 1, "c": True})
    encoding.succeed(["a", 1, True])
    encoding.fail("a", _EXPECTED)
    encoding.fail({"a": object()}, 'Expected JSON value\n  at ["a"]')
    decoding = asserts.decoding()
    decoding.succeed({"a": "a", "b": 1, "c": True})
    decoding.succeed(["a", 1, True])
    decoding.fail("a", "Expected array | object")
    decoding.fail({"a": object()}, 'Expected JSON value\n  at ["a"]')


def test_object_keyword_to_codec_string_tree() -> None:
    """toCodecStringTree: ObjectKeyword"""
    asserts = SchemaAsserts(S.to_codec_string_tree(S.ObjectKeyword))
    encoding = asserts.encoding()
    encoding.fail("a", _EXPECTED)
    encoding.fail(1, _EXPECTED)
    encoding.succeed({"a": "a"})
    encoding.succeed(["a"])
    encoding.fail({"a": 1}, "Expected StringTree")
    decoding = asserts.decoding()
    decoding.fail("a", _EXPECTED)
    decoding.fail(1, "Expected StringTree")
    decoding.succeed({"a": "a"})
    decoding.succeed(["a"])
    decoding.fail({"a": 1}, "Expected StringTree")


def test_object_keyword_to_encoder_xml() -> None:
    """toEncoderXml: ObjectKeyword"""
    serializer = S.to_encoder_xml(S.to_codec_string_tree(S.ObjectKeyword))
    written = fx.run_blocking(serializer({"a": "value"}).exit())
    assert written == Success("<root>\n  <a>value</a>\n</root>")


def test_object_keyword_to_formatter() -> None:
    """toFormatter: ObjectKeyword"""
    format_value = S.to_formatter(S.ObjectKeyword)
    assert format_value({}) == "{}"
    assert format_value({"a": 1}) == '{"a":1}'
    assert format_value([1, 2, 3]) == "[1,2,3]"


def test_object_keyword_to_json_schema_document() -> None:
    """toJsonSchemaDocument: ObjectKeyword"""
    expected = {"anyOf": [{"type": "array"}, {"type": "object"}]}
    assert S.to_json_schema_document(S.ObjectKeyword).schema == expected
    described = S.ObjectKeyword.annotate(description="a")
    assert S.to_json_schema_document(described).schema == expected


def test_rejects_schema_object_keyword() -> None:
    """Opaque schemas: rejects Schema.ObjectKeyword"""
    with pytest.raises(
        ValueError, match=r"Config\.schema does not support opaque StringTree encodings"
    ):
        config.schema(S.ObjectKeyword)


_KEYWORDS: list[tuple[str, Any, str, str, dict[str, object]]] = [
    (
        "ObjectKeyword",
        S.ObjectKeyword,
        "S.ObjectKeyword",
        "object",
        {"anyOf": [{"type": "object"}, {"type": "array"}]},
    ),
    ("Void", S.Void, "S.Void", "None", {"type": "null"}),
    ("Undefined", S.Undefined, "S.Undefined", "None", {"type": "null"}),
]
_IDS = [case[0] for case in _KEYWORDS]


@pytest.mark.parametrize(("tag", "schema", "runtime", "type", "json_schema"), _KEYWORDS, ids=_IDS)
def test_keyword_representation(
    tag: str, schema: Any, runtime: str, type: str, json_schema: dict[str, object]
) -> None:
    """toRepresentation / fromJson / revives / toCodeDocument / toJsonSchemaDocument of the
    keywords: ObjectKeyword, Void, Undefined."""
    document = R.to_representation(schema)
    expected: dict[str, object] = {
        "representation": {"_tag": tag, "checks": cast("list[object]", [])},
        "references": cast("dict[str, object]", {}),
    }
    assert R.to_json(document) == expected
    assert R.to_json(R.from_json(expected)) == expected
    assert R.to_json(R.to_representation(R.from_representation(document, revivers=()))) == expected
    code = R.to_code_document(R.to_multi_document(document)).codes[0]
    assert (code.runtime, code.type) == (runtime, type)
    assert R.to_json_schema_document(document).schema == json_schema


@pytest.mark.parametrize(("tag", "schema", "runtime", "type", "json_schema"), _KEYWORDS, ids=_IDS)
def test_annotated_keyword_representation(
    tag: str, schema: Any, runtime: str, type: str, json_schema: dict[str, object]
) -> None:
    del tag, json_schema
    document = R.to_representation(schema.annotate(description="a"))
    code = R.to_code_document(R.to_multi_document(document)).codes[0]
    assert (code.runtime, code.type) == (f'{runtime}.annotate(description="a")', type)


@pytest.mark.parametrize(("tag", "schema", "runtime", "type", "json_schema"), _KEYWORDS, ids=_IDS)
def test_a_revived_keyword_parses_as_the_keyword(
    tag: str, schema: Any, runtime: str, type: str, json_schema: dict[str, object]
) -> None:
    del runtime, type, json_schema
    revived = R.from_representation(R.to_representation(schema), revivers=())
    assert S.is_(revived)({}) is (tag != "Undefined")
