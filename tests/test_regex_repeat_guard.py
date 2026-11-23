"""No pattern in ``src`` repeats, greedily or lazily, anything wider than one character.

``re`` keeps a backtrack frame for every iteration of a greedy or lazy repeat until the match
ends, unless the repeated thing is one character (a literal, a class, ``.``): then it only
counts. So ``(?:[0-9a-fA-F]{2})*`` held about 75 bytes per byte of hex it read, and
``"(?:\\\\"|[^"])*"`` about 180 per byte of quoted text; a quantifier inside such a repeat can
also backtrack in more ways than the input is long. A possessive repeat (``*+``, ``++``,
``{n,m}+``) keeps no frames; ``tests/security/test_regex_memory.py`` shows each rewrite
matches what the greedy pattern did. A pattern measured safe (its repeat bounded) goes in
``SAFE`` with its measurement.

Patterns are read from every ``re`` call in ``src``: a literal as written, one assigned to a
module global from the compiled module, and any other in ``BUILT_AT_RUN_TIME`` with why it
cannot be read here.
"""

from __future__ import annotations

# pyright: reportPrivateUsage=false
import ast
import importlib
import re
from collections.abc import Iterator
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any

import _source
import pytest

sre: Any = importlib.import_module("re._constants")
_parser: Any = importlib.import_module("re._parser")
ROOT = _source.ROOT
SRC = ROOT / "src"
_CALLS = frozenset(
    {"compile", "match", "fullmatch", "search", "sub", "subn", "split", "findall", "finditer"}
)
_RE_CALL = re.compile(rf"\bre\.(?:{'|'.join(_CALLS)})\(")
"""A quick look for an ``re`` call before parsing a file (most files have none)."""
_REPEATS = (sre.MAX_REPEAT, sre.MIN_REPEAT)

SAFE: dict[tuple[str, str], str] = {
    (
        "src/pyfect/net/net_address/_mac.py",
        r"(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}",
    ): "five iterations at most: 1.5 KB peak on the 17-character match, 1.4 KB on 2 MB",
    (
        "src/pyfect/schema/_net.py",
        r"\A[a-z](?:-?[a-z0-9]){0,9}(?:\.[a-z](?:-?[a-z0-9]){0,9}){0,3}\Z",
    ): "39 iterations at most, generation only: 6.8 KB peak on the 79-character match",
    (
        "src/pyfect/ai/_generated_client.py",
        r"(?:\.|%2e){1,2}",
    ): "two iterations at most: 1.5 KB peak on '%2e%2e', 1.4 KB on 2 MB of dots",
}

_CASE_CLASSES = (
    "Unicode letter, mark and number classes from pyfect._case_unicode; each repeat is of one class"
)

BUILT_AT_RUN_TIME: dict[tuple[str, str], str] = {
    ("src/pyfect/case.py", "f'([{NUMBER}][{MARK}]*)([{LETTER}])'"): _CASE_CLASSES,
    ("src/pyfect/case.py", "f'([{LETTER}][{MARK}]*)([{NUMBER}])'"): _CASE_CLASSES,
    ("src/pyfect/case.py", "f'([{LOWER}{NUMBER}][{MARK}]*)([{UPPER}])'"): _CASE_CLASSES,
    ("src/pyfect/case.py", "f'([{UPPER}][{MARK}]*)([{UPPER}][{MARK}]*[{LOWER}])'"): _CASE_CLASSES,
    ("src/pyfect/case.py", "f'[^{LETTER}{MARK}{NUMBER}]+'"): _CASE_CLASSES,
    ("src/pyfect/ai/_generated_support.py", "python"): "a generated schema's translated pattern",
    (
        "src/pyfect/encoding/csv/_channels.py",
        "f'[{re.escape(delimiter)}\"\\r\\n]'",
    ): "a character class of the configured delimiter",
    (
        "src/pyfect/encoding/csv/_parser.py",
        "f'[{re.escape(delimiter)}\\r\\n\"]'",
    ): "a character class of the configured delimiter",
    ("src/pyfect/encoding/toml.py", "f'[0-9A-Fa-f]{{{length}}}'"): "a fixed count of hex digits",
    ("src/pyfect/encoding/yaml.py", "f'[0-9A-Fa-f]{{{length}}}'"): "a fixed count of hex digits",
    (
        "src/pyfect/http/find_my_way/_router.py",
        "'(?:' + ''.join(regexps) + ')\\\\Z'",
    ): "a route's own parameter patterns, as find-my-way joins them",
    ("src/pyfect/http/_redacted_path.py", "regex"): (
        "a route parameter's own pattern, compiled only to count its capture groups"
    ),
    (
        "src/pyfect/http/headers.py",
        (
            "f'(?:mon|tue|wed|thu|fri|sat|sun), (?P<day>\\\\d{{2}}) (?P<month>[a-z]{{3}}) "
            "(?P<year>\\\\d{{4}}) {_TIME} gmt'"
        ),
    ): "IMF-fixdate: fixed-width fields, no group repeated",
    (
        "src/pyfect/http_api/api.py",
        "f'^{re.escape(name)}\\\\['",
    ): "a redacted query name, escaped, before a literal [",
    (
        "src/pyfect/http/headers.py",
        (
            "f'(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday), "
            "(?P<day>\\\\d{{2}})-(?P<month>[a-z]{{3}})-(?P<year>\\\\d{{2}}) {_TIME} gmt'"
        ),
    ): "RFC 850 date: fixed-width fields, no group repeated",
    (
        "src/pyfect/http/headers.py",
        (
            "f'(?:mon|tue|wed|thu|fri|sat|sun) (?P<month>[a-z]{{3}}) (?P<day> \\\\d|\\\\d{{2}}) "
            "{_TIME} (?P<year>\\\\d{{4}})'"
        ),
    ): "asctime date: fixed-width fields, no group repeated",
    (
        "src/pyfect/schema/_arbitrary_constraint.py",
        "d['source']",
    ): "a schema's own pattern, rebuilt from its JSON",
    ("src/pyfect/schema/_checks_string.py", "source.replace('$', '\\\\Z')"): "a user's pattern",
    ("src/pyfect/schema/_checks_string.py", "pattern"): "a user's pattern",
    (
        "src/pyfect/schema/_decimal_regexp.py",
        "cast('str', drawn['source'])",
    ): "a generated test pattern",
    ("src/pyfect/schema/_ecma_pattern.py", "translate(source, mode)"): "a user's pattern",
    ("src/pyfect/schema/representation/_builtin_revivers.py", "source"): "a revived RegExp",
    (
        "src/pyfect/schema/representation/_builtin_revivers.py",
        "payload['source']",
    ): "a revived RegExp",
    (
        "src/pyfect/schema/representation/_code_document.py",
        "f'(?<![.\\\\w]){name}\\\\b'",
    ): "an escaped identifier between fixed anchors",
    (
        "src/pyfect/sql/clickhouse/_rows.py",
        "b'\\\\n\\\\d+ ' + re.escape(tag) + b'\\\\r\\\\n' + _MARKER + b'\\\\r\\\\n$'",
    ): "an escaped tag between fixed literals",
}


@dataclass(frozen=True, slots=True)
class Found:
    path: str
    line: int
    pattern: str | bytes
    flags: int


def _re_function(node: ast.AST) -> str | None:
    """``"compile"`` for ``re.compile(...)`` and so on; ``None`` for any other node."""
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in _CALLS
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "re"
    ):
        return node.func.attr
    return None


def _module_globals(tree: ast.Module) -> dict[int, str]:
    """The ``re.compile`` calls assigned straight to a module global, by node id."""
    found: dict[int, str] = {}
    for statement in tree.body:
        if isinstance(statement, ast.Assign) and len(statement.targets) == 1:
            target, value = statement.targets[0], statement.value
        elif isinstance(statement, ast.AnnAssign) and statement.value is not None:
            target, value = statement.target, statement.value
        else:
            continue
        if isinstance(target, ast.Name) and _re_function(value) == "compile":
            found[id(value)] = target.id
    return found


def _flag_value(node: ast.expr) -> int:
    """``re.X`` or ``re.X | re.Y``, as written in a call."""
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        return _flag_value(node.left) | _flag_value(node.right)
    assert isinstance(node, ast.Attribute), ast.unparse(node)
    assert isinstance(node.value, ast.Name), ast.unparse(node)
    assert node.value.id == "re", ast.unparse(node)
    return int(getattr(re, node.attr))


def _literal_flags(call: ast.Call, function: str) -> int:
    given = call.args[1] if function == "compile" and len(call.args) > 1 else None
    given = given or next((k.value for k in call.keywords if k.arg == "flags"), None)
    return 0 if given is None else _flag_value(given)


def _module_name(path: Path) -> str:
    parts = path.relative_to(SRC).with_suffix("").parts
    return ".".join(parts[:-1] if parts[-1] == "__init__" else parts)


@cache
def patterns() -> tuple[tuple[Found, ...], frozenset[tuple[str, str]]]:
    """Every ``re`` pattern in ``src`` that can be read here, and the calls whose pattern is
    built at run time (path, source of the pattern argument)."""
    found: list[Found] = []
    built: set[tuple[str, str]] = set()
    for path in _source.files(_source.SRC):
        if _RE_CALL.search(_source.text(path)) is None:
            continue
        tree = _source.tree(path)
        name = path.relative_to(ROOT).as_posix()
        globals_ = _module_globals(tree)
        for node in ast.walk(tree):
            function = _re_function(node)
            if function is None:
                continue
            assert isinstance(node, ast.Call)
            argument = node.args[0]
            if isinstance(argument, ast.Constant) and isinstance(argument.value, str | bytes):
                flags = _literal_flags(node, function)
                found.append(Found(name, node.lineno, argument.value, flags))
            elif id(node) in globals_:
                module = importlib.import_module(_module_name(path))
                compiled: re.Pattern[Any] = getattr(module, globals_[id(node)])
                found.append(Found(name, node.lineno, compiled.pattern, compiled.flags))
            else:
                built.add((name, ast.unparse(argument)))
    return tuple(found), frozenset(built)


_ONE_CHARACTER = ("LITERAL", "NOT_LITERAL", "IN", "ANY", "CATEGORY")


def _one_character(items: Any) -> bool:
    """``re``'s own test for a repeat it runs without frames: one character, or a
    non-capturing group of one."""
    if len(items) != 1:
        return False
    op, av = items[0]
    if op is sre.SUBPATTERN:
        return av[0] is None and _one_character(av[3])
    return str(op) in _ONE_CHARACTER


def _children(op: Any, av: Any) -> list[Any]:
    """The sub-patterns directly inside one parsed item."""
    match op:
        case sre.MAX_REPEAT | sre.MIN_REPEAT | sre.POSSESSIVE_REPEAT:
            inner = [av[2]]
        case sre.SUBPATTERN:
            inner = [av[3]]
        case sre.BRANCH:
            inner = av[1]
        case sre.ASSERT | sre.ASSERT_NOT:
            inner = [av[1]]
        case sre.ATOMIC_GROUP:
            inner = [av]
        case sre.GROUPREF_EXISTS:
            inner = [av[1], av[2] or ()]
        case _:
            inner = []
    return [item for sub in inner for item in sub]


def _framed_repeats(items: Any) -> Iterator[str]:
    """Each greedy or lazy repeat of more than one iteration of more than one character."""
    for op, av in items:
        if op in _REPEATS and av[1] > 1 and not _one_character(av[2]):
            most = "" if av[1] == sre.MAXREPEAT else av[1]
            yield f"{'lazy' if op is sre.MIN_REPEAT else 'greedy'} {{{av[0]},{most}}}"
        yield from _framed_repeats(_children(op, av))


def framed_repeats(pattern: str | bytes, flags: int = 0) -> list[str]:
    return list(_framed_repeats(_parser.parse(pattern, flags)))


@pytest.mark.parametrize(
    "pattern",
    [
        rb"(?:[0-9a-fA-F]{2})*",
        r"[a-z0-9]+(?:-[a-z0-9]+)*",
        r"(?:a|b+)*?",
        r"(?:(?:ab)+)+",
        r"(?=(?:a\d+)*)",
        r"(?:%[0-9A-Fa-f]{2})+",
        r"(?:a{2}){3,}",
        r"(?:ab|cd)*",
        r'"(?:\\"|[^"])*"',
        r"(?:ab)*?",
        r"(a)*",
        r"(?:a|bc){2,5}",
    ],
)
def test_a_repeat_wider_than_one_character_is_found(pattern: str | bytes) -> None:
    assert framed_repeats(pattern) != []


@pytest.mark.parametrize(
    "pattern",
    [
        rb"[0-9a-fA-F]*",
        r"(?:%[0-9A-Fa-f]{2})++",
        r"[a-z0-9]++(?:-[a-z0-9]++)*+",
        r"(?:ab|cd)*+",
        r"(?:a+)?",
        r"(?:ab){1}",
        r"(?:a)*",
        r'"[^"]*"',
        r"a*?\d+.*",
    ],
)
def test_a_one_character_or_possessive_repeat_is_allowed(pattern: str | bytes) -> None:
    assert framed_repeats(pattern) == []


def test_no_src_pattern_repeats_more_than_one_character() -> None:
    offenders = [
        f"{found.path}:{found.line} {found.pattern!r}: {', '.join(repeats)}"
        for found in patterns()[0]
        if (repeats := framed_repeats(found.pattern, found.flags))
        and (found.path, _text(found.pattern)) not in SAFE
    ]
    assert offenders == [], "\n".join(offenders)


def test_every_safe_entry_is_still_a_src_pattern() -> None:
    present = {(found.path, _text(found.pattern)) for found in patterns()[0]}
    assert set(SAFE) - present == set()


def test_every_pattern_built_at_run_time_is_explained() -> None:
    built = patterns()[1]
    assert built - set(BUILT_AT_RUN_TIME) == set(), "add each to BUILT_AT_RUN_TIME with why"
    assert set(BUILT_AT_RUN_TIME) - built == set(), "remove entries no longer in src"


def _text(pattern: str | bytes) -> str:
    return pattern if isinstance(pattern, str) else pattern.decode("latin-1")
