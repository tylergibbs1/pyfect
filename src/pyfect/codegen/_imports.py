"""Import requests and their Python statements.

Effect's ES import kinds map to Python's: a namespace import is ``import a.b as X``
(``from .a import b as X`` for a relative module), a named import is
``from a.b import name as X``, a side-effect import is ``import a.b``, and a type-only
import goes under ``if TYPE_CHECKING:``. Python modules have no default export and no
import attributes, so ``importDefault`` and ``attributes`` have no counterpart."""

from __future__ import annotations

import keyword
from collections.abc import Sequence
from dataclasses import dataclass
from typing import final

from pyfect.codegen._fragment import Binding
from pyfect.codegen._names import is_identifier


def check_module(module: str, *, needs_name: bool) -> None:
    dots = len(module) - len(module.lstrip("."))
    rest = module[dots:]
    names = rest.split(".") if rest else []
    if (needs_name or dots == 0) and not names:
        raise ValueError(f"{module!r} is not a Python module path")
    for name in names:
        _check_name(name, module)


def _check_name(name: str, module: str) -> None:
    if not is_identifier(name) or keyword.iskeyword(name):
        raise ValueError(f"{name!r} in {module!r} is not a Python name")


@final
@dataclass(frozen=True)
class NamespaceImport:
    """``import module as local`` (Effect's ``Namespace`` import kind)."""

    module: str
    local: str
    type_only: bool = False

    def __post_init__(self) -> None:
        check_module(self.module, needs_name=True)


@final
@dataclass(frozen=True)
class NamedImport:
    """``from module import name as local`` (Effect's ``Named`` import kind)."""

    module: str
    name: str
    local: str
    type_only: bool = False

    def __post_init__(self) -> None:
        check_module(self.module, needs_name=False)
        _check_name(self.name, self.module)


type Import = NamespaceImport | NamedImport


@final
class ImportBinding(Binding):
    """The binding of an import request; its module allocates the local name."""

    __slots__ = ("request",)

    def __init__(self, request: Import) -> None:
        super().__init__(request.local)
        self.request = request


def import_key(request: Import) -> tuple[str, str, str]:
    """What makes two requests one import, whatever local name they ask for."""
    if isinstance(request, NamespaceImport):
        return ("namespace", request.module, "")
    return ("named", request.module, request.name)


def import_namespace(module: str, local: str, *, type_only: bool = False) -> Binding:
    """A namespace import (``import module as local``) any module can use."""
    return ImportBinding(NamespaceImport(module, local, type_only))


def import_named(module: str, name: str, *, type_only: bool = False) -> Binding:
    """A named import (``from module import name``) any module can use."""
    return ImportBinding(NamedImport(module, name, name, type_only))


def module_statement(module: str, local: str | None) -> tuple[str, str]:
    """The statement importing ``module`` (as ``local`` when given) and the name it binds."""
    dots = len(module) - len(module.lstrip("."))
    if dots == 0:
        if local is None or local == module:
            return f"import {module}", module.partition(".")[0]
        return f"import {module} as {local}", local
    package, _, last = module.rpartition(".")
    package = package if package.strip(".") else "." * dots
    alias = "" if local is None or local == last else f" as {local}"
    return f"from {package} import {last}{alias}", local or last


@dataclass
class UsedImport:
    """An import the rendered code reads, with its allocated name; ``runtime``
    once any use is not type-only."""

    request: Import
    local: str
    runtime: bool


def print_imports(
    entries: Sequence[UsedImport | str], *, annotations: bool = False
) -> tuple[str, ...]:
    """The import statements: side effects (``str``) and runtime imports in order,
    named imports of a module grouped at its first runtime use, then the type-only
    ones under ``if TYPE_CHECKING:``. ``annotations`` writes
    ``from __future__ import annotations`` first, as type-only imports do."""
    runtime: list[str] = []
    typed: list[str] = []
    groups: dict[str, list[tuple[NamedImport, UsedImport]]] = {}
    for entry in entries:
        if isinstance(entry, UsedImport) and isinstance(entry.request, NamedImport):
            groups.setdefault(entry.request.module, []).append((entry.request, entry))
    for entry in entries:
        if isinstance(entry, str):
            runtime.append(entry)
            continue
        request = entry.request
        if isinstance(request, NamespaceImport):
            (runtime if entry.runtime else typed).append(
                module_statement(request.module, entry.local)[0]
            )
            continue
        group = groups.get(request.module)
        if group is None or (not entry.runtime and any(used.runtime for _, used in group)):
            continue
        del groups[request.module]
        for target, is_runtime in ((runtime, True), (typed, False)):
            names = [
                named.name if named.name == used.local else f"{named.name} as {used.local}"
                for named, used in group
                if used.runtime is is_runtime
            ]
            if names:
                target.append(f"from {request.module} import {', '.join(names)}")
    if not typed:
        return ("from __future__ import annotations", *runtime) if annotations else tuple(runtime)
    block = "\n".join(f"    {line}" for line in typed)
    return (
        "from __future__ import annotations",
        *runtime,
        "from typing import TYPE_CHECKING",
        f"if TYPE_CHECKING:\n{block}",
    )
