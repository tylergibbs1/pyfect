"""Running an external program (a shell, a Python script) from a test.

Starting one can take seconds on a CI runner: ``pwsh`` with a completion
script took 0.8 s on an idle GitHub runner, 3 s with every CPU busy, and
6-35 s reading its files from the runner's cold disk (``ci.yml`` starts it
once before the tests for that). So the wait is ``SUBPROCESS_TIMEOUT``,
generous and under the test's own hang timeout (60 s, ``_timeout.py``): it
only decides how long a hang takes to fail. ``test_subprocess_timeouts.py``
keeps shorter literal timeouts out of the tests."""

import subprocess
from pathlib import Path

SUBPROCESS_TIMEOUT = 45.0
"""Seconds a test waits for an external program to finish."""


def run_program(args: list[str], *, cwd: str | Path) -> str:
    """Run ``args`` in ``cwd`` with empty input, not the test run's own, and
    return its standard output; fails if it exits with an error."""
    return subprocess.run(
        args,
        cwd=cwd,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        check=True,
        timeout=SUBPROCESS_TIMEOUT,
    ).stdout
