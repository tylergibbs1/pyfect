"""``Channel`` methods that run channels or effects alongside each other:
merging, switching, buffering, and stopping a channel when an effect
finishes."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Literal, Never, overload

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
    from pyfect.queue import Strategy

type HaltStrategy = Literal["left", "right", "both", "either"]


class ConcurrencyMethods(
    ChannelBase[
        OutElem_co, OutErr_co, OutDone_co, InElem_contra, InErr_contra, InDone_contra, Env_co
    ]
):
    __slots__ = ()

    def merge[O2, E2 = Never, D2 = None, R2 = Never](
        self,
        that: Channel[O2, E2, D2, InElem_contra, InErr_contra, InDone_contra, R2],
        *,
        halt_strategy: HaltStrategy = "both",
    ) -> Channel[
        OutElem_co | O2,
        OutErr_co | E2,
        OutDone_co | D2,
        InElem_contra,
        InErr_contra,
        InDone_contra,
        Env_co | R2,
    ]:
        """Run both channels at once, writing items as either writes them.
        The merge ends when both have ended, or just the ``"left"``
        (``self``) or ``"right"`` one, or ``"either"``; a failure of either
        fails it at once."""
        from pyfect.channel import _merge

        require_channel(that, "that")
        return _merge.merge(self, that, halt_strategy)

    def merge_effect[E2 = Never, R2 = Never](
        self, eff: Effect[object, E2, R2]
    ) -> Channel[
        OutElem_co,
        OutErr_co | E2,
        OutDone_co,
        InElem_contra,
        InErr_contra,
        InDone_contra,
        Env_co | R2,
    ]:
        """Run ``eff`` alongside the channel: its failure fails the channel;
        it is interrupted when the channel ends."""
        from pyfect.channel import _merge

        return _merge.merge_effect(self, eff)

    def merge_all[O, D1, D, I, IE, ID, EE = Never, RR = Never](
        self: ConcurrencyMethods[ChannelBase[O, EE, D1, I, IE, ID, RR], EE, D, I, IE, ID, RR],
        *,
        concurrency: Concurrency,
        buffer_size: int = 16,
        switch: bool = False,
    ) -> Channel[O, EE, D, I, IE, ID, RR]:
        """Run the channels this channel writes, up to ``concurrency`` at
        once, writing their items as they come (at most ``buffer_size``
        waiting). With ``switch``, a new channel past the limit interrupts
        the oldest one instead of waiting for it."""
        from pyfect.channel import _merge

        return _merge.merge_all(self, concurrency, buffer_size, switch=switch)

    def switch_map[O2, E2 = Never, D2 = None, R2 = Never](
        self,
        f: Callable[
            [OutElem_co], Channel[O2, E2, D2, InElem_contra, InErr_contra, InDone_contra, R2]
        ],
        *,
        concurrency: Concurrency = 1,
        buffer_size: int = 16,
    ) -> Channel[
        O2, OutErr_co | E2, OutDone_co, InElem_contra, InErr_contra, InDone_contra, Env_co | R2
    ]:
        """``flat_map`` where each new item interrupts the oldest running
        channel once ``concurrency`` are running."""
        from pyfect.channel import _combinators, _merge

        return _merge.merge_all(_combinators.map_(self, f), concurrency, buffer_size, switch=True)

    @overload
    def buffer(
        self, *, capacity: Literal["unbounded"]
    ) -> Channel[
        OutElem_co, OutErr_co, OutDone_co, InElem_contra, InErr_contra, InDone_contra, Env_co
    ]: ...
    @overload
    def buffer(
        self, *, capacity: int, strategy: Strategy = "suspend"
    ) -> Channel[
        OutElem_co, OutErr_co, OutDone_co, InElem_contra, InErr_contra, InDone_contra, Env_co
    ]: ...
    def buffer(
        self, *, capacity: int | Literal["unbounded"], strategy: Strategy = "suspend"
    ) -> Channel[
        OutElem_co, OutErr_co, OutDone_co, InElem_contra, InErr_contra, InDone_contra, Env_co
    ]:
        """Pull ahead on a fiber, keeping up to ``capacity`` items for the
        reader; a full buffer waits, or drops the new (``"dropping"``) or
        oldest (``"sliding"``) item."""
        from pyfect.channel import _merge

        return _merge.buffer(self, capacity, strategy, array=False)

    @overload
    def buffer_array[A, E, D, I, IE, ID, R](
        self: ConcurrencyMethods[tuple[A, ...], E, D, I, IE, ID, R],
        *,
        capacity: Literal["unbounded"],
    ) -> Channel[tuple[A, ...], E, D, I, IE, ID, R]: ...
    @overload
    def buffer_array[A, E, D, I, IE, ID, R](
        self: ConcurrencyMethods[tuple[A, ...], E, D, I, IE, ID, R],
        *,
        capacity: int,
        strategy: Strategy = "suspend",
    ) -> Channel[tuple[A, ...], E, D, I, IE, ID, R]: ...
    def buffer_array[A, E, D, I, IE, ID, R](
        self: ConcurrencyMethods[tuple[A, ...], E, D, I, IE, ID, R],
        *,
        capacity: int | Literal["unbounded"],
        strategy: Strategy = "suspend",
    ) -> Channel[tuple[A, ...], E, D, I, IE, ID, R]:
        """``buffer`` counting the items of each tuple; the reader gets all
        the buffered items at once."""
        from pyfect.channel import _merge

        return _merge.buffer(self, capacity, strategy, array=True)

    def interrupt_when[D2, E2 = Never, R2 = Never](
        self, eff: Effect[D2, E2, R2]
    ) -> Channel[
        OutElem_co,
        OutErr_co | E2,
        OutDone_co | D2,
        InElem_contra,
        InErr_contra,
        InDone_contra,
        Env_co | R2,
    ]:
        """Run ``eff`` alongside the channel; when it succeeds, interrupt the
        channel and end with its value; when it fails, fail."""
        from pyfect._effect_args import require_effect
        from pyfect.channel import _merge

        require_effect(eff, "eff")
        return _merge.interrupt_when(self, eff)

    def halt_when[D2, E2 = Never, R2 = Never](
        self, eff: Effect[D2, E2, R2]
    ) -> Channel[
        OutElem_co,
        OutErr_co | E2,
        OutDone_co | D2,
        InElem_contra,
        InErr_contra,
        InDone_contra,
        Env_co | R2,
    ]:
        """Run ``eff`` alongside the channel; once it has finished, the next
        pull ends with its value (or fails with its failure) instead of
        pulling."""
        from pyfect._effect_args import require_effect
        from pyfect.channel import _merge

        require_effect(eff, "eff")
        return _merge.halt_when(self, eff)

    @overload
    def embed_input[O, E, D, R, I, ID, R2 = Never](
        self: ConcurrencyMethods[O, E, D, Never, Never, None, R],
        input: Callable[[Effect[I, Done[ID]]], Effect[object, Never, R2]],
    ) -> Channel[O, E, D, I, Never, ID, R | R2]: ...
    @overload
    def embed_input[O, E, D, R, I, IE, ID, R2 = Never](
        self: ConcurrencyMethods[O, E, D, Never, Never, None, R],
        input: Callable[[Pull[I, IE, ID]], Effect[object, Never, R2]],
    ) -> Channel[O, E, D, I, IE, ID, R | R2]: ...
    def embed_input(
        self, input: Callable[[Any], Effect[object, Never, Any]]
    ) -> Channel[Any, Any, Any, Any, Any, Any, Any]:
        """A channel that hands its upstream to ``input``, run on a fiber,
        and runs this channel with no upstream."""
        from pyfect.channel import _merge

        return _merge.embed_input(self, input)
