"""Running a channel into a queue or a pubsub: the work behind
``run_into_queue``, ``to_queue``, ``run_into_pubsub``, ``to_pubsub`` and
their tuple and ``Take`` variants."""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from typing import Any, Literal

from pyfect._core import Effect
from pyfect.channel._base import AnyChannel
from pyfect.channel._run import run_for_each
from pyfect.pubsub import PubSub
from pyfect.queue import Enqueue, Queue, Strategy
from pyfect.scope import CloseableScope, Scope, acquire_release, fork_in, fork_scoped

type Capacity = int | Literal["unbounded"]


def run_into_queue(
    self: AnyChannel, queue: Enqueue[Any, Any], *, array: bool
) -> Effect[None, Any, Any]:
    offer = queue.offer_all if array else queue.offer
    return queue.into(run_for_each(self, offer)).as_void()


def to_queue(
    self: AnyChannel, capacity: Capacity, strategy: Strategy, *, array: bool
) -> Effect[Queue[Any, Any], Any, Any]:
    def start(scope: CloseableScope) -> Effect[Queue[Any, Any], Any, Any]:
        queue: Queue[Any, Any] = (
            Queue(None) if capacity == "unbounded" else Queue(capacity, strategy)
        )
        return (
            scope.add_finalizer(lambda _: queue.shutdown())
            .and_then(fork_in(run_into_queue(self, queue, array=array), scope))
            .as_(queue)
        )

    return Scope().flat_map(start)


def run_into_pubsub(
    self: AnyChannel, pubsub: PubSub[Any], shutdown_on_end: bool, *, array: bool
) -> Effect[Any, Any, Any]:
    publish = pubsub.publish_all if array else pubsub.publish
    run = run_for_each(self, publish)
    return run.ensuring(pubsub.shutdown()) if shutdown_on_end else run


def _make_pubsub(
    capacity: Capacity, strategy: Strategy, replay: int | None
) -> Effect[PubSub[Any], Any, Any]:
    if capacity == "unbounded":
        make: Effect[PubSub[Any]] = PubSub[Any].unbounded(replay=replay)
    elif strategy == "dropping":
        make = PubSub[Any].dropping(capacity, replay=replay)
    elif strategy == "sliding":
        make = PubSub[Any].sliding(capacity, replay=replay)
    else:
        make = PubSub[Any].bounded(capacity, replay=replay)
    return acquire_release(make, lambda pubsub, _: pubsub.shutdown())


def to_pubsub(
    self: AnyChannel,
    capacity: Capacity,
    strategy: Strategy,
    replay: int | None,
    shutdown_on_end: bool,
    *,
    array: bool,
) -> Effect[PubSub[Any], Any, Any]:
    def start(pubsub: PubSub[Any]) -> Effect[PubSub[Any], Any, Any]:
        run = run_into_pubsub(self, pubsub, shutdown_on_end, array=array)
        return fork_scoped(run).as_(pubsub)

    return _make_pubsub(capacity, strategy, replay).flat_map(start)


def to_pubsub_take(
    self: AnyChannel, capacity: Capacity, strategy: Strategy, replay: int | None
) -> Effect[PubSub[Any], Any, Any]:
    def start(pubsub: PubSub[Any]) -> Effect[PubSub[Any], Any, Any]:
        run = run_for_each(self, pubsub.publish).on_exit(pubsub.end)
        return fork_scoped(run).as_(pubsub)

    return _make_pubsub(capacity, strategy, replay).flat_map(start)
