"""The workflow and cluster engines wait and read time only through the
``Clock`` service, so the ``TestClock`` moves every durable sleep, wake-up
and storage poll (DOGFOOD outlay #2, #3).

A wall-clock module (``time``, ``asyncio``, ``threading``, ``sched``,
``selectors``) or ``datetime.now()`` / ``utcnow()`` / ``today()`` inside
them would schedule something the test clock cannot see. A module may use
``threading`` for its locks (``threading.Lock`` / ``RLock``), which wait on
no time: state shared by runs on other threads holds one.
"""

from __future__ import annotations

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src" / "pyfect"
_ENGINES = ("workflow", "cluster")
_WALL_MODULES = {"time", "asyncio", "threading", "sched", "selectors", "concurrent"}
_WALL_READS = {"now", "utcnow", "today", "fromtimestamp"}
_LOCKS = {"Lock", "RLock"}


def _only_locks(tree: ast.AST) -> bool:
    """Whether every ``threading.<name>`` in ``tree`` is a lock."""
    return all(
        node.attr in _LOCKS
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "threading"
    )


def _receiver(node: ast.expr) -> str | None:
    """``datetime`` for ``datetime.now`` and ``datetime.datetime.now`` alike."""
    if isinstance(node, ast.Name):
        return node.id
    return node.attr if isinstance(node, ast.Attribute) else None


def _offenders() -> list[str]:
    found: list[str] = []
    for package in _ENGINES:
        for path in sorted((SRC / package).rglob("*.py")):
            where = path.relative_to(SRC)
            tree = ast.parse(path.read_text(), str(path))
            locks_only = _only_locks(tree)
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    names = [a.name.split(".")[0] for a in node.names]
                    found += [
                        f"{where}:{node.lineno} imports {n}"
                        for n in names
                        if n in _WALL_MODULES and not (n == "threading" and locks_only)
                    ]
                elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                    module = node.module.split(".")[0]
                    if module in _WALL_MODULES:
                        found.append(f"{where}:{node.lineno} imports {module}")
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr in _WALL_READS
                    and _receiver(node.func.value) in {"datetime", "date"}
                ):
                    found.append(f"{where}:{node.lineno} calls {ast.unparse(node.func)}")
    return found


def test_the_engines_wait_only_on_the_clock_service():
    assert _offenders() == [], "sleep with fx.sleep / Clock and read time from Clock"
