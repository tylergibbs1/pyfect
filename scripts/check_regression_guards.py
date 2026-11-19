"""Every regression test fails against the bug it guards: ``uv run python
scripts/check_regression_guards.py [PATCH...]``.

Each test marked with a guard (``tests/_guards.py``) runs against a copy of ``src`` with the
guard's regression patch applied, and must fail there with an assertion or by hanging (a
timing test with its bound ``GUARD_MARGIN`` times looser). A test that passes would pass
against its own bug: a growth check sized too small to see the old cost, say. Any other
exception (an import the patch broke) is an error. Too slow for every pull request (an injected
quadratic runs until the hang alarm stops it), so it runs nightly
(``.github/workflows/guards-nightly.yml``); that every patch still applies is checked on
every pull request (``tests/test_regression_patches.py``).
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path
from typing import Any, Literal

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from tests._guards import Guard  # noqa: E402, TID251


class _Collector:
    def __init__(self) -> None:
        self.guarded: dict[Guard, list[str]] = defaultdict(list)

    def pytest_collection_modifyitems(self, items: list[pytest.Item]) -> None:
        for item in items:
            for mark in item.iter_markers("guards"):
                # The tests import the module as ``_guards``, this script as ``tests._guards``.
                found: Any = mark.args[0]
                self.guarded[Guard(found.fix, found.patch)].append(item.nodeid)


def _guarded_files() -> list[str]:
    found = subprocess.run(
        ["git", "grep", "-l", "-e", "from _guards import", "--", "tests"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    files = {path for path in found.stdout.split() if Path(path).name.startswith("test_")}
    return sorted(files | {"tests/security/test_parser_complexity.py"})


def _collect() -> dict[Guard, list[str]]:
    collector = _Collector()
    code = pytest.main(
        ["--collect-only", "-q", "-p", "no:randomly", *_guarded_files()], [collector]
    )
    if code != 0:
        raise SystemExit(f"collection failed ({code})")
    return collector.guarded


GUARD_MARGIN = "1.5"
"""A timing test catches its bug only if it fails with its bound this many times looser
(``tests/_growth.py``): one that clears the bound only just is missed on another machine."""

type Verdict = Literal["caught", "MISSED", "error", "skipped", "patch no longer applies"]

_CAUGHT = ("AssertionError", "assert ", "Failed: test hung", "Failed: DID NOT RAISE")
"""Failures that are the test's own verdict."""


def _outcomes(report: Path) -> dict[str, tuple[Verdict, str]]:
    outcomes: dict[str, tuple[Verdict, str]] = {}
    for case in ET.parse(report).iter("testcase"):
        path = case.get("classname", "").replace(".", "/") + ".py"
        name = f"{path}::{case.get('name')}"
        failure = case.find("failure")
        problem = failure if failure is not None else case.find("error")
        if problem is not None:
            message = (problem.get("message") or "").strip()
            why = message.splitlines()[0][:400] if message else ""
            caught = failure is not None and message.startswith(_CAUGHT)
            outcomes[name] = ("caught" if caught else "error", why)
        elif case.find("skipped") is not None:
            outcomes[name] = ("skipped", "")
        else:
            outcomes[name] = ("MISSED", "")
    return outcomes


def check(guard: Guard, nodeids: list[str]) -> dict[str, tuple[Verdict, str]]:
    """Each test's verdict against ``src`` with ``guard``'s patch applied."""
    with tempfile.TemporaryDirectory(prefix="guard-") as work:
        copy = Path(work)
        shutil.copytree(ROOT / "src", copy / "src", ignore=shutil.ignore_patterns("__pycache__"))
        applied = subprocess.run(
            ["git", "apply", str(guard.path)], cwd=copy, capture_output=True, text=True, check=False
        )
        if applied.returncode != 0:
            return dict.fromkeys(nodeids, ("patch no longer applies", applied.stderr.strip()))
        env = {**os.environ, "PYTHONPATH": str(copy / "src"), "PYFECT_GUARD_MARGIN": GUARD_MARGIN}
        report = copy / "report.xml"
        subprocess.run(
            [
                *(
                    sys.executable,
                    "-m",
                    "pytest",
                    "-q",
                    "-p",
                    "no:randomly",
                    "-p",
                    "no:cacheprovider",
                ),
                *("--junitxml", str(report), *nodeids),
            ],
            cwd=ROOT,
            env=env,
            capture_output=True,
            check=False,
        )
        found = _outcomes(report) if report.exists() else {}
        return {nodeid: found.get(nodeid, ("error", "did not run")) for nodeid in nodeids}


def main() -> None:
    parser = argparse.ArgumentParser(description="Every regression test fails against its bug.")
    parser.add_argument("patches", nargs="*", help="check only the guards of these patches")
    only = set(parser.parse_args().patches)
    guarded = _collect()
    if unknown := only - {guard.patch for guard in guarded}:
        raise SystemExit(f"no test guards {sorted(unknown)}")
    if not guarded:
        raise SystemExit("no guarded tests found")
    verdicts: list[Verdict] = []
    for guard, nodeids in sorted(guarded.items(), key=lambda pair: pair[0].patch):
        if only and guard.patch not in only:
            continue
        for nodeid, (verdict, why) in check(guard, nodeids).items():
            print(f"{verdict:8} {guard.patch} {nodeid}  {why}", flush=True)
            verdicts.append(verdict)
    caught = verdicts.count("caught")
    print(f"\n{caught} of {len(verdicts)} guarded tests fail against their bug")
    if caught != len(verdicts):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
