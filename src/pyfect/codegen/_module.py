"""``Module``: Effect's ``Codegen.Module`` builder, printing Python."""

from __future__ import annotations

import warnings
from collections.abc import Iterable, Mapping, MutableMapping, Sequence
from dataclasses import dataclass
from typing import Never, Self, final, overload
from warnings import deprecated

from pyfect.codegen._fragment import (
    Binding,
    DeclarationBinding,
    Deferred,
    Fragment,
    Parts,
    Render,
    literal,
)
from pyfect.codegen._imports import (
    Import,
    ImportBinding,
    UsedImport,
    check_module,
    import_key,
    module_statement,
    print_imports,
)
from pyfect.codegen._names import RESERVED, Scope, allocate, is_identifier
from pyfect.codegen._schema_source import Batch
from pyfect.codegen._schemas import ModuleNames, Schemas
from pyfect.schema.representation._model import References, Representation

_BINDINGS_DEPRECATED = (
    "add_schemas(bindings=...) is deprecated and removed in 0.8.0: use the mapping "
    "add_schemas returns"
)


@final
@dataclass(frozen=True)
class FinalizedDeclaration:
    """A declaration's rendered fragments."""

    binding: DeclarationBinding
    fragments: tuple[str, ...]


@final
@dataclass(frozen=True)
class Finalized:
    """A snapshot of a module (``Module.finalize``): the name of every binding it
    rendered, its declarations in dependency order, the roots asked for, its import
    statements and the fragments ``add`` appended."""

    names: Mapping[Binding, str]
    declarations: tuple[FinalizedDeclaration, ...]
    roots: tuple[str, ...]
    imports: tuple[str, ...]
    body: tuple[str, ...]


@dataclass(frozen=True)
class _Declaration:
    binding: DeclarationBinding
    fragments: tuple[Fragment, ...]
    dependencies: tuple[Binding, ...]
    annotated: bool = False


class Module:
    """A Python module being built (Effect's ``Codegen.Module``).

    ``add_schemas`` adds schemas, ``declare`` allocates a name, ``define`` gives it
    source, ``add`` appends source, and imports are written for the bindings the source
    uses. ``print`` and ``finalize`` take a snapshot; the module stays open.
    ``reserved`` names are left to the surrounding code, as are keywords and builtins."""

    def __init__(self, reserved: Iterable[str] = ()) -> None:
        self._given_reserved = frozenset(reserved)
        self._reserved = RESERVED | self._given_reserved
        self._root = Scope()
        self._names: dict[DeclarationBinding, str] = {}
        self._declarations: dict[DeclarationBinding, _Declaration] = {}
        self._order: list[DeclarationBinding | Batch] = []
        self._imports: dict[tuple[tuple[str, str, str], str, bool], ImportBinding] = {}
        self._provided: dict[tuple[str, str, str], ImportBinding] = {}
        self._side_effects: set[str] = set()
        self._import_order: list[ImportBinding | str | Batch] = []
        self._body: list[Fragment] = []
        self._building = False
        self._schemas = Schemas(
            ModuleNames(self._schema_taken, self._declare_schema, self._side_effect, self._import)
        )

    @overload
    def add_schemas(
        self,
        schemas: Mapping[str, Representation],
        /,
        *,
        references: References | None = None,
        type_only: bool = False,
    ) -> Mapping[str, DeclarationBinding]: ...
    @overload
    @deprecated(_BINDINGS_DEPRECATED)
    def add_schemas(
        self,
        schemas: Mapping[str, Representation],
        /,
        *,
        references: References | None = None,
        type_only: bool = False,
        bindings: MutableMapping[str, DeclarationBinding],
    ) -> Mapping[str, DeclarationBinding]: ...
    def add_schemas(
        self,
        schemas: Mapping[str, Representation],
        /,
        *,
        references: References | None = None,
        type_only: bool = False,
        bindings: MutableMapping[str, DeclarationBinding] | None = None,
    ) -> Mapping[str, DeclarationBinding]:
        """Declares each schema under its name (with a numeric suffix when that is
        taken), with the definitions it refers to: ``X`` holds the schema and
        ``XType`` its type. ``type_only`` writes only the types. Returns each
        schema's binding by the name given (its type's with ``type_only``); a schema
        that is the reference of its own name is that reference. A name added before,
        or a reference defined differently before, raises ``ValueError``."""
        batch = self._schemas.add(schemas, references or {}, type_only=type_only)
        self._order.append(batch)
        self._import_order.append(batch)
        added = {
            root.name: root.names.alias if type_only else root.names.value for root in batch.roots
        }
        if bindings is not None:
            warnings.warn(_BINDINGS_DEPRECATED, DeprecationWarning, stacklevel=2)
            bindings.update(added)
        return added

    def scope(self, parent: Scope | None = None) -> Scope:
        """A declaration scope nested in ``parent`` (the module's own by default)."""
        return self._own(parent).nested()

    def declare(
        self, preferred_name: str, *, exact: bool = False, scope: Scope | None = None
    ) -> DeclarationBinding:
        """A new binding named ``preferred_name`` made an identifier, with a numeric
        suffix when the name is reserved or declared in this scope, an enclosing or a
        nested one. With ``exact`` the name is kept, and one that would change raises
        ``ValueError``."""
        self._build()
        own = self._own(scope)

        def taken_by(name: str) -> str | None:
            return "it is reserved" if name in self._reserved else own.taken_by(name)

        if exact:
            reason = (
                taken_by(preferred_name)
                if is_identifier(preferred_name)
                else "it is not an identifier"
            )
            if reason is not None:
                raise ValueError(f"Cannot declare exact name {literal(preferred_name)}: {reason}")
            name = preferred_name
        else:
            name = allocate(preferred_name, lambda name: taken_by(name) is not None)
        binding = DeclarationBinding(preferred_name, name)
        own.reserve(name)
        self._names[binding] = name
        return binding

    def define(
        self,
        binding: DeclarationBinding,
        fragments: Sequence[Fragment],
        dependencies: Sequence[Binding] = (),
    ) -> Self:
        """Gives ``binding`` its source. ``dependencies`` are the bindings it reads
        when it runs: ``print`` writes their declarations first."""
        if binding not in self._names:
            raise ValueError("Expected a declaration binding owned by this module")
        if binding in self._declarations or self._schemas.owns(binding):
            raise ValueError(f"Duplicate definition: {binding.preferred_name}")
        self._declarations[binding] = _Declaration(binding, tuple(fragments), tuple(dependencies))
        self._order.append(binding)
        return self

    def add_import(self, request: Import) -> Binding:
        """The binding of ``request``; the same request gives the same binding."""
        self._build()
        key = (import_key(request), request.local, request.type_only)
        known = key in self._imports
        binding = self._import(request)
        if not known:
            self._import_order.append(binding)
        return binding

    def provide_import(self, request: Import) -> Binding:
        """The binding of an import the surrounding code already makes, under
        ``request.local`` exactly; the module writes no statement for it. A local
        name already taken raises ``ValueError``."""
        self._build()
        key = import_key(request)
        existing = self._provided.get(key)
        if existing is not None and existing.request.local == request.local:
            return existing
        local = request.local
        if existing is not None or local in self._reserved or local in self._root.names():
            raise ValueError(f"Conflicting predefined import: {local}")
        binding = ImportBinding(request)
        self._root.reserve(local)
        self._provided[key] = binding
        return binding

    def add_side_effect(self, module: str) -> Self:
        """Imports ``module`` for its side effects (``import module``), once, in the
        order of its first call. The name the statement binds is left to it."""
        self._build()
        check_module(module, needs_name=True)
        statement, bound = module_statement(module, None)
        if self._side_effect(statement, bound):
            self._import_order.append(statement)
        return self

    def add(self, fragment: Fragment) -> Self:
        """Appends ``fragment`` after the declarations."""
        self._build()
        self._body.append(fragment)
        return self

    def finalize(self, roots: Sequence[Fragment] = ()) -> Finalized:
        """Renders a snapshot: declarations after their dependencies, then ``roots``
        in order. A missing definition or a cycle of dependencies raises
        ``ValueError``. Later declarations can change import names, so render the
        whole module again after a change."""
        ordered = self._ordered()
        names: dict[Binding, str] = {**self._names}
        imports: dict[tuple[str, str, str], UsedImport] = {}
        render = self._renderer(names, imports)
        declarations = tuple(
            FinalizedDeclaration(d.binding, tuple(map(render, d.fragments))) for d in ordered
        )
        rendered_roots = tuple(map(render, roots))
        body = tuple(map(render, self._body))
        entries: list[UsedImport | str] = []
        for entry in self._expanded_imports():
            if isinstance(entry, str):
                entries.append(entry)
                continue
            key = import_key(entry.request)
            used = imports.get(key)
            if used is not None and (not used.runtime or not entry.request.type_only):
                entries.append(used)
                del imports[key]
        entries.extend(imports.values())
        annotations = any(d.annotated for d in ordered)
        statements = print_imports(entries, annotations=annotations)
        return Finalized(names, declarations, rendered_roots, statements, body)

    def print(self) -> str:
        """The module's source: imports, declarations in dependency order, then what
        ``add`` appended. Run it, or check it with pyright."""
        if not self._building and not self._schemas.declared():
            _empty()
        output = self.finalize()
        parts = [
            "\n".join(output.imports),
            *(fragment for d in output.declarations for fragment in d.fragments),
            *output.body,
        ]
        return "\n\n".join(part for part in parts if part != "") + "\n"

    def _build(self) -> None:
        self._building = True

    def _schema_taken(self, name: str) -> bool:
        """Whether a schema cannot declare ``name``. Schemas may shadow builtins,
        as `to_code_module`'s always could."""
        return name in self._given_reserved or self._root.taken_by(name) is not None

    def _declare_schema(self, name: str) -> DeclarationBinding:
        binding = DeclarationBinding(name, name)
        self._root.reserve(name)
        self._names[binding] = name
        return binding

    def _side_effect(self, statement: str, bound: str) -> bool:
        if statement in self._side_effects:
            return False
        self._side_effects.add(statement)
        self._root.reserve(bound)
        return True

    def _import(self, request: Import) -> ImportBinding:
        """The binding ``add_import`` gives ``request``, without placing it."""
        key = (import_key(request), request.local, request.type_only)
        existing = self._imports.get(key)
        if existing is None:
            existing = self._imports[key] = ImportBinding(request)
        return existing

    def _expanded_imports(self) -> list[ImportBinding | str]:
        entries: list[ImportBinding | str] = []
        for entry in self._import_order:
            if isinstance(entry, Batch):
                entries.extend(self._schemas.imports(entry))
            else:
                entries.append(entry)
        return entries

    def _own(self, scope: Scope | None) -> Scope:
        if scope is None:
            return self._root
        if not scope.in_module_of(self._root):
            raise ValueError("Scope belongs to another module")
        return scope

    def _ordered(self) -> list[_Declaration]:
        declarations: dict[DeclarationBinding, _Declaration] = dict(self._declarations)
        schemas = self._schemas.declarations()
        sequence: list[DeclarationBinding] = []
        for entry in self._order:
            if not isinstance(entry, Batch):
                sequence.append(entry)
                continue
            for d in schemas[entry]:
                declarations[d.binding] = _Declaration(
                    d.binding, d.fragments, d.dependencies, d.annotated
                )
                sequence.append(d.binding)
        ordering = _Ordering(declarations)
        for binding in sequence:
            ordering.visit(binding)
        return ordering.ordered

    def _renderer(
        self, names: dict[Binding, str], imports: dict[tuple[str, str, str], UsedImport]
    ) -> Render:
        taken = set(self._reserved) | self._root.names()
        return _Renderer(names, imports, taken, self._provided).render


class _Ordering:
    """Declarations after the ones they read when they run (a depth-first walk)."""

    def __init__(self, declarations: Mapping[DeclarationBinding, _Declaration]) -> None:
        self._declarations = declarations
        self._visiting: set[Binding] = set()
        self._visited: set[Binding] = set()
        self.ordered: list[_Declaration] = []

    def visit(self, binding: Binding) -> None:
        if binding in self._visited or isinstance(binding, ImportBinding):
            return
        if binding in self._visiting:
            raise ValueError(f"Cyclic initialization dependency: {binding.preferred_name}")
        declaration = (
            self._declarations.get(binding) if isinstance(binding, DeclarationBinding) else None
        )
        if declaration is None:
            raise ValueError(f"Missing definition: {binding.preferred_name}")
        self._visiting.add(binding)
        for dependency in declaration.dependencies:
            self.visit(dependency)
        self._visiting.discard(binding)
        self._visited.add(binding)
        self.ordered.append(declaration)


class _Renderer:
    """Renders fragments with one ``finalize``'s names, each shared fragment once."""

    def __init__(
        self,
        names: dict[Binding, str],
        imports: dict[tuple[str, str, str], UsedImport],
        taken: set[str],
        provided: Mapping[tuple[str, str, str], ImportBinding],
    ) -> None:
        self._names = names
        self._imports = imports
        self._taken = taken
        self._provided = provided
        self._cache: dict[Binding | Parts | Deferred, str] = {}

    def render(self, fragment: Fragment) -> str:
        if isinstance(fragment, str):
            return fragment
        previous = self._cache.get(fragment)
        if previous is not None:
            return previous
        if isinstance(fragment, Parts):
            value = "".join(map(self.render, fragment.parts))
        elif isinstance(fragment, Deferred):
            value = fragment.render(self.render)
        elif isinstance(fragment, ImportBinding):
            value = self._import_name(fragment)
            self._names[fragment] = value
        else:
            found = self._names.get(fragment)
            if found is None:
                raise ValueError("Binding belongs to another module")
            value = found
        self._cache[fragment] = value
        return value

    def _import_name(self, binding: ImportBinding) -> str:
        request = binding.request
        key = import_key(request)
        provided = self._provided.get(key)
        if provided is not None:
            return provided.request.local
        used = self._imports.get(key)
        if used is None:
            local = allocate(request.local, self._taken.__contains__)
            self._taken.add(local)
            used = UsedImport(request, local, runtime=False)
            self._imports[key] = used
        used.runtime = used.runtime or not request.type_only
        return used.local


def _empty() -> Never:
    raise ValueError(
        "A module needs at least one schema or declaration: call add_schemas, define or add first"
    )
