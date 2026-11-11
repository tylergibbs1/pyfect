"""Self-installing modules of ahead-of-time compiled decoders (Effect's
``SchemaAOTCompiler/Build``).

``build(modules=..., out_file=...)`` loads each module, compiles its
exported schemas and writes a module that imports them and installs their
decoders when it is imported. Keys of ``modules`` are the dotted names the
generated module imports; their loaders run during the build, in sorted
order, and must return that module (or its namespace mapping). A module's
exports are its ``__all__``, else its public names; only schemas count.
Decoding is prepared by default; ``"is"`` and ``"make"`` prepare the type
side, ``"encode"`` the flipped AST. Regenerate after a schema or pyfect
changes.
"""

from __future__ import annotations

import types
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from pyfect._core import Effect
from pyfect._json_text import stringify
from pyfect.effect import fail, gen, succeed, sync
from pyfect.errors import TaggedError
from pyfect.file_system import FileSystem
from pyfect.path import Path
from pyfect.platform_error import PlatformError
from pyfect.schema._schema import Top, is_schema
from pyfect.schema.aot_compiler import Operation as CompiledOperation
from pyfect.schema.aot_compiler import Target
from pyfect.schema.aot_compiler import compile as compile_targets
from pyfect.schema.ast import AST

type Operation = Literal["decode", "encode", "is", "make"]
"""An operation whose root AST ``build`` prepares."""

type ModuleLoader = Callable[[], object]
"""Loads a module's namespace during a build."""

type BuildErrorKind = Literal["Generate", "InvalidModule", "LoadModule", "ResolveModule"]

_ORDER: tuple[Operation, ...] = ("decode", "encode", "is", "make")


@dataclass(frozen=True, slots=True)
class BuildResult:
    """``out_file`` (absolute), the number of loaded modules with a schema
    export, and the number of schemas exported by them."""

    out_file: str
    modules: int
    schemas: int


@dataclass(eq=False)
class BuildError(TaggedError):
    """Loading a module or generating the module failed."""

    cause: object
    kind: BuildErrorKind
    message: str
    module: str | None = None


@dataclass(frozen=True, slots=True)
class _Exported:
    alias: str
    name: str
    schema: Top


def _exports(namespace: Mapping[str, object]) -> list[str]:
    names = namespace.get("__all__")
    if isinstance(names, (list, tuple)):
        candidates = [n for n in names if isinstance(n, str)]  # pyright: ignore[reportUnknownVariableType]
    else:
        candidates = [n for n in namespace if not n.startswith("_")]
    return sorted(n for n in candidates if n in namespace and is_schema(namespace[n]))


def _root(exported: _Exported, operation: Operation) -> tuple[AST, CompiledOperation, str]:
    ast = exported.schema.__codec__().ast
    expression = f"{exported.alias}.{exported.name}.__codec__().ast"
    match operation:
        case "decode":
            return ast, "decode", expression
        case "encode":
            flipped = ast.flip()
            return (
                (ast, "decode", expression)
                if flipped is ast
                else (
                    flipped,
                    "decode",
                    f"{expression}.flip()",
                )
            )
        case "is" | "make":
            typed = ast.to_type()
            return (
                (ast, operation, expression)
                if typed is ast
                else (
                    typed,
                    operation,
                    f"{expression}.to_type()",
                )
            )


def _source(imports: list[str], exported: list[_Exported], operations: list[Operation]) -> str:
    targets: list[tuple[AST, list[CompiledOperation], str]] = []
    seen: dict[int, int] = {}
    for item in exported:
        for operation in operations:
            ast, target_operation, expression = _root(item, operation)
            index = seen.get(id(ast))
            if index is not None:
                if target_operation not in targets[index][1]:
                    targets[index][1].append(target_operation)
                continue
            seen[id(ast)] = len(targets)
            targets.append((ast, [target_operation], expression))
    module = compile_targets([Target(ast, ops) for ast, ops, _ in targets])
    roots = ", ".join(expression for _, _, expression in targets)
    return "\n".join([*imports, module, f"install([{roots}])", ""])


def _valid_name(specifier: str) -> bool:
    return bool(specifier) and all(part.isidentifier() for part in specifier.split("."))


def build(
    *,
    modules: Mapping[str, ModuleLoader],
    out_file: str,
    operations: Sequence[Operation] | None = None,
) -> Effect[BuildResult, BuildError | PlatformError, FileSystem | Path]:
    """Write a self-installing module for the schemas ``modules`` export
    (see the module)."""

    def run() -> Any:
        fs = yield from FileSystem()
        path = yield from Path()
        out = path.resolve(out_file)
        requested: set[Operation] = set(operations or ("decode",))
        chosen: list[Operation] = [operation for operation in _ORDER if operation in requested]
        imports: list[str] = []
        exported: list[_Exported] = []
        for specifier in sorted(modules):
            loaded = yield from _load(specifier, modules[specifier])
            if isinstance(loaded, types.ModuleType):
                namespace: Mapping[str, object] = vars(loaded)
            elif isinstance(loaded, Mapping):
                namespace = loaded  # pyright: ignore[reportUnknownVariableType]
            else:
                return (
                    yield from fail(
                        BuildError(
                            loaded,
                            "InvalidModule",
                            f"Schema module {stringify(specifier)} did not load a module namespace",
                            specifier,
                        )
                    )
                )
            names = _exports(namespace)
            if not names:
                continue
            if not _valid_name(specifier):
                return (
                    yield from fail(
                        BuildError(
                            None,
                            "ResolveModule",
                            f"Could not resolve schema module {stringify(specifier)}",
                            specifier,
                        )
                    )
                )
            alias = f"m{len(imports)}"
            imports.append(f"import {specifier} as {alias}")
            exported += [_Exported(alias, n, namespace[n]) for n in names]  # pyright: ignore[reportArgumentType]
        source = yield from _generate(imports, exported, chosen)
        yield from fs.make_directory(path.dirname(out), recursive=True)
        yield from fs.write_file_string(out, source)
        return BuildResult(out, len(imports), len(exported))

    return gen(run)


def _load(specifier: str, loader: ModuleLoader) -> Effect[object, BuildError]:
    def load() -> Effect[object, BuildError]:
        try:
            return succeed(loader())
        except Exception as cause:
            return fail(
                BuildError(
                    cause,
                    "LoadModule",
                    f"Could not load schema module {stringify(specifier)}",
                    specifier,
                )
            )

    return sync(load).flat_map(lambda effect: effect)


def _generate(
    imports: list[str], exported: list[_Exported], operations: list[Operation]
) -> Effect[str, BuildError]:
    def generate() -> Effect[str, BuildError]:
        try:
            return succeed(_source(imports, exported, operations))
        except Exception as cause:
            return fail(BuildError(cause, "Generate", "Could not generate the Schema AOT module"))

    return sync(generate).flat_map(lambda effect: effect)


__all__ = ["BuildError", "BuildResult", "ModuleLoader", "Operation", "PlatformError", "build"]
