"""Reads every ``it`` / ``test`` title out of Effect's test files, and pyfect's ports.

A title is ported when a test here carries it, by the convention of ``tests/oracle``: as a
clause of its docstring (``describe / title``, ``a / b``, ``title: note``), as its function name
without ``test_``, or as a clause of a string in a parametrized table of titles.
"""

from __future__ import annotations

import ast
import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from fnmatch import fnmatch
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


_MENTION = re.compile(r"[\w@.\-/*]+\.tsx?\b")
_NPM_SCOPE = re.compile(r"^(ai|atom|platform|sql)-")
"""``sql-pg/test/...`` names the npm package ``@effect/sql-pg``, whose directory is ``sql/pg``."""


def _resolve(mention: str, effect_files: Iterable[str]) -> list[str]:
    tail = _NPM_SCOPE.sub(r"\1/", mention.removeprefix("./").removeprefix("packages/"))
    return [path for path in effect_files if fnmatch(path, tail) or fnmatch(path, "*/" + tail)]


def named_files(text: str, effect_files: Iterable[str]) -> frozenset[str]:
    """The Effect test files ``text`` names by a path ending (``ai/Chat.test.ts``), which may
    start with an npm package name (``sql-pg/test/...``) or hold a glob (``FindMyWay/*.ts``)."""
    return frozenset(
        path for mention in _MENTION.findall(text) for path in _resolve(mention, effect_files)
    )


def ambiguous_mentions(text: str, effect_files: Iterable[str]) -> list[str]:
    """The mentions in ``text`` without a glob that name more than one Effect file, such as a
    bare ``Client`` test file name, which would let one port stand for each driver's file."""
    return [
        mention
        for mention in _MENTION.findall(text)
        if "*" not in mention and len(_resolve(mention, effect_files)) > 1
    ]


@dataclass
class Ports:
    """What pyfect's tests that name one Effect file say they port, and what their module
    docstrings say they omit."""

    names: set[str] = field(default_factory=set[str])
    """Test names without ``test_`` / ``Test``, which carry a title spelled the same."""
    strings: set[str] = field(default_factory=set[str])
    """Each string that isn't a docstring, and its last ``/`` part: a table's title."""
    docstrings: set[str] = field(default_factory=set[str])
    """Clause runs of each test docstring."""
    module_docstrings: set[str] = field(default_factory=set[str])
    prose: list[str] = field(default_factory=list[str])
    """Test docstrings as lines of words, for titles with interpolated parts."""
    module_prose: list[str] = field(default_factory=list[str])


def read_ports(files: Iterable[Path], effect_files: Iterable[str]) -> dict[str, Ports]:
    """Each Effect file's ports: what the tests carry whose own, class or module docstring
    names that file. A test that names no Effect file ports nothing."""
    effect_files = tuple(effect_files)
    ports: dict[str, Ports] = {}

    def of(keys: frozenset[str]) -> Iterator[Ports]:
        for key in keys:
            yield ports.setdefault(key, Ports())

    def visit(node: ast.AST, keys: frozenset[str], docstring: ast.AST | None) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
                doc = ast.get_docstring(child)
                child_keys = keys | named_files(doc, effect_files) if doc else keys
                test_name = re.match(r"test_|Test(?=[A-Z])", child.name)
                for port in of(child_keys):
                    if test_name:
                        port.names.add(words(child.name[test_name.end() :]))
                    if doc:
                        port.docstrings.update(_runs(doc))
                        port.prose.append(words(doc))
                match child.body:
                    case [ast.Expr(value=ast.Constant() as constant), *_]:
                        visit(child, child_keys, constant)
                    case _:
                        visit(child, child_keys, None)
            elif (
                isinstance(child, ast.Constant)
                and isinstance(child.value, str)
                and child is not docstring
            ):
                for port in of(keys):
                    port.strings.update(
                        (words(child.value), words(child.value.rpartition(" / ")[2]))
                    )
            else:
                visit(child, keys, docstring)

    for path in files:
        tree = ast.parse(path.read_text())
        module_doc = ast.get_docstring(tree) or ""
        keys = named_files(module_doc, effect_files)
        omitted = _OMITTED_FROM.search(module_doc)
        if omitted:
            for port in of(keys):
                port.module_docstrings.update(_runs(module_doc[omitted.start() :]))
                port.module_prose.append(words(module_doc[omitted.start() :]))
        match tree.body:
            case [ast.Expr(value=ast.Constant() as constant), *_]:
                visit(tree, keys, constant)
            case _:
                visit(tree, keys, None)
    return ports


def _found_with_holes(key: str, prose: Iterable[str]) -> bool:
    """A docstring line holds the title's literal pieces in order, from a word's start."""
    pieces = [re.escape(piece.strip()) for piece in key.split(_PLACEHOLDER) if piece.strip()]
    pattern = re.compile(r"(?:^|\s)" + r"[^\n]*?".join(pieces) + r"\b")
    return any(pattern.search(line) for line in prose)


def is_ported(title: str, ports: Ports) -> bool:
    """A test carries the title; a title that is all interpolation can't be looked up."""
    key = words(title)
    if not _WORD.search(key):
        return True
    if _PLACEHOLDER in key:
        return _found_with_holes(key, ports.prose)
    return key in ports.names or key in ports.docstrings or key in ports.strings


def is_noted_as_omitted(title: str, ports: Ports) -> bool:
    """A test module's docstring names the title, the older form of an omission."""
    key = words(title)
    if _PLACEHOLDER in key:
        return _found_with_holes(key, ports.module_prose)
    return key in ports.module_docstrings


def docstrings(path: Path) -> Iterator[str]:
    """The module, class and function docstrings of one Python file."""
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Module | ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            doc = ast.get_docstring(node)
            if doc:
                yield doc
