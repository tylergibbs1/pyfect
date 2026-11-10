"""JSON-RPC messages as the transports write and read them: JSON text.

stdio, HTTP event streams and ``mcp_test`` all go through ``write`` and
``read``, so a message reaches the other side as JSON values (lists, not
tuples; ``1`` for ``1.0``) whichever transport carries it."""

from __future__ import annotations

from typing import NewType

from pyfect import _json_text

Frame = NewType("Frame", str)
"""One message written as JSON text."""


def write(message: object) -> Frame:
    """``message`` as JSON text, written as JavaScript writes it."""
    return Frame(_json_text.stringify(message))


def read(frame: str) -> _json_text.Json:
    """The message ``frame`` holds; ``ValueError`` when it is not JSON."""
    return _json_text.parse(frame)
