"""The tests/ plugin that names threads a test leaves running after its teardown."""

from pathlib import Path

import pytest
from _subprocess import SUBPROCESS_TIMEOUT

LEAVES_A_THREAD = """
import threading

stop = threading.Event()


def parse_forever():
    stop.wait()


def test_leaves_a_thread():
    threading.Thread(target=parse_forever, name="left-behind", daemon=True).start()


def test_after_it():
    stop.set()
"""

JOINS_ITS_THREAD = """
import threading


def test_joins_its_thread():
    thread = threading.Thread(target=lambda: None, name="joined")
    thread.start()
    thread.join()
"""

IDLE_RUNTIME_THREADS = """
import pyfect as fx


def test_uses_the_runtime():
    fx.run_blocking(fx.sleep("1 millis"))
    assert fx.run_blocking(fx.blocking(lambda: 1)) == 1
"""

ABANDONS_A_BLOCKING_CALL = """
import threading

import pyfect as fx

stop = threading.Event()


def test_abandons_a_blocking_call():
    fx.run_blocking_exit(fx.blocking(stop.wait).timeout("10 millis"))


def test_after_it():
    stop.set()
"""


def _warnings(pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch, source: str) -> str:
    """The run's warnings summary; every test in ``source`` passes."""
    monkeypatch.setenv("PYTHONPATH", str(Path(__file__).parent))
    pytester.makepyfile(source)
    result = pytester.runpytest_subprocess("-p", "_leaked_threads", timeout=SUBPROCESS_TIMEOUT)
    result.assert_outcomes(passed=source.count("def test_"))
    out = result.stdout.str()
    return out.split("warnings summary")[1] if "warnings summary" in out else ""


def test_a_thread_left_running_after_a_test_is_named_with_its_stack(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    summary = _warnings(pytester, monkeypatch, LEAVES_A_THREAD)
    assert "::test_leaves_a_thread\n" in summary, summary
    assert "LeakedThreadWarning: left thread 'left-behind' running" in summary, summary
    assert "in parse_forever" in summary, summary
    assert "::test_after_it" not in summary, summary


def test_a_test_that_joins_its_threads_leaves_none(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert not _warnings(pytester, monkeypatch, JOINS_ITS_THREAD)


def test_the_runtimes_own_threads_parked_idle_are_not_named(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert not _warnings(pytester, monkeypatch, IDLE_RUNTIME_THREADS)


def test_a_blocking_pool_worker_still_running_an_abandoned_call_is_named(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    summary = _warnings(pytester, monkeypatch, ABANDONS_A_BLOCKING_CALL)
    assert "::test_abandons_a_blocking_call\n" in summary, summary
    assert "LeakedThreadWarning: left thread 'pyfect-blocking-" in summary, summary
    assert "::test_after_it" not in summary, summary
