"""``Channel`` methods that run a channel: the ``run_*`` folds, ``to_pull``,
and running into (or out to) queues and pubsubs.

Each needs a channel that accepts an upstream ending at once with
``None``: its ``self`` type says so.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Literal, Never, overload

from pyfect.channel._base import (
    ChannelBase,
    Env_co,
    InDone_contra,
    InElem_contra,
    InErr_contra,
    OutDone_co,
    OutElem_co,
    OutErr_co,
)

if TYPE_CHECKING:
    from pyfect._core import Effect
    from pyfect.errors import Done
    from pyfect.option import Option
    from pyfect.pubsub import PubSub
    from pyfect.pull import Pull
    from pyfect.queue import Dequeue, Enqueue, Strategy
    from pyfect.scope import CloseableScope, Scope
    from pyfect.take import Take

type Capacity = int | Literal["unbounded"]


class RunMethods(
    ChannelBase[
        OutElem_co, OutErr_co, OutDone_co, InElem_contra, InErr_contra, InDone_contra, Env_co
    ]
):
    __slots__ = ()

    def run_collect[O, E, D, R](
        self: RunMethods[O, E, D, Never, Never, None, R],
    ) -> Effect[list[O], E, R]:
        """Run the channel and collect every item written."""
        from pyfect.channel import _run

        return _run.run_collect(self)

    def run_drain[O, E, D, R](self: RunMethods[O, E, D, Never, Never, None, R]) -> Effect[D, E, R]:
        """Run the channel, dropping its items; succeed with its end value."""
        from pyfect.channel import _run

        return _run.run_drain(self)

    def run_for_each[O, E, D, R, E2 = Never, R2 = Never](
        self: RunMethods[O, E, D, Never, Never, None, R], f: Callable[[O], Effect[object, E2, R2]]
    ) -> Effect[D, E | E2, R | R2]:
        """Run ``f`` on each item; succeed with the channel's end value."""
        from pyfect.channel import _run

        return _run.run_for_each(self, f)

    def run_for_each_while[O, E, D, R, E2 = Never, R2 = Never](
        self: RunMethods[O, E, D, Never, Never, None, R], f: Callable[[O], Effect[bool, E2, R2]]
    ) -> Effect[D | None, E | E2, R | R2]:
        """Run ``f`` on each item until it succeeds with ``False`` (``None``),
        or the channel ends (its end value)."""
        from pyfect.channel import _run

        return _run.run_for_each_while(self, f)

    def run_fold[O, E, D, R, Z](
        self: RunMethods[O, E, D, Never, Never, None, R],
        initial: Callable[[], Z],
        f: Callable[[Z, O], Z],
    ) -> Effect[Z, E, R]:
        """Fold the items into ``initial()`` with ``f``."""
        from pyfect.channel import _run

        return _run.run_fold(self, initial, f)

    def run_fold_effect[O, E, D, R, Z, E2 = Never, R2 = Never](
        self: RunMethods[O, E, D, Never, Never, None, R],
        initial: Callable[[], Z],
        f: Callable[[Z, O], Effect[Z, E2, R2]],
    ) -> Effect[Z, E | E2, R | R2]:
        """Fold the items into ``initial()`` with the effect ``f``."""
        from pyfect.channel import _run

        return _run.run_fold_effect(self, initial, f)

    def run_count[O, E, D, R](
        self: RunMethods[O, E, D, Never, Never, None, R],
    ) -> Effect[int, E, R]:
        """Run the channel and count its items."""
        from pyfect.channel import _run

        return _run.run_fold(self, _zero, _increment)

    def run_head[O, E, D, R](
        self: RunMethods[O, E, D, Never, Never, None, R],
    ) -> Effect[Option[O], E, R]:
        """The first item (``Some``), or ``None`` when there is none. Stops
        the channel after the first item."""
        from pyfect.channel import _run

        return _run.run_head(self)

    def run_last[O, E, D, R](
        self: RunMethods[O, E, D, Never, Never, None, R],
    ) -> Effect[Option[O], E, R]:
        """The last item (``Some``), or ``None`` when there is none."""
        from pyfect.channel import _run

        return _run.run_last(self)

    def run_bytes[E, D, R](
        self: RunMethods[tuple[bytes, ...], E, D, Never, Never, None, R],
    ) -> Effect[bytes, E, R]:
        """Run a channel of byte chunks and join them (Effect's
        ``mkUint8Array``)."""
        from pyfect.channel import _run

        return _run.run_fold(self, list[bytes], _extend).map(b"".join)

    def to_pull[O, E, D, R](
        self: RunMethods[O, E, D, Never, Never, None, R],
    ) -> Effect[Pull[O, E, D], Never, R | Scope]:
        """Build the channel's pull in the current ``Scope``, which holds
        its resources. The pull has the caller's services and takes turns:
        fibers pulling at once get one item each."""
        from pyfect.channel import _run

        return _run.to_pull(self)

    def to_pull_scoped[O, E, D, R](
        self: RunMethods[O, E, D, Never, Never, None, R], scope: CloseableScope
    ) -> Effect[Pull[O, E, D, R], Never, R]:
        """Build the channel's pull with its resources in ``scope``."""
        from pyfect.channel import _run

        return _run.to_pull_scoped(self, scope)

    # --- queues ---------------------------------------------------------------

    def run_into_queue[O, E, D, R](
        self: RunMethods[O, E, D, Never, Never, None, R], queue: Enqueue[O, E | Done]
    ) -> Effect[None, Never, R]:
        """Offer every item to ``queue``, then end it, or fail it with the
        channel's cause. The queue is finished even if the run is
        interrupted."""
        from pyfect.channel import _sinks

        return _sinks.run_into_queue(self, queue, array=False)

    def run_into_queue_array[A, E, D, R](
        self: RunMethods[tuple[A, ...], E, D, Never, Never, None, R], queue: Enqueue[A, E | Done]
    ) -> Effect[None, Never, R]:
        """``run_into_queue``, offering the items of each tuple."""
        from pyfect.channel import _sinks

        return _sinks.run_into_queue(self, queue, array=True)

    @overload
    def to_queue[O, E, D, R](
        self: RunMethods[O, E, D, Never, Never, None, R], *, capacity: Literal["unbounded"]
    ) -> Effect[Dequeue[O, E | Done], Never, R | Scope]: ...
    @overload
    def to_queue[O, E, D, R](
        self: RunMethods[O, E, D, Never, Never, None, R],
        *,
        capacity: int,
        strategy: Strategy = "suspend",
    ) -> Effect[Dequeue[O, E | Done], Never, R | Scope]: ...
    def to_queue[O, E, D, R](
        self: RunMethods[O, E, D, Never, Never, None, R],
        *,
        capacity: Capacity,
        strategy: Strategy = "suspend",
    ) -> Effect[Dequeue[O, E | Done], Never, R | Scope]:
        """Run the channel on a fiber in the current ``Scope``, offering its
        items to a new queue of ``capacity``; the queue ends (or fails) as
        the channel does and shuts down with the scope."""
        from pyfect.channel import _sinks

        return _sinks.to_queue(self, capacity, strategy, array=False)

    @overload
    def to_queue_array[A, E, D, R](
        self: RunMethods[tuple[A, ...], E, D, Never, Never, None, R],
        *,
        capacity: Literal["unbounded"],
    ) -> Effect[Dequeue[A, E | Done], Never, R | Scope]: ...
    @overload
    def to_queue_array[A, E, D, R](
        self: RunMethods[tuple[A, ...], E, D, Never, Never, None, R],
        *,
        capacity: int,
        strategy: Strategy = "suspend",
    ) -> Effect[Dequeue[A, E | Done], Never, R | Scope]: ...
    def to_queue_array[A, E, D, R](
        self: RunMethods[tuple[A, ...], E, D, Never, Never, None, R],
        *,
        capacity: Capacity,
        strategy: Strategy = "suspend",
    ) -> Effect[Dequeue[A, E | Done], Never, R | Scope]:
        """``to_queue``, offering the items of each tuple."""
        from pyfect.channel import _sinks

        return _sinks.to_queue(self, capacity, strategy, array=True)

    # --- pubsubs --------------------------------------------------------------

    def run_into_pubsub[O, E, D, R](
        self: RunMethods[O, E, D, Never, Never, None, R],
        pubsub: PubSub[O],
        *,
        shutdown_on_end: bool = False,
    ) -> Effect[D, E, R]:
        """Publish every item to ``pubsub``; with ``shutdown_on_end``, shut it
        down when the run ends."""
        from pyfect.channel import _sinks

        return _sinks.run_into_pubsub(self, pubsub, shutdown_on_end, array=False)

    def run_into_pubsub_array[A, E, D, R](
        self: RunMethods[tuple[A, ...], E, D, Never, Never, None, R],
        pubsub: PubSub[A],
        *,
        shutdown_on_end: bool = False,
    ) -> Effect[D, E, R]:
        """``run_into_pubsub``, publishing the items of each tuple."""
        from pyfect.channel import _sinks

        return _sinks.run_into_pubsub(self, pubsub, shutdown_on_end, array=True)

    @overload
    def to_pubsub[O, E, D, R](
        self: RunMethods[O, E, D, Never, Never, None, R],
        *,
        capacity: Literal["unbounded"],
        replay: int | None = None,
        shutdown_on_end: bool = True,
    ) -> Effect[PubSub[O], Never, R | Scope]: ...
    @overload
    def to_pubsub[O, E, D, R](
        self: RunMethods[O, E, D, Never, Never, None, R],
        *,
        capacity: int,
        strategy: Strategy = "suspend",
        replay: int | None = None,
        shutdown_on_end: bool = True,
    ) -> Effect[PubSub[O], Never, R | Scope]: ...
    def to_pubsub[O, E, D, R](
        self: RunMethods[O, E, D, Never, Never, None, R],
        *,
        capacity: Capacity,
        strategy: Strategy = "suspend",
        replay: int | None = None,
        shutdown_on_end: bool = True,
    ) -> Effect[PubSub[O], Never, R | Scope]:
        """Run the channel on a fiber in the current ``Scope``, publishing
        its items to a new pubsub, shut down with the scope (and, unless
        ``shutdown_on_end`` is off, when the run ends)."""
        from pyfect.channel import _sinks

        return _sinks.to_pubsub(self, capacity, strategy, replay, shutdown_on_end, array=False)

    @overload
    def to_pubsub_array[A, E, D, R](
        self: RunMethods[tuple[A, ...], E, D, Never, Never, None, R],
        *,
        capacity: Literal["unbounded"],
        replay: int | None = None,
        shutdown_on_end: bool = True,
    ) -> Effect[PubSub[A], Never, R | Scope]: ...
    @overload
    def to_pubsub_array[A, E, D, R](
        self: RunMethods[tuple[A, ...], E, D, Never, Never, None, R],
        *,
        capacity: int,
        strategy: Strategy = "suspend",
        replay: int | None = None,
        shutdown_on_end: bool = True,
    ) -> Effect[PubSub[A], Never, R | Scope]: ...
    def to_pubsub_array[A, E, D, R](
        self: RunMethods[tuple[A, ...], E, D, Never, Never, None, R],
        *,
        capacity: Capacity,
        strategy: Strategy = "suspend",
        replay: int | None = None,
        shutdown_on_end: bool = True,
    ) -> Effect[PubSub[A], Never, R | Scope]:
        """``to_pubsub``, publishing the items of each tuple."""
        from pyfect.channel import _sinks

        return _sinks.to_pubsub(self, capacity, strategy, replay, shutdown_on_end, array=True)

    @overload
    def to_pubsub_take[A, E, D, R](
        self: RunMethods[tuple[A, ...], E, D, Never, Never, None, R],
        *,
        capacity: Literal["unbounded"],
        replay: int | None = None,
    ) -> Effect[PubSub[Take[A, E, D]], Never, R | Scope]: ...
    @overload
    def to_pubsub_take[A, E, D, R](
        self: RunMethods[tuple[A, ...], E, D, Never, Never, None, R],
        *,
        capacity: int,
        strategy: Strategy = "suspend",
        replay: int | None = None,
    ) -> Effect[PubSub[Take[A, E, D]], Never, R | Scope]: ...
    def to_pubsub_take[A, E, D, R](
        self: RunMethods[tuple[A, ...], E, D, Never, Never, None, R],
        *,
        capacity: Capacity,
        strategy: Strategy = "suspend",
        replay: int | None = None,
    ) -> Effect[PubSub[Take[A, E, D]], Never, R | Scope]:
        """Run the channel on a fiber in the current ``Scope``, publishing
        each tuple as a ``Take``, then the run's exit as the final one."""
        from pyfect.channel import _sinks

        return _sinks.to_pubsub_take(self, capacity, strategy, replay)


def _zero() -> int:
    return 0


def _increment(n: int, _: object) -> int:
    return n + 1


def _extend(chunks: list[bytes], chunk: tuple[bytes, ...]) -> list[bytes]:
    chunks.extend(chunk)
    return chunks
