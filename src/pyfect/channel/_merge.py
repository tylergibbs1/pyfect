"""Channels that run other channels on fibers: ``merge_all`` (behind
concurrent ``flat_map`` and ``switch_map``), ``merge`` and its
``merge_effect`` / ``interrupt_when`` forms, ``halt_when``, ``buffer``
and ``embed_input``.

Every fiber lives in the channel's forked scope, closed as soon as the
channel fails or ends, so a merged channel never outlives its reader.
Items reach the reader through a queue that shuts down with that scope.
"""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Literal

from pyfect._concurrency import Concurrency, race_first
from pyfect._core import Effect, _FailCause, _Succeed, _Suspend
from pyfect._fiber import Fiber
from pyfect.cause import Cause
from pyfect.channel._base import AnyChannel, AnyPull, end_with
from pyfect.channel._channel import Channel, from_pull, from_transform
from pyfect.channel._combinators import permits_of
from pyfect.channel._constructors import bracket, from_effect_drain
from pyfect.effect import from_exit, never, yield_now
from pyfect.exit import Exit, Failure, as_void_all
from pyfect.exit import interrupt as interrupted
from pyfect.latch import Latch
from pyfect.pull import done_exit_from_cause, filter_done, is_done_cause
from pyfect.queue import Queue, Strategy
from pyfect.result import Ok
from pyfect.scope import CloseableScope, fork_in
from pyfect.semaphore import Semaphore

type Channel_ = Channel[Any, Any, Any, Any, Any, Any, Any]
type HaltStrategy = Literal["left", "right", "both", "either"]
type Capacity = int | Literal["unbounded"]

_VOID: Effect[None] = _Succeed(None)


def merge_all(
    channels: AnyChannel, concurrency: Concurrency, buffer_size: int, *, switch: bool
) -> Channel_:
    n = permits_of(concurrency)

    def build(
        upstream: AnyPull, scope: CloseableScope, forked: CloseableScope
    ) -> Effect[AnyPull, Any, Any]:
        permits = None if switch else Semaphore(n)
        done_latch = Latch(open=True)
        fibers: dict[Fiber[Any, Any], CloseableScope] = {}
        queue: Queue[Any, Any] = Queue(buffer_size)

        def next_channel(pull: AnyPull) -> Effect[Any, Any, Any]:
            if permits is None:
                return pull
            take = permits.take(1)
            if len(fibers) < n:
                return take.and_then(pull)

            def raced(fiber: Fiber[Any, Any]) -> Effect[Any, Any, Any]:
                return race_first(take, fiber.join().and_then(never)).and_then(fiber.join())

            return pull.fork().flat_map(raced)

        def evict() -> Effect[None]:
            if len(fibers) < n:
                return _VOID
            fiber, fiber_scope = next(iter(fibers.items()))
            del fibers[fiber]
            if not fibers:
                done_latch.unsafe_open()
            # A worker interrupted before it starts never closes its own
            # scope; failures of replaced workers' finalizers are dropped.
            closed = fiber_scope.close(interrupted()).ignore_cause()
            return fiber.interrupt().and_then(closed).and_then(_Suspend(evict))

        def start(channel: AnyChannel) -> Effect[None, Any, Any]:
            child_scope = forked._fork_now()
            fiber_box: list[Fiber[Any, Any]] = []

            def finished(cause: Any) -> Effect[None]:
                ex = done_exit_from_cause(cause)

                def after_close(close_exit: Exit[Any, Any]) -> Effect[None]:
                    fiber = fiber_box[0]
                    if fiber not in fibers:
                        return _VOID
                    failure = as_void_all([ex, close_exit])
                    report = (
                        queue.fail_cause(failure.cause).as_void()
                        if isinstance(failure, Failure)
                        else _VOID
                    )

                    def release() -> Effect[None]:
                        del fibers[fiber]
                        freed = _VOID if permits is None else permits.release(1).as_void()
                        if not fibers:
                            done_latch.unsafe_open()
                        return freed

                    return report.and_then(_Suspend(release))

                return child_scope.close(ex).exit().flat_map(after_close)

            def run(child_pull: AnyPull) -> Effect[None, Any, Any]:
                worker = (
                    child_pull.tap(lambda _: yield_now())
                    .flat_map(queue.offer)
                    .forever()
                    .on_error(finished)
                )

                def started(fiber: Fiber[Any, Any]) -> None:
                    fiber_box.append(fiber)
                    done_latch.unsafe_close()
                    fibers[fiber] = child_scope

                return evict().and_then(worker.fork()).map(started)

            return channel._transform(upstream, child_scope).flat_map(run)

        def stopped(cause: Any) -> Effect[None]:
            if isinstance(filter_done(cause), Ok):
                return done_latch.when_open(queue.fail_cause(cause)).as_void()
            return queue.fail_cause(cause).as_void()

        def with_pull(pull: AnyPull) -> Effect[AnyPull, Any, Any]:
            loop = _Suspend(lambda: next_channel(pull)).flat_map(start).forever()
            return fork_in(loop.catch_cause(stopped), forked).as_(queue.take())

        return (
            forked.add_finalizer(lambda _: queue.shutdown())
            .and_then(channels._transform(upstream, scope))
            .flat_map(with_pull)
        )

    return bracket(build)


def merge(left: AnyChannel, right: AnyChannel, halt_strategy: HaltStrategy) -> Channel_:
    def build(
        upstream: AnyPull, _scope: CloseableScope, forked: CloseableScope
    ) -> Effect[AnyPull, Any, Any]:
        queue: Queue[Any, Any] = Queue(0)
        done = 0

        def on_exit(side: str, cause: Cause[Any]) -> Effect[None]:
            nonlocal done
            done += 1
            if not is_done_cause(cause):
                return queue.fail_cause(cause).as_void()
            halts = done == 2 if halt_strategy == "both" else halt_strategy in ("either", side)
            return queue.fail_cause(cause).as_void() if halts else _VOID

        def run_side(side: str, channel: AnyChannel) -> Effect[Any]:
            side_scope = forked._fork_now()

            def stopped(cause: Any) -> Effect[None]:
                # A failure beside the side's Done (a finalizer's defect)
                # fails the merge, with any failure closing the scope adds.
                ex = done_exit_from_cause(cause)
                closed = from_exit(ex).on_exit(lambda _: side_scope.close(ex))
                return closed.match_cause_effect(
                    on_failure=lambda close_cause: on_exit(side, close_cause),
                    on_success=lambda _: on_exit(side, cause),
                )

            run = (
                channel._transform(upstream, side_scope)
                .flat_map(lambda pull: pull.flat_map(queue.offer).forever())
                .on_error(stopped)
            )
            return fork_in(run, forked)

        return (
            forked.add_finalizer(lambda _: queue.shutdown())
            .and_then(run_side("left", left))
            .and_then(run_side("right", right))
            .as_(queue.take())
        )

    return bracket(build)


def merge_effect(self: AnyChannel, eff: Effect[Any, Any, Any]) -> Channel_:
    return merge(self, from_effect_drain(eff), "left")


def interrupt_when(self: AnyChannel, eff: Effect[Any, Any, Any]) -> Channel_:
    return merge(self, from_pull(_Succeed(eff.flat_map(end_with))), "either")


def halt_when(self: AnyChannel, eff: Effect[Any, Any, Any]) -> Channel_:
    def build(
        upstream: AnyPull, scope: CloseableScope, forked: CloseableScope
    ) -> Effect[AnyPull, Any, Any]:
        def with_pull(pull: AnyPull) -> Effect[AnyPull]:
            def watch(fiber: Fiber[Any, Any]) -> AnyPull:
                def next_pull() -> AnyPull:
                    ex = fiber.unsafe_poll()
                    if ex is None:
                        return pull
                    return _FailCause(ex.cause) if isinstance(ex, Failure) else end_with(ex.value)

                return _Suspend(next_pull)

            return fork_in(eff, forked, start_immediately=True).map(watch)

        return self._transform(upstream, scope).flat_map(with_pull)

    return bracket(build)


def _make_queue(capacity: Capacity, strategy: Strategy) -> Queue[Any, Any]:
    return Queue(None) if capacity == "unbounded" else Queue(capacity, strategy)


def buffer(self: AnyChannel, capacity: Capacity, strategy: Strategy, *, array: bool) -> Channel_:
    def transform(upstream: AnyPull, scope: CloseableScope) -> Effect[AnyPull, Any, Any]:
        queue = _make_queue(capacity, strategy)
        offer: Callable[[Any], Effect[Any]] = queue.offer_all if array else queue.offer

        def with_pull(pull: AnyPull) -> Effect[AnyPull]:
            run = pull.flat_map(offer).forever().on_error(queue.fail_cause)
            take = queue.take_all().map(tuple) if array else queue.take()
            return fork_in(run, scope).as_(take)

        return (
            scope.add_finalizer(lambda _: queue.shutdown())
            .and_then(self._transform(upstream, scope))
            .flat_map(with_pull)
        )

    return from_transform(transform)


def embed_input(self: AnyChannel, input: Callable[[AnyPull], Effect[Any, Any, Any]]) -> Channel_:
    def build(
        upstream: AnyPull, scope: CloseableScope, forked: CloseableScope
    ) -> Effect[AnyPull, Any, Any]:
        return fork_in(input(upstream), forked).and_then(self._transform(end_with(None), scope))

    return bracket(build)
