"""Ports of the runtime cases of Effect's ``Effect.test.ts``: the run
functions.

Each test's docstring is the Effect test title. ``runFork`` is
``run_fork``, ``runPromise`` is ``run_async``, ``fiber.interruptUnsafe()``
is ``fiber.unsafe_interrupt_as(None)``. Durations are seconds.

Omitted:

- "callback can branch over sync/async": pyfect's ``callback`` has no
  ``executionMode``; ``run_sync`` drives asynchronous effects to the end.
- "terminal root failure captures stack frame", "failure without a current
  frame has no stack annotation and reuses the original exit": ported with
  the other ``tracing`` titles in ``tests/oracle/test_effect_fn.py``.
"""

import asyncio

import pyfect as fx
from pyfect.cause import Interrupt


class _Flags:
    def __init__(self) -> None:
        self.acquire = False
        self.use = False
        self.release = False


def _acquire_use_release(flags: _Flags) -> fx.Effect[int]:
    def acquire() -> int:
        flags.acquire = True
        return 123

    def use(n: int) -> fx.Effect[int]:
        def body() -> int:
            flags.use = True
            return n

        return fx.sync(body)

    def release(n: int, _ex: fx.Exit[int, object]) -> fx.Effect[None]:
        def body() -> None:
            assert n == 123
            flags.release = True

        return fx.sync(body)

    return fx.acquire_use_release(fx.sync(acquire).delay(0.1), use, release)


def test_run_promise():
    """runPromise"""
    assert asyncio.run(fx.run_async(fx.succeed(1))) == 1


def test_acquire_use_release_interrupt():
    """acquireUseRelease interrupt"""
    flags = _Flags()

    async def main() -> fx.Exit[int, object]:
        fiber = fx.run_fork(_acquire_use_release(flags))
        fiber.unsafe_interrupt_as(None)
        return await fx.run_async(fiber.await_exit())

    ex = asyncio.run(main())
    assert isinstance(ex, fx.Failure)
    assert ex.cause.reasons == (Interrupt(None),)
    assert (flags.acquire, flags.use, flags.release) == (True, False, True)


def test_acquire_use_release_uninterruptible():
    """acquireUseRelease uninterruptible"""
    flags = _Flags()

    async def main() -> fx.Exit[int, object]:
        fiber = fx.run_fork(_acquire_use_release(flags).uninterruptible())
        fiber.unsafe_interrupt_as(None)
        return await fx.run_async(fiber.await_exit())

    ex = asyncio.run(main())
    assert isinstance(ex, fx.Failure)
    assert ex.cause.reasons == (Interrupt(None),)
    assert (flags.acquire, flags.use, flags.release) == (True, True, True)
