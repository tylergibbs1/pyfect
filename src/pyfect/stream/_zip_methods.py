"""``Stream`` methods that combine two streams: zipping them item by item,
pairing their latest items, crossing them, merging them as their items
come, interleaving them and racing them."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Never, overload

from pyfect.stream._base import A_co, E_co, R_co, StreamBase, require_stream

if TYPE_CHECKING:
    from pyfect._core import Effect
    from pyfect.channel._concurrency_methods import HaltStrategy
    from pyfect.errors import Done
    from pyfect.pull import Pull
    from pyfect.result import Result
    from pyfect.stream._stream import Stream


class ZipMethods(StreamBase[A_co, E_co, R_co]):
    __slots__ = ()

    # --- zipping --------------------------------------------------------------

    def zip[B, E2 = Never, R2 = Never](
        self, that: Stream[B, E2, R2]
    ) -> Stream[tuple[A_co, B], E_co | E2, R_co | R2]:
        """Pair the items of both streams in order, pulling both at once;
        end when either ends."""
        require_stream(that, "that")
        return self.zip_with(that, _pair)

    def zip_with[B, C, E2 = Never, R2 = Never](
        self, that: Stream[B, E2, R2], f: Callable[[A_co, B], C]
    ) -> Stream[C, E_co | E2, R_co | R2]:
        """``zip``, writing ``f(left, right)`` for each pair."""
        from pyfect.stream import _zipping

        require_stream(that, "that")
        return _zipping.zip_with(self, that, f)

    def zip_with_array[B, C, E2 = Never, R2 = Never](
        self,
        that: Stream[B, E2, R2],
        f: Callable[
            [tuple[A_co, ...], tuple[B, ...]],
            tuple[tuple[C, ...], tuple[A_co, ...], tuple[B, ...]],
        ],
    ) -> Stream[C, E_co | E2, R_co | R2]:
        """Zip chunk by chunk: ``f(left, right)`` gives the chunk to write
        and the left and right items it left over, which the next call gets
        before anything new is pulled from that side."""
        from pyfect.stream import _zipping

        require_stream(that, "that")
        return _zipping.zip_with_array(self, that, f)

    def zip_left[E2 = Never, R2 = Never](
        self, that: Stream[object, E2, R2]
    ) -> Stream[A_co, E_co | E2, R_co | R2]:
        """``zip``, keeping the left items."""
        require_stream(that, "that")
        return self.zip_with(that, _left)

    def zip_right[B, E2 = Never, R2 = Never](
        self, that: Stream[B, E2, R2]
    ) -> Stream[B, E_co | E2, R_co | R2]:
        """``zip``, keeping the right items."""
        require_stream(that, "that")
        return self.zip_with(that, _right)

    def zip_flatten[*Ts, B, E2 = Never, R2 = Never](
        self: ZipMethods[tuple[*Ts], E_co, R_co], that: Stream[B, E2, R2]
    ) -> Stream[tuple[*Ts, B], E_co | E2, R_co | R2]:
        """``zip`` for a stream of tuples: append each right item to its
        left tuple."""
        require_stream(that, "that")
        return self.zip_with(that, lambda left, right: (*left, right))

    def zip_latest[B, E2 = Never, R2 = Never](
        self, that: Stream[B, E2, R2]
    ) -> Stream[tuple[A_co, B], E_co | E2, R_co | R2]:
        """Once both streams have written, pair each new item with the
        other stream's latest; end when either ends."""
        from pyfect.stream import _zipping

        require_stream(that, "that")
        return _zipping.zip_latest_all(self, that)

    def zip_latest_with[B, C, E2 = Never, R2 = Never](
        self, that: Stream[B, E2, R2], f: Callable[[A_co, B], C]
    ) -> Stream[C, E_co | E2, R_co | R2]:
        """``zip_latest``, writing ``f(left, right)`` for each pair."""
        require_stream(that, "that")
        return self.zip_latest(that).map(lambda pair: f(*pair))

    def cross[B, E2 = Never, R2 = Never](
        self, that: Stream[B, E2, R2]
    ) -> Stream[tuple[A_co, B], E_co | E2, R_co | R2]:
        """Every pair of a left and a right item: ``that`` runs again for
        each left item."""
        require_stream(that, "that")
        return self.cross_with(that, _pair)

    def cross_with[B, C, E2 = Never, R2 = Never](
        self, that: Stream[B, E2, R2], f: Callable[[A_co, B], C]
    ) -> Stream[C, E_co | E2, R_co | R2]:
        """``cross``, writing ``f(left, right)`` for each pair."""
        from pyfect.stream._base import as_stream

        require_stream(that, "that")
        return as_stream(self).flat_map(lambda left: that.map(lambda right: f(left, right)))

    # --- merging --------------------------------------------------------------

    def merge[B, E2 = Never, R2 = Never](
        self, that: Stream[B, E2, R2], *, halt_strategy: HaltStrategy = "both"
    ) -> Stream[A_co | B, E_co | E2, R_co | R2]:
        """Run both streams at once, writing items as either writes them.
        The merge ends when both have ended, or just the ``"left"`` (this)
        or ``"right"`` one, or ``"either"``; a failure of either fails it."""
        from pyfect.stream._stream import Stream

        require_stream(that, "that")
        return Stream(self._channel.merge(that._channel, halt_strategy=halt_strategy))

    def merge_effect[E2 = Never, R2 = Never](
        self, eff: Effect[object, E2, R2]
    ) -> Stream[A_co, E_co | E2, R_co | R2]:
        """Run ``eff`` alongside the stream: its failure fails the stream;
        it is interrupted when the stream ends."""
        from pyfect._effect_args import require_effect
        from pyfect.stream._stream import Stream

        require_effect(eff, "eff")
        return Stream(self._channel.merge_effect(eff))

    def merge_result[B, E2 = Never, R2 = Never](
        self, that: Stream[B, E2, R2]
    ) -> Stream[Result[A_co, B], E_co | E2, R_co | R2]:
        """``merge``, writing this stream's items as ``Ok`` and ``that``'s as
        ``Err``."""
        from pyfect.result import Err, Ok
        from pyfect.stream._base import as_stream

        require_stream(that, "that")
        lefts: Stream[Result[A_co, B], E_co, R_co] = as_stream(self).map(Ok)
        return lefts.merge(that.map(Err))

    def merge_left[E2 = Never, R2 = Never](
        self, that: Stream[object, E2, R2]
    ) -> Stream[A_co, E_co | E2, R_co | R2]:
        """Run ``that`` alongside for its effects, writing this stream's
        items."""
        require_stream(that, "that")
        return self.merge_effect(that.run_drain())

    def merge_right[B, E2 = Never, R2 = Never](
        self, that: Stream[B, E2, R2]
    ) -> Stream[B, E_co | E2, R_co | R2]:
        """Run this stream alongside for its effects, writing ``that``'s
        items."""
        from pyfect.stream._base import as_stream

        require_stream(that, "that")
        return that.merge_effect(as_stream(self).run_drain())

    # --- combining with state ---------------------------------------------------

    @overload
    def combine[B, E2, S, C, RR = Never](
        self,
        that: Stream[B, E2, RR],
        initial: Callable[[], S],
        f: Callable[[S, Pull[A_co, E_co], Pull[B, E2]], Effect[tuple[C, S], Done, RR]],
    ) -> Stream[C, Never, R_co | RR]: ...
    @overload
    def combine[B, E2, S, C, EE = Never, RR = Never](
        self,
        that: Stream[B, E2, RR],
        initial: Callable[[], S],
        f: Callable[[S, Pull[A_co, E_co], Pull[B, E2]], Effect[tuple[C, S], EE | Done, RR]],
    ) -> Stream[C, EE, R_co | RR]: ...
    def combine(
        self,
        that: Stream[Any, Any, Any],
        initial: Callable[[], Any],
        f: Callable[[Any, Any, Any], Effect[tuple[Any, Any], Any, Any]],
    ) -> Stream[Any, Any, Any]:
        """Write what ``f(state, pull_left, pull_right)`` makes, threading
        its state; ``f`` pulls single items from either side as it likes and
        ends the stream by failing with ``Done`` (as a pull of an ended side
        does)."""
        from pyfect.stream._mapping import one
        from pyfect.stream._stream import Stream

        require_stream(that, "that")
        items = self._channel.flatten_array()
        combined = items.combine(that._channel.flatten_array(), initial, f)
        return Stream(combined.map(one))

    @overload
    def combine_array[B, E2, S, C, RR = Never](
        self,
        that: Stream[B, E2, RR],
        initial: Callable[[], S],
        f: Callable[
            [S, Pull[tuple[A_co, ...], E_co], Pull[tuple[B, ...], E2]],
            Effect[tuple[tuple[C, ...], S], Done, RR],
        ],
    ) -> Stream[C, Never, R_co | RR]: ...
    @overload
    def combine_array[B, E2, S, C, EE = Never, RR = Never](
        self,
        that: Stream[B, E2, RR],
        initial: Callable[[], S],
        f: Callable[
            [S, Pull[tuple[A_co, ...], E_co], Pull[tuple[B, ...], E2]],
            Effect[tuple[tuple[C, ...], S], EE | Done, RR],
        ],
    ) -> Stream[C, EE, R_co | RR]: ...
    def combine_array(
        self,
        that: Stream[Any, Any, Any],
        initial: Callable[[], Any],
        f: Callable[[Any, Any, Any], Effect[tuple[Any, Any], Any, Any]],
    ) -> Stream[Any, Any, Any]:
        """``combine`` a chunk at a time: the pulls give chunks, and ``f``
        makes a non-empty tuple of items to write."""
        from pyfect.stream._stream import Stream

        require_stream(that, "that")
        return Stream(self._channel.combine(that._channel, initial, f))

    # --- interleaving and racing ----------------------------------------------

    def interleave[B, E2 = Never, R2 = Never](
        self, that: Stream[B, E2, R2]
    ) -> Stream[A_co | B, E_co | E2, R_co | R2]:
        """Alternate items from this stream and ``that``, starting here; when
        one ends, write the rest of the other."""
        from pyfect.stream import _zipping

        require_stream(that, "that")
        return _zipping.interleave_with(self, that, _zipping.alternating())

    def interleave_with[B, EE = Never, RR = Never](
        self, that: Stream[B, EE, RR], decider: Stream[bool, EE, RR]
    ) -> Stream[A_co | B, E_co | EE, R_co | RR]:
        """Take the next item from this stream when ``decider`` writes
        ``True`` and from ``that`` when it writes ``False``, skipping a side
        that has ended; end when both have ended or ``decider`` does."""
        from pyfect.stream import _zipping

        require_stream(that, "that")
        require_stream(decider, "decider")
        return _zipping.interleave_with(self, that, decider)

    def race[B, E2 = Never, R2 = Never](
        self, that: Stream[B, E2, R2]
    ) -> Stream[A_co | B, E_co | E2, R_co | R2]:
        """The stream that writes first; the other is interrupted."""
        from pyfect.stream import _zipping

        require_stream(that, "that")
        return _zipping.race_all(self, that)


def _pair[A, B](left: A, right: B) -> tuple[A, B]:
    return (left, right)


def _left[A](left: A, _: object) -> A:
    return left


def _right[B](_: object, right: B) -> B:
    return right
