"""In CI, name each failure the moment it is reported, on stderr and in the job's step summary.

pytest names failures only in its end-of-run summary, so a shard the job limit cancels, or a
run killed any other way, leaves bare ``F`` marks (run 44406946037 lost three this way). With
``GITHUB_ACTIONS=true`` each failed setup, call or teardown is written as it comes in, one line
like the summary's. Under xdist the controller writes them, as the workers' reports arrive. A
pytest run that a test starts inherits ``PYTEST_XDIST_WORKER`` and writes nothing, so failures
it expects never reach the summary. Locally nothing changes.
"""

from __future__ import annotations

import os
import sys

import pytest


def _reason(report: pytest.TestReport) -> str:
    crash = getattr(report.longrepr, "reprcrash", None)
    message: str = getattr(crash, "message", "") or str(report.longrepr)
    return message.splitlines()[0] if message else ""


def _line(report: pytest.TestReport) -> str:
    kind = "FAILED" if report.when == "call" else f"ERROR at {report.when} of"
    return f"{kind} {report.nodeid} - {_reason(report)}"


def pytest_configure(config: pytest.Config) -> None:
    if (
        os.environ.get("GITHUB_ACTIONS") == "true"
        and "PYTEST_XDIST_WORKER" not in os.environ
        and not hasattr(config, "workerinput")
    ):
        config.pluginmanager.register(_NameFailures(), "failures-named-at-once")


class _NameFailures:
    def pytest_runtest_logreport(self, report: pytest.TestReport) -> None:
        if not report.failed:
            return
        line = _line(report)
        sys.stderr.write(line + "\n")
        sys.stderr.flush()
        if summary := os.environ.get("GITHUB_STEP_SUMMARY"):
            with open(summary, "a", encoding="utf-8") as file:
                file.write(f"- {line.replace(report.nodeid, f'`{report.nodeid}`', 1)}\n")
