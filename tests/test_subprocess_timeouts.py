"""A test waits for an external program at least ``SUBPROCESS_TIMEOUT``
(``tests/_subprocess.py``). A 20-second wait for ``pwsh`` failed on CI
runners where it merely started slowly (22-35 s from a cold disk); the wait
only decides how long a hang takes to fail.

This walks the tests: a ``subprocess`` call, ``communicate`` or
``runpytest_subprocess`` given a literal ``timeout`` shorter than
``SUBPROCESS_TIMEOUT`` fails."""

import ast
from pathlib import Path

from _subprocess import SUBPROCESS_TIMEOUT

_TESTS = Path(__file__).parent
_SUBPROCESS_CALLS = {"run", "Popen", "call", "check_call", "check_output"}
_WAITS = {"communicate", "runpytest_subprocess"}


def _waits_for_a_program(call: ast.Call) -> bool:
    match call.func:
        case ast.Attribute(value=ast.Name(id="subprocess"), attr=name):
            return name in _SUBPROCESS_CALLS
        case ast.Attribute(attr=name):
            return name in _WAITS
        case _:
            return False


def _short_timeouts(tree: ast.AST) -> list[int]:
    return [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and _waits_for_a_program(node)
        for keyword in node.keywords
        if keyword.arg == "timeout"
        and isinstance(keyword.value, ast.Constant)
        and isinstance(keyword.value.value, int | float)
        and keyword.value.value < SUBPROCESS_TIMEOUT
    ]


def test_no_test_waits_less_than_subprocess_timeout_for_a_program():
    found = [
        f"{path.relative_to(_TESTS)}:{line}"
        for path in sorted(_TESTS.rglob("*.py"))
        for line in _short_timeouts(ast.parse(path.read_text(), str(path)))
    ]
    assert found == []


def test_the_guard_sees_a_short_timeout():
    source = (
        "subprocess.run(['pwsh'], timeout=20)\n"
        "process.communicate(b'', timeout=10)\n"
        "subprocess.run(['pwsh'], timeout=SUBPROCESS_TIMEOUT)\n"
        "queue.get(timeout=1)\n"
    )
    assert _short_timeouts(ast.parse(source)) == [1, 2]
