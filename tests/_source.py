"""The repository's Python files: listed and read once per process, parsed on demand.

Guards that scan the source tree share these: each listed, read and parsed every file
itself, so a serial run of the guards parsed `src/` about forty times. The most recently
used trees stay cached up to a budget (every tree would be 1.2 GB per process), so a guard
looking for names skips files that can't hold them (``mentions``, ``may_hold``).
``tests/test_source_cache_guard.py`` keeps every other test file from calling ``ast.parse``
or globbing for ``*.py`` itself.
"""

from __future__ import annotations

import ast
import functools
import gc
import re
import sysconfig
import unicodedata
import weakref
from collections import OrderedDict
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


_TREE_BUDGET = 4 * 2**20
"""Text bytes of the files whose trees stay cached. A tree takes about 36 bytes per byte of
text, so this holds about 150 MB; every tree of `src/` and `tests/` would be 1.2 GB in each
process (each pytest-xdist worker)."""

_FREE_THREADED = bool(sysconfig.get_config_var("Py_GIL_DISABLED"))

_kept: OrderedDict[Path, tuple[ast.Module, tuple[ast.AST, ...] | None]] = OrderedDict()
_kept_bytes = 0


def _parsed(path: Path) -> ast.Module:
    enabled = gc.isenabled()
    gc.disable()  # the parse makes thousands of nodes that all survive: collecting is waste
    try:
        module = ast.parse(text(path), str(path))
    finally:
        if enabled:
            gc.enable()
    # Kept trees would make every full collection rescan their nodes (``conftest.py`` freezes
    # imported modules for the same reason). Young garbage is collected first so it isn't
    # frozen for good; a frozen tree that is dropped is still freed by its reference count,
    # as no node refers back to its parent. The free-threaded collector has no young
    # generation, so there the collection would scan the whole heap once per file.
    if not _FREE_THREADED:
        gc.collect(1)
        gc.freeze()
    return module


_alive: weakref.WeakValueDictionary[Path, ast.Module] = weakref.WeakValueDictionary()
"""Every tree a caller still holds, so a path keeps one tree while anyone reads it."""


def _entry(path: Path) -> tuple[ast.Module, tuple[ast.AST, ...] | None]:
    global _kept_bytes  # noqa: PLW0603
    entry = _kept.get(path)
    if entry is not None:
        _kept.move_to_end(path)
        return entry
    module = _alive.get(path)
    if module is None:
        module = _alive[path] = _parsed(path)
    entry = (module, None)
    _kept[path] = entry
    _kept_bytes += len(text(path))
    while _kept_bytes > _TREE_BUDGET and len(_kept) > 1:
        old, _ = _kept.popitem(last=False)
        _kept_bytes -= len(text(old))
    return entry


def tree(path: Path) -> ast.Module:
    """``path`` parsed; the most recently used trees are kept. Shared by every caller: read
    it, never change it."""
    return _entry(path)[0]


def walk(path: Path) -> tuple[ast.AST, ...]:
    """Every node of ``tree(path)``, in ``ast.walk`` order."""
    module, nodes = _entry(path)
    if nodes is None:
        nodes = tuple(ast.walk(module))
        _kept[path] = (module, nodes)
    return nodes


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


def mentions(path: Path, *names: str) -> bool:
    """Whether ``path`` can hold an identifier or attribute among ``names``, a cheap skip for
    guards that look for names. Python folds non-ASCII identifiers (NFKC), so a non-ASCII
    file is folded first."""
    return any(name in folded(path) for name in names)


@functools.cache
def folded(path: Path) -> str:
    """``text(path)`` as Python reads its identifiers (NFKC), for name searches."""
    source = text(path)
    return source if source.isascii() else unicodedata.normalize("NFKC", source)


_JOIN = r"""['"]{1,3}(?:\s|\\\n|#[^\n]*)*[rRbBuUfFtT]*['"]{1,3}"""
"""Between two adjacent string literals, which Python joins into one constant."""


@functools.cache
def _spellings(value: str) -> re.Pattern[str]:
    splits = [re.escape(value[:i]) + _JOIN + re.escape(value[i:]) for i in range(1, len(value))]
    return re.compile("|".join([re.escape(value), r"\\", *splits]))


def may_hold(path: Path, value: str) -> bool:
    """Whether a string constant in ``path`` can hold ``value``: written out, split across
    joined literals, or behind an escape (any backslash counts)."""
    return _spellings(value).search(text(path)) is not None
