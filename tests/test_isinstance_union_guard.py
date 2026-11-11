"""``isinstance`` and ``issubclass`` take a tuple of classes, never ``A | B``.

``isinstance(x, A | B)`` builds a ``types.UnionType`` on every call: about
100 ns against 9 ns for ``isinstance(x, (A, B))`` on CPython 3.14. The fiber
loop ran one per step (``Success | Failure``), roughly a tenth of a stream's
per-item cost. Pyright narrows a tuple the same way, and ruff removed UP038,
the rule that asked for unions.
"""

from __future__ import annotations

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src" / "pyfect"


def _union_checks(path: Path) -> list[str]:
    return [
        f"{path.name}:{node.lineno}"
        for node in ast.walk(ast.parse(path.read_text(), str(path)))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id in ("isinstance", "issubclass")
        and len(node.args) == 2
        and isinstance(node.args[1], ast.BinOp)
        and isinstance(node.args[1].op, ast.BitOr)
    ]


def test_no_isinstance_takes_a_union():
    """Every ``isinstance(x, A | B)`` in ``src`` is written ``isinstance(x, (A, B))``."""
    found = [hit for path in sorted(SRC.rglob("*.py")) for hit in _union_checks(path)]
    assert found == []


def test_the_guard_sees_a_union(tmp_path: Path):
    """The check finds the form it bans and passes a tuple."""
    sample = tmp_path / "sample.py"
    sample.write_text("isinstance(1, int | str)\nissubclass(int, (int, str))\n")
    assert _union_checks(sample) == ["sample.py:1"]
