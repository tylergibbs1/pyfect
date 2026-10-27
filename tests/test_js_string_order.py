"""JavaScript sorts strings by UTF-16 code units, Python by code points:
they disagree when a character above U+FFFF meets one in U+E000..U+FFFF.
Ports of Effect code that sorts strings use ``_js.js_sort_key``; expected
values printed by Effect under Node."""

import ast
from pathlib import Path

from pyfect import json_patch
from pyfect import json_schema as JS
from pyfect._js import js_sort_key

SRC = Path(__file__).parent.parent / "src" / "pyfect"
_ASTRAL = "\U00010000"
_HIGH_BMP = "￿"


def test_js_sort_key_orders_by_utf16_code_units():
    assert sorted([_HIGH_BMP, _ASTRAL, "a"], key=js_sort_key) == ["a", _ASTRAL, _HIGH_BMP]


def test_json_patch_get_visits_keys_in_javascript_order():
    patch = json_patch.get({_HIGH_BMP: 1, _ASTRAL: 1, "a": 1}, {})
    assert [op["path"] for op in patch] == ["/a", f"/{_ASTRAL}", f"/{_HIGH_BMP}"]


def test_open_api_sanitized_keys_collide_in_javascript_order():
    document = JS.MultiDocument(
        "draft-2020-12",
        ({"$ref": "#/$defs/%F0%90%80%80"}, {"$ref": "#/$defs/%EF%BF%BF"}),
        {_ASTRAL: {"type": "string"}, _HIGH_BMP: {"type": "number"}},
    )
    out = JS.to_multi_document_open_api_3_1(document)
    assert out.schemas == ({"$ref": "#/components/schemas/_"}, {"$ref": "#/components/schemas/__1"})
    assert out.definitions == {"_": {"type": "string"}, "__1": {"type": "number"}}


_JSON_PORTS = [
    SRC / "json_patch.py",
    SRC / "json_pointer.py",
    *sorted((SRC / "json_schema").rglob("*.py")),
    *sorted((SRC / "schema" / "_jsonschema").rglob("*.py")),
]


def test_json_ports_sort_strings_with_the_javascript_key():
    """A bare ``sorted(...)`` in a JSON port orders strings by code point;
    each call must state its ``key`` (``js_sort_key`` for strings)."""
    bare = [
        f"{path.relative_to(SRC)}:{node.lineno}"
        for path in _JSON_PORTS
        for node in ast.walk(ast.parse(path.read_text()))
        if isinstance(node, ast.Call)
        and (
            (isinstance(node.func, ast.Name) and node.func.id == "sorted")
            or (isinstance(node.func, ast.Attribute) and node.func.attr == "sort")
        )
        and not any(keyword.arg == "key" for keyword in node.keywords)
    ]
    assert bare == []
