"""``Channel`` methods about a channel's life: effects at its start, first
item, end and exit; spans and services around it; and running it again
(``repeat``, ``forever``) or pacing it (``schedule``)."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Never, Unpack, overload

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
    from pyfect.cause import Cause
    from pyfect.channel._channel import Channel
    from pyfect.context import TagLike
    from pyfect.exit import Exit
    from pyfect.schedule import Schedule
    from pyfect.schedule._model import SetInputType
    from pyfect.tracer import SpanOptions


class LifecycleMethods(
    ChannelBase[
        OutElem_co, OutErr_co, OutDone_co, InElem_contra, InErr_contra, InDone_contra, Env_co
    ]
):
    __slots__ = ()

    def on_start[E2 = Never, R2 = Never](
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
        """Run ``eff`` on the first pull, before the channel starts."""
        from pyfect._effect_args import require_effect
        from pyfect.channel import _lifecycle

        require_effect(eff, "eff")
        return _lifecycle.on_start(self, eff)

    def on_first[E2 = Never, R2 = Never](
        self, f: Callable[[OutElem_co], Effect[object, E2, R2]]
    ) -> Channel[
        OutElem_co,
        OutErr_co | E2,
        OutDone_co,
        InElem_contra,
        InErr_contra,
        InDone_contra,
        Env_co | R2,
    ]:
        """Run ``f`` on the first item, before writing it."""
        from pyfect.channel import _lifecycle

        return _lifecycle.on_first(self, f)

    def on_end[E2 = Never, R2 = Never](
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
        """Run ``eff`` when the channel ends (not when it fails)."""
        from pyfect._effect_args import require_effect
        from pyfect.channel import _lifecycle

        require_effect(eff, "eff")
        return _lifecycle.on_end(self, eff)

    def on_exit[R2 = Never](
        self, f: Callable[[Exit[OutDone_co, OutErr_co]], Effect[object, Never, R2]]
    ) -> Channel[
        OutElem_co, OutErr_co, OutDone_co, InElem_contra, InErr_contra, InDone_contra, Env_co | R2
    ]:
        """Run ``f(exit)`` as soon as the channel ends or fails, or when its
        run stops early."""
        from pyfect.channel import _lifecycle

        return _lifecycle.on_exit(self, f)

    def on_error[R2 = Never](
        self, f: Callable[[Cause[OutErr_co]], Effect[object, Never, R2]]
    ) -> Channel[
        OutElem_co, OutErr_co, OutDone_co, InElem_contra, InErr_contra, InDone_contra, Env_co | R2
    ]:
        """``on_exit`` for a failure (or an early stop that interrupts)."""
        from pyfect.channel import _lifecycle

        return _lifecycle.on_exit(self, lambda ex: ex.match(on_success=_void, on_failure=f))

    def ensuring[R2 = Never](
        self, finalizer: Effect[object, Never, R2]
    ) -> Channel[
        OutElem_co, OutErr_co, OutDone_co, InElem_contra, InErr_contra, InDone_contra, Env_co | R2
    ]:
        """Run ``finalizer`` however the channel stops."""
        from pyfect._effect_args import require_effect
        from pyfect.channel import _lifecycle

        require_effect(finalizer, "finalizer")
        return _lifecycle.on_exit(self, lambda _: finalizer)

    def with_span(
        self, name: str, **options: Unpack[SpanOptions]
    ) -> Channel[
        OutElem_co, OutErr_co, OutDone_co, InElem_contra, InErr_contra, InDone_contra, Env_co
    ]:
        """Run inside a new span, the parent of the spans made inside. It
        ends with the channel's exit."""
        from pyfect.channel import _lifecycle

        return _lifecycle.with_span(self, name, options)

    def update_service[S, T](
        self, tag: TagLike[S, T], f: Callable[[S], S]
    ) -> Channel[
        OutElem_co, OutErr_co, OutDone_co, InElem_contra, InErr_contra, InDone_contra, Env_co | T
    ]:
        """Run with ``f`` applied to the service of ``tag``, which this
        channel then needs."""
        from pyfect.channel import _context

        return _context.update_context_with(self, lambda ctx: ctx.add(tag, f(ctx.unsafe_get(tag))))

    # --- repetition -----------------------------------------------------------

    @overload
    def repeat[EE = Never, RR = Never](
        self, schedule: Schedule[object, OutDone_co, EE, RR], /
    ) -> Channel[
        OutElem_co,
        OutErr_co | EE,
        OutDone_co,
        InElem_contra,
        InErr_contra,
        InDone_contra,
        Env_co | RR,
    ]: ...
    @overload
    def repeat[O, E, D, I, IE, ID, R, EE = Never, RR = Never](
        self: LifecycleMethods[O, E, D, I, IE, ID, R],
        builder: Callable[[SetInputType[D]], Schedule[object, D, EE, RR]],
        /,
    ) -> Channel[O, E | EE, D, I, IE, ID, R | RR]: ...
    def repeat(
        self, schedule: Schedule[Any, Any, Any, Any] | Callable[[Any], Any], /
    ) -> Channel[Any, Any, Any, Any, Any, Any, Any]:
        """Run the channel again after each end, stepping ``schedule`` with
        its end value, until the schedule stops; then end with the last
        end value. Each run sees its step's ``schedule.CurrentMetadata``."""
        from pyfect.channel import _repeat

        return _repeat.repeat(self, schedule)

    def forever(
        self,
    ) -> Channel[OutElem_co, OutErr_co, Never, InElem_contra, InErr_contra, InDone_contra, Env_co]:
        """Run the channel again each time it ends, until it fails."""
        from pyfect.channel import _repeat

        return _repeat.forever(self)

    def schedule[SO, EE = Never, RR = Never](
        self, schedule: Schedule[SO, OutElem_co, EE, RR]
    ) -> Channel[
        OutElem_co,
        OutErr_co | EE,
        OutDone_co | SO,
        InElem_contra,
        InErr_contra,
        InDone_contra,
        Env_co | RR,
    ]:
        """Step ``schedule`` with each item, writing it after the step's
        delay; when the schedule stops, end with its output (dropping the
        item that stopped it)."""
        from pyfect.channel import _repeat

        return _repeat.schedule(self, schedule)


def _void(_: object) -> Effect[None]:
    from pyfect.effect import void

    return void
