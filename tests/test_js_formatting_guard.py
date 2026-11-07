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


def test_only_json_text_imports_json():
    offenders = [
        f"{name}:{node.lineno}"
        for name, tree in _modules()
        if name not in _JSON_HOME
        for node in ast.walk(tree)
        if (
            isinstance(node, ast.Import) and any(a.name.split(".")[0] == "json" for a in node.names)
        )
        or (isinstance(node, ast.ImportFrom) and (node.module or "").split(".")[0] == "json")
    ]
    assert offenders == [], "use pyfect._json_text (parse / stringify / quote)"


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
