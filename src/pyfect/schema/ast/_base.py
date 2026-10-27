"""The node every schema AST extends, and the helpers that rebuild one."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Hashable, Mapping
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Any, ClassVar

from pyfect.cause import Fail
from pyfect.exit import Exit, Failure, Success
from pyfect.exit import die as die_exit
from pyfect.exit import fail as fail_exit
from pyfect.schema._options import ParseOptions
from pyfect.schema.ast._check import collect_issues
from pyfect.schema.ast._encoding import Encoding, decode_chain, flip_encoding
from pyfect.schema.ast._result import MISSING, MISSING_EXIT, ParseResult, flat_map
from pyfect.schema.issue import Composite, InvalidType, Issue, Pointer, is_issue, reported

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
    ``key_annotations`` describe the key holding the node in a struct.
    ``encoding`` says how the node decodes from other nodes (see
    ``_encoding.py``); a node without one parses its input itself.
    """

    annotations: Annotations | None = field(default=None, kw_only=True)
    checks: Checks | None = field(default=None, kw_only=True)
    key_annotations: Annotations | None = field(default=None, kw_only=True)
    """Annotations of the key holding this node in a struct
    (``message_missing_key``, ...): Effect's ``annotateKey``."""
    encoding: Encoding | None = field(default=None, kw_only=True)
    encoding_checks: Checks | None = field(default=None, kw_only=True)
    """Checks of the decoded side kept by a flipped composite: they run on
    its input (Effect's ``encodingChecks``)."""
    optional_key: bool = field(default=False, kw_only=True)
    """A struct key holding this node may be missing (Effect's
    ``optionalKey`` context): set on the source of a transformation, so a
    key is optional on the encoded side only."""
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

    def parse(self, input: object, options: ParseOptions) -> ParseResult:
        """``input`` decoded through the node's encoding, then checked
        against the node and its checks: an ``Exit``, or an ``Effect`` when
        a transformation needs one."""
        encoding = self.encoding
        if encoding is not None:
            return decode_chain(self, encoding, input, options)
        # ``parse_local``, inlined: this is the hot path.
        if input is MISSING:
            return MISSING_EXIT
        result = self._parse(input, options)
        if (self.checks is None and self.encoding_checks is None) or options.get("disable_checks"):
            return result
        if type(result) is Success:
            return self._run_checks(input, result.value, options)
        return flat_map(result, lambda value: self._run_checks(input, value, options))

    def parse_local(self, input: object, options: ParseOptions) -> ParseResult:
        """``input`` checked against the node itself (not its encoding) and
        its checks. ``MISSING`` stays missing. A subclass overriding it
        overrides ``parse`` too (``parse`` inlines this)."""
        if input is MISSING:
            return MISSING_EXIT
        result = self._parse(input, options)
        if (self.checks is None and self.encoding_checks is None) or options.get("disable_checks"):
            return result
        if type(result) is Success:
            return self._run_checks(input, result.value, options)
        return flat_map(result, lambda value: self._run_checks(input, value, options))

    def _run_checks(self, input: object, value: object, options: ParseOptions) -> ParseResult:
        try:
            if self.encoding_checks is not None:
                issues = collect_issues(self.encoding_checks, input, self, options)
                if issues is not None:
                    return fail_exit(Composite(self, issues, reported(input, options)))
            if self.checks is not None:
                issues = collect_issues(self.checks, value, self, options)
                if issues is not None:
                    return fail_exit(Composite(self, issues, reported(value, options)))
        except Exception as defect:
            # A check that raises is a defect, as in Effect.
            return die_exit(defect)
        return Success(value)

    @abstractmethod
    def _parse(self, input: object, options: ParseOptions) -> ParseResult:
        """``input`` checked against the node's own kind, without checks."""

    def flip(self) -> AST:
        """The node that encodes what this one decodes. A node without an
        encoding flips its parts; a leaf is its own flip."""
        encoding = self.encoding
        if encoding is not None:
            return flip_encoding(self, encoding)
        return self._flip()

    def _flip(self) -> AST:
        """The flip of the node's own parts (it has no encoding)."""
        return self

    def to_type(self) -> AST:
        """The node's decoded side: no encoding, its parts' decoded sides."""
        return (self if self.encoding is None else replace(self, encoding=None))._to_type()

    def _to_type(self) -> AST:
        """The decoded side of the node's own parts (it has no encoding)."""
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


def join_checks(first: Checks | None, second: Checks | None) -> Checks | None:
    if first is None:
        return second
    if second is None:
        return first
    return (*first, *second)


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


def at_key(
    ast: AST, key: Hashable, failure: Failure[Issue], input: object, options: ParseOptions
) -> Failure[Issue]:
    """A child's failure that is not only issues (a defect with them), its
    issues placed at ``key`` of ``ast``'s input; the defects stay."""
    shown = reported(input, options)
    return Failure(
        failure.cause.map(lambda issue: Composite(ast, (Pointer((key,), issue),), shown))
    )


def issue_of(failure: Failure[Issue]) -> Issue | None:
    """The issue of a failed parse, or ``None`` when its cause holds
    anything else (a defect is never a mismatch)."""
    reasons = failure.cause.reasons
    if reasons and all(isinstance(r, Fail) and is_issue(r.error) for r in reasons):
        first = reasons[0]
        return first.error if isinstance(first, Fail) else None
    return None
