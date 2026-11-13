"""What every effect and continuation frame shares: the step protocol and
the base of ``Effect``'s method groups.

A step is one of:

- another ``Effect``: evaluate it next
- a ``Success`` / ``Failure``: hand it to the next frame on the stack
- ``succeed_with(value)``, from a frame: a success handed on as Effect's
  ``succeedWith`` does, counted as an op (see ``pyfect._fiber``)
- ``SUSPEND``: the fiber parked itself; a callback will resume it

``Effect`` (``pyfect._core``) is assembled from method groups, each a
subclass of ``EffectBase`` in a module of its own. ``as_effect`` lets a
group hand ``self`` to the primitives, which take an ``Effect``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar, Final, Generic, Never, TypeVar, cast, final

from pyfect.cause import Cause
from pyfect.exit import Failure, Success

if TYPE_CHECKING:
    from pyfect._core import Effect
    from pyfect._fiber import Fiber

A_co = TypeVar("A_co", covariant=True)
E_co = TypeVar("E_co", covariant=True, default=Never)
R_co = TypeVar("R_co", covariant=True, default=Never)


@final
class _SuspendMarker:
    __slots__ = ()

    def __repr__(self) -> str:
        return "SUSPEND"


SUSPEND: Final = _SuspendMarker()

type Step = Effect[Any, Any, Any] | Success[Any] | Failure[Any] | _SuspendMarker


class Frame:
    """A continuation on the fiber's stack. Defaults pass results through.

    The loop never pauses between a plain ``Exit`` a step or frame returns
    and the next frame, so a frame that claims state (takes a permit)
    returns the result that way, or through ``run_known``; never with
    ``succeed_with``, which the loop may pause before."""

    __slots__ = ()
    # ``run_known``'s wrapper sets it: the loop must not pause before it.
    _holds_decided: ClassVar[bool] = False

    def _on_success(self, value: Any, fiber: Fiber[Any, Any]) -> Step:
        return Success(value)

    def _on_failure(self, cause: Cause[Any], fiber: Fiber[Any, Any]) -> Step:
        return Failure(cause)


@final
class HandedOn(Success[Any]):
    """A frame's success handed on as Effect's ``succeedWith``: the loop
    counts it as an op, and every ``_INLINE_STEPS``-th one goes back
    through the loop, where the fiber may yield. Only the loop sees it: it
    never becomes a fiber's exit."""

    __slots__ = ()


def succeed_with(value: Any) -> Success[Any]:
    """What a frame that computes a value (``map``) returns: Effect's
    ``fiber.succeedWith(value)``."""
    return HandedOn(value)


class EffectBase(Frame, Generic[A_co, E_co, R_co]):
    """The base of each group of ``Effect`` methods. Every instance is an
    ``Effect``: only ``Effect`` combines the groups, and nothing else
    subclasses them."""

    __slots__ = ()


def as_effect[A, E, R](group: EffectBase[A, E, R]) -> Effect[A, E, R]:
    """``self`` inside a method group, typed as the ``Effect`` it is."""
    return cast("Effect[A, E, R]", group)
