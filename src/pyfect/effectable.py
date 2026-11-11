"""Classes whose instances are effects (Effect's ``Effectable`` module)::

    class Answer(effectable.Class[int]):
        def as_effect(self) -> fx.Effect[int]:
            return fx.succeed(42)

    yield from Answer()  # 42

Running an instance runs ``as_effect()``, again on every run. Effect's
``Mixin(Base)`` is multiple inheritance, ``class Boxed(effectable.Class[int],
Box)``; its ``Prototype`` is this class too (docs/PARITY.md section 4).
"""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from abc import ABCMeta, abstractmethod
from typing import TYPE_CHECKING, Any, Generic, Never, TypeVar

from pyfect._core import Effect, Step

if TYPE_CHECKING:
    from pyfect._fiber import Fiber


A_co = TypeVar("A_co", covariant=True)
E_co = TypeVar("E_co", covariant=True, default=Never)
R_co = TypeVar("R_co", covariant=True, default=Never)


class Class(Effect[A_co, E_co, R_co], Generic[A_co, E_co, R_co], metaclass=ABCMeta):
    """An effect defined by ``as_effect`` (Effect's ``Effectable.Class``)."""

    @abstractmethod
    def as_effect(self) -> Effect[A_co, E_co, R_co]:
        """The effect an instance runs, built each time it runs."""

    def _step(self, fiber: Fiber[Any, Any]) -> Step:
        return self.as_effect()


__all__ = ["Class"]
