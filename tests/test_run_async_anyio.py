"""``run_async`` from anyio code on its asyncio backend. anyio cancels by level: a task in a
cancelled scope gets a new ``CancelledError`` at every await until it leaves the scope. Leaving
a cancelled scope still interrupts the fiber, and waits for its finalizers, as a plain
``task.cancel()`` does (``tests/test_run_async_cancel.py``)."""

from collections.abc import Callable, Coroutine
from typing import Any

import anyio
import anyio.lowlevel
import pytest

import pyfect as fx
from pyfect import layer

type Entry = Callable[[fx.Effect[None]], Coroutine[Any, Any, Any]]
type Host = Callable[[Entry, fx.Effect[None]], Coroutine[Any, Any, str]]


def _finalized(log: list[str]) -> fx.Effect[None]:
    """Never ends; its finalizer waits on the scheduler before it logs."""

    @fx.gen
    def finalizer():
        yield from fx.sleep("20 millis")
        log.append("finalizer")

    return fx.never.ensuring(finalizer)


async def _move_on_after(run: Entry, eff: fx.Effect[None]) -> str:
    with anyio.move_on_after(0.01) as scope:
        await run(eff)
    return f"moved on: {scope.cancelled_caught}"


async def _fail_after(run: Entry, eff: fx.Effect[None]) -> str:
    try:
        with anyio.fail_after(0.01):
            await run(eff)
    except TimeoutError:
        return "timed out"
    return "ended"


async def _task_group_cancel(run: Entry, eff: fx.Effect[None]) -> str:
    async with anyio.create_task_group() as group:
        group.start_soon(run, eff)
        await anyio.sleep(0.01)
        group.cancel_scope.cancel()
    return "group cancelled"


_HOSTS: dict[str, tuple[Host, str]] = {
    "move_on_after": (_move_on_after, "moved on: True"),
    "fail_after": (_fail_after, "timed out"),
    "task_group": (_task_group_cancel, "group cancelled"),
}


@pytest.mark.parametrize("host", list(_HOSTS))
@pytest.mark.parametrize("entry", ["fx", "fx_exit", "runtime", "runtime_exit"])
def test_leaving_a_cancelled_anyio_scope_waits_for_the_finalizers(entry: str, host: str) -> None:
    cancel, outcome = _HOSTS[host]

    async def main() -> list[str]:
        log: list[str] = []
        async with fx.ManagedRuntime.make(layer.empty) as runtime:
            run: Entry = {
                "fx": fx.run_async,
                "fx_exit": fx.run_async_exit,
                "runtime": runtime.run_async,
                "runtime_exit": runtime.run_async_exit,
            }[entry]
            log.append(await cancel(run, _finalized(log)))
        return log

    assert anyio.run(main, backend="asyncio") == ["finalizer", outcome]


def test_an_anyio_coroutine_under_from_async_is_cancelled_when_the_fiber_is_interrupted() -> None:
    log: list[str] = []

    async def slow() -> None:
        try:
            await anyio.sleep(10)
        finally:
            with anyio.CancelScope(shield=True):
                await anyio.sleep(0.01)
            log.append("coroutine cleaned up")

    @fx.gen
    def program():
        fiber = yield from fx.from_async(slow).fork()
        yield from fx.sleep("10 millis")
        yield from fiber.interrupt()
        log.append("interrupt returned")

    async def main() -> None:
        await fx.run_async(program)

    anyio.run(main, backend="asyncio")
    assert log == ["coroutine cleaned up", "interrupt returned"]


def test_an_anyio_coroutine_raising_is_a_defect_or_an_unknown_error() -> None:
    async def broken() -> None:
        await anyio.lowlevel.checkpoint()
        raise ConnectionError("down")

    async def main() -> tuple[fx.Exit[None, Any], fx.Exit[None, Any]]:
        return (
            await fx.run_async_exit(fx.from_async(broken)),
            await fx.run_async_exit(fx.try_async(broken)),
        )

    died, failed = anyio.run(main, backend="asyncio")
    assert isinstance(died, fx.Failure) and isinstance(failed, fx.Failure)
    [die] = died.cause.reasons
    assert isinstance(die, fx.cause.Die) and isinstance(die.defect, ConnectionError)
    [fail] = failed.cause.reasons
    assert isinstance(fail, fx.cause.Fail) and isinstance(fail.error, fx.UnknownError)
    assert isinstance(fail.error.cause, ConnectionError)
