"""A tool's ``to_model_output`` parts as MCP tool content (Effect's ``modelOutputContent``).

Text is text. A file at an ``http(s)`` URL is a ``resource_link`` from 2025-06-18, else its
URL as text. An image (and from 2025-03-26 an audio clip) given as bytes, base64 or a base64
data URL is an image or audio block. Anything else is the text placeholder of
``tool_model_output_to_text``.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from pyfect._url import Url
from pyfect.ai.mcp_schema import ContentBlock
from pyfect.ai.prompt import FilePart, TextPart, ToolModelOutputPart, tool_model_output_to_text
from pyfect.encoding import base64
from pyfect.result import Ok

_HTTP_URL = re.compile(r"^https?://", re.IGNORECASE)
_DATA_URL_PREFIX = re.compile(r"^data:[^,]*;base64,", re.IGNORECASE)


def model_output_content(
    parts: Sequence[ToolModelOutputPart], protocol_version: str
) -> list[ContentBlock]:
    return [_block(part, protocol_version) for part in parts]


def _block(part: ToolModelOutputPart, protocol_version: str) -> ContentBlock:
    if isinstance(part, TextPart):
        return {"type": "text", "text": part.text}
    url = _url(part)
    if url is not None:
        if protocol_version >= "2025-06-18":
            name = url if part.file_name is None else part.file_name
            return {"type": "resource_link", "uri": url, "name": name, "mimeType": part.media_type}
        return {"type": "text", "text": url}
    media_type = part.media_type
    data = _bytes(part)
    if data is not None and media_type.startswith("image/"):
        return {"type": "image", "data": base64.encode(data), "mimeType": media_type}
    if data is not None and media_type.startswith("audio/") and protocol_version >= "2025-03-26":
        return {"type": "audio", "data": base64.encode(data), "mimeType": media_type}
    return {"type": "text", "text": tool_model_output_to_text([part])}


def _url(part: FilePart) -> str | None:
    data = part.data
    text = data.href if isinstance(data, Url) else data if isinstance(data, str) else None
    return text if text is not None and _HTTP_URL.match(text) else None


def _bytes(part: FilePart) -> bytes | None:
    data = part.data
    if isinstance(data, bytes):
        return data
    if isinstance(data, str):
        decoded = base64.decode(_DATA_URL_PREFIX.sub("", data, count=1))
        return decoded.value if isinstance(decoded, Ok) else None
    return None


__all__ = ["model_output_content"]
