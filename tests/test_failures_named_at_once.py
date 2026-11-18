"""``tests/_failures_named_at_once.py``: in CI each failure is named the moment it is reported.

A shard the job limit cancels, or a run killed some other way, never prints pytest's summary,
so its ``F`` marks name nothing (run 44406946037 lost three this way). Each case runs a file
whose first test fails and whose second kills the run, then looks for the first test's id.
"""

from pathlib import Path

import pytest
from _subprocess import SUBPROCESS_TIMEOUT

FAILS_THEN_KILLED = """
import os
import signal
import time


def test_a_fails():
    assert 1 == 2, "one is not two"


def test_b_kills_the_run():
    time.sleep(0.5)  # under xdist: let the controller take test_a_fails's report first
    pid = os.getpid() if os.environ["KILL"] == "self" else os.getppid()  # xdist: the controller
    os.kill(pid, signal.SIGKILL)
"""


@pytest.mark.parametrize(
    ("args", "kill"),
    [
        pytest.param((), "self", id="no-xdist"),
        pytest.param(("-n", "1"), "controller", id="xdist"),
    ],
)
def test_a_killed_run_has_named_its_failure(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch, args: tuple[str, ...], kill: str
):
    monkeypatch.setenv("PYTHONPATH", str(Path(__file__).parent))
    summary = pytester.path / "step-summary.md"
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.delenv("PYTEST_XDIST_WORKER", raising=False)  # set when this test runs in one
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    monkeypatch.setenv("KILL", kill)
    pytester.makepyfile(test_killed=FAILS_THEN_KILLED)
    result = pytester.runpytest_subprocess(
        "-q",
        "-p",
        "_failures_named_at_once",
        "-p",
        "no:randomly",
        *args,
        timeout=SUBPROCESS_TIMEOUT,
    )
    assert result.ret != 0
    assert "short test summary" not in result.stdout.str()  # the run never reached its end
    line = "FAILED test_killed.py::test_a_fails - AssertionError: one is not two"
    assert line in result.stderr.str(), result.stderr.str()
    assert "`test_killed.py::test_a_fails`" in summary.read_text()


def test_a_run_a_worker_starts_names_nothing(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
):
    # Its failures are a test's business, not the CI job's.
    monkeypatch.setenv("PYTHONPATH", str(Path(__file__).parent))
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("PYTEST_XDIST_WORKER", "gw0")
    summary = pytester.path / "step-summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    pytester.makepyfile(test_one="def test_fails():\n    assert False\n")
    result = pytester.runpytest_subprocess(
        "-q", "-p", "_failures_named_at_once", "-p", "no:randomly", timeout=SUBPROCESS_TIMEOUT
    )
    assert result.ret == pytest.ExitCode.TESTS_FAILED
    assert "test_one.py::test_fails" not in result.stderr.str()
    assert not summary.exists()


def test_outside_ci_nothing_is_printed_early(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("PYTHONPATH", str(Path(__file__).parent))
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    pytester.makepyfile(test_one="def test_fails():\n    assert False\n")
    result = pytester.runpytest_subprocess(
        "-q", "-p", "_failures_named_at_once", "-p", "no:randomly", timeout=SUBPROCESS_TIMEOUT
    )
    assert result.ret == pytest.ExitCode.TESTS_FAILED
    assert "test_one.py::test_fails" not in result.stderr.str()
