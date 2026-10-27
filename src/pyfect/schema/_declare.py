"""Declared schemas: values a guard or a parser accepts (Effect's
``declare``, ``declareConstructor`` and ``instanceOf``)."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any, Never, TypeIs

from pyfect._core import Effect
from pyfect.exit import Exit, Success
from pyfect.schema import ast
from pyfect.schema._options import ParseOptions
from pyfect.schema._schema import Bottom, Codec
from pyfect.schema.issue import Issue

type Parse[T = object] = Callable[
    [object, ast.Declaration, ParseOptions], Exit[T, Issue] | Effect[T, Issue, Any]
]
"""A declaration's parser: the input, the declaration (for its issues) and
the parse options. It gives an ``Exit``, or an ``Effect`` when a part's
parse is one (``ast.then`` / ``ast.map_value`` keep either)."""


def declare[T](guard: Callable[[object], TypeIs[T]], /, **annotations: object) -> Bottom[T]:
    """The values ``guard`` accepts, unchanged (Effect's ``declare``);
    anything else is ``Expected <expected>``, the ``expected`` annotation
    (default ``<Declaration>``)."""

    def run(_: tuple[ast.AST, ...]) -> Parse:
        def parse(
            input: object, node: ast.Declaration, options: ParseOptions
        ) -> Exit[object, Issue]:
            return Success(input) if guard(input) else ast.invalid_type(node, input, options)

        return parse

    return Bottom(ast.Declaration((), run, annotations=annotations or None))


def instance_of[T](cls: type[T], /, **annotations: object) -> Bottom[T]:
    """Instances of ``cls`` (Effect's ``instanceOf``), expected as the class
    name unless annotated."""

    def guard(input: object) -> TypeIs[T]:
        return isinstance(input, cls)

    return declare(guard, **{"expected": cls.__name__, **annotations})


def declare_constructor[T, RD, RE](
    type_parameters: Sequence[Codec[Any, Any, RD, RE]],
    run: Callable[[tuple[Bottom[Any, Any, Never, Never], ...]], Parse[T]],
    /,
    **annotations: object,
) -> Bottom[T, Any, RD, RE]:
    """A schema of a container of ``type_parameters``' values (Effect's
    ``declareConstructor``). ``run`` gets the type parameters' schemas
    (flipped when encoding) and returns the parser; it parses a part with
    ``schema.ast.parse(part, options)`` and reports its issue with
    ``ast.parse_at_key``. The Type is what the parser returns; write the
    Encoded type out (Python cannot compute it from the type parameters):
    ``boxes: S.Bottom[Box[int], Box[str]] = S.declare_constructor(...)``."""

    def make_parser(nodes: tuple[ast.AST, ...]) -> Parse[T]:
        return run(tuple(Bottom(node) for node in nodes))

    nodes = tuple(p.__codec__().ast for p in type_parameters)
    return Bottom(ast.Declaration(nodes, make_parser, annotations=annotations or None))
