"""The pattern of a ``TemplateLiteral`` (Effect's ``getTemplateLiteralPattern``):
each part's pattern in order, between ``^`` and ``$``. A part with checks,
or a ``one_of`` union (alternatives do not make one branch exclusive),
makes the pattern an approximation."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from pyfect.schema import ast
from pyfect.schema.getter._coerce import to_string

if TYPE_CHECKING:
    from pyfect.schema._jsonschema._compile import Compiler

_SPECIAL = re.compile(r"[/\\^$*+?.()|\[\]{}]")


def escape(text: str) -> str:
    """JavaScript's ``RegExp.escape`` as Effect writes it."""
    return _SPECIAL.sub(lambda m: "\\" + m.group(0), text)


def template_pattern(compiler: Compiler, node: ast.TemplateLiteral) -> tuple[str, bool]:
    """The pattern of ``node``'s parts and whether it is exact."""
    exact = True
    active: set[str] = set()

    def part(node: ast.AST) -> str:
        candidate = compiler.references.candidate(node)
        reference = candidate.reference
        if reference is None:
            return local(candidate.ast)
        compiler.definition_of(candidate)
        if reference in active:
            raise ValueError(f"Invalid recursive TemplateLiteral part {reference}")
        active.add(reference)
        out = local(candidate.ast)
        active.discard(reference)
        return out

    def local(node: ast.AST) -> str:  # noqa: PLR0911
        nonlocal exact
        # A segment check cannot be written into the enclosing pattern.
        if node.checks:
            exact = False
        match node:
            case ast.Literal():
                return escape(to_string(node.literal))
            case ast.String():
                return ast.STRING_PATTERN
            case ast.Number():
                return ast.FINITE_PATTERN
            case ast.BigInt():
                return ast.BIG_INT_PATTERN
            case ast.TemplateLiteral():
                return "".join(map(part, node.parts))
            case ast.Union():
                if not node.types:
                    return "(?!)"
                if node.mode == "one_of":
                    exact = False
                return f"(?:{'|'.join(map(part, node.types))})"
            case _:
                raise ValueError(f"Invalid TemplateLiteral part {node.tag}")

    pattern = f"^{''.join(map(part, node.parts))}$"
    return pattern, exact
