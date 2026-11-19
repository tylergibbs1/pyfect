"""In CI a skipped test fails the run unless its reason is one ``ALLOWED`` explains.

A test that skips because a server, a binary or an interpreter was missing tests nothing, and a
green run hides it (CI once skipped about 400 PostgreSQL and Redis tests this way). With
``PYFECT_REQUIRE_ALL_TESTS=1`` (set by .github/workflows/ci.yml) every skip is checked at the end
of the session: one no rule allows makes the session fail and names it. Locally nothing changes.
"""

from __future__ import annotations

import os
import re
import sys
from collections.abc import Callable
from dataclasses import dataclass

import pytest

ENV = "PYFECT_REQUIRE_ALL_TESTS"


@dataclass(frozen=True)
class Allowed:
    reason: re.Pattern[str]
    why: str
    applies: Callable[[], bool] = lambda: True


def _before_314() -> bool:
    return sys.version_info < (3, 14)


ALLOWED = (
    Allowed(
        re.compile(r"t-strings|compression\.zstd|concurrent\.interpreters"),
        "needs Python 3.14; the 3.14 jobs run it",
        _before_314,
    ),
    Allowed(
        re.compile(r"^(\w+) has no (\w+) helper$|^SQLite has no |^\S+ has no strategy$"),
        "a parametrization the case does not apply to",
    ),
    Allowed(re.compile(r"^skipped anyway$"), "a port of Effect's test of a skipped test"),
    Allowed(
        re.compile(r"^fumadocs-python is not installed"),
        "runs in docs.yml's site job, which installs website/",
    ),
)


def allowed(reason: str) -> Allowed | None:
    return next((rule for rule in ALLOWED if rule.reason.search(reason) and rule.applies()), None)


def _skip_reason(report: pytest.TestReport) -> str:
    longrepr = report.longrepr
    if isinstance(longrepr, tuple):
        return str(longrepr[2]).removeprefix("Skipped: ")
    return str(longrepr)


@dataclass(eq=False)  # a plugin: pluggy hashes it
class _Guard:
    unexpected: list[tuple[str, str]]

    @pytest.hookimpl
    def pytest_runtest_logreport(self, report: pytest.TestReport) -> None:
        if report.skipped and not hasattr(report, "wasxfail"):
            reason = _skip_reason(report)
            if allowed(reason) is None:
                self.unexpected.append((report.nodeid, reason))

    @pytest.hookimpl(trylast=True)
    def pytest_sessionfinish(self, session: pytest.Session) -> None:
        if self.unexpected and session.exitstatus == pytest.ExitCode.OK:
            session.exitstatus = pytest.ExitCode.TESTS_FAILED

    @pytest.hookimpl
    def pytest_terminal_summary(self, terminalreporter: pytest.TerminalReporter) -> None:
        if not self.unexpected:
            return
        terminalreporter.section(f"skips {ENV} does not allow (tests/_skips.py)", red=True)
        for nodeid, reason in self.unexpected:
            terminalreporter.line(f"{nodeid}: {reason}")


def pytest_configure(config: pytest.Config) -> None:
    if os.environ.get(ENV) == "1":
        config.pluginmanager.register(_Guard([]), "pyfect-require-all-tests")
