"""The scope of an entity's activation (Effect's
``internal/entityActivation``): closed when the entity is torn down."""

from __future__ import annotations

from pyfect.context import Tag
from pyfect.scope import CloseableScope


class CurrentActivationScope(
    Tag[CloseableScope], key="effect/cluster/internal/CurrentActivationScope"
):
    """The scope of the running entity's activation."""


__all__ = ["CurrentActivationScope"]
