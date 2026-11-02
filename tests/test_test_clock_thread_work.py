"""TestClock.adjust waits for thread-backed work a woken fiber starts.

After a wake-up the clock waits until the woken fiber suspends. A fiber
waiting on a thread (the SQLite worker, ``fx.blocking``, the HTTP client's
loop) is not done: the thread will resume it. So the clock counts that work
too, as it counts a forked fiber, and the fiber's next ``sleep`` starts on
time. Waits for outside events (a socket read, a child's exit) are not
counted: they may never come (DOGFOOD beacon #9)."""

import time
import warnings
from collections.abc import Callable, Generator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pyfect as fx
from pyfect import testing
from pyfect.sql import sqlite
from pyfect.sql.client import SqlClient


@contextmanager
def _no_busy_warning() -> Generator[None]:
    with warnings.catch_warnings():
        warnings.simplefilter("error", testing.BusyFiberWarning)
        yield


def _iterations(
    step: Callable[[], fx.Effect[Any]], wrap: Callable[[fx.Effect[Any]], fx.Effect[Any]]
):
    """A loop of ``step`` then ``sleep(10)``, run for four ``adjust(10)``s;
    how many times ``step`` ran."""

    @fx.gen
    def program():
        count = yield from fx.Ref.make(0)

        @fx.gen
        def once():
            yield from wrap(step())
            yield from count.update(lambda n: n + 1)
            yield from fx.sleep(10)

        fiber = yield from once.forever().fork()
        for _ in range(4):
            yield from testing.adjust(10)
        seen = yield from count.get()
        yield from fiber.interrupt()
        return seen

    return program


def test_a_loop_of_blocking_work_and_sleep_runs_once_per_adjust():
    work = _iterations(lambda: fx.blocking(lambda: time.sleep(0.02)), lambda eff: eff)
    with _no_busy_warning():
        assert testing.run_test(work) == 5


def test_a_loop_of_sqlite_writes_and_sleep_runs_once_per_adjust(tmp_path: Path):
    @fx.gen
    def program():
        sql = yield from SqlClient()
        yield from sql.unsafe("CREATE TABLE checks (at INTEGER)")
        write = sql.unsafe("INSERT INTO checks (at) VALUES (1)").or_die()
        seen = yield from _iterations(lambda: write, lambda eff: eff)
        rows = yield from sql.unsafe("SELECT count(*) AS n FROM checks")
        return seen, rows[0]["n"]

    client = sqlite.layer(sqlite.SqliteClientConfig(filename=str(tmp_path / "beacon.db")))
    with _no_busy_warning():
        assert testing.run_test(program.pipe(fx.provide(client)).or_die()) == (5, 5)


def test_blocking_work_behind_a_semaphore_runs_once_per_adjust():
    @fx.gen
    def program():
        cap = yield from fx.Semaphore.make(1)
        return (
            yield from _iterations(lambda: fx.blocking(lambda: time.sleep(0.02)), cap.with_permits)
        )

    with _no_busy_warning():
        assert testing.run_test(program) == 5


def test_blocking_work_on_the_asyncio_runner_runs_once_per_adjust():
    import asyncio

    work = _iterations(lambda: fx.blocking(lambda: time.sleep(0.02)), lambda eff: eff)
    with _no_busy_warning():
        assert asyncio.run(testing.run_test_async(work)) == 5


def test_an_interrupted_blocking_wait_does_not_hold_the_clock():
    @fx.gen
    def program():
        @fx.gen
        def once():
            yield from fx.sleep(1)
            work = yield from fx.blocking(lambda: time.sleep(3)).fork()
            yield from fx.yield_now()
            yield from work.interrupt()
            yield from fx.sleep(10)
            return "slept"

        fiber = yield from once.fork()
        yield from testing.adjust(1)
        yield from testing.adjust(10)
        return (yield from fiber.join())

    started = time.monotonic()
    with _no_busy_warning():
        assert testing.run_test(program) == "slept"
    assert time.monotonic() - started < 1
