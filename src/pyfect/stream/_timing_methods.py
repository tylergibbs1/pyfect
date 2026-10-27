"""``Stream`` methods about time and lifetime: schedules, repeats,
timeouts, debouncing, throttling, buffering, stopping a stream when an
effect finishes, and running effects as the stream starts and stops."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Literal, Never, overload

from pyfect.stream._base import A_co, E_co, R_co, StreamBase

if TYPE_CHECKING:
    from pyfect._core import Effect
    from pyfect.cause import Cause
    from pyfect.duration import Duration
    from pyfect.exit import Exit
    from pyfect.queue import Strategy
    from pyfect.schedule import Schedule
    from pyfect.schedule._model import SetInputType
    from pyfect.stream._stream import Stream

type ThrottleStrategy = Literal["shape", "enforce"]


class TimingMethods(StreamBase[A_co, E_co, R_co]):
    __slots__ = ()

    # --- schedules and repeats ------------------------------------------------

    def schedule[EE = Never, RR = Never](
        self, schedule: Schedule[object, A_co, EE, RR]
    ) -> Stream[A_co, E_co | EE, R_co | RR]:
        """Step ``schedule`` with each item, writing it (one per chunk) after
        the step's delay; end when the schedule stops, dropping the item
        that stopped it."""
        from pyfect.stream import _timing

        return _timing.schedule(self, schedule)

    @overload
    def repeat[EE = Never, RR = Never](
        self, schedule: Schedule[object, None, EE, RR], /
    ) -> Stream[A_co, E_co | EE, R_co | RR]: ...
    @overload
    def repeat[EE = Never, RR = Never](
        self, builder: Callable[[SetInputType[None]], Schedule[object, None, EE, RR]], /
    ) -> Stream[A_co, E_co | EE, R_co | RR]: ...
    def repeat(
        self, schedule: Schedule[Any, Any, Any, Any] | Callable[[Any], Any], /
    ) -> Stream[Any, Any, Any]:
        """Run the stream again after each end, while ``schedule`` recurs.
        Each run sees its step's ``schedule.CurrentMetadata``."""
        from pyfect.stream._stream import Stream

        return Stream(self._channel.repeat(schedule))

    def repeat_elements[EE = Never, RR = Never](
        self, schedule: Schedule[object, A_co, EE, RR]
    ) -> Stream[A_co, E_co | EE, R_co | RR]:
        """Write each item, then again each time ``schedule`` (stepped with
        it, fresh for each item) recurs."""
        from pyfect.stream import _timing

        return _timing.repeat_elements(self, schedule)

    def forever(self) -> Stream[A_co, E_co, R_co]:
        """Run the stream again each time it ends, until it fails."""
        from pyfect.stream._stream import Stream

        forever: Any = self._channel.forever()
        return Stream(forever)

    # --- timeouts, debouncing and throttling ----------------------------------

    def timeout(self, duration: Duration) -> Stream[A_co, E_co, R_co]:
        """End the stream if a pull waits ``duration`` for its chunk."""
        from pyfect.stream import _timing

        return _timing.timeout_or_else(self, duration, None)

    def timeout_or_else[B, E2 = Never, R2 = Never](
        self, duration: Duration, or_else: Callable[[], Stream[B, E2, R2]]
    ) -> Stream[A_co | B, E_co | E2, R_co | R2]:
        """Go on with ``or_else()`` if a pull waits ``duration`` for its
        chunk."""
        from pyfect.stream import _timing

        return _timing.timeout_or_else(self, duration, or_else)

    def debounce(self, duration: Duration) -> Stream[A_co, E_co, R_co]:
        """Write the last item of a burst once ``duration`` passes without a
        new chunk; earlier items of the burst are dropped."""
        from pyfect.stream import _timing

        return _timing.debounce(self, duration)

    def throttle(
        self,
        *,
        cost: Callable[[tuple[A_co, ...]], float],
        units: float,
        duration: Duration,
        burst: float = 0,
        strategy: ThrottleStrategy = "shape",
    ) -> Stream[A_co, E_co, R_co]:
        """Limit the stream to ``units`` of ``cost`` per ``duration``, with a
        bucket of up to ``units + burst`` tokens: ``"shape"`` delays a chunk
        until its tokens are there, ``"enforce"`` drops it."""
        from pyfect.effect import succeed
        from pyfect.stream import _timing

        return _timing.throttle(
            self,
            lambda chunk: succeed(cost(chunk)),
            units,
            duration,
            burst=burst,
            strategy=strategy,
        )

    def throttle_effect[E2 = Never, R2 = Never](
        self,
        *,
        cost: Callable[[tuple[A_co, ...]], Effect[float, E2, R2]],
        units: float,
        duration: Duration,
        burst: float = 0,
        strategy: ThrottleStrategy = "shape",
    ) -> Stream[A_co, E_co | E2, R_co | R2]:
        """``throttle`` with an effectful ``cost``."""
        from pyfect.stream import _timing

        return _timing.throttle(self, cost, units, duration, burst=burst, strategy=strategy)

    # --- buffering --------------------------------------------------------------

    @overload
    def buffer(self, *, capacity: Literal["unbounded"]) -> Stream[A_co, E_co, R_co]: ...
    @overload
    def buffer(
        self, *, capacity: int, strategy: Strategy = "suspend"
    ) -> Stream[A_co, E_co, R_co]: ...
    def buffer(
        self, *, capacity: int | Literal["unbounded"], strategy: Strategy = "suspend"
    ) -> Stream[A_co, E_co, R_co]:
        """Pull ahead on a fiber, keeping up to ``capacity`` items for the
        reader; a full buffer waits, or drops the new (``"dropping"``) or
        oldest (``"sliding"``) items."""
        from pyfect.stream._stream import Stream

        if capacity == "unbounded":
            return Stream(self._channel.buffer_array(capacity=capacity))
        return Stream(self._channel.buffer_array(capacity=capacity, strategy=strategy))

    @overload
    def buffer_array(self, *, capacity: Literal["unbounded"]) -> Stream[A_co, E_co, R_co]: ...
    @overload
    def buffer_array(
        self, *, capacity: int, strategy: Strategy = "suspend"
    ) -> Stream[A_co, E_co, R_co]: ...
    def buffer_array(
        self, *, capacity: int | Literal["unbounded"], strategy: Strategy = "suspend"
    ) -> Stream[A_co, E_co, R_co]:
        """``buffer`` counting chunks rather than items."""
        from pyfect.stream._stream import Stream

        if capacity == "unbounded":
            return Stream(self._channel.buffer(capacity=capacity))
        return Stream(self._channel.buffer(capacity=capacity, strategy=strategy))

    # --- stopping ---------------------------------------------------------------

    def halt_when[E2 = Never, R2 = Never](
        self, eff: Effect[object, E2, R2]
    ) -> Stream[A_co, E_co | E2, R_co | R2]:
        """Run ``eff`` alongside; once it has finished, the next pull ends
        the stream (or fails with ``eff``'s failure) instead of pulling."""
        from pyfect._effect_args import require_effect
        from pyfect.stream._stream import Stream

        require_effect(eff, "eff")
        halted: Any = self._channel.halt_when(eff)
        return Stream(halted)

    def interrupt_when[E2 = Never, R2 = Never](
        self, eff: Effect[object, E2, R2]
    ) -> Stream[A_co, E_co | E2, R_co | R2]:
        """Run ``eff`` alongside; when it succeeds, interrupt the stream and
        end; when it fails, fail."""
        from pyfect._effect_args import require_effect
        from pyfect.stream._stream import Stream

        require_effect(eff, "eff")
        interrupted: Any = self._channel.interrupt_when(eff)
        return Stream(interrupted)

    # --- lifetime ---------------------------------------------------------------

    def on_start[E2 = Never, R2 = Never](
        self, eff: Effect[object, E2, R2]
    ) -> Stream[A_co, E_co | E2, R_co | R2]:
        """Run ``eff`` on the first pull, before the stream starts."""
        from pyfect._effect_args import require_effect
        from pyfect.stream._stream import Stream

        require_effect(eff, "eff")
        return Stream(self._channel.on_start(eff))

    def on_first[E2 = Never, R2 = Never](
        self, f: Callable[[A_co], Effect[object, E2, R2]]
    ) -> Stream[A_co, E_co | E2, R_co | R2]:
        """Run ``f`` on the first item, before writing it."""
        from pyfect.stream._stream import Stream

        return Stream(self._channel.on_first(lambda chunk: f(chunk[0])))

    def on_end[E2 = Never, R2 = Never](
        self, eff: Effect[object, E2, R2]
    ) -> Stream[A_co, E_co | E2, R_co | R2]:
        """Run ``eff`` when the stream ends (not when it fails)."""
        from pyfect._effect_args import require_effect
        from pyfect.stream._stream import Stream

        require_effect(eff, "eff")
        return Stream(self._channel.on_end(eff))

    def on_exit[R2 = Never](
        self, f: Callable[[Exit[None, E_co]], Effect[object, Never, R2]]
    ) -> Stream[A_co, E_co, R_co | R2]:
        """Run ``f(exit)`` as soon as the stream ends or fails, or when its
        run stops early."""
        from pyfect.stream._stream import Stream

        return Stream(self._channel.on_exit(f))

    def on_error[R2 = Never](
        self, f: Callable[[Cause[E_co]], Effect[object, Never, R2]]
    ) -> Stream[A_co, E_co, R_co | R2]:
        """``on_exit`` for a failure (or an early stop that interrupts)."""
        from pyfect.stream._stream import Stream

        return Stream(self._channel.on_error(f))

    def ensuring[R2 = Never](
        self, finalizer: Effect[object, Never, R2]
    ) -> Stream[A_co, E_co, R_co | R2]:
        """Run ``finalizer`` however the stream stops."""
        from pyfect._effect_args import require_effect
        from pyfect.stream._stream import Stream

        require_effect(finalizer, "finalizer")
        return Stream(self._channel.ensuring(finalizer))
