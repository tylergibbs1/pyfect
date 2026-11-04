"""The node every schema AST extends, and the helpers that rebuild one."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Hashable, Mapping
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Any, ClassVar

from pyfect._effect_args import require_effect
from pyfect._primitives import known_exit
from pyfect.cause import Fail
from pyfect.exit import Exit, Failure, Success
from pyfect.exit import die as die_exit
from pyfect.exit import fail as fail_exit
from pyfect.schema._options import ParseOptions, is_constructing
from pyfect.schema.ast._check import collect_issues
from pyfect.schema.ast._encoding import Encoding, decode_chain, flip_encoding
from pyfect.schema.ast._result import MISSING, MISSING_EXIT, ParseResult, flat_map, map_issue
from pyfect.schema.issue import Composite, InvalidType, Issue, Pointer, is_issue, reported
from pyfect.schema.issue import Encoding as EncodingIssue

if TYPE_CHECKING:
    from pyfect._core import Effect
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
    constructor_default: Effect[object, Issue] | None = field(
        default=None, kw_only=True, compare=False
    )
    """What a constructor (``make``) gives a missing key or element holding
    this node, parsed by the node (Effect's ``constructorDefault`` context,
    ``with_constructor_default``); decoding never uses it."""
    context_owner: AST | None = field(default=None, init=False, repr=False, compare=False)
    """The node this one copies with only its key context changed (see
    ``replace_context``); any other ``replace`` drops it."""
    body_owner: AST | None = field(default=None, init=False, repr=False, compare=False)
    """The node this one copies with an encoding added (``decode_to``):
    the schema whose values a JSON string holds, say."""
    _type_side: list[AST] = field(
        default_factory=list["AST"], init=False, repr=False, compare=False
    )
    """``to_type()``, made once: contextual copies of a node then share one
    type side, so derivations see one schema (Effect memoizes ``toType``)."""
    _flip_side: list[AST] = field(
        default_factory=list["AST"], init=False, repr=False, compare=False
    )
    """``flip()``, made once (Effect memoizes ``flip``): the flip of a
    recursive schema then refers back to itself, a finite graph."""
    tag: ClassVar[str]

    def owner(self) -> AST:
        """The node whose body this one shares (Effect's
        ``getContextOwner``): copies that change only the key context are
        one schema to derivations and JSON Schema definitions."""
        return self.context_owner or self

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
        if not self._flip_side:
            encoding = self.encoding
            flipped = flip_encoding(self, encoding) if encoding is not None else self._flip()
            self._flip_side.append(flipped)
        return self._flip_side[0]

    def _flip(self) -> AST:
        """The flip of the node's own parts (it has no encoding)."""
        return self

    def to_type(self) -> AST:
        """The node's decoded side: no encoding, its parts' decoded sides. A
        contextual copy's is its owner's, with the copy's key context."""
        owner = self.owner()
        if owner is not self:
            return _with_context(owner.to_type(), self)
        if not self._type_side:
            base = self if self.encoding is None else replace(self, encoding=None)
            self._type_side.append(base._to_type())
        return self._type_side[0]

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


def replace_context[A: AST](
    node: A, *, key_annotations: Annotations | None = None, optional_key: bool | None = None
) -> A:
    """``node`` with another key context: the copy shares ``node``'s body
    (its ``owner``)."""
    out = replace(
        node,
        key_annotations=node.key_annotations if key_annotations is None else key_annotations,
        optional_key=node.optional_key if optional_key is None else optional_key,
    )
    object.__setattr__(out, "context_owner", node.owner())
    return out


def _with_context(typed: AST, source: AST) -> AST:
    if (
        typed.key_annotations == source.key_annotations
        and typed.optional_key == source.optional_key
        and typed.constructor_default is source.constructor_default
    ):
        return typed
    out = replace(
        typed,
        key_annotations=source.key_annotations,
        optional_key=source.optional_key,
        constructor_default=source.constructor_default,
    )
    object.__setattr__(out, "context_owner", typed.owner())
    return out


def with_constructor_default[A: AST](ast: A, default: Effect[object, Issue]) -> A:
    """``ast`` whose missing key or element a constructor fills with
    ``default``'s value (Effect's ``SchemaAST.withConstructorDefault``); the
    copy shares ``ast``'s body."""
    require_effect(default, "default")
    out = replace_context(ast)
    object.__setattr__(out, "constructor_default", default)
    return out


def construct_missing(ast: AST, options: ParseOptions) -> ParseResult | None:
    """The parse of a missing key or element holding ``ast`` under a
    constructor: its constructor default's value, parsed by ``ast`` (a
    failing default is an ``Encoding`` issue, as Effect's ``withDefault``);
    ``None`` without a default or outside a constructor."""
    default = ast.constructor_default
    if default is None or not is_constructing(options):
        return None
    known = known_exit(default)
    if type(known) is Success:
        return ast.parse(known.value, options)
    wrapped = map_issue(default if known is None else known, lambda i: EncodingIssue(ast, i))
    return flat_map(wrapped, lambda value: ast.parse(value, options))
