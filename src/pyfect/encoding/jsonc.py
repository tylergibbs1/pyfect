"""JSON with comments to Python values (Effect's ``encoding/Jsonc``), without
dependencies: the [JSONC draft](https://jsonc.org/) with ``jsonc-parser``
3.3.1's default profile, JSON plus line and block comments, no trailing
commas. One leading byte order mark is skipped. Values are read as pyfect
reads JSON (``JSON.parse``)::

    jsonc.parse('{ "port": 8080 } // comment')  # Ok({"port": 8080})
"""

from __future__ import annotations

import re

from pyfect._binary_codecs import EncodingError
from pyfect._json_text import PARSE_ERRORS
from pyfect._json_text import parse as parse_json
from pyfect.encoding import _json_parser
from pyfect.result import Err, Ok, Result

_LINE_END = re.compile("[\r\n]")


def _strip_comments(text: str) -> str | None:  # noqa: PLR0912 - Effect's scan, kept whole
    """``text`` with each comment outside strings replaced by a space (so
    it cannot join the tokens around it), or ``None`` for an unterminated
    block comment."""
    slash = text.find("/")
    if slash == -1:
        return text
    parts: list[str] = []
    start = 0
    quote = text.find('"')
    while slash != -1:
        if quote != -1 and quote < slash:
            # Skip the string; a quote after an odd run of backslashes is escaped.
            end = quote
            while True:
                end = text.find('"', end + 1)
                if end == -1:
                    break
                backslash = end - 1
                while backslash >= 0 and text[backslash] == "\\":
                    backslash -= 1
                if (end - backslash) % 2 == 1:
                    break
            if end == -1:
                break
            quote = text.find('"', end + 1)
            if slash < end:
                slash = text.find("/", end + 1)
            continue
        following = text[slash + 1 : slash + 2]
        if following == "/":
            line_end = _LINE_END.search(text, slash + 2)
            index = len(text) if line_end is None else line_end.start()
        elif following == "*":
            end = text.find("*/", slash + 2)
            if end == -1:
                return None
            index = end + 2
        else:
            # Not a comment; the JSON parser rejects it.
            slash = text.find("/", slash + 1)
            continue
        parts.append(text[start:slash] + " ")
        start = index
        slash = text.find("/", index)
        if quote != -1 and quote < index:
            quote = text.find('"', index)
    parts.append(text[start:])
    return "".join(parts)


def _parse(text: str) -> object:
    # One leading BOM is ignored without shifting the positions of errors.
    if text.startswith("\ufeff"):
        text = " " + text[1:]
    stripped = _strip_comments(text)
    if stripped is not None:
        try:
            return parse_json(stripped)
        except PARSE_ERRORS:
            pass
    # The strict parser accepts what JSON.parse accepts once comments are
    # removed; it locates the error (and reads nesting too deep for ``json``).
    return _json_parser.parse(text, "JSONC")


def parse(text: str, /) -> Result[object, EncodingError]:
    """The value of a JSONC document, or an ``EncodingError`` whose message
    gives the line and column (in UTF-16 code units) without quoting the
    text. Trailing commas and JSON5 extensions are errors."""
    try:
        return Ok(_parse(text))
    except ValueError as error:
        return Err(EncodingError(kind="Decode", module="Jsonc", input=text, message=str(error)))


__all__ = ["parse"]
