"""Running on an asyncio loop and awaiting coroutines."""

import asyncio

import pytest

import pyfect as fx


def test_run_main_awaits_coroutines():
    async def fetch() -> str:
        await asyncio.sleep(0.01)
        return "data"

    assert fx.run_main(fx.from_async(fetch).map(str.upper)) == "DATA"


def test_try_async_maps_exceptions():
    async def broken() -> str:
        raise ConnectionError("down")

    eff = fx.try_async(broken, lambda e: f"failed: {e}")
    assert fx.run_main(eff.catch_all(fx.succeed)) == "failed: down"


def test_from_async_under_run_blocking_explains_itself():
    async def noop() -> None:
        return None

    with pytest.raises(fx.AsyncioRequiredError):
        fx.run_blocking(fx.from_async(noop))


def test_interrupting_a_fiber_cancels_its_task_and_waits():
    log: list[str] = []

    async def slow() -> None:
        try:
            await asyncio.sleep(10)
        finally:
            await asyncio.sleep(0)
            log.append("task cleaned up")

    @fx.gen
    def program():
        fiber = yield from fx.from_async(slow).fork()
        yield from fx.sleep(0.01)
        yield from fiber.interrupt()
        log.append("after interrupt")

    fx.run_main(program)
    assert log == ["task cleaned up", "after interrupt"]


def test_cancelling_the_awaiting_task_interrupts_the_fiber():
    log: list[str] = []

    async def main() -> None:
        eff = fx.never.ensuring(fx.sync(lambda: log.append("finalizer ran")))
        task = asyncio.create_task(fx.run_async(eff))
        await asyncio.sleep(0.01)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(main())
    assert log == ["finalizer ran"]


def test_fibers_run_concurrently_with_asyncio_tasks():
    async def main() -> list[str]:
        log: list[str] = []

        async def other() -> None:
            await asyncio.sleep(0.01)
            log.append("asyncio task")

        task = asyncio.create_task(other())
        await fx.run_async(fx.sleep(0.05).and_then(fx.sync(lambda: log.append("fiber"))))
        await task
        return log

    assert asyncio.run(main()) == ["asyncio task", "fiber"]
