"""Schemas of frozen dataclasses whose wire keys differ from their
attribute names.

Effect's AI values travel as JSON with camelCase keys (``mediaType``,
``toolCallId``); the Python classes have snake_case attributes. A
``wire_codec`` reads and writes such a class through a mapping keyed by the
wire names, so ``Prompt`` exports, tool results and errors keep Effect's
format.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from pyfect.schema import Bottom, Top, ast


@dataclass(frozen=True, slots=True)
class Key:
    """A wire key ``key`` holding the attribute ``attr``, read with
    ``schema``. ``optional``: the key may be missing and is left out when
    the attribute is ``None``. ``default``: a missing key decodes to
    ``default()`` (the key is still written)."""

    key: str
    attr: str
    schema: Top
    optional: bool = False
    default: Callable[[], object] | None = None


@dataclass(frozen=True, slots=True)
class Const:
    """A wire key always holding ``value`` (a ``type`` or ``_tag``)."""

    key: str
    value: str | bool


type Spec = Key | Const


class _Shape:
    """A ``ClassShape`` for ``ast.Class``: decodes the wire mapping, then
    calls ``cls`` with the attributes."""

    __slots__ = ("_fields", "cls", "specs")

    def __init__(self, cls: type, specs: Sequence[Spec]) -> None:
        self.cls = cls
        self.specs = tuple(specs)
        self._fields: tuple[ast.Objects, ast.AST] | None = None

    def _build(self) -> tuple[ast.Objects, ast.AST]:
        if self._fields is None:
            properties: list[ast.PropertySignature] = []
            for spec in self.specs:
                match spec:
                    case Const(key, value):
                        properties.append(ast.PropertySignature(key, ast.Literal(value)))
                    case Key(key, _, schema, optional, default):
                        properties.append(
                            ast.PropertySignature(
                                key, schema.__codec__().ast, optional=optional, default=default
                            )
                        )
            fields = ast.Objects(tuple(properties))
            self._fields = (fields, fields.flip().to_type())
        return self._fields

    @property
    def fields(self) -> ast.Objects:
        return self._build()[0]

    @property
    def encoded(self) -> ast.AST:
        return self._build()[1]

    @property
    def checks(self) -> None:
        return None

    def construct(self, values: dict[object, object]) -> object:
        kwargs: dict[str, object] = {}
        for spec in self.specs:
            if isinstance(spec, Key) and spec.key in values:
                kwargs[spec.attr] = values[spec.key]
        return self.cls(**kwargs)

    def values_of(self, instance: object) -> dict[object, object]:
        values: dict[object, object] = {}
        for spec in self.specs:
            match spec:
                case Const(key, value):
                    values[key] = value
                case Key(key, attr, _, optional, _):
                    value = getattr(instance, attr)
                    if not (optional and value is None):
                        values[key] = value
        return values


def wire_codec[T](
    cls: type[T], specs: Sequence[Spec], /, **annotations: object
) -> Bottom[T, Mapping[str, object]]:
    """The schema of ``cls`` instances encoded as the mapping ``specs``
    describe (``identifier=`` names it, as for a schema class)."""
    node: Any = ast.Class(_Shape(cls, specs), annotations=annotations or None)
    return Bottom(node)


def key(
    name: str,
    attr: str,
    schema: Top,
    *,
    optional: bool = False,
    default: Callable[[], object] | None = None,
) -> Key:
    return Key(name, attr, schema, optional, default)
