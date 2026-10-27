"""Layers that install a provider as the ``CurrentConfigProvider``."""

from __future__ import annotations

from typing import Never, cast, overload

from pyfect import layer as _layer
from pyfect._core import Effect
from pyfect._effect_args import wrong_argument
from pyfect._effect_base import EffectBase
from pyfect.config_provider._provider import ConfigProvider, CurrentConfigProvider
from pyfect.effect import succeed
from pyfect.layer import Layer
from pyfect.scope import Scope


@overload
def layer(provider: ConfigProvider, /) -> Layer[CurrentConfigProvider]: ...
@overload
def layer[E](provider: Effect[ConfigProvider, E, Scope], /) -> Layer[CurrentConfigProvider, E]: ...
@overload
def layer[E = Never, R = Never](
    provider: Effect[ConfigProvider, E, Scope | R], /
) -> Layer[CurrentConfigProvider, E, R]: ...
def layer(
    provider: ConfigProvider | Effect[ConfigProvider, object, object], /
) -> Layer[CurrentConfigProvider, object, object]:
    """Install ``provider``, or the provider an effect builds, replacing the
    current one."""
    if isinstance(provider, ConfigProvider):
        return _layer.succeed(CurrentConfigProvider, provider)
    return _layer.effect(CurrentConfigProvider, _provider_effect(provider))


@overload
def layer_add(
    provider: ConfigProvider, /, *, as_primary: bool = False
) -> Layer[CurrentConfigProvider]: ...
@overload
def layer_add[E](
    provider: Effect[ConfigProvider, E, Scope], /, *, as_primary: bool = False
) -> Layer[CurrentConfigProvider, E]: ...
@overload
def layer_add[E = Never, R = Never](
    provider: Effect[ConfigProvider, E, Scope | R], /, *, as_primary: bool = False
) -> Layer[CurrentConfigProvider, E, R]: ...
def layer_add(
    provider: ConfigProvider | Effect[ConfigProvider, object, object],
    /,
    *,
    as_primary: bool = False,
) -> Layer[CurrentConfigProvider, object, object]:
    """Combine ``provider`` with the current one: as its fallback, or, with
    ``as_primary``, consulted first."""
    added = _provider_effect(provider)

    def combine(current: ConfigProvider, new: ConfigProvider) -> ConfigProvider:
        return new.or_else(current) if as_primary else current.or_else(new)

    combined = CurrentConfigProvider().flat_map(
        lambda current: added.map(lambda new: combine(current, new))
    )
    return _layer.effect(CurrentConfigProvider, combined)


def _provider_effect(provider: object) -> Effect[ConfigProvider, object, object]:
    """``provider`` as an effect; anything but a provider or an effect is
    rejected when the layer is made, not when it builds."""
    if isinstance(provider, ConfigProvider):
        return succeed(provider)
    if not isinstance(provider, EffectBase):
        raise TypeError(
            wrong_argument(
                provider,
                "provider",
                "an Effect or a ConfigProvider",
                "to run a function, pass fx.sync(f) or fx.suspend(f)",
            )
        )
    return cast(Effect[ConfigProvider, object, object], provider)
