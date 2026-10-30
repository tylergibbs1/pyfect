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

from collections.abc import Callable
from typing import Any

from pyfect._concurrency import Concurrency
from pyfect._core import Effect, _FailCause, _Suspend
from pyfect._fiber import Fiber
from pyfect.cause import Cause
from pyfect.channel._base import AnyChannel, AnyPull
from pyfect.channel._channel import Channel
from pyfect.channel._combinators import UNBOUNDED, permits_of
from pyfect.channel._constructors import bracket
from pyfect.exit import Exit, Failure
from pyfect.queue import Queue
from pyfect.scope import CloseableScope, fork_in
from pyfect.semaphore import Semaphore


def map_effect_concurrent(
    self: AnyChannel,
    f: Callable[[Any], Effect[Any, Any, Any]],
    concurrency: Concurrency,
    *,
    unordered: bool,
) -> Channel[Any, Any, Any, Any, Any, Any, Any]:
    n = permits_of(concurrency)

    def build(
        upstream: AnyPull, scope: CloseableScope, forked: CloseableScope
    ) -> Effect[AnyPull, Any, Any]:
        def with_pull(pull: AnyPull) -> Effect[AnyPull, Any, Any]:
            results: Queue[Any, Any] = Queue(0)
            start = unordered_producer if unordered else ordered_producer
            return (
                forked.add_finalizer(lambda _: results.shutdown())
                .and_then(start(pull, results))
                .as_(results.take())
            )

        def unordered_producer(pull: AnyPull, results: Queue[Any, Any]) -> Effect[Any]:
            permits = Semaphore(n)
            release = permits.release(1)

            def run(item: Any) -> Effect[Any]:
                handled = (
                    _Suspend(lambda: f(item))
                    .match_cause_effect(on_failure=results.fail_cause, on_success=results.offer)
                    .and_then(release)
                )
                return fork_in(handled, forked, start_immediately=True).as_void()

            loop = permits.take(1).and_then(pull).flat_map(run).forever()
            stopped = loop.catch_cause(
                lambda cause: permits.with_permits(results.fail_cause(cause), n - 1)
            )
            return fork_in(stopped, forked)

        def ordered_producer(pull: AnyPull, results: Queue[Any, Any]) -> Effect[Any]:
            # Room for n - 2 joins: one more waits in the offer after its
            # fiber starts, and the consumer holds the one it is joining.
            joins: Queue[Effect[Any, Any, Any], Any] = Queue(
                None if n == UNBOUNDED else max(0, n - 2)
            )
            failed: list[Cause[Any]] = []

            def on_exit(ex: Exit[Any, Any]) -> None:
                if isinstance(ex, Failure):
                    failed.append(ex.cause)
                    results.fail_cause_unsafe(ex.cause)

            def run(item: Any) -> Effect[Any, Any, Any]:
                if failed:
                    return _FailCause(failed[0])

                def started(fiber: Fiber[Any, Any]) -> Effect[Any]:
                    fiber.add_observer_unsafe(on_exit)
                    return joins.offer(fiber.join())

                return fork_in(_Suspend(lambda: f(item)), forked, start_immediately=True).flat_map(
                    started
                )

            consumer = (
                joins.take()
                .flatten()
                .flat_map(results.offer)
                .forever()
                .catch_cause(results.fail_cause)
            )
            producer = (
                pull.flat_map(run)
                .forever()
                .catch_cause(
                    lambda cause: joins.offer(_FailCause(cause)).and_then(joins.fail_cause(cause))
                )
            )
            return (
                forked.add_finalizer(lambda _: joins.shutdown())
                .and_then(fork_in(consumer, forked))
                .and_then(fork_in(producer, forked))
            )

        return self._transform(upstream, scope).flat_map(with_pull)

    return bracket(build)
