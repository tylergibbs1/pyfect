"""The node every schema AST extends, and the helpers that rebuild one."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Any, ClassVar

from pyfect.cause import Fail
from pyfect.exit import Exit, Failure, Success
from pyfect.exit import die as die_exit
from pyfect.exit import fail as fail_exit
from pyfect.schema._options import ParseOptions
from pyfect.schema.ast._check import collect_issues
from pyfect.schema.issue import Composite, InvalidType, Issue, is_issue, reported

if TYPE_CHECKING:
    from pyfect.schema.ast._check import Check

type Annotations = Mapping[str, object]
type Checks = tuple[Check[Any], *tuple[Check[Any], ...]]
"""The checks of a node, run in order on the value it parsed."""


@dataclass(frozen=True, slots=True, eq=False)
class AST(ABC):
    """A schema node. Nodes compare by identity, as in Effect.

    ``checks`` run on every value the node itself accepts (Effect's
    ``checks``); a subclass parses its own kind in ``_parse``.
    """

    annotations: Annotations | None = field(default=None, kw_only=True)
    checks: Checks | None = field(default=None, kw_only=True)
    tag: ClassVar[str]

    @abstractmethod
    def get_expected(self) -> str:
        """What the node itself expects (``"string"``)."""

    def resolve(self) -> Annotations | None:
        """The annotations that describe the node: its last check's when it
        has checks, else its own (Effect's ``resolveAnnotations``)."""
        return self.checks[-1].annotations if self.checks else self.annotations

    def expected(self) -> str:
        """The text ``"Expected <...>"`` messages use: the ``identifier``
        annotation, else ``get_expected()`` (Effect's ``getExpected``)."""
        identifier = (self.resolve() or {}).get("identifier")
        return identifier if isinstance(identifier, str) else self.get_expected()

    def parse(self, input: object, options: ParseOptions) -> Exit[object, Issue]:
        """``input`` checked against this node and then its checks:
        ``Success`` with the value or ``Failure`` with the issue."""
        exit = self._parse(input, options)
        checks = self.checks
        if checks is None or options.get("disable_checks") or not isinstance(exit, Success):
            return exit
        try:
            issues = collect_issues(checks, exit.value, self, options)
        except Exception as defect:
            # A check that raises is a defect, as in Effect.
            return die_exit(defect)
        if issues is None:
            return exit
        return fail_exit(Composite(self, issues, reported(exit.value, options)))

    @abstractmethod
    def _parse(self, input: object, options: ParseOptions) -> Exit[object, Issue]:
        """``input`` checked against the node's own kind, without checks."""

    def flip(self) -> AST:
        """The node that encodes what this one decodes. A node without an
        encoding is its own flip."""
        return self

    def to_type(self) -> AST:
        """The node's decoded side. A node without an encoding is its own."""
        return self

    def __str__(self) -> str:
        return f"<{self.tag}>"


def annotate[N: AST](ast: N, annotations: Annotations) -> N:
    """``ast`` with ``annotations`` merged over its own; on a node with
    checks they go to the last check, which then describes the node."""
    if ast.checks:
        *rest, last = ast.checks
        return replace(ast, checks=(*rest, last.annotate(**annotations)))
    return replace(ast, annotations={**(ast.annotations or {}), **annotations})


def append_checks[N: AST](ast: N, checks: Checks) -> N:
    """``ast`` with ``checks`` run after its own."""
    return replace(ast, checks=(*ast.checks, *checks) if ast.checks else checks)


@dataclass(frozen=True, slots=True, eq=False)
class Refinement(AST):
    """A node accepting the values a predicate selects, unchanged."""

    def _parse(self, input: object, options: ParseOptions) -> Exit[object, Issue]:
        if self.accepts(input):
            return Success(input)
        return invalid_type(self, input, options)

    @abstractmethod
    def accepts(self, input: object) -> bool: ...


def invalid_type(ast: AST, input: object, options: ParseOptions) -> Failure[Issue]:
    return fail_exit(InvalidType(ast, reported(input, options)))


def issue_of(failure: Failure[Issue]) -> Issue | None:
    """The issue of a failed parse, or ``None`` when its cause holds
    anything else (a defect is never a mismatch)."""
    reasons = failure.cause.reasons
    if reasons and all(isinstance(r, Fail) and is_issue(r.error) for r in reasons):
        first = reasons[0]
        return first.error if isinstance(first, Fail) else None
    return None
