"""Why a value was rejected (Effect's ``SchemaIssue``): a tree of issues.

Leaves say what went wrong (``InvalidType``: not a value of the expected
kind; ``InvalidValue``: the right kind, a wrong value; ``MissingKey``,
``UnexpectedKey``, ``Forbidden``, ``OneOf``: several union members matched).
``Pointer`` says where (a path below the enclosing value), ``Composite``
groups several issues of one value, ``Filter`` wraps the issue of a failed
check, ``AnyOf`` the issues of a union's members, and ``Encoding`` an issue
raised while transforming a value.

``input`` is ``Some(value)`` only when parsing ran with ``report_input=True``
(the rejected value is then kept and printed); otherwise ``None``.
``format_issue`` is Effect's default formatter: each leaf's message, with
``\\n  at ["key"][0]`` below the root.
"""

from __future__ import annotations

from collections.abc import Hashable, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, TypeIs

from pyfect.logger._text import format_unknown, json_quote
from pyfect.option import Option, Some

if TYPE_CHECKING:
    from pyfect.schema._options import ParseOptions
    from pyfect.schema.ast import AST, Check, Union
    from pyfect.schema.ast import Filter as AstFilter

type PathKey = Hashable
"""A key of a path: a mapping key (a ``str`` in decoded JSON) or an index."""
type Path = tuple[PathKey, ...]
type IssueAnnotations = Mapping[str, object]
"""Annotations of a leaf issue; ``message`` replaces its text, ``expected``
fills ``"Expected <...>"``."""


def reported(input: object, options: ParseOptions) -> Option[object]:
    """``input`` as an issue keeps it: only under ``report_input``."""
    return Some(input) if options.get("report_input") else None


@dataclass(frozen=True, slots=True)
class InvalidType:
    """``input`` is not a value of the kind ``ast`` expects."""

    ast: AST
    input: Option[object] = None


@dataclass(frozen=True, slots=True)
class InvalidValue:
    """A value of the right kind that is not allowed."""

    annotations: IssueAnnotations | None = None
    input: Option[object] = None


@dataclass(frozen=True, slots=True)
class MissingKey:
    """A required key is absent; ``annotations`` are the key's."""

    annotations: IssueAnnotations | None = None


@dataclass(frozen=True, slots=True)
class UnexpectedKey:
    """A key the schema does not declare (``on_excess_property="error"``)."""

    ast: AST
    input: Option[object] = None


@dataclass(frozen=True, slots=True)
class Forbidden:
    """An operation that is not allowed at all."""

    annotations: IssueAnnotations | None = None
    input: Option[object] = None


@dataclass(frozen=True, slots=True)
class Pointer:
    """``issue`` at ``path``, relative to the enclosing value."""

    path: Path
    issue: Issue


@dataclass(frozen=True, slots=True)
class Composite:
    """Several issues of one value (``ast``'s), printed one after another."""

    ast: AST
    issues: tuple[Issue, *tuple[Issue, ...]]
    input: Option[object] = None


@dataclass(frozen=True, slots=True)
class Encoding:
    """``issue`` raised while transforming a value of ``ast``."""

    ast: AST
    issue: Issue
    input: Option[object] = None


@dataclass(frozen=True, slots=True)
class Filter:
    """``issue`` raised by the check ``filter`` on a value."""

    filter: AstFilter[Any]
    issue: Issue
    input: Option[object] = None


@dataclass(frozen=True, slots=True)
class AnyOf:
    """No member of the union ``ast`` matched; ``issues`` are the tried
    members' (none when no member could take the value)."""

    ast: Union
    issues: tuple[Issue, ...]
    input: Option[object] = None


@dataclass(frozen=True, slots=True)
class OneOf:
    """Several members of the ``"one_of"`` union ``ast`` matched."""

    ast: Union
    successes: tuple[AST, ...]
    input: Option[object] = None


type Leaf = InvalidType | InvalidValue | MissingKey | UnexpectedKey | Forbidden | OneOf
type Issue = Leaf | Filter | Pointer | Composite | Encoding | AnyOf


def is_issue(value: object) -> TypeIs[Issue]:
    return isinstance(
        value,
        InvalidType
        | InvalidValue
        | MissingKey
        | UnexpectedKey
        | Forbidden
        | OneOf
        | Filter
        | Pointer
        | Composite
        | Encoding
        | AnyOf,
    )


def format_issue(issue: Issue) -> str:
    """Effect's default formatter (``SchemaIssue.defaultFormatter``): one
    message per leaf, each followed by ``\\n  at <path>`` below the root."""
    return _format(issue, "", None)


def format_path(path: Path) -> str:
    """``["a"][1]``: string keys as JSON strings, any other key (an index)
    as ``format_unknown`` prints it."""
    return "".join(f"[{_format_key(key)}]" for key in path)


def _format_key(key: PathKey) -> str:
    return json_quote(key) if isinstance(key, str) else format_unknown(key)


def _format(issue: Issue, path: str, override: str | None) -> str:
    match issue:
        case Filter(issue=inner):
            return _format(inner, path, override if override is not None else filter_message(issue))
        case Encoding(issue=inner):
            return _format(inner, path, override)
        case Pointer(segments, inner):
            return _format(inner, path + format_path(segments), override)
        case Composite(issues=issues):
            return "\n".join(_format(i, path, override) for i in issues)
        case AnyOf(issues=issues) if issues:
            return "\n".join(_format(i, path, override) for i in issues)
        case AnyOf(ast=ast):
            found = override if override is not None else _find_message(issue)
            message = found if found is not None else _expected_message(ast.expected(), issue.input)
        case _:
            message = override if override is not None else leaf_message(issue)
    return f"{message}\n  at {path}" if path else message


def leaf_message(issue: Leaf) -> str:
    """A leaf's text: its ``message`` annotation, else the default one
    (Effect's ``defaultLeafHook``)."""
    message = _find_message(issue)
    return message if message is not None else _default_leaf_message(issue)


_WITH_INPUT: dict[type, tuple[str, str]] = {
    UnexpectedKey: ("Expected no excess property", "Unexpected key with value"),
    OneOf: (
        "Expected exactly one member to match",
        "Expected exactly one member to match the input",
    ),
}


def _default_leaf_message(issue: Leaf) -> str:
    match issue:
        case InvalidType(ast=ast):
            return _expected_message(ast.expected(), issue.input)
        case InvalidValue():
            expected = _find_expected(issue)
            if expected is not None:
                return _expected_message(expected, issue.input)
            return _with_input("Expected a valid value", "Invalid data", issue.input)
        case MissingKey():
            return "Missing key"
        case Forbidden():
            return "Forbidden operation"
        case UnexpectedKey() | OneOf():
            return _with_input(*_WITH_INPUT[type(issue)], issue.input)


def _with_input(without: str, prefix: str, input: Option[object]) -> str:
    return without if input is None else f"{prefix} {_show(input)}"


def filter_message(issue: Filter) -> str | None:
    """The text of a failed check (Effect's ``defaultCheckHook`` and its
    fallback): the check's ``message``, the inner issue's, then for an
    ``InvalidValue`` ``"Expected <expected>"`` from the inner issue or the
    check."""
    message = _find_message(issue)
    if message is None:
        message = _find_message(issue.issue)
    if message is not None or not isinstance(issue.issue, InvalidValue):
        return message
    expected = _find_expected(issue.issue)
    if expected is None:
        return _expected_message(format_check(issue.filter), issue.input)
    return _expected_message(expected, issue.issue.input)


def format_check(check: Check[Any]) -> str:
    """What a check expects: its ``expected`` annotation, ``<filter>``, or a
    group's members joined by ``" & "``."""
    expected = (check.annotations or {}).get("expected")
    if isinstance(expected, str):
        return expected
    from pyfect.schema.ast import FilterGroup

    if isinstance(check, FilterGroup):
        return " & ".join(format_check(c) for c in check.checks)
    return "<filter>"


def _find_expected(issue: InvalidValue) -> str | None:
    expected = (issue.annotations or {}).get("expected")
    return expected if isinstance(expected, str) else None


def _find_message(issue: Issue) -> str | None:
    """The issue's own ``message`` annotation (``message_missing_key`` /
    ``message_unexpected_key`` for those leaves)."""
    match issue:
        case Pointer() | Composite():
            return None
        case Encoding(issue=inner):
            return _find_message(inner)
        case Filter(filter=check):
            annotations = check.annotations
        case InvalidType(ast=ast) | UnexpectedKey(ast=ast) | AnyOf(ast=ast) | OneOf(ast=ast):
            annotations = ast.annotations
        case InvalidValue(annotations=annotations) | Forbidden(annotations=annotations):
            pass
        case MissingKey(annotations=annotations):
            pass
    key = (
        "message_missing_key"
        if isinstance(issue, MissingKey)
        else "message_unexpected_key"
        if isinstance(issue, UnexpectedKey)
        else "message"
    )
    message = (annotations or {}).get(key)
    return message if isinstance(message, str) else None


def _expected_message(expected: str, input: Option[object]) -> str:
    return f"Expected {expected}" if input is None else f"Expected {expected}, got {_show(input)}"


def _show(input: Some[object]) -> str:
    return format_unknown(input.value)
