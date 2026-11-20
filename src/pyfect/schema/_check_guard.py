"""``guard_check``: a check from ``Annotated`` metadata that raises (a length check on an
``int``) says which field and which check, instead of escaping as a defect that the
synchronous adapters report as ``"Constructor adapter can only throw schema issues"``.

pyright checks ``S.Int.check(S.is_min_length(1))`` but not a check inside ``Annotated``, so a
check that doesn't fit the field's type shows first at run time. Effect has no schema error
for a filter that throws, so this is a ``TypeError``, chained from what the check raised; the
adapters raise it as it is (``_adapters.schema_error_of``)."""

from __future__ import annotations

import re
from dataclasses import replace
from typing import TYPE_CHECKING, Any

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
