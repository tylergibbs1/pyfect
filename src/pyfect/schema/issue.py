"""Why a value was rejected (Effect's ``SchemaIssue``): a tree of issues.

Leaves say what went wrong (``InvalidType``: not a value of the expected
kind; ``InvalidValue``: the right kind, a wrong value; ``MissingKey``,
``UnexpectedKey``, ``Forbidden``). ``Pointer`` says where (a path below the
enclosing value), ``Composite`` groups several issues of one value, and
``Encoding`` wraps an issue raised while transforming a value.

``input`` is ``Some(value)`` only when parsing ran with ``report_input=True``
(the rejected value is then kept and printed); otherwise ``None``.
``format_issue`` is Effect's default formatter: each leaf's message, with
``\\n  at ["key"][0]`` below the root.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, TypeIs

from pyfect.logger._text import format_unknown, json_quote
from pyfect.option import Option, Some

if TYPE_CHECKING:
    from pyfect.schema._options import ParseOptions
    from pyfect.schema.ast import AST

type PathKey = str | int
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


type Leaf = InvalidType | InvalidValue | MissingKey | UnexpectedKey | Forbidden
type Issue = Leaf | Pointer | Composite | Encoding


def is_issue(value: object) -> TypeIs[Issue]:
    return isinstance(
        value,
        InvalidType
        | InvalidValue
        | MissingKey
        | UnexpectedKey
        | Forbidden
        | Pointer
        | Composite
        | Encoding,
    )


def format_issue(issue: Issue) -> str:
    """Effect's default formatter (``SchemaIssue.defaultFormatter``)."""
    return _format(issue, "")


def format_path(path: Path) -> str:
    """``["a"][1]``: string keys as JSON strings, indexes bare."""
    return "".join(f"[{json_quote(key) if isinstance(key, str) else key}]" for key in path)


def _format(issue: Issue, path: str) -> str:
    match issue:
        case Encoding(issue=inner):
            return _format(inner, path)
        case Pointer(segments, inner):
            return _format(inner, path + format_path(segments))
        case Composite(issues=issues):
            return "\n".join(_format(i, path) for i in issues)
        case _:
            message = leaf_message(issue)
    return f"{message}\n  at {path}" if path else message


def leaf_message(issue: Leaf) -> str:
    """A leaf's text: its ``message`` annotation, else the default one
    (Effect's ``defaultLeafHook``)."""
    message = _find_message(issue)
    if message is not None:
        return message
    match issue:
        case InvalidType(ast=ast):
            return _expected_message(ast.expected(), issue.input)
        case InvalidValue():
            return _invalid_value_message(issue)
        case MissingKey():
            return "Missing key"
        case UnexpectedKey(input=input):
            return (
                "Expected no excess property"
                if input is None
                else f"Unexpected key with value {_show(input)}"
            )
        case Forbidden():
            return "Forbidden operation"


def _invalid_value_message(issue: InvalidValue) -> str:
    expected = (issue.annotations or {}).get("expected")
    if isinstance(expected, str):
        return _expected_message(expected, issue.input)
    return "Expected a valid value" if issue.input is None else f"Invalid data {_show(issue.input)}"


def _find_message(issue: Leaf) -> str | None:
    match issue:
        case InvalidType(ast=ast) | UnexpectedKey(ast=ast):
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
