"""Python source for an AST's fast paths (Effect's internal ``codegen``).

``generate(ast, operation)`` gives the body of a factory
``(ast, R, resolve) -> operation`` (``R`` is ``runtime``), or ``None`` when the
operation is not generated for that AST. ``is`` and ``decode`` are
straight-line validators of a subtree without transformations,
declarations, suspensions or classes; they answer ``False`` / ``INVALID``
instead of building issues. ``make`` is ``decode`` for a fixed struct or a
homogeneous array without unions, records or constructor defaults.
``decode_effect`` and ``make_effect`` use the runtime's complete parsers.

Constants are read from the AST at install time through their paths
(``ast.properties[0].type``), never serialized, so an ahead-of-time module
built from this source needs no code generation at run time.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from typing import Final, Literal, cast

from pyfect.schema.ast import (
    AST,
    Any,
    Arrays,
    BigInt,
    Boolean,
    Class,
    Declaration,
    Never,
    Null,
    Number,
    Objects,
    String,
    Suspend,
    Union,
    Unknown,
)
from pyfect.schema.ast import (
    Literal as LiteralNode,
)
from pyfect.schema.compiler._registry import DecoderOperation
from pyfect.schema.getter import Transform
from pyfect.schema.transformation import Transformation

MAX_GENERATED_DEPTH: Final = 256
MAX_GENERATED_NODES: Final = 2048

type _Operation = Literal["decode", "is"]


@dataclass(slots=True)
class _Facts:
    supported: bool = True
    output_free: bool = True
    make_safe: bool = True
    nodes: int = 1
    height: int = 0


_UNSUPPORTED: Final = _Facts(supported=False, output_free=False, make_safe=False)


def _blocks(ast: AST) -> bool:
    """A node no fast path goes through: a transformation, a declaration, a
    suspension or a class."""
    return ast.encoding is not None or isinstance(ast, (Declaration, Suspend, Class))


def _children(ast: AST) -> list[AST] | None:
    """The nodes a composite's fast path visits; ``None`` for a leaf or a
    struct that cannot have one (a field with a default)."""
    match ast:
        case Arrays():
            return [e.type for e in ast.elements] + list(ast.rest)
        case Objects():
            if any(p.default is not None for p in ast.properties):
                return None
            out = [p.type for p in ast.properties]
            for index in ast.index_signatures:
                out += [index.parameter, index.type]
            return out
        case Union():
            return list(ast.types)
        case _:
            return []


def _make_safe_node(ast: AST) -> bool:
    return (
        not isinstance(ast, (Union, Declaration, Suspend, Class))
        and not (isinstance(ast, Objects) and ast.index_signatures)
        and ast.encoding is None
        and ast.constructor_default is None
    )


@dataclass(slots=True)
class _Budget:
    remaining: int = MAX_GENERATED_NODES


def _facts_of(  # noqa: PLR0911 - one exit per budget or support outcome
    ast: AST, depth: int = 0, budget: _Budget | None = None
) -> _Facts | None:
    """What a fast path through ``ast`` needs; ``None`` when it exceeds the
    depth or node budget here (Effect's ``getFacts``)."""
    budget = budget or _Budget()
    if ast.compiler_facts:
        facts = cast("_Facts", ast.compiler_facts[0])
        budget.remaining -= facts.nodes
        if budget.remaining < 0 or depth + facts.height > MAX_GENERATED_DEPTH:
            return None
        return facts
    budget.remaining -= 1
    if budget.remaining < 0 or depth > MAX_GENERATED_DEPTH:
        return None
    children = _children(ast)
    facts = _Facts()
    if children is None:
        return _stop(ast)
    for child in children:
        if _blocks(child):
            return _stop(ast)
        if isinstance(child, (Arrays, Objects, Union)):
            sub = _facts_of(child, depth + 1, budget)
            if sub is None:
                return None
            if not sub.supported:
                return _stop(ast)
            facts.output_free = facts.output_free and sub.output_free
            facts.make_safe = facts.make_safe and sub.make_safe
            facts.nodes += sub.nodes
            facts.height = max(facts.height, sub.height + 1)
        else:
            budget.remaining -= 1
            if budget.remaining < 0 or depth + 1 > MAX_GENERATED_DEPTH:
                return None
            facts.make_safe = facts.make_safe and _make_safe_node(child)
            facts.nodes += 1
            facts.height = max(facts.height, 1)
    if isinstance(ast, (Arrays, Objects, Union)):
        facts.output_free = ast.checks is None and facts.output_free
    facts.make_safe = facts.make_safe and _make_safe_node(ast)
    ast.compiler_facts.append(facts)
    return facts


def _stop(ast: AST) -> _Facts:
    ast.compiler_facts.append(_UNSUPPORTED)
    return _UNSUPPORTED


def emission(ast: AST, local: bool = False) -> Literal["unsupported", "decode", "is"]:
    """Which fast paths ``ast`` can have (``local``: ignoring its encoding)."""
    if (not local and ast.encoding is not None) or isinstance(ast, (Declaration, Suspend, Class)):
        return "unsupported"
    facts = _facts_of(ast)
    if facts is None or not facts.supported:
        return "unsupported"
    return "is" if facts.output_free else "decode"


def should_compile_parser(ast: AST) -> bool:
    """Whether compiling ``ast`` can beat the interpreter (Effect's
    ``shouldCompileParser``)."""
    if ast.encoding is not None or ast.checks is not None or ast.encoding_checks is not None:
        return True
    if isinstance(ast, Class) and ast.side == "type":
        return True
    return isinstance(ast, (Arrays, Objects, Union)) or ast.tag == "TemplateLiteral"


def _make_safe(ast: AST) -> bool:
    facts = _facts_of(ast)
    return facts is not None and facts.make_safe


def should_compile_make(ast: AST) -> bool:
    shaped = (isinstance(ast, Arrays) and not ast.elements and len(ast.rest) == 1) or (
        isinstance(ast, Objects) and bool(ast.properties) and not ast.index_signatures
    )
    return shaped and _make_safe(ast)


# ------------------------------------------------------------------ emitter


@dataclass(slots=True)
class _Emitter:
    operation: _Operation
    helpers: list[str] = field(default_factory=list[str])
    names: dict[int, str] = field(default_factory=dict[int, str])
    constants: list[str] = field(default_factory=list[str])
    constant_index: dict[str, int] = field(default_factory=dict[str, int])
    bound: set[str] = field(default_factory=set[str])
    """The ``C[n]`` expressions already handed out."""
    next: int = 0

    @property
    def fail(self) -> str:
        return "return I" if self.operation == "decode" else "return False"

    def var(self) -> str:
        self.next += 1
        return f"v{self.next}"

    def constant(self, reference: str) -> str:
        """``C[n]``, bound once to ``reference`` (a path from ``ast`` or from
        an earlier constant, so no expression nests deeper than a node)."""
        if reference in self.bound:
            return reference
        index = self.constant_index.get(reference)
        if index is None:
            index = self.constant_index[reference] = len(self.constants)
            self.constants.append(reference)
        bound = f"C[{index}]"
        self.bound.add(bound)
        return bound


def _literal_source(value: object) -> str | None:
    """A literal key or value as Python source, when its ``repr`` is one."""
    if value is None or isinstance(value, (bool, int, str)):
        return repr(value)
    if isinstance(value, float):
        return f"float({str(value)!r})"
    return None


def _emit(ast: AST, v: str, path: str, e: _Emitter) -> tuple[list[str], str]:
    """Statements checking ``v`` against ``ast`` (returning on failure) and
    the expression of its output."""
    lines, out = _emit_base(ast, v, path, e)
    if ast.encoding_checks is not None:
        lines.append(f"if K({e.constant(path)}, {v}, True, o): {e.fail}")
    if ast.checks is None:
        return lines, out
    checked = e.var()
    lines += [f"{checked} = {out}", f"if K({e.constant(path)}, {checked}, False, o): {e.fail}"]
    return lines, checked


def _type_test(ast: AST, v: str) -> str | None:  # noqa: PLR0911, PLR0912 - one case per leaf
    """A Python expression true when ``v`` is a value of leaf ``ast``."""
    match ast:
        case Never():
            return "False"
        case Any() | Unknown():
            return "True"
        case Null():
            return f"{v} is None"
        case String():
            return f"isinstance({v}, str)"
        case Number():
            return f"(isinstance({v}, (int, float)) and not isinstance({v}, bool))"
        case Boolean():
            return f"isinstance({v}, bool)"
        case BigInt():
            return f"(isinstance({v}, int) and not isinstance({v}, bool))"
        case LiteralNode(literal=literal):
            source = _literal_source(literal)
            if source is None:
                return None
            match literal:
                case None:
                    return f"{v} is None"
                case bool():
                    return f"(isinstance({v}, bool) and {v} == {source})"
                case int() | float():
                    return (
                        f"(isinstance({v}, (int, float)) and not isinstance({v}, bool)"
                        f" and {v} == {source})"
                    )
                case str():
                    return f"(isinstance({v}, str) and {v} == {source})"
        case _:
            return None


def _emit_base(ast: AST, v: str, path: str, e: _Emitter) -> tuple[list[str], str]:
    if isinstance(ast, (Arrays, Objects, Union)):
        if isinstance(ast, Objects) and not ast.properties and not ast.index_signatures:
            return [f"if {v} is None or isinstance({v}, R.NotAnObject): {e.fail}"], v
        helper = _helper(ast, path, e)
        if e.operation == "is":
            return [f"if not {helper}({v}, o): return False"], v
        out = e.var()
        return [f"{out} = {helper}({v}, o)", f"if {out} is I: return I"], out
    test = _type_test(ast, v)
    if test is not None:
        lines = [f"if not ({test}): {e.fail}"]
        if isinstance(ast, Number) and ast.whole:
            out = e.var()
            lines.append(
                f"{out} = int({v}) if isinstance({v}, float) and {v}.is_integer() else {v}"
            )
            return lines, out
        return lines, v
    # Any other leaf (an enum, a template literal) runs its own parse.
    out = e.var()
    return [f"{out} = L({e.constant(path)}, {v}, o)", f"if {out} is I: {e.fail}"], out


def _helper(ast: Arrays | Objects | Union, path: str, e: _Emitter) -> str:
    name = e.names.get(id(ast))
    if name is not None:
        return name
    e.next += 1
    name = e.names[id(ast)] = f"h{e.next}"
    # Its parts' paths start from this node's constant.
    path = e.constant(path)
    match ast:
        case Objects():
            body = _objects(ast, path, e)
        case Arrays():
            body = _arrays(ast, path, e)
        case Union():
            body = _union(ast, path, e)
    e.helpers.append("\n".join([f"def {name}(i, o):", *(f"    {line}" for line in body)]))
    return name


def _indent(lines: list[str], by: int = 1) -> list[str]:
    return [("    " * by) + line for line in lines]


def _key(name: object, path: str, e: _Emitter) -> str:
    source = _literal_source(name) if isinstance(name, (str, int)) else None
    return source if source is not None else e.constant(path)


def _objects(ast: Objects, path: str, e: _Emitter) -> list[str]:
    decode = e.operation == "decode"
    me = e.constant(path)
    lines = [
        "if type(i) is dict:",
        "    m = i",
        "else:",
        "    m = R.keys_of(i)",
        f"    if m is None: {e.fail}",
    ]
    if ast.index_signatures:
        # Strict parsing lists the keys once, before any property is read;
        # otherwise they are listed after the properties (as the interpreter).
        lines.append(
            f"entries = R.index_entries({me}, m, o)"
            " if o.get('on_excess_property') == 'error' else None"
        )
    lines.append(
        f"if o.get('on_excess_property') == 'error' and R.has_excess({me}, m, o): {e.fail}"
    )
    if decode:
        lines.append("out = {}")
    for n, prop in enumerate(ast.properties):
        prop_path = f"{path}.properties[{n}]"
        key = _key(prop.name, f"{prop_path}.name", e)
        value = e.var()
        child, decoded = _emit(prop.type, value, f"{prop_path}.type", e)
        present = [f"{value} = m[{key}]", *child]
        if decode:
            present.append(f"out[{key}] = {decoded}")
        lines.append(f"if {key} in m:")
        lines += _indent(present)
        if not prop.optional:
            lines.append(f"else: {e.fail}")
    declared = (
        e.constant(f"R.declared({path})") if ast.properties and ast.index_signatures else None
    )
    if ast.index_signatures:
        lines.append(f"if entries is None: entries = R.index_entries({me}, m, o)")
    for n, index in enumerate(ast.index_signatures):
        index_path = f"{path}.index_signatures[{n}]"
        k = e.var()
        value = e.var()
        key_lines, decoded_key = _emit(index.parameter, k, f"{index_path}.parameter", e)
        value_lines, decoded = _emit(index.type, value, f"{index_path}.type", e)
        body = [*key_lines, f"{value} = m[{k}]", *value_lines]
        if decode:
            assign = f"out[{decoded_key}] = {decoded}"
            if declared is not None:
                body.append(f"if {k} not in {declared} and {decoded_key} not in {declared}:")
                body.append(f"    {assign}")
            else:
                body.append(assign)
        lines.append(f"for {k} in entries[{n}]:")
        lines += _indent(body)
    lines.append("return out" if decode else "return True")
    return lines


def _arrays(ast: Arrays, path: str, e: _Emitter) -> list[str]:
    decode = e.operation == "decode"
    count = len(ast.elements)
    optional = [el.optional for el in ast.elements]
    required = optional.index(True) if True in optional else count
    tail = max(0, len(ast.rest) - 1)
    lines = [f"if not isinstance(i, (list, tuple)): {e.fail}", "n = len(i)"]
    if not ast.rest:
        lines.append(f"if n > {count}: {e.fail}")
    lines.append(f"if n < {required + tail}: {e.fail}")
    if decode:
        lines.append("out = []")

    def position(index_source: str, node: AST, node_path: str) -> list[str]:
        value = e.var()
        child, decoded = _emit(node, value, node_path, e)
        body = [f"{value} = i[{index_source}]", *child]
        if decode:
            body.append(f"out.append({decoded})")
        return body

    for index, element in enumerate(ast.elements):
        body = position(str(index), element.type, f"{path}.elements[{index}].type")
        if index < required:
            lines += body
        else:
            lines.append(f"if {index} < n:")
            lines += _indent(body)
    if ast.rest:
        j = e.var()
        lines.append(f"for {j} in range({count}, n - {tail}):")
        lines += _indent(position(j, ast.rest[0], f"{path}.rest[0]"))
        for t in range(tail):
            lines += position(f"n - {tail - t}", ast.rest[t + 1], f"{path}.rest[{t + 1}]")
    if decode:
        lines.append("return out" if ast.mutable else "return tuple(out)")
    else:
        lines.append("return True")
    return lines


def _member(ast: AST, path: str, e: _Emitter) -> str:
    """A helper function parsing one union member."""
    if (
        isinstance(ast, (Arrays, Objects, Union))
        and not (isinstance(ast, Objects) and not ast.properties and not ast.index_signatures)
        and ast.checks is None
        and ast.encoding_checks is None
    ):
        return _helper(ast, path, e)
    e.next += 1
    name = f"h{e.next}"
    lines, out = _emit(ast, "i", path, e)
    result = out if e.operation == "decode" else "True"
    e.helpers.append("\n".join([f"def {name}(i, o):", *_indent([*lines, f"return {result}"])]))
    return name


def _union(ast: Union, path: str, e: _Emitter) -> list[str]:
    members = [_member(t, f"{path}.types[{n}]", e) for n, t in enumerate(ast.types)]
    table = e.var()
    e.helpers.append(f"{table} = ({', '.join(members)}{',' if len(members) == 1 else ''})")
    me = e.constant(path)
    decode = e.operation == "decode"
    if ast.mode == "any_of":
        if decode:
            return [
                f"for c in {me}.candidates(i, False):",
                f"    r = {table}[c](i, o)",
                "    if r is not I: return r",
                "return I",
            ]
        return [
            f"for c in {me}.candidates(i, False):",
            f"    if {table}[c](i, o): return True",
            "return False",
        ]
    ok = "r is not I" if decode else "r"
    return [
        "out = I" if decode else "out = True",
        "s = 0",
        f"for c in {me}.candidates(i, False):",
        f"    r = {table}[c](i, o)",
        f"    if {ok}:",
        "        s += 1",
        f"        if s > 1: {e.fail}",
        "        out = r",
        f"if s != 1: {e.fail}",
        "return out",
    ]


def _render(ast: AST, operation: _Operation, path: str = "ast") -> list[str]:
    """A factory body returning the generated operation of ``ast``."""
    e = _Emitter(operation)
    lines, out = _emit(ast, "i", path, e)
    result = out if operation == "decode" else "True"
    root = ["def run(i, o):", *_indent([*lines, f"return {result}"])]
    return [
        "I = R.INVALID",
        "K = R.check_issues",
        "L = R.local_value",
        "C = []",
        *(f"C.append({reference})" for reference in e.constants),
        *"\n".join(e.helpers).splitlines(),
        *root,
        "return run",
    ]


def _encoding(ast: AST) -> str | None:
    """A complete decoder for one ``transform`` from a leaf to a leaf, its
    source parsed and checked inline, once (Effect's ``emitEncoding``)."""
    links = ast.encoding
    if links is None or len(links) != 1 or ast.encoding_checks is not None:
        return None
    link = links[0]
    source = link.to
    if (
        source.encoding is not None
        or source.encoding_checks is not None
        or not isinstance(link.transformation, Transformation)
        or not isinstance(link.transformation.decode, Transform)  # pyright: ignore[reportUnknownMemberType]
        or (isinstance(ast, Number) and ast.whole)
        or (isinstance(source, Number) and source.whole)
    ):
        return None
    source_test = _type_test(source, "i")
    target_test = _type_test(ast, "value")
    if source_test is None or target_test is None:
        return None
    source_checks = (
        []
        if source.checks is None
        else [
            "issues = R.issues_of(source, i, o)",
            "if issues is not None: return R.invalid_source(ast, i, issues, o)",
        ]
    )
    target_checks = (
        []
        if ast.checks is None
        else [
            "issues = R.issues_of(ast, value, o)",
            "if issues is not None: return R.invalid_target(ast, value, issues, o)",
        ]
    )
    body = [
        "if i is R.MISSING: return R.MISSING_EXIT",
        f"if not ({source_test}): return R.invalid_source(ast, i, None, o)",
        *source_checks,
        "value = transform(i)",
        "if value is R.MISSING: return R.MISSING_EXIT",
        f"if not ({target_test}): return R.invalid_target(ast, value, None, o)",
        *target_checks,
        "return R.Success(value)",
    ]
    return "\n".join(
        [
            "source = ast.encoding[0].to",
            "transform = ast.encoding[0].transformation.decode.f",
            "def run(i, o):",
            "    try:",
            *_indent(body, 2),
            "    except Exception as defect:",
            "        return R.die_exit(defect)",
            "return run",
        ]
    )


_EMIT_FRAMES: Final = 8
"""Python frames the emitter spends per nesting level, at most."""


def generate(ast: AST, operation: DecoderOperation) -> str | None:
    """The body of a factory ``(ast, R, resolve)`` making ``operation`` for
    ``ast``, or ``None`` when it is not generated (Effect's ``generate``)."""
    # The emitter recurses per level, up to ``MAX_GENERATED_DEPTH`` levels,
    # on top of the caller's stack.
    limit = sys.getrecursionlimit()
    sys.setrecursionlimit(limit + MAX_GENERATED_DEPTH * _EMIT_FRAMES)
    try:
        return _generate(ast, operation)
    finally:
        sys.setrecursionlimit(limit)


def _generate(ast: AST, operation: DecoderOperation) -> str | None:  # noqa: PLR0911 - one exit per operation
    if operation == "make":
        if not should_compile_make(ast):
            return None
        if isinstance(ast, Objects):
            return "\n".join(
                [
                    "if any(resolve(p.type).compiled is not None for p in ast.properties):",
                    "    return None",
                    *_render(ast, "decode"),
                ]
            )
        element = "\n".join(
            [
                "def element(R):",
                *_indent(
                    _render(
                        ast.rest[0] if isinstance(ast, Arrays) else ast, "decode", "ast.rest[0]"
                    )
                ),
            ]
        )
        return "\n".join(
            [
                element,
                "child = resolve(ast.rest[0])",
                "m = element(R) if child.compiled is None else child.make",
                "if m is None:",
                "    return None",
                "return R.array_maker(ast, m)",
            ]
        )
    if operation in ("is", "decode"):
        if not should_compile_parser(ast):
            return None
        kind = emission(ast)
        if kind == "unsupported" or (operation == "is" and kind != "is"):
            return None
        return "\n".join(_render(ast, operation))
    if operation == "decode_effect":
        inline = _encoding(ast)
        if inline is not None:
            return inline
        detailed = emission(ast) != "unsupported"
        return f"return R.decode(ast, resolve, {detailed})"
    return "return R.make(ast, resolve)"
