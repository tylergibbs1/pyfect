"""A hung test fails instead of blocking the suite.

Two tx-core mutants (an uninterruptible body, a retry flag never cleared) were
caught only because the suite hung. ``tests/_timeout.py`` turns such a hang
into a test failure.
"""

from pathlib import Path

import pytest
from _subprocess import SUBPROCESS_TIMEOUT

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
    result = pytester.runpytest_subprocess("-p", "_timeout", timeout=SUBPROCESS_TIMEOUT)
    result.assert_outcomes(failed=1)
    result.stdout.fnmatch_lines(["*test hung: still running after 0.5s*"])


SPINNING_LOOP_TEST = """
import asyncio
import time

def test_spins_in_the_loop():
    async def main():
        loop = asyncio.get_running_loop()

        def spin_in_a_callback():
            time.sleep(0.01)
            loop.call_soon(spin_in_a_callback)

        spin_in_a_callback()
        await asyncio.Event().wait()

    asyncio.run(main())
"""


def test_a_test_spinning_inside_an_asyncio_loop_fails_where_it_was_stuck(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    """asyncio runs callbacks catching every exception but ``KeyboardInterrupt`` and
    ``SystemExit`` (it reports the rest to the loop's exception handler), so an alarm that
    raised ``pytest.fail`` there was swallowed and the test hung for good."""
    monkeypatch.setenv("PYTHONPATH", str(Path(__file__).parent))
    pytester.makepyfile(SPINNING_LOOP_TEST)
    pytester.makeini("[pytest]\ntest_timeout = 0.5\n")
    result = pytester.runpytest_subprocess("-p", "_timeout", timeout=SUBPROCESS_TIMEOUT)
    result.assert_outcomes(failed=1)
    result.stdout.fnmatch_lines(
        [
            "*test hung: still running after 0.5s; stuck in:*",
            "*in spin_in_a_callback*",
            "*task Task-1 awaits in:*",
            "*in main*",
        ]
    )


def test_the_suite_loads_the_timeout_plugin(pytestconfig: pytest.Config) -> None:
    assert pytestconfig.pluginmanager.has_plugin("_timeout")
