"""The native stacks the hang alarm (tests/_timeout.py) adds to the report of a test it failed."""

import os
import re
import shutil
import sys
from pathlib import Path

import pytest
from _native_stacks import native_stacks
from _subprocess import SUBPROCESS_TIMEOUT

BLOCKED_IN_C = """
import threading


def test_waits_on_a_lock_it_holds():
    lock = threading.Lock()
    lock.acquire()
    lock.acquire()
"""


def _hang(pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch) -> str:
    monkeypatch.setenv("PYTHONPATH", str(Path(__file__).parent))
    pytester.makepyfile(BLOCKED_IN_C)
    pytester.makeini("[pytest]\ntest_timeout = 0.5\n")
    result = pytester.runpytest_subprocess("-p", "_timeout", timeout=SUBPROCESS_TIMEOUT)
    result.assert_outcomes(failed=1)
    out = result.stdout.str()
    assert "test hung: still running after 0.5s" in out, out
    return out


@pytest.mark.skipif(
    shutil.which("py-spy") is None and shutil.which("gdb") is None, reason="needs gdb or py-spy"
)
def test_a_test_hung_in_c_reports_its_native_frames(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    out = _hang(pytester, monkeypatch)
    assert "native stacks from " in out, out
    stacks = out.split("native stacks from ", 1)[1]
    # a C frame: gdb's "#3  0x... in poll ()", or py-spy's "    poll (libc.so.6)"
    assert re.search(r"^#\d+ +0x[0-9a-f]+ in \S+", stacks, re.MULTILINE) or (
        stacks.startswith("py-spy")
        and re.search(r"^\s+\w+ \(lib[\w.+-]*\.so[\d.]*\)$", stacks, re.MULTILINE)
    ), out


def test_without_a_tool_the_report_says_so_in_one_line(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("PATH", str(tmp_path))
    out = _hang(pytester, monkeypatch)
    assert "native stacks: neither py-spy nor gdb is installed" in out, out


@pytest.mark.skipif(sys.platform == "win32", reason="a shell script stands in for gdb")
def test_a_tool_that_does_not_finish_is_given_up_on(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    gdb = tmp_path / "gdb"
    gdb.write_text(f"#!/bin/sh\nexec {shutil.which('sleep')} 60\n")
    gdb.chmod(0o755)
    monkeypatch.setenv("PATH", str(tmp_path))
    assert native_stacks(os.getpid(), deadline=0.5) == (
        "native stacks: none captured; gdb: still running after 0.5 s"
    )
