"""``Channel`` methods that transform what a channel writes or how it ends:
mapping, flat-mapping, filtering, folding, concatenating and piping."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING, Any, Never, TypeIs, overload

from pyfect.channel._base import (
    ChannelBase,
    Env_co,
    InDone_contra,
    InElem_contra,
    InErr_contra,
    OutDone_co,
    OutElem_co,
    OutErr_co,
    require_channel,
)

if TYPE_CHECKING:
    from pyfect._concurrency import Concurrency
    from pyfect._core import Effect
    from pyfect.channel._channel import Channel
    from pyfect.errors import Done
    from pyfect.pull import Pull
    from pyfect.take import Take


class TransformMethods(
    ChannelBase[
        OutElem_co, OutErr_co, OutDone_co, InElem_contra, InErr_contra, InDone_contra, Env_co
    ]
):
    __slots__ = ()

    # --- mapping ------------------------------------------------------------

    def map[B](
        self, f: Callable[[OutElem_co], B]
    ) -> Channel[B, OutErr_co, OutDone_co, InElem_contra, InErr_contra, InDone_contra, Env_co]:
        """Apply ``f`` to each item written."""
        from pyfect.channel import _combinators

        return _combinators.map_(self, f)

    def map_effect[B, E2 = Never, R2 = Never](
        self,
        f: Callable[[OutElem_co], Effect[B, E2, R2]],
        *,
        concurrency: Concurrency = None,
        unordered: bool = False,
    ) -> Channel[
        B, OutErr_co | E2, OutDone_co, InElem_contra, InErr_contra, InDone_contra, Env_co | R2
    ]:
        """Write what ``f(item)`` succeeds with, failing with its error.
        With ``concurrency`` above 1, up to that many run at once; their
        results keep upstream's order unless ``unordered``."""
        from pyfect.channel import _combinators

        return _combinators.map_effect(self, f, concurrency, unordered=unordered)

    def tap[E2 = Never, R2 = Never](
        self, f: Callable[[OutElem_co], Effect[object, E2, R2]], *, concurrency: Concurrency = None
    ) -> Channel[
        OutElem_co,
        OutErr_co | E2,
        OutDone_co,
        InElem_contra,
        InErr_contra,
        InDone_contra,
        Env_co | R2,
    ]:
        """Run ``f`` on each item, then write the item."""
        from pyfect.channel import _combinators

        return _combinators.map_effect(self, lambda a: f(a).as_(a), concurrency)

    def map_done[D2](
        self, f: Callable[[OutDone_co], D2]
    ) -> Channel[OutElem_co, OutErr_co, D2, InElem_contra, InErr_contra, InDone_contra, Env_co]:
        """Apply ``f`` to the value the channel ends with."""
        from pyfect.channel import _combinators

        return _combinators.map_done(self, f)

    def map_done_effect[D2, E2 = Never, R2 = Never](
        self, f: Callable[[OutDone_co], Effect[D2, E2, R2]]
    ) -> Channel[
        OutElem_co, OutErr_co | E2, D2, InElem_contra, InErr_contra, InDone_contra, Env_co | R2
    ]:
        """End with what ``f(done)`` succeeds with, or fail with its error."""
        from pyfect.channel import _combinators

        return _combinators.map_done_effect(self, f)

    def map_input[I2, R2 = Never](
        self, f: Callable[[I2], Effect[InElem_contra, InErr_contra, R2]]
    ) -> Channel[OutElem_co, OutErr_co, OutDone_co, I2, InErr_contra, InDone_contra, Env_co | R2]:
        """Read upstream items through ``f``."""
        from pyfect.channel import _combinators

        return _combinators.map_input(self, f)

    def map_input_error[IE2, R2 = Never](
        self, f: Callable[[IE2], Effect[InErr_contra, InErr_contra, R2]]
    ) -> Channel[OutElem_co, OutErr_co, OutDone_co, InElem_contra, IE2, InDone_contra, Env_co | R2]:
        """Read upstream's failures through ``f``; the channel sees the
        error ``f`` succeeds or fails with."""
        from pyfect.channel import _combinators

        return _combinators.map_input_error(self, f)

    # --- flat-mapping ---------------------------------------------------------

    def flat_map[O2, E2 = Never, R2 = Never](
        self,
        f: Callable[
            [OutElem_co], Channel[O2, E2, Any, InElem_contra, InErr_contra, InDone_contra, R2]
        ],
        *,
        concurrency: Concurrency = None,
        buffer_size: int = 16,
    ) -> Channel[
        O2, OutErr_co | E2, OutDone_co, InElem_contra, InErr_contra, InDone_contra, Env_co | R2
    ]:
        """Write the items of ``f(item)`` for each item, one channel after
        another; with ``concurrency`` above 1, up to that many at once,
        their items merged through a buffer of ``buffer_size``."""
        from pyfect.channel import _combinators, _merge

        if _combinators.is_sequential(concurrency):
            return _combinators.flat_map(self, f)
        return _merge.merge_all(_combinators.map_(self, f), concurrency, buffer_size, switch=False)

    def flatten[O2, E, D, I, IE, ID, R, E2 = Never, R2 = Never](
        self: TransformMethods[Channel[O2, E2, Any, I, IE, ID, R2], E, D, I, IE, ID, R],
    ) -> Channel[O2, E | E2, D, I, IE, ID, R | R2]:
        """Write the items of each channel this channel writes, in turn."""
        from pyfect.channel import _combinators

        return _combinators.flat_map(self, _identity)

    def flatten_array[A, E, D, I, IE, ID, R](
        self: TransformMethods[Sequence[A], E, D, I, IE, ID, R],
    ) -> Channel[A, E, D, I, IE, ID, R]:
        """Write the items of each sequence one by one."""
        from pyfect.channel import _filters

        return _filters.flatten_array(self)

    def flatten_take[A, E, D, I, IE, ID, R, E2 = Never, D2 = None](
        self: TransformMethods[Take[A, E2, D2], E, D, I, IE, ID, R],
    ) -> Channel[tuple[A, ...], E | E2, D2, I, IE, ID, R]:
        """Replay each ``Take``: write its items, or fail or end as it says."""
        from pyfect.channel import _combinators
        from pyfect.take import to_pull

        return _combinators.map_effect(self, to_pull, None)

    def drain(
        self,
    ) -> Channel[Never, OutErr_co, OutDone_co, InElem_contra, InErr_contra, InDone_contra, Env_co]:
        """Run the channel for its effects, writing nothing."""
        from pyfect.channel import _combinators

        return _combinators.drain(self)

    # --- filtering and folding ------------------------------------------------

    @overload
    def filter[B](
        self, predicate: Callable[[OutElem_co], TypeIs[B]]
    ) -> Channel[B, OutErr_co, OutDone_co, InElem_contra, InErr_contra, InDone_contra, Env_co]: ...
    @overload
    def filter(
        self, predicate: Callable[[OutElem_co], bool]
    ) -> Channel[
        OutElem_co, OutErr_co, OutDone_co, InElem_contra, InErr_contra, InDone_contra, Env_co
    ]: ...
    def filter(
        self, predicate: Callable[[Any], bool]
    ) -> Channel[Any, Any, Any, Any, Any, Any, Any]:
        """Write only the items that pass ``predicate``."""
        from pyfect.channel import _filters

        return _filters.filter_(self, predicate)

    def filter_effect[E2 = Never, R2 = Never](
        self, predicate: Callable[[OutElem_co], Effect[bool, E2, R2]]
    ) -> Channel[
        OutElem_co,
        OutErr_co | E2,
        OutDone_co,
        InElem_contra,
        InErr_contra,
        InDone_contra,
        Env_co | R2,
    ]:
        """Write only the items whose ``predicate`` succeeds with ``True``."""
        from pyfect.channel import _filters

        return _filters.filter_effect(self, predicate)

    def filter_array[A, E, D, I, IE, ID, R](
        self: TransformMethods[tuple[A, ...], E, D, I, IE, ID, R], predicate: Callable[[A], bool]
    ) -> Channel[tuple[A, ...], E, D, I, IE, ID, R]:
        """Keep the items of each tuple that pass ``predicate``, skipping
        tuples left empty."""
        from pyfect.channel import _filters

        return _filters.filter_array(self, predicate)

    def filter_array_effect[A, E, D, I, IE, ID, R, E2 = Never, R2 = Never](
        self: TransformMethods[tuple[A, ...], E, D, I, IE, ID, R],
        predicate: Callable[[A], Effect[bool, E2, R2]],
    ) -> Channel[tuple[A, ...], E | E2, D, I, IE, ID, R | R2]:
        """``filter_array`` with an effectful ``predicate``."""
        from pyfect.channel import _filters

        return _filters.filter_array_effect(self, predicate)

    def scan[S](
        self, initial: S, f: Callable[[S, OutElem_co], S]
    ) -> Channel[S, OutErr_co, OutDone_co, InElem_contra, InErr_contra, InDone_contra, Env_co]:
        """Write ``initial``, then each state ``f`` folds the items into."""
        from pyfect.channel import _filters
        from pyfect.effect import sync

        return _filters.scan_effect(self, initial, lambda s, a: sync(lambda: f(s, a)))

    def scan_effect[S, E2 = Never, R2 = Never](
        self, initial: S, f: Callable[[S, OutElem_co], Effect[S, E2, R2]]
    ) -> Channel[
        S, OutErr_co | E2, OutDone_co, InElem_contra, InErr_contra, InDone_contra, Env_co | R2
    ]:
        """``scan`` with an effectful ``f``."""
        from pyfect.channel import _filters

        return _filters.scan_effect(self, initial, f)

    @overload
    def map_accum[S, B](
        self,
        initial: Callable[[], S],
        f: Callable[[S, OutElem_co], tuple[S, Sequence[B]]],
        *,
        on_halt: Callable[[S], Sequence[B]] | None = None,
    ) -> Channel[B, OutErr_co, OutDone_co, InElem_contra, InErr_contra, InDone_contra, Env_co]: ...
    @overload
    def map_accum[S, B, E2 = Never, R2 = Never](
        self,
        initial: Callable[[], S],
        f: Callable[[S, OutElem_co], Effect[tuple[S, Sequence[B]], E2, R2]],
        *,
        on_halt: Callable[[S], Sequence[B]] | None = None,
    ) -> Channel[
        B, OutErr_co | E2, OutDone_co, InElem_contra, InErr_contra, InDone_contra, Env_co | R2
    ]: ...
    def map_accum(
        self,
        initial: Callable[[], Any],
        f: Callable[[Any, Any], Any],
        *,
        on_halt: Callable[[Any], Sequence[Any]] | None = None,
    ) -> Channel[Any, Any, Any, Any, Any, Any, Any]:
        """Thread a state through the items: ``f(state, item)`` gives the
        next state and the items to write (or an effect of both). When
        upstream stops, ``on_halt(state)`` gives the last items to write."""
        from pyfect.channel import _filters

        return _filters.map_accum(self, initial, f, on_halt)

    # --- sequencing -----------------------------------------------------------

    def concat_with[O2, E2 = Never, D2 = None, R2 = Never](
        self,
        f: Callable[
            [OutDone_co], Channel[O2, E2, D2, InElem_contra, InErr_contra, InDone_contra, R2]
        ],
    ) -> Channel[
        OutElem_co | O2, OutErr_co | E2, D2, InElem_contra, InErr_contra, InDone_contra, Env_co | R2
    ]:
        """When this channel ends, go on with ``f(done)`` on the same
        upstream. This channel's resources are released first."""
        from pyfect.channel import _combinators

        return _combinators.concat_with(self, f)

    def concat[O2, E2 = Never, D2 = None, R2 = Never](
        self, that: Channel[O2, E2, D2, InElem_contra, InErr_contra, InDone_contra, R2]
    ) -> Channel[
        OutElem_co | O2, OutErr_co | E2, D2, InElem_contra, InErr_contra, InDone_contra, Env_co | R2
    ]:
        """Write this channel's items, then ``that``'s, ending as ``that``."""
        from pyfect.channel import _combinators

        require_channel(that, "that")
        return _combinators.concat_with(self, lambda _: that)

    def or_else_if_empty[O2, E2 = Never, D2 = None, R2 = Never](
        self,
        f: Callable[
            [OutDone_co], Channel[O2, E2, D2, InElem_contra, InErr_contra, InDone_contra, R2]
        ],
    ) -> Channel[
        OutElem_co | O2,
        OutErr_co | E2,
        OutDone_co | D2,
        InElem_contra,
        InErr_contra,
        InDone_contra,
        Env_co | R2,
    ]:
        """Go on with ``f(done)`` if this channel ends without writing."""
        from pyfect.channel import _combinators

        return _combinators.or_else_if_empty(self, f)

    @overload
    def combine[O2, E2, D2, S, B, L = None, RR = Never](
        self,
        that: Channel[O2, E2, D2, InElem_contra, InErr_contra, InDone_contra, RR],
        initial: Callable[[], S],
        f: Callable[
            [S, Pull[OutElem_co, OutErr_co, OutDone_co], Pull[O2, E2, D2]],
            Effect[tuple[B, S], Done[L], RR],
        ],
    ) -> Channel[B, Never, L, InElem_contra, InErr_contra, InDone_contra, Env_co | RR]: ...
    @overload
    def combine[O2, E2, D2, S, B, L = None, EE = Never, RR = Never](
        self,
        that: Channel[O2, E2, D2, InElem_contra, InErr_contra, InDone_contra, RR],
        initial: Callable[[], S],
        f: Callable[
            [S, Pull[OutElem_co, OutErr_co, OutDone_co], Pull[O2, E2, D2]],
            Effect[tuple[B, S], EE | Done[L], RR],
        ],
    ) -> Channel[B, EE, L, InElem_contra, InErr_contra, InDone_contra, Env_co | RR]: ...
    def combine(
        self,
        that: Channel[Any, Any, Any, Any, Any, Any, Any],
        initial: Callable[[], Any],
        f: Callable[[Any, Any, Any], Effect[tuple[Any, Any], Any, Any]],
    ) -> Channel[Any, Any, Any, Any, Any, Any, Any]:
        """Write what ``f(state, left, right)`` makes from the two pulls,
        threading its state. ``f`` ends the channel by failing with
        ``Done``."""
        from pyfect.channel import _combinators

        require_channel(that, "that")
        return _combinators.combine(self, that, initial, f)

    def pipe_to[O2, E2 = Never, D2 = None, R2 = Never](
        self, that: Channel[O2, E2, D2, OutElem_co, OutErr_co, OutDone_co, R2]
    ) -> Channel[O2, E2, D2, InElem_contra, InErr_contra, InDone_contra, Env_co | R2]:
        """Feed this channel's output to ``that`` as its upstream."""
        from pyfect.channel import _combinators

        require_channel(that, "that")
        return _combinators.pipe_to(self, that)

    def pipe_to_or_fail[O2, E2 = Never, D2 = None, R2 = Never](
        self, that: Channel[O2, E2, D2, OutElem_co, Never, OutDone_co, R2]
    ) -> Channel[O2, OutErr_co | E2, D2, InElem_contra, InErr_contra, InDone_contra, Env_co | R2]:
        """``pipe_to`` for a ``that`` that cannot see upstream failures: they
        pass through ``that`` untouched (its error handlers never see them)
        and fail the channel."""
        from pyfect.channel import _upstream

        require_channel(that, "that")
        return _upstream.pipe_to_or_fail(self, that)


def _identity[T](value: T) -> T:
    return value
