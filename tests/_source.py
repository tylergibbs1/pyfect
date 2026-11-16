"""The repository's Python files, listed, read and parsed once per process.

Guards that scan the source tree share these caches: each parsed every file
itself, so a serial run of the guards parsed `src/` about forty times.
``tests/test_source_cache_guard.py`` keeps every other test file from calling
``ast.parse`` or globbing for ``*.py`` itself.
"""

from __future__ import annotations

import ast
import functools
import gc
from pathlib import Path
from typing import Literal, overload

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src" / "pyfect"
TESTS = ROOT / "tests"


@functools.cache
def files(root: Path, pattern: str = "*.py", *, recursive: bool = True) -> tuple[Path, ...]:
    """The files under ``root`` matching ``pattern``, sorted: ``rglob``, or ``glob`` when not
    ``recursive``."""
    return tuple(sorted(root.rglob(pattern) if recursive else root.glob(pattern)))


@functools.cache
def text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


@functools.cache
def tree(path: Path) -> ast.Module:
    """``path`` parsed. Shared by every caller: read it, never change it."""
    enabled = gc.isenabled()
    gc.disable()  # the parse makes thousands of nodes that all survive: collecting is waste
    try:
        module = ast.parse(text(path), str(path))
    finally:
        # Cached for the session: the collector would rescan millions of nodes (as
        # conftest.py's freeze says for imported modules) for nothing.
        gc.freeze()
        if enabled:
            gc.enable()
    return module


@functools.cache
def walk(path: Path) -> tuple[ast.AST, ...]:
    """Every node of ``tree(path)``, in ``ast.walk`` order."""
    return tuple(ast.walk(tree(path)))


@overload
def parse(source: str, filename: str = ..., mode: Literal["exec"] = ...) -> ast.Module: ...
@overload
def parse(source: str, filename: str = ..., *, mode: Literal["eval"]) -> ast.Expression: ...
def parse(
    source: str, filename: str = "<unknown>", mode: Literal["exec", "eval"] = "exec"
) -> ast.Module | ast.Expression:
    """``source`` parsed, uncached: for code a test writes or takes apart itself, not for
    files (use ``tree``)."""
    if mode == "eval":
        return ast.parse(source, filename, "eval")
    return ast.parse(source, filename)


def mentions(path: Path, *words: str) -> bool:
    """Whether ``path`` can hold an identifier or attribute among ``words``: a cheap skip for
    guards that look for names. Python folds non-ASCII identifiers (NFKC), so a file with any
    non-ASCII text always counts."""
    source = text(path)
    return not source.isascii() or any(word in source for word in words)
