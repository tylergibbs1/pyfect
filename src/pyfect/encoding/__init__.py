"""Framers: channels between bytes or text and the values they frame
(Effect's ``effect/encoding``).

- ``ndjson``: newline-delimited JSON.
- ``json_array``: the elements of one JSON array, streamed.
- ``sse``: Server-Sent Events.
- ``ini``: INI text to nested dicts (``parse``).
- ``yaml``: one YAML document to Python values (``parse``).
- ``toml``: TOML text to nested dicts (``parse``).
- ``schema_binary``: a compact binary codec derived from a schema's encoded
  side, byte-compatible with Effect's ``SchemaBinary``.
- ``base64``, ``base64_url``, ``hex``: binary-to-text codecs whose ``decode``
  returns a ``Result`` with an ``EncodingError`` (``encoding_error``).

Each module's decoders and encoders are channels; put a stream through
one with ``Stream.pipe_through_channel``::

    from pyfect.encoding import ndjson

    records = byte_stream.pipe_through_channel(ndjson.decode())
"""

from pyfect._json_text import Json
from pyfect.encoding import (
    base64,
    base64_url,
    encoding_error,
    hex,
    ini,
    json_array,
    ndjson,
    schema_binary,
    sse,
    toml,
    yaml,
)
from pyfect.encoding.encoding_error import EncodingError

__all__ = [
    "EncodingError",
    "Json",
    "base64",
    "base64_url",
    "encoding_error",
    "hex",
    "ini",
    "json_array",
    "ndjson",
    "schema_binary",
    "sse",
    "toml",
    "yaml",
]
