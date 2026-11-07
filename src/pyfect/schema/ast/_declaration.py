"""``Declaration``: values a function parses, given the nodes of its type
parameters (Effect's ``Declaration``): ``Option(A)``, ``frozenset[A]``,
``timedelta``, ...

``run(type_parameters)`` makes the parser on first use; the parser gets
the input, the declaration itself (for its issues) and the parse options.
Flipping a declaration flips its type parameters, so the same parser
encodes with them.
"""

from __future__ import annotations

from collections.abc import Callable, Hashable
from dataclasses import dataclass, field, replace
from typing import cast

from pyfect.exit import Exit, Failure, Success
from pyfect.exit import die as die_exit
from pyfect.exit import fail as fail_exit
from pyfect.schema._options import ParseOptions
from pyfect.schema.ast._base import AST, issue_of
from pyfect.schema.ast._result import ParseResult, then
from pyfect.schema.issue import Composite, Issue, Pointer, reported

type DeclarationParser = Callable[[object, Declaration, ParseOptions], ParseResult]
type DeclarationRun = Callable[[tuple[AST, ...]], DeclarationParser]


@dataclass(frozen=True, slots=True, eq=False)
class Declaration(AST):
    """Values ``run(type_parameters)`` accepts. Without an ``expected``
    annotation it expects ``<Declaration>``."""

    type_parameters: tuple[AST, ...]
    run: DeclarationRun
    encoding_run: DeclarationRun | None = field(default=None, kw_only=True)
    """The parser maker of the flipped declaration, which then has ``run``
    as its own ``encoding_run``: a declaration that encodes differently.
    ``None`` encodes with ``run``."""
    _parser: list[DeclarationParser] = field(
        default_factory=list[DeclarationParser], init=False, repr=False
    )
    tag = "Declaration"

    def get_expected(self) -> str:
        expected = (self.annotations or {}).get("expected")
        return expected if isinstance(expected, str) else "<Declaration>"

    def _parse(self, input: object, options: ParseOptions) -> ParseResult:
        # Making the parser is the declaration's own setup: an error there
        # is raised, not turned into a defect of this input.
        if not self._parser:
            self._parser.append(self.run(self.type_parameters))
        try:
            return self._parser[0](input, self, options)
        except Exception as defect:
            return die_exit(defect)

    def _map(self, f: Callable[[AST], AST]) -> Declaration:
        parameters = tuple(map(f, self.type_parameters))
        if all(a is b for a, b in zip(parameters, self.type_parameters, strict=True)):
            return self
        return replace(self, type_parameters=parameters)

    def _flip(self) -> Declaration:
        # Checks describe the decoded side: flipped, they check the input.
        flipped = self._map(lambda t: t.flip())
        if self.encoding_run is not None:
            flipped = replace(flipped, run=self.encoding_run, encoding_run=self.run)
        if self.checks is None and self.encoding_checks is None:
            return flipped
        return replace(flipped, checks=self.encoding_checks, encoding_checks=self.checks)

    def _to_type(self) -> Declaration:
        return self._map(lambda t: t.to_type())

    def children(self) -> tuple[AST, ...]:
        return self.type_parameters

    def _keeps_structural_checks(self) -> bool:
        return bool(self.type_parameters)


def parse_at_key(
    ast: AST,
    key: Hashable,
    node: AST,
    value: object,
    *,
    input: object,
    options: ParseOptions,
) -> ParseResult:
    """``value`` (``input``'s part at ``key``) parsed by ``node``; an issue
    is reported as ``ast``'s at ``key`` (Effect's ``makeCompositeAtKey``)."""

    def at_key(exit: Exit[object, Issue]) -> Exit[object, Issue]:
        if type(exit) is Success:
            return exit
        failure = cast("Failure[Issue]", exit)
        issue = issue_of(failure)
        if issue is None:
            return failure
        return fail_exit(Composite(ast, (Pointer((key,), issue),), reported(input, options)))

    return then(node.parse(value, options), at_key)
