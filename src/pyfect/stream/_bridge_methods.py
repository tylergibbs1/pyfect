"""``Stream`` methods that hand a stream's items to something outside it:
queues, pubsubs and ``async for``."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal, Never, overload

from pyfect.stream._base import A_co, E_co, R_co, StreamBase

if TYPE_CHECKING:
    from pyfect._core import Effect
    from pyfect.context import Context
    from pyfect.errors import Done
    from pyfect.pubsub import PubSub
    from pyfect.queue import Dequeue, Enqueue, Strategy
    from pyfect.scope import Scope
    from pyfect.stream._async_iterable import StreamAsyncIterable
    from pyfect.take import Take

type Capacity = int | Literal["unbounded"]


class BridgeMethods(StreamBase[A_co, E_co, R_co]):
    __slots__ = ()

    # --- queues -----------------------------------------------------------------

    def run_into_queue(self, queue: Enqueue[A_co, E_co | Done]) -> Effect[None, Never, R_co]:
        """Offer every item to ``queue``, then end it, or fail it with the
        stream's cause. The queue is finished even if the run is
        interrupted."""
        return self._channel.run_into_queue_array(queue)

    @overload
    def to_queue(
        self, *, capacity: Literal["unbounded"]
    ) -> Effect[Dequeue[A_co, E_co | Done], Never, R_co | Scope]: ...
    @overload
    def to_queue(
        self, *, capacity: int, strategy: Strategy = "suspend"
    ) -> Effect[Dequeue[A_co, E_co | Done], Never, R_co | Scope]: ...
    def to_queue(
        self, *, capacity: Capacity, strategy: Strategy = "suspend"
    ) -> Effect[Dequeue[A_co, E_co | Done], Never, R_co | Scope]:
        """Run the stream on a fiber in the current ``Scope``, offering its
        items to a new queue of ``capacity``; the queue ends (or fails) as
        the stream does and shuts down with the scope."""
        if capacity == "unbounded":
            return self._channel.to_queue_array(capacity=capacity)
        return self._channel.to_queue_array(capacity=capacity, strategy=strategy)

    # --- pubsubs ----------------------------------------------------------------

    def run_into_pubsub(
        self, pubsub: PubSub[A_co], *, shutdown_on_end: bool = False
    ) -> Effect[None, E_co, R_co]:
        """Publish every item to ``pubsub``; with ``shutdown_on_end``, shut it
        down when the run ends."""
        return self._channel.run_into_pubsub_array(pubsub, shutdown_on_end=shutdown_on_end)

    @overload
    def to_pubsub(
        self,
        *,
        capacity: Literal["unbounded"],
        replay: int | None = None,
        shutdown_on_end: bool = True,
    ) -> Effect[PubSub[A_co], Never, R_co | Scope]: ...
    @overload
    def to_pubsub(
        self,
        *,
        capacity: int,
        strategy: Strategy = "suspend",
        replay: int | None = None,
        shutdown_on_end: bool = True,
    ) -> Effect[PubSub[A_co], Never, R_co | Scope]: ...
    def to_pubsub(
        self,
        *,
        capacity: Capacity,
        strategy: Strategy = "suspend",
        replay: int | None = None,
        shutdown_on_end: bool = True,
    ) -> Effect[PubSub[A_co], Never, R_co | Scope]:
        """Run the stream on a fiber in the current ``Scope``, publishing its
        items to a new pubsub, shut down with the scope (and, unless
        ``shutdown_on_end`` is off, when the run ends)."""
        if capacity == "unbounded":
            return self._channel.to_pubsub_array(
                capacity=capacity, replay=replay, shutdown_on_end=shutdown_on_end
            )
        return self._channel.to_pubsub_array(
            capacity=capacity, strategy=strategy, replay=replay, shutdown_on_end=shutdown_on_end
        )

    @overload
    def to_pubsub_take(
        self, *, capacity: Literal["unbounded"], replay: int | None = None
    ) -> Effect[PubSub[Take[A_co, E_co]], Never, R_co | Scope]: ...
    @overload
    def to_pubsub_take(
        self, *, capacity: int, strategy: Strategy = "suspend", replay: int | None = None
    ) -> Effect[PubSub[Take[A_co, E_co]], Never, R_co | Scope]: ...
    def to_pubsub_take(
        self, *, capacity: Capacity, strategy: Strategy = "suspend", replay: int | None = None
    ) -> Effect[PubSub[Take[A_co, E_co]], Never, R_co | Scope]:
        """Run the stream on a fiber in the current ``Scope``, publishing
        each chunk as a ``Take``, then its exit, so every subscriber (one
        that subscribes late too) sees the end or the failure."""
        if capacity == "unbounded":
            return self._channel.to_pubsub_take(capacity=capacity, replay=replay)
        return self._channel.to_pubsub_take(capacity=capacity, strategy=strategy, replay=replay)

    # --- async iteration --------------------------------------------------------

    def to_async_iterable[A, E](self: BridgeMethods[A, E, Never]) -> StreamAsyncIterable[A]:
        """The stream as an ``async for`` source, for asyncio code. Each
        ``async for`` runs the stream afresh on the running loop; a failure
        raises the squashed error. Close an iterator left early with
        ``contextlib.aclosing`` (or ``aclose()``)."""
        from pyfect.context import Context
        from pyfect.stream._async_iterable import StreamAsyncIterable

        return StreamAsyncIterable(self._channel, Context.empty())

    def to_async_iterable_with(self, context: Context[R_co]) -> StreamAsyncIterable[A_co]:
        """``to_async_iterable`` for a stream that needs the services in
        ``context``."""
        from pyfect.stream._async_iterable import StreamAsyncIterable

        return StreamAsyncIterable(self._channel, context)

    def to_async_iterable_effect(self) -> Effect[StreamAsyncIterable[A_co], Never, R_co]:
        """``to_async_iterable_with`` the current fiber's services."""
        from pyfect._context_effects import context
        from pyfect.stream._async_iterable import StreamAsyncIterable

        return context().map(lambda ctx: StreamAsyncIterable(self._channel, ctx))
