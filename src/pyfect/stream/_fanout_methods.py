"""``Stream`` methods that split one stream into several: grouping by
key, partitioning, broadcasting and sharing."""

from __future__ import annotations

from collections.abc import Callable, Hashable
from typing import TYPE_CHECKING, Literal, Never, overload

from pyfect.stream._base import A_co, E_co, R_co, StreamBase

if TYPE_CHECKING:
    from pyfect._concurrency import Concurrency
    from pyfect._core import Effect
    from pyfect.duration import Input as DurationInput
    from pyfect.errors import Done
    from pyfect.queue import Dequeue, Strategy
    from pyfect.result import Result
    from pyfect.scope import Scope
    from pyfect.stream._stream import Stream

type Capacity = int | Literal["unbounded"]

GROUP_BUFFER_SIZE = 4096
"""How many items each ``group_by`` group holds before upstream waits."""


class FanOutMethods(StreamBase[A_co, E_co, R_co]):
    __slots__ = ()

    # --- grouping -------------------------------------------------------------

    def group_by[K: Hashable, V, E2 = Never, R2 = Never](
        self,
        f: Callable[[A_co], Effect[tuple[K, V], E2, R2]],
        *,
        buffer_size: int = GROUP_BUFFER_SIZE,
        idle_time_to_live: DurationInput | None = None,
    ) -> Stream[tuple[K, Stream[V]], E_co | E2, R_co | R2]:
        """Write ``(key, group)`` once per new key ``f(item)`` gives, where
        ``group`` is the stream of that key's values. Upstream runs on a
        fiber and waits while a group holds ``buffer_size`` values; a group
        read by nobody for ``idle_time_to_live`` ends, and the key's next
        value starts a new one. A group that stops early drops its values."""
        from pyfect.stream import _grouping

        return _grouping.group_by(self, f, buffer_size, idle_time_to_live)

    def group_by_key[K: Hashable](
        self,
        f: Callable[[A_co], K],
        *,
        buffer_size: int = GROUP_BUFFER_SIZE,
        idle_time_to_live: DurationInput | None = None,
    ) -> Stream[tuple[K, Stream[A_co]], E_co, R_co]:
        """``group_by`` with the items as values, keyed by ``f(item)``."""
        from pyfect.stream import _grouping

        return _grouping.group_by_key(self, f, buffer_size, idle_time_to_live)

    def group_adjacent_by[K](
        self, f: Callable[[A_co], K]
    ) -> Stream[tuple[K, tuple[A_co, ...]], E_co, R_co]:
        """Write each run of neighbouring items with equal keys ``f(item)``
        as ``(key, items)``; a key that comes back later starts a new run."""
        from pyfect.stream import _grouping

        return _grouping.group_adjacent_by(self, f)

    # --- partitioning ---------------------------------------------------------

    def partition[P, F](
        self, f: Callable[[A_co], Result[P, F]], *, capacity: Capacity = 16
    ) -> Effect[tuple[Stream[P, E_co], Stream[F, E_co]], Never, R_co | Scope]:
        """Split the items into the ``Ok`` values of ``f(item)`` and the
        ``Err`` ones. Upstream runs on a fiber in the current ``Scope``; the
        faster reader gets at most ``capacity`` items ahead of the slower."""
        from pyfect.stream import _fanout

        return _fanout.partition(self, f, capacity)

    def partition_effect[P, F, E2 = Never, R2 = Never](
        self,
        f: Callable[[A_co], Effect[Result[P, F], E2, R2]],
        *,
        capacity: Capacity = 4096,
        concurrency: Concurrency = None,
    ) -> Effect[tuple[Stream[P, E_co | E2], Stream[F, E_co | E2]], Never, R_co | R2 | Scope]:
        """``partition`` with an effectful ``f``, run on up to
        ``concurrency`` items at once (in order)."""
        from pyfect.stream import _fanout

        return _fanout.partition_effect(self, f, capacity, concurrency)

    def partition_queue[P, F](
        self, f: Callable[[A_co], Result[P, F]], *, capacity: Capacity = 4096
    ) -> Effect[tuple[Dequeue[P, E_co | Done], Dequeue[F, E_co | Done]], Never, R_co | Scope]:
        """``partition`` into two queues, which end (or fail) as the stream
        does."""
        from pyfect.stream import _fanout

        return _fanout.partition_queue(self, f, capacity)

    # --- broadcasting ---------------------------------------------------------

    @overload
    def broadcast(
        self, *, capacity: Literal["unbounded"], replay: int | None = None
    ) -> Effect[Stream[A_co, E_co], Never, R_co | Scope]: ...
    @overload
    def broadcast(
        self, *, capacity: int, strategy: Strategy = "suspend", replay: int | None = None
    ) -> Effect[Stream[A_co, E_co], Never, R_co | Scope]: ...
    def broadcast(
        self, *, capacity: Capacity, strategy: Strategy = "suspend", replay: int | None = None
    ) -> Effect[Stream[A_co, E_co], Never, R_co | Scope]:
        """Run the stream on a fiber in the current ``Scope``, publishing its
        chunks to a pubsub of ``capacity`` chunks; each run of the returned
        stream reads what is published from then on (and the last
        ``replay`` chunks), then the end or failure."""
        from pyfect.stream import _fanout

        return _fanout.broadcast(self, capacity, strategy, replay)

    @overload
    def broadcast_n(
        self, n: int, *, capacity: Literal["unbounded"], replay: int | None = None
    ) -> Effect[tuple[Stream[A_co, E_co], ...], Never, R_co | Scope]: ...
    @overload
    def broadcast_n(
        self,
        n: int,
        *,
        capacity: int,
        strategy: Strategy = "suspend",
        replay: int | None = None,
    ) -> Effect[tuple[Stream[A_co, E_co], ...], Never, R_co | Scope]: ...
    def broadcast_n(
        self,
        n: int,
        *,
        capacity: Capacity,
        strategy: Strategy = "suspend",
        replay: int | None = None,
    ) -> Effect[tuple[Stream[A_co, E_co], ...], Never, R_co | Scope]:
        """``n`` streams (none below 1) each reading every chunk. They
        subscribe now, so none misses the start; with ``"suspend"`` the
        upstream stays at most ``capacity`` chunks ahead of the slowest. A
        stream that stops unsubscribes."""
        from pyfect.stream import _fanout

        return _fanout.broadcast_n(self, n, capacity, strategy, replay)

    @overload
    def share(
        self,
        *,
        capacity: Literal["unbounded"],
        replay: int | None = None,
        idle_time_to_live: DurationInput | None = None,
    ) -> Effect[Stream[A_co, E_co], Never, R_co | Scope]: ...
    @overload
    def share(
        self,
        *,
        capacity: int,
        strategy: Strategy = "suspend",
        replay: int | None = None,
        idle_time_to_live: DurationInput | None = None,
    ) -> Effect[Stream[A_co, E_co], Never, R_co | Scope]: ...
    def share(
        self,
        *,
        capacity: Capacity,
        strategy: Strategy = "suspend",
        replay: int | None = None,
        idle_time_to_live: DurationInput | None = None,
    ) -> Effect[Stream[A_co, E_co], Never, R_co | Scope]:
        """A stream that ``broadcast``s this one when its first reader
        starts and stops it when the last one stops (or ``idle_time_to_live``
        after, so a later reader continues where it left off)."""
        from pyfect.stream import _fanout

        return _fanout.share(self, capacity, strategy, replay, idle_time_to_live)
