"""A shared test server whose start did not finish (it raised, or the per-test timeout
stopped it) fails every later test at once with that error. Each later test used to start
it again and wait out its own timeout: one stalled ``docker run`` cost 60 s per test."""

from pathlib import Path

import pytest

SERVERS = ["_clickhouse", "_libsql", "_mssql", "_mysql", "_postgres", "_redis"]

_TESTS = """
import pytest

from oracle import {module} as shared

starts = []


def hangs():
    starts.append(None)
    pytest.fail("test hung: still running after 60s")


shared._start = hangs


def test_first():
    shared.server()


def test_second():
    shared.server()


def test_started_once():
    assert len(starts) == 1
"""


@pytest.mark.parametrize("module", SERVERS)
def test_a_start_that_did_not_finish_fails_later_tests_with_its_error(
    module: str, pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("PYTHONPATH", str(Path(__file__).parents[1]))
    pytester.makepyfile(test_uses=_TESTS.format(module=module))
    result = pytester.runpytest_subprocess("-p", "no:randomly", "-p", "no:cacheprovider")
    result.assert_outcomes(passed=1, failed=2)
    result.stdout.fnmatch_lines(
        [
            "*_ test_first _*",
            "E *Failed: test hung: still running after 60s",
            "*_ test_second _*",
            "E *Failed: * did not start in an earlier test: test hung: still running after 60s",
        ]
    )
