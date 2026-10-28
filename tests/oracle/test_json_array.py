"""Ports of Effect's ``encoding/JsonArray.test.ts``.

Each test's docstring is the Effect test title. ``Uint8Array`` is
``bytes``, ``JSON.parse`` is ``json.loads`` and ``Stream.mkString`` is
``run_string``.

Adapted, with the reason:

- "reports a UTF-16 offset across a chunk boundary" expects offset 6
  where Effect expects 7: offsets count characters (Python's string
  indices), and the emoji before the bad value is one character but two
  UTF-16 code units. The cause is the ``json.JSONDecodeError`` that
  ``json.loads`` raised (Effect's ``SyntaxError``).
- "rejects invalid options" leaves out ``maxDepth: 1.5``: ``max_depth`` is
  an ``int``, so pyright rejects a fraction. Bad options raise
  ``ValueError``.
- "fails for values without a JSON representation" passes a function, an
  object and a set where Effect passes ``undefined``, a function and a
  ``bigint``. ``json.dumps`` raises ``TypeError`` for each, so every error
  has a ``TypeError`` cause (Effect's ``undefined`` and function have
  none: ``JSON.stringify`` returns ``undefined`` instead of throwing).
- ``JsonArray.isJsonArrayError`` is ``isinstance``.
"""

import json
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any, TypedDict

import pytest

import pyfect as fx
from pyfect import channel, stream, testing
from pyfect import schema as S
from pyfect.encoding import Json, json_array
from pyfect.encoding.json_array import JsonArrayError


def _decode_chunks(chunks: list[str], **options: Any) -> fx.Effect[list[Json], JsonArrayError]:
    texts = stream.from_arrays(*[(chunk,) for chunk in chunks])
    return texts.pipe_through_channel(json_array.decode_string(**options)).run_collect()


def _decode_error(chunks: list[str], **options: Any) -> fx.Effect[JsonArrayError, list[Json]]:
    return _decode_chunks(chunks, **options).flip()


def _splits(text: str) -> Iterator[list[str]]:
    """Every way of splitting ``text`` into two chunks, plus one-character
    chunks."""
    yield [text]
    yield list(text)
    for i in range(1, len(text)):
        yield [text[:i], text[i:]]


@testing.effect
def test_agrees_with_json_parse_across_chunk_boundaries():
    """agrees with JSON.parse across chunk boundaries"""
    valid = [
        " \t\r\n[] ",
        "[1, -2.5e+3, true, false, null]",
        '["[]{},:\\"", "\\\\", "\\u00e9\\ud83d\\ude00"]',
        '[{"a": [1, {"b": "]}"}]}, [[], {}]]',
        "\r\n[1,\r\n2\r]\n",
    ]
    invalid = ["", "[1,]", "[1 2]", "[1true]", "[1", "[1]]", "[1]x", "[\u00a01]", "[\f1]"]
    for text in valid:
        for chunks in _splits(text):
            assert (yield from _decode_chunks(chunks)) == json.loads(text), chunks
    for text in invalid:
        with pytest.raises(ValueError):
            json.loads(text)
        for chunks in _splits(text):
            assert (yield from _decode_error(chunks)).kind == "Syntax", chunks


# --- decodeString -----------------------------------------------------------------


@testing.effect
def test_emits_one_output_chunk_per_input_chunk():
    """emits one output chunk per input chunk"""
    texts = stream.make("[1,2,", "3", ",4]").rechunk(1)
    chunks = (
        yield from texts.pipe_through_channel(json_array.decode_string()).chunks().run_collect()
    )
    assert chunks == [(1, 2), (3, 4)]


@testing.effect
def test_strips_a_leading_bom():
    """strips a leading BOM"""
    assert (yield from _decode_chunks(["﻿", "[1]"])) == [1]
    error = yield from _decode_error(["[1,﻿2]"])
    assert error.kind == "Syntax"


@testing.effect
def test_reports_a_utf16_offset_across_a_chunk_boundary():
    """reports a UTF-16 offset across a chunk boundary"""
    error = yield from _decode_error(['["😀",', ' {"a": x}]'])
    assert (error.kind, error.offset) == ("Syntax", 6)
    assert isinstance(error.cause, json.JSONDecodeError)


@testing.effect
def test_selects_an_array_through_an_rfc_6901_pointer():
    """selects an array through an RFC 6901 pointer"""
    cases: list[tuple[str, str, Json]] = [
        ('{"before": 0, "items": [1, 2], "after": null}', "/items", [1, 2]),
        ('{"a": [0, {"b": [3]}]}', "/a/1/b", [3]),
        ('{"a/b": {"m~n": [true]}}', "/a~1b/m~0n", [True]),
        ('{"\\u0061": [1]}', "/a", [1]),
        ('{"x": 1, "x": 2, "a": [1]}', "/a", [1]),
    ]
    for text, pointer, expected in cases:
        assert (yield from _decode_chunks(list(text), pointer=pointer)) == expected


@testing.effect
def test_rejects_invalid_pointers_and_malformed_off_path_values():
    """rejects invalid pointers and malformed off-path values"""
    cases = [
        ('{"a": []}', "/b", "Pointer"),
        ('{"a": {}}', "/a", "Pointer"),
        ('{"a": 1}', "/a/b", "Pointer"),
        ('{"a": [], "\\u0061": []}', "/a", "Pointer"),
        ('{"x": [1,], "a": []}', "/a", "Syntax"),
        ('{"a": [1], "x": tru}', "/a", "Syntax"),
    ]
    for text, pointer, kind in cases:
        assert (yield from _decode_error(list(text), pointer=pointer)).kind == kind


@testing.effect
def test_bounds_elements_and_off_path_values_without_overflowing_the_stack():
    """bounds elements and off-path values without overflowing the stack"""
    values = yield from _decode_chunks(['[[1], "abc"]'], max_depth=1, max_element_size=5)
    assert values == [[1], "abc"]
    cases: list[tuple[str, dict[str, Any]]] = [
        ("[[[1]]]", {"max_depth": 1}),
        ('{"x": [[1]], "a": []}', {"pointer": "/a", "max_depth": 1}),
        ('["abcde"]', {"max_element_size": 6}),
        ('{"x": "abcde", "a": []}', {"pointer": "/a", "max_element_size": 6}),
        ("[" * 100000, {}),
    ]
    for text, options in cases:
        error = yield from _decode_error([text], **options)
        assert error.kind == "Limit"
        if options.get("pointer"):
            assert 'Value outside the selected array at "/x"' in error.message


def test_rejects_invalid_options():
    """rejects invalid options"""
    with pytest.raises(ValueError):
        json_array.decode_string(pointer="a")
    with pytest.raises(ValueError):
        json_array.decode_string(pointer="/a~2")
    with pytest.raises(ValueError):
        json_array.decode_string(max_depth=-1)
    with pytest.raises(ValueError):
        json_array.decode_string(max_element_size=0.5)


@testing.effect
def test_passes_through_upstream_failures_and_the_done_value():
    """passes through upstream failures and the done value"""
    failing = stream.make("[1,").concat(stream.fail("upstream"))
    error = yield from failing.pipe_through_channel(json_array.decode_string()).run_collect().flip()
    assert error == "upstream"

    def items():
        yield ("[1]",)
        return "done"

    upstream = channel.from_iterator(items)
    done = yield from upstream.pipe_to(json_array.decode_string()).run_drain()
    assert done == "done"


# --- decode -----------------------------------------------------------------------


@testing.effect
def test_rejects_truncated_utf8_after_a_complete_array_at_eof():
    """rejects truncated UTF-8 after a complete array at EOF"""
    data = stream.make(bytes([0x5B, 0x31, 0x5D, 0xC3]))
    error = yield from data.pipe_through_channel(json_array.decode()).run_collect().flip()
    assert error.kind == "Syntax"


@testing.effect
def test_decodes_utf8_split_at_every_byte():
    """decodes UTF-8 split at every byte"""
    encoded = '﻿["é", "😀", {"ключ": "値"}]'.encode()
    for i in range(len(encoded) + 1):
        data = stream.make(encoded[:i], encoded[i:])
        values = yield from data.pipe_through_channel(json_array.decode()).run_collect()
        assert values == ["é", "😀", {"ключ": "値"}]


# --- encodeString -----------------------------------------------------------------


@testing.effect
def test_writes_one_json_array():
    """writes one JSON array"""
    empty: fx.Stream[int] = stream.empty
    assert (yield from empty.pipe_through_channel(json_array.encode_string()).run_string()) == "[]"
    values = stream.make(1, 2, 3).rechunk(2)
    chunks = yield from values.pipe_through_channel(json_array.encode_string()).run_collect()
    assert json.loads("".join(chunks)) == [1, 2, 3]


@testing.effect
def test_fails_for_values_without_a_json_representation():
    """fails for values without a JSON representation"""
    inputs: list[Any] = [lambda: None, object(), {1, 2}]
    for value in inputs:
        values = stream.make(value).pipe_through_channel(json_array.encode_string())
        error = yield from values.run_collect().flip()
        assert isinstance(error, JsonArrayError)
        assert error.kind == "Encode"
        assert error.offset is None
        assert isinstance(error.cause, TypeError)


# --- schemas ----------------------------------------------------------------------


class _Item(TypedDict):
    id: float
    at: datetime


Item = S.Struct(_Item, at=S.DateTimeUtcFromString)


@testing.effect
def test_schemas_decode_schema_decodes_elements():
    """schemas: decodeSchema decodes elements"""
    body = b'{"items": [{"id": 1, "at": "2024-01-01T00:00:00Z"}]}'
    values = yield from (
        stream.make(body)
        .pipe_through_channel(json_array.decode_schema(Item, pointer="/items"))
        .run_collect()
    )
    assert values[0]["id"] == 1
    assert values[0]["at"] == datetime(2024, 1, 1, tzinfo=UTC)


@testing.effect
def test_schemas_decode_schema_string_fails_with_a_schema_error():
    """schemas: decodeSchemaString fails with a SchemaError"""
    error = yield from (
        stream.make('[{"id": "1", "at": "2024-01-01T00:00:00Z"}]')
        .pipe_through_channel(json_array.decode_schema_string(Item))
        .run_collect()
        .flip()
    )
    assert isinstance(error, S.SchemaError)


@testing.effect
def test_schemas_encode_schema_round_trips_through_decode_schema():
    """schemas: encodeSchema round trips through decodeSchema"""
    decoded = yield from S.decode_effect(Item)({"id": 1, "at": "2024-01-01T00:00:00Z"})
    value: _Item = {"id": 1, "at": decoded["at"]}
    text = yield from (
        stream.make(value).pipe_through_channel(json_array.encode_schema_string(Item)).run_string()
    )
    assert text == '[{"id":1,"at":"2024-01-01T00:00:00.000Z"}]'
    values = yield from (
        stream.make(value)
        .pipe_through_channel(json_array.encode_schema(Item))
        .pipe_through_channel(json_array.decode_schema(Item))
        .run_collect()
    )
    assert values == [value]
