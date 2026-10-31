"""Singletons (Effect's ``Singleton``): an effect run on exactly one
runner of the cluster, the one owning its shard."""

from __future__ import annotations

from typing import Any, Never, overload

from pyfect import layer as layer_
from pyfect._core import Effect
from pyfect._effect_args import require_effect
from pyfect.cluster.sharding import Sharding
from pyfect.layer import Layer
from pyfect.scope import Scope


@overload
def make[E](
    name: str, run: Effect[None, E, Scope], /, *, shard_group: str | None = None
) -> Layer[Never, Never, Sharding]: ...
@overload
def make[E, R](
    name: str, run: Effect[None, E, R | Scope], /, *, shard_group: str | None = None
) -> Layer[Never, Never, Sharding | R]: ...
def make(
    name: str, run: Effect[None, Any, Any], /, *, shard_group: str | None = None
) -> Layer[Never, Never, Any]:
    """Register ``run`` as the singleton ``name`` (in ``shard_group``,
    ``"default"`` when ``None``) with ``Sharding``: the runner owning its
    shard runs it, and moves it when the shard moves."""
    require_effect(run, "run")
    return layer_.effect_discard(
        Sharding().flat_map(lambda sharding: sharding.register_singleton(name, run, shard_group))
    )


__all__ = ["make"]
