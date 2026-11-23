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

from collections.abc import Callable, Generator
from typing import Any, Literal

from pyfect._concurrency import Concurrency, race_first
from pyfect._core import Effect, _FailCause, _Gen, _Succeed, _Suspend
from pyfect._fiber import Fiber
from pyfect.cause import Cause
from pyfect.channel._base import AnyChannel, AnyPull, end_with
from pyfect.channel._channel import Channel, from_pull, from_transform
from pyfect.channel._combinators import permits_of
from pyfect.channel._constructors import bracket, from_effect_drain
from pyfect.effect import from_exit, never, yield_now
from pyfect.exit import Failure, as_void_all
from pyfect.exit import interrupt as interrupted
from pyfect.latch import Latch
from pyfect.pull import done_exit_from_cause, filter_done, is_done_cause
from pyfect.queue import Queue, Strategy
from pyfect.queue._queue import _made
from pyfect.result import Ok
from pyfect.scope import CloseableScope, fork_in
from pyfect.semaphore import Semaphore

type Channel_ = Channel[Any, Any, Any, Any, Any, Any, Any]
type HaltStrategy = Literal["left", "right", "both", "either"]
type Capacity = int | Literal["unbounded"]

_VOID: Effect[None] = _Succeed(None)


def _worker_ended(
    cause: Any,
    *,
    child_scope: CloseableScope,
    fiber_box: list[Fiber[Any, Any]],
    fibers: dict[Fiber[Any, Any], CloseableScope],
    queue: Queue[Any, Any],
    permits: Semaphore | None,
    done_latch: Latch,
) -> Generator[Effect[Any, Any, Any], Any]:
    """``merge_all``'s worker ``onError`` handler, Effect's generator op for op."""
    ex = done_exit_from_cause(cause)
    close_exit = yield from child_scope.close(ex).exit()
    fiber = fiber_box[0]
    if fiber not in fibers:
        return
    # Usage and finalizer failures reach the reader before the permit or the
    # latch lets the outer channel end.
    failure = as_void_all([ex, close_exit])
    if isinstance(failure, Failure):
        yield from queue.fail_cause(failure.cause)
    del fibers[fiber]
    if permits is not None:
        yield from permits.release(1)
    if not fibers:
        yield from done_latch.open()


def merge_all(
    channels: AnyChannel, concurrency: Concurrency, buffer_size: int, *, switch: bool
) -> Channel_:
    n = permits_of(concurrency)

    def build(
        upstream: AnyPull, scope: CloseableScope, forked: CloseableScope
    ) -> Effect[AnyPull, Any, Any]:
        # Effect's generator, op for op: the latch and the queue are made as
        # ops, the queue's shutdown added to the forked scope, the loop forked,
        # and the queue's take returned.
        def body() -> Generator[Effect[Any, Any, Any], Any, AnyPull]:
            permits = None if switch else Semaphore(n)
            done_latch: Latch = yield Latch.make(open=True)
            fibers: dict[Fiber[Any, Any], CloseableScope] = {}
            queue: Queue[Any, Any] = yield Queue[Any, Any].bounded(buffer_size)
            yield _Suspend(lambda: forked._add_finalizer_exit(lambda _: queue.shutdown()))
            pull: AnyPull = yield channels._transform(upstream, scope)

            def start(
                channel: AnyChannel,
            ) -> tuple[
                CloseableScope,
                Callable[[AnyPull], Effect[Fiber[Any, Any], Any, Any]],
                list[Fiber[Any, Any]],
            ]:
                child_scope = forked.fork_unsafe()
                fiber_box: list[Fiber[Any, Any]] = []

                def finished(cause: Any) -> Effect[None]:
                    return _Gen(
                        lambda: _worker_ended(
                            cause,
                            child_scope=child_scope,
                            fiber_box=fiber_box,
                            fibers=fibers,
                            queue=queue,
                            permits=permits,
                            done_latch=done_latch,
                        )
                    )

                def worker(child_pull: AnyPull) -> Effect[Fiber[Any, Any], Any, Any]:
                    return (
                        child_pull.tap(lambda _: yield_now())
                        .flat_map(queue.offer)
                        .forever(disable_yield=True)
                        .on_error(finished)
                        .fork()
                    )

                return child_scope, worker, fiber_box

            def stopped(cause: Any) -> Effect[bool]:
                if isinstance(filter_done(cause), Ok):
                    return done_latch.when_open(queue.fail_cause(cause))
                return queue.fail_cause(cause)

            def merging(pull: AnyPull) -> Generator[Effect[Any, Any, Any], Any]:
                # Effect's loop, one generator, op for op.
                while True:
                    pull_fiber: Fiber[Any, Any] | None = None
                    if permits is not None:
                        if len(fibers) < n:
                            yield from permits.take(1)
                        else:
                            pull_fiber = yield from pull.fork()
                            yield from race_first(
                                permits.take(1), pull_fiber.join().and_then(never)
                            )
                    channel: AnyChannel = (
                        (yield from pull) if pull_fiber is None else (yield from pull_fiber.join())
                    )
                    child_scope, worker, fiber_box = start(channel)
                    child_pull: AnyPull = yield from channel._transform(upstream, child_scope)
                    while len(fibers) >= n:
                        fiber, fiber_scope = next(iter(fibers.items()))
                        del fibers[fiber]
                        if not fibers:
                            yield from done_latch.open()
                        yield from fiber.interrupt()
                        # A worker interrupted before it starts never closes its own
                        # scope; failures of replaced workers' finalizers are dropped.
                        yield from fiber_scope.close(interrupted()).ignore_cause()
                    fiber = yield from worker(child_pull)
                    fiber_box.append(fiber)
                    done_latch.close_unsafe()
                    fibers[fiber] = child_scope

            loop = _Gen(lambda: merging(pull))
            yield fork_in(loop.catch_cause(stopped), forked)
            return queue.take()

        return _Gen(body)

    return bracket(build)


def merge(left: AnyChannel, right: AnyChannel, halt_strategy: HaltStrategy) -> Channel_:
    # Effect's ``Channel.merge``, op for op: one generator making the queue,
    # adding its shutdown to the forked scope and forking both sides.
    def build(
        upstream: AnyPull, _scope: CloseableScope, forked: CloseableScope
    ) -> Effect[AnyPull, Any, Any]:
        def body() -> Generator[Effect[Any, Any, Any], Any, AnyPull]:
            queue: Queue[Any, Any] = yield Queue[Any, Any].bounded(0)
            yield _Suspend(lambda: forked._add_finalizer_exit(lambda _: queue.shutdown()))
            done = 0

            def on_exit(side: str, cause: Cause[Any]) -> Effect[object]:
                nonlocal done
                done += 1
                if not is_done_cause(cause):
                    return queue.fail_cause(cause)
                halts = done == 2 if halt_strategy == "both" else halt_strategy in ("either", side)
                return queue.fail_cause(cause) if halts else _VOID

            def run_side(side: str, channel: AnyChannel, side_scope: CloseableScope) -> Effect[Any]:
                def stopped(cause: Any) -> Effect[object]:
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
                return fork_in(run, forked, start_immediately=True)

            yield run_side("left", left, forked.fork_unsafe())
            yield run_side("right", right, forked.fork_unsafe())
            return queue.take()

        return _Gen(body)

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
                    ex = fiber.poll_unsafe()
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
    # Effect's generator, op for op: the pull, the queue (``Queue.make``), its
    # shutdown added to the scope, the producer forked, the queue's take
    # returned.
    def transform(upstream: AnyPull, scope: CloseableScope) -> Effect[AnyPull, Any, Any]:
        def body() -> Generator[Effect[Any, Any, Any], Any, AnyPull]:
            pull: AnyPull = yield self._transform(upstream, scope)
            queue: Queue[Any, Any] = yield _made(lambda: _make_queue(capacity, strategy))
            yield _Suspend(lambda: scope._add_finalizer_exit(lambda _: queue.shutdown()))
            offer: Callable[[Any], Effect[Any]] = queue.offer_all if array else queue.offer
            run = pull.flat_map(offer).forever(disable_yield=True).on_error(queue.fail_cause)
            yield fork_in(run, scope)
            return queue._take_chunk() if array else queue.take()

        return _Gen(body)

    return from_transform(transform)


def embed_input(self: AnyChannel, input: Callable[[AnyPull], Effect[Any, Any, Any]]) -> Channel_:
    def build(
        upstream: AnyPull, scope: CloseableScope, forked: CloseableScope
    ) -> Effect[AnyPull, Any, Any]:
        return fork_in(input(upstream), forked).and_then(self._transform(end_with(None), scope))

    return bracket(build)
