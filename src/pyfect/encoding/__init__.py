"""Framers: channels between bytes or text and the values they frame
(Effect's ``effect/encoding``).

- ``ndjson``: newline-delimited JSON.
- ``json_array``: the elements of one JSON array, streamed.
- ``sse``: Server-Sent Events.

Each module's decoders and encoders are channels; put a stream through
one with ``Stream.pipe_through_channel``::

    from pyfect.encoding import ndjson

    records = byte_stream.pipe_through_channel(ndjson.decode())
"""

from pyfect.encoding import json_array, ndjson, sse
from pyfect.encoding._json import Json

__all__ = ["Json", "json_array", "ndjson", "sse"]
