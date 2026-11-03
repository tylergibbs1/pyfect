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
from typing import TYPE_CHECKING, Any, Never

from pyfect._core import Effect, Step

if TYPE_CHECKING:
    from pyfect._fiber import Fiber


class Class[A, E = Never, R = Never](Effect[A, E, R], metaclass=ABCMeta):
    """An effect defined by ``as_effect`` (Effect's ``Effectable.Class``)."""

    @abstractmethod
    def as_effect(self) -> Effect[A, E, R]:
        """The effect an instance runs, built each time it runs."""

    def _step(self, fiber: Fiber[Any, Any]) -> Step:
        return self.as_effect()


__all__ = ["Class"]
