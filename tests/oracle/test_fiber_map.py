"""Ports of Effect's ``FiberMap.test.ts``.

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
    container = yield from fx.FiberMap[str].make().pipe(fx.provide_service(fx.Scope, scope))
    previous = yield from container.run(
        "key",
        started.succeed(None)
        .and_then(fx.never)
        .on_interrupt(
            release.wait().and_then(fx.sync(lambda: events.append("worker cleanup done")))
        ),
    )
    yield from started.wait()
    yield from container.run("key", fx.never)

    closing = yield from scope.close(fx.Success(None)).fork(start_immediately=True)
    yield from release.succeed(None)
    yield from closing.join()
    yield from previous.await_exit()

    assert events == ["worker cleanup done", "resource released"]


@testing.effect
def test_run_defers_startup():
    """run defers startup"""
    container = yield from fx.FiberMap[str].make()
    started = False

    def start() -> None:
        nonlocal started
        started = True

    fiber = yield from container.run("key", fx.sync(start), start_immediately=False)
    assert not started
    yield from fiber.join()
    assert started


@testing.effect
def test_retains_ownership_of_replacements_made_by_a_synchronous_finalizer():
    """retains ownership of replacements made by a synchronous finalizer"""
    scope = fx.CloseableScope()
    fiber_map = yield from fx.FiberMap[str].make().pipe(fx.provide_service(fx.Scope, scope))
    run = yield from fiber_map.runtime()
    fibers: list[fx.Fiber[Any, Any]] = []
    yield from fx.add_finalizer(lambda _: fx.Fiber.interrupt_all(fibers))

    previous = run("key", fx.never.ensuring(fx.sync(lambda: fibers.append(run("key", fx.never)))))
    replacement = run("key", fx.never)
    fibers.extend([previous, replacement])
    assert len(fibers) == 3

    yield from scope.close(fx.Success(None))

    for fiber in fibers:
        assert fiber.unsafe_poll() is not None


@testing.effect
def test_removes_a_synchronously_completed_replacement():
    """removes a synchronously completed replacement"""
    fiber_map = yield from fx.FiberMap[str].make()
    previous = yield from fiber_map.run("key", fx.never)
    replacement = yield from fiber_map.run("key", fx.succeed("done"))

    assert (yield from replacement.join()) == "done"
    assert _interrupted((yield from previous.await_exit()))
    assert (yield from fiber_map.size()) == 0


@testing.effect
def test_interrupts_fibers():
    """interrupts fibers"""
    ref = yield from fx.Ref.make(0)

    @fx.gen
    def program():
        fiber_map = yield from fx.FiberMap[int].make()
        yield from fx.for_each(
            range(1, 11),
            lambda i: fiber_map.run(i, fx.never.on_interrupt(ref.update(lambda n: n + 1))),
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
        fiber_map = yield from fx.FiberMap[int].make()
        run = yield from fiber_map.runtime()
        for i in range(1, 11):
            run(i, fx.never.on_interrupt(ref.update(lambda n: n + 1)))
        yield from fx.yield_now()

    yield from fx.scoped(program)
    assert (yield from ref.get()) == 10


@testing.effect
def test_get_and_get_unsafe():
    """get and getUnsafe"""
    fiber_map = yield from fx.FiberMap[str, str].make()

    assert fiber_map.unsafe_get("a") is None
    assert (yield from fiber_map.get("a")) is None

    fiber = yield from fiber_map.run("a", fx.never)

    assert fiber_map.unsafe_get("a") is fiber
    assert (yield from fiber_map.get("a")) is fiber


@testing.effect
def test_join():
    """join"""
    fiber_map = yield from fx.FiberMap[str].make()
    fiber_map.unsafe_set("a", (yield from fx.void.fork_daemon(start_immediately=True)))
    fiber_map.unsafe_set("b", (yield from fx.void.fork_daemon(start_immediately=True)))
    fiber_map.unsafe_set("c", (yield from fx.fail("fail").fork_daemon(start_immediately=True)))
    fiber_map.unsafe_set("d", (yield from fx.fail("ignored").fork_daemon(start_immediately=True)))
    assert (yield from fiber_map.join().flip()) == "fail"


@testing.effect
def test_size():
    """size"""
    scope = fx.CloseableScope()
    fiber_map = yield from fx.FiberMap[str].make().pipe(fx.provide_service(fx.Scope, scope))
    fiber_map.unsafe_set("a", (yield from fx.never.fork_daemon(start_immediately=True)))
    fiber_map.unsafe_set("b", (yield from fx.never.fork_daemon(start_immediately=True)))
    assert (yield from fiber_map.size()) == 2
    yield from scope.close(fx.Success(None))
    assert (yield from fiber_map.size()) == 0


@testing.effect
def test_only_if_missing():
    """onlyIfMissing"""
    handle = yield from fx.FiberMap[str].make()
    fiber_a = yield from handle.run("a", fx.never)
    fiber_b = yield from handle.run("a", fx.never, only_if_missing=True)
    fiber_c = yield from handle.run("a", fx.never, only_if_missing=True)
    yield from fx.yield_now()
    assert _interrupted((yield from fiber_b.await_exit()))
    assert _interrupted((yield from fiber_c.await_exit()))
    assert fiber_a.unsafe_poll() is None


@testing.effect
def test_only_if_missing_keeps_the_same_registered_fiber():
    """onlyIfMissing keeps the same registered fiber"""
    fiber_map = yield from fx.FiberMap[str].make()
    worker, cleanups = yield from _make_worker
    fiber_map.unsafe_set("key", worker)
    fiber_map.unsafe_set("key", worker, only_if_missing=True)

    assert fiber_map.unsafe_get("key") is worker
    assert worker.unsafe_poll() is None
    assert (yield from cleanups.get()) == 0


@pytest.mark.parametrize("propagate_interruption", [False, True])
@testing.effect
def test_same_fiber_registration_preserves_propagate_interruption(propagate_interruption: bool):
    """same-fiber registration preserves propagateInterruption: ${propagateInterruption}"""
    fiber_map = yield from fx.FiberMap[str].make()
    worker, _ = yield from _make_worker
    fiber_map.unsafe_set("key", worker, propagate_interruption=propagate_interruption)
    fiber_map.unsafe_set(
        "key", worker, only_if_missing=True, propagate_interruption=not propagate_interruption
    )

    yield from worker.interrupt()
    assert (yield from fiber_map.deferred.is_done()) == propagate_interruption


@testing.effect
def test_runtime_only_if_missing():
    """runtime onlyIfMissing"""
    run = yield from fx.FiberMap[str].make_runtime()
    fiber_a = run("a", fx.never)
    fiber_b = run("a", fx.never, only_if_missing=True)
    fiber_c = run("a", fx.never, only_if_missing=True)
    yield from fx.yield_now()
    assert _interrupted((yield from fiber_b.await_exit()))
    assert _interrupted((yield from fiber_c.await_exit()))
    assert fiber_a.unsafe_poll() is None


@testing.effect
def test_propagate_interruption_false():
    """propagateInterruption false"""
    fiber_map = yield from fx.FiberMap[str].make()
    fiber = yield from fiber_map.run("a", fx.never, propagate_interruption=False)
    yield from fx.yield_now()
    yield from fiber.interrupt()
    assert not (yield from fiber_map.deferred.is_done())


@testing.effect
def test_propagate_interruption_true():
    """propagateInterruption true"""
    fiber_map = yield from fx.FiberMap[str].make()
    fiber = yield from fiber_map.run("a", fx.never, propagate_interruption=True)
    yield from fx.yield_now()
    yield from fiber.interrupt()
    assert _interrupted((yield from fiber_map.join().exit()))


@testing.effect
def test_await_empty():
    """awaitEmpty"""
    fiber_map = yield from fx.FiberMap[str].make()
    for key in "abcd":
        yield from fiber_map.run(key, fx.sleep(1))

    fiber = yield from fiber_map.await_empty().fork()
    yield from testing.adjust(0.5)
    assert fiber.unsafe_poll() is None
    yield from testing.adjust(0.5)
    assert fiber.unsafe_poll() is not None


@testing.effect(asyncio=True)
def test_make_runtime_promise():
    """makeRuntimePromise"""
    run = yield from fx.FiberMap[str].make_runtime_async()
    result = yield from fx.from_async(lambda: run("a", fx.succeed("done")))
    assert result == "done"
