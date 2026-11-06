"""A hung test fails instead of blocking the suite.

Two tx-core mutants (an uninterruptible body, a retry flag never cleared) were
caught only because the suite hung. ``tests/_timeout.py`` turns such a hang
into a test failure.
"""

from pathlib import Path

import pytest

HANGING_TEST = """
import pyfect as fx

def test_waits_forever():
    fx.run_blocking(fx.tx(fx.tx_retry))
"""


def test_a_transaction_that_never_wakes_fails_the_test(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PYTHONPATH", str(Path(__file__).parent))
    pytester.makepyfile(HANGING_TEST)
    pytester.makeini("[pytest]\ntest_timeout = 0.5\n")
    result = pytester.runpytest_subprocess("-p", "_timeout", timeout=30)
    result.assert_outcomes(failed=1)
    result.stdout.fnmatch_lines(["*test hung: still running after 0.5s*"])


def test_the_suite_loads_the_timeout_plugin(pytestconfig: pytest.Config) -> None:
    assert pytestconfig.pluginmanager.has_plugin("_timeout")
