"""Why a value was rejected: the issue tree behind ``SchemaError``, and the
text Effect's default formatter prints for it.

This is the slice of Effect's ``SchemaIssue`` that configuration needs
until Schema lands (M8): a leaf says what was expected, a ``Pointer`` says
where, and a ``Composite`` collects the failures of several alternatives.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from pyfect.config_provider import Path
from pyfect.errors import TaggedError


@dataclass(frozen=True, slots=True)
class InvalidType:
    """No value of the expected kind (``"Expected string"``)."""

    expected: str


@dataclass(frozen=True, slots=True)
class InvalidValue:
    """A value of the right kind that fails a check."""

    message: str


@dataclass(frozen=True, slots=True)
class Forbidden:
    """A value that is not allowed at all."""

    message: str


@dataclass(frozen=True, slots=True)
class Pointer:
    """``issue`` at ``path``, relative to the enclosing issue."""

    path: Path
    issue: Issue


@dataclass(frozen=True, slots=True)
class Composite:
    """Several issues, one per failed alternative, printed one after another."""

    issues: tuple[Issue, ...]


type Issue = InvalidType | InvalidValue | Forbidden | Pointer | Composite


def format_issue(issue: Issue) -> str:
    """Effect's default formatting: each leaf's message, followed by
    ``\\n  at ["key"][0]`` when it sits below the root."""
    return _format(issue, "")


def _format(issue: Issue, path: str) -> str:
    match issue:
        case Pointer(segments, inner):
            return _format(inner, path + format_path(segments))
        case Composite(issues):
            return "\n".join(_format(i, path) for i in issues)
        case InvalidType(expected):
            message = f"Expected {expected}"
        case InvalidValue(message) | Forbidden(message):
            pass
    return f"{message}\n  at {path}" if path else message


def format_path(path: Path) -> str:
    """``["a"][1]``: string segments as JSON strings, indexes bare."""
    return "".join(
        f"[{seg}]" if isinstance(seg, int) else f"[{json.dumps(seg, ensure_ascii=False)}]"
        for seg in path
    )


@dataclass(eq=False)
class SchemaError(TaggedError):
    """Data was found but did not have the expected shape or value."""

    issue: Issue

    @property
    def message(self) -> str:
        return format_issue(self.issue)
