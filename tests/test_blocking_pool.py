"""``fx.blocking``'s threads: daemon threads that exit when idle, so a process
whose blocking work was abandoned (interrupted) still exits at once. Effect has
no thread pool (Node's work runs on libuv's); a stuck ``ThreadPoolExecutor``
worker made interpreter shutdown wait for ever (graft #10)."""

import subprocess
import sys
import textwrap
import threading
import time

import pyfect as fx
from pyfect import duration
from pyfect._blocking_pool import BlockingPool

_ABANDONS_STUCK_WORK = textwrap.dedent(
    """
    import threading
    import pyfect as fx

    stuck = threading.Event()
    work = fx.blocking(stuck.wait).timeout("50 millis")
    print(type(fx.run_blocking(work.exit())).__name__)
    """
)


def test_a_process_exits_promptly_with_blocking_work_abandoned() -> None:
    started = time.monotonic()
    done = subprocess.run(
        [sys.executable, "-c", _ABANDONS_STUCK_WORK],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert done.returncode == 0, done.stderr
    assert done.stdout.strip() == "Failure"
    assert time.monotonic() - started < 15


def test_blocking_threads_are_daemons() -> None:
    def daemon() -> bool:
        return threading.current_thread().daemon

    assert fx.run_blocking(fx.blocking(daemon))


def test_idle_threads_exit() -> None:
    pool = BlockingPool(max_workers=4, idle=duration.seconds(0.05), name="test-idle")
    futures = [pool.submit(lambda: time.sleep(0.01)) for _ in range(4)]
    for future in futures:
        future.result(timeout=5)
    deadline = time.monotonic() + 5
    while pool.threads and time.monotonic() < deadline:
        time.sleep(0.01)
    assert pool.threads == 0


def test_work_beyond_the_idle_threads_starts_a_thread_each() -> None:
    pool = BlockingPool(max_workers=4, idle=duration.seconds(5), name="test-grow")
    gate = threading.Barrier(4, timeout=5)
    futures = [pool.submit(gate.wait) for _ in range(4)]
    assert sorted(f.result(timeout=5) for f in futures) == [0, 1, 2, 3]


def test_a_raise_completes_the_future_with_it() -> None:
    pool = BlockingPool(max_workers=1, idle=duration.seconds(5), name="test-raise")

    def boom() -> None:
        raise KeyError("x")

    assert isinstance(pool.submit(boom).exception(timeout=5), KeyError)
