"""Adds every thread's native stack to the report of a test the hang alarm failed.

A hang inside C (a subinterpreter call, a lock, a driver) shows up in Python's stacks only as
the call that never returned. ``py-spy dump --native`` when it is installed, else ``gdb``,
reads the C frames of the hung process. The alarm (``tests/_timeout.py``) takes them while the
test is still stuck, before it raises the failure, as ``capture``: once the failure unwinds the
test, the frames that hung are gone. The capture has a deadline and never raises, so it can't
mask the failure and delays it by at most ``DEADLINE`` seconds; any problem is a line of the
report instead of the stacks.
"""

import ctypes
import math
import os
import shutil
import subprocess
import sys
import threading
import time
from collections.abc import Generator
from contextlib import contextmanager

import pytest

DEADLINE = 10.0
"""Seconds the capture may take, both tools together."""

_PR_SET_PTRACER = 0x59616D61
_PR_SET_PTRACER_ANY = ctypes.c_ulong(-1).value


def _commands(pid: int) -> list[tuple[str, list[str], str]]:
    """Each tool, its arguments, and what its output holds once it read frames (gdb exits 0
    after it failed to attach, too)."""
    return [
        ("py-spy", ["dump", "--native", "--pid", str(pid)], "Thread "),
        ("gdb", ["-p", str(pid), "-batch", "-nx", "-ex", "thread apply all bt"], "#0 "),
    ]


@contextmanager
def _traceable() -> Generator[None]:
    """Lets a child attach to this process where Yama's ptrace_scope 1 allows tracing only
    descendants (Ubuntu's default): the tools run as children of the process they read."""
    if sys.platform != "linux":
        yield
        return
    libc = ctypes.CDLL(None, use_errno=True)
    libc.prctl(_PR_SET_PTRACER, _PR_SET_PTRACER_ANY, 0, 0, 0)
    try:
        yield
    finally:
        libc.prctl(_PR_SET_PTRACER, 0, 0, 0, 0)


def _last_line(text: str) -> str:
    lines = [line for line in text.strip().splitlines() if line.strip()]
    return lines[-1] if lines else "no output"


def native_stacks(pid: int, deadline: float = DEADLINE) -> str:
    """Every thread's native stack in process ``pid``, or one line saying why there are none."""
    found = [
        (name, path, args, frames)
        for name, args, frames in _commands(pid)
        if (path := shutil.which(name)) is not None
    ]
    if not found:
        return "native stacks: neither py-spy nor gdb is installed"
    ends = time.monotonic() + deadline
    failures: list[str] = []
    try:
        with _traceable():
            for name, path, args, frames in found:
                left = ends - time.monotonic()
                if left <= 0:
                    failures.append(f"{name}: no time left")
                    continue
                try:
                    done = subprocess.run(
                        [path, *args], capture_output=True, text=True, timeout=left, check=False
                    )
                except subprocess.TimeoutExpired:
                    failures.append(f"{name}: still running after {deadline:g} s")
                    continue
                if done.returncode == 0 and frames in done.stdout:
                    return f"native stacks from {name}:\n{done.stdout.rstrip()}"
                failures.append(f"{name}: {_last_line(done.stderr or done.stdout)}")
    except Exception as error:  # the report must still go out
        failures.append(f"{type(error).__name__}: {error}")
    return "native stacks: none captured; " + "; ".join(failures)


_CAPTURED = pytest.StashKey[str]()
_captures: list[tuple[float, float]] = []
"""When each capture ran (``time.monotonic``): a tool attached to the process stops every
thread, which the stall watchdog (``tests/_stalls.py``) would report as a frozen host."""
_captures_lock = threading.Lock()


def capture(item: pytest.Item) -> None:
    """Takes this process's native stacks for ``item``'s report, once, while it hangs."""
    if _CAPTURED in item.stash:
        return
    # Open until it ends: when the tool lets go, the watchdog may run before this thread.
    window = (time.monotonic(), math.inf)
    with _captures_lock:
        _captures.append(window)
        del _captures[:-8]
    try:
        item.stash[_CAPTURED] = native_stacks(os.getpid())
    finally:
        with _captures_lock:
            _captures[_captures.index(window)] = (window[0], time.monotonic())


def froze(since: float, until: float) -> bool:
    """Whether a capture ran between ``since`` and ``until`` (``time.monotonic``)."""
    with _captures_lock:
        return any(start < until and end > since for start, end in _captures)


@pytest.hookimpl(wrapper=True)
def pytest_runtest_makereport(
    item: pytest.Item, call: pytest.CallInfo[None]
) -> Generator[None, pytest.TestReport, pytest.TestReport]:
    report = yield
    captured = item.stash.get(_CAPTURED, None)
    if call.when == "call" and captured is not None:
        report.sections.append(("native stacks", captured))
    return report
