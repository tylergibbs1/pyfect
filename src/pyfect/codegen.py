"""Python source from schema representations (Effect's ``Codegen``).

``Module`` collects named schemas and prints them as one module:
imports, type aliases, artifacts, the shared references in order, then a
variable for each schema. It replaces ``representation.to_code_document``
followed by ``to_code_module``."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Never, Self

from pyfect.schema.representation._code_document import code_document, to_code_module
from pyfect.schema.representation._model import MultiDocument, References, Representation

__all__ = ["Module"]


class Module:
    """A module of generated schemas (Effect's ``Codegen.Module``)."""

    def __init__(self) -> None:
        self._schemas: dict[str, Representation] = {}
        self._references: dict[str, Representation] = {}

    def add_schemas(
        self, schemas: Mapping[str, Representation], /, *, references: References | None = None
    ) -> Self:
        """Adds each schema as a variable of its name, with the definitions
        it refers to. A name added before, or a reference defined
        differently before, raises ``ValueError``."""
        for name in schemas:
            if name in self._schemas:
                raise ValueError(f"A schema named {name!r} was already added")
        given = references or {}
        for ref, representation in given.items():
            if self._references.get(ref, representation) != representation:
                raise ValueError(f"The reference {ref!r} was already defined differently")
        self._schemas.update(schemas)
        self._references.update(given)
        return self

    def print(self) -> str:
        """The module's source. Run it, or check it with pyright."""
        first, *rest = self._schemas.values() or _no_schemas()
        document = MultiDocument((first, *rest), dict(self._references))
        return to_code_module(code_document(document), names=tuple(self._schemas))


def _no_schemas() -> Never:
    raise ValueError("A module needs at least one schema: call add_schemas first")
