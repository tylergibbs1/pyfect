"""Checks (Effect's ``SchemaAST.Filter`` / ``FilterGroup``): validations a
node runs on a value of its own kind.

A ``Filter`` runs a function giving ``None`` (pass) or an issue; a
``FilterGroup`` runs several checks as one. Each failure is wrapped in an
``issue.Filter`` naming the check, so the formatter can print the check's
``message`` or ``"Expected <expected>"``. With ``errors="first"`` the first
failure stops the checks; with ``errors="all"`` every check runs unless one
marked ``abort()`` fails.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any, Generic, TypeVar

from pyfect.schema import issue as _issue
from pyfect.schema.issue import Composite, InvalidValue, Issue, Path, Pointer, is_issue, reported

if TYPE_CHECKING:
    from pyfect.schema._options import ParseOptions
    from pyfect.schema.ast._base import AST, Annotations

type FilterIssue = str | Issue | tuple[Path, str | Issue]
"""One failure a filter function reports: a message, an issue, or either
at a path below the value (Effect's ``{ path, issue }``)."""

type FilterOutput = bool | FilterIssue | list[FilterIssue] | None
"""What a filter function gives: ``True`` / ``None`` / ``[]`` to accept,
``False`` (``"Expected <expected>"``), one failure or a list of them."""


T_contra = TypeVar("T_contra", contravariant=True)


@dataclass(frozen=True, slots=True, eq=False)
class Filter(Generic[T_contra]):
    """One check. ``run(value, ast, options)`` gives ``None`` or the issue;
    ``annotations`` describe it (``expected``, ``message``, ``title``, ...);
    an ``aborted`` filter stops the checks after it when it fails."""

    run: Callable[[T_contra, AST, ParseOptions], Issue | None]
    annotations: Annotations | None = None
    aborted: bool = False

    def annotate(self, /, **annotations: object) -> Filter[T_contra]:
        """This filter with ``annotations`` merged over its own."""
        return replace(self, annotations={**(self.annotations or {}), **annotations})

    def abort(self) -> Filter[T_contra]:
        """This filter, stopping the checks after it when it fails."""
        return replace(self, aborted=True)

    def and_[T](self: Filter[T], other: Check[T], /, **annotations: object) -> FilterGroup[T]:
        """This check and ``other`` as one group (Effect's ``and``)."""
        return FilterGroup((self, other), annotations or None)


@dataclass(frozen=True, slots=True, eq=False)
class FilterGroup(Generic[T_contra]):
    """Several checks run as one; ``annotations`` describe the group
    (its ``expected`` is the default text of its members' failures)."""

    checks: tuple[Check[T_contra], *tuple[Check[T_contra], ...]]
    annotations: Annotations | None = None

    def annotate(self, /, **annotations: object) -> FilterGroup[T_contra]:
        return replace(self, annotations={**(self.annotations or {}), **annotations})

    def and_[T](self: FilterGroup[T], other: Check[T], /, **annotations: object) -> FilterGroup[T]:
        return FilterGroup((self, other), annotations or None)


type Check[T] = Filter[T] | FilterGroup[T]


def has_check(checks: Sequence[Check[Any]] | None, id: str) -> bool:
    """Whether a check with the ``representation`` id ``id`` is among
    ``checks`` or the groups inside them (Effect's ``hasCheck``)."""
    for check in checks or ():
        if isinstance(check, FilterGroup):
            if has_check(check.checks, id):
                return True
            continue
        representation = (check.annotations or {}).get("representation")
        if isinstance(representation, Mapping) and representation.get("id") == id:  # pyright: ignore[reportUnknownMemberType]
            return True
    return False


def make_filter[T](
    predicate: Callable[[T], FilterOutput], /, *, abort: bool = False, **annotations: object
) -> Filter[T]:
    """A filter from a function returning a ``FilterOutput`` (Effect's
    ``makeFilter``)."""

    return filter_of(predicate, annotations or None, abort)


def filter_of[T](
    predicate: Callable[[T], FilterOutput],
    annotations: Annotations | None = None,
    abort: bool = False,
) -> Filter[T]:
    """``make_filter`` with the annotations as one mapping."""

    def run(input: T, ast: AST, options: ParseOptions) -> Issue | None:
        return normalize_filter_output(ast, predicate(input), input, options)

    return Filter(run, annotations, abort)


def make_filter_by_guard[T](
    guard: Callable[[T], bool], annotations: Annotations | None = None
) -> Filter[T]:
    """A filter accepting what ``guard`` accepts; it always aborts, as the
    checks after a guard may rely on it."""

    def run(input: T, ast: AST, options: ParseOptions) -> Issue | None:
        return None if guard(input) else InvalidValue(None, reported(input, options))

    return Filter(run, annotations, True)


def normalize_filter_output(
    ast: AST, out: FilterOutput, input: object, options: ParseOptions
) -> Issue | None:
    """The issue a filter function's output stands for, or ``None``."""
    if out is None or out is True:
        return None
    if out is False:
        return InvalidValue(None, reported(input, options))
    if not isinstance(out, list):
        return _filter_issue(out, input, options)
    issues = [_filter_issue(entry, input, options) for entry in out]
    if not issues:
        return None
    if len(issues) == 1:
        return issues[0]
    return Composite(ast, (issues[0], *issues[1:]), reported(input, options))


def _filter_issue(entry: FilterIssue, input: object, options: ParseOptions) -> Issue:
    if isinstance(entry, str):
        return InvalidValue({"message": entry}, reported(input, options))
    if is_issue(entry):
        return entry
    path, inner = entry
    return Pointer(path, _filter_issue(inner, input, options) if isinstance(inner, str) else inner)


def collect_issues(
    checks: Sequence[Check[object]], value: object, ast: AST, options: ParseOptions
) -> tuple[Issue, *tuple[Issue, ...]] | None:
    """The failures of ``checks`` on ``value``, or ``None``."""
    issues: list[_issue.Filter] = []
    _collect(checks, value, ast, options, issues)
    return (issues[0], *issues[1:]) if issues else None


def _collect(
    checks: Sequence[Check[object]],
    value: object,
    ast: AST,
    options: ParseOptions,
    issues: list[_issue.Filter],
) -> bool:
    """Append the failures; ``True`` when the checks must stop."""
    every = options.get("errors") == "all"
    for check in checks:
        if isinstance(check, FilterGroup):
            if _collect(check.checks, value, ast, options, issues):
                return True
            continue
        failure = check.run(value, ast, options)
        if failure is not None:
            issues.append(_issue.Filter(check, failure, reported(value, options)))
            if not every or check.aborted:
                return True
    return False
