"""Tests read and parse the repository's Python files only through ``tests/_source.py``.

Each source guard used to list, read and parse the tree itself, so a serial run parsed
`src/` about forty times and single guards took up to 9 s. ``_source`` caches the listing
and the text for the process and the recent trees; this keeps the next guard on it.
"""

from __future__ import annotations

import ast
from collections.abc import Sequence
from pathlib import Path

import _source

_SHARED = Path(_source.__file__).resolve()
_READS = frozenset({"read_text", "read_bytes"})


def _imported_as(nodes: Sequence[ast.AST], name: str) -> tuple[set[str], set[str]]:
    """Local names bound to module ``name``, and to its ``parse``."""
    modules: set[str] = set()
    parses: set[str] = set()
    for node in nodes:
        if isinstance(node, ast.Import):
            modules |= {a.asname or a.name for a in node.names if a.name == name}
        elif isinstance(node, ast.ImportFrom) and node.module == name and node.level == 0:
            parses |= {a.asname or a.name for a in node.names if a.name == "parse"}
    return modules, parses


def _calls_parse(call: ast.Call, modules: set[str], parses: set[str]) -> bool:
    func = call.func
    if isinstance(func, ast.Name):
        return func.id in parses
    return (
        isinstance(func, ast.Attribute)
        and func.attr == "parse"
        and isinstance(func.value, ast.Name)
        and func.value.id in modules
    )


def _offenders(nodes: Sequence[ast.AST]) -> list[str]:
    """``nodes``: every node of one module."""
    imports = [node for node in nodes if isinstance(node, ast.Import | ast.ImportFrom)]
    ast_names, ast_parses = _imported_as(imports, "ast")
    source_names, source_parses = _imported_as(imports, "_source")
    found: list[str] = []
    for node in nodes:
        if not isinstance(node, ast.Call):
            continue
        func, args = node.func, node.args
        if _calls_parse(node, ast_names, ast_parses):
            found.append(f"{node.lineno}: ast.parse (use _source.tree, or _source.parse)")
        elif (
            isinstance(func, ast.Attribute)
            and func.attr in ("glob", "rglob")
            and args
            and isinstance(args[0], ast.Constant)
            and isinstance(args[0].value, str)
            and args[0].value.endswith(".py")
        ):
            found.append(f"{node.lineno}: {func.attr}({args[0].value!r}) (use _source.files)")
        elif (
            _calls_parse(node, source_names, source_parses)
            and args
            and isinstance(args[0], ast.Call)
            and isinstance(args[0].func, ast.Attribute)
            and args[0].func.attr in _READS
        ):
            found.append(f"{node.lineno}: _source.parse of a file read (use _source.tree)")
    return found


def test_only_the_shared_module_lists_reads_and_parses_python_files() -> None:
    found = [
        f"{path.relative_to(_source.TESTS)}:{line}"
        for path in _source.files(_source.TESTS)
        if path.resolve() != _SHARED
        # Each finding names parse (imported under any alias, its import says so) or glob.
        and _source.mentions(path, "parse", "glob")
        for line in _offenders(_source.walk(path))
    ]
    assert not found, "\n".join(found)


def test_the_guard_catches_each_way_around_the_cache() -> None:
    source = """
import ast
import ast as pyast
from ast import parse
import _source
from _source import parse as snippet
from pathlib import Path
ast.parse(Path("a.py").read_text())
pyast.parse("x = 1")
parse("x = 1")
sorted(Path("src").rglob("*.py"))
Path("src").glob("test_*.py")
_source.parse(Path("a.py").read_text())
snippet(Path("a.py").read_bytes())
_source.parse("x = 1")
_source.tree(Path("a.py"))
Path("docs").rglob("*.mdx")
"""
    found = _offenders(list(ast.walk(_source.parse(source))))
    assert sorted(int(hit.split(":")[0]) for hit in found) == [8, 9, 10, 11, 12, 13, 14]
