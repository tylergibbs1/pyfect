"""``map_effect`` with ``concurrency`` above 1 (Effect's
``mapEffectConcurrent``).

A producer fiber pulls upstream and forks ``f(item)`` for each item, at
most ``concurrency`` at a time; results go through a rendezvous queue to
the channel's pull. In order, the producer queues each fiber's ``join``
and a consumer fiber hands the results on in that order; unordered, each
fiber offers its own result. Every fiber lives in the channel's forked
scope, so ending the channel interrupts what is still running.
"""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from collections.abc import Callable, Generator
from typing import Any

from pyfect._concurrency import Concurrency
from pyfect._core import Effect, _FailCause, _Gen, _Succeed, _Suspend, _WithFiber
from pyfect._fiber import Fiber
from pyfect._fiber_collections import CapturedRuntime
from pyfect.cause import Cause
from pyfect.channel._base import AnyChannel, AnyPull
from pyfect.channel._channel import Channel
from pyfect.channel._combinators import UNBOUNDED, permits_of
from pyfect.channel._constructors import bracket
from pyfect.exit import Exit, Failure
from pyfect.queue import Queue
from pyfect.scope import CloseableScope, fork_in
from pyfect.semaphore import Semaphore

_VOID: Effect[None] = _Succeed(None)
# Effect's ``Queue.bounded(MAX_SAFE_INTEGER - 2)`` for unbounded concurrency.
_UNBOUNDED_JOINS = 2**53 - 3


def map_effect_concurrent(
    self: AnyChannel,
    f: Callable[[Any], Effect[Any, Any, Any]],
    concurrency: Concurrency,
    *,
    unordered: bool,
) -> Channel[Any, Any, Any, Any, Any, Any, Any]:
    n = permits_of(concurrency)

    # Effect's ``mapEffectConcurrent``, op for op: one generator; each
    # ``f(item)`` runs on a root fiber started at once (``runForkWith``)
    # and tied to the forked scope (``Fiber.runIn``).
    def build(
        upstream: AnyPull, scope: CloseableScope, forked: CloseableScope
    ) -> Effect[AnyPull, Any, Any]:
        def body() -> Generator[Effect[Any, Any, Any], Any, AnyPull]:
            pull: AnyPull = yield self._transform(upstream, scope)
            results: Queue[Any, Any] = yield Queue[Any, Any].bounded(0)
            yield _Suspend(lambda: forked._add_finalizer_exit(lambda _: results.shutdown()))
            runtime: CapturedRuntime = yield _WithFiber(
                lambda fiber: _Succeed(CapturedRuntime(fiber))
            )

            def run_fork(eff: Effect[Any, Any, Any]) -> Fiber[Any, Any]:
                fiber = runtime.fork(eff, uninterruptible=False, scheduler=None)
                return fiber.run_in(forked)

            if unordered:
                yield unordered_producer(pull, results, forked, run_fork)
            else:
                yield from ordered_producer(pull, results, forked, run_fork)
            return results.take()

        return _Gen(body)

    def unordered_producer(
        pull: AnyPull,
        results: Queue[Any, Any],
        forked: CloseableScope,
        run_fork: Callable[[Effect[Any, Any, Any]], Any],
    ) -> Effect[Any]:
        permits = Semaphore(n)
        release = permits.release(1)

        def handle(eff: Effect[Any, Any, Any]) -> Effect[Any]:
            return eff.match_cause_effect(
                on_failure=lambda cause: results.fail_cause(cause).flat_map(lambda _: release),
                on_success=lambda value: results.offer(value).flat_map(lambda _: release),
            )

        def run(item: Any) -> Effect[None]:
            run_fork(handle(_Suspend(lambda: f(item))))
            return _VOID

        loop = permits.take(1).flat_map(lambda _: pull).flat_map(run).forever(disable_yield=True)
        stopped = loop.catch_cause(
            lambda cause: permits.with_permits(results.fail_cause(cause), n - 1)
        )
        return fork_in(stopped, forked)

    def ordered_producer(
        pull: AnyPull,
        results: Queue[Any, Any],
        forked: CloseableScope,
        run_fork: Callable[[Effect[Any, Any, Any]], Any],
    ) -> Generator[Effect[Any, Any, Any], Any]:
        # Room for n - 2 joins: one more waits in the offer after its fiber
        # starts, and the consumer holds the one it is joining.
        joins: Queue[Effect[Any, Any, Any], Any] = yield Queue[Effect[Any, Any, Any], Any].bounded(
            _UNBOUNDED_JOINS if n == UNBOUNDED else max(0, n - 2)
        )
        yield _Suspend(lambda: forked._add_finalizer_exit(lambda _: joins.shutdown()))
        consumer = (
            joins.take()
            .flatten()
            .flat_map(results.offer)
            .forever(disable_yield=True)
            .catch_cause(results.fail_cause)
        )
        yield fork_in(consumer, forked)
        failed: list[Cause[Any]] = []

        def on_exit(ex: Exit[Any, Any]) -> None:
            if isinstance(ex, Failure):
                failed.append(ex.cause)
                results.fail_cause_unsafe(ex.cause)

        def run(item: Any) -> Effect[Any, Any, Any]:
            if failed:
                return _FailCause(failed[0])
            fiber: Fiber[Any, Any] = run_fork(_Suspend(lambda: f(item)))
            fiber.add_observer_unsafe(on_exit)
            return joins.offer(fiber.join())

        producer = (
            pull.flat_map(run)
            .forever(disable_yield=True)
            .catch_cause(
                lambda cause: joins.offer(_FailCause(cause)).flat_map(
                    lambda _: joins.fail_cause(cause)
                )
            )
        )
        yield fork_in(producer, forked)

    return bracket(build)
