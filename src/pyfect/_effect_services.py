"""``Effect`` methods for services."""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from pyfect import _core
from pyfect._effect_base import A_co, E_co, EffectBase, R_co, as_effect

if TYPE_CHECKING:
    from pyfect._core import Effect
    from pyfect.context import TagLike


class ServiceMethods(EffectBase[A_co, E_co, R_co]):
    __slots__ = ()

    def update_service[S, T](
        self, tag: TagLike[S, T], f: Callable[[S], S]
    ) -> Effect[A_co, E_co, R_co | T]:
        """Run with ``f`` applied to the service of ``tag``, which this
        effect then needs."""
        return _core._Locally(as_effect(self), lambda ctx: ctx.add(tag, f(ctx.unsafe_get(tag))))
