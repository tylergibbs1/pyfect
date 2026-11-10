"""``Stream`` methods that feed the stream to a ``Sink``: ``run``,
``transduce``, ``aggregate``, ``aggregate_within``, ``grouped_within``,
``pipe_through``, ``tap_sink`` and ``peel``. The work is in
``pyfect.stream._sinking``."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Never, overload

from pyfect.stream._base import A_co, E_co, R_co, StreamBase

if TYPE_CHECKING:
    from pyfect._core import Effect
    from pyfect.duration import Input as DurationInput
    from pyfect.option import Option
    from pyfect.schedule import Schedule
    from pyfect.scope import Scope
    from pyfect.sink import Sink
    from pyfect.stream._stream import Stream


def _require_sink(sink: object) -> None:
    from pyfect.sink._sink import require_sink

    require_sink(sink, "sink")


class SinkMethods(StreamBase[A_co, E_co, R_co]):
    __slots__ = ()

    def run[B, L, E2 = Never, R2 = Never](
        self, sink: Sink[B, A_co, L, E2, R2]
    ) -> Effect[B, E_co | E2, R_co | R2]:
        """Run the stream into ``sink`` and succeed with the sink's value.
        The stream's failures pass by the sink's error handlers."""
        from pyfect.stream import _sinking

        _require_sink(sink)
        return _sinking.run(self, sink)

    # A stream of ``Never`` has no items to leave over, so it takes any
    # sink; the overload keeps pyright from reading ``A`` as ``Never``.
    @overload
    def transduce[B, E, R, E2 = Never, R2 = Never](
        self: SinkMethods[Never, E, R], sink: Sink[B, Never, object, E2, R2]
    ) -> Stream[B, E | E2, R | R2]: ...
    @overload
    def transduce[A, E, R, B, E2 = Never, R2 = Never](
        self: SinkMethods[A, E, R], sink: Sink[B, A, A, E2, R2]
    ) -> Stream[B, E | E2, R | R2]: ...
    def transduce(self, sink: Sink[Any, Any, Any, Any, Any]) -> Stream[Any, Any, Any]:
        """Run ``sink`` again and again on the stream, writing each value it
        ends with; its leftovers start the next run. A stream failure ends
        the current run first."""
        from pyfect.stream import _sinking

        _require_sink(sink)
        return _sinking.transduce(self, sink)

    @overload
    def aggregate[B, E, R, E2 = Never, R2 = Never](
        self: SinkMethods[Never, E, R], sink: Sink[B, Never, object, E2, R2]
    ) -> Stream[B, E | E2, R | R2]: ...
    @overload
    def aggregate[A, E, R, B, E2 = Never, R2 = Never](
        self: SinkMethods[A, E, R], sink: Sink[B, A, A, E2, R2]
    ) -> Stream[B, E | E2, R | R2]: ...
    def aggregate(self, sink: Sink[Any, Any, Any, Any, Any]) -> Stream[Any, Any, Any]:
        """``transduce`` while the stream keeps running: a fiber pulls the
        stream as ``sink`` asks for input, and each run of the sink ends
        when the sink is done."""
        from pyfect import schedule
        from pyfect.stream import _sinking

        _require_sink(sink)
        return _sinking.aggregate_within(self, sink, schedule.forever)

    @overload
    def aggregate_within[B, E, R, EE = Never, RR = Never](
        self: SinkMethods[Never, E, R],
        sink: Sink[B, Never, object, EE, RR],
        schedule: Schedule[object, Option[B], EE, RR],
    ) -> Stream[B, E | EE, R | RR]: ...
    @overload
    def aggregate_within[A, E, R, B, EE = Never, RR = Never](
        self: SinkMethods[A, E, R],
        sink: Sink[B, A, A, EE, RR],
        schedule: Schedule[object, Option[B], EE, RR],
    ) -> Stream[B, E | EE, R | RR]: ...
    def aggregate_within(
        self,
        sink: Sink[Any, Any, Any, Any, Any],
        schedule: Schedule[Any, Any, Any, Any],
    ) -> Stream[Any, Any, Any]:
        """``aggregate``, also ending each run of ``sink`` when ``schedule``
        says so. The schedule steps once input arrives (with the last value
        written) and its clock leaves out the time between runs; a schedule
        that stops ends the stream once the sink has drained its
        leftovers."""
        from pyfect.stream import _sinking

        _require_sink(sink)
        return _sinking.aggregate_within(self, sink, schedule)

    def grouped_within(
        self, chunk_size: int, duration: DurationInput
    ) -> Stream[list[A_co], E_co, R_co]:
        """Group the items in lists of up to ``chunk_size`` (at least 1),
        ending a group early once ``duration`` has passed since its first
        item."""
        from pyfect import schedule
        from pyfect.sink import take
        from pyfect.stream import _sinking

        return _sinking.aggregate_within(self, take(max(chunk_size, 1)), schedule.spaced(duration))

    def pipe_through[B, L, E2 = Never, R2 = Never](
        self, sink: Sink[B, A_co, L, E2, R2]
    ) -> Stream[L, E_co | E2, R_co | R2]:
        """Run the stream into ``sink`` and write the sink's leftovers. The
        stream's failures pass by the sink's error handlers."""
        from pyfect.stream import _sinking

        _require_sink(sink)
        return _sinking.pipe_through(self, sink)

    def tap_sink[E2 = Never, R2 = Never](
        self, sink: Sink[object, A_co, object, E2, R2]
    ) -> Stream[A_co, E_co | E2, R_co | R2]:
        """Send each chunk to ``sink`` too, as it is written. The stream
        waits for the sink to take each chunk; once the sink is done it
        goes on alone, and a sink failure fails the stream."""
        from pyfect.stream import _sinking

        _require_sink(sink)
        return _sinking.tap_sink(self, sink)

    @overload
    def peel[B, E, R, E2 = Never, R2 = Never](
        self: SinkMethods[Never, E, R], sink: Sink[B, Never, object, E2, R2]
    ) -> Effect[tuple[B, Stream[Never, E]], E | E2, Scope | R | R2]: ...
    @overload
    def peel[A, E, R, B, E2 = Never, R2 = Never](
        self: SinkMethods[A, E, R], sink: Sink[B, A, A, E2, R2]
    ) -> Effect[tuple[B, Stream[A, E]], E | E2, Scope | R | R2]: ...
    def peel(self, sink: Sink[Any, Any, Any, Any, Any]) -> Effect[Any, Any, Any]:
        """Run ``sink`` on the start of the stream and succeed with its value
        and the rest of the stream (the sink's leftovers first). The rest
        reads the stream's pull, which lives in the current ``Scope``."""
        from pyfect.stream import _sinking

        _require_sink(sink)
        return _sinking.peel(self, sink)
