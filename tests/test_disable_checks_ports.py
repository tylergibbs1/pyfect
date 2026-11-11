"""Ports keep Effect's ``new A(props, { disableChecks: true })``: ``S.new(A, disable_checks=True)``.

For each pyfect test module, the Effect test files its docstrings name (as in
``test_effect_titles.py``) are read for ``new A(...)`` calls whose last argument is
``{ disableChecks: true }``. Where those files construct ``A`` only that way, the module must not
call ``A(...)``. Where they also construct ``A`` with its checks, a module that calls ``A(...)``
must use ``S.new(A, disable_checks=True)`` somewhere too, unless ``MIXED_EXCEPTIONS`` says why
not. A port that dropped the option ran every check Effect skips: 450 thousand of them made one
test time out in CI. Constructions inside helpers of other modules are not seen. Skipped without
an Effect checkout, as in CI.
"""

from __future__ import annotations

import ast
import os
import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import pytest
from _effect_titles import effect_test_files, named_files, skip_balanced, skip_string

_TESTS = Path(__file__).parent
_CHECKOUT = Path(
    os.environ.get("PYFECT_EFFECT_REF") or _TESTS.parent.parent / "pyfect-ref" / "effect"
)
_PACKAGES = _CHECKOUT / "packages"

pytestmark = pytest.mark.skipif(
    not _PACKAGES.is_dir(),
    reason=f"no Effect checkout at {_CHECKOUT}; set PYFECT_EFFECT_REF to Effect's repository",
)

MIXED_EXCEPTIONS: dict[tuple[str, str], str] = {
    (
        "tests/oracle/test_schema_class.py",
        "A",
    ): "Schema.test.ts builds a class A with disableChecks only in a withConstructorDefault "
    "title, ported in test_schema_constructor_default.py",
    (
        "tests/oracle/test_schema_struct_keys.py",
        "A",
    ): "Schema.test.ts builds a class A with disableChecks only in a withConstructorDefault "
    "title, ported in test_schema_constructor_default.py",
}
"""(port module, class): why the module builds the class only with its checks."""

_NEW = re.compile(r"(?<![\w.$])new\s+([\w$.]+)\s*\(")
_DISABLE_CHECKS = re.compile(r"\s*\{\s*disableChecks\s*:\s*true\s*,?\s*\}\s*,?\s*")


@dataclass
class Constructions:
    """The classes an Effect test file constructs, by their last name."""

    unchecked: set[str] = field(default_factory=set[str])
    checked: set[str] = field(default_factory=set[str])


def _last_argument(text: str, start: int, end: int) -> str:
    """The last top-level argument of the call whose arguments are ``text[start:end]``."""
    last = start
    index = start
    while index < end:
        char = text[index]
        if char in "\"'`":
            index = skip_string(text, index)
        elif char in "([{":
            index = skip_balanced(text, index)
        else:
            if char == ",":
                last = index + 1
            index += 1
    tail = text[last:end]
    if not tail.strip() and last > start:
        # A trailing comma: the argument before it.
        return _last_argument(text, start, last - 1)
    return tail


def constructions(source: str) -> Constructions:
    """``source``'s ``new A(...)`` calls, split by whether the last argument is
    ``{ disableChecks: true }``."""
    found = Constructions()
    for match in _NEW.finditer(source):
        opening = match.end() - 1
        closing = skip_balanced(source, opening) - 1
        name = match.group(1).rpartition(".")[2]
        arguments = source[opening + 1 : closing]
        is_options = arguments.strip() and _DISABLE_CHECKS.fullmatch(
            _last_argument(source, opening + 1, closing)
        )
        # ``new A({ disableChecks: true })`` alone is a constructor taking options, not props.
        if is_options and _last_argument(source, opening + 1, closing) != arguments:
            found.unchecked.add(name)
        else:
            found.checked.add(name)
    return found


def _name(node: ast.expr) -> str | None:
    match node:
        case ast.Name(id=name) | ast.Attribute(attr=name):
            return name
        case _:
            return None


@dataclass
class PortCalls:
    plain: dict[str, list[int]] = field(default_factory=lambda: defaultdict(list[int]))
    """Each class called directly, with the lines."""
    unchecked: set[str] = field(default_factory=set[str])
    """Each class built with ``new(A, disable_checks=True)``."""


def port_calls(tree: ast.AST) -> PortCalls:
    calls = PortCalls()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = _name(node.func)
        if name == "new" and node.args:
            target = _name(node.args[0])
            disabled = any(
                k.arg == "disable_checks"
                and isinstance(k.value, ast.Constant)
                and k.value.value is True
                for k in node.keywords
            )
            if target is not None and disabled:
                calls.unchecked.add(target)
        elif name is not None:
            calls.plain[name].append(node.lineno)
    return calls


def _docstrings(tree: ast.Module) -> str:
    nodes = [tree, *(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef | ast.ClassDef))]
    return "\n".join(doc for n in nodes if (doc := ast.get_docstring(n)))


def test_constructions_reads_the_options_argument() -> None:
    source = """
        new EventJournal.Entry({ id, payload: f(a, b) }, { disableChecks: true })
        new RemoteEntry({ entry: new Entry({ id }, {
          disableChecks: true
        }) }, { disableChecks: true },)
        new Checked({ a: "{ disableChecks: true }" })
        new Options({ disableChecks: true })
    """
    found = constructions(source)
    assert found.unchecked == {"Entry", "RemoteEntry"}
    assert found.checked == {"Checked", "Options"}


def test_port_calls_finds_plain_and_unchecked_constructions() -> None:
    tree = ast.parse(
        "J.Entry(id=1)\nS.new(J.RemoteEntry, disable_checks=True)(entry=x)\nnew(Other)(a=1)"
    )
    calls = port_calls(tree)
    assert dict(calls.plain) == {"Entry": [1]}
    assert calls.unchecked == {"RemoteEntry"}


def test_ports_keep_effects_disable_checks_constructions() -> None:
    by_file: dict[str, Constructions] = {}
    for path in effect_test_files(_PACKAGES):
        source = path.read_text()
        if "disableChecks" in source:
            by_file[path.relative_to(_PACKAGES).as_posix()] = constructions(source)
    assert by_file, "no Effect test constructs a class with disableChecks: is the checkout right?"
    all_files = [path.relative_to(_PACKAGES).as_posix() for path in effect_test_files(_PACKAGES)]
    problems: list[str] = []
    ported: set[str] = set()
    excused: set[tuple[str, str]] = set()
    for module in sorted(_TESTS.rglob("*.py")):
        tree = ast.parse(module.read_text())
        named = [by_file[f] for f in named_files(_docstrings(tree), all_files) if f in by_file]
        unchecked = set[str]().union(*(c.unchecked for c in named))
        if not unchecked:
            continue
        checked = set[str]().union(*(c.checked for c in named))
        calls = port_calls(tree)
        where = module.relative_to(_TESTS.parent)
        for name in sorted(unchecked):
            if name in calls.unchecked:
                ported.add(name)
            if name not in calls.plain:
                continue
            key = (where.as_posix(), name)
            if name not in checked:
                lines = ", ".join(map(str, calls.plain[name]))
                problems.append(f"{where}:{lines}: {name}(...) where Effect skips its checks")
            elif key in MIXED_EXCEPTIONS:
                excused.add(key)
            elif name not in calls.unchecked:
                problems.append(f"{where}: Effect builds {name} with disableChecks too; no S.new")
    assert ported, "no port builds a class with S.new(..., disable_checks=True)"
    stale = sorted(set(MIXED_EXCEPTIONS) - excused)
    assert not stale, f"MIXED_EXCEPTIONS entries that match nothing: {stale}"
    assert not problems, "\n".join(problems)
