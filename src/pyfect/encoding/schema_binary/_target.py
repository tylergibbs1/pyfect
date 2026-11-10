"""The schema pass around the binary layer (Effect's ``compileTarget`` and its
bypasses): each schema's derived target, and the codecs built from it."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field, replace
from functools import lru_cache
from typing import Any, cast

from pyfect import schema as S
from pyfect.encoding.schema_binary import _encode, _wire
from pyfect.encoding.schema_binary._compile import (
    JSON_IDS,
    NATIVES,
    compile_layout,
    representation_id,
)
from pyfect.encoding.schema_binary._decode import decode_one_shot
from pyfect.encoding.schema_binary._fingerprint import STRICT_MODE, Mode, compile_mode
from pyfect.encoding.schema_binary._layout import Layout
from pyfect.encoding.schema_binary._values import is_cyclic
from pyfect.exit import Exit, Success
from pyfect.exit import fail as fail_exit
from pyfect.schema import ParseOptions, ast
from pyfect.schema import getter as G
from pyfect.schema import transformation as T
from pyfect.schema._codec_derivation import CodecDerivation
from pyfect.schema._codec_links import UNKNOWN_TO_JSON
from pyfect.schema.issue import Issue

type BytesCodec[A] = S.Codec[A, bytes, Any, Any]
"""A schema read from and written to one binary frame."""

type _Accept = Callable[[object, ParseOptions], bool]


class _Derivation(CodecDerivation):
    """Effect's ``toBinaryAST``: natively written declarations recurse, any
    other is written through its ``to_codec_json`` or ``to_codec`` link."""

    opaque = UNKNOWN_TO_JSON

    def _leaf(self, node: ast.AST) -> ast.AST:
        if not isinstance(node, ast.Declaration):
            return node
        id = representation_id(node)
        if id is not None and (id in NATIVES or id in JSON_IDS):
            return node._map(self)  # pyright: ignore[reportPrivateUsage]
        annotations = node.annotations or {}
        parameters = tuple(ast.to_encoded(p) for p in node.type_parameters)
        link = None
        for key in ("to_codec_json", "to_codec"):
            make = annotations.get(key)
            if callable(make):
                link = cast("Callable[[tuple[ast.AST, ...]], ast.Link | None]", make)(parameters)
                if link is not None:
                    break
        if link is None:
            return node
        return replace(node, encoding=(ast.Link(self(link.to), link.transformation),))

    def _priority(self, encoded: ast.AST) -> int:
        return 0


@dataclass(frozen=True, slots=True)
class CompiledTarget:
    target: S.Bottom[Any, Any, Any, Any]
    layout: Layout
    exact: bool
    exit_success: bool
    recursive: bool
    """A recursive schema can hold a cyclic value, which only the schema pass
    detects, so encoding one keeps that pass even when the layout is exact."""


@lru_cache(maxsize=4096)
def _compile_target_from_ast(node: ast.AST) -> CompiledTarget:
    raw: S.Bottom[Any, Any, Any, Any] = S.Bottom(_Derivation()(node))
    compiled = compile_layout(raw.ast)
    target = _with_cycle_guard(raw) if compiled.recursive else raw
    return CompiledTarget(
        target, compiled.layout, compiled.exact, compiled.exit_success, compiled.recursive
    )


def compile_target(schema: S.Codec[Any, Any, Any, Any]) -> CompiledTarget:
    return _compile_target_from_ast(schema.__codec__().ast)


def is_success_exit(value: object) -> bool:
    return isinstance(value, Success)


def is_object(value: object) -> bool:
    """Whether a decoded value has an identity of its own to hand over."""
    return not (value is None or isinstance(value, str | bool | int | float | bytes))


def reports_excess(_: object, options: ParseOptions) -> bool:
    """The binary layer drops unknown keys instead of reporting them, so
    only ``on_excess_property="error"`` needs the schema pass to see the input."""
    return options.get("on_excess_property") != "error"


def _never_accepts(_: object, __: ParseOptions) -> bool:
    return False


@dataclass(slots=True, eq=False)
class _Trusted:
    """The value the binary decoder produced most recently. The schema pass
    around the decode runs straight after it, so one slot is all the handoff
    needs; a value that misses it just pays the real check."""

    value: object = None

    def take(self, input: object) -> bool:
        if self.value is None or input is not self.value:
            return False
        self.value = None
        return True


@dataclass(frozen=True, slots=True, eq=False)
class _Bypass(ast.Declaration):
    """A target whose two directions accept their own inputs unchanged:
    ``flip`` swaps its parser for the other direction's."""

    other: ast.DeclarationRun = field(default=lambda _: _no_parser, kw_only=True)

    def _flip(self) -> ast.Declaration:
        return replace(self, run=self.other, other=self.run)

    def _to_type(self) -> ast.Declaration:
        return self


def _no_parser(_: object, __: ast.Declaration, ___: ParseOptions) -> ast.ParseResult:
    raise AssertionError("a bypass always has a parser for each direction")


def _bypass_pass(
    target: S.Bottom[Any, Any, Any, Any], decode_accept: _Accept, encode_accept: _Accept
) -> S.Bottom[Any, Any, Any, Any]:
    typed = target.ast.to_type()

    def run(accept: _Accept) -> ast.DeclarationRun:
        def make(_: tuple[ast.AST, ...]) -> ast.DeclarationParser:
            def parse(input: object, __: ast.Declaration, options: ParseOptions) -> ast.ParseResult:
                return Success(input) if accept(input, options) else typed.parse(input, options)

            return parse

        return make

    return S.Bottom(
        _Bypass(
            (typed,),
            run(decode_accept),
            annotations={"expected": "binary value"},
            other=run(encode_accept),
        )
    )


def _with_trusted_decode(
    target: S.Bottom[Any, Any, Any, Any], trusted: _Trusted, bypass_encode: bool
) -> S.Bottom[Any, Any, Any, Any]:
    """The binary layer validates an exact schema in both directions. Encoding
    skips the pass outright (a recursive schema keeps it: the cycle walk lives
    there). Decoding only lets through values the binary layer just produced,
    so every other input, ``S.is_`` included, still runs the real check."""
    return _bypass_pass(
        target,
        lambda input, _: trusted.take(input),
        reports_excess if bypass_encode else _never_accepts,
    )


def _with_exit_success_decode(
    target: S.Bottom[Any, Any, Any, Any], trusted: _Trusted
) -> S.Bottom[Any, Any, Any, Any]:
    """Only failure exits pay the schema pass, for their cause's encodings.
    Not a sound ``S.is_`` guard: only ``to_codec_direct`` uses it."""

    def make(parameters: tuple[ast.AST, ...]) -> ast.DeclarationParser:
        (codec,) = parameters

        def parse(input: object, _: ast.Declaration, options: ParseOptions) -> ast.ParseResult:
            if trusted.take(input) or (
                is_success_exit(input) and options.get("on_excess_property") != "error"
            ):
                return Success(input)
            return codec.parse(input, options)

        return parse

    return S.Bottom(
        ast.Declaration((target.ast,), make, annotations={"expected": "binary exit value"})
    )


def _pass_through(target: S.Bottom[Any, Any, Any, Any]) -> S.Bottom[Any, Any, Any, Any]:
    """An exact schema's target adds nothing, except under
    ``on_excess_property="error"``. Not a sound ``S.is_`` guard: only
    ``to_codec_direct`` uses it."""
    return _bypass_pass(target, reports_excess, reports_excess)


def _with_cycle_guard(target: S.Bottom[Any, Any, Any, Any]) -> S.Bottom[Any, Any, Any, Any]:
    """Refuses a value holding itself; a value the schema pass just decoded
    skips the walk once."""
    decoded: list[object] = []

    def make(parameters: tuple[ast.AST, ...]) -> ast.DeclarationParser:
        (typed,) = parameters

        def parse(input: object, node: ast.Declaration, options: ParseOptions) -> ast.ParseResult:
            if decoded and decoded[0] is input:
                decoded.clear()
                return Success(input)
            if is_cyclic(input):
                return ast.invalid_type(node, input, options)
            return typed.parse(input, options)

        return parse

    def remember(value: object) -> object:
        decoded[:] = [value]
        return value

    guard = ast.Declaration(
        (target.ast.to_type(),), make, annotations={"expected": "acyclic value"}
    )
    return S.Bottom(ast.decode_to(target.ast, guard, T.transform(decode=remember, encode=_same)))


def _same(value: object) -> object:
    return value


def _transformation(
    layout: Layout, mode: Mode, trusted: _Trusted | None, success_only: bool
) -> T.Transformation[object, bytes]:
    def decode(data: bytes, options: ParseOptions) -> Exit[object, Issue]:
        try:
            value = decode_one_shot(layout, data, options, mode)
        except _wire.IssueError as error:
            return fail_exit(error.issue)
        if (
            trusted is not None
            and is_object(value)
            and (not success_only or is_success_exit(value))
        ):
            trusted.value = value
        return Success(value)

    def encode(value: object, options: ParseOptions) -> Exit[bytes, Issue]:
        try:
            return Success(_encode.encode_frame(layout, value, options, mode))
        except _wire.IssueError as error:
            return fail_exit(error.issue)

    return T.Transformation(G.TransformEffect(decode), G.TransformEffect(encode))


def _assemble(
    target: S.Bottom[Any, Any, Any, Any],
    layout: Layout,
    mode: Mode,
    trusted: _Trusted | None,
    success_only: bool = False,
) -> BytesCodec[Any]:
    return S.Bytes.pipe(S.decode_to(target, _transformation(layout, mode, trusted, success_only)))


def _make_codec(schema: S.Codec[Any, Any, Any, Any], fingerprint: bool) -> BytesCodec[Any]:
    compiled = compile_target(schema)
    return _codec_in_mode(compiled, compile_mode(compiled.layout, fingerprint))


def _make_strict_codec(schema: S.Codec[Any, Any, Any, Any]) -> BytesCodec[Any]:
    return _codec_in_mode(compile_target(schema), STRICT_MODE)


def _codec_in_mode(compiled: CompiledTarget, mode: Mode) -> BytesCodec[Any]:
    if not compiled.exact:
        return _assemble(compiled.target, compiled.layout, mode, None)
    trusted = _Trusted()
    target = _with_trusted_decode(compiled.target, trusted, not compiled.recursive)
    return _assemble(target, compiled.layout, mode, trusted)


def _make_direct_codec(schema: S.Codec[Any, Any, Any, Any], fingerprint: bool) -> BytesCodec[Any]:
    compiled = compile_target(schema)
    mode = compile_mode(compiled.layout, fingerprint)
    if compiled.exact:
        return _assemble(_pass_through(compiled.target), compiled.layout, mode, None)
    if not compiled.exit_success:
        return make_codec(schema, fingerprint)
    trusted = _Trusted()
    target = _with_exit_success_decode(compiled.target, trusted)
    return _assemble(target, compiled.layout, mode, trusted, True)


make_codec = lru_cache(maxsize=4096)(_make_codec)
make_strict_codec = lru_cache(maxsize=4096)(_make_strict_codec)
make_direct_codec = lru_cache(maxsize=4096)(_make_direct_codec)
"""Memoized by schema identity and wire mode."""


def excess_is_error(options: ParseOptions) -> bool:
    return options.get("on_excess_property") == "error"


__all__ = ["BytesCodec", "CompiledTarget"]
