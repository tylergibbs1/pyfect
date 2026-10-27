"""JSON Pointer tokens and URI fragments (RFC 6901, Effect's ``JsonPointer``).

A JSON Pointer separates tokens with ``/``, so a token escapes ``~`` as
``~0`` and ``/`` as ``~1``. A URI fragment percent-encodes the escaped
pointer as JavaScript's ``encodeURI`` does, with ``#`` encoded too::

    json_pointer.escape_token("a/b")                   # "a~1b"
    json_pointer.parse_uri_fragment("#/users/a~1b")    # ["users", "a/b"]
    json_pointer.format_uri_fragment(["a b", "Rate%"]) # "#/a%20b/Rate%25"
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from urllib.parse import quote

# What JavaScript's ``encodeURI`` leaves alone, besides letters and digits.
_URI_SAFE = ";,/?:@&=+$-_.!~*'()#"
_INVALID_ESCAPE = re.compile(r"~(?:[^01]|$)")
_PERCENT = re.compile(r"%([0-9A-Fa-f]{2})")


def escape_token(token: str) -> str:
    """``token`` with ``~`` as ``~0`` and ``/`` as ``~1`` (``~`` first, so
    nothing is escaped twice)."""
    return token.replace("~", "~0").replace("/", "~1")


def unescape_token(token: str) -> str:
    """The inverse of ``escape_token``: ``~1`` to ``/``, then ``~0`` to ``~``."""
    return token.replace("~1", "/").replace("~0", "~")


def _encode_uri(text: str) -> str:
    """JavaScript's ``encodeURI``. A lone surrogate raises ``ValueError``
    (Effect's ``URIError``)."""
    try:
        return quote(text, safe=_URI_SAFE, errors="strict")
    except UnicodeEncodeError as error:
        raise ValueError("URI malformed") from error


def _decode_uri_component(text: str) -> str:
    """JavaScript's ``decodeURIComponent``: a stray ``%`` or invalid UTF-8
    raises ``ValueError``."""
    if "%" in _PERCENT.sub("", text):
        raise ValueError("URI malformed")
    data = bytearray()
    position = 0
    for match in _PERCENT.finditer(text):
        data += text[position : match.start()].encode()
        data.append(int(match.group(1), 16))
        position = match.end()
    data += text[position:].encode()
    return data.decode()


def _format_uri_fragment_token(token: str) -> str:
    return _encode_uri(escape_token(token)).replace("#", "%23")


def _decode_uri_fragment(fragment: str) -> str | None:
    if fragment in ("", "#"):
        return ""
    if not fragment.startswith("#"):
        return None
    encoded = fragment[1:]
    try:
        if _encode_uri(encoded).replace("%25", "%").replace("#", "%23") != encoded:
            return None
        pointer = _decode_uri_component(encoded)
    except ValueError:
        return None
    if pointer.startswith("/") and not _INVALID_ESCAPE.search(pointer):
        return pointer
    return None


def parse_uri_fragment(fragment: str) -> list[str] | None:
    """The tokens of a JSON Pointer URI fragment (``""`` and ``"#"`` are the
    root, ``[]``), percent-decoded and then unescaped. ``None`` for anything
    that is not a fragment, holds a character needing percent-encoding, or
    has an invalid ``~`` escape."""
    pointer = _decode_uri_fragment(fragment)
    if pointer is None:
        return None
    if not pointer:
        return []
    return [unescape_token(token) for token in pointer[1:].split("/")]


def format_uri_fragment(path: Sequence[str]) -> str:
    """``path`` as a URI fragment: each token escaped, then percent-encoded;
    the empty path is ``"#"``. A token with a lone surrogate raises
    ``ValueError``."""
    return "#" + "".join(f"/{_format_uri_fragment_token(token)}" for token in path)
