"""Streams fed from outside: callbacks offering to a queue, queues,
pubsubs, schedules, ticks and async iterables."""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from collections.abc import AsyncIterable, Callable
from typing import Any, Never, overload

from pyfect import channel
from pyfect._core import Effect, _Succeed, _Suspend, _Sync
from pyfect.channel._base import end_with
from pyfect.duration import Duration, to_seconds
from pyfect.errors import Done
from pyfect.pubsub import PubSub, Subscription
from pyfect.queue import Dequeue, Queue, Strategy
from pyfect.schedule import Schedule
from pyfect.schedule._model import Metadata, Stop, to_step_with_metadata
from pyfect.scope import Scope
from pyfect.stream._stream import Stream, from_pull
from pyfect.take import Take

type AnyPull = Effect[Any, Any, Any]


@overload
def callback[A, E = Never](
    f: Callable[[Queue[A, E | Done]], Effect[object, E, Scope]],
    *,
    buffer_size: int | None = None,
    strategy: Strategy = "suspend",
) -> Stream[A, E]: ...
@overload
def callback[A, E = Never, R = Never](
    f: Callable[[Queue[A, E | Done]], Effect[object, E, R | Scope]],
    *,
    buffer_size: int | None = None,
    strategy: Strategy = "suspend",
) -> Stream[A, E, R]: ...
def callback(
    f: Callable[[Queue[Any, Any]], Effect[object, Any, Any]],
    *,
    buffer_size: int | None = None,
    strategy: Strategy = "suspend",
) -> Stream[Any, Any, Any]:
    """A stream of what ``f`` offers to a queue. ``f`` runs on a fiber, with
    the stream's ``Scope``, when the stream starts; the stream ends when the
    queue ends and fails with ``f``'s failure or the queue's. With a
    ``buffer_size`` the queue is bounded and ``strategy`` says what a full
    one does (``"suspend"`` waits: backpressure)."""
    chunks: Any = channel.callback_array(f, buffer_size=buffer_size, strategy=strategy)
    return Stream(chunks)


@overload
def from_queue[A](queue: Dequeue[A, Done]) -> Stream[A]: ...
@overload
def from_queue[A, E](queue: Dequeue[A, E | Done]) -> Stream[A, E]: ...
def from_queue(queue: Dequeue[Any, Any]) -> Stream[Any, Any]:
    """A stream taking everything waiting in ``queue`` at each pull, until
    it ends (or fails)."""
    return Stream(channel.from_queue_array(queue))


def from_subscription[A](subscription: Subscription[A]) -> Stream[A]:
    """A stream of the messages of ``subscription``; it ends when the
    pubsub shuts down."""
    return Stream(channel.from_subscription_array(subscription))


def from_pubsub[A](pubsub: PubSub[A]) -> Stream[A]:
    """A stream of what is published to ``pubsub`` after the stream starts
    (and what it replays); it ends when the pubsub shuts down."""
    return Stream(channel.from_pubsub_array(pubsub))


def from_pubsub_take[A, E](pubsub: PubSub[Take[A, E, None]]) -> Stream[A, E]:
    """A stream replaying the ``Take`` values published to ``pubsub``: the
    chunks, then the failure or the end."""
    return Stream(channel.from_pubsub_take(pubsub))


def from_schedule[O, E = Never, R = Never](schedule: Schedule[O, object, E, R]) -> Stream[O, E, R]:
    """A stream of the outputs of ``schedule``, each after its delay; it
    ends when the schedule stops."""

    def with_step(step: Callable[[None], Effect[Metadata[O, Any] | Stop[O], E, R]]) -> AnyPull:
        def written(decision: Metadata[O, Any] | Stop[O]) -> AnyPull:
            return end_with(None) if isinstance(decision, Stop) else _Succeed((decision.output,))

        return step(None).flat_map(written)

    return from_pull(to_step_with_metadata(schedule).map(with_step))


def tick(interval: Duration) -> Stream[None]:
    """An endless stream of ``None``: the first at once, then one after
    each ``interval``."""
    seconds = to_seconds(interval)
    tock: Effect[tuple[None]] = _Succeed((None,))

    def make_pull() -> AnyPull:
        delayed = tock.delay(seconds)
        first = True

        def pull() -> AnyPull:
            nonlocal first
            if first:
                first = False
                return tock
            return delayed

        return _Suspend(pull)

    return from_pull(_Sync(make_pull))


def from_async_iterable[A, E](
    iterable: AsyncIterable[A], on_error: Callable[[Exception], E]
) -> Stream[A, E]:
    """A stream of what ``iterable`` yields, failing with
    ``on_error(exception)`` if it raises. The iterator is closed when the
    run ends. Needs an asyncio loop (``run_async``)."""
    return Stream(channel.from_async_iterable_array(iterable, on_error))
