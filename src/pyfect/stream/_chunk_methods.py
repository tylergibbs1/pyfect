"""``Stream`` methods that work on chunks and positions: rechunking,
grouping, sliding windows, splitting, scans, accumulating maps, and pairing
items with their index or neighbours.

Sizes are ``int``s; a size below one counts as one. Groups and windows
are tuples.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING, Never

from pyfect.stream._base import A_co, E_co, R_co, StreamBase

if TYPE_CHECKING:
    from pyfect._core import Effect
    from pyfect.option import Option
    from pyfect.stream._stream import Stream


class ChunkMethods(StreamBase[A_co, E_co, R_co]):
    __slots__ = ()

    # --- chunks ---------------------------------------------------------------

    def chunks(self) -> Stream[tuple[A_co, ...], E_co, R_co]:
        """Write each chunk as one item."""
        from pyfect.stream._stream import Stream

        return Stream(self._channel.map(lambda chunk: (chunk,)))

    def collect(self) -> Stream[list[A_co], E_co, R_co]:
        """Write every item as one list, once the stream ends."""
        from pyfect.stream._base import as_stream
        from pyfect.stream._constructors import from_effect

        return from_effect(as_stream(self).run_collect())

    def accumulate(self) -> Stream[tuple[A_co, ...], E_co, R_co]:
        """For each chunk, write a tuple of every item so far."""
        from pyfect.stream import _chunking

        return _chunking.accumulate(self)

    def rechunk(self, size: int) -> Stream[A_co, E_co, R_co]:
        """Write the items in chunks of ``size`` (the last may be smaller)."""
        from pyfect.stream import _chunking

        return _chunking.rechunk(self, size)

    def grouped(self, size: int) -> Stream[tuple[A_co, ...], E_co, R_co]:
        """Write the items in tuples of ``size`` (the last may be smaller)."""
        return self.rechunk(size).chunks()

    def sliding(self, size: int) -> Stream[tuple[A_co, ...], E_co, R_co]:
        """Windows of ``size`` items, each one item on from the last."""
        from pyfect.stream import _chunking

        return _chunking.sliding_size(self, size, 1)

    def sliding_size(self, size: int, step: int) -> Stream[tuple[A_co, ...], E_co, R_co]:
        """Windows of ``size`` items, each ``step`` items on from the last.
        When the stream ends or fails, the items not yet in a full window
        are written as one shorter window first."""
        from pyfect.stream import _chunking

        return _chunking.sliding_size(self, size, step)

    def split(self, predicate: Callable[[A_co], bool]) -> Stream[tuple[A_co, ...], E_co, R_co]:
        """Write the runs of items between the items that pass ``predicate``
        (which are dropped); empty runs are skipped."""
        from pyfect.stream import _chunking

        return _chunking.split(self, predicate)

    # --- scans and accumulating maps ------------------------------------------

    def scan[S](self, initial: Callable[[], S], f: Callable[[S, A_co], S]) -> Stream[S, E_co, R_co]:
        """Write ``initial()``, then each state ``f`` folds the items into."""
        from pyfect.stream import _chunking

        return _chunking.scan(self, initial, f)

    def scan_effect[S, E2 = Never, R2 = Never](
        self, initial: Callable[[], S], f: Callable[[S, A_co], Effect[S, E2, R2]]
    ) -> Stream[S, E_co | E2, R_co | R2]:
        """``scan`` with an effectful ``f``."""
        from pyfect.stream import _chunking

        return _chunking.scan_effect(self, initial, f)

    def map_accum[S, B](
        self,
        initial: Callable[[], S],
        f: Callable[[S, A_co], tuple[S, Sequence[B]]],
        *,
        on_halt: Callable[[S], Sequence[B]] | None = None,
    ) -> Stream[B, E_co, R_co]:
        """Thread a state through the items: ``f(state, item)`` gives the
        next state and the items to write. When the stream ends or fails,
        ``on_halt(state)`` gives the last items to write."""
        from pyfect.stream import _chunking

        return _chunking.map_accum(self, initial, f, on_halt, array=False)

    def map_accum_array[S, B](
        self,
        initial: Callable[[], S],
        f: Callable[[S, tuple[A_co, ...]], tuple[S, Sequence[B]]],
        *,
        on_halt: Callable[[S], Sequence[B]] | None = None,
    ) -> Stream[B, E_co, R_co]:
        """``map_accum`` over each chunk."""
        from pyfect.stream import _chunking

        return _chunking.map_accum(self, initial, f, on_halt, array=True)

    def map_accum_effect[S, B, E2 = Never, R2 = Never](
        self,
        initial: Callable[[], S],
        f: Callable[[S, A_co], Effect[tuple[S, Sequence[B]], E2, R2]],
        *,
        on_halt: Callable[[S], Sequence[B]] | None = None,
    ) -> Stream[B, E_co | E2, R_co | R2]:
        """``map_accum`` with an effectful ``f``, one item at a time."""
        from pyfect.stream import _chunking

        return _chunking.map_accum_effect(self, initial, f, on_halt, array=False)

    def map_accum_array_effect[S, B, E2 = Never, R2 = Never](
        self,
        initial: Callable[[], S],
        f: Callable[[S, tuple[A_co, ...]], Effect[tuple[S, Sequence[B]], E2, R2]],
        *,
        on_halt: Callable[[S], Sequence[B]] | None = None,
    ) -> Stream[B, E_co | E2, R_co | R2]:
        """``map_accum_array`` with an effectful ``f``."""
        from pyfect.stream import _chunking

        return _chunking.map_accum_effect(self, initial, f, on_halt, array=True)

    # --- positions and neighbours ---------------------------------------------

    def zip_with_index(self) -> Stream[tuple[A_co, int], E_co, R_co]:
        """Pair each item with its index, from 0."""
        from pyfect.stream import _chunking

        return _chunking.zip_with_index(self)

    def zip_with_next(self) -> Stream[tuple[A_co, Option[A_co]], E_co, R_co]:
        """Pair each item with the next one (``None`` for the last)."""
        from pyfect.stream import _chunking

        return _chunking.zip_with_next(self)

    def zip_with_previous(self) -> Stream[tuple[Option[A_co], A_co], E_co, R_co]:
        """Pair each item with the one before it (``None`` for the first)."""
        from pyfect.stream import _chunking

        return _chunking.zip_with_previous(self)

    def zip_with_previous_and_next(
        self,
    ) -> Stream[tuple[Option[A_co], A_co, Option[A_co]], E_co, R_co]:
        """Each item between the one before it and the next one."""
        from pyfect.stream import _chunking

        return _chunking.zip_with_previous_and_next(self)
