"""What generated schema operations call (Effect's
``SchemaCompiler/runtime``). It holds no code generation, so a module the
ahead-of-time compiler wrote runs on it alone. Generated modules must come
from the same pyfect version.
"""

from __future__ import annotations

from collections.abc import Callable, Hashable, Mapping
from typing import Any, cast

from pyfect.exit import Success
from pyfect.exit import die as die_exit
from pyfect.exit import fail as fail_exit
from pyfect.schema._options import ParseOptions
from pyfect.schema.ast import (
    AST,
    Arrays,
    BigInt,
    Boolean,
    Never,
    Null,
    Number,
    Objects,
    String,
    Unknown,
    collect_issues,
)
from pyfect.schema.ast import Any as AnyNode
from pyfect.schema.ast import Literal as LiteralNode
from pyfect.schema.ast._encoding import Encoding
from pyfect.schema.ast._literal import same_literal
from pyfect.schema.ast._objects import ObjectKeys, reads_properties
from pyfect.schema.ast._result import MISSING, MISSING_EXIT, NotAnObject, ParseResult
from pyfect.schema.compiler._registry import (
    DEFAULT_PARSE_OPTIONS,
    INVALID,
    Entry,
    Make,
    Parser,
    Resolve,
    interpreter,
    resolve,
    set_compiler,
)
from pyfect.schema.getter import Passthrough, Transform
from pyfect.schema.issue import Composite, InvalidType, reported
from pyfect.schema.issue import Encoding as EncodingIssue
from pyfect.schema.transformation import Transformation

__all__ = [
    "DEFAULT_PARSE_OPTIONS",
    "INVALID",
    "MISSING",
    "MISSING_EXIT",
    "NotAnObject",
    "Success",
    "array_maker",
    "check_issues",
    "declared",
    "decode",
    "die_exit",
    "has_excess",
    "index_entries",
    "invalid_source",
    "invalid_target",
    "issues_of",
    "keys_of",
    "local_value",
    "make",
    "resolve",
    "set_compiler",
]


def keys_of(input: object) -> Mapping[object, object] | None:
    """``input`` read as keys, as a struct reads it (``None``: not an object)."""
    if isinstance(input, Mapping):
        return cast("Mapping[object, object]", input)
    if reads_properties(input):
        return ObjectKeys(input)
    return None


def check_issues(ast: AST, value: object, encoded: bool, options: ParseOptions) -> bool:
    """``ast``'s checks (its encoding checks when ``encoded``) fail on ``value``."""
    checks = ast.encoding_checks if encoded else ast.checks
    if checks is None or options.get("disable_checks"):
        return False
    return collect_issues(checks, value, ast, options) is not None


def local_value(ast: AST, value: object, options: ParseOptions) -> object:
    """``value`` parsed by leaf ``ast`` and its checks, or ``INVALID``."""
    result = ast.parse_local(value, options)
    return result.value if type(result) is Success else INVALID


def index_entries(
    ast: Objects, keys: Mapping[object, object], options: ParseOptions
) -> list[list[object]]:
    """The keys each index signature takes, read before any property, as
    the interpreter reads them."""
    return [[key for key in keys if index.selects(key, options)] for index in ast.index_signatures]


def has_excess(ast: Objects, keys: Mapping[object, object], options: ParseOptions) -> bool:
    """``keys`` holds a key no property declares and no index signature takes."""
    declared = {p.name for p in ast.properties}
    return any(
        key not in declared and not any(i.selects(key, options) for i in ast.index_signatures)
        for key in keys
    )


def declared(ast: Objects) -> frozenset[Hashable]:
    return frozenset(p.name for p in ast.properties)


def array_maker(ast: Arrays, element: Make) -> Make:
    """A homogeneous array's synchronous constructor over ``element``'s."""

    def make(input: object, options: ParseOptions) -> object:
        if input is MISSING:
            return MISSING
        if not isinstance(input, (list, tuple)):
            return INVALID
        out: list[object] = []
        for item in cast("list[object]", input):
            value = element(item, options)
            if value is INVALID or value is MISSING:
                return INVALID
            out.append(value)
        if check_issues(ast, out, False, options):
            return INVALID
        return out if ast.mutable else tuple(out)

    return make


def decode(ast: AST, resolve_child: Resolve, detailed: bool = False) -> Parser:
    """The complete decoder of a compiled ``ast``: a single pure
    transformation between leaves inline, else the interpreter over the
    registry (``detailed``: the node's own fast path ran first, so its
    children parse in detail)."""
    inline = _encoding_decoder(ast)
    if inline is not None:
        return inline
    if isinstance(ast, Objects) and ast.properties and not ast.index_signatures:
        return interpreter(ast, _inlining(ast, resolve_child), detailed)
    return interpreter(ast, resolve_child, detailed)


def _inlining(ast: Objects, resolve_child: Resolve) -> Resolve:
    """``resolve_child`` but for a property whose single transformation
    runs inline (Effect's ``emitObject``): its entry is resolved only when
    the source value is not one the inline decoder takes."""
    inline: dict[int, Entry] = {}
    for prop in ast.properties:
        child = prop.type
        decoder = _encoding_decoder(child) or _chain_decoder(child)
        links = child.encoding
        source_test = None if links is None else _leaf_test(links[0].to)
        if decoder is not None and source_test is not None:
            inline[id(child)] = Entry(
                child,
                _InlineSource(_inline_parser(child, decoder, source_test, resolve_child)),
                False,
                resolve_child,
            )

    def scoped(child: AST) -> Entry:
        found = inline.get(id(child))
        return found if found is not None else resolve_child(child)

    return scoped if inline else resolve_child


class _InlineSource:
    __slots__ = ("decode_effect",)

    def __init__(self, decode_effect: Parser) -> None:
        self.decode_effect = decode_effect


def _inline_parser(
    child: AST, decoder: Parser, source_test: Callable[[object], bool], resolve_child: Resolve
) -> Parser:
    def parse(input: object, options: ParseOptions) -> ParseResult:
        if input is MISSING or not source_test(input):
            return resolve_child(child).parser(input, options)
        return decoder(input, options)

    return parse


def make(ast: AST, resolve_child: Resolve) -> Parser:
    """The complete constructor of ``ast`` over the registry."""
    return interpreter(ast, resolve_child)


def _leaf_test(ast: AST) -> Callable[[object], bool] | None:  # noqa: PLR0911 - one case per leaf
    match ast:
        case Never():
            return lambda _: False
        case AnyNode() | Unknown():
            return lambda _: True
        case Null():
            return lambda v: v is None
        case String():
            return lambda v: isinstance(v, str)
        case Number(whole=False):
            return lambda v: isinstance(v, (int, float)) and not isinstance(v, bool)
        case Boolean():
            return lambda v: isinstance(v, bool)
        case BigInt():
            return lambda v: isinstance(v, int) and not isinstance(v, bool)
        case LiteralNode(literal=literal):
            return lambda v: same_literal(literal, v)
        case _:
            return None


def issues_of(ast: AST, value: object, options: ParseOptions) -> Any:
    """The issues of ``ast``'s checks on ``value`` (``None``: none, or
    checks disabled), for an issue built from them without running them
    again."""
    if ast.checks is None or options.get("disable_checks"):
        return None
    return collect_issues(ast.checks, value, ast, options)


def invalid_source(ast: AST, input: object, issues: Any, options: ParseOptions) -> ParseResult:
    """``input`` is not a value of ``ast``'s single encoding source (its
    type when ``issues`` is ``None``, else its checks' ``issues``)."""
    source = cast("Encoding", ast.encoding)[0].to
    shown = reported(input, options)
    inner = InvalidType(source, shown) if issues is None else Composite(source, issues, shown)
    return fail_exit(EncodingIssue(ast, inner, shown))


def invalid_target(ast: AST, value: object, issues: Any, options: ParseOptions) -> ParseResult:
    """A transformed ``value`` is not of ``ast``'s type (``issues`` is
    ``None``) or fails its checks."""
    shown = reported(value, options)
    return fail_exit(InvalidType(ast, shown) if issues is None else Composite(ast, issues, shown))


def _chain_decoder(ast: AST) -> Parser | None:
    """A chain of ``passthrough`` / ``transform`` links between leaves, only
    its first source checked, decoded inline without parsing any node of
    the chain again (Effect's ``canInlineEncoding``)."""
    links = ast.encoding
    target_test = _leaf_test(ast)
    if (
        links is None
        or ast.checks is not None
        or ast.encoding_checks is not None
        or target_test is None
        or (isinstance(ast, Number) and ast.whole)
    ):
        return None
    steps: list[tuple[Callable[[object], object] | None, AST, Callable[[object], bool]]] = []
    for index, link in enumerate(links):
        node = link.to
        test = _leaf_test(node)
        transformation = link.transformation
        if (
            test is None
            or node.encoding is not None
            or node.encoding_checks is not None
            or (node.checks is not None and index != len(links) - 1)
            or (isinstance(node, Number) and node.whole)
            or not isinstance(transformation, Transformation)
        ):
            return None
        decode = cast("Transformation[object, object, Any, Any]", transformation).decode
        if isinstance(decode, Transform):
            steps.append((decode.f, node, test))
        elif isinstance(decode, Passthrough):
            steps.append((None, node, test))
        else:
            return None
    source = links[-1].to

    def run(input: object, options: ParseOptions) -> ParseResult:  # noqa: PLR0911 - one exit per issue
        try:
            if input is MISSING:
                return MISSING_EXIT
            shown = reported(input, options)
            if not steps[-1][2](input):
                return fail_exit(EncodingIssue(ast, InvalidType(source, shown), shown))
            issues = issues_of(source, input, options)
            if issues is not None:
                return fail_exit(EncodingIssue(ast, Composite(source, issues, shown), shown))
            value = input
            for index in range(len(steps) - 1, -1, -1):
                f = steps[index][0]
                if f is not None:
                    value = f(value)
                if value is MISSING:
                    return MISSING_EXIT
                if index:
                    _, node, test = steps[index - 1]
                    if not test(value):
                        issue = InvalidType(node, reported(value, options))
                        return fail_exit(EncodingIssue(ast, issue, shown))
            if not target_test(value):
                return fail_exit(InvalidType(ast, reported(value, options)))
            return Success(value)
        except Exception as defect:
            return die_exit(defect)

    return run


def _encoding_decoder(ast: AST) -> Parser | None:
    """Effect's ``emitEncoding``: one ``transform`` from a leaf to a leaf,
    decoded without parsing the source node again."""
    links = ast.encoding
    if links is None or len(links) != 1 or ast.encoding_checks is not None:
        return None
    link = links[0]
    source = link.to
    transformation = cast("Transformation[object, object, Any, Any]", link.transformation)
    if (
        source.encoding is not None
        or source.encoding_checks is not None
        or not isinstance(link.transformation, Transformation)
        or not isinstance(transformation.decode, Transform)
    ):
        return None
    source_test = _leaf_test(source)
    target_test = _leaf_test(ast)
    if source_test is None or target_test is None:
        return None
    transform = transformation.decode.f

    def run(input: object, options: ParseOptions) -> ParseResult:  # noqa: PLR0911 - one exit per issue
        try:
            if input is MISSING:
                return MISSING_EXIT
            shown = reported(input, options)
            if not source_test(input):
                return fail_exit(EncodingIssue(ast, InvalidType(source, shown), shown))
            if source.checks is not None and not options.get("disable_checks"):
                issues = collect_issues(source.checks, input, source, options)
                if issues is not None:
                    return fail_exit(EncodingIssue(ast, Composite(source, issues, shown), shown))
            value = transform(input)
            if value is MISSING:
                return MISSING_EXIT
            if not target_test(value):
                return fail_exit(InvalidType(ast, reported(value, options)))
            if ast.checks is not None and not options.get("disable_checks"):
                issues = collect_issues(ast.checks, value, ast, options)
                if issues is not None:
                    return fail_exit(Composite(ast, issues, reported(value, options)))
            return Success(value)
        except Exception as defect:
            return die_exit(defect)

    return run
