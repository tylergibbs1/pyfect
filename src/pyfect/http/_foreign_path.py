"""The path a foreign handler (an ASGI app, a Web handler) is given must
split into the segments the router matched: ``%2F`` stays encoded, and a
dot segment, which the router matched literally but the handler may
resolve, is refused."""

from __future__ import annotations

import re
from urllib.parse import unquote

_ENCODED_SLASH = re.compile("(%2[fF])")


def decode_path(path: str) -> str:
    """``path`` percent-decoded but for ``%2F``."""
    pieces = _ENCODED_SLASH.split(path)
    return "".join(piece if i % 2 else unquote(piece) for i, piece in enumerate(pieces))


def has_dot_segment(path: str) -> bool:
    """Whether a segment of ``path`` is ``.`` or ``..`` once decoded, with
    ``\\`` as a separator too (WHATWG URLs and Windows paths split there)."""
    segments = decode_path(path).replace("\\", "/").split("/")
    return any(segment in (".", "..") for segment in segments)


__all__ = ["decode_path", "has_dot_segment"]
