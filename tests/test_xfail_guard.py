"""Every expected failure says why and fails on every run, whatever the timing.

A strict xfail on a ``testing.live`` test (the real clock) failed CI when a slow run made it
pass: "rebalances on runner addition, graceful stop, and abrupt death" waited 15 s for a
handover that a 15 s timeout gated. So no live test is marked xfail, every xfail names its
reason, and ``xfail_strict`` (pyproject) makes an unexpected pass fail the run, so none may
opt out with ``strict=False``.
"""

import ast
from pathlib import Path

TESTS = Path(__file__).parent


def _called(node: ast.AST, name: str) -> bool:
    """``<anything>.name(...)`` or ``<anything>.name``."""
    target = node.func if isinstance(node, ast.Call) else node
    return isinstance(target, ast.Attribute) and target.attr == name


def _problems(source: str, where: str) -> list[str]:
    tree = ast.parse(source)
    problems: list[tuple[int, str]] = []
    xfail_names = {
        target.id
        for node in tree.body
        if isinstance(node, ast.Assign) and _called(node.value, "xfail")
        for target in node.targets
        if isinstance(target, ast.Name)
    }
    called = {id(node.func) for node in ast.walk(tree) if isinstance(node, ast.Call)}
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr == "xfail" and id(node) not in called:
            problems.append((node.lineno, "xfail without a reason"))
        elif isinstance(node, ast.Call) and _called(node, "xfail"):
            keywords = {k.arg: k.value for k in node.keywords}
            if "reason" not in keywords and not node.args:
                problems.append((node.lineno, "xfail without a reason"))
            strict = keywords.get("strict")
            if isinstance(strict, ast.Constant) and strict.value is False:
                problems.append((node.lineno, "xfail with strict=False"))
        elif isinstance(node, ast.FunctionDef) and any(
            _called(d, "live") for d in node.decorator_list
        ):
            marked = any(
                _called(n, "xfail") or (isinstance(n, ast.Name) and n.id in xfail_names)
                for d in node.decorator_list
                for n in ast.walk(d)
            ) or any(_called(n, "xfail") for n in ast.walk(node))
            if marked:
                problems.append((node.lineno, f"xfail on the live test {node.name}"))
    return [f"{where}:{line} {problem}" for line, problem in sorted(problems)]


def test_xfails_name_a_reason_stay_strict_and_skip_live_tests():
    problems = [
        problem
        for path in sorted(TESTS.rglob("*.py"))
        for problem in _problems(path.read_text(encoding="utf-8"), str(path.relative_to(TESTS)))
    ]
    assert problems == []


_FLAGGED = """
import pytest
from pyfect import testing

_GAP = pytest.mark.xfail(reason="pyfect gap")

@pytest.mark.xfail(strict=False, reason="flaky")
def test_lenient(): ...

@pytest.mark.xfail
def test_unexplained(): ...

@_GAP
@testing.live(timeout="1 minute")
def test_named_marker(): ...

@testing.live(timeout="1 minute")
def test_applied(request):
    request.applymarker(pytest.mark.xfail(reason="race"))

def test_fine():
    pytest.xfail("an upstream bug")
"""


def test_the_guard_flags_each_kind_of_problem():
    assert _problems(_FLAGGED, "t.py") == [
        "t.py:7 xfail with strict=False",
        "t.py:10 xfail without a reason",
        "t.py:15 xfail on the live test test_named_marker",
        "t.py:18 xfail on the live test test_applied",
    ]
