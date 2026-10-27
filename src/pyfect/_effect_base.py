"""What every effect and continuation frame shares: the step protocol and
the base of ``Effect``'s method groups.

A step is one of:

- another ``Effect``: evaluate it next
- a ``Success`` / ``Failure``: hand it to the next frame on the stack
- ``SUSPEND``: the fiber parked itself; a callback will resume it

``Effect`` (``pyfect._core``) is assembled from method groups, each a
subclass of ``EffectBase`` in a module of its own. ``as_effect`` lets a
group hand ``self`` to the primitives, which take an ``Effect``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Final, Generic, Never, TypeVar, cast, final

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
    """A continuation on the fiber's stack. Defaults pass results through."""

    __slots__ = ()

    def _on_success(self, value: Any, fiber: Fiber[Any, Any]) -> Step:
        return Success(value)

    def _on_failure(self, cause: Cause[Any], fiber: Fiber[Any, Any]) -> Step:
        return Failure(cause)


class EffectBase(Frame, Generic[A_co, E_co, R_co]):
    """The base of each group of ``Effect`` methods. Every instance is an
    ``Effect``: only ``Effect`` combines the groups, and nothing else
    subclasses them."""

    __slots__ = ()


def as_effect[A, E, R](group: EffectBase[A, E, R]) -> Effect[A, E, R]:
    """``self`` inside a method group, typed as the ``Effect`` it is."""
    return cast("Effect[A, E, R]", group)
