"""The tests/ plugin that names threads a test file's tests leave running past the file."""

from pathlib import Path

import pytest
from _subprocess import SUBPROCESS_TIMEOUT

STOP = """
import threading

stop = threading.Event()
"""

LEAVES_A_THREAD = """
import threading

from stop import stop


def parse_forever():
    stop.wait()


def test_leaves_a_thread():
    threading.Thread(target=parse_forever, name="left-behind", daemon=True).start()


def test_after_it_in_the_file():
    pass
"""

STOPS_IT = """
from stop import stop


def test_in_the_next_file():
    stop.set()
"""

SHARES_A_THREAD_WITHIN_ITS_FILE = """
import threading

stop = threading.Event()


def test_starts_a_shared_thread():
    threading.Thread(target=stop.wait, name="shared", daemon=True).start()


def test_stops_it():
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
import pyfect as fx

from stop import stop


def test_abandons_a_blocking_call():
    fx.run_blocking_exit(fx.blocking(stop.wait).timeout("10 millis"))
"""

IDLE_LOOP_EXECUTOR = """
import asyncio

from pyfect.socket._loop import get_loop


def test_resolves_on_the_shared_loop():
    async def lookup():
        return await asyncio.get_running_loop().run_in_executor(None, lambda: 1)

    assert asyncio.run_coroutine_threadsafe(lookup(), get_loop()).result(5) == 1
"""

PROCESS_WIDE_PEER = """
import threading

from _threads import process_wide
from stop import stop


def test_starts_a_process_wide_peer():
    threading.Thread(target=stop.wait, name=process_wide("peer"), daemon=True).start()
"""


def _warnings(pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch, **files: str) -> str:
    """The run's warnings summary; every test in ``files`` passes. A file named ``stop``
    (the shared event) is added, and ``test_z`` stops it after the others have run."""
    monkeypatch.setenv("PYTHONPATH", str(Path(__file__).parent))
    pytester.makepyfile(stop=STOP, **files, test_z=STOPS_IT)
    pytester.syspathinsert()
    result = pytester.runpytest_subprocess("-p", "_leaked_threads", timeout=SUBPROCESS_TIMEOUT)
    result.assert_outcomes(passed=sum(source.count("def test_") for source in files.values()) + 1)
    out = result.stdout.str()
    return out.split("warnings summary")[1] if "warnings summary" in out else ""


def test_a_thread_left_running_past_its_file_is_named_with_the_test_and_its_stack(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    summary = _warnings(pytester, monkeypatch, test_a=LEAVES_A_THREAD)
    assert (
        "LeakedThreadWarning: test_a.py::test_leaves_a_thread left thread 'left-behind' "
        "running past its file"
    ) in " ".join(summary.split()), summary
    assert "in parse_forever" in summary, summary
    assert "test_z.py" not in summary, summary


def test_a_thread_shared_by_the_tests_of_one_file_is_not_named(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert not _warnings(pytester, monkeypatch, test_a=SHARES_A_THREAD_WITHIN_ITS_FILE)


def test_a_test_that_joins_its_threads_leaves_none(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert not _warnings(pytester, monkeypatch, test_a=JOINS_ITS_THREAD)


def test_the_runtimes_own_threads_parked_idle_are_not_named(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert not _warnings(pytester, monkeypatch, test_a=IDLE_RUNTIME_THREADS)


def test_a_blocking_pool_worker_still_running_an_abandoned_call_is_named(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    summary = _warnings(pytester, monkeypatch, test_a=ABANDONS_A_BLOCKING_CALL)
    assert "test_a.py::test_abandons_a_blocking_call left thread 'pyfect-blocking-" in summary, (
        summary
    )


def test_a_process_wide_peer_is_not_named(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert not _warnings(pytester, monkeypatch, test_a=PROCESS_WIDE_PEER)


def test_a_pyfect_loops_idle_executor_worker_is_not_named(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert not _warnings(pytester, monkeypatch, test_a=IDLE_LOOP_EXECUTOR)
