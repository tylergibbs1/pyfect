"""Generate ``pyfect.ai.openai.generated`` from Effect's generated OpenAI
module: ``uv run python scripts/gen_openai_schemas.py [GENERATED_TS]``.

Effect's ``@effect/ai-openai`` ships ``src/Generated.ts``, the OpenAI
OpenAPI spec turned into ``effect/Schema`` declarations by Effect's
generator. This script reads its declaration section (every
``export const X = Schema...``) and writes the same schemas in pyfect:

- ``generated/types.py``: a ``TypedDict`` for each struct (a nested one
  is named after its path, ``Parent__key``) and a ``type`` alias for every
  other schema, as Effect's ``export type``;
- ``generated/_schemas_N.py`` and ``generated/_recursive.py``: the
  schemas, with their checks and annotations (camelCase keys in
  snake_case, as pyfect spells them), re-exported by
  ``generated/__init__.py``.

The TypeScript is read with a parser for the subset the generator emits
(calls, chained methods, object and array literals, strings, numbers,
``suspend`` thunks and ``new RegExp``); anything else is an error naming
the declaration, so an Effect update that changes the shape fails loudly
instead of producing a wrong schema. ``--check`` fails when the files on
disk differ from what the source gives. The source is
``$PYFECT_REF/packages/ai/openai/src/Generated.ts``, ``$PYFECT_REF``
defaulting to ``~/pyfect-ref/effect``.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "src" / "pyfect" / "ai" / "openai" / "generated"


def default_source() -> Path:
    ref = Path(os.environ.get("PYFECT_REF", Path.home() / "pyfect-ref" / "effect"))
    return ref / "packages" / "ai" / "openai" / "src" / "Generated.ts"


class GenerateError(Exception):
    """The TypeScript has a shape the generator does not know."""


# --- tokens -----------------------------------------------------------------------------

_TOKEN = re.compile(
    r"""
    (?P<ws>\s+)
  | (?P<comment>//[^\n]*)
  | (?P<string>"(?:[^"\\]|\\.)*")
  | (?P<number>-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)
  | (?P<arrow>=>)
  | (?P<name>[A-Za-z_$][A-Za-z0-9_$]*)
  | (?P<punct>[(){}\[\],:.<>?|=])
    """,
    re.VERBOSE,
)


@dataclass(frozen=True)
class Token:
    kind: str
    text: str


def tokenize(source: str) -> list[Token]:
    tokens: list[Token] = []
    position = 0
    while position < len(source):
        match = _TOKEN.match(source, position)
        if match is None:
            raise GenerateError(f"unexpected character {source[position]!r}")
        kind = match.lastgroup or ""
        if kind not in ("ws", "comment"):
            tokens.append(Token(kind, match.group()))
        position = match.end()
    return tokens


# --- syntax -----------------------------------------------------------------------------


@dataclass(frozen=True)
class Ref:
    name: str


@dataclass(frozen=True)
class Str:
    value: str


@dataclass(frozen=True)
class Num:
    value: int | float


@dataclass(frozen=True)
class Bool:
    value: bool


@dataclass(frozen=True)
class Null:
    pass


@dataclass(frozen=True)
class Obj:
    entries: tuple[tuple[str, Node], ...]


@dataclass(frozen=True)
class Arr:
    items: tuple[Node, ...]


@dataclass(frozen=True)
class Call:
    """``Schema.<name>(args)``, or ``Schema.<name>`` itself when ``args``
    is ``None``."""

    name: str
    args: tuple[Node, ...] | None


@dataclass(frozen=True)
class Method:
    target: Node
    name: str
    args: tuple[Node, ...]


@dataclass(frozen=True)
class Thunk:
    body: Node


@dataclass(frozen=True)
class RegExp:
    source: str
    flags: str


@dataclass(frozen=True)
class Global:
    name: str


type Node = Ref | Str | Num | Bool | Null | Obj | Arr | Call | Method | Thunk | RegExp | Global


class Parser:
    def __init__(self, tokens: list[Token]) -> None:
        self.tokens = tokens
        self.index = 0

    def peek(self, offset: int = 0) -> Token | None:
        at = self.index + offset
        return self.tokens[at] if at < len(self.tokens) else None

    def next(self) -> Token:
        token = self.peek()
        if token is None:
            raise GenerateError("unexpected end of input")
        self.index += 1
        return token

    def expect(self, text: str) -> None:
        token = self.next()
        if token.text != text:
            raise GenerateError(f"expected {text!r}, got {token.text!r}")

    def at(self, text: str) -> bool:
        token = self.peek()
        return token is not None and token.text == text

    def done(self) -> bool:
        return self.index >= len(self.tokens)

    def expression(self) -> Node:
        node = self.primary()
        while self.at("."):
            self.next()
            name = self.next().text
            self.expect("(")
            node = Method(node, name, self.arguments(")"))
        return node

    def arguments(self, close: str) -> tuple[Node, ...]:
        items: list[Node] = []
        while not self.at(close):
            items.append(self.expression())
            if not self.at(close):
                self.expect(",")
        self.expect(close)
        return tuple(items)

    def primary(self) -> Node:  # noqa: PLR0911, PLR0912
        token = self.next()
        if token.kind == "string":
            return Str(json.loads(token.text))
        if token.kind == "number":
            number = float(token.text)
            return Num(int(number) if number.is_integer() and "." not in token.text else number)
        if token.text == "{":
            return self.object()
        if token.text == "[":
            return Arr(self.arguments("]"))
        if token.text == "(":
            return self.thunk()
        if token.kind != "name":
            raise GenerateError(f"unexpected {token.text!r}")
        match token.text:
            case "true" | "false":
                return Bool(token.text == "true")
            case "null":
                return Null()
            case "new":
                return self.regexp()
            case "Schema":
                self.expect(".")
                name = self.next().text
                if self.at("("):
                    self.next()
                    return Call(name, self.arguments(")"))
                return Call(name, None)
            case "globalThis":
                self.expect(".")
                return Global(self.next().text)
            case _:
                return Ref(token.text)

    def object(self) -> Obj:
        entries: list[tuple[str, Node]] = []
        while not self.at("}"):
            key = self.next()
            name = json.loads(key.text) if key.kind == "string" else key.text
            self.expect(":")
            entries.append((name, self.expression()))
            if not self.at("}"):
                self.expect(",")
        self.expect("}")
        return Obj(tuple(entries))

    def thunk(self) -> Thunk:
        """``(): Schema.Codec<X> => body``: the annotation is skipped."""
        self.expect(")")
        if self.at(":"):
            depth = 0
            while True:
                token = self.next()
                if token.text == "<":
                    depth += 1
                elif token.text == ">":
                    depth -= 1
                elif token.kind == "arrow" and depth == 0:
                    break
        elif self.next().kind != "arrow":
            raise GenerateError("expected =>")
        return Thunk(self.expression())

    def regexp(self) -> RegExp:
        if self.next().text != "RegExp":
            raise GenerateError("only `new RegExp(...)` is supported")
        self.expect("(")
        args = self.arguments(")")
        match args:
            case (Str(source), Str(flags)):
                return RegExp(source, flags)
            case (Str(source),):
                return RegExp(source, "")
            case _:
                raise GenerateError("RegExp takes string arguments")


@dataclass(frozen=True)
class Declaration:
    name: str
    node: Node


_START = re.compile(r"^(export type |export const |const |export interface |export function )")
_CONST = re.compile(r"^(?:export )?const ([A-Za-z_$][A-Za-z0-9_$]*)\s*=\s*", re.S)


def declarations(source: str) -> Iterator[Declaration]:
    """The ``const`` declarations of Generated.ts's schema section (it ends
    where the generated client's ``OperationConfig`` starts)."""
    end = source.find("export interface OperationConfig")
    section = source if end < 0 else source[:end]
    chunk: list[str] = []
    for line in [*section.splitlines(), "export type __END = never"]:
        if _START.match(line) and chunk:
            yield from _declaration("\n".join(chunk))
            chunk = []
        if chunk or _START.match(line):
            chunk.append(line)


def _declaration(chunk: str) -> Iterator[Declaration]:
    match = _CONST.match(chunk)
    if match is None:
        return
    name = match.group(1)
    try:
        parser = Parser(tokenize(chunk[match.end() :]))
        node = parser.expression()
    except GenerateError as error:
        raise GenerateError(f"{name}: {error}") from error
    if not parser.done():
        raise GenerateError(f"{name}: unexpected {parser.next().text!r} after the schema")
    yield Declaration(name, node)


# --- emitting ---------------------------------------------------------------------------

_PRIMITIVES = {
    "String": ("String", "str"),
    "Number": ("Number", "float"),
    "Finite": ("Finite", "float"),
    "Boolean": ("Boolean", "bool"),
    "Null": ("Null", "None"),
    "Unknown": ("Unknown", "object"),
    "Never": ("Never", "_t.Never"),
    "Json": ("Json", "_S.JsonValue"),
}

_CHECKS = {
    "isInt": "is_int",
    "isFinite": "is_finite",
    "isMinLength": "is_min_length",
    "isMaxLength": "is_max_length",
    "isMinCodePoints": "is_min_code_points",
    "isMaxCodePoints": "is_max_code_points",
    "isGreaterThan": "is_greater_than",
    "isGreaterThanOrEqualTo": "is_greater_than_or_equal_to",
    "isLessThan": "is_less_than",
    "isLessThanOrEqualTo": "is_less_than_or_equal_to",
    "isMinProperties": "is_min_properties",
    "isMaxProperties": "is_max_properties",
    "isPropertyNames": "is_property_names",
    "isMultipleOf": "is_multiple_of",
}

_GLOBALS = {"Blob": ("bytes", "bytes")}


def snake(name: str) -> str:
    return re.sub(r"(?<=[a-z0-9])([A-Z])", r"_\1", name).lower()


def _ident(text: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_]", "_", text)
    return cleaned if cleaned and not cleaned[0].isdigit() else f"_{cleaned}"


def py_name(name: str) -> str:
    """A TypeScript name in Python: ``__recursive_X`` is module-private."""
    return "_" + name.removeprefix("__") if name.startswith("__recursive_") else name


def literal(node: Node) -> str:
    match node:
        case Str(value):
            return json.dumps(value, ensure_ascii=False)
        case Num(value):
            return repr(value)
        case Bool(value):
            return "True" if value else "False"
        case Null():
            return "None"
        case _:
            raise GenerateError(f"not a literal: {node!r}")


@dataclass(frozen=True)
class Emitted:
    """A schema declaration in Python: its ``name``, its line and the
    names it refers to. ``lazy`` names the struct of a recursive schema,
    declared in the recursive module and loaded on first use."""

    name: str
    line: str
    refs: frozenset[str]
    recursive: bool = False


@dataclass
class Emitter:
    """Builds both modules, one declaration at a time."""

    types: list[str] = field(default_factory=list[str])
    schemas: list[Emitted] = field(default_factory=list[Emitted])
    type_names: set[str] = field(default_factory=set[str])
    pending: list[str] = field(default_factory=list[str])
    refs: set[str] = field(default_factory=set[str])

    def unique(self, name: str) -> str:
        candidate, n = name, 1
        while candidate in self.type_names:
            n += 1
            candidate = f"{name}_{n}"
        self.type_names.add(candidate)
        return candidate

    def declaration(self, declaration: Declaration) -> None:
        name = declaration.name
        node = declaration.node
        type_name = name.removeprefix("__recursive_")
        self.pending = []
        self.refs = set()
        if (
            isinstance(node, Call)
            and node.name == "suspend"
            and _suspended(node) == (f"__recursive_{name}")
        ):
            # The struct is declared with the other recursive ones under
            # ``__recursive_<name>``, whose TypedDict takes this name; the
            # declared type breaks the cycle for the type checker.
            target = py_name(f"__recursive_{name}")
            declared = f"_S.Bottom[_T.{name}, _t.Any]"
            line = f"{name}: {declared} = _b.lazy({_RECURSIVE_MODULE!r}, {target!r})"
            self.schemas.append(Emitted(name, line, frozenset()))
            return
        expression, py_type = self.schema(node, type_name, top=True)
        self.types.extend(self.pending)
        if py_type != type_name:
            self.type_names.add(type_name)
            self.types.append(f"type {type_name} = {py_type}")
        if _is_struct(node):
            declared = f"_StructSchema[_T.{type_name}, _t.Never, _t.Never]"
        else:
            declared = f"_S.Bottom[_T.{type_name}, _t.Any]"
        line = f"{py_name(name)}: {declared} = {expression}"
        recursive = name.startswith("__recursive_")
        self.schemas.append(Emitted(py_name(name), line, frozenset(self.refs), recursive))

    def schema(self, node: Node, path: str, *, top: bool = False) -> tuple[str, str]:  # noqa: PLR0911, PLR0912
        """The Python expression of a schema node and its decoded type."""
        match node:
            case Ref(name):
                self.refs.add(py_name(name))
                return py_name(name), _type_ref(name)
            case Global(name) if name in _GLOBALS:
                return _GLOBALS[name]
            case Method(target, "annotate", (Obj() as annotations,)):
                expression, py_type = self.schema(target, path, top=top)
                return f"{expression}.annotate({self.annotations(annotations)})", py_type
            case Method(target, "check", checks):
                expression, py_type = self.schema(target, path, top=top)
                rendered = ", ".join(self.check(check) for check in checks)
                return f"_b.check({expression}, {rendered})", py_type
            case Call(name, None) if name in _PRIMITIVES:
                schema, py_type = _PRIMITIVES[name]
                return f"_S.{schema}", py_type
            case Call("Literal", (value,)):
                return f"_b.literal({literal(value)})", f"_t.Literal[{literal(value)}]"
            case Call("Literals", (Arr(items),)):
                values = ", ".join(literal(item) for item in items)
                return f"_b.literals([{values}])", f"_t.Literal[{values}]"
            case Call("Struct", (Obj(entries),)):
                return self.struct(entries, path if top else self.unique(path))
            case Call("StructWithRest", (struct, Arr(records))):
                expression, py_type = self.schema(struct, path, top=top)
                rest = [self.schema(record, f"{path}__rest")[0] for record in records]
                return f"_b.struct_with_rest({expression}, {', '.join(rest)})", py_type
            case Call("Union", (Arr(members), *options)):
                rendered = [self.schema(m, f"{path}__{i}") for i, m in enumerate(members)]
                mode = ""
                if options:
                    match options[0]:
                        case Obj((("mode", Str("oneOf")),)):
                            mode = ', mode="one_of"'
                        case _:
                            raise GenerateError(f"unknown Union options {options[0]!r}")
                schemas = ", ".join(expression for expression, _ in rendered)
                return f"_b.union({schemas}{mode})", _union(py_type for _, py_type in rendered)
            case Call("Array", (item,)):
                expression, py_type = self.schema(item, f"{path}__item")
                return f"_b.array({expression})", f"_abc.Sequence[{py_type}]"
            case Call("Record", (key, value)):
                key_expression, key_type = self.schema(key, f"{path}__key")
                expression, py_type = self.schema(value, f"{path}__value")
                return (
                    f"_b.record({key_expression}, {expression})",
                    f"_abc.Mapping[{key_type}, {py_type}]",
                )
            case Call("suspend", (Thunk(body),)):
                expression, py_type = self.schema(body, path)
                return f"_b.suspend(lambda: {expression})", py_type
            case Call("instanceOf", (target, *options)):
                expression, py_type = self.schema(target, path)
                rendered = self.annotations(options[0]) if options else ""
                separator = ", " if rendered else ""
                return f"_b.instance_of({expression}{separator}{rendered})", py_type
            case _:
                raise GenerateError(f"unsupported schema {_describe(node)}")

    def struct(self, entries: tuple[tuple[str, Node], ...], type_name: str) -> tuple[str, str]:
        self.type_names.add(type_name)
        fields: list[str] = []
        annotations: list[str] = []
        optional: list[str] = []
        for key, value in entries:
            inner = value
            is_optional = False
            if isinstance(inner, Call) and inner.name in ("optionalKey", "optional"):
                is_optional = True
                match inner.args:
                    case (wrapped,):
                        inner = wrapped
                    case _:
                        raise GenerateError(f"{key}: Schema.{inner.name} takes one schema")
            expression, py_type = self.schema(inner, f"{type_name}__{_ident(key)}")
            key_text = json.dumps(key)
            fields.append(f"{key_text}: {expression}")
            annotation = f"_t.NotRequired[{py_type}]" if is_optional else py_type
            annotations.append(f"{key_text}: {json.dumps(annotation)}")
            if is_optional:
                optional.append(key_text)
        body = ", ".join(annotations)
        self.pending.append(f"{type_name} = _t.TypedDict({json.dumps(type_name)}, {{{body}}})")
        optional_text = f", optional=({', '.join(optional)},)" if optional else ""
        return f"_b.struct(_T.{type_name}, {{{', '.join(fields)}}}{optional_text})", type_name

    def annotations(self, node: Node) -> str:
        if not isinstance(node, Obj):
            raise GenerateError(f"annotations must be an object, got {_describe(node)}")
        return ", ".join(f"{snake(key)}={literal(value)}" for key, value in node.entries)

    def check(self, node: Node) -> str:
        match node:
            case Method(target, "annotate", (Obj() as annotations,)):
                return f"{self.check(target)}.annotate({self.annotations(annotations)})"
            case Call("makeFilterGroup", (Arr(items),)):
                return f"_S.make_filter_group({', '.join(self.check(item) for item in items)})"
            case Call("isPattern", (RegExp(source, flags),)):
                if flags not in ("", "u"):
                    raise GenerateError(f"unsupported RegExp flags {flags!r}")
                return f"_b.js_pattern({_python_regex(source)}, {source!r})"
            case Call("isPropertyNames", (schema,)):
                return f"_S.is_property_names({self.schema(schema, '_')[0]})"
            case Call(name, args) if name in _CHECKS:
                rendered = ", ".join(literal(arg) for arg in args or ())
                return f"_S.{_CHECKS[name]}({rendered})"
            case _:
                raise GenerateError(f"unsupported check {_describe(node)}")


def _is_struct(node: Node) -> bool:
    """Whether the schema is a ``Struct`` (possibly annotated or checked)."""
    match node:
        case Method(target, "annotate" | "check", _):
            return _is_struct(target)
        case Call("Struct", _):
            return True
        case _:
            return False


def _suspended(node: Call) -> str | None:
    match node.args:
        case (Thunk(Ref(name)),):
            return name
        case _:
            return None


def _type_ref(name: str) -> str:
    return name.removeprefix("__recursive_")


def _union(types: Iterator[str]) -> str:
    seen: list[str] = []
    for py_type in types:
        if py_type not in seen:
            seen.append(py_type)
    return " | ".join(seen)


def _python_regex(source: str) -> str:
    """A JavaScript ``u`` pattern as a Python one: ``$`` (outside a class)
    ends the input, as JavaScript's does, where Python's also matches
    before a final newline. Syntax the two read differently fails."""
    if re.search(r"\\[pPkdDwWbB]|\(\?<[=!]?[A-Za-z]|\\u\{", source):
        raise GenerateError(f"RegExp {source!r} uses syntax JavaScript reads differently")
    out: list[str] = []
    in_class = False
    index = 0
    while index < len(source):
        char = source[index]
        if char == "\\":
            out.append(source[index : index + 2])
            index += 2
            continue
        if in_class:
            in_class = char != "]"
        elif char == "[":
            in_class = True
        elif char == "$":
            char = r"\Z"
        elif char == ".":
            raise GenerateError(f"RegExp {source!r}: `.` excludes more line ends in JavaScript")
        out.append(char)
        index += 1
    translated = "".join(out)
    re.compile(translated)
    return repr(translated)


def _describe(node: Node) -> str:
    match node:
        case Call(name, _):
            return f"Schema.{name}"
        case Method(_, name, _):
            return f".{name}(...)"
        case _:
            return type(node).__name__


PACKAGE = "pyfect.ai.openai.generated"
_RECURSIVE_MODULE = f"{PACKAGE}._recursive"
CHUNK = 1000
"""Declarations per schema module: pyright gives up on a module with
several thousand (``Code is too complex to analyze``)."""

_HEADER = """# pyright: reportPrivateUsage=false, reportUnusedImport=false
"""

_CHUNK_HEADER = f'''"""Schemas generated by ``scripts/gen_openai_schemas.py``; do not edit.
Import them from ``{PACKAGE}``."""

{_HEADER}from __future__ import annotations

import typing as _t

from pyfect import schema as _S
from pyfect.ai.openai import _generated_support as _b
from pyfect.ai.openai.generated import types as _T
from pyfect.schema._struct import StructSchema as _StructSchema
'''

_INIT_HEADER = f'''"""The schemas of the OpenAI API (Effect's ``Generated.ts``), generated from
Effect's module by ``scripts/gen_openai_schemas.py``: rerun it after an
update, do not edit. Each schema has Effect's name, its checks and its
annotations; its type is the name of the same name in ``types``::

    from pyfect.ai.openai import generated
    from pyfect.ai.openai.generated import types

    call: types.FunctionToolCall = S.decode_unknown_sync(generated.FunctionToolCall)(json)
"""

{_HEADER}from __future__ import annotations
'''

_TYPES_HEADER = f'''"""The types of the OpenAI API schemas: a ``TypedDict`` for each struct (a
nested one named after its path, ``Parent__key``), an alias for every
other schema. Generated by ``scripts/gen_openai_schemas.py``; do not edit."""

{_HEADER}from __future__ import annotations

import collections.abc as _abc
import typing as _t

from pyfect import schema as _S
'''


def _module(header: str, items: list[Emitted], home: dict[str, str], module: str) -> str:
    imports: dict[str, set[str]] = {}
    for item in items:
        for ref in item.refs:
            source = home[ref]
            if source != module:
                imports.setdefault(source, set()).add(ref)
    lines = [header]
    for source in sorted(imports):
        names = ", ".join(sorted(imports[source]))
        lines.append(f"from {source} import {names}")
    lines.append("")
    lines.extend(item.line for item in items)
    return "\n".join(lines) + "\n"


_TYPE_NAME = re.compile(r"^(?:type )?([A-Za-z_][A-Za-z0-9_]*) = ")


def _all(names: list[str]) -> str:
    return "\n__all__ = [\n" + "".join(f'    "{name}",\n' for name in sorted(names)) + "]\n"


def generate(source: str) -> dict[str, str]:
    """The generated package's modules (file name to text) for a
    Generated.ts source."""
    emitter = Emitter()
    for declaration in declarations(source):
        try:
            emitter.declaration(declaration)
        except GenerateError as error:
            raise GenerateError(f"{declaration.name}: {error}") from error
    if not emitter.schemas:
        raise GenerateError("no schema declarations found")
    plain = [item for item in emitter.schemas if not item.recursive]
    recursive = [item for item in emitter.schemas if item.recursive]
    chunks = [plain[i : i + CHUNK] for i in range(0, len(plain), CHUNK)]
    home: dict[str, str] = {}
    type_names = [m.group(1) for line in emitter.types if (m := _TYPE_NAME.match(line))]
    if len(type_names) != len(emitter.types):
        raise GenerateError("a type declaration that is not one line")
    files: dict[str, str] = {
        "types.py": _TYPES_HEADER + "\n".join(emitter.types) + "\n" + _all(type_names)
    }
    modules: list[tuple[str, list[Emitted]]] = [
        (f"_schemas_{index}", chunk) for index, chunk in enumerate(chunks)
    ]
    modules.append(("_recursive", recursive))
    for name, items in modules:
        for item in items:
            home[item.name] = f"{PACKAGE}.{name}"
    for name, items in modules:
        files[f"{name}.py"] = _module(_CHUNK_HEADER, items, home, f"{PACKAGE}.{name}")
    exports = [f"from {home[item.name]} import {item.name} as {item.name}" for item in plain]
    files["__init__.py"] = (
        _INIT_HEADER + "\n" + "\n".join(exports) + "\n" + _all([item.name for item in plain])
    )
    return files


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate pyfect.ai.openai.generated")
    parser.add_argument("source", nargs="?", type=Path, default=None)
    parser.add_argument("--check", action="store_true", help="fail when the files are stale")
    args = parser.parse_args(argv)
    source_path: Path = args.source or default_source()
    files = generate(source_path.read_text())
    if args.check:
        stale = [
            name
            for name, text in files.items()
            if not (OUT_DIR / name).exists() or (OUT_DIR / name).read_text() != text
        ]
        stale += [path.name for path in OUT_DIR.glob("*.py") if path.name not in files]
        for name in stale:
            print(f"{name} is stale; rerun {Path(__file__).name}", file=sys.stderr)
        return 1 if stale else 0
    OUT_DIR.mkdir(exist_ok=True)
    for path in OUT_DIR.glob("*.py"):
        if path.name not in files:
            path.unlink()
    for name, text in files.items():
        (OUT_DIR / name).write_text(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
