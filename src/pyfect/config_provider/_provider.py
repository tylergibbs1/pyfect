"""The ``ConfigProvider`` interface, ``make``, and the reference holding the
current provider."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import override

from pyfect._core import Effect
from pyfect.config_provider._case import config_case
from pyfect.config_provider._node import Node, Path, PathInput, SourceError, to_path
from pyfect.context import Reference
from pyfect.effect import succeed

type Lookup = Callable[[Path], Effect[Node | None, SourceError]]


class ConfigProvider(ABC):
    """A source of configuration ``Node`` values, looked up by path.

    ``load`` gives ``None`` for an absent path and fails with
    ``SourceError`` only when the source cannot be read; absence is what
    ``or_else`` falls back on. Build one with ``make``, ``from_env``,
    ``from_unknown``, ``from_dot_env_contents`` or ``from_dir``."""

    __slots__ = ()

    @abstractmethod
    def load(self, path: PathInput) -> Effect[Node | None, SourceError]:
        """The node at ``path`` after this provider's path transformations,
        or ``None`` when there is none."""

    @abstractmethod
    def map_input(self, f: Callable[[Path], PathInput]) -> ConfigProvider:
        """A provider that applies ``f`` to lookup paths after its existing
        transformations. ``or_else`` providers apply it to both operands."""

    def or_else(self, that: ConfigProvider) -> ConfigProvider:
        """Look up in this provider, then in ``that`` when the path is
        absent here. A ``SourceError`` does not fall back, and found
        containers are not merged."""
        return _OrElse(self, that)

    def nested(self, prefix: str | PathInput) -> ConfigProvider:
        """Look every path up under ``prefix``."""
        head = (prefix,) if isinstance(prefix, str) else to_path(prefix)
        return self.map_input(lambda path: head + path)

    def constant_case(self) -> ConfigProvider:
        """Convert string segments to CONSTANT_CASE (Effect's ``configCase``:
        ``"databaseHost"`` is ``"DATABASE_HOST"``, ``"api-v2"`` is
        ``"API_V2"``); numeric segments are kept."""
        return self.map_input(_constant_case)

    def __repr__(self) -> str:
        return "ConfigProvider()"


def _constant_case(path: Path) -> Path:
    return tuple(seg if isinstance(seg, int) else config_case(seg) for seg in path)


def make(get: Lookup) -> ConfigProvider:
    """A provider over ``get``, which receives the transformed path and
    returns the node there, ``None``, or a ``SourceError`` failure."""
    return _Source(get, _identity)


def _identity(path: Path) -> Path:
    return path


class _Source(ConfigProvider):
    __slots__ = ("_get", "_transform")

    def __init__(self, get: Lookup, transform: Callable[[Path], Path]) -> None:
        self._get = get
        self._transform = transform

    @override
    def load(self, path: PathInput) -> Effect[Node | None, SourceError]:
        return self._get(self._transform(to_path(path)))

    @override
    def map_input(self, f: Callable[[Path], PathInput]) -> ConfigProvider:
        transform = self._transform
        return _Source(self._get, lambda path: to_path(f(transform(path))))


class _OrElse(ConfigProvider):
    __slots__ = ("_first", "_second")

    def __init__(self, first: ConfigProvider, second: ConfigProvider) -> None:
        self._first = first
        self._second = second

    @override
    def load(self, path: PathInput) -> Effect[Node | None, SourceError]:
        second = self._second
        return self._first.load(path).flat_map(
            lambda node: second.load(path) if node is None else succeed(node)
        )

    @override
    def map_input(self, f: Callable[[Path], PathInput]) -> ConfigProvider:
        return _OrElse(self._first.map_input(f), self._second.map_input(f))


class CurrentConfigProvider(Reference[ConfigProvider]):
    """The provider ``Config`` values are read from. ``from_env()`` by
    default; install another with ``config_provider.layer``."""

    @classmethod
    def default(cls) -> ConfigProvider:
        from pyfect.config_provider._env import from_env

        return from_env()
