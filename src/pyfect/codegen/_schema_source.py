"""The Python a module writes for its schemas: each schema's type alias, the artifacts
it names and its value, with the names its imports bind left to the module to allocate."""

from __future__ import annotations

import ast
import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field

from pyfect.codegen._fragment import Binding, DeclarationBinding, Fragment, code
from pyfect.codegen._imports import (
    Import,
    ImportBinding,
    NamedImport,
    NamespaceImport,
    module_statement,
)
from pyfect.schema.representation._code import (
    Code,
    EnumArtifact,
    ImportArtifact,
    TypedDictArtifact,
)
from pyfect.schema.representation._code_document import SchemaCodes
from pyfect.schema.representation._model import Representation

ANY_IMPORT = NamedImport("typing", "Any", "Any")


@dataclass(frozen=True)
class SchemaNames:
    """The bindings of one schema: its value and its type alias."""

    value: DeclarationBinding
    alias: DeclarationBinding


@dataclass(frozen=True)
class Root:
    """A schema added under ``name``; ``reuses`` when it is the reference of that name."""

    name: str
    representation: Representation
    names: SchemaNames
    reuses: bool


@dataclass(eq=False)
class Batch:
    """The schemas of one ``add_schemas`` call, and their source once generated."""

    roots: tuple[Root, ...]
    references: Mapping[str, Representation]
    given: tuple[str, ...]
    introduced: tuple[str, ...]
    type_only: bool
    schema: ImportBinding
    generated: Generated | None = None


@dataclass(frozen=True)
class Generated:
    """A batch's source, with the bindings of the names it imports."""

    codes: SchemaCodes
    imports: Mapping[str, Binding]
    import_order: tuple[ImportBinding | str, ...]
    artifacts: Mapping[str, DeclarationBinding]


@dataclass(frozen=True)
class SchemaDeclaration:
    """A declaration a batch defines: what ``Module.define`` would store, and
    whether it is annotated (pyright then wants ``from __future__ import annotations``)."""

    binding: DeclarationBinding
    fragments: tuple[Fragment, ...]
    dependencies: tuple[Binding, ...]
    annotated: bool = False


@dataclass
class _Layout:
    """Each schema's alias, the artifacts it names, then its value."""

    names: Mapping[str, DeclarationBinding]
    generated: Generated
    declarations: list[SchemaDeclaration] = field(default_factory=list[SchemaDeclaration])
    placed: set[str] = field(default_factory=set[str])

    def schema(self, names: SchemaNames, source: Code, *, recursive: bool, value: bool) -> None:
        imports = self.generated.imports
        alias = names.alias
        self.declarations.append(
            SchemaDeclaration(alias, (code("type ", alias, " = ", bind(source.type, imports)),), ())
        )
        mentioned = all_names(source.type) | (all_names(source.runtime) if value else set[str]())
        for name, binding in self.generated.artifacts.items():
            if name in mentioned:
                self.artifact(name, binding)
        if not value:
            return
        runtime = bind(source.runtime, imports)
        dependencies = self.dependencies(eager_names(source.runtime))
        if recursive:
            schema, any_ = imports["S"], imports["Any"]
            annotation = code(schema, ".Bottom[", alias, ", ", [any_, ", "] * 2, any_, "]")
            fragment = code(names.value, ": ", annotation, " = ", runtime)
            dependencies = (alias, *dependencies)
        else:
            fragment = code(names.value, " = ", runtime)
        self.declarations.append(
            SchemaDeclaration(names.value, (fragment,), dependencies, annotated=recursive)
        )

    def artifact(self, name: str, binding: DeclarationBinding) -> None:
        if name in self.placed:
            return
        self.placed.add(name)
        artifact = next(
            a
            for a in self.generated.codes.artifacts
            if isinstance(a, (TypedDictArtifact, EnumArtifact)) and a.identifier == name
        )
        source = artifact.code.runtime
        names = eager_names(source, statement=True) - {name}
        self.declarations.append(
            SchemaDeclaration(
                binding,
                (bind(source, self.generated.imports, statement=True),),
                self.dependencies(names),
            )
        )

    def dependencies(self, names: Iterable[str]) -> tuple[Binding, ...]:
        return tuple(self.names[name] for name in sorted(names) if name in self.names)


def declarations(
    batch: Batch,
    generated: Generated,
    references: Mapping[str, SchemaNames],
    names: Mapping[str, DeclarationBinding],
    runtime_references: set[str],
) -> list[SchemaDeclaration]:
    """``batch``'s declarations in the order it defines them."""
    layout = _Layout(names, generated)
    codes = generated.codes
    by_identifier = {references[ref].value.name: ref for ref in batch.introduced}
    for named in codes.references.non_recursives:
        ref = by_identifier[named.identifier]
        layout.schema(references[ref], named.code, recursive=False, value=ref in runtime_references)
    for identifier, source in codes.references.recursives.items():
        ref = by_identifier[identifier]
        layout.schema(references[ref], source, recursive=True, value=ref in runtime_references)
    for root, source in zip(batch.roots, codes.roots, strict=True):
        if not root.reuses:
            layout.schema(root.names, source, recursive=False, value=not batch.type_only)
    for name, binding in generated.artifacts.items():
        layout.artifact(name, binding)
    return layout.declarations


def runtime_references(batches: Iterable[Batch], references: Mapping[str, SchemaNames]) -> set[str]:
    """The references whose values some schema with a value reads."""
    by_identifier = {names.value.name: ref for ref, names in references.items()}
    sources: dict[str, str] = {}
    pending: list[str] = []
    for batch in batches:
        generated = batch.generated
        if generated is None:
            continue
        codes = generated.codes
        sources.update(
            (named.identifier, named.code.runtime) for named in codes.references.non_recursives
        )
        sources.update(
            (identifier, c.runtime) for identifier, c in codes.references.recursives.items()
        )
        if not batch.type_only:
            pending.extend(batch.given)
            for root, source in zip(batch.roots, codes.roots, strict=True):
                pending.extend(by_identifier.get(name, "") for name in all_names(source.runtime))
                if root.reuses:
                    pending.append(root.name)
    needed: set[str] = set()
    while pending:
        ref = pending.pop()
        if ref not in references or ref in needed:
            continue
        needed.add(ref)
        source = sources.get(references[ref].value.name)
        if source is not None:
            pending.extend(by_identifier.get(name, "") for name in all_names(source))
    return needed


type Request = Import | tuple[str, str]
"""An import request, or the statement of a dotted ``import a.b`` and the name it
binds, which cannot change."""


def import_requests(codes: SchemaCodes) -> list[Request]:
    """The imports ``codes`` asks for."""
    requests: list[Request] = []
    for artifact in codes.artifacts:
        if isinstance(artifact, ImportArtifact):
            requests.extend(_requests(artifact.declaration))
    if codes.references.recursives:
        requests.append(ANY_IMPORT)
    return requests


def _requests(line: str) -> list[Request]:
    try:
        [statement] = ast.parse(line).body
    except (SyntaxError, ValueError):
        raise ValueError(f"Cannot place the import {line!r} in a module") from None
    if isinstance(statement, ast.ImportFrom) and all(a.name != "*" for a in statement.names):
        module = "." * statement.level + (statement.module or "")
        return [NamedImport(module, a.name, a.asname or a.name) for a in statement.names]
    if isinstance(statement, ast.Import):
        requests: list[Request] = []
        for alias in statement.names:
            if alias.asname is not None:
                requests.append(NamespaceImport(alias.name, alias.asname))
            elif "." in alias.name:
                requests.append(module_statement(alias.name, None))
            else:
                requests.append(NamespaceImport(alias.name, alias.name))
        return requests
    raise ValueError(f"Cannot place the import {line!r} in a module")


_LINES = re.compile(r"[^\r\n]*(?:\r\n|\r|\n)|[^\r\n]+$")
"""Lines as Python's tokenizer counts them."""


def _utf8_width(char: str) -> int:
    point = ord(char)
    return 1 if point < 0x80 else 2 if point < 0x800 else 3 if point < 0x10000 else 4


def _index(lines: list[str], starts: list[int], line: int, offset: int) -> int:
    """The index in the source of ``ast``'s position: ``offset`` counts UTF-8 bytes."""
    text = lines[line - 1]
    column = 0
    while offset > 0:
        offset -= _utf8_width(text[column])
        column += 1
    return starts[line - 1] + column


def bind(source: str, imports: Mapping[str, Binding], *, statement: bool = False) -> Fragment:
    """``source`` with each name an import binds replaced by that import's binding,
    so the module can rename it."""
    tree = ast.parse(source, mode="exec" if statement else "eval")
    lines = _LINES.findall(source)
    starts = [0]
    for line in lines:
        starts.append(starts[-1] + len(line))
    spans = sorted(
        (
            _index(lines, starts, node.lineno, node.col_offset),
            _index(lines, starts, node.end_lineno or node.lineno, node.end_col_offset or 0),
            imports[node.id],
        )
        for node in ast.walk(tree)
        if isinstance(node, ast.Name) and node.id in imports
    )
    parts: list[Fragment] = []
    position = 0
    for start, end, binding in spans:
        parts.extend((source[position:start], binding))
        position = end
    parts.append(source[position:])
    return code(parts)


def _names(tree: ast.AST, skip: Callable[[ast.AST], bool]) -> set[str]:
    found: set[str] = set()
    stack = [tree]
    while stack:
        node = stack.pop()
        if skip(node):
            continue
        if isinstance(node, ast.Name):
            found.add(node.id)
        stack.extend(ast.iter_child_nodes(node))
    return found


def eager_names(source: str, *, statement: bool = False) -> set[str]:
    """The names ``source`` reads when it runs, which leaves out what a lambda reads."""
    tree = ast.parse(source, mode="exec" if statement else "eval")
    return _names(tree, lambda node: isinstance(node, ast.Lambda))


def all_names(source: str) -> set[str]:
    """Every name ``source`` reads, now or from a lambda."""
    return _names(ast.parse(source, mode="eval"), lambda _: False)
