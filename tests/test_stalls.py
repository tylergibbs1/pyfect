"""``tests/_stalls.py`` names what stalled a test: pyfect blocking, or the host.

Each case runs a small test file under the plugin in a subprocess, with a short
``stall_threshold``, and reads the "stall" section of its failure.
"""

from pathlib import Path

import pytest
from _stalls import DumpedThread, Frame, _dump_threads  # pyright: ignore[reportPrivateUsage]
from _subprocess import SUBPROCESS_TIMEOUT

BLOCKING_FIBER = """
import time

import pyfect as fx


def wait_on_purpose():
    time.sleep(0.8)  # a blocking call inside a fiber step


def test_blocks():
    fx.run_blocking(fx.sync(wait_on_purpose))
    assert False
"""

GIL_HELD = """
import pyfect as fx


def count_on_purpose():
    return sum(range(3 * 10**8))  # one C call (about 1 s), holding the GIL


def test_holds_the_gil():
    fx.run_blocking(fx.sync(count_on_purpose))
    assert False
"""

FROZEN_PROCESS = """
import os
import subprocess

import pyfect as fx


def test_is_frozen():
    # What a starved host does to the process: no thread runs, and no CPU time passes.
    pid = os.getpid()
    script = f"sleep 0.2; kill -STOP {pid}; sleep 1; kill -CONT {pid}"
    freezer = subprocess.Popen(["sh", "-c", script])
    fx.run_blocking(fx.sleep("1500 millis"))
    freezer.wait(timeout=5)
    assert False
"""

IDLE_WAIT = """
import pyfect as fx


def test_sleeps():
    fx.run_blocking(fx.sleep("800 millis"))
    assert False
"""


def _run(pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch, source: str) -> str:
    monkeypatch.setenv("PYTHONPATH", str(Path(__file__).parent))
    pytester.makepyfile(source)
    pytester.makeini("[pytest]\nstall_threshold = 0.3\n")
    result = pytester.runpytest_subprocess("-p", "_stalls", timeout=SUBPROCESS_TIMEOUT)
    result.assert_outcomes(failed=1)
    return result.stdout.str()


def test_a_blocking_call_in_a_fiber_step_is_named(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    out = _run(pytester, monkeypatch, BLOCKING_FIBER)
    assert "stall" in out
    assert "pyfect blocked in wait_on_purpose (" in out
    assert "test_a_blocking_call_in_a_fiber_step_is_named.py:7)" in out


@pytest.mark.skipif(
    not getattr(__import__("sys"), "_is_gil_enabled", lambda: True)(),
    reason="free-threaded: a C call holds no GIL, and the fiber sampler names it",
)
def test_a_c_call_holding_the_gil_is_named_from_the_faulthandler_dump(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    out = _run(pytester, monkeypatch, GIL_HELD)
    assert "process stalled" in out
    assert "pyfect blocked in count_on_purpose (" in out


@pytest.mark.skipif(__import__("sys").platform == "win32", reason="SIGSTOP is POSIX")
def test_a_frozen_process_is_named_a_host_stall(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    out = _run(pytester, monkeypatch, FROZEN_PROCESS)
    assert "process stalled 1." in out
    assert ": host (" in out
    assert "pyfect blocked" not in out


def test_a_fiber_waiting_on_a_timer_is_no_stall(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    out = _run(pytester, monkeypatch, IDLE_WAIT)
    assert "process stalled" not in out


def test_a_dump_reads_each_threads_frames_innermost_first() -> None:
    dump = (
        "Timeout (0:00:02)!\n"
        "Thread 0x00007f0000000001 (most recent call first):\n"
        '  File "/usr/lib/python3.13/threading.py", line 359 in wait\n'
        '  File "/w/app.py", line 3 in main\n'
        "\n"
        "Current thread 0x00007f0000000002 (most recent call first):\n"
        '  File "/w/app.py", line 9 in spin\n'
    )
    assert _dump_threads(dump) == [
        DumpedThread(
            "0x00007f0000000001",
            False,
            (
                Frame("/usr/lib/python3.13/threading.py", 359, "wait"),
                Frame("/w/app.py", 3, "main"),
            ),
        ),
        DumpedThread("0x00007f0000000002", True, (Frame("/w/app.py", 9, "spin"),)),
    ]
    assert Frame("/usr/lib/python3.13/threading.py", 359, "wait").idle
    assert not Frame("/w/app.py", 9, "spin").idle


def test_the_suite_loads_the_stall_plugin(pytestconfig: pytest.Config) -> None:
    assert pytestconfig.pluginmanager.has_plugin("_stalls")
