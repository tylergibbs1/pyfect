"""``tests/_stalls.py`` names what stalled a test: pyfect blocking, or the host.

Each case runs a small test file under the plugin in a subprocess, with a short
``stall_threshold``, and reads the "stall" section of its failure.
"""

from pathlib import Path

import pytest
from _stalls import (
    DumpedThread,
    Frame,
    _dump_threads,  # pyright: ignore[reportPrivateUsage]
    _no_busy_thread,  # pyright: ignore[reportPrivateUsage]
)
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

GIL_HELD_SLEEP = """
import ctypes


def sleep_on_purpose():
    ctypes.PyDLL(None).sleep(1)  # libc sleep through PyDLL: the GIL stays held, no CPU used


def test_sleeps_holding_the_gil():
    sleep_on_purpose()  # outside a fiber, as a driver's C call on the test's thread
    assert False
"""

DEADLOCK = """
import threading
import time


def test_deadlocks():
    # Every thread waits on a lock another holds (bounded, so the test ends): nothing runs,
    # but nothing holds the GIL either, so the watchdog keeps ticking.
    first, second = threading.Lock(), threading.Lock()

    def take(held, wanted):
        with held:
            time.sleep(0.1)
            wanted.acquire(timeout=1.5)

    threads = [
        threading.Thread(target=take, args=(first, second)),
        threading.Thread(target=take, args=(second, first)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert False
"""

FROZEN_RIGHT_AFTER_ARMING = """
import faulthandler
import os
import subprocess
import threading
import time

import _stalls
import pyfect as fx


class StopAfterArming:
    \"\"\"The watchdog's faulthandler, whose next arming is followed by a SIGSTOP of the
    process before the watchdog notes when the dump is due.\"\"\"

    def __init__(self):
        self.next = threading.Event()

    def __getattr__(self, name):
        return getattr(faulthandler, name)

    def dump_traceback_later(self, *args, **kwargs):
        faulthandler.dump_traceback_later(*args, **kwargs)
        if self.next.is_set():
            self.next.clear()
            script = f"kill -STOP {os.getpid()}; sleep 1; kill -CONT {os.getpid()}"
            subprocess.Popen(["sh", "-c", script])
            time.sleep(0.3)  # the stop lands here: armed, the due time not yet noted


def test_is_frozen_right_after_arming():
    shim = StopAfterArming()
    _stalls.faulthandler = shim
    shim.next.set()
    fx.run_blocking(fx.sleep("2 seconds"))
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
    """The host froze every thread, faulthandler's C watchdog too, so its dump is written
    late, once the process runs again. On Linux in a container, run this under an init
    process (``docker run --init``): as PID 1 the test process ignores a SIGSTOP sent from
    inside its own namespace, and never freezes."""
    out = _run(pytester, monkeypatch, FROZEN_PROCESS)
    assert "process stalled 1." in out
    assert ": host: process frozen, " in out  # the dump late, or not yet at resume
    assert "pyfect blocked" not in out


@pytest.mark.skipif(__import__("sys").platform == "win32", reason="libc sleep through ctypes")
@pytest.mark.skipif(
    not getattr(__import__("sys"), "_is_gil_enabled", lambda: True)(),
    reason="free-threaded: no GIL to hold, so the watchdog keeps running",
)
@pytest.mark.skipif(__import__("sys").platform == "win32", reason="SIGSTOP is POSIX")
def test_a_freeze_right_after_the_dump_is_armed_is_a_host_stall(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    """#135's CI: a freeze that lands between arming faulthandler's dump and noting when it
    is due made the due time fall after the freeze, so the dump the C watchdog wrote at
    resume read as on time, and the stall as in-process. The due time is noted first."""
    out = _run(pytester, monkeypatch, FROZEN_RIGHT_AFTER_ARMING)
    assert "process stalled 1." in out
    assert ": host: process frozen, " in out
    assert "on time" not in out


def test_a_c_call_sleeping_with_the_gil_held_is_named_pyfect_not_host(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Like a frozen host it uses no CPU and starves the watchdog thread, but faulthandler's
    C watchdog needs no GIL and writes its dump on time: the process was running."""
    out = _run(pytester, monkeypatch, GIL_HELD_SLEEP)
    assert "pyfect blocked in sleep_on_purpose (" in out
    assert ": host" not in out


def test_a_deadlock_is_no_stall(pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch) -> None:
    """Every thread blocked on a lock leaves the GIL free: the watchdog still ticks on time,
    so a deadlock is never taken for a frozen host."""
    out = _run(pytester, monkeypatch, DEADLOCK)
    assert "process stalled" not in out


def test_a_fiber_waiting_on_a_timer_is_no_stall(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    out = _run(pytester, monkeypatch, IDLE_WAIT)
    assert "process stalled" not in out


BUSY_HANG = """
def spin_on_purpose():
    total = 0
    for n in range(10**4):
        total += n
    return total


def test_spins():
    while True:  # never ends: the hang alarm fails it
        spin_on_purpose()
"""

WAITING_HANG = """
import threading


def wait_on_purpose():
    threading.Event().wait()  # nothing sets it


def test_waits():
    wait_on_purpose()
"""

FIBER_TIMEOUT = """
import pyfect as fx
import pyfect.testing as it


@it.live(timeout="1 second")
def test_times_out():
    yield from fx.never  # nothing wakes it
"""

BUSY_FIBER = """
import pyfect as fx


def spin_on_purpose():
    return sum(range(10**5))  # about 1 ms on one line, so every sample reads the same stack


@fx.fn
def steps():
    for _ in range(4000):  # about 2 s
        yield from fx.sync(spin_on_purpose)


def test_spins_in_steps():
    fx.run_blocking(steps())
    assert False
"""


def _hang(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch, source: str, alarm: int = 1
) -> str:
    monkeypatch.setenv("PYTHONPATH", str(Path(__file__).parent))
    pytester.makepyfile(source)
    pytester.makeini(f"[pytest]\nstall_threshold = 0.3\ntest_timeout = {alarm}\n")
    result = pytester.runpytest_subprocess(
        "-p", "_timeout", "-p", "_stalls", timeout=SUBPROCESS_TIMEOUT
    )
    result.assert_outcomes(failed=1)
    return result.stdout.str()


def test_a_hang_with_no_stall_says_where_the_test_was_running(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A test the hang alarm fails while it kept running Python (no stall) says so, and
    names the frame it was last in."""
    out = _hang(pytester, monkeypatch, BUSY_HANG)
    assert "test hung: still running after 1s" in out
    assert "no stall: the process kept running Python" in out
    assert "the test thread was last in spin_on_purpose (" in out


def test_a_hang_waiting_on_a_lock_says_where_the_test_waited(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    out = _hang(pytester, monkeypatch, WAITING_HANG)
    assert "no stall: the process kept running Python" in out
    assert "the test thread was waiting in wait (" in out
    assert "wait_on_purpose (" in out


def test_a_pyfect_test_timeout_with_no_stall_says_where_the_test_waited(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    out = _hang(pytester, monkeypatch, FIBER_TIMEOUT, alarm=10)  # pyfect's 1 s timeout first
    assert "TestTimeoutError" in out
    assert "no stall: the process kept running Python" in out
    assert "the test thread was waiting in " in out


def test_a_fiber_running_the_same_stack_on_the_cpu_is_busy_not_blocked(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Identical steps in a loop look like one step that never moves; with the CPU busy
    the stall is "busy", not "blocked"."""
    out = _run(pytester, monkeypatch, BUSY_FIBER)
    assert "pyfect busy " in out
    assert " in spin_on_purpose (" in out
    assert "pyfect blocked" not in out


def test_an_on_time_dump_with_no_busy_thread_and_no_cpu_is_unexplained() -> None:
    """Nothing in the process explains such a stall, so it is neither called in-process nor
    counted as a host freeze."""
    named = _no_busy_thread(1.1, 0.0, 0.0, on_time=True, dump=True)
    assert named.startswith("unexplained: ")


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
