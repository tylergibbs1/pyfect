"""The registry of parser operations per exact AST (Effect's internal
``compilerRegistry``).

Each AST resolves to one ``Entry``, cached on the node, holding its
operations: ``is`` / ``decode`` / ``make`` (optional synchronous fast paths
that answer ``INVALID`` instead of an issue) and ``decode_effect`` /
``make_effect`` (complete parsers). Every operation is resolved once, on
first use. A node with nothing installed is interpreted.

Until a decoder or a compiler is installed, ``AST.parse`` interprets
directly. Once one is (``set``, ``install``, ``enable``), every node's parse
goes through ``dispatch``: a parent's interpreter resolves each child on
first use and keeps that entry (a frame in ``_FRAME`` holds what the
running parent captured), so parsers that already reached a child keep
using it after the child is replaced, as Effect's ``lazyParser`` does.
"""

from __future__ import annotations

from collections.abc import Callable
from contextvars import ContextVar
from typing import Any, Final, Literal, Protocol, cast, final

from pyfect.exit import Success
from pyfect.exit import die as die_exit
from pyfect.schema._options import ParseOptions, is_constructing
from pyfect.schema.ast import (
    AST,
    Arrays,
    Class,
    Declaration,
    Objects,
    Suspend,
    TemplateLiteral,
    Union,
)
from pyfect.schema.ast._base import set_dispatch
from pyfect.schema.ast._result import MISSING, ParseResult
from pyfect.schema.ast._union import forget_tried


@final
class Invalid:
    """The type of ``INVALID``."""

    __slots__ = ()

    def __repr__(self) -> str:
        return "<invalid>"


INVALID: Final = Invalid()
"""What a fast path (``is`` aside) returns for an invalid input (Effect's
``SchemaCompiler.invalid``)."""

DEFAULT_PARSE_OPTIONS: Final[ParseOptions] = {}
"""The options of a call that gives none (Effect's ``defaultParseOptions``):
this same object, so an operation can tell."""

type Parser = Callable[[object, ParseOptions], ParseResult]
"""A complete parse: an ``Exit``, or an ``Effect`` when a transformation
needs one; ``MISSING`` in gives ``MISSING`` out (Effect's ``Parser``)."""
type Is = Callable[[object, ParseOptions], bool]
type Decode = Callable[[object, ParseOptions], object]
"""The decoded value, or ``INVALID``."""
type Make = Callable[[object, ParseOptions], object]
type DecodeEffect = Parser
type MakeEffect = Parser
type DecoderOperation = Literal["is", "decode", "make", "decode_effect", "make_effect"]
type Resolve = Callable[[AST], Entry]


class DecoderSource(Protocol):
    """The operations installed for an AST (Effect's ``CompiledDecoder``):
    ``decode_effect`` is required; ``is_``, ``decode``, ``make`` and
    ``make_effect`` are optional attributes. Each is read once, when first
    needed, so a property can make it lazily."""

    @property
    def decode_effect(self) -> DecodeEffect: ...


type Compile = Callable[[AST, Resolve, DecoderOperation], object]
"""Makes one operation of an AST on first use (``None``: not provided)."""
type CompileSource = Callable[[AST, Resolve], DecoderSource | None]
"""A whole-registry compiler: the operations of any AST (``None`` keeps
the interpreter)."""

_ATTRIBUTE: Final[dict[DecoderOperation, str]] = {
    "is": "is_",
    "decode": "decode",
    "make": "make",
    "decode_effect": "decode_effect",
    "make_effect": "make_effect",
}

type _Frame = tuple[dict[int, Entry], Resolve, bool]
"""A running interpreter: the child entries it captured, how it resolves
children, and whether its children parse in detail (``decode_effect``:
the node's own fast path already failed)."""

_FRAME: ContextVar[_Frame | None] = ContextVar("pyfect.schema.compiler.frame", default=None)

_UNSET: Final = object()


@final
class Entry:
    """The operations of one AST (see the module)."""

    __slots__ = (
        "_ops",
        "ast",
        "compiled",
        "complete",
        "constructor",
        "fast_then_complete",
        "per_operation",
        "resolve",
    )

    def __init__(self, ast: AST, compiled: object, per_operation: bool, resolve: Resolve) -> None:
        self.ast = ast
        self.compiled = compiled
        """The installed ``DecoderSource`` or ``Compile``; ``None`` interprets."""
        self.per_operation = per_operation
        self.resolve = resolve
        self._ops: dict[str, Any] = {}
        self.complete: Parser | None = None
        """``decode_effect`` once resolved."""
        self.fast_then_complete: Parser | None = None
        """``parser`` once resolved."""
        self.constructor: Parser | None = None
        """``make_effect`` once resolved."""

    def resolved(self, operation: str) -> bool:
        """``operation`` (or ``"parser"``) was resolved already (Effect's
        ``Object.hasOwn(entry, operation)``)."""
        match operation:
            case "decode_effect":
                return self.complete is not None
            case "parser":
                return self.fast_then_complete is not None
            case "make_effect":
                return self.constructor is not None
            case _:
                return operation in self._ops

    def _operation(self, key: DecoderOperation) -> Any:
        compiled = self.compiled
        if compiled is None:
            return None
        if self.per_operation:
            return cast("Compile", compiled)(self.ast, self.resolve, key)
        return getattr(compiled, _ATTRIBUTE[key], None)

    def _memo(self, key: str, make: Callable[[], Any]) -> Any:
        found = self._ops.get(key, _UNSET)
        if found is _UNSET:
            found = make()
            self._ops[key] = found
        return found

    @property
    def is_(self) -> Is | None:
        return self._memo("is", lambda: self._operation("is"))

    @property
    def decode(self) -> Decode | None:
        return self._memo("decode", lambda: self._operation("decode"))

    @property
    def make(self) -> Make | None:
        return self._memo("make", lambda: self._operation("make"))

    @property
    def decode_effect(self) -> Parser:
        found = self.complete
        if found is None:
            found = self.complete = self._operation("decode_effect") or interpreter(
                self.ast, self.resolve
            )
        return found

    @property
    def parser(self) -> Parser:
        """``decode`` with ``decode_effect`` after ``INVALID``, or
        ``decode_effect`` alone."""
        found = self.fast_then_complete
        if found is None:
            decode = self.decode
            found = self.fast_then_complete = (
                self.decode_effect
                if decode is None
                else with_decode(decode, lambda: self.decode_effect)
            )
        return found

    @property
    def compiled_make_effect(self) -> Parser | None:
        """The installed ``make_effect``, if any (Effect's ``compiledMakeEffect``)."""
        return self._memo("compiled_make_effect", lambda: self._operation("make_effect"))

    @property
    def make_effect(self) -> Parser:
        found = self.constructor
        if found is None:
            found = self.constructor = self.compiled_make_effect or interpreter(
                self.ast, self.resolve
            )
        return found


def interpreter(ast: AST, resolve: Resolve, detailed: bool = False) -> Parser:
    """The interpreter of ``ast``, its children resolved through ``resolve``
    on first use and kept (Effect's ``Interpreter.compile`` over
    ``lazyParser``)."""
    if not _has_children(ast):
        # Nothing to resolve below a leaf: no frame needed.
        return ast.interpret
    captured: dict[int, Entry] = {}
    frame: _Frame = (captured, resolve, detailed)

    def parse(input: object, options: ParseOptions) -> ParseResult:
        token = _FRAME.set(frame)
        try:
            return ast.interpret(input, options)
        finally:
            _FRAME.reset(token)

    return parse


def _has_children(ast: AST) -> bool:
    return ast.encoding is not None or isinstance(
        ast, (Arrays, Objects, Union, Suspend, Declaration, Class, TemplateLiteral)
    )


def with_decode(fast: Decode, detailed: Callable[[], Parser]) -> Parser:
    """``fast``, then the complete parser after ``INVALID`` (Effect's
    ``withDecode``); a raise is a defect, never parsed again."""
    complete: list[Parser] = []

    def parse(input: object, options: ParseOptions) -> ParseResult:
        if input is not MISSING:
            try:
                value = fast(input, options)
            except Exception as defect:
                return die_exit(defect)
            if value is not INVALID:
                return Success(value)
        if not complete:
            complete.append(detailed())
        return complete[0](input, options)

    return parse


def dispatch(ast: AST, input: object, options: ParseOptions) -> ParseResult:
    """``AST.parse`` once the registry is active."""
    frame = _FRAME.get()
    if frame is None:
        entry = resolve(ast)
        detailed = False
    else:
        captured, resolve_child, detailed = frame
        entry = captured.get(id(ast))
        if entry is None:
            # The parent holds the child, so its id stays this node's.
            entry = captured[id(ast)] = resolve_child(ast)
    if is_constructing(options):
        return (entry.constructor or entry.make_effect)(input, options)
    if detailed:
        return (entry.complete or entry.decode_effect)(input, options)
    return (entry.fast_then_complete or entry.parser)(input, options)


class _State:
    generation = 0
    compiler: CompileSource | None = None
    active = False


def active() -> bool:
    """A decoder or a compiler was installed: parsers resolve entries.
    Until then they call ``AST.parse`` and resolve nothing."""
    return _State.active


def _cached(ast: AST) -> Entry | None:
    slot = ast.compiler_entry
    if slot and slot[0] == _State.generation:
        return cast("Entry", slot[1])
    return None


def _store(ast: AST, entry: Entry) -> Entry:
    ast.compiler_entry[:] = [_State.generation, entry]
    return entry


def resolve(ast: AST) -> Entry:
    """The entry of ``ast``, made and cached on first use: compiled by the
    installed compiler, if any, else interpreted."""
    cached = _cached(ast)
    if cached is not None:
        return cached
    if not _State.active:
        return _store(ast, Entry(ast, None, False, _interpreted_under(ast)))
    compiler = _State.compiler
    compiled = None if compiler is None else compiler(ast, resolve)
    return _store(ast, Entry(ast, compiled, False, resolve))


def _interpreted_under(parent: AST) -> Resolve:
    """How an entry resolved before anything was installed resolves its children: interpreted
    for good, as Effect's interpreter resolves them eagerly then; but a Union member the union
    never tried is resolved from the registry when first tried, as Effect's Union parser
    compiles a member then (``Union.tried``)."""

    def resolve_child(child: AST) -> Entry:
        if isinstance(parent, Union) and not parent.tried(child):
            return resolve(child)
        return Entry(child, None, False, _interpreted_under(child))

    return resolve_child


def _activate() -> None:
    _State.active = True
    set_dispatch(dispatch)


def set(ast: AST, decoder: DecoderSource | None, resolve_child: Resolve = resolve) -> Entry:
    """Install ``decoder`` for ``ast``, replacing its entry; parsers that
    already resolved the old entry keep it."""
    if decoder is not None:
        _activate()
    return _store(ast, Entry(ast, decoder, False, resolve_child))


def set_compiler(ast: AST, compile: Compile, resolve_child: Resolve = resolve) -> Entry:
    """Install ``compile`` for ``ast``: each operation made on first use."""
    _activate()
    return _store(ast, Entry(ast, compile, True, resolve_child))


def install(compiler: CompileSource) -> None:
    """Compile every AST resolved from now on with ``compiler``."""
    _activate()
    _State.compiler = compiler


def enable(ast: AST, compiler: CompileSource) -> None:
    """Compile ``ast`` and the nodes its parsers reach with ``compiler``."""
    _activate()
    scoped = _Scoped(compiler)
    decoder = compiler(ast, scoped)
    cached = _cached(ast)
    if decoder is not None or cached is None or cached.compiled is None:
        set(ast, decoder, scoped)


@final
class _Scoped:
    """How ``enable`` resolves the nodes below its AST: compiled with its compiler."""

    __slots__ = ("compiler",)

    def __init__(self, compiler: CompileSource) -> None:
        self.compiler = compiler

    def __call__(self, child: AST) -> Entry:
        cached = _cached(child)
        if cached is not None and (cached.compiled is not None or cached.resolve is self):
            return cached
        return set(child, self.compiler(child, self), self)


def reset() -> None:
    """Forget every entry and compiler and go back to the interpreter (for
    tests, which share one process where Effect's run one module each)."""
    _State.generation += 1
    _State.compiler = None
    _State.active = False
    set_dispatch(None)
    forget_tried()
