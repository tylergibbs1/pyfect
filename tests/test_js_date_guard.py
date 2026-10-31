"""Text Effect reads with ``new Date(text)`` is read by ``pyfect._js_date``,
and named zones come from ``date_time.zone_named``.

``datetime.fromisoformat`` takes text JavaScript rejects (``2024-W01-1``,
a ``,5`` fraction, a ``+05:30:15`` offset) and rejects text it reads (a
lowercase ``z``, ``+002024``, ``2024-02-30``). ``ZoneInfo(name)`` keeps the
caller's casing (``europe/london``), which ``Intl`` canonicalizes.
"""

from __future__ import annotations

import ast
from collections.abc import Iterator
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src" / "pyfect"

# Reads back ISO text that pyfect itself wrote with ``datetime.isoformat``.
_READS_ITS_OWN_ISOFORMAT = {"schema/_arbitrary_constraint.py"}


def _calls(attr: str) -> Iterator[tuple[str, int]]:
    for path in sorted(SRC.rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(), str(path))):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = (
                func.attr
                if isinstance(func, ast.Attribute)
                else func.id
                if isinstance(func, ast.Name)
                else None
            )
            if name == attr:
                yield str(path.relative_to(SRC)), node.lineno


def test_no_fromisoformat_outside_its_own_isoformat():
    offenders = [
        f"{path}:{line}"
        for path, line in _calls("fromisoformat")
        if path not in _READS_ITS_OWN_ISOFORMAT
    ]
    assert offenders == [], "parse with pyfect._js_date (parse / parse_input)"


def test_named_zones_are_made_only_by_zone_named():
    offenders = [
        f"{path}:{line}" for path, line in _calls("ZoneInfo") if path != "date_time/_zones.py"
    ]
    assert offenders == [], "use date_time.zone_named, which canonicalizes the name"
