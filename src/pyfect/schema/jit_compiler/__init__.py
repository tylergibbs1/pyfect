"""Schema decoders generated as Python source at run time (Effect's
``SchemaJITCompiler``).

``enable(ast)`` compiles an AST and the nodes its parsers reach; importing
``pyfect.schema.jit_compiler.install`` compiles every AST resolved after
the import. Each operation is generated on first use and compiled with
``exec``; when ``exec`` is unavailable or generation fails, parsing stays
with the interpreter. Errors raised while parsing are never retried.
"""

from __future__ import annotations

import builtins
from typing import Any

from pyfect.schema.ast import AST
from pyfect.schema.compiler import _codegen as codegen
from pyfect.schema.compiler import runtime
from pyfect.schema.compiler._registry import (
    DecodeEffect,
    DecoderOperation,
    DecoderSource,
    Resolve,
)
from pyfect.schema.compiler._registry import enable as _enable

_PROBE = "pass"
"""What ``exec`` runs once to see that it works (Effect checks
``new Function("return true")``)."""


class _Exec:
    checked: object = None
    supported = False


def _supported() -> bool:
    current = builtins.exec
    if _Exec.checked is not current:
        _Exec.checked = current
        try:
            current(_PROBE, {})
            _Exec.supported = True
        except Exception:
            _Exec.supported = False
    return _Exec.supported


def _build(ast: AST, resolve: Resolve, source: str) -> Any:
    lines = source.splitlines()
    module = "\n".join(["def factory(ast, R, resolve):", *(f"    {line}" for line in lines)])
    namespace: dict[str, Any] = {}
    builtins.exec(module, namespace)
    return namespace["factory"](ast, runtime, resolve)


class _Lazy:
    """Each operation of one AST, generated when first read."""

    __slots__ = ("ast", "decode_failed", "resolve")

    def __init__(self, ast: AST, resolve: Resolve) -> None:
        self.ast = ast
        self.resolve = resolve
        self.decode_failed = False

    def operation(self, key: DecoderOperation) -> Any:
        construction = key in ("make", "make_effect")
        if construction or not self.decode_failed:
            try:
                source = codegen.generate(self.ast, key)
                if source is None:
                    return None
                return _build(self.ast, self.resolve, source)
            except Exception:
                # Only generation and initialization fail here.
                if not construction:
                    self.decode_failed = True
        if key == "decode_effect":
            return runtime.decode(self.ast, self.resolve)
        if key == "make_effect":
            return runtime.make(self.ast, self.resolve)
        return None

    @property
    def is_(self) -> Any:
        return self.operation("is")

    @property
    def decode(self) -> Any:
        return self.operation("decode")

    @property
    def make(self) -> Any:
        return self.operation("make")

    @property
    def decode_effect(self) -> DecodeEffect:
        return self.operation("decode_effect")

    @property
    def make_effect(self) -> Any:
        return self.operation("make_effect")


def compiler(ast: AST, resolve: Resolve) -> DecoderSource | None:
    """The lazily generated operations of ``ast``, or ``None`` when
    compiling it cannot beat the interpreter or ``exec`` is unavailable."""
    if not codegen.should_compile_parser(ast) or not _supported():
        return None
    return _Lazy(ast, resolve)


def enable(ast: AST, /) -> None:
    """Compile ``ast`` and its parsing dependencies on first use (Effect's
    ``SchemaJITCompiler.enable``). Enable before the first parse: parsers
    that already resolved an entry keep it. The type side and the flipped
    AST are separate ASTs; enable them separately."""
    _enable(ast, compiler)


__all__ = ["compiler", "enable"]
