"""Keeps redaction where every log and telemetry sink gets it.

Sinks turn values into output only through ``pyfect.logger._text``
(``format_unknown``, ``to_json``) and ``pyfect._json_text.stringify``, which
ask ``pyfect._redaction`` for a value's redacted form or ``to_json`` before
walking it. So a sink module must not walk or print values itself, and a type
that redacts anything must give those renderers its redacted form."""

from __future__ import annotations

import ast
from pathlib import Path

SRC = Path(__file__).parent.parent / "src" / "pyfect"
SINKS = [
    *(SRC / "logger").rglob("*.py"),
    *(SRC / "otel").rglob("*.py"),
    *(SRC / "observability").rglob("*.py"),
    *(SRC / "devtools").rglob("*.py"),
    *(SRC / "tracer").rglob("*.py"),
    SRC / "cause.py",
]
RENDERERS = {SRC / "logger" / "_text.py"}
# Walks of a value's contents. ``repr`` defers to the type's own ``__repr__``,
# which the redacting types define.
WALKS = {"vars", "asdict", "astuple", "pformat", "pprint", "dumps"}
REDACTS = {"current_redacted_names", "redact_url", "is_redacted_name"}


def _name(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def test_sinks_render_values_only_through_the_redacting_renderers() -> None:
    found: list[str] = []
    for path in SINKS:
        if path in RENDERERS:
            continue
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Call) and _name(node.func) in WALKS:
                found.append(f"{path.relative_to(SRC)}:{node.lineno} calls {_name(node.func)}")
            if isinstance(node, ast.Attribute) and node.attr == "__dict__":
                found.append(f"{path.relative_to(SRC)}:{node.lineno} reads __dict__")
    assert found == []


def test_a_type_that_redacts_gives_its_redacted_form_to_the_renderers() -> None:
    found: list[str] = []
    for path in SRC.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if not isinstance(node, ast.ClassDef):
                continue
            used = {_name(n) for n in ast.walk(node) if isinstance(n, ast.Name | ast.Attribute)}
            methods = {f.name for f in node.body if isinstance(f, ast.FunctionDef)}
            if used & REDACTS and not methods & {"to_json", "__redacted__"}:
                found.append(f"{path.relative_to(SRC)}: {node.name}")
    assert found == []
