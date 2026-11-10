"""``S.HashSet`` / ``S.HashMap`` against Effect 4.1.2 under Node: JSON writes the
values (or ``[key, value]`` pairs) in Effect's hash order, issues land where
Effect puts them, and the JSON Schema and representation are Effect's."""

import pytest

from pyfect import schema as S
from pyfect.hash_map import HashMap
from pyfect.hash_set import HashSet
from pyfect.schema import representation as R


def test_json_writes_values_and_entries_in_effects_hash_order():
    """Effect: ``encodeSync(toCodecJson(HashSet(Number)))(HashSet.make(3, 1, 2, 10,
    100, -5, 0.5, 1e21))`` is ``[1,2,3,100,0.5,10,1e+21,-5]``, and so on."""
    numbers = S.encode_sync(S.to_codec_json(S.HashSet(S.Number)))
    assert numbers(HashSet.make(3, 1, 2, 10, 100, -5, 0.5, 1e21)) == (
        1,
        2,
        3,
        100,
        0.5,
        10,
        1e21,
        -5,
    )
    strings = S.encode_sync(S.to_codec_json(S.HashSet(S.String)))
    assert strings(HashSet.make("b", "a", "c", "hello", "")) == ("a", "", "c", "b", "hello")
    entries = S.encode_sync(S.to_codec_json(S.HashMap(S.String, S.Number)))
    assert entries(HashMap.make(("b", 1), ("a", 2), ("c", 3), ("zz", 4))) == (
        ("a", 2),
        ("zz", 4),
        ("c", 3),
        ("b", 1),
    )


def test_decoding_issues_are_where_effect_reports_them():
    json_set = S.decode_unknown_sync(S.to_codec_json(S.HashSet(S.Number)))
    with pytest.raises(
        S.SchemaError, match=r'^Expected "Infinity" \| "-Infinity" \| "NaN"\n  at \[1\]$'
    ):
        json_set([1, "x"])
    with pytest.raises(S.SchemaError, match=r"^Expected array$"):
        json_set({})
    json_map = S.decode_unknown_sync(S.to_codec_json(S.HashMap(S.String, S.Number)))
    with pytest.raises(S.SchemaError, match=r"^Missing key\n  at \[1\]\[1\]$"):
        json_map([["a", 1], ["b"]])
    with pytest.raises(S.SchemaError, match=r"^Expected HashMap$"):
        S.decode_unknown_sync(S.HashMap(S.String, S.Number))({})
    with pytest.raises(S.SchemaError, match=r"^Expected a value with a size of at least 2$"):
        S.decode_unknown_sync(S.HashSet(S.String).check(S.is_min_size(2)))(HashSet.make("a"))


def test_json_schema_is_the_array_effect_writes():
    assert S.to_json_schema_document(S.HashSet(S.String)).schema == {
        "type": "array",
        "items": {"type": "string"},
    }
    assert S.to_json_schema_document(S.HashMap(S.String, S.Number)).schema == {
        "type": "array",
        "items": {
            "type": "array",
            "prefixItems": [
                {"type": "string"},
                {
                    "anyOf": [
                        {"type": "number"},
                        {"type": "string", "enum": ["Infinity", "-Infinity", "NaN"]},
                    ]
                },
            ],
            "maxItems": 2,
            "minItems": 2,
        },
    }


def test_representation_is_effects_declaration():
    assert R.to_json(R.to_representation(S.HashSet(S.String))) == {
        "representation": {
            "_tag": "Declaration",
            "checks": [],
            "annotations": {"expected": "HashSet"},
            "representation": {"id": "effect/schema/HashSet", "payload": None},
            "typeParameters": [{"_tag": "String", "checks": []}],
        },
        "references": {},
    }


def test_nested_sets_format_sorted():
    """Effect: ``HashSet(2) { HashSet(0) {}, HashSet(2) { 1, 2 } }``."""
    format = S.to_formatter(S.HashSet(S.HashSet(S.Number)))
    value = HashSet.make(HashSet.make(2.0, 1.0), HashSet[float].empty())
    assert format(value) == "HashSet(2) { HashSet(0) {}, HashSet(2) { 1, 2 } }"
