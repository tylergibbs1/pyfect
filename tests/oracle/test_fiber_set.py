"""Ports of Effect's ``FiberSet.test.ts`` and
``FiberSetRuntimePropagation.test.ts``.

Each test's docstring is the Effect test title. ``Effect.runFork(eff)`` is
``eff.fork_daemon(start_immediately=True)``, ``Scope.provide(scope)`` is
``fx.scope.provide(scope)``, and ``makeRuntimePromise`` is
``make_runtime_async`` (a runner returning an asyncio future). Durations
are seconds rather than milliseconds. "identifies FiberSet in JSON" checks
``repr``: Python has no ``toJSON``.
"""

from typing import Any

import pyfect as fx
from pyfect import schedule, testing


def _interrupted(ex: fx.Exit[Any, Any] | None) -> bool:
    return isinstance(ex, fx.Failure) and ex.cause.has_interrupts


@testing.effect
def test_run_defers_startup():
    """run defers startup"""
    container = yield from fx.FiberSet.make()
    started = False

    def start() -> None:
        nonlocal started
        started = True

    fiber = yield from container.run(fx.sync(start), start_immediately=False)
    assert not started
    yield from fiber.join()
    assert started


@testing.effect
def test_identifies_fiber_set_in_json():
    """identifies FiberSet in JSON"""
    fiber_set = yield from fx.FiberSet.make()
    assert repr(fiber_set) == "FiberSet(size=0)"


@testing.effect
def test_interrupts_running_fibers_when_the_scope_closes():
    """interrupts running fibers when the scope closes"""
    ref = yield from fx.Ref.make(0)

    @fx.gen
    def program():
        fiber_set = yield from fx.FiberSet.make()
        yield from (
            fx.never.on_interrupt(ref.update(lambda n: n + 1))
            .pipe(fiber_set.run)
            .repeat(schedule.recurs(9))
        )
        yield from fx.yield_now()

    yield from fx.scoped(program)
    assert (yield from ref.get()) == 10


@testing.effect
def test_runtime():
    """runtime"""
    ref = yield from fx.Ref.make(0)

    @fx.gen
    def program():
        fiber_set = yield from fx.FiberSet.make()
        run = yield from fiber_set.runtime()
        for _ in range(10):
            run(fx.never.on_interrupt(ref.update(lambda n: n + 1)))
        yield from fx.yield_now()

    yield from fx.scoped(program)
    assert (yield from ref.get()) == 10


@testing.effect
def test_runs_fibers_concurrently_and_await_empty_waits_for_completion():
    """runs fibers concurrently and awaitEmpty waits for completion"""
    fiber_set = yield from fx.FiberSet[None, str].make()
    fiber_set.add_unsafe((yield from fx.void.fork_daemon(start_immediately=True)))
    fiber_set.add_unsafe((yield from fx.void.fork_daemon(start_immediately=True)))
    fiber_set.add_unsafe((yield from fx.fail("fail").fork_daemon(start_immediately=True)))
    assert (yield from fiber_set.join().flip()) == "fail"


@testing.effect
def test_size():
    """size"""
    scope = fx.CloseableScope()
    fiber_set = yield from fx.FiberSet.make().pipe(fx.scope.provide(scope))
    fiber_set.add_unsafe((yield from fx.never.fork_daemon(start_immediately=True)))
    fiber_set.add_unsafe((yield from fx.never.fork_daemon(start_immediately=True)))
    assert (yield from fiber_set.size()) == 2
    yield from scope.close(fx.Success(None))
    assert (yield from fiber_set.size()) == 0


@testing.effect
def test_propagate_interruption_false_ignores_external_interruption():
    """propagateInterruption false ignores external interruption"""
    fiber_set = yield from fx.FiberSet.make()
    fiber = yield from fiber_set.run(fx.never, propagate_interruption=False)
    yield from fx.yield_now()
    yield from fiber.interrupt()
    assert not (yield from fiber_set.deferred.is_done())


@testing.effect
def test_propagate_interruption_true_fails_join_on_external_interruption():
    """propagateInterruption true fails join on external interruption"""
    fiber_set = yield from fx.FiberSet.make()
    fiber = yield from fiber_set.run(fx.never, propagate_interruption=True)
    yield from fx.yield_now()
    yield from fiber.interrupt()
    assert _interrupted((yield from fiber_set.join().exit()))


@testing.effect
def test_await_empty():
    """awaitEmpty"""
    fiber_set = yield from fx.FiberSet.make()
    for _ in range(4):
        yield from fiber_set.run(fx.sleep(1))

    fiber = yield from fiber_set.await_empty().fork()
    yield from testing.adjust(0.5)
    assert fiber.poll_unsafe() is None
    yield from testing.adjust(0.5)
    assert fiber.poll_unsafe() is not None


@testing.effect(asyncio=True)
def test_make_runtime_promise():
    """makeRuntimePromise"""
    run = yield from fx.FiberSet.make_runtime_async()
    result = yield from fx.from_async(lambda: run(fx.succeed("done")))
    assert result == "done"


@testing.effect
def test_records_external_interruption_when_enabled():
    """records external interruption when enabled"""
    fiber_set = yield from fx.FiberSet.make()
    run = yield from fiber_set.runtime()
    fiber = run(fx.never, propagate_interruption=True)

    yield from fiber.interrupt()

    assert (yield from fiber_set.deferred.is_done())
