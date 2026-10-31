"""Schemas carried as bytes: an event's payload, a write request, a
batch of changes.

Effect writes these with ``SchemaBinary``, which pyfect does not port;
here a value is its schema's JSON encoding (``S.to_codec_json``) as UTF-8
text. Peers and journals written by Effect cannot be read.
"""

from __future__ import annotations

from typing import Any

from pyfect import schema as S
from pyfect._js import text_encode
from pyfect.exit import Exit, Success
from pyfect.exit import fail as fail_exit
from pyfect.schema import getter as G
from pyfect.schema import transformation as T
from pyfect.schema.issue import InvalidValue, Issue, reported

type BytesCodec[A] = S.Codec[A, bytes, Any, Any]


def _decode_utf8(data: bytes, options: S.ParseOptions) -> Exit[str, Issue]:
    try:
        return Success(data.decode())
    except UnicodeDecodeError:
        return fail_exit(InvalidValue({"expected": "UTF-8 bytes"}, reported(data, options)))


_UTF8: T.Transformation[str, bytes] = T.Transformation(
    G.TransformEffect(_decode_utf8), G.transform(text_encode)
)
_TEXT = S.Bytes.pipe(S.decode_to(S.String, _UTF8))


def to_codec[A](schema: S.Codec[A, Any, Any, Any], /) -> BytesCodec[A]:
    """``schema`` read from and written to bytes."""
    return _TEXT.pipe(S.decode_to(S.from_json_string(S.to_codec_json(schema))))


__all__ = ["BytesCodec", "to_codec"]
