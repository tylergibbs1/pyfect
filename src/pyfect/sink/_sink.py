"""The ``Sink`` type, its ``End`` and its methods.

A sink is a function from an upstream pull of non-empty tuples (and a
``CloseableScope``) to an effect that consumes some of that input and
succeeds with an ``End``: the sink's value and the input it read but did
not use (Effect v4's ``Sink.transform``). The upstream fails only with
``Done()``; a stream's own failures reach a sink as hidden defects, so no
sink error handler sees them (``Stream.run``).

The methods give their work to ``pyfect.sink._combinators``, imported when
called (it builds ``Sink`` values, so it loads after this module).
"""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Generic, Never, Self, TypeVar, overload

from pyfect._core import Effect, _Suspend
from pyfect._effect_args import wrong_argument
from pyfect.errors import Done

if TYPE_CHECKING:
    from pyfect.cause import Cause
    from pyfect.exit import Exit
    from pyfect.scope import CloseableScope

A_co = TypeVar("A_co", covariant=True)
In_contra = TypeVar("In_contra", contravariant=True, default=object)
L_co = TypeVar("L_co", covariant=True, default=Never)
E_co = TypeVar("E_co", covariant=True, default=Never)
R_co = TypeVar("R_co", covariant=True, default=Never)

type End[A, L = Never] = tuple[A, tuple[L, ...] | None]
"""What a sink ends with: its value, and the input it read but did not
use (a non-empty tuple, or ``None``). Effect's ``Sink.End``."""

type Upstream[In] = Effect[tuple[In, ...], Done]
"""What a sink reads: a pull of non-empty tuples that ends with
``Done()``."""

type Transform[A, In, L, E, R] = Callable[[Upstream[In], CloseableScope], Effect[End[A, L], E, R]]
"""What a sink is made of (see ``sink.from_transform``)."""


class Sink(Generic[A_co, In_contra, L_co, E_co, R_co]):
    """``Sink[A, In, L, E, R]``: reads ``In`` items until it has what it
    needs, then succeeds with ``A`` and leaves over the ``L`` items it read
    but did not use; or fails with ``E``. Needs the services ``R``.

    Build sinks with the functions in ``pyfect.sink`` and run them with
    ``Stream.run``. Methods keep or add to the type parameters; the
    combinators that remove services (``provide_service``,
    ``provide_context``) are functions in ``pyfect.sink``, used with
    ``.pipe``.
    """

    __slots__ = ("_build",)

    def __init__(self, transform: Transform[A_co, In_contra, L_co, E_co, R_co]) -> None:
        self._build: Transform[Any, Any, Any, Any, Any] = transform

    def _transform(self, upstream: Upstream[Any], scope: CloseableScope) -> Effect[End[Any, Any]]:
        """The effect consuming ``upstream``. Built when it runs, so a
        raising transform is a defect of the run."""
        build = self._build
        return _Suspend(lambda: build(upstream, scope))

    def pipe[B](self, f: Callable[[Self], B], /) -> B:
        """Apply ``f`` to this sink (one step; see ``Effect.pipe``)."""
        return f(self)

    # --- the value ---------------------------------------------------------

    def map[B](self, f: Callable[[A_co], B]) -> Sink[B, In_contra, L_co, E_co, R_co]:
        """The sink with its value replaced by ``f(value)``."""
        from pyfect.sink import _combinators

        return _combinators.map_end(self, lambda end: (f(end[0]), end[1]))

    def as_[B](self, value: B) -> Sink[B, In_contra, L_co, E_co, R_co]:
        """The sink with its value replaced by ``value``."""
        from pyfect.sink import _combinators

        return _combinators.map_end(self, lambda end: (value, end[1]))

    def map_effect[B, E2 = Never, R2 = Never](
        self, f: Callable[[A_co], Effect[B, E2, R2]]
    ) -> Sink[B, In_contra, L_co, E_co | E2, R_co | R2]:
        """The sink with its value replaced by what ``f(value)`` succeeds
        with."""
        from pyfect.sink import _combinators

        return _combinators.map_effect_end(self, lambda end: f(end[0]).map(lambda b: (b, end[1])))

    def map_end[B, L2 = Never](
        self, f: Callable[[End[A_co, L_co]], End[B, L2]]
    ) -> Sink[B, In_contra, L2, E_co, R_co]:
        """The sink with its whole ``End`` (value and leftovers) replaced by
        ``f(end)``."""
        from pyfect.sink import _combinators

        return _combinators.map_end(self, f)

    def map_effect_end[B, L2 = Never, E2 = Never, R2 = Never](
        self, f: Callable[[End[A_co, L_co]], Effect[End[B, L2], E2, R2]]
    ) -> Sink[B, In_contra, L2, E_co | E2, R_co | R2]:
        """``map_end`` with an effectful ``f``."""
        from pyfect.sink import _combinators

        return _combinators.map_effect_end(self, f)

    def summarized[S, B, E2 = Never, R2 = Never](
        self, summary: Effect[S, E2, R2], f: Callable[[S, S], B]
    ) -> Sink[tuple[A_co, B], In_contra, L_co, E_co | E2, R_co | R2]:
        """Run ``summary`` before and after the sink and pair its value with
        ``f(before, after)``."""
        from pyfect._effect_args import require_effect
        from pyfect.sink import _combinators

        require_effect(summary, "summary")
        return _combinators.summarized(self, summary, f)

    def with_duration(self) -> Sink[tuple[A_co, float], In_contra, L_co, E_co, R_co]:
        """Pair the value with how long the sink ran, in seconds, measured in
        whole monotonic nanoseconds."""
        from pyfect.sink import _combinators

        return _combinators.with_duration(self)

    # --- the input and the leftovers ---------------------------------------

    def map_input[In0](self, f: Callable[[In0], In_contra]) -> Sink[A_co, In0, L_co, E_co, R_co]:
        """A sink reading ``In0`` items, each given to this sink as
        ``f(item)``."""
        from pyfect.sink import _combinators

        return _combinators.map_input_array(self, lambda chunk: tuple(map(f, chunk)))

    def map_input_effect[In0, E2 = Never, R2 = Never](
        self, f: Callable[[In0], Effect[In_contra, E2, R2]]
    ) -> Sink[A_co, In0, L_co, E_co | E2, R_co | R2]:
        """``map_input`` with an effectful ``f``, run on each item in
        order."""
        from pyfect.sink import _combinators

        return _combinators.map_input_effect(self, f)

    def map_input_array[In0](
        self, f: Callable[[tuple[In0, ...]], tuple[In_contra, ...]]
    ) -> Sink[A_co, In0, L_co, E_co, R_co]:
        """A sink reading ``In0`` chunks, each given to this sink as
        ``f(chunk)``, which must be non-empty."""
        from pyfect.sink import _combinators

        return _combinators.map_input_array(self, f)

    def map_input_array_effect[In0, E2 = Never, R2 = Never](
        self, f: Callable[[tuple[In0, ...]], Effect[tuple[In_contra, ...], E2, R2]]
    ) -> Sink[A_co, In0, L_co, E_co | E2, R_co | R2]:
        """``map_input_array`` with an effectful ``f``."""
        from pyfect.sink import _combinators

        return _combinators.map_input_array_effect(self, f)

    def map_leftover[L2](self, f: Callable[[L_co], L2]) -> Sink[A_co, In_contra, L2, E_co, R_co]:
        """The sink with each leftover item replaced by ``f(item)``."""
        from pyfect.sink import _combinators

        return _combinators.map_end(
            self, lambda end: (end[0], None if end[1] is None else tuple(map(f, end[1])))
        )

    def ignore_leftover(self) -> Sink[A_co, In_contra, Never, E_co, R_co]:
        """The sink without its leftovers: what it read but did not use is
        dropped."""
        from pyfect.sink import _combinators

        return _combinators.map_end(self, lambda end: (end[0], None))

    # A sink without leftovers has none to feed on; the overload keeps
    # pyright from reading the input type off ``L = Never``.
    @overload
    def flat_map[I, B, L2 = Never, E2 = Never, R2 = Never](
        self: Sink[A_co, I, Never, E_co, R_co], f: Callable[[A_co], Sink[B, I, L2, E2, R2]]
    ) -> Sink[B, I, L2, E_co | E2, R_co | R2]: ...
    @overload
    def flat_map[I, B, L2 = Never, E2 = Never, R2 = Never](
        self: Sink[A_co, I, I, E_co, R_co], f: Callable[[A_co], Sink[B, I, L2, E2, R2]]
    ) -> Sink[B, I, I | L2, E_co | E2, R_co | R2]: ...
    def flat_map(
        self, f: Callable[[A_co], Sink[Any, Any, Any, Any, Any]]
    ) -> Sink[Any, Any, Any, Any, Any]:
        """Run this sink, then ``f(value)`` on the rest of the input, its
        leftovers first. Leftovers the second sink does not read stay
        leftovers."""
        from pyfect.sink import _combinators

        return _combinators.flat_map(self, f)

    # --- failures ----------------------------------------------------------

    def map_error[E2](self, f: Callable[[E_co], E2]) -> Sink[A_co, In_contra, L_co, E2, R_co]:
        """The sink with its typed error replaced by ``f(error)``."""
        from pyfect.sink import _combinators

        return _combinators.transform_effect(self, lambda eff: eff.map_error(f))

    def catch_all[B, E2 = Never, R2 = Never](
        self, f: Callable[[E_co], Effect[B, E2, R2]]
    ) -> Sink[A_co | B, In_contra, L_co, E2, R_co | R2]:
        """Recover from a typed failure with the value of ``f(error)``
        (Effect's ``Sink.catch``). The stream's own failures pass by."""
        from pyfect.sink import _combinators

        return _combinators.catch_all(self, f)

    def catch_cause[B, E2 = Never, R2 = Never](
        self, f: Callable[[Cause[E_co]], Effect[B, E2, R2]]
    ) -> Sink[A_co | B, In_contra, L_co, E2, R_co | R2]:
        """Recover from any failure of the sink with the value of
        ``f(cause)``. The stream's own failures pass by."""
        from pyfect.sink import _combinators

        return _combinators.catch_cause(self, f)

    def or_else[I, B, L2 = Never, E2 = Never, R2 = Never](
        self: Sink[A_co, I, L_co, E_co, R_co], f: Callable[[E_co], Sink[B, I, L2, E2, R2]]
    ) -> Sink[A_co | B, I, L_co | L2, E2, R_co | R2]:
        """After a typed failure, go on with ``f(error)`` on the rest of
        the input. The stream's own failures pass by."""
        from pyfect.sink import _combinators

        return _combinators.or_else(self, f)

    # --- finalizers --------------------------------------------------------

    def on_exit[R2 = Never](
        self, f: Callable[[Exit[A_co, E_co]], Effect[object, Never, R2]]
    ) -> Sink[A_co, In_contra, L_co, E_co, R_co | R2]:
        """Run ``f(exit)`` when the sink ends. A stream failure stops the
        sink as an interruption would, so ``f`` sees an interrupt."""
        from pyfect.sink import _combinators

        return _combinators.on_exit(self, f)

    def ensuring[R2 = Never](
        self, finalizer: Effect[object, Never, R2]
    ) -> Sink[A_co, In_contra, L_co, E_co, R_co | R2]:
        """Run ``finalizer`` however the sink ends."""
        from pyfect._effect_args import require_effect
        from pyfect.sink import _combinators

        require_effect(finalizer, "finalizer")
        return _combinators.on_exit(self, lambda _: finalizer)


type AnySink = Sink[Any, Any, Any, Any, Any]


def require_sink(value: object, name: str) -> None:
    """Raise ``TypeError`` naming ``name`` unless ``value`` is a ``Sink``."""
    if not isinstance(value, Sink):
        raise TypeError(wrong_argument(value, name, "a Sink", "build one with pyfect.sink"))
