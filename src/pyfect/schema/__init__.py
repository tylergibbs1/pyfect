"""Schemas (Effect's ``Schema``): describe a value once, then decode,
validate and encode it::

    from pyfect import schema as S

    S.decode_unknown_sync(S.String)("a")    # "a"
    S.decode_unknown_sync(S.String)(1)      # raises SchemaError("Expected string")
    S.decode_unknown_result(S.Number)("a")  # Err(SchemaError(...))

A schema is a ``Bottom[T, E, RD, RE]``: it decodes an ``E`` (Encoded) into
a ``T`` (Type) and encodes back, needing services ``RD`` / ``RE``.
Anything that takes a schema accepts a ``Codec[T, E, RD, RE]``; ``Schema[T]``,
``Decoder[T]`` and ``Encoder[E]`` leave the other parameters open.

The decoders and encoders (``decode_unknown_sync``, ``encode_effect``, ...)
take parse options as keyword arguments (``errors="all"``,
``report_input=True``, see ``ParseOptions``) both when made and when
called. They fail with ``SchemaError``, whose ``issue`` (``pyfect.schema.issue``)
says what was wrong and where; the AST is in ``pyfect.schema.ast``.

See docs/SCHEMA_DESIGN.md for how schemas are typed.
"""

from pyfect.schema import ast, issue
from pyfect.schema._error import SchemaError
from pyfect.schema._options import ParseOptions
from pyfect.schema._parse import (
    Guard,
    Parser,
    asserts,
    decode_effect,
    decode_exit,
    decode_option,
    decode_result,
    decode_sync,
    decode_unknown_effect,
    decode_unknown_exit,
    decode_unknown_option,
    decode_unknown_result,
    decode_unknown_sync,
    encode_effect,
    encode_exit,
    encode_option,
    encode_result,
    encode_sync,
    encode_unknown_effect,
    encode_unknown_exit,
    encode_unknown_option,
    encode_unknown_result,
    encode_unknown_sync,
    is_,
)
from pyfect.schema._primitives import (
    Any,
    BigInt,
    Boolean,
    Never,
    Null,
    Number,
    String,
    Unknown,
)
from pyfect.schema._schema import (
    Bottom,
    Codec,
    Decoder,
    Encoder,
    Schema,
    Top,
    is_schema,
)

__all__ = [
    "Any",
    "BigInt",
    "Boolean",
    "Bottom",
    "Codec",
    "Decoder",
    "Encoder",
    "Guard",
    "Never",
    "Null",
    "Number",
    "ParseOptions",
    "Parser",
    "Schema",
    "SchemaError",
    "String",
    "Top",
    "Unknown",
    "asserts",
    "ast",
    "decode_effect",
    "decode_exit",
    "decode_option",
    "decode_result",
    "decode_sync",
    "decode_unknown_effect",
    "decode_unknown_exit",
    "decode_unknown_option",
    "decode_unknown_result",
    "decode_unknown_sync",
    "encode_effect",
    "encode_exit",
    "encode_option",
    "encode_result",
    "encode_sync",
    "encode_unknown_effect",
    "encode_unknown_exit",
    "encode_unknown_option",
    "encode_unknown_result",
    "encode_unknown_sync",
    "is_",
    "is_schema",
    "issue",
]
