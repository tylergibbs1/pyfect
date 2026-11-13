"""Every public generic class keeps the variance pinned in `tests/_variance_expected.py`.

Pyright infers a frozen dataclass's PEP 695 type parameters as invariant (its
synthesized ``__replace__`` takes the fields), and a mutable attribute, a
``list[A]`` or a method taking ``A`` does the same to any class. Effect marks its
variance (``in``/``out``, ``Covariant<A>``), so a class stricter than Effect's
rejects code Effect accepts: ``add_all([route_a, route_b])`` matched no overload.

`tests/_variance_probe.py` is generated from the table and checked by the pyright
run. For each type parameter it returns ``C[Sub]`` as ``C[Super]`` and the
reverse; the direction the table says fails carries a
``# pyright: ignore[reportReturnType]``, and unnecessary ignores fail the build.
A change that makes a class stricter fails the pyright run; one that loosens it
fails too, until the table says the new, looser variance.

A dataclass spells its variance with ``TypeVar(covariant=True)``, which pyright
does not check against the fields. The probe also restates each such
dataclass's fields as a protocol with the same TypeVars, and pyright checks a
protocol's declared variance: a ``Callable[[A], ...]`` or a mutable field under
a covariant ``A`` fails the run.

Regenerate the probe after editing the table, or when a class changes, with

    UPDATE_VARIANCE_PROBE=1 uv run pytest tests/test_variance.py

and print the variance pyright infers today (for a new class) with

    uv run python tests/test_variance.py
"""

import ast
import inspect
import json
import os
import re
import subprocess
import sys
import types
import typing
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, ParamSpec, TypeAliasType, TypeVar, TypeVarTuple

from _pyfect_modules import modules
from _variance_expected import EXPECTED, Variance

import pyfect

ROOT = Path(__file__).parent.parent
PROBE = Path(__file__).parent / "_variance_probe.py"
IGNORE = "  # pyright: ignore[reportReturnType]"

type Param = TypeVar | ParamSpec | TypeVarTuple
type Direction = Literal["out", "in"]


@dataclass(frozen=True)
class GenericClass:
    path: str
    cls: type
    params: tuple[Param, ...]


def _own_params(cls: type) -> tuple[Param, ...]:
    own = vars(cls)
    return own.get("__type_params__", ()) or own.get("__parameters__", ())


def public_generic_classes() -> list[GenericClass]:
    """Each generic class pyfect defines, under its shortest public name."""
    found: dict[int, tuple[str, type]] = {}
    for module in [pyfect, *modules(public=True)]:
        for attr, value in vars(module).items():
            if attr.startswith("_") or not isinstance(value, type):
                continue
            if not value.__module__.startswith("pyfect") or not _own_params(value):
                continue
            path = f"{module.__name__}.{attr}"
            seen = found.get(id(value))
            if seen is None or (len(path), path) < (len(seen[0]), seen[0]):
                found[id(value)] = (path, value)
    return [
        GenericClass(path, cls, _own_params(cls))
        for path, cls in sorted(found.values(), key=lambda found: found[0])
    ]


_SPECIAL_FORMS: tuple[object, ...] = (
    typing.Any,
    typing.Never,
    typing.NoReturn,
    typing.LiteralString,
)


def _spell_atom(annotation: object) -> str | None:
    """The source text of a non-generic ``annotation``, or ``None`` for a generic one."""
    literals: dict[object, str] = {None: "None", types.NoneType: "None", Ellipsis: "..."}
    if any(annotation is literal for literal in literals):
        return literals[annotation]
    if isinstance(annotation, TypeAliasType):
        return f"{annotation.__module__}.{annotation.__name__}"
    if isinstance(annotation, type) and not isinstance(annotation, types.GenericAlias):
        if annotation.__module__ == "builtins":
            return annotation.__qualname__
        return f"{annotation.__module__}.{annotation.__qualname__}"
    if any(annotation is form for form in _SPECIAL_FORMS):
        return f"typing.{typing.cast('typing.Any', annotation)._name}"
    return None


def _spell(annotation: object, var: Callable[[TypeVar], str] = lambda _: "Any") -> str:
    """Source text naming ``annotation`` through its defining module's dotted path."""

    def spell(inner: object) -> str:
        return _spell(inner, var)

    if isinstance(annotation, TypeVar):
        return var(annotation)
    if isinstance(annotation, list):
        return f"[{', '.join(spell(a) for a in typing.cast('list[object]', annotation))}]"
    atom = _spell_atom(annotation)
    if atom is not None:
        return atom
    origin = typing.get_origin(annotation)
    args: tuple[object, ...] = typing.get_args(annotation)
    if origin is None:
        raise TypeError(f"cannot spell {annotation!r}")
    if origin is typing.Annotated:
        return spell(args[0])
    if origin in (types.UnionType, typing.Union):
        return " | ".join(spell(a) for a in args)
    inner = (repr(a) for a in args) if origin is Literal else (spell(a) for a in args)
    return f"{'typing.Literal' if origin is Literal else spell(origin)}[{', '.join(inner)}]"


def _module_of(dotted: str) -> str | None:
    """The longest prefix of ``dotted`` that is an imported module."""
    parts = dotted.split(".")
    for end in range(len(parts) - 1, 0, -1):
        if ".".join(parts[:end]) in sys.modules:
            return ".".join(parts[:end])
    return None


def _arg(param: Param) -> str:
    if isinstance(param, ParamSpec):
        return "..."
    if isinstance(param, TypeVarTuple):
        return "*tuple[Any, ...]"
    return "Any"


def _bound(param: TypeVar, cls: type) -> object:
    """``param``'s bound, a forward reference resolved in ``cls``'s module."""
    bound = param.__bound__
    if isinstance(bound, typing.ForwardRef):
        return getattr(sys.modules[cls.__module__], bound.__forward_arg__)
    return bound


def _sub_super(param: TypeVar, cls: type) -> tuple[str, str]:
    bound = _bound(param, cls)
    return ("_Sub", "_Super") if bound is None else ("Never", _spell(bound))


def _variance_checks(
    generic: GenericClass, row: tuple[Variance, ...] | None
) -> Iterator[tuple[int, Direction, str]]:
    """``(param index, direction, function source)``; ``{name}`` is the function's name."""
    for j, param in enumerate(generic.params):
        if not isinstance(param, TypeVar) or (row is not None and row[j] == "skip"):
            continue
        sub, sup = _sub_super(param, generic.cls)
        directions: tuple[tuple[Direction, str, str], ...] = (("out", sub, sup), ("in", sup, sub))
        for direction, low, high in directions:
            args = [_arg(p) for p in generic.params]
            args[j] = low
            source = f"{generic.path}[{', '.join(args)}]"
            args[j] = high
            target = f"{generic.path}[{', '.join(args)}]"
            fails = row is not None and row[j] not in (direction, "bi")
            yield (
                j,
                direction,
                f"def {{name}}(x: {source}) -> {target}:\n    return x{IGNORE if fails else ''}",
            )


def _import_map(module: types.ModuleType) -> dict[str, str]:
    """Each name ``module``'s imports bind (``TYPE_CHECKING`` ones too), to its dotted path."""
    tree = ast.parse(inspect.getsource(module))
    package = module.__name__ if hasattr(module, "__path__") else module.__name__.rpartition(".")[0]
    bound: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                bound[alias.asname or alias.name.split(".")[0]] = (
                    alias.name if alias.asname else alias.name.split(".")[0]
                )
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if node.level:
                parent = package.rsplit(".", node.level - 1)[0] if node.level > 1 else package
                base = f"{parent}.{base}" if base else parent
            for alias in node.names:
                bound[alias.asname or alias.name] = f"{base}.{alias.name}"
    return bound


@dataclass(frozen=True)
class Attribute:
    annotation: str
    module: types.ModuleType
    read_only: bool
    owner: type


_WRAPPERS = {"Final", "ReadOnly", "NotRequired", "Required", "Annotated"}


def _unwrap(annotation: ast.expr) -> tuple[ast.expr | None, bool]:
    """The type under ``Final``/``ReadOnly``/``NotRequired``, and whether it is read-only;
    ``None`` for a ``ClassVar``."""
    read_only = False
    while True:
        head = annotation.value if isinstance(annotation, ast.Subscript) else annotation
        name = head.attr if isinstance(head, ast.Attribute) else getattr(head, "id", None)
        if name == "ClassVar":
            return None, False
        if name not in _WRAPPERS:
            return annotation, read_only
        read_only = read_only or name in {"Final", "ReadOnly"}
        if not isinstance(annotation, ast.Subscript):
            return None, read_only  # a bare ``Final``: the type is inferred
        inner = annotation.slice
        annotation = inner.elts[0] if isinstance(inner, ast.Tuple) else inner


def _attributes(cls: type) -> dict[str, Attribute]:
    """Each annotated instance attribute (class body or ``self.x: T``), bases first."""
    found: dict[str, Attribute] = {}
    bases: list[type] = list(reversed(cls.__mro__))
    for base in bases:
        if not base.__module__.startswith("pyfect") or typing.is_protocol(base):
            continue
        definition, module = _class_node(base)
        params = getattr(base, "__dataclass_params__", None)
        frozen = params is not None and params.frozen
        named_tuple = tuple in base.__mro__
        # A plain class's body annotations are often class settings a subclass overrides.
        declares_fields = params is not None or named_tuple or typing.is_typeddict(base)
        annotated: list[tuple[str, ast.expr]] = [
            (node.target.id, node.annotation)
            for node in definition.body
            if declares_fields
            and isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
        ]
        annotated += [
            (node.target.attr, node.annotation)
            for method in definition.body
            if isinstance(method, ast.FunctionDef)
            for node in ast.walk(method)
            if isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Attribute)
            and isinstance(node.target.value, ast.Name)
            and node.target.value.id == "self"
        ]
        for name, annotation in annotated:
            if name.startswith("_") and not name.endswith("__"):
                continue  # private: only the class's own methods, which pyright checks, write it
            inner, read_only = _unwrap(annotation)
            if inner is not None:
                found[name] = Attribute(
                    ast.unparse(inner), module, read_only or frozen or named_tuple, base
                )
    return found


def _defining_module(cls: type) -> types.ModuleType:
    """The module whose source defines ``cls`` (``Some.__module__`` is reassigned)."""
    top = cls.__qualname__.split(".")[0]
    candidates = [sys.modules[cls.__module__]] + [
        m for name, m in sorted(sys.modules.items()) if name.startswith("pyfect.")
    ]
    for module in candidates:
        if getattr(module, top, None) is getattr(sys.modules[cls.__module__], top, cls):
            source = inspect.getsource(module)
            if re.search(rf"^\s*class {top}\b", source, re.MULTILINE):
                return module
    raise LookupError(cls)


def _class_node(cls: type) -> tuple[ast.ClassDef, types.ModuleType]:
    """``cls``'s definition (``inspect.getsource`` misses slots classes), and its module."""
    module = _defining_module(cls)
    node: ast.AST = ast.parse(inspect.getsource(module))
    for part in cls.__qualname__.split("."):
        node = next(n for n in ast.walk(node) if isinstance(n, ast.ClassDef) and n.name == part)
    return typing.cast("ast.ClassDef", node), module


def _qualifier(module: types.ModuleType, names: dict[str, str]) -> ast.NodeTransformer:
    """Spells names through dotted paths, the class's TypeVars through ``names``."""
    imports = _import_map(module)

    class Qualify(ast.NodeTransformer):
        def visit_Name(self, node: ast.Name) -> ast.expr:
            if node.id in names:
                spelled = names[node.id]
            elif node.id in imports:
                spelled = imports[node.id]
            elif isinstance(getattr(module, node.id, None), types.ModuleType):
                spelled = getattr(module, node.id).__name__
            elif isinstance(getattr(module, node.id, None), ParamSpec):
                spelled = "..."
            elif isinstance(getattr(module, node.id, None), TypeVar | TypeVarTuple):
                spelled = "Any"
            elif hasattr(module, node.id):
                spelled = f"{module.__name__}.{node.id}"
            else:
                return node
            return ast.parse(spelled, mode="eval").body

        def visit_Subscript(self, node: ast.Subscript) -> ast.expr:
            if isinstance(node.value, ast.Name) and node.value.id == "Literal":
                node.value = self.visit_Name(node.value)
                return node
            return typing.cast("ast.expr", self.generic_visit(node))

        def visit_Constant(self, node: ast.Constant) -> ast.expr:
            if not isinstance(node.value, str):
                return node
            try:  # a quoted annotation
                quoted = ast.parse(node.value, mode="eval").body
            except SyntaxError:
                return node
            return typing.cast("ast.expr", self.visit(quoted))

    return Qualify()


def _qualify(source: str, module: types.ModuleType, names: dict[str, str]) -> str:
    """``source``'s names spelled through dotted paths, the class's TypeVars through ``names``."""
    return ast.unparse(_qualifier(module, names).visit(ast.parse(source, mode="eval")))


def _fields_protocol(i: int, generic: GenericClass) -> str | None:
    """The class's attributes as a protocol with its declared co/contravariant TypeVars."""
    typevars = [p for p in generic.params if isinstance(p, TypeVar)]
    declared = [p for p in typevars if p.__covariant__ or p.__contravariant__]
    if not declared or typing.is_protocol(generic.cls):
        return None
    names = {
        p.__name__: f"T{i}_{k}_{'co' if p.__covariant__ else 'contra'}" if p in declared else "Any"
        for k, p in enumerate(typevars)
    }
    lines = [
        f"{names[p.__name__]} = TypeVar({names[p.__name__]!r}, "
        f"{'covariant' if p.__covariant__ else 'contravariant'}=True"
        f"{'' if p.__bound__ is None else f', bound={_spell(_bound(p, generic.cls))}'})"
        for p in declared
    ]
    lines.append(f"class Fields{i}(Protocol[{', '.join(names[p.__name__] for p in declared)}]):")
    for name, attribute in _attributes(generic.cls).items():
        own = names if attribute.owner is generic.cls else {}
        hidden = {p.__name__: _arg(p) for p in _own_params(attribute.owner)}
        spelled = _qualify(attribute.annotation, attribute.module, {**hidden, **own})
        if attribute.read_only:
            lines += ["    @property", f"    def {name}(self) -> {spelled}: ..."]
        else:
            lines.append(f"    {name}: {spelled}")
    # Each parameter's declared direction, so one no attribute uses passes.
    co = ", ".join(names[p.__name__] for p in declared if p.__covariant__)
    contra = "".join(
        f", _{k}: {names[p.__name__]}" for k, p in enumerate(declared) if p.__contravariant__
    )
    lines.append(f"    def declared(self{contra}) -> tuple[{co or '()'}]: ...")
    return "\n".join(lines)


def render_probe(
    generics: list[GenericClass], table: dict[str, tuple[Variance, ...]] | None
) -> tuple[str, dict[str, tuple[str, int, Direction]]]:
    """The probe's source and, per check function's name, the parameter it checks."""
    blocks: list[str] = []
    checks: dict[str, tuple[str, int, Direction]] = {}
    for i, generic in enumerate(generics):
        row = None if table is None else table[generic.path]
        blocks.append(f"# {generic.path}")
        for j, direction, source in _variance_checks(generic, row):
            name = f"v{i}_{j}_{direction}"
            checks[name] = (generic.path, j, direction)
            blocks.append(source.format(name=name))
        protocol = _fields_protocol(i, generic)
        if protocol is not None:
            blocks.append(protocol)
    body = "\n\n".join(blocks)
    imports = sorted(
        {
            module
            for name in re.findall(r"(?<![\w.'\"])([a-z]\w*(?:\.\w+)+)", body)
            for module in [_module_of(name)]
            if module is not None
        }
    )
    text = "\n".join(
        [
            '"""Generated by tests/test_variance.py from tests/_variance_expected.py."""',
            "",
            # Deprecated classes keep their variance until they are removed.
            "# pyright: reportPrivateUsage=false, reportDeprecated=false",
            "",
            "from typing import Any, Never, Protocol, TypeVar",
            *(f"import {m}" for m in imports),
            "",
            "class _Super: ...",
            "class _Sub(_Super): ...",
            "",
            body,
        ]
    )
    for command in (["check", "--fix-only", "--quiet"], ["format"]):
        text = subprocess.run(
            [sys.executable, "-m", "ruff", *command, "--stdin-filename", str(PROBE), "-"],
            input=text,
            capture_output=True,
            text=True,
            check=True,
            cwd=ROOT,
        ).stdout
    return text, checks


def _pyright_errors(text: str) -> list[tuple[int, dict[str, typing.Any]]]:
    scratch = PROBE.with_name("_variance_measure.py")
    scratch.write_text(text)
    try:
        run = subprocess.run(
            [sys.executable, "-m", "pyright", "--outputjson", str(scratch)],
            capture_output=True,
            text=True,
            check=False,
            cwd=ROOT,
        )
    finally:
        scratch.unlink()
    diagnostics: list[dict[str, typing.Any]] = json.loads(run.stdout)["generalDiagnostics"]
    return [(d["range"]["start"]["line"], d) for d in diagnostics if d["severity"] == "error"]


def measure() -> dict[str, tuple[Variance, ...]]:
    """The variance pyright infers for each public generic class today."""
    generics = public_generic_classes()
    text, checks = render_probe(generics, None)
    owner: list[str | None] = []
    current: str | None = None
    for line in text.splitlines():
        match = re.match(r"def (v\w+)\(", line)
        current = match.group(1) if match else (None if line.startswith("class") else current)
        owner.append(current)
    failed: set[str] = set()
    for line, diagnostic in _pyright_errors(text):
        name = owner[line]
        if diagnostic.get("rule") != "reportReturnType" or name is None:
            source = text.splitlines()[line]
            print(f"not a variance check: {diagnostic['message']}\n  {source}", file=sys.stderr)
            continue
        failed.add(name)
    passed: dict[tuple[str, int], set[Direction]] = {}
    for name, (path, j, direction) in checks.items():
        passed.setdefault((path, j), set())
        if name not in failed:
            passed[(path, j)].add(direction)
    labels: dict[frozenset[Direction], Variance] = {
        frozenset({"out", "in"}): "bi",
        frozenset({"out"}): "out",
        frozenset({"in"}): "in",
        frozenset(): "inv",
    }
    return {
        g.path: tuple(
            labels[frozenset(passed[(g.path, j)])] if (g.path, j) in passed else "skip"
            for j in range(len(g.params))
        )
        for g in generics
    }


def test_every_public_generic_class_has_its_variance_pinned():
    found = {g.path: len(g.params) for g in public_generic_classes()}
    pinned = {path: len(row) for path, row in EXPECTED.items()}
    assert found == pinned


def test_the_probe_is_generated_from_the_table():
    text, _ = render_probe(public_generic_classes(), EXPECTED)
    if os.environ.get("UPDATE_VARIANCE_PROBE"):
        PROBE.write_text(text)
    assert PROBE.read_text() == text, "run UPDATE_VARIANCE_PROBE=1 pytest tests/test_variance.py"


def _slots(cls: type) -> set[str]:
    slots = vars(cls).get("__slots__", ())
    return {slots} if isinstance(slots, str) else set(slots)


def test_no_final_public_slot_in_a_class_with_inferred_variance():
    """Pyright reads a slot as a writable descriptor, so ``self.x: Final`` on a slot keeps
    the PEP 695 parameters ``x`` uses invariant. A read-only attribute of such a class is a
    private slot behind a ``@property`` (Effect's ``readonly``)."""
    offenders = [
        f"{generic.path}.{node.target.attr}"
        for generic in public_generic_classes()
        if all(getattr(p, "__infer_variance__", False) for p in generic.params)
        for node in ast.walk(_class_node(generic.cls)[0])
        if isinstance(node, ast.AnnAssign)
        and isinstance(node.target, ast.Attribute)
        and node.target.attr in _slots(generic.cls)
        and not node.target.attr.startswith("_")
        and _unwrap(node.annotation)[1]
    ]
    assert not offenders


if __name__ == "__main__":
    for path, row in measure().items():
        print(f"    {path!r}: {row!r},")
