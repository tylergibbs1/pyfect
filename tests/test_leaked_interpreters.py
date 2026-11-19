"""The tests/ plugin that fails a test leaving a subinterpreter alive past its teardown."""

import sys
from pathlib import Path

import pytest
from _subprocess import SUBPROCESS_TIMEOUT

pytestmark = pytest.mark.skipif(
    sys.version_info < (3, 14), reason="needs Python 3.14's concurrent.interpreters"
)

LEAVES_ONE = """
from concurrent import interpreters

left = []


def test_leaves_an_interpreter():
    left.append(interpreters.create())


def test_after_it():
    pass


def test_z_closes_it():
    left.pop().close()
"""

CLOSES_ITS_OWN = """
from concurrent import interpreters


def test_closes_its_interpreter():
    interpreters.create().close()
"""


def _run(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch, source: str
) -> pytest.RunResult:
    monkeypatch.setenv("PYTHONPATH", str(Path(__file__).parent))
    pytester.makepyfile(test_a=source)
    return pytester.runpytest_subprocess(
        "-p", "_leaked_interpreters", "-p", "no:randomly", timeout=SUBPROCESS_TIMEOUT
    )


def test_a_test_that_leaves_a_subinterpreter_alive_fails_in_its_teardown(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    result = _run(pytester, monkeypatch, LEAVES_ONE)
    result.assert_outcomes(passed=3, errors=1)
    out = " ".join(result.stdout.str().split())
    assert "ERROR at teardown of test_leaves_an_interpreter" in out, out
    assert "test_a.py::test_leaves_an_interpreter left subinterpreter" in out, out


def test_a_test_that_closes_its_subinterpreters_passes(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    _run(pytester, monkeypatch, CLOSES_ITS_OWN).assert_outcomes(passed=1)
