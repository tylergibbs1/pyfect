"""Text that reaches a hash, a signature or the wire is encoded with
``pyfect._js.text_encode`` (JavaScript's ``TextEncoder``: a lone surrogate
becomes U+FFFD); ``str.encode()`` raises on one, so a key ``"a\\ud800b"``
killed a workflow's execution id (QA ai-workflow WF-2), and the same raise
was in ``Stream.encode_text``, HTTP bodies and the cluster lock namespace.
Every package is covered; ``json_pointer`` re-encodes the literal text of
``decodeURIComponent``, where JavaScript keeps a lone surrogate as it is.
A call on an imported name (``ndjson.encode()``) is a function, not
``str.encode``."""

from __future__ import annotations

import ast
from pathlib import Path

_SRC = Path(__file__).parent.parent / "src" / "pyfect"
_EXEMPT = {"_js.py", "json_pointer.py"}
_UTF8 = {"utf-8", "utf8", "UTF-8"}


def _imported_names(tree: ast.Module) -> set[str]:
    return {
        (alias.asname or alias.name).split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import | ast.ImportFrom)
        for alias in node.names
    }


def _is_utf8_encode(node: ast.Call, imported: set[str]) -> bool:
    if not (isinstance(node.func, ast.Attribute) and node.func.attr == "encode"):
        return False
    if isinstance(node.func.value, ast.Name) and node.func.value.id in imported:
        return False
    if node.keywords:
        return False
    if not node.args:
        return True
    first = node.args[0]
    return len(node.args) == 1 and isinstance(first, ast.Constant) and first.value in _UTF8


def test_text_is_encoded_as_text_encoder_encodes_it():
    offenders: list[str] = []
    for path in sorted(_SRC.rglob("*.py")):
        if path.name in _EXEMPT:
            continue
        tree = ast.parse(path.read_text())
        imported = _imported_names(tree)
        offenders.extend(
            f"{path.relative_to(_SRC)}:{node.lineno} {ast.unparse(node)}"
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and _is_utf8_encode(node, imported)
        )
    assert offenders == []
