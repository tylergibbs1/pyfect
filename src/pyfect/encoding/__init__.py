"""Framers: channels between bytes or text and the values they frame
(Effect's ``effect/encoding``).

- ``ndjson``: newline-delimited JSON.
- ``json_array``: the elements of one JSON array, streamed.
- ``sse``: Server-Sent Events.
- ``ini``: INI text to nested dicts (``parse``).
- ``yaml``: one YAML document to Python values (``parse``).

Each module's decoders and encoders are channels; put a stream through
one with ``Stream.pipe_through_channel``::

    from pyfect.encoding import ndjson

    records = byte_stream.pipe_through_channel(ndjson.decode())
"""

from pyfect._json_text import Json
from pyfect.encoding import ini, json_array, ndjson, sse, yaml

__all__ = ["Json", "ini", "json_array", "ndjson", "sse", "yaml"]
