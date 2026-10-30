"""Ports of Effect's ``ManagedRuntime.test.ts``.

Each test's docstring is the Effect test title. ``runPromise`` is
``run_async``, ``dispose()`` is ``dispose_async`` (a Promise), ``await
using`` is ``async with``, ``forkChild`` is ``fork`` and ``forkDetach`` is
``fork_daemon``. ``Layer.effectDiscard(eff)`` is a layer building a unit
service (``_discard``). Effect's 500 ms ``Promise.race`` deadlock bounds
are ``asyncio.wait_for``; durations are seconds.
"""

import asyncio
from collections.abc import Awaitable, Coroutine
from typing import Any, Literal

import pytest

import pyfect as fx
from pyfect import layer

_BOUND = 1.0


class _Unit(fx.Tag[None]): ...


class Name(fx.Tag[str]): ...


def _discard(eff: fx.Effect[object, Any, fx.Scope]) -> layer.Layer[_Unit, Any]:
    return layer.effect(_Unit, eff.as_void())


def _finalizer(f: fx.Effect[object]) -> layer.Layer[_Unit, Any]:
    return _discard(fx.add_finalizer(lambda _ex: f))


async def _settles(coro: Awaitable[object]) -> str:
    """Effect's ``Promise.race`` against a timeout: unlike ``wait_for``, a
    timeout leaves the task alone, as cancelling it would wait for the
    uninterruptible disposal it is stuck in."""
    _, pending = await asyncio.wait({asyncio.ensure_future(coro)}, timeout=_BOUND)
    return "timed out" if pending else "settled"


def _run[T](main: Coroutine[Any, Any, T]) -> T:
    """``asyncio.run``, except that a task left stuck by a timed-out
    ``_settles`` is abandoned rather than cancelled and awaited."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(main)
    finally:
        if not asyncio.all_tasks(loop):
            loop.close()


def test_memoizes_the_layer_build():
    """memoizes the layer build"""
    count = 0

    def build() -> None:
        nonlocal count
        count += 1

    async def main() -> None:
        runtime = fx.ManagedRuntime.make(_discard(fx.sync(build)))
        await runtime.run_async(fx.void)
        await runtime.run_async(fx.void)
        await runtime.dispose_async()

    _run(main())
    assert count == 1


def test_provides_context():
    """provides context"""

    async def main() -> str:
        runtime = fx.ManagedRuntime.make(layer.succeed(Name, "test"))
        result = await runtime.run_async(Name())
        await runtime.dispose_async()
        return result

    assert _run(main()) == "test"


def test_allows_sharing_a_memo_map():
    """allows sharing a MemoMap"""
    count = 0

    def build() -> None:
        nonlocal count
        count += 1

    shared = _discard(fx.sync(build))

    async def main() -> None:
        runtime_a = fx.ManagedRuntime.make(shared)
        runtime_b = fx.ManagedRuntime.make(shared, memo_map=runtime_a.memo_map)
        await runtime_a.run_async(fx.void)
        await runtime_b.run_async(fx.void)
        await runtime_a.dispose_async()
        await runtime_b.dispose_async()

    _run(main())
    assert count == 1


def test_can_be_built_synchronously():
    """can be built synchronously"""
    runtime = fx.ManagedRuntime.make(layer.succeed(Name, "test"))
    services = fx.run_sync(runtime.context_effect)
    assert fx.run_sync(Name(), context=services) == "test"


def test_supports_await_using():
    """supports await using"""
    count = 0

    def release() -> None:
        nonlocal count
        count += 1

    async def main() -> None:
        async with fx.ManagedRuntime.make(_finalizer(fx.sync(release))) as runtime:
            await runtime.run_async(fx.void)
            assert count == 0

    _run(main())
    assert count == 1


def test_fibers_are_interrupted_on_dispose():
    """fibers are interrupted on dispose"""

    async def main() -> fx.Exit[Any, Any] | None:
        runtime = fx.ManagedRuntime.make(layer.empty)
        fiber = runtime.run_fork(fx.never)
        await runtime.dispose_async()
        return fiber.poll_unsafe()

    ex = _run(main())
    assert isinstance(ex, fx.Failure)
    assert ex.cause.has_interrupts


def test_dispose_effect_inside_run_promise_after_an_async_boundary_releases_the_layer():
    """disposeEffect inside runPromise after an async boundary releases the layer"""
    released = False

    def release() -> None:
        nonlocal released
        released = True

    async def main() -> str:
        runtime = fx.ManagedRuntime.make(_finalizer(fx.sync(release)))
        return await _settles(runtime.run_async(fx.sleep(0.001).ensuring(runtime.dispose_effect)))

    assert (_run(main()), released) == ("settled", True)


def test_dispose_effect_inside_an_immediately_started_request_child_releases_the_layer():
    """disposeEffect inside an immediately started request child releases the layer"""
    released = False

    def release() -> None:
        nonlocal released
        released = True

    async def main() -> str:
        runtime = fx.ManagedRuntime.make(_finalizer(fx.sync(release)))

        @fx.gen
        def request():
            yield from fx.sleep(0.001)
            child = yield from runtime.dispose_effect.fork(start_immediately=True)
            yield from child.join()

        return await _settles(runtime.run_async(request))

    assert (_run(main()), released) == ("settled", True)


def test_a_request_that_disposes_the_runtime_before_its_first_async_step_keeps_running():
    """a request that disposes the runtime before its first async step keeps running"""
    released = False

    def release() -> None:
        nonlocal released
        released = True

    async def main() -> str:
        runtime = fx.ManagedRuntime.make(_finalizer(fx.yield_now().and_then(fx.sync(release))))
        await runtime.run_async(fx.void)

        @fx.gen
        def request():
            yield from runtime.dispose_effect
            yield from fx.yield_now()
            return "finished"

        return await runtime.run_async(request)

    assert (_run(main()), released) == ("finished", True)


def test_a_layer_build_that_disposes_the_runtime_is_interrupted():
    """a layer build that disposes the runtime is interrupted"""

    async def main() -> bool | str:
        runtime: fx.ManagedRuntime[_Unit, Any] = fx.ManagedRuntime.make(
            _discard(fx.suspend(lambda: runtime.dispose_effect).and_then(fx.never))
        )
        task = asyncio.ensure_future(fx.run_async_exit(runtime.context_effect))
        if await _settles(asyncio.shield(task)) == "timed out":
            return "timed out"
        return isinstance(task.result(), fx.Failure)

    assert _run(main()) is True


def test_detached_fiber_disposal_still_interrupts_and_awaits_its_former_request():
    """detached-fiber disposal still interrupts and awaits its former request"""
    events: list[str] = []
    runtime = fx.ManagedRuntime.make(_finalizer(fx.sync(lambda: events.append("layer released"))))

    @fx.gen
    def disposing():
        gate = yield from fx.Deferred[None].make()
        started = yield from fx.Deferred[fx.Fiber[None]].make()

        @fx.gen
        def request():
            detached = yield from gate.wait().ensuring(runtime.dispose_effect).fork_daemon()
            yield from started.succeed(detached)
            return (yield from fx.never)

        @fx.gen
        def cleanup():
            yield from fx.sleep(0.001)
            events.append("former request cleaned up")

        runtime.run_fork(request.ensuring(cleanup))
        detached = yield from started.wait()
        yield from gate.succeed(None)
        yield from detached.join()

    result = _run(_settles(fx.run_async(disposing)))
    assert (result, events) == ("settled", ["former request cleaned up", "layer released"])


@pytest.mark.parametrize("method", ["dispose_effect", "dispose"])
def test_finishes_request_cleanup_before_releasing_layer_resources_with(
    method: Literal["dispose_effect", "dispose"],
):
    """finishes request cleanup before releasing layer resources with ${method}

    Effect's layer is a ``Pool`` (M4); here the layer's resource is a
    connection whose release is the pool closing, and the request's cleanup
    uses it."""
    events: list[str] = []
    is_open = {"pool": True}

    class Database(fx.Tag[dict[str, bool]]): ...

    def close() -> None:
        is_open["pool"] = False
        events.append("pool closed")

    database = layer.effect(
        Database, fx.acquire_release(fx.succeed(is_open), lambda _db, _ex: fx.sync(close))
    )

    @fx.gen
    def program():
        gate = yield from fx.Deferred[None].make()
        started = yield from fx.Deferred[None].make()
        runtime = fx.ManagedRuntime.make(database)
        yield from runtime.context_effect

        @fx.gen
        def request_cleanup():
            yield from gate.wait()
            pool = yield from Database()
            outcome = "Success" if pool["pool"] else "Failure"
            events.append(f"request cleanup: {outcome}")

        @fx.gen
        def request():
            yield from Database()
            yield from started.succeed(None)
            return (yield from fx.never.ensuring(request_cleanup))

        runtime.run_fork(request)
        yield from started.wait()

        if method == "dispose_effect":
            fiber = yield from runtime.dispose_effect.fork(start_immediately=True)
            yield from gate.succeed(None)
            yield from fiber.join()
        else:
            task = asyncio.ensure_future(runtime.dispose_async())
            yield from gate.succeed(None)
            yield from fx.from_async(lambda: task)

    _run(fx.run_async(program))
    assert events == ["request cleanup: Success", "pool closed"]


def test_overlapping_disposal_with_the_exported_context_waits_for_layer_release():
    """overlapping disposal with the exported context waits for layer release

    Effect provides the exported context to the second disposal; here it
    is a root fiber started with that context."""
    events: list[str] = []

    @fx.gen
    def program():
        started = yield from fx.Deferred[None].make()
        release = yield from fx.Deferred[None].make()

        @fx.gen
        def finalizer():
            yield from started.succeed(None)
            yield from release.wait()
            events.append("layer released")

        runtime = fx.ManagedRuntime.make(_finalizer(finalizer))
        context = yield from runtime.context_effect

        first = yield from runtime.dispose_effect.fork(start_immediately=True)
        yield from started.wait()
        second = fx.run_fork(
            runtime.dispose_effect.and_then(
                fx.sync(lambda: events.append("second disposeEffect done"))
            ),
            context=context,
        )
        yield from release.succeed(None)
        yield from first.join()
        yield from second.join()

    fx.testing.run_test(program)
    assert events == ["layer released", "second disposeEffect done"]


def test_a_layer_build_interrupted_by_dispose_can_dispose_the_runtime():
    """a layer build interrupted by dispose can dispose the runtime"""
    cleaned = False

    def clean() -> None:
        nonlocal cleaned
        cleaned = True

    async def main() -> str:
        started = asyncio.Event()

        def start() -> fx.Effect[None]:
            started.set()
            return fx.never

        runtime: fx.ManagedRuntime[_Unit, Any] = fx.ManagedRuntime.make(
            _discard(
                fx.suspend(start).ensuring(
                    fx.suspend(lambda: runtime.dispose_effect.and_then(fx.sync(clean)))
                )
            )
        )
        runtime.run_fork(fx.void)
        await started.wait()
        return await _settles(runtime.dispose_async())

    assert (_run(main()), cleaned) == ("settled", True)


def test_a_layer_finalizer_shared_through_a_memo_map_can_dispose_the_runtime_releasing_it():
    """a layer finalizer shared through a MemoMap can dispose the runtime releasing it"""
    released = False

    def release() -> None:
        nonlocal released
        released = True

    async def main() -> str:
        shared = _finalizer(fx.suspend(lambda: runtime_b.dispose_effect.and_then(fx.sync(release))))
        # runtime_a builds the layer, but runtime_b holds the last reference to it.
        runtime_a = fx.ManagedRuntime.make(shared)
        runtime_b: fx.ManagedRuntime[_Unit, Any] = fx.ManagedRuntime.make(
            shared, memo_map=runtime_a.memo_map
        )
        await runtime_a.run_async_exit(fx.void)
        await runtime_b.run_async_exit(fx.void)
        await runtime_a.dispose_async()
        assert not released
        return await _settles(runtime_b.dispose_async())

    assert _run(main()) == "settled"
    assert released


def test_runtimes_whose_layer_finalizers_dispose_each_other_can_be_disposed():
    """runtimes whose layer finalizers dispose each other can be disposed"""

    async def main() -> str:
        runtime_a: fx.ManagedRuntime[_Unit, Any] = fx.ManagedRuntime.make(
            _discard(fx.add_finalizer(lambda _ex: runtime_b.dispose_effect))
        )
        runtime_b: fx.ManagedRuntime[_Unit, Any] = fx.ManagedRuntime.make(
            _discard(fx.add_finalizer(lambda _ex: runtime_a.dispose_effect))
        )
        await runtime_a.run_async_exit(fx.void)
        await runtime_b.run_async_exit(fx.void)
        return await _settles(runtime_a.dispose_async())

    assert _run(main()) == "settled"


def test_completes_sequential_layer_finalizers_when_dispose_effect_is_interrupted():
    """completes sequential layer finalizers when disposeEffect is interrupted"""
    ran: list[str] = []

    @fx.gen
    def program():
        started = yield from fx.Deferred[None].make()
        release = yield from fx.Deferred[None].make()

        @fx.gen
        def flush_logs():
            yield from started.succeed(None)
            yield from release.wait()
            ran.append("flush logs")

        @fx.gen
        def make_layer():
            scope = yield from fx.Scope()
            yield from scope.add_finalizer(
                lambda _ex: fx.sync(lambda: ran.append("close database"))
            )
            yield from scope.add_finalizer(lambda _ex: flush_logs)

        runtime = fx.ManagedRuntime.make(_discard(make_layer))
        yield from runtime.context_effect

        closing = yield from runtime.dispose_effect.fork(start_immediately=True)
        yield from started.wait()
        # Interrupt from a separate fiber so this fiber can release the finalizer.
        interrupting = yield from closing.interrupt().fork(start_immediately=True)
        yield from release.succeed(None)
        yield from interrupting.join()
        yield from closing.await_exit()
        yield from runtime.dispose_effect

    fx.testing.run_test(program)
    assert ran == ["flush logs", "close database"]
