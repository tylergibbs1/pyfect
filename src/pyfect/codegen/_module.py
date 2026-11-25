"""``Module``: Effect's ``Codegen.Module`` builder, printing Python."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Never, Self, final

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
from pyfect.schema.representation._code_document import code_document, to_code_module
from pyfect.schema.representation._model import MultiDocument, References, Representation

_BOTH = (
    "A module holds schemas (add_schemas) or declarations (declare, define, add and imports), "
    "not both"
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


class Module:
    """A Python module being built (Effect's ``Codegen.Module``).

    Either add schemas (``add_schemas``) or build it from declarations: ``declare``
    allocates a name, ``define`` gives it source, ``add`` appends source, and imports
    are written for the bindings the source uses. ``print`` and ``finalize`` take a
    snapshot; the module stays open. ``reserved`` names are left to the surrounding
    code, as are keywords and builtins."""

    def __init__(self, reserved: Iterable[str] = ()) -> None:
        self._schemas: dict[str, Representation] = {}
        self._references: dict[str, Representation] = {}
        self._reserved = RESERVED | frozenset(reserved)
        self._root = Scope()
        self._names: dict[DeclarationBinding, str] = {}
        self._declarations: dict[DeclarationBinding, _Declaration] = {}
        self._imports: dict[tuple[tuple[str, str, str], str, bool], ImportBinding] = {}
        self._provided: dict[tuple[str, str, str], ImportBinding] = {}
        self._side_effects: set[str] = set()
        self._import_order: list[ImportBinding | str] = []
        self._body: list[Fragment] = []
        self._building = False

    def add_schemas(
        self, schemas: Mapping[str, Representation], /, *, references: References | None = None
    ) -> Self:
        """Adds each schema as a variable of its name, with the definitions
        it refers to. A name added before, or a reference defined
        differently before, raises ``ValueError``, as does a module built
        from declarations."""
        if self._building:
            raise ValueError(_BOTH)
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
        if binding in self._declarations:
            raise ValueError(f"Duplicate definition: {binding.preferred_name}")
        self._declarations[binding] = _Declaration(binding, tuple(fragments), tuple(dependencies))
        return self

    def add_import(self, request: Import) -> Binding:
        """The binding of ``request``; the same request gives the same binding."""
        self._build()
        key = (import_key(request), request.local, request.type_only)
        existing = self._imports.get(key)
        if existing is not None:
            return existing
        binding = ImportBinding(request)
        self._imports[key] = binding
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
        if statement not in self._side_effects:
            self._side_effects.add(statement)
            self._import_order.append(statement)
            self._root.reserve(bound)
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
        if self._schemas:
            raise ValueError(_BOTH)
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
        for entry in self._import_order:
            if isinstance(entry, str):
                entries.append(entry)
                continue
            key = import_key(entry.request)
            used = imports.get(key)
            if used is not None and (not used.runtime or not entry.request.type_only):
                entries.append(used)
                del imports[key]
        entries.extend(imports.values())
        return Finalized(names, declarations, rendered_roots, print_imports(entries), body)

    def print(self) -> str:
        """The module's source: imports, declarations in dependency order, then what
        ``add`` appended. Run it, or check it with pyright."""
        if self._schemas:
            first, *rest = self._schemas.values()
            document = MultiDocument((first, *rest), dict(self._references))
            return to_code_module(code_document(document), names=tuple(self._schemas))
        if not self._building:
            _empty()
        output = self.finalize()
        parts = [
            "\n".join(output.imports),
            *(fragment for d in output.declarations for fragment in d.fragments),
            *output.body,
        ]
        return "\n\n".join(part for part in parts if part != "") + "\n"

    def _build(self) -> None:
        if self._schemas:
            raise ValueError(_BOTH)
        self._building = True

    def _own(self, scope: Scope | None) -> Scope:
        if scope is None:
            return self._root
        if not scope.in_module_of(self._root):
            raise ValueError("Scope belongs to another module")
        return scope

    def _ordered(self) -> list[_Declaration]:
        visiting: set[Binding] = set()
        visited: set[Binding] = set()
        ordered: list[_Declaration] = []

        def visit(binding: Binding) -> None:
            if binding in visited or isinstance(binding, ImportBinding):
                return
            if binding in visiting:
                raise ValueError(f"Cyclic initialization dependency: {binding.preferred_name}")
            declaration = (
                self._declarations.get(binding) if isinstance(binding, DeclarationBinding) else None
            )
            if declaration is None:
                raise ValueError(f"Missing definition: {binding.preferred_name}")
            visiting.add(binding)
            for dependency in declaration.dependencies:
                visit(dependency)
            visiting.discard(binding)
            visited.add(binding)
            ordered.append(declaration)

        for binding in self._declarations:
            visit(binding)
        return ordered

    def _renderer(
        self, names: dict[Binding, str], imports: dict[tuple[str, str, str], UsedImport]
    ) -> Render:
        taken = set(self._reserved) | self._root.names()
        cache: dict[Binding | Parts | Deferred, str] = {}

        def render(fragment: Fragment) -> str:
            if isinstance(fragment, str):
                return fragment
            previous = cache.get(fragment)
            if previous is not None:
                return previous
            if isinstance(fragment, Parts):
                value = "".join(map(render, fragment.parts))
            elif isinstance(fragment, Deferred):
                value = fragment.render(render)
            elif isinstance(fragment, ImportBinding):
                value = self._import_name(fragment, imports, taken)
                names[fragment] = value
            else:
                found = names.get(fragment)
                if found is None:
                    raise ValueError("Binding belongs to another module")
                value = found
            cache[fragment] = value
            return value

        return render

    def _import_name(
        self,
        binding: ImportBinding,
        imports: dict[tuple[str, str, str], UsedImport],
        taken: set[str],
    ) -> str:
        request = binding.request
        key = import_key(request)
        provided = self._provided.get(key)
        if provided is not None:
            return provided.request.local
        used = imports.get(key)
        if used is None:
            local = allocate(request.local, taken.__contains__)
            taken.add(local)
            used = UsedImport(request, local, runtime=False)
            imports[key] = used
        used.runtime = used.runtime or not request.type_only
        return used.local


def _empty() -> Never:
    raise ValueError(
        "A module needs at least one schema or declaration: call add_schemas, define or add first"
    )
