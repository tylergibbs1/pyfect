"""Operation documents split into the pieces needed to rename and alias
them without a GraphQL parser (Effect's ``GraphQL.DocumentTemplate``).
``@effect/graphql-generator`` emits one per query and mutation.

A ``body`` is ``Parts``: literal text at even indices and, at odd indices,
the variable and fragment names renamed when the operation is repeated
under a prefix. Joining the pieces gives the printed document. A fragment
whose body has a name in it is per-slice (it references a variable); every
other fragment is shared.
"""

from __future__ import annotations

from dataclasses import dataclass

type Parts = tuple[str, ...]
"""Literal text at even indices and names to rename at odd indices."""


@dataclass(frozen=True, slots=True)
class Variable:
    """A variable definition: ``$name:`` followed by ``body`` (its type,
    default value and directives as printed)."""

    name: str
    body: str


@dataclass(frozen=True, slots=True, kw_only=True)
class Selection:
    """A root selection. For a field, ``body`` is everything after its
    name and the response key is ``alias or name``; a fragment spread or
    inline fragment has no ``name`` and ``body`` is the whole selection."""

    body: Parts
    name: str | None = None
    alias: str | None = None


@dataclass(frozen=True, slots=True)
class Fragment:
    """A fragment definition: ``fragment`` and ``name``, then ``body``
    from its type condition on."""

    name: str
    body: Parts


@dataclass(frozen=True, slots=True, kw_only=True)
class DocumentTemplate:
    """The variable definitions, the operation's directives (if any), the
    root selections and the fragments the operation uses, in document
    order."""

    variables: tuple[Variable, ...] = ()
    selections: tuple[Selection, ...]
    fragments: tuple[Fragment, ...] = ()
    directives: Parts | None = None


__all__ = ["DocumentTemplate", "Fragment", "Parts", "Selection", "Variable"]
