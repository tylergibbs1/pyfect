"""The tests/ plugin that names timers a test file's tests leave on the background scheduler."""

from pathlib import Path

import pytest
from _subprocess import SUBPROCESS_TIMEOUT

LEAVES_A_SLEEPING_FIBER = """
import pyfect as fx


def reconnect_later():
    return fx.sleep("1 hour")


def test_leaves_a_sleeping_fiber():
    fx.run_blocking(reconnect_later().fork_daemon().as_void())


def test_after_it_in_the_file():
    pass
"""

LEAVES_A_FIBER_THAT_ENDS_SOON = """
import pyfect as fx


def test_leaves_a_fiber_that_ends_soon():
    fx.run_blocking(fx.sleep("50 millis").fork_daemon().as_void())
"""

INTERRUPTS_ITS_FIBER_WITHIN_THE_FILE = """
import pyfect as fx

fibers = []


@fx.fn
def sleeper():
    fiber = yield from fx.sleep("1 hour").fork_daemon()
    yield from fx.yield_now()  # it sleeps before the run returns
    return fiber


def test_leaves_a_sleeping_fiber():
    fibers.append(fx.run_blocking(sleeper()))


def test_interrupts_it():
    fx.run_blocking(fx.Fiber.interrupt_all(fibers))
"""

BLOCKS_THE_BACKGROUND_THREAD = """
import threading

from pyfect.scheduler import BACKGROUND

stop = threading.Event()
started = threading.Event()


def block():
    started.set()
    stop.wait()


def test_blocks_the_background_thread():
    BACKGROUND.schedule(block)
    assert started.wait(5)
    BACKGROUND.schedule(lambda: None)  # queued behind it
    BACKGROUND.schedule(lambda: None)
"""

UNBLOCKS_IT = """
from test_a import stop


def test_in_the_next_file():
    stop.set()
"""


def _run(pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch, ini: str, **files: str):
    monkeypatch.setenv("PYTHONPATH", str(Path(__file__).parent))
    pytester.makeini(f"[pytest]\n{ini}\n")
    pytester.makepyfile(**files)
    return pytester.runpytest_subprocess("-p", "_leaked_fibers", timeout=SUBPROCESS_TIMEOUT)


def _warnings(pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch, **files: str) -> str:
    """The run's warnings summary, with leaks only warned about; every test in ``files``
    passes."""
    result = _run(pytester, monkeypatch, "leaked_fibers = warn", **files)
    result.assert_outcomes(passed=sum(source.count("def test_") for source in files.values()))
    out = result.stdout.str()
    return " ".join(out.split("warnings summary")[1].split()) if "warnings summary" in out else ""


def test_a_fiber_left_sleeping_past_its_file_is_named_with_the_test(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    summary = _warnings(pytester, monkeypatch, test_a=LEAVES_A_SLEEPING_FIBER)
    assert (
        "LeakedFiberWarning: test_a.py::test_leaves_a_sleeping_fiber left 1 timer(s) pending "
        "on the background scheduler past its file, the last due in 3600.0s"
    ) in summary, summary


def test_a_fiber_left_sleeping_past_its_file_fails_the_file(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Enforced by default: the file's last test errors in its teardown; the tests passed."""
    result = _run(pytester, monkeypatch, "", test_a=LEAVES_A_SLEEPING_FIBER)
    result.assert_outcomes(passed=2, errors=1)
    out = " ".join(result.stdout.str().split())
    assert "ERROR at teardown of test_after_it_in_the_file" in out, out
    assert "test_a.py::test_leaves_a_sleeping_fiber left 1 timer(s)" in out, out


def test_a_timer_due_right_after_the_file_is_not_named(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert not _warnings(pytester, monkeypatch, test_a=LEAVES_A_FIBER_THAT_ENDS_SOON)


def test_a_fiber_interrupted_within_its_file_is_not_named(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert not _warnings(pytester, monkeypatch, test_a=INTERRUPTS_ITS_FIBER_WITHIN_THE_FILE)


def test_a_background_thread_that_does_not_drain_is_named_instead_of_its_timers(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Its queued tasks may still set timers: a read now could miss them."""
    summary = _warnings(
        pytester, monkeypatch, test_a=BLOCKS_THE_BACKGROUND_THREAD, test_z=UNBLOCKS_IT
    )
    assert (
        "LeakedFiberWarning: test_a.py::test_blocks_the_background_thread: at its teardown "
        "the background scheduler did not drain within 0.5 s: a task still running, 2 more ready"
    ) in summary, summary
