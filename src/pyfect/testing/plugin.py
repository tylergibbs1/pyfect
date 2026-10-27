"""The pytest plugin, registered through the ``pytest11`` entry point.

- The ``pyfect_timeout`` ini option sets the default real-time timeout of
  ``@effect`` and ``@live`` tests (seconds; ``0`` disables it).
- The ``pyfect_effect`` and ``pyfect_live`` markers are put on those tests,
  so ``-m "not pyfect_live"`` skips the tests that take real time.
- A failed ``==`` involving an ``Exit`` failure shows its ``Cause.pretty()``.
"""

from __future__ import annotations

import pytest

from pyfect.duration import Seconds
from pyfect.exit import Failure
from pyfect.testing._assertions import describe_exit
from pyfect.testing._decorators import settings


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addini(
        "pyfect_timeout",
        "Default real-time timeout, in seconds, of @fx.testing.effect and @fx.testing.live "
        "tests (0 disables it)",
        default="5",
    )


_previous_timeout = pytest.StashKey[Seconds | None]()


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "pyfect_effect: a test run with a TestClock")
    config.addinivalue_line("markers", "pyfect_live: a test run with the live clock")
    config.stash[_previous_timeout] = settings.timeout
    timeout = float(config.getini("pyfect_timeout"))
    settings.timeout = Seconds(timeout) if timeout > 0 else None


def pytest_unconfigure(config: pytest.Config) -> None:
    # A nested in-process run (pytester) must not change the outer defaults.
    settings.timeout = config.stash.get(_previous_timeout, settings.timeout)


def pytest_assertrepr_compare(op: str, left: object, right: object) -> list[str] | None:
    if op != "==":
        return None
    failures: list[Failure[object]] = [side for side in (left, right) if isinstance(side, Failure)]
    if not failures:
        return None
    lines = [f"{left!r} == {right!r}"]
    for failure in failures:
        lines.extend(describe_exit(failure).splitlines())
    return lines
