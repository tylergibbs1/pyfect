"""A compact binary codec derived from a schema's encoded side (Effect's
``encoding/SchemaBinary``), byte-compatible with Effect's::

    from pyfect import schema as S
    from pyfect.encoding import schema_binary

    codec = schema_binary.to_codec(S.Struct(Person))
    data = S.encode_unknown_sync(codec)({"name": "Ada", "age": 36})
    person = S.decode_unknown_sync(codec)(data)

The default wire format supports compatible schema evolution: a field an old
reader does not know is skipped, and an array of structs is written as a row
run, whose rows declare their shape once and back-reference repeated strings.
``fingerprint=True`` uses positional layouts and an 8-byte layout hash for
smaller frames, and rejects a peer whose encoded layout differs.

``to_codec`` handles exactly one frame per encode and decode. Use ``parser``
for concatenated frames and ``encoder`` for a writer with a connection-scoped
string dictionary; ``encode``, ``decode`` and ``duplex`` are channels.

A ``datetime`` is written in milliseconds and a ``Duration`` in nanoseconds,
as Effect's are. A ``datetime`` cannot hold Effect's dates outside years 1 to
9999: reading one fails.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from typing import Any, Unpack

from pyfect import schema as S
from pyfect.encoding.schema_binary import _dictionary, _encode
from pyfect.encoding.schema_binary._channels import decode, duplex, encode
from pyfect.encoding.schema_binary._compile import FIELD_ID_KEY, FIXED_WIDTH_KEY
from pyfect.encoding.schema_binary._fingerprint import compile_mode
from pyfect.encoding.schema_binary._parser import Parser, make_parser
from pyfect.encoding.schema_binary._target import (
    BytesCodec,
    compile_target,
    excess_is_error,
    is_success_exit,
    make_codec,
    make_direct_codec,
    make_strict_codec,
)
from pyfect.encoding.schema_binary._wire import IssueError
from pyfect.schema import ParseOptions, SchemaError, ast

_MAX_FIELD_ID = 0xFFFFFFFF


def to_codec[A](
    schema: S.Codec[A, Any, Any, Any], /, *, fingerprint: bool = False
) -> BytesCodec[A]:
    """``schema`` read from and written to one binary frame, memoized by
    schema identity and wire mode.

    Bytes carry the layout of the schema that wrote them: read them with that
    schema or a compatible evolution of it (fingerprint mode needs an
    identical encoded layout). Most union codecs prefix values with a member
    selector, so they cannot read bytes written by a member's own codec."""
    return make_codec(schema.__codec__(), fingerprint)


def to_codec_strict[A](schema: S.Codec[A, Any, Any, Any], /) -> BytesCodec[A]:
    """The default-mode ``to_codec`` codec, except that decoding rejects a
    struct field, an extra key, a union member or a field wire kind the schema
    does not know, instead of skipping it."""
    return make_strict_codec(schema.__codec__())


def to_codec_direct[A](
    schema: S.Codec[A, Any, Any, Any], /, *, fingerprint: bool = False
) -> BytesCodec[A]:
    """``to_codec`` without the schema pass around the binary layer, for
    schemas the binary layer validates on its own (any other falls back to
    ``to_codec``). It encodes and decodes the same values, but is not a sound
    ``S.is_`` guard: only for callers that never guard on it."""
    return make_direct_codec(schema.__codec__(), fingerprint)


def _rethrown[A](f: Callable[[], A]) -> A:
    try:
        return f()
    except IssueError as error:
        raise SchemaError(error.issue) from None


def encode_unknown_sync(
    schema: S.Codec[Any, Any, Any, Any],
    /,
    *,
    fingerprint: bool = False,
    **options: Unpack[ParseOptions],
) -> Callable[[object], bytes]:
    """Encodes one frame without the schema pass ``to_codec`` wraps around it
    when the binary layer validates the schema on its own; any other schema
    falls back to the codec, so checks and transformations still run."""
    compiled = compile_target(schema)
    mode = compile_mode(compiled.layout, fingerprint)

    def direct(value: object) -> bytes:
        return _rethrown(lambda: _encode.encode_frame(compiled.layout, value, options, mode))

    if compiled.exact and not excess_is_error(options):
        return direct
    fallback = S.encode_unknown_sync(to_codec(schema, fingerprint=fingerprint), **options)
    # The binary layer drops excess keys instead of reporting them.
    if not compiled.exit_success or excess_is_error(options):
        return fallback

    def through(value: object) -> bytes:
        return direct(value) if is_success_exit(value) else fallback(value)

    return through


def encode_many_unknown_sync(
    schema: S.Codec[Any, Any, Any, Any],
    /,
    *,
    fingerprint: bool = False,
    **options: Unpack[ParseOptions],
) -> Callable[[Sequence[object]], bytes]:
    """Encodes concatenated frames in one writer pass, with
    ``encode_unknown_sync``'s direct path and fallback."""
    compiled = compile_target(schema)
    if not compiled.exact or excess_is_error(options):
        encode_one = encode_unknown_sync(schema, fingerprint=fingerprint, **options)
        return lambda values: b"".join(map(encode_one, values))
    mode = compile_mode(compiled.layout, fingerprint)

    def many(values: Sequence[object]) -> bytes:
        return _rethrown(lambda: _encode.encode_frames(compiled.layout, values, options, mode))

    return many


def _require_dictionary(exact: bool, dictionary: bool) -> bool:
    if dictionary and not exact:
        raise ValueError(
            "Binary layout: dictionary needs a schema the binary layer validates on its own"
        )
    return dictionary


def parser[A](
    schema: S.Codec[A, Any, Any, Any],
    /,
    *,
    fingerprint: bool = False,
    dictionary: bool = False,
    max_frame_size: int | None = None,
    **options: Unpack[ParseOptions],
) -> Parser[A]:
    """A stateful parser of concatenated frames. ``max_frame_size`` limits a
    buffered frame. With ``dictionary``, frames share one string dictionary
    with the ``encoder`` that wrote them, and must be read in order; a schema
    the binary layer does not fully validate cannot use it (``ValueError``)."""
    compiled = compile_target(schema)
    decode_target = None if compiled.exact else S.decode_unknown_sync(compiled.target, **options)

    def decode_success(value: object) -> object:
        assert decode_target is not None
        return value if is_success_exit(value) else decode_target(value)

    return make_parser(
        compiled.layout,
        compile_mode(compiled.layout, fingerprint),
        options,
        max_frame_size,
        decode_success if decode_target is not None and compiled.exit_success else decode_target,
        _require_dictionary(compiled.exact, dictionary),
    )


@dataclass(frozen=True, slots=True)
class Encoder:
    """The writer ``encoder`` returns."""

    encode: Callable[[object], bytes]
    encode_many: Callable[[Sequence[object]], bytes]


def encoder(
    schema: S.Codec[Any, Any, Any, Any],
    /,
    *,
    fingerprint: bool = False,
    dictionary: bool = False,
    **options: Unpack[ParseOptions],
) -> Encoder:
    """A writer for one connection. With ``dictionary``, every frame shares
    the string dictionary its matching ``parser`` rebuilds as it reads them,
    so both must come from one schema and the same options."""
    compiled = compile_target(schema)
    if not _require_dictionary(compiled.exact, dictionary):
        return Encoder(
            encode_unknown_sync(schema, fingerprint=fingerprint, **options),
            encode_many_unknown_sync(schema, fingerprint=fingerprint, **options),
        )
    mode = compile_mode(compiled.layout, fingerprint)
    validate: Callable[[object], object] = (
        S.encode_unknown_sync(compiled.target, **options)
        if excess_is_error(options)
        else (lambda value: value)
    )
    dict_ = _dictionary.DictWrite()

    def encode_one(value: object) -> bytes:
        return _rethrown(
            lambda: _encode.encode_frame(compiled.layout, validate(value), options, mode, dict_)
        )

    def encode_many(values: Sequence[object]) -> bytes:
        return _rethrown(
            lambda: _encode.encode_frames(
                compiled.layout, [validate(v) for v in values], options, mode, dict_
            )
        )

    return Encoder(encode_one, encode_many)


int32: S.Bottom[float] = S.Number.check(S.is_int32(**{FIXED_WIDTH_KEY: "i32"}))
"""A 32-bit signed integer written as four little-endian bytes, for values
that regularly need more than four bytes as a varint (hashes, full-range ids);
small values are cheaper as ``S.Int``. Rejects non-integers and values outside
``-2 ** 31`` through ``2 ** 31 - 1`` instead of truncating them; ``-0`` is
written as ``0``.

Switching a field between this, ``uint32``, ``S.Number`` or ``S.Int`` changes
its encoding, so it is not a compatible evolution: in default mode the other
reader can decode a different value without an error. Fingerprint mode
rejects the layout mismatch."""

uint32: S.Bottom[float] = S.Number.check(S.is_uint32(**{FIXED_WIDTH_KEY: "u32"}))
"""A 32-bit unsigned integer written as four little-endian bytes. Rejects
non-integers and values outside ``0`` through ``2 ** 32 - 1`` instead of
wrapping them; see ``int32``."""

int64: S.Bottom[int] = S.BigInt.check(
    S.is_between_big_int(
        minimum=-(2**63),
        maximum=2**63 - 1,
        expected="a 64-bit integer",
        **{FIXED_WIDTH_KEY: "i64"},  # pyright: ignore[reportArgumentType]
    )
)
"""A 64-bit signed integer (Effect's ``bigint``) written as eight
little-endian bytes. Rejects values outside ``-2 ** 63`` through
``2 ** 63 - 1`` instead of wrapping them. As a struct field it costs one
length byte more than the payload, because the eight-byte field kind belongs
to floating-point numbers. Switching a field between this, ``uint64`` or
``S.BigInt`` is not a compatible evolution: a default-mode reader may decode
the other form as a different value without an error."""

uint64: S.Bottom[int] = S.BigInt.check(
    S.is_between_big_int(
        minimum=0,
        maximum=2**64 - 1,
        expected="a 64-bit unsigned integer",
        **{FIXED_WIDTH_KEY: "u64"},  # pyright: ignore[reportArgumentType]
    )
)
"""A 64-bit unsigned integer (Effect's ``bigint``) written as eight
little-endian bytes. Rejects values outside ``0`` through ``2 ** 64 - 1``
instead of wrapping them; see ``int64``."""


def _with_key_id(node: ast.AST, id: int) -> ast.AST:
    annotations = {**(node.key_annotations or {}), FIELD_ID_KEY: id}
    return ast.replace_context(node, key_annotations=annotations)


def field_id(id: int, /) -> Callable[[S.Top], S.Bottom[Any, Any, Any, Any]]:
    """Assigns a struct property's wire field id, an integer from 1 through
    4294967295: to preserve it across a rename or resolve a hash collision.
    Anything else raises ``ValueError``."""
    if type(id) is not int or not 0 < id <= _MAX_FIELD_ID:
        raise ValueError(f"Binary layout field id must be an integer in [1, 4294967295], got {id}")

    def annotate(schema: S.Top) -> S.Bottom[Any, Any, Any, Any]:
        codec = schema.__codec__()
        node = _with_key_id(codec.ast, id)
        if node.encoding is not None:
            *init, last = node.encoding
            link = ast.Link(_with_key_id(last.to, id), last.transformation)
            node = replace(node, encoding=(*init, link))
        return replace(codec, ast=node)

    return annotate


__all__ = [
    "BytesCodec",
    "Encoder",
    "Parser",
    "SchemaError",
    "decode",
    "duplex",
    "encode",
    "encode_many_unknown_sync",
    "encode_unknown_sync",
    "encoder",
    "field_id",
    "int32",
    "int64",
    "parser",
    "to_codec",
    "to_codec_direct",
    "to_codec_strict",
    "uint32",
    "uint64",
]
