"""``pyfect._loop_bridge``: a fiber running a coroutine on a loop of pyfect's.

The race every driver had to get right on its own: an interrupt before the
coroutine starts, while it runs, and after its value reached the loop but
before the fiber took it, with each value released exactly once; and a
bridge closed while a fiber waits. Each case holds the loop (``_held``) so the
order is fixed, not timed."""

from __future__ import annotations

import asyncio
import gc
import logging
import threading
from collections.abc import Callable, Iterator
from typing import Any, Never

import pytest

import pyfect as fx
from pyfect._loop_bridge import (
    CANCEL,
    CANCEL_AND_WAIT,
    OnInterrupt,
    OwnedLoopBridge,
    stop_with,
)
from pyfect._released import Released
from pyfect.exit import Exit, Failure, Success


class Failed(Exception):
    def __init__(self, cause: BaseException) -> None:
        super().__init__(repr(cause))
        self.cause = cause


def _catch(error: BaseException) -> fx.Effect[Never, Failed]:
    return fx.fail(Failed(error))


@pytest.fixture
def bridge() -> Iterator[OwnedLoopBridge]:
    made = OwnedLoopBridge("test-bridge", "test bridge")
    yield made
    fx.run_blocking(made.close())


def _held(bridge: OwnedLoopBridge) -> threading.Event:
    """Hold the loop until the event is set."""
    go = threading.Event()
    bridge.call_soon(lambda: go.wait(10))
    return go


def _interrupted(exit: Exit[Any, Any]) -> bool:
    return isinstance(exit, Failure) and exit.cause.has_interrupts_only


class _Releases:
    def __init__(self) -> None:
        self.released: list[str] = []

    async def __call__(self, value: str) -> None:
        self.released.append(value)


def test_a_value_goes_to_the_fiber_and_an_error_through_catch(bridge: OwnedLoopBridge) -> None:
    async def value() -> str:
        return "made"

    async def broken() -> str:
        raise ValueError("no")

    assert fx.run_blocking(bridge.run(value, _catch, waits_for="work").or_die()) == "made"
    error = fx.run_blocking(bridge.run(broken, _catch, waits_for="work").flip().or_die())
    assert isinstance(error.cause, ValueError)


def test_a_raise_in_catch_is_a_defect(bridge: OwnedLoopBridge) -> None:
    async def broken() -> str:
        raise ValueError("no")

    def catch(_error: BaseException) -> fx.Effect[Never, Failed]:
        raise RuntimeError("catch broke")

    exit = fx.run_blocking(bridge.run(broken, catch, waits_for="work").exit())
    assert isinstance(exit, Failure)
    assert isinstance(exit.cause.squash(), RuntimeError)


@pytest.mark.parametrize("on_interrupt", [CANCEL, CANCEL_AND_WAIT])
def test_interrupted_before_it_starts_it_never_runs(
    bridge: OwnedLoopBridge, on_interrupt: OnInterrupt
) -> None:
    ran: list[str] = []
    releases = _Releases()

    async def make() -> str:
        ran.append("ran")
        return "made"

    @fx.gen
    def program():
        fiber = yield from bridge.run(
            make, _catch, waits_for="work", release=releases, on_interrupt=on_interrupt
        ).fork(start_immediately=True)
        yield from fx.sync(lambda: fiber.interrupt_as_unsafe(None))
        yield from fx.sync(go.set)
        return (yield from fiber.await_exit())

    go = _held(bridge)
    try:
        exit = fx.run_blocking(program)
    finally:
        go.set()
    fx.run_blocking(bridge.close())
    assert _interrupted(exit)
    assert ran == []
    assert releases.released == []


def test_cancel_goes_on_at_once_and_cancels_the_coroutine(bridge: OwnedLoopBridge) -> None:
    started = threading.Event()
    cancelled = threading.Event()

    async def make() -> str:
        started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.set()
            raise
        return "never"

    @fx.gen
    def program():
        fiber = yield from bridge.run(make, _catch, waits_for="work", on_interrupt=CANCEL).fork()
        yield from fx.blocking(started.wait)
        yield from fiber.interrupt()
        return (yield from fiber.await_exit())

    assert _interrupted(fx.run_blocking(program))
    assert cancelled.wait(5)


def test_cancel_and_wait_goes_on_once_the_coroutine_has_ended(bridge: OwnedLoopBridge) -> None:
    started = threading.Event()
    ended: list[str] = []

    async def make() -> str:
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            await asyncio.sleep(0.05)
            ended.append("ended")
        return "never"

    @fx.gen
    def program():
        fiber = yield from bridge.run(
            make, _catch, waits_for="work", on_interrupt=CANCEL_AND_WAIT
        ).fork()
        yield from fx.blocking(started.wait)
        yield from fiber.interrupt()
        return list(ended)

    assert fx.run_blocking(program) == ["ended"]


def test_a_stop_runs_on_the_task_and_is_waited_for(bridge: OwnedLoopBridge) -> None:
    started = threading.Event()
    stopped: list[str] = []

    async def make() -> str:
        started.set()
        await asyncio.Event().wait()
        return "never"

    async def stop(task: asyncio.Task[Any]) -> None:
        task.cancel()
        await asyncio.wait([task])
        stopped.append("stopped")

    @fx.gen
    def program():
        fiber = yield from bridge.run(
            make, _catch, waits_for="work", on_interrupt=stop_with(stop)
        ).fork()
        yield from fx.blocking(started.wait)
        yield from fiber.interrupt()
        return list(stopped)

    assert fx.run_blocking(program) == ["stopped"]


@pytest.mark.parametrize("on_interrupt", [CANCEL, CANCEL_AND_WAIT])
def test_a_value_made_after_the_interrupt_is_released_once(
    bridge: OwnedLoopBridge, on_interrupt: OnInterrupt
) -> None:
    """The coroutine makes its value all the same (it ignores the cancel, as a
    connect that finished in the same step would)."""
    started = threading.Event()
    releases = _Releases()

    async def make() -> str:
        started.set()
        finish = asyncio.get_running_loop().create_future()
        asyncio.get_running_loop().call_later(0.05, finish.set_result, None)
        while not finish.done():
            try:
                await asyncio.wait([finish])
            except asyncio.CancelledError:
                continue
        return "made"

    @fx.gen
    def program():
        fiber = yield from bridge.run(
            make, _catch, waits_for="work", release=releases, on_interrupt=on_interrupt
        ).fork()
        yield from fx.blocking(started.wait)
        yield from fiber.interrupt()
        return (yield from fiber.await_exit())

    assert _interrupted(fx.run_blocking(program))
    fx.run_blocking(bridge.close())
    assert releases.released == ["made"]


def test_a_value_handed_over_but_not_taken_is_released_once(bridge: OwnedLoopBridge) -> None:
    """The loop gave the value to the fiber, but the interrupt lands before
    the fiber's scheduler takes it."""
    handed = threading.Event()
    releases = _Releases()

    async def make() -> str:
        loop = asyncio.get_running_loop()
        # Runs after the task's own callbacks have handed the value over.
        loop.call_soon(lambda: loop.call_soon(handed.set))
        return "made"

    @fx.gen
    def program():
        fiber = yield from bridge.run(make, _catch, waits_for="work", release=releases).fork(
            start_immediately=True
        )
        # Holds the scheduler, so the fiber cannot take the value before the interrupt.
        yield from fx.sync(lambda: handed.wait(10))
        yield from fx.sync(lambda: fiber.interrupt_as_unsafe(None))
        return (yield from fiber.await_exit())

    assert _interrupted(fx.run_blocking(program))
    fx.run_blocking(bridge.close())
    assert releases.released == ["made"]


def test_a_value_the_fiber_took_is_never_released(bridge: OwnedLoopBridge) -> None:
    releases = _Releases()

    async def make() -> str:
        return "made"

    @fx.gen
    def program():
        value = yield from bridge.run(make, _catch, waits_for="work", release=releases)
        yield from fx.never.timeout("1 millis").ignore()
        return value

    assert fx.run_blocking(program.or_die()) == "made"
    fx.run_blocking(bridge.close())
    assert releases.released == []


def test_an_abort_cancels_while_the_fiber_still_waits(bridge: OwnedLoopBridge) -> None:
    listeners: list[Callable[[], None]] = []
    started = threading.Event()

    def aborted_by(listener: Callable[[], None]) -> Callable[[], None]:
        listeners.append(listener)
        return lambda: listeners.remove(listener)

    async def make() -> str:
        started.set()
        await asyncio.Event().wait()
        return "never"

    @fx.gen
    def program():
        fiber = yield from bridge.run(make, _catch, waits_for="work", aborted_by=aborted_by).fork()
        yield from fx.blocking(started.wait)
        yield from fx.sync(listeners[0])
        return (yield from fiber.join().flip().or_die())

    error = fx.run_blocking(program)
    assert isinstance(error.cause, asyncio.CancelledError)
    assert listeners == []


def test_closing_while_a_fiber_waits_cancels_its_coroutine(bridge: OwnedLoopBridge) -> None:
    started = threading.Event()

    async def make() -> str:
        started.set()
        await asyncio.Event().wait()
        return "never"

    @fx.gen
    def program():
        fiber = yield from bridge.run(make, _catch, waits_for="event").fork()
        yield from fx.blocking(started.wait)
        yield from bridge.close()
        return (yield from fiber.join().flip().or_die())

    error = fx.run_blocking(program)
    assert isinstance(error.cause, asyncio.CancelledError)


def test_a_call_after_close_fails_with_released(bridge: OwnedLoopBridge) -> None:
    async def make() -> str:
        return "made"

    fx.run_blocking(bridge.close())
    error = fx.run_blocking(bridge.run(make, _catch, waits_for="work").flip().or_die())
    assert isinstance(error.cause, Released)
    assert error.cause.owner == "test bridge"
    assert isinstance(fx.run_blocking(bridge.close().exit()), Success)


def test_a_release_started_while_the_bridge_closes_runs_to_its_end(
    bridge: OwnedLoopBridge, caplog: pytest.LogCaptureFixture
) -> None:
    """A response dropped as its client shuts down is still closed (CI run
    44334314912 caught one destroyed while pending)."""
    closed: list[str] = []

    async def aclose() -> None:
        for _ in range(3):
            await asyncio.sleep(0)
        closed.append("closed")

    async def shutdown() -> None:
        bridge.start(aclose)
        await asyncio.sleep(0)

    fx.run_blocking(bridge.close(shutdown))
    assert closed == ["closed"]
    gc.collect()
    assert [r.getMessage() for r in caplog.records if r.levelno >= logging.ERROR] == []
