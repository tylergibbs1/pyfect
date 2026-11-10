"""Ports of Effect's ``effect/test/Glob.test.ts``, every title."""

from __future__ import annotations

import time
from typing import NamedTuple

import pytest

from pyfect import glob


class _Case(NamedTuple):
    pattern: str
    matches: tuple[str, ...]
    rejects: tuple[str, ...]
    dot: bool = False


_CASES = [
    _Case("a.ts", ("a.ts", "./a.ts"), ("b.ts", "dir/a.ts")),
    _Case("*.ts", ("a.ts", "a.b.ts"), (".a.ts", "dir/a.ts", "a.js")),
    _Case("?.ts", ("a.ts",), ("ab.ts", ".ts")),
    _Case("**/*.ts", ("a.ts", "a/b/c.ts"), (".a.ts", "a/.b/c.ts")),
    _Case("a/**", ("a", "a/b/c"), ("ab",)),
    _Case("a/**/b", ("a/b", "a/x/y/b"), ("a/x",)),
    _Case(".*", (".env",), ("env", ".", "..")),
    _Case("*", (".env", "a"), (".", "..", "a/b"), dot=True),
    _Case("[!a-c]x", ("dx",), ("ax", "/x")),
    _Case("[[:digit:]]x", ("1x",), ("ax",)),
    _Case("[😀-😂]x", ("😁x",), ("😃x",)),
    _Case("{a,{b,c}d}", ("a", "bd", "cd"), ("b", "d")),
    _Case("{a,b/c}/x", ("a/x", "b/c/x"), ("b/x",)),
    _Case("{a}", ("{a}",), ("a",)),
    _Case("[{a,b}]", ("{", ",", "}", "a", "b"), ("[a]", "c")),
    _Case("[]{a,b}]", ("]", "{", "b"), ("[]a]", "c")),
    _Case("{[,]x,b}", (",x", "b"), ("[", "]x")),
    _Case("[ab", ("[ab",), ("a",)),
    _Case("\\*.ts", ("*.ts",), ("a.ts",)),
    _Case("!(a)", ("!(a)",), ("b",)),
    _Case("dir/", ("dir/",), ("dir", "dir/a")),
    _Case("a/.", ("a/",), ("a",)),
    _Case("**/.", (), ("a", "a/", "a/b")),
    _Case("**/..", (), ("..", "a/..")),
    _Case("/abs/*.ts", ("/abs/a.ts",), ("abs/a.ts",)),
    _Case("C:/x/*", ("C:/x/a",), ("x/a",)),
    _Case("//server/share/*", (), ("//server/share/a", "/server/share/a")),
    _Case("/server/share/*", ("/server/share/a",), ("//server/share/a",)),
    _Case("**", ("a/b",), ("/a", "C:/a")),
]


@pytest.mark.parametrize(
    "case", _CASES, ids=[f"{c.pattern}{' (dot)' if c.dot else ''}" for c in _CASES]
)
def test_match(case: _Case) -> None:
    """match ``${pattern}${dot ? " (dot)" : ""}``"""
    compiled = glob.make(case.pattern, dot=case.dot)
    for path in case.matches:
        assert glob.match(compiled, path), f"expected {case.pattern} to match {path}"
    for path in case.rejects:
        assert not compiled.match(path), f"expected {case.pattern} not to match {path}"


def test_braces_beyond_the_expansion_limit() -> None:
    """matches braces literally when they expand to more than 10,000 alternatives"""
    assert glob.make("{a,b}" * 13).match("b" * 13)
    pattern = "{a,b}" * 20
    compiled = glob.make(pattern)
    assert not compiled.match("a" * 20)
    assert compiled.match(pattern)


def test_repeated_wildcards() -> None:
    """matches repeated wildcards without exponential backtracking"""
    compiled = glob.make("*a" * 15 + "b")
    start = time.perf_counter()
    assert not compiled.match("a" * 30)
    assert time.perf_counter() - start < 0.5


def test_adversarial_patterns() -> None:
    """compiles adversarial patterns without overflowing"""
    brackets = "[{" * 20_000
    assert glob.make(brackets).match(brackets)
    nested = "{a," * 100 + "b" + "}" * 100
    assert glob.make(nested).match(nested)


def test_escape() -> None:
    """escape makes special characters literal"""
    text = "a*b?c[d]{e,f}\\g"
    compiled = glob.make(glob.escape(text))
    assert compiled.match(text)
    assert not compiled.match("axbxcdeg")


def test_pipe_and_json() -> None:
    compiled = glob.make("*.ts", dot=True)
    assert compiled.pipe(lambda g: g.match(".a.ts"))
    assert compiled.to_json() == {"_id": "Glob", "pattern": "*.ts", "dot": True}
