"""``tests/_stalls.py`` names what stalled a test: pyfect blocking, or the host.

Each case runs a small test file under the plugin in a subprocess, with a short
``stall_threshold``, and reads the "stall" section of its failure.
"""

import inspect
import os
import re
import subprocess
import sys
import threading
from pathlib import Path

import pytest
from _stalls import (
    DumpedThread,
    Frame,
    _current_threads,  # pyright: ignore[reportPrivateUsage]
    _Dump,  # pyright: ignore[reportPrivateUsage]
    _not_frozen,  # pyright: ignore[reportPrivateUsage]
    _Timing,  # pyright: ignore[reportPrivateUsage]
)
from _subprocess import SUBPROCESS_TIMEOUT
from _thread_cpu_timer import AVAILABLE as _STACK_DUMPS

_NEEDS_STACK_DUMPS = pytest.mark.skipif(
    not _STACK_DUMPS,
    reason="the stall dump's per-thread timers (SIGEV_THREAD_ID) are Linux's: off it, no "
    "thread writes its stack during a stall, so nothing names a GIL-held call",
)

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

_SLEEP_HOLDING_THE_GIL = """
import ctypes
import os
import subprocess

_writers = []


def a_pipe_written_in(seconds):
    # read()'s arguments for a pipe written to in ``seconds``. A read through PyDLL holds the
    # GIL and uses no CPU, and the kernel restarts it after the stall dump's signal
    # (faulthandler's handlers are SA_RESTART); a sleep it would cut short, and back in
    # Python the watchdog would take the GIL.
    out, into = os.pipe()
    _writers.append(subprocess.Popen(["sh", "-c", f"sleep {seconds}; printf x"], stdout=into))
    os.close(into)
    return out, ctypes.create_string_buffer(1), 1
"""

GIL_HELD_SLEEP = (
    _SLEEP_HOLDING_THE_GIL
    + """

def sleep_on_purpose():
    ctypes.PyDLL(None).read(*a_pipe_written_in(1))  # the GIL stays held, no CPU used


def test_sleeps_holding_the_gil():
    sleep_on_purpose()  # outside a fiber, as a driver's C call on the test's thread
    assert False
"""
)

GIL_HELD_SLEEP_DUMPED_IN_THE_RUNNER = (
    _SLEEP_HOLDING_THE_GIL
    + """
import inspect

import _pytest._code.code
import _pytest.nodes
import _stalls
import pluggy._callers

take = _stalls._DumpTimer.take

# Where release 0.6.25's loop caught the test thread: pytest reading a failed test's source
# for its report, with no frame of the test or of pyfect left on the stack.
REPORTING = tuple(
    _stalls.Frame(module.__file__, line, func)
    for module, line, func in (
        (inspect, 1021, "getmodule"),
        (inspect, 1074, "findsource"),
        (_pytest._code.code, 926, "_getentrysource"),
        (_pytest._code.code, 1243, "repr_excinfo"),
        (_pytest.nodes, 477, "_repr_failure_py"),
        (pluggy._callers, 121, "_multicall"),
    )
)


def dumped_in_the_runner(self, *, stalled):
    \"\"\"The stalled tick's dump, on time, with every thread in pytest's report.\"\"\"
    dump = take(self, stalled=stalled)
    if not stalled or dump is None:
        return dump
    threads = [_stalls.DumpedThread(t.ident, t.current, REPORTING) for t in dump.threads]
    return _stalls._Dump(threads, dump.at, 0.0, _stalls._Timing.ON_TIME)


_stalls._DumpTimer.take = dumped_in_the_runner


def test_stalls_in_the_runner():
    ctypes.PyDLL(None).read(*a_pipe_written_in(1))  # the GIL held 1 s
    assert False
"""
)

GIL_HELD_SLEEP_DUMPED_LATE = (
    _SLEEP_HOLDING_THE_GIL
    + """
import threading

import _stalls

arm = _stalls._DumpTimer.arm
late = threading.Event()
armed_late = threading.Event()


def arm_late(timer):
    \"\"\"The watchdog's arming, once ``late`` is set noting each dump due 0.2 s before it fires:
    the dump then reads 0.2 s late, as a loaded host's signal delivery made it (CI, 3.14.0, load
    8.7 on 4 CPUs).\"\"\"
    arm(timer)
    if late.is_set():
        timer._current.due -= 0.2
        armed_late.set()


_stalls._DumpTimer.arm = arm_late


def sleep_on_purpose():
    ctypes.PyDLL(None).read(*a_pipe_written_in(1))  # the GIL stays held, no CPU used


def test_sleeps_holding_the_gil():
    late.set()
    assert armed_late.wait(timeout=2)
    sleep_on_purpose()  # whichever arming is current when the read starts, its dump reads late
    assert False
"""
)

GIL_HELD_SLEEP_JUDGED_SLOWLY = (
    _SLEEP_HOLDING_THE_GIL
    + """
import time

import _stalls

judge = _stalls.Watchdog._process_stall


def judge_slowly(watchdog, *args, **kwargs):
    \"\"\"The watchdog's judging of a stall, done 0.5 s late: what a loaded host made of its
    wait for a SIGCONT (1.2 s, 4 CPUs with 28 busy processes).\"\"\"
    stall = judge(watchdog, *args, **kwargs)
    time.sleep(0.5)
    return stall


_stalls.Watchdog._process_stall = judge_slowly


def sleep_on_purpose():
    ctypes.PyDLL(None).read(*a_pipe_written_in(1))  # the GIL stays held, no CPU used


def test_sleeps_holding_the_gil():
    sleep_on_purpose()
    assert False
"""
)

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
import os
import subprocess
import threading
import time

import _stalls
import pyfect as fx

arm = _stalls.StackDumps.arm
stop_next = threading.Event()


def stop_after_arming(dumps, delay, *, but=None):
    \"\"\"The watchdog's dump timers, whose next arming is followed by a SIGSTOP of the
    process before the watchdog notes it replaced the last.\"\"\"
    arm(dumps, delay, but=but)
    if stop_next.is_set():
        stop_next.clear()
        script = f"kill -STOP {os.getpid()}; sleep 1; kill -CONT {os.getpid()}"
        subprocess.Popen(["sh", "-c", script])
        time.sleep(0.3)  # the stop lands here: armed


_stalls.StackDumps.arm = stop_after_arming


def test_is_frozen_right_after_arming():
    stop_next.set()
    fx.run_blocking(fx.sleep("2 seconds"))
    assert False
"""

IDLE_WAIT = """
import pyfect as fx


def test_sleeps():
    fx.run_blocking(fx.sleep("800 millis"))
    assert False
"""


_IDS_FILE = "process-ids.txt"


def _ids() -> str:
    """This process's pid, parent, process group and session: whether a group with a stopped
    member could be orphaned (the kernel then sends it SIGHUP and SIGCONT) depends on them."""
    group = os.getpgid(0) if hasattr(os, "getpgid") else "-"
    session = os.getsid(0) if hasattr(os, "getsid") else "-"
    return f"pid {os.getpid()} ppid {os.getppid()} pgid {group} sid {session}"


def _run_inner(pytester: pytest.Pytester, *args: str) -> pytest.RunResult:
    """``runpytest_subprocess``, with the inner run writing its ids (``_ids``) as it starts:
    a run killed mid-test can't say them later."""
    pytester.makeconftest(
        f"import os\n\n\n{inspect.getsource(_ids)}\n\ndef pytest_configure(config):\n"
        f"    with open({_IDS_FILE!r}, 'w') as f:\n        f.write(_ids())\n"
    )
    return pytester.runpytest_subprocess(*args, timeout=SUBPROCESS_TIMEOUT)


def _described(result: pytest.RunResult, *, passed: bool = False) -> str:
    """The run's stdout, exit status and stderr, after checking its one test passed or failed
    as expected. A run killed mid-test (three times on CI, in tests that SIGSTOP it) leaves stdout
    cut off after the file name, with no summary: only the status (minus the signal's number)
    and stderr say what happened."""
    ids = Path(_IDS_FILE)  # pytester runs in its own directory
    inner = ids.read_text() if ids.exists() else "not written"
    out = (
        f"{result.stdout.str()}\n[exit {result.ret}; inner {inner}; outer {_ids()}; stderr]\n"
        f"{result.stderr.str()}"
    )
    assert result.ret == (pytest.ExitCode.OK if passed else pytest.ExitCode.TESTS_FAILED), out
    result.assert_outcomes(passed=int(passed), failed=int(not passed))
    return out


@pytest.mark.skipif(__import__("sys").platform == "win32", reason="SIGKILL is POSIX")
def test_a_run_killed_mid_test_says_how_it_ended(pytester: pytest.Pytester) -> None:
    pytester.makepyfile(
        "import os, signal\n\n\ndef test_killed():\n    os.kill(os.getpid(), signal.SIGKILL)\n"
    )
    result = _run_inner(pytester)
    with pytest.raises(
        AssertionError, match=r"\[exit -9; inner pid \d+ ppid \d+ pgid \d+ sid \d+;"
    ):
        _described(result)


def _run(pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch, source: str) -> str:
    monkeypatch.setenv("PYTHONPATH", str(Path(__file__).parent))
    pytester.makepyfile(source)
    pytester.makeini("[pytest]\nstall_threshold = 0.3\n")
    result = _run_inner(pytester, "-p", "_stalls")
    return _described(result)


def test_a_blocking_call_in_a_fiber_step_is_named(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    out = _run(pytester, monkeypatch, BLOCKING_FIBER)
    assert "stall" in out
    assert "pyfect blocked in wait_on_purpose (" in out
    assert "test_a_blocking_call_in_a_fiber_step_is_named.py:7)" in out


@_NEEDS_STACK_DUMPS
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
    """The host froze every thread, and the SIGCONT that resumed them says so. On Linux in a
    container, run this under an init
    process (``docker run --init``): as PID 1 the test process ignores a SIGSTOP sent from
    inside its own namespace, and never freezes."""
    out = _run(pytester, monkeypatch, FROZEN_PROCESS)
    assert "process stalled 1." in out
    assert ": host: process frozen, resumed by SIGCONT (" in out, out
    assert "pyfect blocked" not in out


@_NEEDS_STACK_DUMPS
@pytest.mark.skipif(__import__("sys").platform == "win32", reason="libc sleep through ctypes")
@pytest.mark.skipif(
    not getattr(__import__("sys"), "_is_gil_enabled", lambda: True)(),
    reason="free-threaded: no GIL to hold, so the watchdog keeps running",
)
@pytest.mark.skipif(__import__("sys").platform == "win32", reason="SIGSTOP is POSIX")
def test_a_freeze_right_after_the_dump_is_armed_is_a_host_stall(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    """#135's CI: a freeze that lands between arming the dump and noting when it is due made
    the due time fall after the freeze, so the dump written at resume read as on time, and
    the stall as in-process. The due time is noted first."""
    out = _run(pytester, monkeypatch, FROZEN_RIGHT_AFTER_ARMING)
    assert "process stalled 1." in out
    assert ": host: process frozen, " in out
    assert "on time" not in out


@_NEEDS_STACK_DUMPS
def test_a_stall_with_only_the_runner_on_the_stack_is_not_named_pyfect(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Release 0.6.25's loop: the process stalled while pytest built a failure's report, and
    the dump's busy thread, all pytest and standard library frames, read "pyfect blocked in
    getmodule (inspect.py)". The stall is the runner's."""
    out = _run(pytester, monkeypatch, GIL_HELD_SLEEP_DUMPED_IN_THE_RUNNER)
    assert re.search(r"process stalled 1\.\d s: the test runner busy in getmodule \(", out), out
    assert "pyfect blocked" not in out


@_NEEDS_STACK_DUMPS
def test_a_c_call_sleeping_with_the_gil_held_is_named_pyfect_not_host(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Like a frozen host it uses no CPU and starves the watchdog thread, but the stall dump
    needs no GIL (each thread writes its own stack from a signal) and comes on time: the
    process was running."""
    out = _run(pytester, monkeypatch, GIL_HELD_SLEEP)
    assert "pyfect blocked in sleep_on_purpose (" in out
    assert ": host" not in out


@_NEEDS_STACK_DUMPS
def test_a_c_call_holding_the_gil_dumped_late_is_named_pyfect_not_host(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A loaded host delivers the dump's signal late (0.1 s on CI), but the dump still came
    while the call held the GIL, a threshold before the watchdog could tick: the process was
    running, so the stall is the call's, as with a dump on time. The read is one stall (the
    GIL stays held, so the watchdog cannot tick in it): naming the call is its whole verdict,
    and other stalls a loaded host adds to the run may rightly read "unexplained"."""
    out = _run(pytester, monkeypatch, GIL_HELD_SLEEP_DUMPED_LATE)
    assert "pyfect blocked in sleep_on_purpose (" in out, out
    assert ": host" not in out


@pytest.mark.skipif(__import__("sys").platform == "win32", reason="libc read through ctypes")
def test_a_stall_judged_slowly_is_in_the_failure_it_happened_in(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The v0.6.24 release run: judging the stall outlasted the failure report's wait for it,
    and teardown disarmed the watchdog before it was recorded, so the failure had no stall
    section. The report waits for the stall's judgment, however long it takes."""
    out = _run(pytester, monkeypatch, GIL_HELD_SLEEP_JUDGED_SLOWLY)
    assert re.search(r"-+ stall -+\nprocess stalled 1\.\d s: ", out), out


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

WAITING_ON_A_WORKER = """
import threading
import time


def sleep_on_purpose():
    time.sleep(3)  # past the 1 s alarm: the work the test waits for is stuck


def test_waits_on_a_worker():
    done = threading.Event()
    parked = threading.Event()
    threading.Thread(target=sleep_on_purpose, name="pyfect-sqlite_0", daemon=True).start()
    threading.Thread(target=parked.wait, name="pyfect-parked", daemon=True).start()
    done.wait()  # what the worker would set when it finished
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
    result = _run_inner(pytester, "-p", "_timeout", "-p", "_stalls")
    return _described(result)


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


def test_a_hang_waiting_on_a_worker_names_the_working_pyfect_threads(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    """#153's CI: a test waited 5 s on the sqlite worker, and the report could not tell
    whether the worker was stuck or had finished with the wake lost. A waiting test thread
    now comes with every pyfect thread that was working at that sample, and where."""
    out = _hang(pytester, monkeypatch, WAITING_ON_A_WORKER)
    assert "the test thread was waiting in wait (" in out
    assert "pyfect-sqlite_0 was in sleep_on_purpose (" in out, out
    assert "pyfect-parked was in" not in out, out


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


STARVED_BUSY_FIBER = """
import os
import subprocess
import sys
import time

import pyfect as fx


def spin_on_purpose():
    return sum(range(10**5))


@fx.fn
def steps():
    end = time.monotonic() + 1.5
    while time.monotonic() < end:
        yield from fx.sync(spin_on_purpose)


def test_spins_in_steps_starved():
    cpu = min(os.sched_getaffinity(0))
    for task in os.listdir("/proc/self/task"):  # the watchdog's thread too
        os.sched_setaffinity(int(task), {cpu})
    # Spinners on the same CPU, inheriting the pin: the steps get a small share of it.
    spinners = [subprocess.Popen([sys.executable, "-c", "while True: pass"]) for _ in range(20)]
    try:
        time.sleep(0.5)
        fx.run_blocking(steps())
    finally:
        for spinner in spinners:
            spinner.kill()
            spinner.wait()
    assert False
"""


@pytest.mark.skipif(
    not Path("/proc/self/schedstat").exists(), reason="run-queue time is Linux's schedstat"
)
def test_a_busy_fiber_the_host_starves_of_cpu_is_busy_not_blocked(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A step that spins on a CPU it must share uses little CPU, as a blocked one does, but
    it waits in the run queue for the rest: still busy, not blocked."""
    out = _run(pytester, monkeypatch, STARVED_BUSY_FIBER)
    assert "pyfect busy " in out, out
    assert "pyfect blocked" not in out, out


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

_SAMPLED_BUSY_STEPS = """
import sys
import time

import _stalls
import pyfect as fx
import pytest

SAMPLED_CPU = 0.1
\"\"\"Seconds of the busy thread's own CPU spun while it is sampled: one sample per 10 ms of
it (``_stalls._PROFILE_INTERVAL``), however starved the host leaves the process.\"\"\"


def spin_on_purpose(n=10**5):
    return sum(range(n))  # one C call: holds the GIL throughout (10**5: about 1 ms)


def step():
    spin_on_purpose()
    time.sleep(0.0002)  # releases the GIL: with no forced switch, the only place a tick lands


@pytest.fixture
def sampler(request):
    \"\"\"The watchdog's CPU sampler, with the GIL switched only where a step releases it.
    Forced switches, which a starved host lets the watchdog ask for anywhere, would put its
    ticks at different lines of the same busy loop, cutting one stall into several, the first
    with a sample or none.\"\"\"
    interval = sys.getswitchinterval()
    sys.setswitchinterval(60)
    try:
        yield request.config.stash[_stalls._WATCHDOG]._cpu
    finally:
        sys.setswitchinterval(interval)


def busy_until_sampled(sampler):
    \"\"\"Busy steps until the watchdog names them a busy stall and samples the thread.\"\"\"
    while sampler.thread is None:
        yield from fx.sync(step)


def spun(cpu):
    \"\"\"Whether ``cpu`` seconds of this thread's CPU have passed (``time.thread_time``).\"\"\"
    end = time.thread_time() + cpu
    return lambda: time.thread_time() >= end
"""

BUSY_UNTIL_SAMPLED = (
    _SAMPLED_BUSY_STEPS
    + """

def spin_until_sampled():
    # No tick until it returns (the GIL stays held): the stall's only head written meanwhile
    # came before the first sample, and the samples go on.
    done = spun(SAMPLED_CPU)
    while not done():
        spin_on_purpose()


@fx.fn
def steps(sampler):
    yield from busy_until_sampled(sampler)
    yield from fx.sync(spin_until_sampled)  # the stall ends before the next tick


def test_busy_until_sampled(sampler):
    fx.run_blocking(steps(sampler))
"""
)

OWN_PROFILING_TIMER = (
    _SAMPLED_BUSY_STEPS
    + """
import signal

fired = []


@fx.fn
def steps(sampler):
    yield from busy_until_sampled(sampler)
    done = spun(SAMPLED_CPU)
    while not done():
        yield from fx.sync(step)


def test_profiles_itself(sampler):
    def on_prof(signum, frame):
        fired.append(signum)

    signal.signal(signal.SIGPROF, on_prof)
    signal.setitimer(signal.ITIMER_PROF, 0.05, 0.05)
    try:
        fx.run_blocking(steps(sampler))  # a busy stall, sampled
        assert signal.getitimer(signal.ITIMER_PROF)[1] == 0.05
        assert signal.getsignal(signal.SIGPROF) is on_prof
        assert fired  # its timer kept firing into its own handler
    finally:
        signal.setitimer(signal.ITIMER_PROF, 0, 0)
        signal.signal(signal.SIGPROF, signal.SIG_DFL)
"""
)


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
    """The watchdog's samples use their own timer and signal: a test's profiling timer and
    handler stay its own, and the stall is still named from CPU samples."""
    out = _outcomes(pytester, monkeypatch, OWN_PROFILING_TIMER, passed=1, warnings=1)
    assert " in spin_on_purpose (" in out, out
    assert "CPU samples" in out, out


SAMPLED_WHILE_THREADS_COME_AND_GO = """
import os
import threading
import time
import zlib

import _stalls

_stalls._PROFILE_INTERVAL = 0.001  # a sample every millisecond of CPU
stop = time.monotonic() + 1.5
data = os.urandom(1 << 18)


def without_the_gil():
    while time.monotonic() < stop:
        zlib.compress(data, 6)


def come_and_go():
    while time.monotonic() < stop:
        threads = [threading.Thread(target=int) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()


for target in (without_the_gil, come_and_go, come_and_go, come_and_go, come_and_go):
    threading.Thread(target=target, daemon=True).start()


def deep(n):
    return 0 if n == 0 else 1 + deep(n - 1)


samples = _stalls._CpuSamples()
samples.start(f"0x{threading.get_ident():016x}")
while time.monotonic() < stop:
    deep(100)
busiest = samples.busiest()
samples.close()
assert busiest is not None and busiest[0][0].func == "deep", busiest
"""


def _run_with_stalls(source: str) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "PYTHONPATH": os.pathsep.join([str(Path(__file__).parent), *sys.path])}
    return subprocess.run(
        [sys.executable, "-c", source],
        env=env,
        capture_output=True,
        text=True,
        timeout=SUBPROCESS_TIMEOUT,
        check=False,
    )


@pytest.mark.skipif(sys.platform != "linux", reason="the CPU samples run only on Linux")
def test_cpu_samples_survive_threads_that_come_and_go_and_run_without_the_gil() -> None:
    """A sample read every thread's frames from whichever thread the signal landed on, often
    one without the GIL, while the busy thread changed its frames and other threads came and
    went: CPython segfaulted (CI, Python 3.13, a worker lost with an empty dump). Each sample
    now reads only the sampled thread's own frames, there."""
    done = _run_with_stalls(SAMPLED_WHILE_THREADS_COME_AND_GO)
    assert done.returncode == 0, (done.returncode, done.stderr[-2000:])


LATE_SAMPLE_SIGNAL = """
import signal
import threading

import _stalls

samples = _stalls._CpuSamples()
samples.start(f"0x{threading.get_ident():016x}")
samples.stop()
signal.raise_signal(_stalls._SAMPLE_SIGNAL)  # one the timer raised just before it stopped
samples.close()
print("survived")
"""


@pytest.mark.skipif(sys.platform != "linux", reason="the CPU samples run only on Linux")
def test_a_sample_signal_after_sampling_stopped_does_nothing() -> None:
    """A signal the timer raised just before it stopped can arrive after the handler is put
    back. SIGPROF's default action ended the process (an xdist worker lost with no dump)."""
    done = _run_with_stalls(LATE_SAMPLE_SIGNAL)
    assert (done.returncode, done.stdout.strip()) == (0, "survived"), done.stderr[-2000:]


def test_an_on_time_dump_with_no_busy_thread_and_no_cpu_is_unexplained() -> None:
    """Nothing in the process explains such a stall, so it is neither called in-process nor
    counted as a host freeze."""
    dump = _Dump([], 0.0, 0.0, _Timing.ON_TIME)
    assert _not_frozen(1.1, 0.0, dump, dumps=True).startswith("unexplained: ")


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

FROZEN_WITH_NO_DUMP_IN_TIME = (
    _freeze_script(1.0)
    + """
import _stalls

# As on a loaded runner, where faulthandler's C thread wrote after the watchdog had judged:
# no dump is ever read, so only the freeze's own SIGCONT shows it.
_stalls._DumpTimer.take = lambda self, *, stalled: None


@it.live(timeout="1 second")
def test_frozen_with_no_dump():
    freezer = freeze_soon()
    yield from fx.sleep("3 seconds")  # 2 s of the test's own time: past its limit
    freezer.wait(timeout=5)
"""
)

LATE_DUMP_WITHOUT_A_FREEZE = (
    _SLEEP_HOLDING_THE_GIL
    + """
import time

import _stalls
import pyfect as fx
import pyfect.testing as it

take = _stalls._DumpTimer.take


def unwritten_when_stalled(self, *, stalled):
    \"\"\"As in a Linux container under load: faulthandler's thread had not written 1.8 s
    after its due time, with the process running a GIL-held sleep.\"\"\"
    dump = take(self, stalled=stalled)
    return _stalls._Dump([], time.time(), 1.8, _stalls._Timing.MISSED) if stalled else dump


_stalls._DumpTimer.take = unwritten_when_stalled


def sleep_on_purpose():
    ctypes.PyDLL(None).read(*a_pipe_written_in(2))  # the GIL held 2 s: looks frozen, is not


@it.live(timeout="1 second")
def test_holds_the_gil_with_a_late_dump():
    yield from fx.sync(sleep_on_purpose)  # the timeout passes during it
    yield from fx.never  # so it is due as soon as the step ends
"""
)

FROZEN_AFTER_THE_CLOCKS = """
import os
import subprocess
import threading
import time

import _stalls
import pyfect as fx
import pyfect.testing as it

_stalls._DumpTimer.take = lambda self, *, stalled: None  # only the SIGCONT shows the freeze
mark = _stalls._Steal.mark
freeze = threading.Event()


def freeze_after_the_clocks(steal):
    \"\"\"Where a tick that saw no stall marks the CPU steal, after reading its clocks, once
    asked: the host freezes the process, so the freeze is the next tick's stall.\"\"\"
    mark(steal)
    if freeze.is_set():
        freeze.clear()
        script = f"kill -STOP {os.getpid()}; sleep 1; kill -CONT {os.getpid()}"
        subprocess.Popen(["sh", "-c", script])
        time.sleep(0.3)  # the stop lands here
        time.sleep(0.05)  # from the resume: the SIGCONT's byte is written before this tick ends


_stalls._Steal.mark = freeze_after_the_clocks


@it.live(timeout="1 second")
def test_frozen_after_the_clocks():
    freeze.set()
    yield from fx.sleep("3 seconds")  # 2 s of the test's own time: past its limit
"""

DEADLOCKED_FIBER = """
import pyfect as fx
import pyfect.testing as it


@it.live(timeout="1 second")
def test_deadlocked():
    yield from fx.never  # every fiber waiting: the watchdog keeps ticking
"""

GIL_HELD_IN_A_STEP = (
    _SLEEP_HOLDING_THE_GIL
    + """
import pyfect as fx
import pyfect.testing as it


def sleep_on_purpose():
    ctypes.PyDLL(None).read(*a_pipe_written_in(2))  # the GIL held 2 s: looks frozen, is not


@it.live(timeout="1 second")
def test_holds_the_gil():
    yield from fx.sync(sleep_on_purpose)  # the timeout passes during it
    yield from fx.never  # so it is due as soon as the step ends
"""
)


STARVED_BEFORE_REARMING = (
    _SLEEP_HOLDING_THE_GIL
    + """
import threading

import _stalls
import pyfect as fx
import pyfect.testing as it

starve, parked, holding = threading.Event(), threading.Event(), threading.Event()
sample_fibers = _stalls.Watchdog._sample_fibers


def park_after_sampling(watchdog, now):
    \"\"\"The watchdog's sample of the fibers, after which, once asked, it waits for the test
    thread to take the GIL: starved after this tick's dump was read, before its re-arm.\"\"\"
    sample_fibers(watchdog, now)
    if starve.is_set():
        starve.clear()
        parked.set()
        holding.wait(timeout=5)


_stalls.Watchdog._sample_fibers = park_after_sampling


def sleep_on_purpose():
    starve.set()
    parked.wait(timeout=5)
    holding.set()
    ctypes.PyDLL(None).read(*a_pipe_written_in(2))  # the GIL held 2 s: the watchdog starved


@it.live(timeout="1 second")
def test_starves_the_watchdog():
    yield from fx.sync(sleep_on_purpose)
    yield from fx.never
"""
)

FROZEN_BEFORE_REARMING = """
import os
import subprocess
import threading
import time

import _stalls
import pyfect as fx
import pyfect.testing as it

sample_fibers = _stalls.Watchdog._sample_fibers
freeze = threading.Event()


def freeze_after_sampling(watchdog, now):
    \"\"\"The watchdog's sample of the fibers, after which, once, the host freezes the process:
    where ``STARVED_BEFORE_REARMING`` starves it.\"\"\"
    sample_fibers(watchdog, now)
    if freeze.is_set():
        freeze.clear()
        script = f"kill -STOP {os.getpid()}; sleep 1; kill -CONT {os.getpid()}"
        subprocess.Popen(["sh", "-c", script])
        time.sleep(0.3)  # the stop lands here
        time.sleep(0.05)  # from the resume: the C watchdog writes before its timer is re-armed


_stalls.Watchdog._sample_fibers = freeze_after_sampling


@it.live(timeout="1 second")
def test_frozen_before_rearming():
    freeze.set()
    yield from fx.sleep("3 seconds")  # 2 s of the test's own time: past its limit
"""


FROZEN_IN_A_COLLECTION = """
import ctypes
import gc
import os
import subprocess

import pyfect as fx
import pyfect.testing as it

freeze = False
freezers = []


def freeze_in_the_collection(phase, info):
    \"\"\"Once, the host freezes the process inside a collection, after the watchdog's
    callback noted its start. The GIL stays held throughout, as in the collector's C code, so
    the collection ends (its callbacks run) before the watchdog's first tick after it.\"\"\"
    global freeze
    if phase == "start" and freeze:
        freeze = False
        out, into = os.pipe()
        pid = os.getpid()
        script = f"kill -STOP {pid}; sleep 1; kill -CONT {pid}; printf x"
        freezers.append(subprocess.Popen(["sh", "-c", script], stdout=into))
        os.close(into)
        ctypes.PyDLL(None).read(out, ctypes.create_string_buffer(1), 1)  # once resumed


gc.callbacks.append(freeze_in_the_collection)


@it.live(timeout="1 second")
def test_frozen_in_a_collection():
    global freeze
    freeze = True
    gc.collect(0)
    yield from fx.sleep("3 seconds")  # 2 s of the test's own time: past its limit
"""

COLLECTION_HOLDING_THE_GIL = (
    _SLEEP_HOLDING_THE_GIL
    + """
import gc

import pyfect as fx
import pyfect.testing as it

hold = False


def hold_the_gil_in_the_collection(phase, info):
    # As a long collection does: the GIL held 1 s, inside it, with no freeze.
    global hold
    if phase == "start" and hold:
        hold = False
        ctypes.PyDLL(None).read(*a_pipe_written_in(1))


gc.callbacks.append(hold_the_gil_in_the_collection)


@it.live(timeout="1 second")
def test_collects_for_long():
    global hold
    hold = True
    gc.collect(0)
    yield from fx.never
"""
)


def _limited(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch, source: str, *, passed: bool = False
) -> str:
    monkeypatch.setenv("PYTHONPATH", str(Path(__file__).parent))
    pytester.makepyfile(source)
    pytester.makeini("[pytest]\nstall_threshold = 0.3\n")
    result = _run_inner(pytester, "-p", "_stalls")
    return _described(result, passed=passed)


@pytest.mark.skipif(__import__("sys").platform == "win32", reason="SIGSTOP is POSIX")
def test_a_host_freeze_is_left_out_of_a_tests_timeout(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Frozen 1.5 s by the host, a test with 0.3 s of its own work stays within its 1 s
    limit. (On Linux in a container, run under ``docker run --init``: see
    ``test_a_frozen_process_is_named_a_host_stall``.)"""
    _limited(pytester, monkeypatch, FROZEN_WITHIN_ITS_LIMIT, passed=True)


@pytest.mark.skipif(__import__("sys").platform == "win32", reason="SIGSTOP is POSIX")
def test_a_timeout_after_a_host_freeze_says_what_it_left_out(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    out = _limited(pytester, monkeypatch, FROZEN_PAST_ITS_LIMIT)
    assert "TestTimeoutError: test timed out after 1.0 s of running time (" in out, out
    # About 1 s: a freeze is counted as the watchdog's gap less one tick, so never more.
    assert re.search(r"host froze the process (0\.[89]|1\.[0-9]) s, not counted\)", out), out


@pytest.mark.skipif(__import__("sys").platform == "win32", reason="SIGSTOP is POSIX")
def test_a_freeze_whose_dump_is_not_in_time_is_left_out(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    """CI on a loaded runner (load 5.00): faulthandler's dump came after the watchdog judged
    the stall, which then read "unexplained: no dump came due" and counted the 1 s freeze.
    The SIGCONT that ended it proves the freeze without the dump."""
    out = _limited(pytester, monkeypatch, FROZEN_WITH_NO_DUMP_IN_TIME)
    assert ": host: process frozen, resumed by SIGCONT (" in out, out
    assert "TestTimeoutError: test timed out after 1.0 s of running time (" in out, out
    assert re.search(r"host froze the process (0\.[89]|1\.[0-9]) s, not counted\)", out), out


@pytest.mark.skipif(__import__("sys").platform == "win32", reason="SIGSTOP is POSIX")
def test_a_sigcont_read_at_a_tick_with_no_stall_proves_the_next_ticks(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Frozen just after a tick read its clocks, the watchdog resumed in a tick that saw no
    stall, which dropped the SIGCONT as in no stall; the next tick's stall then had none."""
    out = _limited(pytester, monkeypatch, FROZEN_AFTER_THE_CLOCKS)
    assert ": host: process frozen, resumed by SIGCONT (" in out, out
    assert "TestTimeoutError: test timed out after 1.0 s of running time (" in out, out


def test_a_deadlock_times_out_on_time(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every fiber waiting is not the host freezing the process: nothing is left out."""
    out = _limited(pytester, monkeypatch, DEADLOCKED_FIBER)
    assert "TestTimeoutError: test timed out after 1.0s; it was interrupted" in out, out
    assert "not counted" not in out, out


@pytest.mark.skipif(__import__("sys").platform == "win32", reason="libc sleep through ctypes")
def test_a_c_call_holding_the_gil_times_out_on_time(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A GIL-held sleep starves the watchdog and uses no CPU, as a freeze does, but its
    faulthandler dump comes on time: pyfect's own time, so nothing is left out."""
    out = _limited(pytester, monkeypatch, GIL_HELD_IN_A_STEP)
    assert "TestTimeoutError: test timed out after 1.0s" in out, out
    assert "not counted" not in out, out


@_NEEDS_STACK_DUMPS
@pytest.mark.skipif(__import__("sys").platform == "win32", reason="libc sleep through ctypes")
@pytest.mark.skipif(
    not getattr(__import__("sys"), "_is_gil_enabled", lambda: True)(),
    reason="free-threaded: no GIL to hold, so the watchdog keeps running",
)
def test_a_watchdog_starved_before_it_rearms_counts_the_time(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    """#263's CI: starved by a GIL-held call after reading one tick's dump and before
    re-arming, the watchdog judged the dump the old arming wrote on time against the new
    arming's due: "the dump -2.1 s late", a host freeze, and 1 s left out of the timeout."""
    out = _limited(pytester, monkeypatch, STARVED_BEFORE_REARMING)
    assert "TestTimeoutError: test timed out after 1.0s" in out, out
    assert "pyfect blocked in sleep_on_purpose (" in out, out
    assert ": host" not in out, out
    assert "not counted" not in out, out


@_NEEDS_STACK_DUMPS
@pytest.mark.skipif(__import__("sys").platform == "win32", reason="libc sleep through ctypes")
@pytest.mark.skipif(
    not getattr(__import__("sys"), "_is_gil_enabled", lambda: True)(),
    reason="free-threaded: no GIL to hold, so the watchdog keeps running",
)
def test_a_late_dump_with_no_sigcont_counts_the_time(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Under load in a Linux container, faulthandler's dump was still unwritten 1.8 s past
    due during a GIL-held sleep, with no freeze: "host: process frozen, the dump 1.8 s late,
    unwritten", and 1 s left out of test_a_c_call_holding_the_gil_times_out_on_time's
    timeout. A late dump proves no freeze; only a SIGCONT does."""
    out = _limited(pytester, monkeypatch, LATE_DUMP_WITHOUT_A_FREEZE)
    assert "TestTimeoutError: test timed out after 1.0s" in out, out
    assert "unexplained: the dump 1.8 s late, unwritten, but no SIGCONT, so " in out, out
    assert ": host" not in out, out
    assert "not counted" not in out, out


@pytest.mark.skipif(__import__("sys").platform == "win32", reason="SIGSTOP is POSIX")
def test_a_freeze_before_the_watchdog_rearms_is_left_out(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Where ``test_a_watchdog_starved_before_it_rearms_counts_the_time`` starves the
    watchdog, a SIGSTOP freezes it: the SIGCONT that ends the freeze leaves it out."""
    out = _limited(pytester, monkeypatch, FROZEN_BEFORE_REARMING)
    assert ": host: process frozen, resumed by SIGCONT (" in out, out
    assert "TestTimeoutError: test timed out after 1.0 s of running time (" in out, out
    assert re.search(r"host froze the process (0\.[89]|1\.[0-9]) s, not counted\)", out), out


@pytest.mark.skipif(__import__("sys").platform == "win32", reason="SIGSTOP is POSIX")
def test_a_freeze_inside_a_collection_is_left_out(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Release 0.6.20's CI: SIGSTOPped while a collection ran, the process "stalled 1.1 s:
    pyfect blocked in garbage collection (generation 0, 1.0 s)", and the 1 s freeze counted
    in the timeout. The collection's wall time held the freeze; the SIGCONT proves it."""
    out = _limited(pytester, monkeypatch, FROZEN_IN_A_COLLECTION)
    assert ": host: process frozen, resumed by SIGCONT (" in out, out
    assert "garbage collection" not in out, out
    assert "TestTimeoutError: test timed out after 1.0 s of running time (" in out, out
    assert re.search(r"host froze the process (0\.[89]|1\.[0-9]) s, not counted\)", out), out


@pytest.mark.skipif(__import__("sys").platform == "win32", reason="libc read through ctypes")
def test_a_long_collection_is_named_and_counted(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A collection that holds the GIL 1 s with no freeze is pyfect's own time."""
    out = _limited(pytester, monkeypatch, COLLECTION_HOLDING_THE_GIL)
    assert ": pyfect blocked in garbage collection (generation 0, " in out, out
    assert "TestTimeoutError: test timed out after 1.0s" in out, out
    assert "not counted" not in out, out


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


TWO_STALLS = """
import time

import pyfect as fx


def short_block():
    time.sleep(0.6)


def long_block():
    time.sleep(1.5)


def test_blocks_twice():
    fx.run_blocking(fx.sync(short_block))
    fx.run_blocking(fx.sync(long_block))
"""


def test_a_passing_test_that_stalled_is_warned_about_its_longest_stall(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Under load one busy loop can be seen as several stalls, the first a short piece: the
    warning names the longest, as the blocked-past-limit failure does."""
    monkeypatch.setenv("PYTHONPATH", str(Path(__file__).parent))
    pytester.makepyfile(TWO_STALLS)
    pytester.makeini("[pytest]\nstall_threshold = 0.3\n")
    out = _described(_run_inner(pytester, "-p", "_stalls"), passed=True)
    warned = [line for line in out.splitlines() if "StallWarning:" in line]
    assert len(warned) == 1, out
    assert "pyfect blocked in long_block (" in warned[0], out


def test_a_frame_in_a_wait_is_idle() -> None:
    assert Frame("/usr/lib/python3.13/threading.py", 359, "wait").idle
    assert not Frame("/w/app.py", 9, "spin").idle


def test_the_current_threads_are_read_innermost_first() -> None:
    def here() -> list[DumpedThread]:
        return _current_threads()

    mine = [t for t in here() if t.current]
    assert len(mine) == 1, mine
    assert [f.func for f in mine[0].frames[:2]] == ["_current_threads", "here"]
    assert int(mine[0].ident, 16) == threading.get_ident()


def test_the_suite_loads_the_stall_plugin(pytestconfig: pytest.Config) -> None:
    assert pytestconfig.pluginmanager.has_plugin("_stalls")
