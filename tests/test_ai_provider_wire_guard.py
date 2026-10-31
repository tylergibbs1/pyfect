"""Provider wire JSON is checked only through ``_provider.wire_decoder`` /
``wire_match``, which read whole floats (``1.0``) as ints as JavaScript
does; a schema applied to the raw JSON would reject ``1.0`` where Effect's
``Schema.Int`` takes it (QA ai-workflow PROV-1)."""

from __future__ import annotations

import ast
from pathlib import Path

_AI = Path(__file__).parent.parent / "src" / "pyfect" / "ai"
_PROVIDER_FILES = [
    *sorted((_AI / "openai_compat").glob("*.py")),
    *sorted((_AI / "anthropic").glob("*.py")),
    _AI / "_openai_errors.py",
]
_RAW_CHECKS = {
    "is_",
    "decode_unknown_effect",
    "decode_unknown_sync",
    "decode_unknown_exit",
    "decode_unknown_result",
    "decode_effect",
    "decode_sync",
}
_TEXT_SCHEMAS = {"UnknownFromJsonString"}
"""Schemas of JSON text, not of its values: what they decode is checked next."""


def test_provider_json_is_checked_through_the_wire_helpers():
    offenders: list[str] = []
    for path in _PROVIDER_FILES:
        for node in ast.walk(ast.parse(path.read_text())):
            if not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in _RAW_CHECKS
            ):
                continue
            argument = ast.unparse(node.args[0]) if node.args else ""
            if argument.removeprefix("S.") not in _TEXT_SCHEMAS:
                offenders.append(f"{path.name}:{node.lineno} {ast.unparse(node)}")
    assert offenders == []
