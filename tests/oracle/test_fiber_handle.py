"""Ports of Effect's ``FiberHandle.test.ts``.

Each test's docstring is the Effect test title. ``Effect.runFork(eff)`` is
``eff.fork_daemon(start_immediately=True)``, ``Scope.provide(scope)`` is
``provide_service(fx.Scope, scope)``, ``getUnsafe`` / ``get`` give the
fiber or ``None``, and ``makeRuntimePromise`` is ``make_runtime_async`` (a
runner returning an asyncio future). Durations are seconds rather than
milliseconds.
"""

from typing import Any

import pytest

import pyfect as fx
from pyfect import testing


def _interrupted(ex: fx.Exit[Any, Any] | None) -> bool:
    return isinstance(ex, fx.Failure) and ex.cause.has_interrupts


@fx.gen
def _make_worker():
    ready = yield from fx.Deferred[None].make()
    cleanups = yield from fx.Ref.make(0)
    fiber = yield from (
        ready.succeed(None)
        .and_then(fx.never)
        .ensuring(cleanups.update(lambda n: n + 1))
        .fork_scoped(start_immediately=True)
    )
    yield from ready.wait()
    return fiber, cleanups


@testing.effect
def test_closing_the_scope_waits_for_asynchronous_cleanup_of_a_replaced_fiber():
    """closing the scope waits for asynchronous cleanup of a replaced fiber"""
    events: list[str] = []
    started = yield from fx.Deferred[None].make()
    release = yield from fx.Deferred[None].make()
    scope = fx.CloseableScope()
    yield from scope.add_finalizer(lambda _: fx.sync(lambda: events.append("resource released")))
    container = yield from fx.FiberHandle.make().pipe(fx.provide_service(fx.Scope, scope))
    previous = yield from container.run(
        started.succeed(None)
        .and_then(fx.never)
        .on_interrupt(
            release.wait().and_then(fx.sync(lambda: events.append("worker cleanup done")))
        )
    )
    yield from started.wait()
    yield from container.run(fx.never)

    closing = yield from scope.close(fx.Success(None)).fork(start_immediately=True)
    yield from release.succeed(None)
    yield from closing.join()
    yield from previous.await_exit()

    assert events == ["worker cleanup done", "resource released"]


@testing.effect
def test_run_defers_startup():
    """run defers startup"""
    container = yield from fx.FiberHandle.make()
    started = False

    def start() -> None:
        nonlocal started
        started = True

    fiber = yield from container.run(fx.sync(start), start_immediately=False)
    assert not started
    yield from fiber.join()
    assert started


@testing.effect
def test_interrupts_the_current_fiber_when_the_scope_closes():
    """interrupts the current fiber when the scope closes"""
    ref = yield from fx.Ref.make(0)

    @fx.gen
    def program():
        handle = yield from fx.FiberHandle.make()
        yield from handle.run(fx.never.on_interrupt(ref.update(lambda n: n + 1)))
        yield from fx.yield_now()

    yield from fx.scoped(program)
    assert (yield from ref.get()) == 1


@testing.effect
def test_retains_ownership_of_a_replacement_made_by_a_synchronous_finalizer():
    """retains ownership of a replacement made by a synchronous finalizer"""
    scope = fx.CloseableScope()
    handle = yield from fx.FiberHandle.make().pipe(fx.provide_service(fx.Scope, scope))
    run = yield from handle.runtime()
    fibers: list[fx.Fiber[Any, Any]] = []
    yield from fx.add_finalizer(lambda _: fx.Fiber.interrupt_all(fibers))

    previous = run(fx.never.ensuring(fx.sync(lambda: fibers.append(run(fx.never)))))
    replacement = run(fx.never)
    fibers.extend([previous, replacement])
    assert len(fibers) == 3

    yield from scope.close(fx.Success(None))

    assert previous.poll_unsafe() is not None
    assert replacement.poll_unsafe() is not None
    assert fibers[0].poll_unsafe() is not None


@testing.effect
def test_runtime():
    """runtime"""
    ref = yield from fx.Ref.make(0)

    def counting() -> fx.Effect[None]:
        return fx.never.on_interrupt(ref.update(lambda n: n + 1))

    @fx.gen
    def program():
        handle = yield from fx.FiberHandle.make()
        run = yield from handle.runtime()
        run(counting())
        yield from fx.yield_now()
        run(counting())
        yield from fx.yield_now()
        run(counting(), only_if_missing=True)
        yield from fx.yield_now()
        assert (yield from ref.get()) == 1

    yield from fx.scoped(program)
    assert (yield from ref.get()) == 2


@testing.effect
def test_get_and_get_unsafe():
    """get and getUnsafe"""
    handle = yield from fx.FiberHandle[str].make()

    assert handle.get_unsafe() is None
    assert (yield from handle.get()) is None

    fiber = yield from handle.run(fx.never)

    assert handle.get_unsafe() is fiber
    assert (yield from handle.get()) is fiber


@testing.effect
def test_join_ignores_managed_replacement_interruptions_and_fails_with_child_errors():
    """join ignores managed replacement interruptions and fails with child errors"""
    handle = yield from fx.FiberHandle.make()
    handle.set_unsafe((yield from fx.void.fork_daemon(start_immediately=True)))
    handle.set_unsafe((yield from fx.fail("fail").fork_daemon(start_immediately=True)))
    assert (yield from handle.join().flip()) == "fail"


@testing.effect
def test_only_if_missing_keeps_the_current_fiber_and_interrupts_rejected_starts():
    """onlyIfMissing keeps the current fiber and interrupts rejected starts"""
    handle = yield from fx.FiberHandle.make()
    fiber_a = yield from handle.run(fx.never)
    fiber_b = yield from handle.run(fx.never, only_if_missing=True)
    fiber_c = yield from handle.run(fx.never, only_if_missing=True)
    yield from fx.yield_now()
    assert _interrupted((yield from fiber_b.await_exit()))
    assert _interrupted((yield from fiber_c.await_exit()))
    assert fiber_a.poll_unsafe() is None


@testing.effect
def test_only_if_missing_keeps_the_same_registered_fiber():
    """onlyIfMissing keeps the same registered fiber"""
    handle = yield from fx.FiberHandle.make()
    worker, cleanups = yield from _make_worker
    handle.set_unsafe(worker)
    handle.set_unsafe(worker, only_if_missing=True)

    assert handle.get_unsafe() is worker
    assert worker.poll_unsafe() is None
    assert (yield from cleanups.get()) == 0


@pytest.mark.parametrize("propagate_interruption", [False, True])
@testing.effect
def test_same_fiber_registration_preserves_propagate_interruption(propagate_interruption: bool):
    """same-fiber registration preserves propagateInterruption: ${propagateInterruption}"""
    handle = yield from fx.FiberHandle.make()
    worker, _ = yield from _make_worker
    handle.set_unsafe(worker, propagate_interruption=propagate_interruption)
    handle.set_unsafe(
        worker, only_if_missing=True, propagate_interruption=not propagate_interruption
    )

    yield from worker.interrupt()
    assert (yield from handle.deferred.is_done()) == propagate_interruption


@testing.effect
def test_clear_does_not_remove_a_newer_fiber_installed_while_interrupting_the_previous_one():
    """clear does not remove a newer fiber installed while interrupting the previous one"""
    handle = yield from fx.FiberHandle.make()
    yield from handle.run(fx.sleep("200 millis").uninterruptible())

    clear_fiber = yield from handle.clear().fork(start_immediately=True)
    yield from testing.adjust("50 millis")
    next_fiber = yield from handle.run(fx.never)
    yield from testing.adjust("200 millis")
    yield from clear_fiber.join()

    assert handle.get_unsafe() is next_fiber
    assert next_fiber.poll_unsafe() is None


@testing.effect
def test_runtime_only_if_missing():
    """runtime onlyIfMissing"""
    run = yield from fx.FiberHandle.make_runtime()
    fiber_a = run(fx.never)
    fiber_b = run(fx.never, only_if_missing=True)
    fiber_c = run(fx.never, only_if_missing=True)
    yield from fx.yield_now()
    assert _interrupted((yield from fiber_b.await_exit()))
    assert _interrupted((yield from fiber_c.await_exit()))
    assert fiber_a.poll_unsafe() is None


@testing.effect
def test_propagate_interruption_false():
    """propagateInterruption: false"""
    handle = yield from fx.FiberHandle.make()
    fiber = yield from handle.run(fx.never, propagate_interruption=False)
    yield from fx.yield_now()
    yield from fiber.interrupt()
    assert not (yield from handle.deferred.is_done())


@testing.effect
def test_propagate_interruption_true():
    """propagateInterruption: true"""
    handle = yield from fx.FiberHandle.make()
    fiber = yield from handle.run(fx.never, propagate_interruption=True)
    yield from fx.yield_now()
    yield from fiber.interrupt()
    assert _interrupted((yield from handle.join().exit()))


@testing.effect
def test_await_empty():
    """awaitEmpty"""
    handle = yield from fx.FiberHandle.make()
    yield from handle.run(fx.sleep("1 second"))

    fiber = yield from handle.await_empty().fork()
    yield from testing.adjust("500 millis")
    assert fiber.poll_unsafe() is None
    yield from testing.adjust("500 millis")
    assert fiber.poll_unsafe() is not None


@testing.effect(asyncio=True)
def test_make_runtime_promise():
    """makeRuntimePromise"""
    run = yield from fx.FiberHandle.make_runtime_async()
    result = yield from fx.from_async(lambda: run(fx.succeed("done")))
    assert result == "done"
