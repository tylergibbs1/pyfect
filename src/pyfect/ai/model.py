"""A provider's model as a layer (Effect's ``Model``).

``make("openai", "gpt-4o", layer)`` is ``layer`` plus the ``ProviderName``
and ``ModelName`` services; ``capture_requirements`` gives the layer with
the current context already provided.
"""

from __future__ import annotations

from typing import Any, cast

import pyfect as fx
from pyfect import layer as L
from pyfect._core import Effect
from pyfect.context import Context, Tag


class ProviderName(Tag[str], key="effect/ai/Model/ProviderName"):
    """The provider of the current model."""


class ModelName(Tag[str], key="effect/ai/Model/ModelName"):
    """The current model's name."""


class Model[Provides, Requires]:
    """A model's layer, with its ``provider``."""

    __slots__ = ("layer", "provider")

    def __init__(self, provider: str, layer: L.Layer[Any, Any, Any]) -> None:
        self.provider = provider
        self.layer: L.Layer[Provides | ProviderName | ModelName, Any, Requires] = layer

    @property
    def capture_requirements(
        self,
    ) -> Effect[L.Layer[Provides | ProviderName | ModelName], Any, Requires]:
        """The layer with the current context provided to it."""
        return cast(
            "Any",
            fx.context().map(lambda ctx: self.layer.pipe(L.provide(L.succeed_context(ctx)))),
        )

    def to_json(self) -> dict[str, object]:
        return {"_id": "effect/ai/Model", "provider": self.provider}


def make[Provides, Requires](
    provider: str, model_name: str, layer: L.Layer[Provides, Any, Requires]
) -> Model[Provides, Requires]:
    names = L.succeed_context(Context.make(ProviderName, provider).add(ModelName, model_name))
    return Model(provider, cast("Any", L.merge(cast("Any", layer), names)))


__all__ = ["Model", "ModelName", "ProviderName", "make"]
