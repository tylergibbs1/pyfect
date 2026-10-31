"""Python's base64 decoders skip characters outside the alphabet unless
told not to, so ``urlsafe_b64decode`` took ``"ab!!cd"`` and the standard
alphabet where Effect's ``Base64Url.decode`` fails (QA ai-workflow EL-3).
Decode with ``schema.getter._binary``'s ``base64_decode`` /
``base64_url_decode`` (Effect's), or ``b64decode(..., validate=True)``."""

from __future__ import annotations

import ast
from pathlib import Path

_SRC = Path(__file__).parent.parent / "src" / "pyfect"
_LENIENT = {"urlsafe_b64decode", "standard_b64decode", "b32decode", "a85decode", "b85decode"}


def _validated(call: ast.Call) -> bool:
    return any(
        k.arg == "validate" and isinstance(k.value, ast.Constant) and k.value.value is True
        for k in call.keywords
    )


def test_no_lenient_base64_decoding():
    offenders: list[str] = []
    for path in sorted(_SRC.rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text())):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
                continue
            name = node.func.attr
            if name in _LENIENT or (name == "b64decode" and not _validated(node)):
                offenders.append(f"{path.relative_to(_SRC)}:{node.lineno} {name}")
    assert offenders == []
