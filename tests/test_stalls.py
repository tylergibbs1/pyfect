"""``tests/_stalls.py`` names what stalled a test: pyfect blocking, or the host.

Each case runs a small test file under the plugin in a subprocess, with a short
``stall_threshold``, and reads the "stall" section of its failure.
"""

import re
import sys
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


SLOW_RUNNER_AFTER_THE_FAILURE = """
import time

import _pytest.capture

# pytest's own work after the failure unwound the test, made slow enough to be sampled:
# compiled under capture.py's name, so its frame reads as the runner's.
_SOURCE = '''
def suspend_global_capture(self, in_=False):
    time.sleep(0.5)
    return _original(self, in_)
'''
_scope = {"time": time, "_original": _pytest.capture.CaptureManager.suspend_global_capture}
exec(compile(_SOURCE, _pytest.capture.__file__, "exec"), _scope)
_pytest.capture.CaptureManager.suspend_global_capture = _scope["suspend_global_capture"]
"""


def test_a_hang_names_the_test_not_the_runner_work_after_it(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    """#149's CI: the last sample before the phase ended was taken after the failure had
    unwound the test, in pytest's capture code, and was reported as where the test was."""
    pytester.makeconftest(SLOW_RUNNER_AFTER_THE_FAILURE)
    out = _hang(pytester, monkeypatch, BUSY_HANG)
    assert "the test thread was last in spin_on_purpose (" in out, out


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
    assert re.search(r" (in|near) spin_on_purpose \(", out), out
    assert "pyfect blocked" not in out


BUSY_BETWEEN_GIL_RELEASES = """
import signal
import time

import pyfect as fx


def spin_on_purpose():
    return sum(range(10**5))  # about 1 ms, holding the GIL


def step():
    spin_on_purpose()
    time.sleep(0.0002)  # releases the GIL, and no CPU: where a GIL-side sample always lands


@fx.fn
def steps():
    start = time.process_time()
    while time.process_time() - start < 2:  # 2 s of CPU, however fast the machine
        yield from fx.sync(step)


def test_spins_between_gil_releases():
    fx.run_blocking(steps())
    assert False


def test_after_it():
    # The stall and its test are over: no profiling timer or handler is left behind.
    assert signal.getitimer(signal.ITIMER_PROF) == (0.0, 0.0)
    assert signal.getsignal(signal.SIGPROF) is signal.SIG_DFL
"""

BUSY_UNTIL_SAMPLED = """
import signal
import time

import pyfect as fx


def spin_on_purpose(n):
    return sum(range(n))  # one C call: holds the GIL throughout


def step():
    spin_on_purpose(10**5)  # about 1 ms
    time.sleep(0.0002)  # room for the watchdog to take the GIL, so its ticks keep time


def sampling():
    return signal.getitimer(signal.ITIMER_PROF) != (0.0, 0.0)


@fx.fn
def steps():
    start = time.process_time()
    while not sampling() and time.process_time() - start < 2:
        yield from fx.sync(step)
    # About 0.1 s with no tick: the CPU samples go on, the stall ends before the next tick.
    yield from fx.sync(lambda: spin_on_purpose(10**7))


def test_busy_until_sampled():
    fx.run_blocking(steps())
"""

OWN_PROFILING_TIMER = """
import signal
import time

import pyfect as fx

fired = []


def spin_on_purpose():
    return sum(range(10**5))


def step():
    spin_on_purpose()
    time.sleep(0.0002)


@fx.fn
def steps():
    start = time.process_time()
    while time.process_time() - start < 2:  # 2 s of CPU, however fast the machine
        yield from fx.sync(step)


def test_profiles_itself():
    def on_prof(signum, frame):
        fired.append(signum)

    signal.signal(signal.SIGPROF, on_prof)
    signal.setitimer(signal.ITIMER_PROF, 0.05, 0.05)
    try:
        fx.run_blocking(steps())  # a busy stall, past the threshold
        assert signal.getitimer(signal.ITIMER_PROF)[1] == 0.05
        assert signal.getsignal(signal.SIGPROF) is on_prof
        assert fired  # its timer kept firing into its own handler
    finally:
        signal.setitimer(signal.ITIMER_PROF, 0, 0)
        signal.signal(signal.SIGPROF, signal.SIG_DFL)
"""


def _outcomes(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch, source: str, **outcomes: int
) -> str:
    monkeypatch.setenv("PYTHONPATH", str(Path(__file__).parent))
    pytester.makepyfile(source)
    pytester.makeini("[pytest]\nstall_threshold = 0.3\n")
    result = pytester.runpytest_subprocess("-p", "_stalls", timeout=SUBPROCESS_TIMEOUT)
    result.assert_outcomes(**outcomes)
    return result.stdout.str()


@pytest.mark.skipif(
    sys.platform != "linux", reason="exact CPU samples need Linux (macOS raises SIGPROF late)"
)
def test_a_busy_stall_is_named_where_its_cpu_goes_not_where_it_releases_the_gil(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A sample taken holding the GIL finds the busy thread where it released it: here
    every one would read ``time.sleep``'s line in ``step``, which uses no CPU. The CPU
    samples, taken only during the stall, find ``spin_on_purpose``; the next test sees no
    profiling timer or handler."""
    out = _outcomes(pytester, monkeypatch, BUSY_BETWEEN_GIL_RELEASES, failed=1, passed=1)
    assert "pyfect busy " in out
    assert " in spin_on_purpose (" in out, out
    assert "CPU samples" in out


@pytest.mark.skipif(sys.platform != "linux", reason="the CPU samples run only on Linux")
def test_a_busy_stall_ending_right_after_sampling_starts_is_named_from_its_samples(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The stall ends before the watchdog's next tick, so the only head written during it
    came before the first sample: it is named from the samples taken until it ended."""
    out = _outcomes(pytester, monkeypatch, BUSY_UNTIL_SAMPLED, passed=1)
    assert " in spin_on_purpose (" in out, out
    assert "CPU samples" in out, out
    assert "approximate" not in out, out


@pytest.mark.skipif(sys.platform != "linux", reason="the CPU samples run only on Linux")
def test_a_tests_own_profiling_timer_survives_a_busy_stall(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The watchdog never takes SIGPROF from a test using it: the stall is named
    approximately, and the test's timer and handler stay its own."""
    out = _outcomes(pytester, monkeypatch, OWN_PROFILING_TIMER, passed=1, warnings=1)
    assert "approximate" in out, out


def test_an_on_time_dump_with_no_busy_thread_and_no_cpu_is_unexplained() -> None:
    """Nothing in the process explains such a stall, so it is neither called in-process nor
    counted as a host freeze."""
    named = _no_busy_thread(1.1, 0.0, 0.0, on_time=True, dump=True)
    assert named.startswith("unexplained: ")


def _freeze_script(freeze: float) -> str:
    return f"""
import os
import subprocess

import pyfect as fx
import pyfect.testing as it


def freeze_soon():
    # What a starved host does to the process: no thread runs, and no CPU time passes.
    script = "sleep 0.2; kill -STOP {{pid}}; sleep {freeze}; kill -CONT {{pid}}"
    return subprocess.Popen(["sh", "-c", script.format(pid=os.getpid())])
"""


FROZEN_WITHIN_ITS_LIMIT = (
    _freeze_script(1.5)
    + """

@it.live(timeout="1 second")
def test_frozen_then_done():
    freezer = freeze_soon()
    yield from fx.sleep("1800 millis")  # 0.3 s of the test's own time, after the freeze
    freezer.wait(timeout=5)
"""
)

FROZEN_PAST_ITS_LIMIT = (
    _freeze_script(1.0)
    + """

@it.live(timeout="1 second")
def test_frozen_and_slow():
    freezer = freeze_soon()
    yield from fx.sleep("3 seconds")  # 2 s of the test's own time: past its limit
    freezer.wait(timeout=5)
"""
)

DEADLOCKED_FIBER = """
import pyfect as fx
import pyfect.testing as it


@it.live(timeout="1 second")
def test_deadlocked():
    yield from fx.never  # every fiber waiting: the watchdog keeps ticking
"""

GIL_HELD_IN_A_STEP = """
import ctypes

import pyfect as fx
import pyfect.testing as it


def sleep_on_purpose():
    ctypes.PyDLL(None).sleep(2)  # the GIL held 2 s, no CPU used: looks frozen, is not


@it.live(timeout="1 second")
def test_holds_the_gil():
    yield from fx.sync(sleep_on_purpose)  # the timeout passes during it
    yield from fx.never  # so it is due as soon as the step ends
"""


def _limited(pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch, source: str) -> str:
    monkeypatch.setenv("PYTHONPATH", str(Path(__file__).parent))
    pytester.makepyfile(source)
    pytester.makeini("[pytest]\nstall_threshold = 0.3\n")
    result = pytester.runpytest_subprocess("-p", "_stalls", timeout=SUBPROCESS_TIMEOUT)
    return result.stdout.str()


@pytest.mark.skipif(__import__("sys").platform == "win32", reason="SIGSTOP is POSIX")
def test_a_host_freeze_is_left_out_of_a_tests_timeout(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Frozen 1.5 s by the host, a test with 0.3 s of its own work stays within its 1 s
    limit. (On Linux in a container, run under ``docker run --init``: see
    ``test_a_frozen_process_is_named_a_host_stall``.)"""
    out = _limited(pytester, monkeypatch, FROZEN_WITHIN_ITS_LIMIT)
    assert "1 passed" in out, out


@pytest.mark.skipif(__import__("sys").platform == "win32", reason="SIGSTOP is POSIX")
def test_a_timeout_after_a_host_freeze_says_what_it_left_out(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    out = _limited(pytester, monkeypatch, FROZEN_PAST_ITS_LIMIT)
    assert "TestTimeoutError: test timed out after 1.0 s of running time (" in out
    # About 1 s: a freeze is counted as the watchdog's gap less one tick, so never more.
    assert re.search(r"host froze the process (0\.[89]|1\.[0-9]) s, not counted\)", out), out


def test_a_deadlock_times_out_on_time(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every fiber waiting is not the host freezing the process: nothing is left out."""
    out = _limited(pytester, monkeypatch, DEADLOCKED_FIBER)
    assert "TestTimeoutError: test timed out after 1.0s; it was interrupted" in out
    assert "not counted" not in out


@pytest.mark.skipif(__import__("sys").platform == "win32", reason="libc sleep through ctypes")
def test_a_c_call_holding_the_gil_times_out_on_time(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A GIL-held sleep starves the watchdog and uses no CPU, as a freeze does, but its
    faulthandler dump comes on time: pyfect's own time, so nothing is left out."""
    out = _limited(pytester, monkeypatch, GIL_HELD_IN_A_STEP)
    assert "TestTimeoutError: test timed out after 1.0s" in out
    assert "not counted" not in out


BLOCKS_PAST_ITS_LIMIT = """
import time

import pyfect as fx
import pyfect.testing as it


def block_on_purpose():
    time.sleep(1.5)  # a blocking call in a fiber step: the timer cannot fire during it


@it.live(timeout="1 second")
def test_blocks():
    yield from fx.sync(block_on_purpose)
"""

WITHIN_ITS_LIMIT = """
import pyfect as fx
import pyfect.testing as it


@it.live(timeout="1 second")
def test_waits():
    yield from fx.sleep("300 millis")
"""


def _blocking(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch, source: str, mode: str
) -> pytest.RunResult:
    monkeypatch.setenv("PYTHONPATH", str(Path(__file__).parent))
    pytester.makepyfile(source)
    pytester.makeini(f"[pytest]\nstall_threshold = 0.3\nblocked_past_limit = {mode}\n")
    return pytester.runpytest_subprocess("-p", "_stalls", timeout=SUBPROCESS_TIMEOUT)


def test_a_test_that_blocked_past_its_limit_fails(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A step that blocks past the timeout passes in ``pyfect.testing``, as in Effect: the
    timer cannot fire while the thread is blocked. Our suite fails it ("fibers never
    block"), naming the stall."""
    result = _blocking(pytester, monkeypatch, BLOCKS_PAST_ITS_LIMIT, "fail")
    result.assert_outcomes(failed=1)
    out = result.stdout.str()
    assert "finished, but blocked past its 1.0 s limit: ran 1." in out
    assert "pyfect blocked in block_on_purpose (" in out


def test_a_test_that_blocked_past_its_limit_warns_in_report_mode(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    result = _blocking(pytester, monkeypatch, BLOCKS_PAST_ITS_LIMIT, "warn")
    # The watchdog's own StallWarning for the block, then the limit's.
    result.assert_outcomes(passed=1, warnings=2)
    out = result.stdout.str()
    assert "StallWarning: process stalled 1." in out
    assert "BlockedPastLimitWarning: finished, but blocked past its 1.0 s limit" in out


def test_a_test_within_its_limit_passes(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    _blocking(pytester, monkeypatch, WITHIN_ITS_LIMIT, "fail").assert_outcomes(passed=1)


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
