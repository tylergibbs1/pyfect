"""``TemplateLiteral`` and ``TemplateLiteralParser``: strings made of
ordered parts (Effect's schemas of TypeScript template literal types)::

    S.TemplateLiteral("/user/", S.Number)          # "/user/123"
    S.TemplateLiteralParser("/user/", S.FiniteFromString)
    # decodes "/user/42" to ("/user/", 42)

A part is a literal (``str``, ``int`` or ``float``, matched by its text) or
a schema of strings, numbers or bigints (see ``ast.TemplateLiteral``).
``TemplateLiteral`` keeps the string and rejects parts with an encoding;
``TemplateLiteralParser`` decodes the string into a tuple with one value
per part and takes any part whose encoded side is such a schema. Pyright
cannot compute a template's string type nor the parser's tuple type: the
Type is ``str`` and ``tuple[Any, ...]``.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import Any, Generic, Never, TypeVar, overload

from pyfect._one_or_many import one_or_many
from pyfect.exit import Exit, Success
from pyfect.schema import ast
from pyfect.schema import transformation as T
from pyfect.schema._codec_links import (
    BIG_INT_TO_STRING,
    FINITE_TO_STRING,
    NUMBER_TO_STRING,
    is_finite_number,
    literal_to_string,
)
from pyfect.schema._options import ParseOptions
from pyfect.schema._schema import Bottom, Codec, is_schema
from pyfect.schema.ast._template_literal import (
    TemplateLiteral as TemplateLiteralNode,
)
from pyfect.schema.ast._template_literal import (
    normalize_encoded,
    segment,
    template_mismatch,
)
from pyfect.schema.issue import Issue

RD_co = TypeVar("RD_co", covariant=True)
RE_co = TypeVar("RE_co", covariant=True)

type LiteralPart = str | int | float
"""A literal part, matched by its text (``1`` by ``"1"``)."""
type TemplateLiteralPart = Codec[Any, Any, Never, Never] | LiteralPart


def _node(part: object) -> ast.AST:
    if is_schema(part):
        return part.__codec__().ast
    return ast.Literal(part)  # pyright: ignore[reportArgumentType]


def _nodes(parts: Sequence[object]) -> tuple[ast.AST, ...]:
    return tuple(map(_node, parts))


@dataclass(frozen=True, slots=True, eq=False)
class TemplateLiteralSchema(Bottom[str, str, Never, Never]):
    """A template literal; ``parts`` are its parts, as given."""

    parts: tuple[TemplateLiteralPart, ...]


@overload
def TemplateLiteral(
    parts: list[TemplateLiteralPart] | tuple[TemplateLiteralPart, ...], /
) -> TemplateLiteralSchema: ...
@overload
def TemplateLiteral(*parts: TemplateLiteralPart) -> TemplateLiteralSchema: ...
def TemplateLiteral(*parts: Any) -> TemplateLiteralSchema:
    """The strings made of ``parts``, kept as they are (Effect's
    ``TemplateLiteral``): ``Expected a string matching template literal
    parts`` otherwise. The parts are given as arguments or, as in Effect,
    as one list or tuple. A part with an encoding raises ``ValueError``
    (use ``TemplateLiteralParser``)."""
    parts = one_or_many(parts)
    return TemplateLiteralSchema(TemplateLiteralNode(_nodes(parts)), parts)


@dataclass(frozen=True, slots=True, eq=False)
class TemplateLiteralParserSchema(
    Bottom[tuple[Any, ...], str, RD_co, RE_co], Generic[RD_co, RE_co]
):
    """A template literal parser; ``parts`` are its parts, as given."""

    parts: tuple[Codec[Any, Any, RD_co, RE_co] | LiteralPart, ...]


@overload
def TemplateLiteralParser[RD = Never, RE = Never](
    parts: list[Codec[Any, Any, RD, RE] | LiteralPart]
    | tuple[Codec[Any, Any, RD, RE] | LiteralPart, ...],
    /,
) -> TemplateLiteralParserSchema[RD, RE]: ...
@overload
def TemplateLiteralParser[RD = Never, RE = Never](
    *parts: Codec[Any, Any, RD, RE] | LiteralPart,
) -> TemplateLiteralParserSchema[RD, RE]: ...
def TemplateLiteralParser(*parts: Any) -> TemplateLiteralParserSchema[Any, Any]:
    """The strings made of ``parts``, decoded into a tuple of the parts'
    values (Effect's ``TemplateLiteralParser``): a literal part gives its
    literal, a schema part its decoded value. A part may transform (its
    encoded side is the template's part). The split is greedy, so encoding
    a tuple and decoding the string may give another tuple when a segment
    holds a separator."""
    parts = one_or_many(parts)
    return TemplateLiteralParserSchema(template_literal_parser(_nodes(parts)), parts)


# ------------------------------------------------------------------ the AST


def part_from_string(node: ast.AST) -> ast.AST:
    """``node`` read from its segment's text: a number, bigint or
    non-string literal at its most encoded end decodes from its text
    (Effect's ``partFromString``)."""
    if node.encoding is not None:
        *init, last = node.encoding
        to = part_from_string(last.to)
        return (
            node
            if to is last.to
            else replace(node, encoding=(*init, ast.Link(to, last.transformation)))
        )
    match node:
        case ast.Number():
            link = FINITE_TO_STRING if is_finite_number(node) else NUMBER_TO_STRING
            return replace(node, encoding=(link,))
        case ast.BigInt():
            return replace(node, encoding=(BIG_INT_TO_STRING,))
        case ast.Literal() if not isinstance(node.literal, str):
            return literal_to_string(node)
        case ast.Union():
            types = tuple(map(part_from_string, node.types))
            same = all(a is b for a, b in zip(types, node.types, strict=True))
            return node if same else replace(node, types=types)
        case _:
            return node


def segments_tuple(nodes: Sequence[ast.AST]) -> ast.Arrays:
    """A fixed tuple of ``nodes``."""
    return ast.Arrays(tuple(ast.Element(node) for node in nodes))


def _join(parts: tuple[str, ...]) -> str:
    return "".join(parts)


def template_literal_parser(parts: Sequence[ast.AST]) -> ast.Arrays:
    """The tuple of ``parts``' values decoded from the template of their
    encoded sides (Effect's ``templateLiteralParser``)."""
    template = TemplateLiteralNode(normalize_encoded(parts))

    def decode(text: str, options: ParseOptions) -> Exit[tuple[str, ...], Issue]:
        segments = segment(template, text, options)
        if segments is None:
            return template_mismatch(text, options)
        return Success(tuple(segments))

    def encode(values: tuple[str, ...], _: ParseOptions) -> Exit[str, Issue]:
        return Success(_join(values))

    tuple_node = segments_tuple(tuple(map(part_from_string, parts)))
    return ast.decode_to(template, tuple_node, T.transform_effect(decode=decode, encode=encode))
