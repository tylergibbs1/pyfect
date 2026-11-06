"""Ports of the ``AsyncLocalStorage`` titles of Effect's ``Effect.test.ts``.

Node's ``AsyncLocalStorage`` is Python's ``contextvars``: a fiber that
parked resumes in the context it parked in (Effect's fiber captures the
async context when it yields and resumes in it), not in the context of the
fiber or thread that woke it. Each title runs with a waiter that has no
value of its own and with one that sets its own.

Omitted: "does not leave async resources open after the effect completes"
(Node's ``async_hooks`` resource tracking has no Python counterpart; a
captured ``contextvars.Context`` is a plain object).
"""

import asyncio
import contextvars
from typing import Any

import pytest

import pyfect as fx

store: contextvars.ContextVar[str] = contextvars.ContextVar("store", default="none")


@fx.gen
def observe():
    resumed = store.get()

    async def read() -> str:
        return store.get()

    promise = yield from fx.from_async(read)
    yield from fx.sleep(0.001)
    after_sleep = store.get()
    return {"resumed": resumed, "promise": promise, "after_sleep": after_sleep}


def expected(value: str) -> dict[str, str]:
    return {"resumed": value, "promise": value, "after_sleep": value}


async def run_with_store[A](value: str | None, eff: fx.Effect[A, Any]) -> A:
    """Run ``eff`` in a task of its own, with ``store`` set to ``value``."""

    async def inner() -> A:
        if value is not None:
            store.set(value)
        return await fx.run_async(eff)

    return await asyncio.create_task(inner())


@pytest.mark.parametrize(
    "waiter_store", [None, "waiter"], ids=["without a store", "with its own store"]
)
def test_deferred_await_resumes_in_the_awaiters_context(waiter_store: str | None) -> None:
    """Deferred.await resumes in the awaiter's context"""

    async def main() -> None:
        deferred = fx.run_blocking(fx.Deferred[None].make())
        waiter = asyncio.create_task(
            run_with_store(waiter_store, deferred.wait().and_then(observe))
        )
        completer = await run_with_store(
            "waker",
            fx.sleep(0.005).and_then(deferred.succeed(None)).and_then(fx.sync(store.get)),
        )
        assert completer == "waker"
        assert await waiter == expected(waiter_store or "none")

    asyncio.run(main())


@pytest.mark.parametrize(
    "waiter_store", [None, "waiter"], ids=["without a store", "with its own store"]
)
def test_pool_get_resumes_in_the_waiters_context(waiter_store: str | None) -> None:
    """Pool.get resumes in the waiter's context"""

    async def main() -> None:
        scope = fx.CloseableScope()
        try:
            pool = await fx.run_async(
                fx.Pool.make(fx.succeed("conn"), size=1)
                .tap(lambda p: fx.scoped(p.get()))
                .pipe(fx.provide_service(fx.Scope, scope))
            )
            holder_acquired = fx.run_blocking(fx.Deferred[str].make())
            holder = asyncio.create_task(
                run_with_store(
                    "waker",
                    fx.scoped(
                        pool.get()
                        .and_then(fx.sync(store.get))
                        .tap(holder_acquired.succeed)
                        .and_then(fx.sleep(0.01))
                        .and_then(fx.sync(store.get))
                    ),
                )
            )
            assert await fx.run_async(holder_acquired.wait()) == "waker"
            waiter = asyncio.create_task(
                run_with_store(waiter_store, fx.scoped(pool.get()).and_then(observe))
            )
            assert await holder == "waker"
            assert await waiter == expected(waiter_store or "none")
        finally:
            await fx.run_async(scope.close(fx.exit.void))

    asyncio.run(main())


def test_a_value_the_fiber_sets_survives_its_suspensions() -> None:
    """pyfect: a fiber's own ``set`` is kept across a park and resume."""

    @fx.gen
    def program():
        yield from fx.sync(lambda: store.set("mine"))
        yield from fx.sleep(0.001)
        return store.get()

    async def main() -> str:
        return await run_with_store(None, program)

    assert asyncio.run(main()) == "mine"
