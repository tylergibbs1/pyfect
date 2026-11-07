"""Reads every ``it`` / ``test`` title out of Effect's test files, and pyfect's ports.

A title is ported when a test here carries it, by the convention of ``tests/oracle``: as a
clause of its docstring (``describe / title``, ``a / b``, ``title: note``), as its function name
without ``test_``, or as a clause of a string in a parametrized table of titles.
"""

from __future__ import annotations

import ast
import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path

_OPENING = re.compile(r"(?<![\w.$])(?:it|test)((?:\.\w+)*)\s*\(")
_PLACEHOLDER = "\0"
_CAMEL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")
_WORD = re.compile(r"[a-z0-9]+")
_SPRINTF = re.compile(r"%[sdifoOj]|\$\{?[A-Za-z_][\w.]*\}?")
_ESCAPE = re.compile(r"\\(.)", re.DOTALL)


def _skip_string(text: str, start: int) -> int:
    """The index after the quoted string or template opening at ``start``."""
    quote = text[start]
    index = start + 1
    while index < len(text):
        char = text[index]
        if char == "\\":
            index += 2
        elif char == quote:
            return index + 1
        elif quote == "`" and text.startswith("${", index):
            index = _skip_balanced(text, index + 1)
        else:
            index += 1
    return index


def _skip_balanced(text: str, start: int) -> int:
    """The index after the bracket opening at ``start``, skipping strings and comments."""
    depth = 0
    index = start
    while index < len(text):
        char = text[index]
        if char in "\"'`":
            index = _skip_string(text, index)
            continue
        if text.startswith("//", index):
            end = text.find("\n", index)
            index = len(text) if end < 0 else end
            continue
        if text.startswith("/*", index):
            end = text.find("*/", index)
            index = len(text) if end < 0 else end + 2
            continue
        if char in "([{":
            depth += 1
        elif char in ")]}":
            depth -= 1
            if depth == 0:
                return index + 1
        index += 1
    return index


def _template_title(text: str, start: int) -> tuple[str, int]:
    """A string literal's text with interpolations as ``_PLACEHOLDER``, and its end."""
    quote = text[start]
    out: list[str] = []
    index = start + 1
    while index < len(text):
        char = text[index]
        if char == "\\":
            out.append(text[index : index + 2])
            index += 2
        elif char == quote:
            return _ESCAPE.sub(r"\1", "".join(out)), index + 1
        elif quote == "`" and text.startswith("${", index):
            index = _skip_balanced(text, index + 1)
            out.append(_PLACEHOLDER)
        else:
            out.append(char)
            index += 1
    return "".join(out), index


def _strip_comment_lines(source: str) -> str:
    return re.sub(r"(?m)^\s*(//|\*|/\*).*$", "", source)


def _title_after(source: str, start: int, modifiers: str) -> str | None:
    """The title of the call whose arguments open at ``start``; None when it isn't literal."""
    index = start
    while True:
        while index < len(source) and source[index].isspace():
            index += 1
        char = source[index : index + 1]
        if char in ('"', "'", "`"):
            title, end = _template_title(source, index)
            parts = [title]
            index = end
            while True:
                match = re.compile(r"\s*\+\s*").match(source, index)
                if match is None:
                    break
                if source[match.end() : match.end() + 1] not in ('"', "'", "`"):
                    parts.append(_PLACEHOLDER)
                    break
                more, index = _template_title(source, match.end())
                parts.append(more)
            return "".join(parts)
        if ".each" not in modifiers and ".for" not in modifiers:
            return None
        # it.each(table)("title", ...): the table is the first call, the title the second.
        end = _skip_balanced(source, index - 1)
        if source[end : end + 1] != "(":
            return None
        index = end + 1
        modifiers = ""


def titles_in_source(source: str) -> Iterator[str]:
    """The titles of the ``it`` and ``test`` calls in one TypeScript file."""
    code = _strip_comment_lines(source)
    for match in _OPENING.finditer(code):
        title = _title_after(code, match.end(), match.group(1))
        if title is not None:
            yield title


def effect_test_files(packages: Path) -> Iterator[Path]:
    """Every TypeScript file under a package's ``test`` directory."""
    for path in sorted(packages.rglob("*.ts*")):
        parts = path.relative_to(packages).parts
        if "node_modules" in parts or "test" not in parts or path.name.endswith(".d.ts"):
            continue
        if path.suffix in {".ts", ".tsx"}:
            yield path


def words(text: str) -> str:
    """``text`` as lowercase words, so ``toSeconds``, ``to_seconds`` and ``to seconds`` agree."""
    spaced = _SPRINTF.sub(_PLACEHOLDER, text)
    spaced = _CAMEL.sub(" ", spaced).lower()
    return " ".join(
        _PLACEHOLDER if piece == _PLACEHOLDER else piece
        for piece in re.findall(rf"[a-z0-9]+|{_PLACEHOLDER}", spaced)
    )


_BOUNDARY = re.compile(r"[/;:,>()\"'`]|\.(?=\s|$)|\s-\s|\n\s*\n")
_LONGEST_RUN = 8
_OMITTED_FROM = re.compile(r"\bomit|\bnot ported|\bleft out|\bdropped|\bskipped", re.IGNORECASE)
"""An older omission is a title named in a module docstring from where it starts listing them."""


def _runs(text: str) -> Iterator[str]:
    """Each run of ``text``'s clauses as words, and each run's end of two words or more, which
    is the title under a ``describe`` prefix. A title carried by a docstring stands between its
    separators, so a few of its words inside a sentence don't count."""
    clauses = [words(clause) for clause in _BOUNDARY.split(text)]
    clauses = [clause for clause in clauses if clause]
    for start in range(len(clauses)):
        for end in range(start + 1, min(start + _LONGEST_RUN, len(clauses)) + 1):
            run = " ".join(clauses[start:end]).split(" ")
            yield " ".join(run)
            for first in range(1, len(run) - 1):
                yield " ".join(run[first:])


@dataclass(frozen=True)
class Ports:
    """What pyfect's tests say they port, and what their module docstrings say they omit."""

    names: frozenset[str]
    """Test names without ``test_`` / ``Test``, which carry a title spelled the same."""
    strings: frozenset[str]
    """Each string that isn't a docstring, and its last ``/`` part: a table's title."""
    docstrings: frozenset[str]
    """Clause runs of each test docstring."""
    module_docstrings: frozenset[str]
    prose: tuple[str, str]
    """Test and module docstrings as lines of words, for titles with interpolated parts."""


def read_ports(files: Iterable[Path]) -> Ports:
    names: set[str] = set()
    strings: set[str] = set()
    docstrings: set[str] = set()
    module_docstrings: set[str] = set()
    prose: list[str] = []
    module_prose: list[str] = []
    for path in files:
        tree = ast.parse(path.read_text())
        docstring_nodes: set[int] = set()
        module_doc = ast.get_docstring(tree)
        omitted = module_doc and _OMITTED_FROM.search(module_doc)
        if module_doc and omitted:
            module_docstrings.update(_runs(module_doc[omitted.start() :]))
            module_prose.append(words(module_doc[omitted.start() :]))
        for node in ast.walk(tree):
            if isinstance(node, ast.Module | ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
                match node.body:
                    case [ast.Expr(value=ast.Constant() as constant), *_]:
                        docstring_nodes.add(id(constant))
                    case _:
                        pass
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
                test_name = re.match(r"test_|Test(?=[A-Z])", node.name)
                if test_name:
                    names.add(words(node.name[test_name.end() :]))
                doc = ast.get_docstring(node)
                if doc:
                    docstrings.update(_runs(doc))
                    prose.append(words(doc))
            elif (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and id(node) not in docstring_nodes
            ):
                strings.update((words(node.value), words(node.value.rpartition(" / ")[2])))
    return Ports(
        frozenset(names),
        frozenset(strings),
        frozenset(docstrings),
        frozenset(module_docstrings),
        (" \n ".join(prose), " \n ".join(module_prose)),
    )


def _found_with_holes(key: str, prose: str) -> bool:
    pieces = [re.escape(piece.strip()) for piece in key.split(_PLACEHOLDER) if piece.strip()]
    return re.search(r" " + r"[^\n]*?".join(pieces) + r"\b", prose) is not None


def is_ported(title: str, ports: Ports) -> bool:
    """A test carries the title; a title that is all interpolation can't be looked up."""
    key = words(title)
    if not _WORD.search(key):
        return True
    if _PLACEHOLDER in key:
        return _found_with_holes(key, ports.prose[0])
    return key in ports.names or key in ports.docstrings or key in ports.strings


def is_noted_as_omitted(title: str, ports: Ports) -> bool:
    """A test module's docstring names the title, the older form of an omission."""
    key = words(title)
    if _PLACEHOLDER in key:
        return _found_with_holes(key, ports.prose[1])
    return key in ports.module_docstrings
