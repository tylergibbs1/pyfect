"""``all`` and ``all_dict``: several configs read as one.

The children are read in order. A group fails as soon as a child fails
(invalid data or a source error), even after an absent child; otherwise it
is absent when any child is, with the first absent child's error.
"""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, overload

from pyfect._concurrency import for_each
from pyfect._core import Effect
from pyfect.config._config import Config, Resolution, require_config
from pyfect.config._error import ConfigError
from pyfect.config_provider import ConfigProvider, Path
from pyfect.result import Err, Ok


@overload
def all() -> Config[tuple[()]]: ...
@overload
def all[A1](c1: Config[A1], /) -> Config[tuple[A1]]: ...
@overload
def all[A1, A2](c1: Config[A1], c2: Config[A2], /) -> Config[tuple[A1, A2]]: ...
@overload
def all[A1, A2, A3](
    c1: Config[A1], c2: Config[A2], c3: Config[A3], /
) -> Config[tuple[A1, A2, A3]]: ...
@overload
def all[A1, A2, A3, A4](
    c1: Config[A1], c2: Config[A2], c3: Config[A3], c4: Config[A4], /
) -> Config[tuple[A1, A2, A3, A4]]: ...
@overload
def all[A1, A2, A3, A4, A5](
    c1: Config[A1], c2: Config[A2], c3: Config[A3], c4: Config[A4], c5: Config[A5], /
) -> Config[tuple[A1, A2, A3, A4, A5]]: ...
@overload
def all[A](*configs: Config[A]) -> Config[tuple[A, ...]]: ...
def all(*configs: Config[Any]) -> Config[tuple[Any, ...]]:
    """The configs' values as a tuple, in order (Effect's ``Config.all``
    of a tuple or an iterable: pass ``*configs``)."""
    for i, c in enumerate(configs):
        require_config(c, f"configs[{i}]")
    return Config(lambda provider, prefix: _collect(configs, provider, prefix).map(_tuple))


def all_dict[K, A](configs: Mapping[K, Config[A]]) -> Config[dict[K, A]]:
    """The configs' values under the same keys (Effect's ``Config.all`` of a
    record). The mapping is copied when the config is made."""
    keys = tuple(configs)
    values = tuple(configs[k] for k in keys)
    for k, c in zip(keys, values, strict=True):
        require_config(c, f"configs[{k!r}]")

    def to_dict(resolution: Resolution[list[A]]) -> Resolution[dict[K, A]]:
        match resolution:
            case Ok(items):
                return Ok(dict(zip(keys, items, strict=True)))
            case Err():
                return resolution

    return Config(lambda provider, prefix: _collect(values, provider, prefix).map(to_dict))


def _collect[A](
    configs: tuple[Config[A], ...], provider: ConfigProvider, prefix: Path
) -> Effect[Resolution[list[A]], ConfigError]:
    return for_each(configs, lambda c: c._evaluate(provider, prefix)).map(_first_absent)


def _first_absent[A](resolutions: list[Resolution[A]]) -> Resolution[list[A]]:
    values: list[A] = []
    for resolution in resolutions:
        match resolution:
            case Ok(value):
                values.append(value)
            case Err():
                return resolution
    return Ok(values)


def _tuple[A](resolution: Resolution[list[A]]) -> Resolution[tuple[A, ...]]:
    match resolution:
        case Ok(items):
            return Ok(tuple(items))
        case Err():
            return resolution
