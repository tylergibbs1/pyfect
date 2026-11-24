"""The Markdown scanning ``chat_markdown`` splits by: code fences, lines,
block boundaries and cuts that fit a length."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass

from pyfect._js import text_encode
from pyfect.chat import _graphemes

# JavaScript's whitespace (``\\s``, ``String.prototype.trim``), which the cuts
# follow so that a part splits where Effect's does.
_SPACE = (
    "\t\n\v\f\r \u00a0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009"
    "\u200a\u2028\u2029\u202f\u205f\u3000\ufeff"
)
_LAST_WORD = re.compile(f"[{_SPACE}][^{_SPACE}]*$")
_FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")
_HOLD_LIMIT = 300  # Past this many held characters, a held line is released to its last space.


@dataclass(frozen=True)
class Fence:
    """An open code fence: its marker and the line that opened it."""

    marker: str
    line: str


@dataclass(frozen=True)
class Line:
    end: int  # The index after the line's newline.
    fence: Fence | None  # The fence open after the line.
    closed: bool  # The line closes a fence.
    boundary: bool  # A part can end after it: outside a fence, and blank or closing one.


def is_blank(text: str) -> bool:
    return text.strip(_SPACE) == ""


def _fence_after(fence: Fence | None, line: str) -> tuple[Fence | None, bool]:
    match = _FENCE.match(line)
    if match is None:
        return fence, False
    marker, info = match.group(1), match.group(2)
    if fence is None:
        if marker[0] == "`" and "`" in info:
            return None, False
        return Fence(marker, line.lstrip(_SPACE)), False
    if marker[0] == fence.marker[0] and len(marker) >= len(fence.marker) and is_blank(info):
        return None, True
    return fence, False


def scan_lines(text: str, fence: Fence | None, complete: bool) -> list[Line]:
    """The lines of ``text`` read from a state of ``fence``; only complete
    lines count, unless ``complete`` says the text is finished."""
    lines: list[Line] = []
    start = 0
    while start < len(text):
        newline = text.find("\n", start)
        if newline == -1 and not complete:
            break
        end = len(text) if newline == -1 else newline + 1
        line = text[start : len(text) if newline == -1 else newline].removesuffix("\r")
        fence, closed = _fence_after(fence, line)
        lines.append(Line(end, fence, closed, fence is None and (closed or is_blank(line))))
        start = end
    return lines


def fence_at(lines: list[Line], initial: Fence | None, index: int) -> Fence | None:
    fence = initial
    for line in lines:
        if line.end > index:
            break
        fence = line.fence
    return fence


def closing(fence: Fence | None, markdown: str) -> str:
    if fence is None:
        return ""
    return ("" if markdown == "" or markdown.endswith("\n") else "\n") + fence.marker


def reopening(fence: Fence | None) -> str:
    return "" if fence is None else fence.line + "\n"


def render(prefix: str, text: str, fence: Fence | None) -> str:
    """Markdown for ``text`` written as a whole message: an open fence is
    closed."""
    markdown = prefix + text
    return markdown + closing(fence_at(scan_lines(text, fence, True), fence, len(text)), markdown)


def fit_cut(
    measure: Callable[[str], int], text: str, fence: Fence | None, prefix: str, room: int
) -> int:
    """Where to cut ``text`` so that ``prefix``, the cut text and a closing
    fence measure at most ``room``: a fitting block boundary, else after the
    last line, else after the last whitespace, else at the last character.
    Never inside a grapheme cluster, and never at 0."""
    lines = scan_lines(text, fence, False)

    def fits(cut: int) -> bool:
        markdown = prefix + text[:cut]
        return measure(markdown + closing(fence_at(lines, fence, cut), markdown)) <= room

    low, high = 0, len(text)
    while low < high:
        middle = (low + high + 1) // 2
        if fits(middle):
            low = middle
        else:
            high = middle - 1
    most = low
    # Closing a fence removes the synthetic suffix. Look ahead two real closes beyond the
    # estimate, farthest first, to bound the extra measurements.
    closes = [line for line in lines if line.closed and line.end > most][:2]
    candidates = [line.end for line in reversed(closes)]
    candidates += [line.end for line in reversed(lines) if line.boundary and line.end <= most]
    candidates += [line.end for line in reversed(lines) if line.end <= most]
    for i in range(most - 1, 0, -1):
        if text[i] in _SPACE:
            candidates.append(i + 1)
            break
    candidates.append(most)
    clusters = _graphemes.starts(text)
    for candidate in candidates:
        cut = _graphemes.start_at(clusters, text, candidate)
        if cut > 0 and fits(cut):
            return cut
    # Not even one cluster fits: the cut goes after the first, and the write fails TooLarge.
    return _graphemes.start_at(clusters, text, most) or _graphemes.end_of(clusters, text, 0)


def last_content_start(text: str) -> int:
    """Where the last cluster of ``text`` that is not whitespace starts, or
    -1 for blank text."""
    end = len(text.rstrip(_SPACE))
    if end == 0:
        return -1
    return _graphemes.start_at(_graphemes.starts(text), text, end - 1)


def releasable(pending: str, fence: Fence | None) -> str:
    """What an append may send of ``pending`` before the input is finished:
    up to the last complete line, unless inside a code fence."""
    lines = scan_lines(pending, fence, False)
    complete = lines[-1].end if lines else 0
    if complete == len(pending):
        return pending
    if fence_at(lines, fence, complete) is None:
        tail = pending[complete:]
        if len(tail) <= _HOLD_LIMIT:
            return pending[:complete]
        space = _LAST_WORD.search(tail)
        if space is not None:
            return pending[: complete + space.start() + 1]
    # The next delta may still extend the trailing cluster, even inside a fence; a split
    # surrogate may complete a code point that extends the cluster before it.
    text = pending[:-1] if pending and 0xD800 <= ord(pending[-1]) <= 0xDBFF else pending
    clusters = _graphemes.starts(text)
    return pending[: clusters[-1] if clusters else 0]


def well_formed(text: str) -> str:
    """``text`` with lone surrogates replaced by U+FFFD, as UTF-8 needs."""
    return "".join("�" if 0xD800 <= ord(c) <= 0xDFFF else c for c in text)


def utf8_length(text: str) -> int:
    return len(text_encode(text))
