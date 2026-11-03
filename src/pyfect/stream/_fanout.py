"""The work behind ``Stream``'s ``partition`` family, ``broadcast``,
``broadcast_n`` and ``share``: one upstream run feeding several readers.

The partitions run the upstream on a fiber in the caller's scope, writing
into two queues; the broadcasts publish its chunks to a pubsub of
``Take`` values that every reader subscribes to.
"""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from collections.abc import Callable, Generator
from typing import Any, Literal

from pyfect import channel
from pyfect._concurrency import Concurrency
from pyfect._core import Effect, _Gen, _Succeed
from pyfect._fiber import Fiber
from pyfect.cause import Cause
from pyfect.channel._sinks import make_pubsub
from pyfect.duration import Duration
from pyfect.effect import provide_service
from pyfect.queue import Queue, Strategy
from pyfect.rc_ref import RcRef
from pyfect.result import Err, Result
from pyfect.scope import Scope, fork_in, fork_scoped
from pyfect.stream._base import AnyStream, as_stream
from pyfect.stream._grouping import from_queue_shutdown_on_end
from pyfect.stream._stream import Stream

type AnyEffect = Effect[Any, Any, Any]
type AnyStream_ = Stream[Any, Any, Any]
type Capacity = int | Literal["unbounded"]

_VOID: AnyEffect = _Succeed(None)


# --- partitions ------------------------------------------------------------------


def partition_queue(
    self: AnyStream, f: Callable[[Any], Result[Any, Any]], capacity: Capacity
) -> AnyEffect:
    bound = None if capacity == "unbounded" else capacity

    def body() -> Generator[AnyEffect, Any, tuple[Queue[Any, Any], Queue[Any, Any]]]:
        scope = yield Scope()
        pull = yield self._channel.to_pull_scoped(scope)
        passes: Queue[Any, Any] = Queue(bound)
        fails: Queue[Any, Any] = Queue(bound)

        def feed() -> Generator[AnyEffect, Any]:
            while True:
                chunk = yield pull
                passed: list[Any] = []
                failed: list[Any] = []
                for item in chunk:
                    match f(item):
                        case Err(error):
                            failed.append(error)
                        case ok:
                            passed.append(ok.value)
                pass_fiber: Fiber[Any, Any] | None = None
                if passed and (rest := passes.offer_all_unsafe(passed)):
                    pass_fiber = yield passes.offer_all(rest).fork()
                if failed and (rest := fails.offer_all_unsafe(failed)):
                    yield fails.offer_all(rest)
                if pass_fiber is not None:
                    yield pass_fiber.join()

        def fail_both(cause: Cause[Any]) -> AnyEffect:
            passes.fail_cause_unsafe(cause)
            fails.fail_cause_unsafe(cause)
            return _VOID

        yield fork_in(_Gen(feed).on_error(fail_both), scope)
        return passes, fails

    return _Gen(body)


def _as_streams(queues: tuple[Queue[Any, Any], Queue[Any, Any]]) -> tuple[AnyStream_, AnyStream_]:
    passes, fails = queues
    return from_queue_shutdown_on_end(passes), from_queue_shutdown_on_end(fails)


def partition(
    self: AnyStream, f: Callable[[Any], Result[Any, Any]], capacity: Capacity
) -> AnyEffect:
    return partition_queue(self, f, capacity).map(_as_streams)


def partition_effect(
    self: AnyStream,
    f: Callable[[Any], Effect[Result[Any, Any], Any, Any]],
    capacity: Capacity,
    concurrency: Concurrency,
) -> AnyEffect:
    mapped = as_stream(self).map_effect(f, concurrency=concurrency)
    return partition_queue(mapped, _identity, capacity).map(_as_streams)


def _identity[T](value: T) -> T:
    return value


# --- broadcasts ------------------------------------------------------------------


def broadcast(
    self: AnyStream, capacity: Capacity, strategy: Strategy, replay: int | None
) -> AnyEffect:
    from pyfect.stream._sources import from_pubsub_take

    takes: AnyEffect = (
        self._channel.to_pubsub_take(capacity=capacity, replay=replay)
        if capacity == "unbounded"
        else self._channel.to_pubsub_take(capacity=capacity, strategy=strategy, replay=replay)
    )
    return takes.map(from_pubsub_take)


def broadcast_n(
    self: AnyStream, n: int, capacity: Capacity, strategy: Strategy, replay: int | None
) -> AnyEffect:
    def body() -> Generator[AnyEffect, Any, tuple[AnyStream_, ...]]:
        pubsub = yield make_pubsub(capacity, strategy, replay)
        parent = yield Scope()
        streams: list[AnyStream_] = []
        for _ in range(max(0, n)):
            scope = parent.fork_unsafe()
            subscription = yield pubsub.subscribe().pipe(provide_service(Scope, scope))
            reader: Any = channel.from_effect_take(subscription.take()).on_exit(scope.close)
            streams.append(Stream(reader))
        yield fork_scoped(self._channel.run_for_each(pubsub.publish).on_exit(pubsub.end))
        return tuple(streams)

    return _Gen(body)


def share(
    self: AnyStream,
    capacity: Capacity,
    strategy: Strategy,
    replay: int | None,
    idle_time_to_live: Duration | None,
) -> AnyEffect:
    from pyfect.stream._constructors import unwrap

    def reader(ref: RcRef[AnyStream_, Any]) -> AnyStream_:
        return unwrap(ref.get())

    acquire = broadcast(self, capacity, strategy, replay)
    return RcRef.make(acquire, idle_time_to_live=idle_time_to_live).map(reader)
