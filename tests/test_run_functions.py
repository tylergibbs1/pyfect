"""run_fork, run_callback and the run functions' ``context`` argument."""

import asyncio
from typing import Any

import pytest

import pyfect as fx
from pyfect import testing
from pyfect.scheduler import SyncScheduler


class Name(fx.Tag[str]): ...


class Port(fx.Tag[int]): ...


services = fx.Context.make(Name, "ada").add(Port, 8080)


@fx.gen
def describe():
    name = yield from Name()
    port = yield from Port()
    return f"{name}:{port}"


def test_run_sync_with_a_context():
    assert fx.run_sync(describe, context=services) == "ada:8080"
    ex = fx.run_sync_exit(Name().and_then(fx.fail("no")), context=services)
    assert isinstance(ex, fx.Failure)


def test_run_async_with_a_context():
    assert asyncio.run(fx.run_async(describe, context=services)) == "ada:8080"


def test_a_context_with_more_services_than_needed_is_accepted():
    assert fx.run_sync(Name(), context=services) == "ada"


def test_run_fork_without_a_fiber_loop_or_scheduler_raises():
    with pytest.raises(fx.NoRunError):
        fx.run_fork(fx.void)


def test_run_fork_on_a_given_scheduler_runs_when_driven():
    scheduler = SyncScheduler()
    fiber = fx.run_fork(Name(), context=services, scheduler=scheduler)
    assert fiber.unsafe_poll() is None
    scheduler.run_until(lambda: fiber.unsafe_poll() is not None)
    assert fiber.unsafe_poll() == fx.Success("ada")


@testing.effect
def test_run_fork_from_a_fiber_runs_at_once_and_outlives_it():
    log: list[str] = []
    fiber = fx.run_fork(fx.sync(lambda: log.append("ran")).and_then(fx.sleep(1)))
    assert log == ["ran"]
    assert fiber.unsafe_poll() is None
    yield from fiber.interrupt()


def test_run_fork_on_a_loop_runs_at_once():
    async def main() -> list[str]:
        log: list[str] = []
        fiber = fx.run_fork(fx.sync(lambda: log.append("ran")))
        assert fiber.unsafe_poll() == fx.Success(None)
        return log

    assert asyncio.run(main()) == ["ran"]


def test_run_callback_reports_the_exit_and_can_interrupt():
    async def main() -> list[fx.Exit[Any, Any]]:
        exits: list[fx.Exit[Any, Any]] = []
        interrupt = fx.run_callback(fx.never, on_exit=exits.append)
        assert exits == []
        interrupt(7)
        await asyncio.sleep(0)
        fx.run_callback(Name(), context=services, on_exit=exits.append)
        return exits

    first, second = asyncio.run(main())
    assert isinstance(first, fx.Failure)
    assert first.cause.interruptors == {7}
    assert second == fx.Success("ada")


def test_a_finalizer_sees_the_closing_fibers_services_under_its_own():
    """Effect's addFinalizer provides its captured context over the closing
    fiber's (``provideContext`` merges)."""
    seen: list[str] = []

    @fx.gen
    def register():
        scope = yield from fx.Scope()
        yield from scope.add_finalizer(lambda _ex: describe.map(seen.append))

    closing = fx.CloseableScope()
    fx.run_sync(
        register.pipe(fx.provide_service(fx.Scope, closing)), context=fx.Context.make(Name, "own")
    )
    fx.run_sync(closing.close(fx.Success(None)), context=services)
    assert seen == ["own:8080"]
