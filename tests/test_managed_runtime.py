"""ManagedRuntime beyond Effect's tests: sync use, context managers, and
the per-request pattern of a web server's lifespan."""

import asyncio
import sys
import threading
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Never

import pytest

import pyfect as fx
from pyfect import layer


class Name(fx.Tag[str]): ...


class Ticks(fx.Tag[fx.Ref[int]]): ...


@dataclass
class ConfigMissing(fx.TaggedError):
    key: str


def tracked(log: list[str]) -> layer.Layer[Name]:
    return layer.effect(
        Name,
        fx.acquire_release(
            fx.sync(lambda: log.append("acquire") or "svc"),
            lambda _n, _ex: fx.sync(lambda: log.append("release")),
        ),
    )


def test_sync_context_manager_builds_on_enter_and_releases_on_exit():
    log: list[str] = []
    with fx.ManagedRuntime.make(tracked(log)) as runtime:
        assert log == ["acquire"]
        assert runtime.run_sync(Name()) == "svc"
        assert runtime.run_sync(Name().map(str.upper)) == "SVC"
    assert log == ["acquire", "release"]


def test_a_failing_build_on_enter_raises_and_releases_what_was_built():
    log: list[str] = []
    acquired = fx.acquire_release(
        fx.sync(lambda: log.append("acquire") or "svc"),
        lambda _n, _ex: fx.sync(lambda: log.append("release")),
    )
    broken = layer.effect(Name, acquired.and_then(fx.fail(ConfigMissing("url"))))
    with pytest.raises(ConfigMissing), fx.ManagedRuntime.make(broken):
        pytest.fail("unreachable")
    assert log == ["acquire", "release"]


def test_runs_after_dispose_die():
    runtime = fx.ManagedRuntime.make(layer.succeed(Name, "x"))
    assert runtime.run_sync(Name()) == "x"
    runtime.dispose()
    ex = runtime.run_sync_exit(Name())
    assert isinstance(ex, fx.Failure)
    assert "ManagedRuntime disposed" in ex.cause.pretty()


def test_dispose_twice_is_a_no_op():
    log: list[str] = []
    runtime = fx.ManagedRuntime.make(tracked(log))
    runtime.run_sync(fx.void)
    runtime.dispose()
    runtime.dispose()
    assert log == ["acquire", "release"]


def test_fibers_the_layer_forked_keep_running_across_sync_runs():
    @fx.gen
    def ticking():
        ticks = yield from fx.Ref.make(0)
        yield from ticks.update(lambda n: n + 1).and_then(fx.sleep(0.001)).forever().fork_scoped()
        return ticks

    with fx.ManagedRuntime.make(layer.effect(Ticks, ticking)) as runtime:
        first = runtime.run_sync(Ticks().flat_map(lambda t: t.get()))
        runtime.run_sync(fx.sleep(0.02))
        second = runtime.run_sync(Ticks().flat_map(lambda t: t.get()))
    assert second > first


def test_sync_runs_from_several_threads_share_one_build():
    builds: list[str] = []
    runtime = fx.ManagedRuntime.make(tracked(builds))
    results: list[str] = []

    def request() -> None:
        results.append(runtime.run_sync(fx.sleep(0.001).and_then(Name())))

    threads = [threading.Thread(target=request) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    runtime.dispose()
    assert results == ["svc"] * 8
    assert builds == ["acquire", "release"]


def test_a_sync_run_and_a_loop_on_another_thread_first_using_it_share_one_build(
    fast_thread_switches: None,
):
    """The build is claimed under a lock: two threads using the runtime for
    the first time at once (a sync run here, an asyncio loop there) used to
    build the layer twice, about once in 30 tries with frequent thread
    switches."""
    for _ in range(200):
        log: list[str] = []
        runtime = fx.ManagedRuntime.make(tracked(log))
        assert _first_used_from_two_threads(runtime) == ["svc", "svc"]
        assert log == ["acquire", "release"]


def _first_used_from_two_threads(runtime: fx.ManagedRuntime[Name]) -> list[object]:
    """A loop thread and this thread run on ``runtime`` at the same moment;
    then it is disposed."""
    results: list[object] = []
    go = threading.Barrier(2)

    async def main() -> None:
        go.wait()
        results.append(await asyncio.wait_for(runtime.run_async(Name()), 5))

    thread = threading.Thread(target=lambda: asyncio.run(main()))
    thread.start()
    go.wait()
    results.append(runtime.run_sync(Name()))
    thread.join(10)
    runtime.dispose()
    return results


@pytest.fixture
def fast_thread_switches() -> Iterator[None]:
    previous = sys.getswitchinterval()
    sys.setswitchinterval(1e-6)
    try:
        yield
    finally:
        sys.setswitchinterval(previous)


def test_lifespan_and_per_request_runs():
    """The FastAPI pattern: enter in the lifespan, run each request, and a
    cancelled request (client gone) interrupts its effect."""
    log: list[str] = []

    async def main() -> None:
        async with fx.ManagedRuntime.make(tracked(log)) as runtime:
            assert await runtime.run_async(Name()) == "svc"
            slow = asyncio.ensure_future(
                runtime.run_async(fx.never.on_interrupt(fx.sync(lambda: log.append("cancelled"))))
            )
            await asyncio.sleep(0.01)
            slow.cancel()
            with pytest.raises(asyncio.CancelledError):
                await slow
            assert (await runtime.context()) is not None

    asyncio.run(main())
    assert log == ["acquire", "cancelled", "release"]


def test_run_callback_on_a_runtime():
    async def main() -> list[fx.Exit[str, Never]]:
        exits: list[fx.Exit[str, Never]] = []
        async with fx.ManagedRuntime.make(layer.succeed(Name, "x")) as runtime:
            runtime.run_callback(Name(), on_exit=exits.append)
            await asyncio.sleep(0.01)
        return exits

    assert asyncio.run(main()) == [fx.Success("x")]


def _within[T](seconds: float, f: Callable[[], T]) -> T:
    """``f()`` on a daemon thread, failing the test (not hanging the suite)
    if it has not returned within ``seconds``."""
    out: list[T] = []
    errors: list[BaseException] = []

    def target() -> None:
        try:
            out.append(f())
        except BaseException as e:
            errors.append(e)

    thread = threading.Thread(target=target, daemon=True)
    thread.start()
    thread.join(seconds)
    if thread.is_alive():
        pytest.fail(f"still running after {seconds}s")
    if errors:
        raise errors[0]
    return out[0]


def test_a_sync_run_inside_a_sync_run_of_the_same_runtime_completes():
    """Driving the runtime's scheduler from inside one of its fibers would
    stall that fiber's run, so a nested sync run gets a scheduler of its own."""
    runtime = fx.ManagedRuntime.make(layer.succeed(Name, "x"))
    inner = fx.sleep(0.001).and_then(Name())
    outer = fx.sync(lambda: runtime.run_sync(inner)).flat_map(
        lambda a: fx.sleep(0.001).as_(a + "!")
    )
    assert _within(5, lambda: runtime.run_sync(outer)) == "x!"
    runtime.dispose()


def test_blocking_dispose_on_a_running_loop_raises():
    """A blocking dispose on the loop's thread could never see the loop's
    fibers finish, so it raises rather than hang."""

    async def main() -> None:
        runtime = fx.ManagedRuntime.make(layer.succeed(Name, "x"))
        fiber = runtime.run_fork(fx.never)
        with pytest.raises(RuntimeError, match="dispose_async"):
            runtime.dispose()
        with pytest.raises(RuntimeError, match="async with"), runtime:
            pytest.fail("unreachable")
        await runtime.dispose_async()
        assert isinstance(fiber.poll_unsafe(), fx.Failure)

    _within(5, lambda: asyncio.run(main()))


def test_blocking_dispose_inside_a_fiber_raises():
    """Inside a fiber, blocking would stall the fiber's own run (and a
    request would wait for itself): use ``dispose_effect`` there."""
    runtime = fx.ManagedRuntime.make(layer.succeed(Name, "x"))
    ex = _within(5, lambda: runtime.run_sync_exit(fx.sync(runtime.dispose)))
    assert isinstance(ex, fx.Failure)
    assert "dispose_effect" in ex.cause.pretty()
    runtime.dispose()


def test_interrupting_a_call_waiting_for_a_disposal_only_stops_the_wait():
    """Effect's ``disposeEffect`` docs: a call made while a disposal runs
    waits for it, and interrupting that call only stops the wait."""
    events: list[str] = []

    @fx.gen
    def program():
        started = yield from fx.Deferred[None].make()
        release = yield from fx.Deferred[None].make()

        @fx.gen
        def slow_release():
            yield from started.succeed(None)
            yield from release.wait()
            events.append("layer released")

        runtime = fx.ManagedRuntime.make(
            layer.effect(Name, fx.add_finalizer(lambda _ex: slow_release).as_("x"))
        )
        yield from runtime.context_effect
        first = yield from runtime.dispose_effect.fork(start_immediately=True)
        yield from started.wait()
        waiting = yield from runtime.dispose_effect.fork(start_immediately=True)
        yield from waiting.interrupt()
        ex = yield from waiting.await_exit()
        events.append("wait interrupted" if isinstance(ex, fx.Failure) else "wait finished")
        yield from release.succeed(None)
        yield from first.join()

    fx.testing.run_test(program)
    assert events == ["wait interrupted", "layer released"]


def test_first_runs_racing_on_a_loop_and_a_sync_thread_build_the_layer_once():
    builds: list[str] = []

    def build() -> str:
        builds.append("build")
        time.sleep(0.1)  # widen the window between checking and starting the build
        return "svc"

    runtime = fx.ManagedRuntime.make(layer.effect(Name, fx.sync(build)))
    results: list[str] = []
    on_loop = threading.Thread(
        target=lambda: results.append(asyncio.run(runtime.run_async(Name())))
    )
    on_loop.start()
    results.append(runtime.run_sync(Name()))
    on_loop.join()
    runtime.dispose()
    assert (builds, results) == (["build"], ["svc", "svc"])
