"""Sources fed from outside a channel: callbacks offering to a queue,
queues, pubsubs, schedules and async iterables."""
# pyright: reportPrivateUsage=false

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterable, AsyncIterator, Callable, Coroutine
from typing import Any, Never, overload

from pyfect import _background as background
from pyfect._core import Effect, _FailCause, _Succeed, _Suspend, _Sync
from pyfect.channel._base import AnyPull, end_with
from pyfect.channel._channel import Channel, from_pull, from_transform
from pyfect.channel._constructors import from_effect_take, unwrap_effect
from pyfect.effect import provide_service, try_async
from pyfect.errors import Done
from pyfect.pubsub import PubSub, Subscription
from pyfect.queue import Dequeue, Queue, Strategy
from pyfect.schedule import Schedule
from pyfect.schedule._model import to_step_with_sleep
from pyfect.scope import CloseableScope, Scope, fork_in
from pyfect.take import Take

type Source[A, E = Never, R = Never] = Channel[A, E, None, object, object, object, R]


def _async_queue(
    scope: CloseableScope,
    f: Callable[[Queue[Any, Any]], Effect[Any, Any, Any]],
    buffer_size: int | None,
    strategy: Strategy,
) -> Effect[Queue[Any, Any]]:
    def start() -> Effect[Queue[Any, Any]]:
        queue: Queue[Any, Any] = Queue(buffer_size, strategy)
        run = f(queue).pipe(provide_service(Scope, scope)).catch_cause(queue.fail_cause)
        return (
            scope.add_finalizer(lambda _: queue.shutdown())
            .and_then(fork_in(run, scope, start_immediately=True))
            .as_(queue)
        )

    return _Suspend(start)


@overload
def callback[A, E = Never](
    f: Callable[[Queue[A, E | Done]], Effect[object, E, Scope]],
    *,
    buffer_size: int | None = None,
    strategy: Strategy = "suspend",
) -> Source[A, E]: ...
@overload
def callback[A, E = Never, R = Never](
    f: Callable[[Queue[A, E | Done]], Effect[object, E, R | Scope]],
    *,
    buffer_size: int | None = None,
    strategy: Strategy = "suspend",
) -> Source[A, E, R]: ...
def callback(
    f: Callable[[Queue[Any, Any]], Effect[object, Any, Any]],
    *,
    buffer_size: int | None = None,
    strategy: Strategy = "suspend",
) -> Source[Any, Any, Any]:
    """A source of what ``f`` offers to a queue, run on a fiber when the
    channel starts, with the channel's ``Scope``. It ends when the queue
    ends and fails with ``f``'s failure or the queue's."""
    channel: Source[Any, Any, Any] = from_transform(
        lambda _upstream, scope: _async_queue(scope, f, buffer_size, strategy).map(
            lambda queue: queue.take()
        )
    )
    return channel


@overload
def callback_array[A, E = Never](
    f: Callable[[Queue[A, E | Done]], Effect[object, E, Scope]],
    *,
    buffer_size: int | None = None,
    strategy: Strategy = "suspend",
) -> Source[tuple[A, ...], E]: ...
@overload
def callback_array[A, E = Never, R = Never](
    f: Callable[[Queue[A, E | Done]], Effect[object, E, R | Scope]],
    *,
    buffer_size: int | None = None,
    strategy: Strategy = "suspend",
) -> Source[tuple[A, ...], E, R]: ...
def callback_array(
    f: Callable[[Queue[Any, Any]], Effect[object, Any, Any]],
    *,
    buffer_size: int | None = None,
    strategy: Strategy = "suspend",
) -> Source[Any, Any, Any]:
    """``callback``, writing every item waiting in the queue at once."""
    channel: Source[Any, Any, Any] = from_transform(
        lambda _upstream, scope: _async_queue(scope, f, buffer_size, strategy).map(
            lambda queue: queue.take_all().map(tuple)
        )
    )
    return channel


@overload
def from_queue[A](queue: Dequeue[A, Done]) -> Source[A]: ...
@overload
def from_queue[A, E](queue: Dequeue[A, E | Done]) -> Source[A, E]: ...
def from_queue(queue: Dequeue[Any, Any]) -> Source[Any, Any]:
    """A source taking from ``queue`` until it ends (or fails)."""
    return from_pull(_Succeed(queue.take()))


@overload
def from_queue_array[A](queue: Dequeue[A, Done]) -> Source[tuple[A, ...]]: ...
@overload
def from_queue_array[A, E](queue: Dequeue[A, E | Done]) -> Source[tuple[A, ...], E]: ...
def from_queue_array(queue: Dequeue[Any, Any]) -> Source[tuple[Any, ...], Any]:
    """``from_queue``, writing every item waiting at once."""
    return from_pull(_Succeed(queue.take_all().map(tuple)))


def from_subscription[A](subscription: Subscription[A]) -> Source[A]:
    """A source taking from ``subscription``; it ends when the pubsub shuts
    down."""
    take: Effect[A, Done] = subscription.take().catch_cause(_end_on_interrupt)
    return from_pull(_Succeed(take))


def from_subscription_array[A](subscription: Subscription[A]) -> Source[tuple[A, ...]]:
    """``from_subscription``, writing every message waiting at once."""
    take: Effect[tuple[A, ...], Done] = (
        subscription.take_all().map(tuple).catch_cause(_end_on_interrupt)
    )
    return from_pull(_Succeed(take))


def from_pubsub[A](pubsub: PubSub[A]) -> Source[A]:
    """A source of what is published to ``pubsub`` once the channel runs."""
    channel: Source[A] = unwrap_effect(pubsub.subscribe().map(from_subscription))
    return channel


def from_pubsub_array[A](pubsub: PubSub[A]) -> Source[tuple[A, ...]]:
    """``from_pubsub``, writing every message waiting at once."""
    channel: Source[tuple[A, ...]] = unwrap_effect(pubsub.subscribe().map(from_subscription_array))
    return channel


def from_pubsub_take[A, E, D](
    pubsub: PubSub[Take[A, E, D]],
) -> Channel[tuple[A, ...], E, D, object, object, object]:
    """A source replaying the ``Take`` values published to ``pubsub``."""
    channel: Channel[tuple[A, ...], E, D, object, object, object] = unwrap_effect(
        pubsub.subscribe().map(lambda sub: from_effect_take(sub.take()))
    )
    return channel


def from_schedule[O, E = Never, R = Never](
    schedule: Schedule[O, Any, E, R],
) -> Channel[O, E, O, object, object, object, R]:
    """Write each output of ``schedule`` after its delay; end with the
    final output when it stops."""

    # Effect's: one pull, the sleeping step applied to ``None``.
    return from_pull(to_step_with_sleep(schedule).map(lambda step: step(None)))


def from_async_iterable[A, E](
    iterable: AsyncIterable[A], on_error: Callable[[Exception], E]
) -> Source[A, E]:
    """A source of what ``iterable`` yields, failing with
    ``on_error(exception)`` if it raises. The iterator is closed when the
    run ends: awaited if idle, else without waiting for the pending
    ``__anext__``. Needs an asyncio loop (``run_async``)."""

    def transform(_upstream: AnyPull, scope: CloseableScope) -> Effect[AnyPull]:
        iterator: AsyncIterator[A] = aiter(iterable)
        pulling_on: asyncio.AbstractEventLoop | None = None
        """The loop of the ``__anext__`` in flight, if one is."""

        async def next_item() -> tuple[bool, A | None]:
            nonlocal pulling_on
            pulling_on = asyncio.get_running_loop()
            try:
                return False, await anext(iterator)
            except StopAsyncIteration:
                return True, None
            finally:
                pulling_on = None

        def close() -> Effect[None, Any, Any]:
            aclose = getattr(iterator, "aclose", None)
            if aclose is None:
                return _Succeed(None)
            loop = pulling_on
            if loop is not None:
                return _Sync(lambda: _discard_task(aclose, loop))
            return try_async(aclose).ignore()

        def written(result: tuple[bool, A | None]) -> AnyPull:
            ended, item = result
            return end_with(None) if ended else _Succeed(item)

        pull = try_async(next_item, on_error).flat_map(written)
        return scope.add_finalizer(lambda _: _Suspend(close)).as_(pull)

    channel: Source[A, E] = from_transform(transform)
    return channel


def from_async_iterable_array[A, E](
    iterable: AsyncIterable[A], on_error: Callable[[Exception], E]
) -> Source[tuple[A, ...], E]:
    """``from_async_iterable``, writing each item as a 1-tuple."""
    return from_async_iterable(iterable, on_error).map(lambda item: (item,))


def _discard_task(
    aclose: Callable[[], Coroutine[Any, Any, object]], loop: asyncio.AbstractEventLoop
) -> None:
    background.start(aclose(), loop).add_done_callback(_retrieve)


def _retrieve(task: asyncio.Future[object]) -> None:
    if not task.cancelled():
        task.exception()


def _end_on_interrupt(cause: Any) -> Effect[Never, Any]:
    return end_with(None) if cause.has_interrupts and not cause.has_fails else _FailCause(cause)
