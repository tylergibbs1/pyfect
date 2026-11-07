"""The shared registry of schema decoders (Effect's ``SchemaCompiler``).

A decoder installed with ``set`` for an exact AST is used by every parser
(``S.decode_unknown_sync``, ``S.is_``, ``Bottom.make``, ...) and by every
schema that reaches the AST, without a compiled schema type or a second
parser API. The JIT compiler (``pyfect.schema.jit_compiler``) and modules
written by the ahead-of-time compiler (``pyfect.schema.aot_compiler``) fill
the same registry.

An installed decoder (a ``CompiledDecoder``, or any object with these
attributes) has ``decode_effect``, the complete decoder, and may have the
fast paths ``is_``, ``decode`` and ``make``, which return ``INVALID`` for an
invalid input (``is_`` returns ``False``), and ``make_effect``, the
complete constructor. Each attribute is read once, when first needed.
Parsers that already resolved an AST keep its entry after a later ``set``.
"""

from __future__ import annotations

from dataclasses import dataclass

from pyfect.schema.ast import AST
from pyfect.schema.ast._result import MISSING
from pyfect.schema.compiler._registry import (
    DEFAULT_PARSE_OPTIONS,
    INVALID,
    Decode,
    DecodeEffect,
    DecoderSource,
    Invalid,
    Is,
    Make,
    MakeEffect,
)
from pyfect.schema.compiler._registry import set as _set


@dataclass(frozen=True, slots=True, kw_only=True)
class CompiledDecoder:
    """The operations installed for an AST (see the module)."""

    decode_effect: DecodeEffect
    is_: Is | None = None
    decode: Decode | None = None
    make: Make | None = None
    make_effect: MakeEffect | None = None


def set(ast: AST, decoder: DecoderSource, /) -> None:
    """Install ``decoder`` for ``ast`` (Effect's ``SchemaCompiler.set``). A
    later ``set`` replaces it for parsers that have not resolved ``ast``
    yet; the decoder is trusted to implement the AST's semantics."""
    _set(ast, decoder)


__all__ = [
    "DEFAULT_PARSE_OPTIONS",
    "INVALID",
    "MISSING",
    "CompiledDecoder",
    "Decode",
    "DecodeEffect",
    "DecoderSource",
    "Invalid",
    "Is",
    "Make",
    "MakeEffect",
    "set",
]
