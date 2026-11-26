"""The schemas of a module (Effect's ``addSchemas``).

A schema ``X`` declares two names: ``X`` for its value and ``XType`` for its type alias
(Python has one namespace where TypeScript has two). The names are allocated when the
schemas are added; the source is generated the first time the module renders them, so a
representation that cannot be printed raises there, as ``print`` always did. A module of
schemas alone prints as one ``to_code_module``, 0.6's layout."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

from pyfect.codegen._fragment import Binding, DeclarationBinding
from pyfect.codegen._imports import Import, ImportBinding, NamedImport
from pyfect.codegen._names import allocate
from pyfect.codegen._schema_source import (
    Batch,
    Generated,
    Root,
    SchemaDeclaration,
    SchemaNames,
    declarations,
    import_requests,
    runtime_references,
)
from pyfect.schema.representation._code import EnumArtifact, TypedDictArtifact
from pyfect.schema.representation._code_document import (
    code_document,
    code_schemas,
    fits_module,
    is_reserved_name,
    reference_names_taken,
    reference_order,
    sanitize_identifier,
    to_code_module,
)
from pyfect.schema.representation._model import (
    MultiDocument,
    Reference,
    References,
    Representation,
)

_SCHEMA_IMPORT = NamedImport("pyfect", "schema", "S")


@dataclass(frozen=True)
class ModuleNames:
    """What the schemas use of their module: whether a schema may not declare a name,
    declaring one exactly, adding a side-effect statement binding a name (``False``
    when the module has it), and the binding of an import, which the schemas place."""

    taken: Callable[[str], bool]
    declare: Callable[[str], DeclarationBinding]
    side_effect: Callable[[str, str], bool]
    import_binding: Callable[[Import], ImportBinding]


class Schemas:
    """The schemas added to one module, batch by batch."""

    def __init__(self, module: ModuleNames) -> None:
        self._module = module
        self._schemas: dict[str, Representation] = {}
        self._references: dict[str, Representation] = {}
        self._reference_names: dict[str, SchemaNames] = {}
        self._names: dict[str, DeclarationBinding] = {}
        self._batches: list[Batch] = []

    def add(
        self, schemas: Mapping[str, Representation], references: References, *, type_only: bool
    ) -> Batch:
        """Names ``schemas`` and the references not named before. A name added before,
        or a reference defined differently before, raises ``ValueError``."""
        for name in schemas:
            if name in self._schemas:
                raise ValueError(f"A schema named {name!r} was already added")
        for ref, representation in references.items():
            if self._references.get(ref, representation) != representation:
                raise ValueError(f"The reference {ref!r} was already defined differently")
        self._schemas.update(schemas)
        self._references.update(references)
        introduced = self._name_references(reference_order(self._references))
        roots = tuple(self._root(name, schema) for name, schema in schemas.items())
        schema = self._module.import_binding(_SCHEMA_IMPORT)
        batch = Batch(
            roots, dict(self._references), tuple(references), introduced, type_only, schema
        )
        self._batches.append(batch)
        return batch

    def declared(self) -> bool:
        """Whether any schema or reference was added."""
        return bool(self._names)

    def owns(self, binding: DeclarationBinding) -> bool:
        """Whether ``binding`` is a name the schemas declared, which they define."""
        return self._names.get(binding.name) is binding

    def module(self) -> str | None:
        """The schemas as one ``to_code_module``, or ``None`` when their names need
        the declarations' layout."""
        if not self._schemas:
            return None
        for batch in self._batches:
            for root in batch.roots:
                if batch.type_only or root.reuses or root.names.value.name != root.name:
                    return None
        first, *rest = self._schemas.values()
        document = code_document(MultiDocument((first, *rest), dict(self._references)))
        names = tuple(self._schemas)
        return to_code_module(document, names=names) if fits_module(names, document) else None

    def declarations(self) -> dict[Batch, list[SchemaDeclaration]]:
        """Each batch's declarations, in the order it defines them."""
        for batch in self._batches:
            self._generate(batch)
        runtime = runtime_references(self._batches, self._reference_names)
        return {
            batch: declarations(
                batch, self._generate(batch), self._reference_names, self._names, runtime
            )
            for batch in self._batches
        }

    def imports(self, batch: Batch) -> list[ImportBinding | str]:
        """The imports ``batch`` may write, in the order it asks for them."""
        return [batch.schema, *self._generate(batch).import_order]

    def _declare(self, name: str) -> DeclarationBinding:
        binding = self._module.declare(name)
        self._names[name] = binding
        return binding

    def _declare_schema(self, name: str) -> SchemaNames:
        return SchemaNames(self._declare(name), self._declare(f"{name}Type"))

    def _name_references(self, order: Sequence[str]) -> tuple[str, ...]:
        """Names the references not named before, as ``code_document`` would."""
        reserved = reference_names_taken(len(self._schemas))
        taken = self._module.taken

        def is_taken(name: str) -> bool:
            return any(
                n in reserved or is_reserved_name(n) or taken(n) for n in (name, f"{name}Type")
            )

        introduced = tuple(ref for ref in order if ref not in self._reference_names)
        for ref in introduced:
            name = allocate(sanitize_identifier(ref), is_taken)
            self._reference_names[ref] = self._declare_schema(name)
        return introduced

    def _root(self, name: str, schema: Representation) -> Root:
        if isinstance(schema, Reference) and schema.ref == name:
            names = self._reference_names.get(name)
            if names is not None:
                return Root(name, schema, names, reuses=True)
        taken = self._module.taken
        allocated = allocate(
            name, lambda name: is_reserved_name(name) or taken(name) or taken(f"{name}Type")
        )
        return Root(name, schema, self._declare_schema(allocated), reuses=False)

    def _generate(self, batch: Batch) -> Generated:
        if batch.generated is not None:
            return batch.generated
        identifiers = {ref: names.value.name for ref, names in self._reference_names.items()}
        codes = code_schemas(
            [root.representation for root in batch.roots],
            batch.references,
            identifiers=identifiers,
            compile=batch.introduced,
            is_taken=self._module.taken,
        )
        imports: dict[str, Binding] = {"S": batch.schema}
        order: list[ImportBinding | str] = []
        for request in import_requests(codes):
            if isinstance(request, tuple):
                statement, bound = request
                if self._module.side_effect(statement, bound):
                    order.append(statement)
                continue
            binding = self._module.import_binding(request)
            imports[request.local] = binding
            order.append(binding)
        artifacts = {
            artifact.identifier: self._declare(artifact.identifier)
            for artifact in codes.artifacts
            if isinstance(artifact, (TypedDictArtifact, EnumArtifact))
        }
        batch.generated = Generated(codes, imports, tuple(order), artifacts)
        return batch.generated
