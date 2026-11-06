"""Generated source (Effect's ``Code``, ``makeCode``, ``Artifact`` and
``CodeDocument``), and what ``to_code_document`` emits and ``to_code_module`` lays out."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Code:
    """The ``runtime`` expression building a schema and the ``type`` of
    its values."""

    runtime: str
    type: str


def make_code(runtime: str, type: str, /) -> Code:
    """``Code(runtime, type)`` (Effect's ``makeCode``)."""
    return Code(runtime, type)


@dataclass(frozen=True, slots=True)
class ImportArtifact:
    """A line the generated code needs at the top of its module."""

    declaration: str


@dataclass(frozen=True, slots=True)
class TypedDictArtifact:
    """The ``TypedDict`` a struct is made from: ``code.runtime`` defines
    ``identifier``."""

    identifier: str
    code: Code


@dataclass(frozen=True, slots=True)
class EnumArtifact:
    """The ``enum.Enum`` an ``S.Enum`` holds: ``code.runtime`` defines ``identifier``."""

    identifier: str
    code: Code


type Artifact = ImportArtifact | TypedDictArtifact | EnumArtifact


@dataclass(frozen=True, slots=True)
class NamedCode:
    """A definition: ``identifier = code.runtime``, ``type <identifier>Type = code.type``."""

    identifier: str
    code: Code


@dataclass(frozen=True, slots=True)
class CodeReferences:
    """The named schemas: ``non_recursives`` in dependency order, then
    ``recursives``, which refer to each other through ``S.suspend``."""

    non_recursives: tuple[NamedCode, ...]
    recursives: Mapping[str, Code]


@dataclass(frozen=True, slots=True)
class CodeDocument:
    """Generated code for a document's roots (``codes``), its ``references``
    and the ``artifacts`` they use."""

    codes: tuple[Code, *tuple[Code, ...]]
    references: CodeReferences
    artifacts: tuple[Artifact, ...]


@dataclass(frozen=True, slots=True)
class CheckCodeInput:
    """What a ``to_code`` annotation of a check gets: its schemas' code."""

    schemas: tuple[Code, ...]


@dataclass(frozen=True, slots=True)
class DeclarationCodeInput:
    """What a ``to_code`` annotation of a declaration gets: its type parameters' code."""

    type_parameters: tuple[Code, ...]


@dataclass(frozen=True, slots=True)
class GeneratedCheck:
    """A ``to_code`` annotation's answer for a check; ``imports`` are module lines."""

    runtime: str
    imports: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class GeneratedDeclaration:
    """A ``to_code`` annotation's answer for a declaration."""

    runtime: str
    type: str
    imports: tuple[str, ...] = ()
