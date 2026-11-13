"""The guard for JavaScript's text rules (QA schema-data, root cause of F09,
F13): where Effect's ``JSON.stringify`` / ``String(value)`` output is the
contract, Python's ``json`` and ``repr`` must not write it.

Every JSON text goes through ``pyfect._json_text`` (``parse``,
``stringify``, ``quote``), the only module importing ``json``. In the
message-formatting and wire modules, ``repr`` / ``!r`` appear only in
``__repr__`` methods and in the messages of raised programming errors;
numbers there are written with ``pyfect._js.js_number`` / ``js_string``.
"""

from __future__ import annotations

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src" / "pyfect"

_JSON_HOME = {"_json_text.py"}
# Where Effect's text is the contract: issue messages, formatters, codecs.
_FORMATTING = ("schema", "logger", "encoding", "date_time/_iso.py", "_json_text.py")
# ``_js.py`` turns Python's shortest float spelling into JavaScript's; the
# others raise class-definition errors naming Python annotations and keys, or
# (``_code_builtins``, the schema compiler's ``_codegen``) write Python source,
# where ``repr`` is the right spelling.
_REPR_HOME = {
    "_js.py",
    "schema/compiler/_codegen.py",
    "schema/_derive.py",
    "schema/model/_class.py",
    "schema/representation/_code_builtins.py",
}


def _modules() -> list[tuple[str, ast.Module]]:
    return [
        (str(path.relative_to(SRC)), ast.parse(path.read_text(), str(path)))
        for path in sorted(SRC.rglob("*.py"))
    ]


# Python's ``json`` and the libraries modelled on it raise on (or write) ``NaN``
# and infinities where ``JSON.stringify`` writes ``null`` (GQL-1).
_JSON_LIBRARIES = {"json", "simplejson", "orjson", "ujson", "rapidjson"}


def _imported_modules(node: ast.AST) -> list[str]:
    """The modules ``node`` imports: an import statement, a call of
    ``__import__`` / ``import_module`` with a literal name, or
    ``msgspec.json``."""
    match node:
        case ast.Attribute(value=ast.Name(id="msgspec"), attr="json"):
            return ["msgspec.json"]
        case ast.Import(names=names):
            return [alias.name for alias in names]
        case ast.ImportFrom(module=module):
            return [module or ""]
        case ast.Call(func=ast.Name(id="__import__") | ast.Attribute(attr="import_module")):
            return [
                arg.value
                for arg in node.args[:1]
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str)
            ]
        case _:
            return []


def _is_json_library(module: str) -> bool:
    return module.partition(".")[0] in _JSON_LIBRARIES or module.startswith("msgspec.json")


def test_only_json_text_imports_json():
    offenders = [
        f"{name}:{getattr(node, 'lineno', 0)}"
        for name, tree in _modules()
        if name not in _JSON_HOME
        for node in ast.walk(tree)
        if any(_is_json_library(str(m)) for m in _imported_modules(node))
    ]
    assert offenders == [], "use pyfect._json_text (parse / stringify / quote)"


def test_the_guard_sees_every_way_of_importing_json():
    source = """
import json
import json.decoder
from json import dumps
import orjson
__import__("json")
importlib.import_module("ujson")
msgspec.json.encode(x)
"""
    found = [m for node in ast.walk(ast.parse(source)) for m in _imported_modules(node)]
    assert all(_is_json_library(m) for m in found)
    assert len(found) == 7


def _exempt_nodes(tree: ast.Module) -> set[int]:
    """Nodes inside ``__repr__`` methods, ``raise`` statements and
    ``Decimal(repr(x))`` (exact decimal arithmetic, not text)."""
    exempt: set[int] = set()
    for node in ast.walk(tree):
        inside = (
            (isinstance(node, ast.FunctionDef) and node.name == "__repr__")
            or isinstance(node, ast.Raise)
            or (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "Decimal"
            )
        )
        if inside:
            exempt.update(id(child) for child in ast.walk(node))
    return exempt


def test_formatting_code_never_writes_with_repr():
    offenders: list[str] = []
    for name, tree in _modules():
        if name in _REPR_HOME or not name.startswith(_FORMATTING):
            continue
        exempt = _exempt_nodes(tree)
        for node in ast.walk(tree):
            if id(node) in exempt:
                continue
            is_repr = (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "repr"
            ) or (isinstance(node, ast.FormattedValue) and node.conversion == ord("r"))
            if is_repr:
                offenders.append(f"{name}:{getattr(node, 'lineno', 0)}")
    assert offenders == [], "write with pyfect._js.js_number / js_string or _json_text.quote"
