"""An effect test fits in the default real-time timeout, 5 s, as in Effect.

``@testing.effect`` interrupts a test after 5 s of real time by default, as
``@effect/vitest`` inherits vitest's ``testTimeout``. A busy machine stretches real
time, so a test that needs more than that fails under load (pytest-xdist on a CI
runner): its timing belongs on the ``TestClock``, or it must get faster. A longer
limit is not the fix. The tests in ``tests/_longer_timeouts.txt`` still set one; each is
a bug to fix, listed so the list only shrinks (issue #21). A timeout of 5 s or less
is always allowed.
"""

from __future__ import annotations

import ast
import tomllib
from pathlib import Path

import _source
from _inventory import parse
from _source import TESTS

from pyfect.duration import from_input_unsafe, seconds
from pyfect.testing._decorators import settings

_DEFAULT_SECONDS = 5.0
_DECORATORS = frozenset({"effect", "live", "prop", "effect_prop", "live_prop", "layer_fixture"})

LONGER = TESTS / "_longer_timeouts.txt"
"""``path::name timeout  # reason`` per line (``tests/_inventory.py``): the test, or the
module-level name bound to the decorator, still allowed more than 5 s, and the real time it
waits on that the TestClock cannot drive."""


def _listed() -> dict[str, str]:
    return {test: entry.value for test, entry in parse(LONGER.read_text()).items()}


def _longer_timeouts(path: Path) -> dict[str, str]:
    name = path.relative_to(TESTS).as_posix()
    found: dict[str, str] = {}

    def visit(node: ast.AST, owner: str) -> None:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and owner == "":
            owner = node.name
        elif isinstance(node, ast.Assign) and owner == "" and len(node.targets) == 1:
            target = node.targets[0]
            if isinstance(target, ast.Name):
                owner = target.id
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in _DECORATORS
            and ast.unparse(node.func.value).endswith("testing")
        ):
            for keyword in node.keywords:
                value = keyword.value
                if keyword.arg != "timeout" or not isinstance(value, ast.Constant):
                    continue
                assert isinstance(value.value, str | int | float), ast.unparse(value)
                if from_input_unsafe(value.value).to_seconds() > _DEFAULT_SECONDS:
                    key = f"{name}::{owner}"
                    assert key not in found, f"{key} sets two timeouts"
                    found[key] = str(value.value)
        for child in ast.iter_child_nodes(node):
            visit(child, owner)

    visit(_source.tree(path), "")
    return found


def _all_longer_timeouts() -> dict[str, str]:
    found: dict[str, str] = {}
    for path in _source.files(TESTS, "test_*.py"):
        if _source.mentions(path, "timeout"):  # the keyword every longer timeout sets
            found |= _longer_timeouts(path)
    return found


def test_the_default_timeout_is_effects() -> None:
    config = tomllib.loads((TESTS.parent / "pyproject.toml").read_text())
    assert "pyfect_timeout" not in config["tool"]["pytest"]["ini_options"]
    assert settings.timeout == seconds(_DEFAULT_SECONDS)


def test_only_listed_tests_take_longer_than_the_default() -> None:
    assert _all_longer_timeouts() == _listed(), (
        "a test that needs more than 5 s of real time is a bug: check timing on the "
        "TestClock or make it faster; delete a fixed test's line from tests/_longer_timeouts.txt"
    )
