"""The node every schema AST extends, and the helpers that rebuild one."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable, Hashable, Iterable, Mapping
from dataclasses import MISSING as NO_DEFAULT
from dataclasses import dataclass, field, fields
from typing import TYPE_CHECKING, Any, ClassVar, cast

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
    compiler_entry: list[object] = field(
        default_factory=list[object], init=False, repr=False, compare=False
    )
    """The compiler registry's entry for this exact node (Effect's registry
    ``WeakMap``), held by ``pyfect.schema.compiler``."""
    compiler_facts: list[object] = field(
        default_factory=list[object], init=False, repr=False, compare=False
    )
    """What a generated fast path through this node needs, worked out once
    (Effect's ``codegen`` facts ``WeakMap``)."""
    _encoded_side: list[AST] = field(
        default_factory=list["AST"], init=False, repr=False, compare=False
    )
    """``to_encoded``, made once; the result is its own encoded side
    (Effect's ``memoizeIdempotent``)."""
    tag: ClassVar[str]
    UNSHARED_FIELDS: ClassVar[frozenset[str]] = frozenset(
        {"context_owner", "body_owner", "_type_side", "_flip_side", "_encoded_side"}
    )
    """Fields a copy never shares: what a node is a copy of, and its
    projections, which change with its metadata."""

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
        a transformation needs one. Once a decoder is installed in the
        compiler registry (``pyfect.schema.compiler``), the node's registry
        entry parses it."""
        if _dispatch is not None:
            return _dispatch(self, input, options)
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

    def interpret(self, input: object, options: ParseOptions) -> ParseResult:
        """``parse`` without the registry: the interpreter (Effect's
        ``Interpreter.compile``). A subclass overriding it sets ``parse =
        parse_by_interpreting``."""
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
            owner = self.owner()
            if encoding is not None:
                flipped = flip_encoding(self, encoding)
            elif owner is not self:
                # A contextual copy's flip is its owner's, in the copy's
                # context: one schema to derivations.
                flipped_owner = owner.flip()
                flipped = self if flipped_owner is owner else _with_context(flipped_owner, self)
            else:
                flipped = self._flip()
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
            typed = owner.to_type()
            if typed is owner and self.encoding is None:
                return self
            return _with_context(typed, self)
        if not self._type_side:
            base = self if self.encoding is None else replace_encoding(self, None)
            typed = base._to_type()
            encoding_checks = typed.encoding_checks
            if encoding_checks is not None:
                # Checks of the encoded side hold for the decoded one when no
                # part transforms; else only those of the shape (a size).
                if _preserves_encoding_checks(base):
                    promoted = encoding_checks
                elif typed._keeps_structural_checks():
                    promoted = structural_checks(encoding_checks)
                else:
                    promoted = None
                typed = copy(
                    typed, encoding_checks=None, checks=join_checks(typed.checks, promoted)
                )
            self._type_side.append(typed)
            if typed is not self and not typed._type_side:
                typed._type_side.append(typed)
        return self._type_side[0]

    def _to_type(self) -> AST:
        """The node with its parts' decoded sides (it has no encoding); its
        ``encoding_checks`` stay for ``to_type`` to promote."""
        return self

    def children(self) -> Iterable[AST]:
        """The nodes this one parses its parts with (Effect's ``recur``); a
        ``Suspend``'s target is not made for this."""
        return ()

    def is_opaque(self) -> bool:
        """Its values may have another shape than its input though it has no
        encoding: a ``Suspend`` (not made to find out), a class's or an enum's
        decoding."""
        return False

    def _keeps_structural_checks(self) -> bool:
        """Its encoded side's checks of the shape (``structural_checks``)
        hold on the decoded side even when a part transforms."""
        return False

    def __str__(self) -> str:
        return f"<{self.tag}>"


type Dispatch = Callable[[AST, object, ParseOptions], ParseResult]

_dispatch: Dispatch | None = None
"""The compiler registry's parse, once a decoder or compiler is installed
(Effect's ``compilerAdaptersEnabled``); ``None`` keeps the interpreter."""


def set_dispatch(dispatch: Dispatch | None) -> None:
    """Route every node's ``parse`` through ``dispatch`` (``None``: back to
    the interpreter). Only the compiler registry calls it."""
    global _dispatch  # noqa: PLW0603 - read on every parse, so a plain module global
    _dispatch = dispatch


def dispatching() -> bool:
    """A compiler registry routes parses: a missing key then reaches its
    node's installed decoder as ``MISSING``, as in Effect."""
    return _dispatch is not None


def parse_by_interpreting(self: AST, input: object, options: ParseOptions) -> ParseResult:
    """``parse`` for a node class that overrides ``interpret``."""
    if _dispatch is not None:
        return _dispatch(self, input, options)
    return self.interpret(input, options)


def _preserves_encoding_checks(ast: AST) -> bool:
    """No part of ``ast``, at any depth, transforms (Effect's
    ``canPreserveEncodingChecks``)."""
    pending = list(ast.children())
    seen: set[int] = set()
    while pending:
        child = pending.pop()
        if id(child) in seen:
            continue
        seen.add(id(child))
        if child.encoding is not None or child.is_opaque():
            return False
        pending.extend(child.children())
    return True


STRUCTURAL = "~structural"
"""The annotation of a check of a value's shape (a length, a size, a key
count): it holds on both sides of a composite whose parts transform."""


def _is_structural(check: Check[Any]) -> bool:
    from pyfect.schema.ast._check import FilterGroup  # _check imports this module.

    if (check.annotations or {}).get(STRUCTURAL) is True:
        return True
    return isinstance(check, FilterGroup) and all(_is_structural(c) for c in check.checks)


def structural_checks(checks: Checks) -> Checks | None:
    """The structural checks among ``checks``, a group's structural members
    taken out of it (Effect's ``extractStructuralChecks``)."""
    from pyfect.schema.ast._check import FilterGroup  # _check imports this module.

    def extract(check: Check[Any]) -> list[Check[Any]]:
        if _is_structural(check):
            return [check]
        if isinstance(check, FilterGroup):
            return [found for member in check.checks for found in extract(member)]
        return []

    out = [found for check in checks for found in extract(check)]
    return (out[0], *out[1:]) if out else None


_METADATA = frozenset(
    {
        "annotations",
        "checks",
        "key_annotations",
        "encoding",
        "encoding_checks",
        "optional_key",
        "constructor_default",
    }
)
_CONTEXT = frozenset({"key_annotations", "optional_key", "constructor_default"})


def copy[N: AST](ast: N, **changes: object) -> N:
    """``ast`` with ``changes`` to its metadata (``_METADATA``): its class,
    parts and prepared data (a template's segments, a suspended target) are
    shared, its projections are not (Effect's ``copy``). A copy that changes
    only its key context shares ``ast``'s body (``owner``)."""
    unknown = changes.keys() - _METADATA
    if unknown:
        raise TypeError(f"copy changes only metadata, not {sorted(unknown)}")
    out = object.__new__(type(ast))
    for f in fields(ast):
        name = f.name
        if name in changes:
            value = changes[name]
        elif name in ast.UNSHARED_FIELDS:
            value = f.default if f.default_factory is NO_DEFAULT else f.default_factory()
        else:
            value = getattr(ast, name)
        object.__setattr__(out, name, value)
    if changes.keys() <= _CONTEXT:
        object.__setattr__(out, "context_owner", ast.owner())
    return out


def encoded_optional(type: AST, *, optional: bool) -> bool:
    """Whether a key or element of ``type`` (``optional`` on the type side)
    may be missing when encoded: a node that is ``optional_key`` itself says
    so through its encoded side (Effect's ``isOptional`` of ``toEncoded``);
    otherwise an optional key stays optional, or a decoding default makes
    a required one optional."""
    flipped = type.flip().optional_key
    return flipped if type.optional_key else optional or flipped


def map_or_same[A](items: tuple[A, ...], f: Callable[[A], A]) -> tuple[A, ...]:
    """``f`` of each item, or ``items`` itself when ``f`` returns every item
    unchanged (``is``), Effect's ``mapOrSame``."""
    out: list[A] | None = None
    for i, item in enumerate(items):
        mapped = f(item)
        if out is not None:
            out.append(mapped)
        elif mapped is not item:
            out = [*items[:i], mapped]
    return items if out is None else tuple(out)


def replace_checks[N: AST](ast: N, checks: Checks | None) -> N:
    """``ast`` with ``checks`` in place of its own; ``ast`` itself when they
    are the same tuple. A ``Suspend`` takes no checks (its target does)."""
    if ast.tag == "Suspend" and checks:
        raise ValueError("Cannot add checks to Suspend")
    return ast if ast.checks is checks else copy(ast, checks=checks)


def replace_encoding[N: AST](ast: N, encoding: Encoding | None) -> N:
    """``ast`` decoding through ``encoding`` instead of its own; ``ast``
    itself when it is the same."""
    return ast if ast.encoding is encoding else copy(ast, encoding=encoding)


def annotate[N: AST](ast: N, annotations: Annotations) -> N:
    """``ast`` with ``annotations`` merged over its own; on a node with
    checks they go to the last check, which then describes the node."""
    if ast.checks:
        *rest, last = ast.checks
        return replace_checks(ast, (*rest, last.annotate(**annotations)))
    return copy(ast, annotations={**(ast.annotations or {}), **annotations})


def append_checks[N: AST](ast: N, checks: Checks) -> N:
    """``ast`` with ``checks`` run after its own."""
    return replace_checks(ast, (*ast.checks, *checks) if ast.checks else checks)


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
    """``node`` with another key context (Effect's ``replaceContext``): a
    copy sharing ``node``'s body (its ``owner``), ``node`` itself when the
    context is its own, or the owner when the context is the owner's."""
    return _in_context(
        node,
        node.key_annotations if key_annotations is None else key_annotations,
        node.optional_key if optional_key is None else optional_key,
        node.constructor_default,
    )


def _in_context[A: AST](
    node: A,
    key_annotations: Annotations | None,
    optional_key: bool,
    constructor_default: Effect[object, Issue] | None,
) -> A:
    def holds(other: AST) -> bool:
        return (
            other.key_annotations == key_annotations
            and other.optional_key == optional_key
            and other.constructor_default is constructor_default
        )

    if holds(node):
        return node
    owner = node.owner()
    if owner is not node and owner.encoding is node.encoding and holds(owner):
        return cast("A", owner)
    return copy(
        node,
        key_annotations=key_annotations,
        optional_key=optional_key,
        constructor_default=constructor_default,
    )


def _with_context(typed: AST, source: AST) -> AST:
    return _in_context(
        typed, source.key_annotations, source.optional_key, source.constructor_default
    )


def with_constructor_default[A: AST](ast: A, default: Effect[object, Issue]) -> A:
    """``ast`` whose missing key or element a constructor fills with
    ``default``'s value (Effect's ``SchemaAST.withConstructorDefault``); the
    copy shares ``ast``'s body."""
    require_effect(default, "default")
    return _in_context(ast, ast.key_annotations, ast.optional_key, default)


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
