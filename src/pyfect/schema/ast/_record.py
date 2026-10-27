"""The ``Objects`` of a record: values of one node under keys of another."""

from __future__ import annotations

from pyfect.schema.ast._base import AST
from pyfect.schema.ast._keywords import Never
from pyfect.schema.ast._literal import Literal, LiteralValue, same_literal
from pyfect.schema.ast._objects import IndexSignature, Objects, PropertySignature
from pyfect.schema.ast._union import Union


def record(key: AST, value: AST) -> Objects:
    """Effect's ``record``: each literal key (a ``Literal``, or one in a
    union) is a required property, listed once; any other key node is an
    index signature. ``Never`` takes no key."""
    literals: list[LiteralValue] = []
    parameters: list[AST] = []

    def go(node: AST) -> None:
        match node:
            case Literal(literal=literal) if node.checks is None:
                if not any(same_literal(seen, literal) for seen in literals):
                    literals.append(literal)
            case Never():
                pass
            case Union(types=types) if node.checks is None:
                for member in types:
                    go(member)
            case _:
                parameters.append(node)

    go(key)
    return Objects(
        tuple(PropertySignature(name, value) for name in literals),
        tuple(IndexSignature(parameter, value) for parameter in parameters),
    )
