"""Schema decoders written ahead of time as a Python module (Effect's
``SchemaAOTCompiler``).

``compile(targets)`` gives the source of a module exporting
``install(asts)``. Save it, import it, and call ``install`` with the
targets' ASTs in the same order before parsing: it installs the generated
operations in the registry ``pyfect.schema.compiler`` shares with the JIT
compiler, each initialized on first use. The module imports only
``pyfect.schema.compiler.runtime``: no code generation and no ``exec`` at
run time.

Only the requested operation families and their static dependencies are
emitted; repeated ASTs and shared dependencies are installed once, by
identity, and identical factories are written once. Unrequested or
unsupported operations keep the interpreter. Constants, functions and
checks are read from the ASTs given to ``install``, never serialized, so
regenerate the module whenever a schema or pyfect changes. Target the type
side (``ast.to_type()``) with ``"make"`` or ``"is"``, and the flipped AST
(``ast.flip()``) with ``"decode"`` to prepare encoding.
"""

from __future__ import annotations

import textwrap
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Final, Literal

from pyfect.schema.ast import AST, Arrays, Declaration, Objects, TemplateLiteral, Union
from pyfect.schema.compiler import _codegen as codegen
from pyfect.schema.compiler._registry import DecoderOperation

type Operation = Literal["decode", "is", "make"]
"""A parser operation prepared by ``compile``."""

type _Planned = Operation | Literal["decode_effect"]

_DECODER_ORDER: Final[tuple[DecoderOperation, ...]] = (
    "is",
    "decode",
    "make",
    "decode_effect",
    "make_effect",
)
_OPERATION_ORDER: Final[tuple[Operation, ...]] = ("decode", "is", "make")


@dataclass(frozen=True, slots=True)
class Target:
    """An exact AST and the operations to prepare for it."""

    ast: AST
    operations: Sequence[Operation]


@dataclass(slots=True)
class _Plan:
    name: str
    reference: str
    compilable: bool
    requested: set[_Planned] = field(default_factory=set[_Planned])
    sources: dict[DecoderOperation, str] = field(default_factory=dict[DecoderOperation, str])
    attempted: set[DecoderOperation] = field(default_factory=set[DecoderOperation])


def _dependencies(node: AST, name: str) -> list[tuple[AST, str]]:
    out: list[tuple[AST, str]] = []
    match node:
        case Declaration():
            out += [(c, f"{name}.type_parameters[{i}]") for i, c in enumerate(node.type_parameters)]
        case TemplateLiteral():
            out += [(c, f"{name}.parts[{i}]") for i, c in enumerate(node.parts)]
        case Arrays():
            out += [(e.type, f"{name}.elements[{i}].type") for i, e in enumerate(node.elements)]
            out += [(c, f"{name}.rest[{i}]") for i, c in enumerate(node.rest)]
        case Objects():
            out += [(p.type, f"{name}.properties[{i}].type") for i, p in enumerate(node.properties)]
            for i, index in enumerate(node.index_signatures):
                out.append((index.parameter, f"{name}.index_signatures[{i}].parameter"))
                out.append((index.type, f"{name}.index_signatures[{i}].type"))
        case Union():
            out += [(c, f"{name}.types[{i}]") for i, c in enumerate(node.types)]
        case _:
            pass
    for i, link in enumerate(node.encoding or ()):
        out.append((link.to, f"{name}.encoding[{i}].to"))
    return out


def compile(targets: Sequence[Target], /) -> str:
    """The source of a module exporting ``install(asts)`` for ``targets``
    (see the module). Generation installs nothing and runs no check or
    transformation; an empty list gives a module whose ``install`` does
    nothing."""
    seen: dict[int, tuple[AST, _Plan]] = {}

    def add_source(node: AST, plan: _Plan, operation: DecoderOperation) -> bool:
        if operation in plan.attempted:
            return operation in plan.sources
        plan.attempted.add(operation)
        if not plan.compilable:
            return False
        source = codegen.generate(node, operation)
        if source is None:
            return False
        plan.sources[operation] = source
        return True

    def visit(node: AST, reference: str, operation: _Planned) -> None:
        found = seen.get(id(node))
        if found is None:
            plan = _Plan(f"a{len(seen)}", reference, codegen.should_compile_parser(node))
            seen[id(node)] = (node, plan)
        else:
            plan = found[1]
        if operation in plan.requested:
            return
        plan.requested.add(operation)
        match operation:
            case "decode":
                add_source(node, plan, "decode")
                visit(node, reference, "decode_effect")
            case "decode_effect":
                add_source(node, plan, "decode_effect")
                for child, path in _dependencies(node, plan.name):
                    visit(child, path, operation)
            case "is":
                if not add_source(node, plan, "is"):
                    visit(node, reference, "decode")
            case "make":
                add_source(node, plan, "make")
                add_source(node, plan, "make_effect")
                for child, path in _dependencies(node, plan.name):
                    visit(child, path, operation)

    for index, target in enumerate(targets):
        for operation in _OPERATION_ORDER:
            if operation in target.operations:
                visit(target.ast, f"asts[{index}]", operation)
    return _module([plan for _, plan in seen.values()])


def _module(plans: list[_Plan]) -> str:
    factories: list[str] = []
    factory_names: dict[str, str] = {}
    bindings: list[str] = []
    installations: list[str] = []
    for plan in plans:
        bindings.append(f"{plan.name} = {plan.reference}")
        cases = [
            f'case "{key}":\n' + textwrap.indent(plan.sources[key], "    ")
            for key in _DECODER_ORDER
            if key in plan.sources
        ]
        if not cases:
            continue
        body = "match operation:\n" + textwrap.indent("\n".join(cases), "    ")
        factory = factory_names.get(body)
        if factory is None:
            factory = factory_names[body] = f"d{len(factory_names)}"
            factories.append(
                f"def {factory}(ast, resolve, operation):\n"
                "    R = runtime\n" + textwrap.indent(body, "    ") + "\n    return None\n"
            )
        installations.append(f"runtime.set_compiler({plan.name}, {factory})")
    install = ["def install(asts):", *(f"    {line}" for line in bindings + installations)]
    if len(install) == 1:
        install.append("    pass")
    return "\n".join(
        [
            "# Generated by pyfect.schema.aot_compiler. Regenerate after schema or pyfect changes.",
            "# ruff: noqa",
            "# pyright: basic",
            "from pyfect.schema.compiler import runtime",
            "",
            *factories,
            "",
            *install,
            "",
        ]
    )


__all__ = ["Operation", "Target", "compile"]
