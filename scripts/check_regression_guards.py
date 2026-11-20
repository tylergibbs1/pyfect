"""Every regression test fails against the bug it guards: ``uv run python
scripts/check_regression_guards.py [PATCH...]``.

Each test marked with a guard (``tests/_guards.py``) runs against a copy of ``src`` with the
guard's regression patch applied, and must fail there with an assertion or by hanging (a
timing test with its bound ``GUARD_MARGIN`` times looser). A test that passes would pass
against its own bug: a growth check sized too small to see the old cost, say. Any other
exception (an import the patch broke) is an error. Each test runs in a process of its own,
killed past ``DEADLINE`` or once it holds ``MEMORY`` (``run_guarded``): an injected bug may
hold quadratic memory or spin where the hang alarm can't stop it, and either counts as caught.
Too slow for every pull request (an injected quadratic runs until the hang alarm stops it),
so it runs nightly
(``.github/workflows/guards-nightly.yml``); that every patch still applies is checked on
every pull request (``tests/test_regression_patches.py``).
"""

from __future__ import annotations

import argparse
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from collections import defaultdict
from dataclasses import dataclass
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

DEADLINE = 180.0
"""Seconds one guarded test's process may run before it is killed and its bug counted as
caught: three times the hang alarm (``test_timeout``), which leaves its native-stack capture
and pytest's start-up room. The alarm can't stop a bug spinning inside one C call."""

MEMORY = 4 << 30
"""Resident bytes one guarded test's process may hold before it is killed and its bug counted
as caught. A guard's process holds about 0.2 GB, its tests' peaks under 1 GB more;
json-patch's copies held 16 GB within ten seconds against its bug and took the runner down.
Resident, not mapped: the fresh-stack walk maps 300 threads' stacks and touches little."""

_WATCH = 0.2
"""Seconds between reads of the test's resident memory: at the 2 GB a second json-patch's
copies grew, the process is killed within about 0.4 GB of ``MEMORY``."""


@dataclass(frozen=True, slots=True)
class Outcome:
    verdict: Verdict
    why: str
    seconds: float


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


def _resident(pid: int) -> int:
    """Bytes ``pid`` holds in memory, 0 once it is gone."""
    found = subprocess.run(
        ["ps", "-o", "rss=", "-p", str(pid)], capture_output=True, text=True, check=False
    )
    return int(found.stdout.strip() or 0) * 1024


def run_guarded(
    nodeid: str, *, cwd: Path, src: Path, deadline: float = DEADLINE, memory: int = MEMORY
) -> Outcome:
    """``nodeid``'s verdict against the source at ``src``, run in a process of its own (with
    any it starts) killed past ``deadline`` seconds or once it holds ``memory`` bytes."""
    with tempfile.TemporaryDirectory(prefix="guard-report-") as reports:
        report = Path(reports) / "report.xml"
        env = {**os.environ, "PYTHONPATH": str(src), "PYFECT_GUARD_MARGIN": GUARD_MARGIN}
        command = [
            *(sys.executable, "-m", "pytest", "-q", "-p", "no:randomly", "-p", "no:cacheprovider"),
            *("--junitxml", str(report), nodeid),
        ]
        start = time.monotonic()
        with subprocess.Popen(
            command,
            cwd=cwd,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            process_group=0,
        ) as process:
            killed = None
            while (code := process.poll()) is None:
                if time.monotonic() - start > deadline:
                    killed = f"killed: still running after {deadline:g}s"
                elif (held := _resident(process.pid)) > memory:
                    killed = f"killed: held {held / 2**30:.1f} GB, over {memory / 2**30:g} GB"
                if killed:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait()
                    return Outcome("caught", killed, time.monotonic() - start)
                time.sleep(_WATCH)
        seconds = time.monotonic() - start
        found = _outcomes(report).get(nodeid) if report.exists() else None
        verdict, why = found or ("error", f"did not run (exit code {code})")
        return Outcome(verdict, why, seconds)


def check(guard: Guard, nodeids: list[str]) -> dict[str, Outcome]:
    """Each test's verdict against ``src`` with ``guard``'s patch applied."""
    with tempfile.TemporaryDirectory(prefix="guard-") as work:
        copy = Path(work)
        shutil.copytree(ROOT / "src", copy / "src", ignore=shutil.ignore_patterns("__pycache__"))
        applied = subprocess.run(
            ["git", "apply", str(guard.path)], cwd=copy, capture_output=True, text=True, check=False
        )
        if applied.returncode != 0:
            why = applied.stderr.strip()
            return dict.fromkeys(nodeids, Outcome("patch no longer applies", why, 0.0))
        return {nodeid: run_guarded(nodeid, cwd=ROOT, src=copy / "src") for nodeid in nodeids}


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
        for nodeid, found in check(guard, nodeids).items():
            print(
                f"{found.verdict:8} {found.seconds:4.0f}s {guard.patch} {nodeid}  {found.why}",
                flush=True,
            )
            verdicts.append(found.verdict)
    caught = verdicts.count("caught")
    print(f"\n{caught} of {len(verdicts)} guarded tests fail against their bug")
    if caught != len(verdicts):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
