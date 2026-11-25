"""Names a generated module may declare, and the scopes that hold them."""

from __future__ import annotations

import builtins
import keyword
import unicodedata
from collections.abc import Callable
from typing import final

# Keywords and builtins: generated code reads builtins (``literal`` writes ``float("nan")``),
# so no declaration or import may shadow one. ``TYPE_CHECKING`` guards type-only imports.
RESERVED = frozenset((*keyword.kwlist, *dir(builtins), "TYPE_CHECKING"))


def is_identifier(name: str) -> bool:
    """A name Python binds as written (it normalizes identifiers with NFKC)."""
    return name.isidentifier() and unicodedata.normalize("NFKC", name) == name


def allocate(preferred_name: str, is_taken: Callable[[str], bool]) -> str:
    """``preferred_name`` made an identifier, with the first free numeric suffix."""
    normalized = unicodedata.normalize("NFKC", preferred_name)
    base = "".join(char if f"_{char}".isidentifier() else "_" for char in normalized) or "_"
    valid = base if base[0].isidentifier() else f"_{base}"
    name = valid
    suffix = 0
    while is_taken(name):
        suffix += 1
        name = f"{valid}{suffix}"
    return name


@final
class Scope:
    """A declaration scope of one module (``Module.scope``)."""

    __slots__ = ("_nested", "_owner", "_parent", "_taken")

    def __init__(self, owner: object | None = None, parent: Scope | None = None) -> None:
        self._owner = object() if owner is None else owner
        self._parent = parent
        self._taken: set[str] = set()
        self._nested: set[str] = set()

    def nested(self) -> Scope:
        return Scope(self._owner, self)

    def in_module_of(self, other: Scope) -> bool:
        return self._owner is other._owner

    def reserve(self, name: str) -> None:
        self._taken.add(name)
        current = self._parent
        while current is not None:
            current._nested.add(name)
            current = current._parent

    def taken_by(self, name: str) -> str | None:
        """Why ``name`` cannot be declared here, or ``None`` when it can."""
        if name in self._nested:
            return "a nested scope declares it"
        current: Scope | None = self
        while current is not None:
            if name in current._taken:
                return (
                    "this scope declares it"
                    if current is self
                    else "an enclosing scope declares it"
                )
            current = current._parent
        return None

    def names(self) -> set[str]:
        return self._taken | self._nested
