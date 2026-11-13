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
    walk = _TemplatePattern(compiler)
    pattern = f"^{''.join(map(walk.part, node.parts))}$"
    return pattern, walk.exact


class _TemplatePattern:
    __slots__ = ("active", "compiler", "exact")

    def __init__(self, compiler: Compiler) -> None:
        self.compiler = compiler
        self.exact = True
        self.active: set[str] = set()

    def part(self, node: ast.AST) -> str:
        candidate = self.compiler.references.candidate(node)
        reference = candidate.reference
        if reference is None:
            return self.local(candidate.ast)
        self.compiler.definition_of(candidate)
        if reference in self.active:
            raise ValueError(f"Invalid recursive TemplateLiteral part {reference}")
        self.active.add(reference)
        out = self.local(candidate.ast)
        self.active.discard(reference)
        return out

    def local(self, node: ast.AST) -> str:  # noqa: PLR0911
        # A segment check cannot be written into the enclosing pattern.
        if node.checks:
            self.exact = False
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
                return "".join(map(self.part, node.parts))
            case ast.Union():
                if not node.types:
                    return "(?!)"
                if node.mode == "one_of":
                    self.exact = False
                return f"(?:{'|'.join(map(self.part, node.types))})"
            case _:
                raise ValueError(f"Invalid TemplateLiteral part {node.tag}")
