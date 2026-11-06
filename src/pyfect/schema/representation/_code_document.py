"""``to_code_document``: Python source for a document's schemas (Effect's
``toCodeDocument``, which writes TypeScript; a Python struct needs a
``TypedDict``, so it comes out as an artifact). ``to_code_module`` lays a
``CodeDocument`` out as one module that runs and type-checks."""

from __future__ import annotations

import keyword
import re
from collections.abc import Callable, Sequence
from typing import cast

from pyfect.schema.issue import Path
from pyfect.schema.representation import _model as R
from pyfect.schema.representation._code import (
    Artifact,
    CheckCodeInput,
    Code,
    CodeDocument,
    CodeReferences,
    DeclarationCodeInput,
    EnumArtifact,
    GeneratedCheck,
    GeneratedDeclaration,
    ImportArtifact,
    NamedCode,
    TypedDictArtifact,
)
from pyfect.schema.representation._code_builtins import (
    check_code,
    declaration_code,
    string_literal,
    value_literal,
)
from pyfect.schema.representation._code_sort import topological_sort
from pyfect.schema.representation._from import error_with_path

_EXCLUDED_ANNOTATIONS = frozenset(
    {
        "representation",
        "arbitrary_constraint",
        "to_json_schema",
        "to_code",
        "to_equivalence",
        "to_formatter",
        "to_codec",
        "to_codec_json",
        "to_codec_string_tree",
        "to_codec_iso",
        "to_codec_arbitrary",
        "~structural",
        "~sentinels",
        "~identifier",
        "~constructor",
    }
)
_FINITE = 'S.is_finite().annotate(expected="a finite number")'
_RESERVED = frozenset(
    {
        "S",
        "Any",
        "Literal",
        "Mapping",
        "Never",
        "None",
        "NotRequired",
        "TypedDict",
        "True",
        "False",
        "enum",
        "re",
    }
)

_TYPING = "from typing import "


def sanitize_identifier(input: str) -> str:
    """``input`` as a Python identifier, public and capitalized as a schema's name is."""
    if not input:
        return "_"
    out = re.sub(r"[^A-Za-z0-9_]", "_", input)
    first = out[0]
    if "a" <= first <= "z":
        return first.upper() + out[1:]
    return f"_{out}" if "0" <= first <= "9" else out


def _is_plain_key(name: str) -> bool:
    return name.isidentifier() and not keyword.iskeyword(name)


def _keywords(entries: Sequence[tuple[str, str]]) -> str:
    """``entries`` as keyword arguments; a name that is not an identifier goes
    through ``**``."""
    plain = [f"{name}={value}" for name, value in entries if _is_plain_key(name)]
    others = [f"{string_literal(n)}: {v}" for n, v in entries if not _is_plain_key(n)]
    if others:
        plain.append(f"**{{{', '.join(others)}}}")
    return ", ".join(plain)


def _render_annotations(annotations: R.Annotations | None) -> str:
    entries: list[tuple[str, str]] = []
    for key, value in (annotations or {}).items():
        if key in _EXCLUDED_ANNOTATIONS:
            continue
        rendered = value_literal(value)
        if rendered is not None:
            entries.append((key, rendered))
    return _keywords(entries)


def _annotate(annotations: R.Annotations | None, method: str = "annotate") -> str:
    rendered = _render_annotations(annotations)
    return f".{method}({rendered})" if rendered else ""


def _is_simple_literal(node: R.Representation) -> bool:
    return isinstance(node, R.Literal) and not node.checks and node.annotations is None


def _literal_type(value: R.LiteralValue) -> str:
    # ``Literal[1.5]`` is not a type.
    return "float" if isinstance(value, float) else f"Literal[{value_literal(value)}]"


class _Generator:
    def __init__(self, document: R.MultiDocument) -> None:
        self.document = document
        self.sorted = topological_sort(document.references)
        self.artifacts: list[Artifact] = []
        self.identifiers: dict[str, str] = {}
        roots = (f"Schema{index}" for index in range(len(document.representations)))
        self.taken = {name for root in (*_RESERVED, *roots) for name in (root, f"{root}Type")}
        self.union_members: dict[str, tuple[str, ...]] = {}
        self.compiling_recursive = False
        self.explicit_suspends = 0

    # ---------------------------------------------------------------- names

    def identifier(self, ref: str) -> str:
        known = self.identifiers.get(ref)
        if known is None:
            known = self.identifiers[ref] = self.fresh(ref)
        return known

    def fresh(self, seed: str) -> str:
        sanitized = sanitize_identifier(seed)
        candidate = sanitized
        suffix = 0
        while (
            candidate in self.taken
            or f"{candidate}Type" in self.taken
            or keyword.iskeyword(candidate)
        ):
            suffix += 1
            candidate = f"{sanitized}{suffix}"
        self.taken |= {candidate, f"{candidate}Type"}
        return candidate

    def union_type(self, members: Sequence[str]) -> str:
        """``members`` joined, each once: ``None | None`` raises when evaluated."""
        flat = (m for member in members for m in self.union_members.get(member, (member,)))
        unique = tuple(dict.fromkeys(flat))
        out = " | ".join(unique)
        if len(unique) > 1:
            self.union_members[out] = unique
        return out

    def add_import(self, declaration: str) -> None:
        artifact = ImportArtifact(declaration)
        if artifact not in self.artifacts:
            self.artifacts.append(artifact)

    def typing(self, name: str) -> str:
        self.add_import(f"{_TYPING}{name}")
        return name

    # --------------------------------------------------------------- checks

    def check(self, check: R.Check, path: Path) -> str:
        identity = check.representation
        schemas = tuple(
            self.recur(schema, (*path, "representation", "schemas", i))
            for i, schema in enumerate((identity.schemas or ()) if identity else ())
        )
        generated = self.generated_check(check, schemas)
        if generated is not None:
            for declaration in generated.imports:
                self.add_import(declaration)
            runtime = generated.runtime
        elif isinstance(check, R.FilterGroup):
            children = (self.check(c, (*path, "checks", i)) for i, c in enumerate(check.checks))
            runtime = f"S.make_filter_group({', '.join(children)})"
        else:
            raise error_with_path("Missing to_code callback", (*path, "annotations", "to_code"))
        runtime += _annotate(check.annotations)
        if isinstance(check, R.Filter) and check.aborted:
            runtime += ".abort()"
        return runtime

    def generated_check(self, check: R.Check, schemas: tuple[Code, ...]) -> GeneratedCheck | None:
        callback = (check.annotations or {}).get("to_code")
        if callable(callback):
            make = cast("Callable[[CheckCodeInput], GeneratedCheck]", callback)
            return make(CheckCodeInput(schemas))
        identity = check.representation
        return None if identity is None else check_code(identity.id, identity.payload, schemas)

    # ---------------------------------------------------------------- nodes

    def recur(self, node: R.Representation, path: Path) -> Code:
        if isinstance(node, R.Reference):
            return self.reference(node, path)
        base = self.on(node, path)
        runtime = base.runtime + _annotate(node.annotations)
        checks: tuple[R.Check, ...] = getattr(node, "checks", ())
        for index, check in enumerate(checks):
            compiled = self.check(check, (*path, "checks", index))
            runtime = (
                "S.Finite"
                if runtime == "S.Number" and compiled == _FINITE
                else f"{runtime}.check({compiled})"
            )
        return Code(runtime, base.type)

    def reference(self, node: R.Reference, path: Path) -> Code:
        if node.ref not in self.document.references:
            raise error_with_path(f"Invalid reference {node.ref}", (*path, "ref"))
        identifier = self.identifier(node.ref)
        type = f"{identifier}Type"
        recursive = node.ref in self.sorted.recursives
        if self.compiling_recursive and not self.explicit_suspends and recursive:
            return Code(f"S.suspend(lambda: {identifier})", type)
        return Code(identifier, type)

    def on(self, node: R.Representation, path: Path) -> Code:  # noqa: PLR0911, PLR0912
        match node:
            case R.Declaration():
                return self.declaration(node, path)
            case R.Suspend(thunk=thunk):
                self.explicit_suspends += 1
                inner = self.recur(thunk, (*path, "thunk"))
                self.explicit_suspends -= 1
                return Code(f"S.suspend(lambda: {inner.runtime})", inner.type)
            case R.Null():
                return Code("S.Null", "None")
            case R.Never():
                return Code("S.Never", self.typing("Never"))
            case R.Unknown():
                return Code("S.Unknown", "object")
            case R.Any():
                return Code("S.Any", self.typing("Any"))
            case R.String():
                return Code("S.String", "str")
            case R.Number():
                return Code("S.Number", "float")
            case R.Boolean():
                return Code("S.Boolean", "bool")
            case R.BigInt():
                return Code("S.BigInt", "int")
            case R.Literal(literal=literal):
                self.typing("Literal")
                return Code(f"S.Literal({value_literal(literal)})", _literal_type(literal))
            case R.Enum(enums=enums):
                return self.enum(enums)
            case R.TemplateLiteral(parts=parts):
                codes = (self.recur(p, (*path, "parts", i)) for i, p in enumerate(parts))
                return Code(f"S.TemplateLiteral({', '.join(c.runtime for c in codes)})", "str")
            case R.Arrays():
                return self.arrays(node, path)
            case R.Objects():
                return self.objects(node, path)
            case R.Union():
                return self.union(node, path)
            case _:
                raise TypeError(f"Cannot generate code for {node!r}")

    def declaration(self, node: R.Declaration, path: Path) -> Code:
        parameters = tuple(
            self.recur(t, (*path, "type_parameters", i)) for i, t in enumerate(node.type_parameters)
        )
        callback = (node.annotations or {}).get("to_code")
        identity = node.representation
        generated: GeneratedDeclaration | None = None
        if callable(callback):
            make = cast("Callable[[DeclarationCodeInput], GeneratedDeclaration]", callback)
            generated = make(DeclarationCodeInput(parameters))
        elif identity is not None:
            generated = declaration_code(identity.id, identity.payload, parameters)
        if generated is None:
            raise error_with_path("Missing to_code callback", (*path, "annotations", "to_code"))
        for declaration in generated.imports:
            self.add_import(declaration)
        return Code(generated.runtime, generated.type)

    def enum(self, enums: Sequence[tuple[str, R.EnumValue]]) -> Code:
        self.add_import("import enum")
        identifier = self.fresh("_Enum")
        members = ", ".join(f"{string_literal(n)}: {value_literal(v)}" for n, v in enums)
        define = f"{identifier} = enum.Enum({string_literal(identifier)}, {{{members}}})"
        self.artifacts.append(EnumArtifact(identifier, Code(define, f"type[{identifier}]")))
        return Code(f"S.Enum({identifier})", identifier)

    def arrays(self, node: R.Arrays, path: Path) -> Code:
        elements: list[Code] = []
        for index, element in enumerate(node.elements):
            type = self.recur(element.type, (*path, "elements", index, "type"))
            runtime = f"S.optional_key({type.runtime})" if element.is_optional else type.runtime
            elements.append(
                Code(runtime + _annotate(element.annotations, "annotate_key"), type.type)
            )
        rest = [self.recur(r, (*path, "rest", i)) for i, r in enumerate(node.rest)]
        required = [
            code.type
            for code, element in zip(elements, node.elements, strict=True)
            if not element.is_optional
        ]
        optional = [
            code.type
            for code, element in zip(elements, node.elements, strict=True)
            if element.is_optional
        ]
        runtimes = ", ".join(code.runtime for code in elements)
        if len(rest) == 1 and not elements:
            return Code(f"S.Array({rest[0].runtime})", f"tuple[{rest[0].type}, ...]")
        unbounded = [*optional, *(r.type for r in rest[:1])]
        tail = f"*tuple[{self.union_type(unbounded)}, ...]" if unbounded else None
        post = [r.type for r in rest[1:]]
        parts = [*required, *([tail] if tail else []), *post]
        type = f"tuple[{', '.join(parts)}]" if parts else "tuple[()]"
        if not rest:
            return Code(f"S.Tuple({runtimes})", type)
        return Code(
            f"S.TupleWithRest(S.Tuple({runtimes}), {', '.join(r.runtime for r in rest)})", type
        )

    def objects(self, node: R.Objects, path: Path) -> Code:
        keys: list[tuple[str, str]] = []
        fields: list[tuple[str, str]] = []
        for index, p in enumerate(node.property_signatures):
            if not isinstance(p.name, str):
                raise error_with_path(
                    "A generated struct has string keys",
                    (*path, "property_signatures", index, "name"),
                )
            type = self.recur(p.type, (*path, "property_signatures", index, "type"))
            hint = f"{self.typing('NotRequired')}[{type.type}]" if p.is_optional else type.type
            keys.append((p.name, hint))
            fields.append((p.name, type.runtime + _annotate(p.annotations, "annotate_key")))
        records = [
            (
                self.recur(s.parameter, (*path, "index_signatures", i, "parameter")),
                self.recur(s.type, (*path, "index_signatures", i, "type")),
            )
            for i, s in enumerate(node.index_signatures)
        ]
        record_codes = [
            Code(f"S.Record({k.runtime}, {v.runtime})", f"dict[{k.type}, {v.type}]")
            for k, v in records
        ]
        if not keys and len(record_codes) == 1:
            return record_codes[0]
        struct = self.struct(keys, fields)
        if not record_codes:
            return struct
        rests = ", ".join(r.runtime for r in record_codes)
        return Code(f"S.StructWithRest({struct.runtime}, {rests})", struct.type)

    def struct(self, keys: Sequence[tuple[str, str]], fields: Sequence[tuple[str, str]]) -> Code:
        identifier = self.fresh("_Struct")
        typed_dict = self.typing("TypedDict")
        entries = ", ".join(f"{string_literal(name)}: {hint}" for name, hint in keys)
        define = f"{identifier} = {typed_dict}({string_literal(identifier)}, {{{entries}}})"
        self.artifacts.append(TypedDictArtifact(identifier, Code(define, f"type[{identifier}]")))
        arguments = _keywords(fields)
        return Code(
            f"S.Struct({identifier}{', ' if arguments else ''}{arguments})",
            identifier,
        )

    def union(self, node: R.Union, path: Path) -> Code:
        one_of = node.mode == "one_of"
        if not one_of and not node.types:
            return Code("S.Never", self.typing("Never"))
        if not one_of and all(_is_simple_literal(t) for t in node.types):
            literals = [cast("R.Literal", t).literal for t in node.types]
            self.typing("Literal")
            types = self.union_type([_literal_type(value) for value in literals])
            rendered = [cast("str", value_literal(value)) for value in literals]
            if len(rendered) == 1:
                return Code(f"S.Literal({rendered[0]})", types)
            return Code(f"S.Literals([{', '.join(rendered)}])", types)
        codes = [self.recur(t, (*path, "types", i)) for i, t in enumerate(node.types)]
        mode = ', mode="one_of"' if one_of else ""
        return Code(
            f"S.Union([{', '.join(c.runtime for c in codes)}]{mode})",
            self.union_type([c.type for c in codes]) or self.typing("Never"),
        )


def to_code_document(document: R.MultiDocument, /) -> CodeDocument:
    """Python source for ``document``'s schemas: an expression and a type for each
    root and each reference, and the artifacts they use. A check or declaration
    pyfect does not know gives its source through a ``to_code`` annotation
    (``GeneratedCheck`` / ``GeneratedDeclaration``); without one this raises
    ``RepresentationError``. ``S.Int`` is written ``S.Number.check(S.is_int())``,
    which it is in a document: it then accepts ``1.0`` too."""
    generator = _Generator(document)
    sorted = generator.sorted
    for ref, _ in sorted.non_recursives:
        generator.identifier(ref)
    for ref in sorted.recursives:
        generator.identifier(ref)
    non_recursives = tuple(
        NamedCode(generator.identifier(ref), generator.recur(node, ("references", ref)))
        for ref, node in sorted.non_recursives
    )
    recursives: dict[str, Code] = {}
    for ref, node in sorted.recursives.items():
        generator.compiling_recursive = True
        recursives[generator.identifier(ref)] = generator.recur(node, ("references", ref))
        generator.compiling_recursive = False
    first, *rest = (
        generator.recur(node, ("representations", i))
        for i, node in enumerate(document.representations)
    )
    return CodeDocument(
        (first, *rest),
        CodeReferences(non_recursives, recursives),
        tuple(generator.artifacts),
    )


def _defined_names(document: CodeDocument) -> set[str]:
    references = document.references
    identifiers = [named.identifier for named in references.non_recursives]
    identifiers += list(references.recursives)
    identifiers += [
        artifact.identifier
        for artifact in document.artifacts
        if isinstance(artifact, TypedDictArtifact | EnumArtifact)
    ]
    return {name for identifier in identifiers for name in (identifier, f"{identifier}Type")}


def _check_root_names(names: Sequence[str], document: CodeDocument) -> None:
    taken = _RESERVED | _defined_names(document)
    for index, name in enumerate(names):
        if (
            not name.isidentifier()
            or keyword.iskeyword(name)
            or name in taken
            or name in names[:index]
        ):
            raise ValueError(f"A module cannot have the root name {name!r}")


def _imports(artifacts: Sequence[Artifact], body: str) -> list[str]:
    """The import lines ``body`` needs: a type the module's aliases do not write
    (a record's in a struct with a rest) would be an unused import."""
    typing_names: set[str] = set()
    lines: set[str] = set()
    for artifact in artifacts:
        if isinstance(artifact, ImportArtifact):
            line = artifact.declaration
            if line.startswith(_TYPING):
                typing_names.add(line.removeprefix(_TYPING))
            else:
                lines.add(line)
    used = {
        name for name in typing_names | {"Any"} if re.search(rf"(?<![.\w]){name}\b", body, re.ASCII)
    }
    plain = sorted(line for line in lines if line.startswith("import "))
    froms = sorted(line for line in lines if not line.startswith("import "))
    if used:
        froms.insert(0, f"{_TYPING}{', '.join(sorted(used))}")
    return [*plain, *froms]


def to_code_module(document: CodeDocument, /, *, names: Sequence[str] = ()) -> str:
    """``document`` as one module: imports, type aliases (they may refer to each
    other), artifacts, references in order, then a variable for each root, named by
    ``names`` (``Schema0``, ... by default). Run it, or check it with pyright."""
    _check_root_names(names, document)
    root_names = [names[i] if i < len(names) else f"Schema{i}" for i in range(len(document.codes))]
    recursives = document.references.recursives
    non_recursives = document.references.non_recursives
    lines = [f"type {named.identifier}Type = {named.code.type}" for named in non_recursives]
    lines += [f"type {identifier}Type = {code.type}" for identifier, code in recursives.items()]
    lines += [
        f"type {name}Type = {code.type}"
        for name, code in zip(root_names, document.codes, strict=True)
    ]
    lines += [
        artifact.code.runtime
        for artifact in document.artifacts
        if isinstance(artifact, TypedDictArtifact | EnumArtifact)
    ]
    lines += [f"{named.identifier} = {named.code.runtime}" for named in non_recursives]
    lines += [
        f"{identifier}: S.Bottom[{identifier}Type, Any, Any, Any] = {code.runtime}"
        for identifier, code in recursives.items()
    ]
    lines += [
        f"{name} = {code.runtime}" for name, code in zip(root_names, document.codes, strict=True)
    ]
    body = "\n".join(lines) + "\n"
    header = [
        "from __future__ import annotations",
        "",
        *_imports(document.artifacts, body),
        "",
        "from pyfect import schema as S",
        "",
    ]
    return "\n".join(header) + "\n" + body
