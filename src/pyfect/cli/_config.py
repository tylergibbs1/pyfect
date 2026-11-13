"""Command configs: a class whose attributes are flags, arguments and
nested configs, and the parsed instance of it a handler receives (Effect's
``Command.Config`` record and the internal ``cli/internal/config``).

``class Clone(Config): repository = Argument.string("repository")``
declares the params; the parser builds a ``Clone`` whose ``repository`` is
the parsed ``str``. Params are read in definition order, base classes
first.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any, ClassVar, Generic, Self, TypeVar, cast, overload

from pyfect.cli import param as p
from pyfect.cli.argument import Argument
from pyfect.cli.flag import Flag

C_co = TypeVar("C_co", bound="Config", covariant=True)


@dataclass(frozen=True, eq=False, slots=True)
class Nested(Generic[C_co]):
    """A group of params from another config class, read as an instance of
    it (``database = nested(Database)``)."""

    config: type[C_co]

    @overload
    def __get__(self, instance: None, owner: type[object]) -> Self: ...
    @overload
    def __get__(self, instance: object, owner: type[object]) -> C_co: ...
    def __get__(self, instance: object, owner: type[object]) -> Self | C_co:
        if instance is None:
            return self
        raise AttributeError(f"{owner.__name__} has no parsed value for this group")


def nested[C: Config](config: type[C]) -> Nested[C]:
    return Nested(config)


type Field = Flag[Any] | Argument[Any] | Nested[Any]


class Config:
    """The params of a command, as class attributes; an instance holds the
    parsed values. The base class itself has no params."""

    __cli_fields__: ClassVar[dict[str, Field]] = {}

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        fields: dict[str, Field] = {}
        for klass in reversed(cls.__mro__):
            for name, value in vars(klass).items():
                if isinstance(value, (Flag, Argument, Nested)):
                    fields.pop(name, None)
                    fields[name] = cast("Field", value)
        cls.__cli_fields__ = fields

    def __init__(self, **values: object) -> None:
        fields = type(self).__cli_fields__
        for name in values:
            if name not in fields:
                raise TypeError(f"{type(self).__name__}: unexpected param {name!r}")
        for name in fields:
            if name not in values:
                raise TypeError(f"{type(self).__name__}: missing param {name!r}")
        self.__dict__.update(values)

    def _values(self) -> Iterator[tuple[str, object]]:
        for name in type(self).__cli_fields__:
            yield name, self.__dict__.get(name)

    def __eq__(self, other: object) -> bool:
        if type(other) is not type(self):
            return NotImplemented
        return dict(self._values()) == dict(cast("Config", other)._values())

    def __hash__(self) -> int:
        return id(self)

    def __repr__(self) -> str:
        inner = ", ".join(f"{name}={value!r}" for name, value in self._values())
        return f"{type(self).__name__}({inner})"


# --- parsed form -----------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ParamNode:
    index: int


@dataclass(frozen=True, slots=True)
class NestedNode:
    config: type[Config]
    tree: Tree


type Node = ParamNode | NestedNode
type Tree = tuple[tuple[str, Node], ...]


@dataclass(frozen=True, slots=True)
class ConfigInternal:
    """A config class flattened: its params in order, flags and arguments
    apart, and how to rebuild the instance from the parsed values."""

    config: type[Config]
    flags: tuple[p.Param[Any], ...]
    arguments: tuple[p.Param[Any], ...]
    ordered_params: tuple[p.Param[Any], ...]
    tree: Tree

    def reconstruct(self, values: tuple[object, ...]) -> Config:
        return _build(self.config, self.tree, values)


def parse_config(config: type[Config], last: tuple[str, ...] = ()) -> ConfigInternal:
    """``config`` flattened. Fields named in ``last`` are taken after the
    others, so a command's own params come before shared ones it inherits."""
    ordered: list[p.Param[Any]] = []
    tree = _parse_tree(config, last, ordered)
    params = tuple(ordered)
    return ConfigInternal(
        config,
        tuple(param for param in params if param.kind == p.FLAG),
        tuple(param for param in params if param.kind == p.ARGUMENT),
        params,
        tree,
    )


def _parse_tree(klass: type[Config], last: tuple[str, ...], ordered: list[p.Param[Any]]) -> Tree:
    fields = klass.__cli_fields__
    names = [n for n in fields if n not in last] + [n for n in fields if n in last]
    tree: list[tuple[str, Node]] = []
    for name in names:
        value = fields[name]
        if isinstance(value, Nested):
            tree.append((name, NestedNode(value.config, _parse_tree(value.config, (), ordered))))
        else:
            tree.append((name, ParamNode(len(ordered))))
            ordered.append(value.param)
    return tuple(tree)


def _build(config: type[Config], tree: Tree, values: tuple[object, ...]) -> Config:
    instance = config.__new__(config)
    for name, node in tree:
        match node:
            case ParamNode(index):
                instance.__dict__[name] = values[index]
            case NestedNode(nested_config, nested_tree):
                instance.__dict__[name] = _build(nested_config, nested_tree, values)
    return instance


empty_config: ConfigInternal = parse_config(Config)

__all__ = ["Config", "ConfigInternal", "Nested", "empty_config", "nested", "parse_config"]
