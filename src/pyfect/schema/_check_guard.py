"""Checks from ``Annotated`` metadata, which pyright cannot match to the field's type
(it checks ``S.Int.check(S.is_min_length(1))``, not a check inside ``Annotated``).

``require_fitting`` is that type check, made where the schema is derived (a schema class's
definition): it runs the check on a value of each primitive kind the field's type holds (a
string, a number, a boolean, ``None``, a literal, an array) and raises ``CheckRaisedError``
naming the field and the check when it raises ``TypeError`` or ``AttributeError``, as Effect's
compiler rejects such a check. ``guard_check`` covers what that can't decide (a declaration,
a class): a check that raises on a value names the field and the check, instead of escaping
as a defect that the synchronous adapters report as ``"Constructor adapter can only throw
schema issues"``. Effect has no schema error for a filter that throws, so both are a
``TypeError``, chained from what the check raised; the adapters raise it as it is
(``_adapters.schema_error_of``)."""

from __future__ import annotations

import re
from dataclasses import replace
from typing import TYPE_CHECKING, Any

from pyfect.exit import Success
from pyfect.schema import ast

if TYPE_CHECKING:
    from pyfect.schema._options import ParseOptions
    from pyfect.schema.issue import Issue


class CheckRaisedError(TypeError):
    """A field's check raised on a value; ``__cause__`` is what it raised."""


def guard_check(check: ast.Check[Any], field: str | None) -> ast.Check[Any]:
    """``check``, raising ``CheckRaisedError`` naming ``field`` and the check when its
    function raises. Without a ``field`` (no class or struct around it) it is unchanged."""
    if field is None:
        return check
    if isinstance(check, ast.FilterGroup):
        first, *rest = (guard_check(c, field) for c in check.checks)
        return replace(check, checks=(first, *rest))
    run = check.run
    name = _name(check)

    def guarded(value: Any, node: ast.AST, options: ParseOptions) -> Issue | None:
        try:
            return run(value, node, options)
        except Exception as error:
            raise CheckRaisedError(
                f"{field}: the check{name} raised on {value!r}: {type(error).__name__}: {error}. "
                "Give the field a check that fits its type"
            ) from error

    return replace(check, run=guarded)


_KINDS = (ast.String, ast.Number, ast.Boolean, ast.BigInt, ast.Null, ast.Arrays)
"""The types whose values ``require_fitting`` can make without knowing more."""

_CANDIDATES: tuple[object, ...] = ("", 0, False, None, (), [])

_NO_CHECKS: ParseOptions = {"disable_checks": True}


def require_fitting(check: ast.Check[Any], node: ast.AST, field: str | None) -> None:
    """Raise ``CheckRaisedError`` when ``check`` raises ``TypeError`` or ``AttributeError`` on a
    value of a kind ``node``'s type holds (a length check on an ``int``), naming ``field``."""
    for kind, sample in _samples(node.to_type()):
        for one in _filters(check):
            try:
                one.run(sample, kind, {})
            except (TypeError, AttributeError) as error:
                raise CheckRaisedError(
                    f"{field or 'Annotated'}: the check{_name(one)} cannot check "
                    f"{kind.expected()} values: on {sample!r} it raised "
                    f"{type(error).__name__}: {error}. Give the field a check that fits its type"
                ) from error


def _samples(node: ast.AST) -> list[tuple[ast.AST, object]]:
    """A value of each primitive kind ``node`` holds, with that kind's node."""
    if isinstance(node, ast.Union):
        return [sample for member in node.types for sample in _samples(member.to_type())]
    if isinstance(node, ast.Literal):
        return [(node, node.literal)]
    if not isinstance(node, _KINDS):
        return []
    for candidate in _CANDIDATES:
        if type(ast.run_now(node.parse(candidate, _NO_CHECKS))) is Success:
            return [(node, candidate)]
    return []


def _filters(check: ast.Check[Any]) -> list[ast.Filter[Any]]:
    if isinstance(check, ast.FilterGroup):
        return [one for inner in check.checks for one in _filters(inner)]
    return [check]


def _name(check: ast.Filter[Any]) -> str:
    """`` is_min_length (a value with a length of at least 1)``: the function that made
    the check, from its representation id, and what it expects; empty when unknown."""
    annotations = check.annotations or {}
    representation = annotations.get("representation")
    made_by = ""
    if isinstance(representation, dict):
        id_ = str(representation.get("id", ""))  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]
        tail = id_.rsplit("/", 1)[-1]
        made_by = " " + re.sub(r"(?<!^)(?=[A-Z])", "_", tail).lower() if tail else ""
    expected = annotations.get("expected")
    return f"{made_by} ({expected})" if made_by and expected else made_by
