"""Extended grapheme cluster boundaries (Unicode UAX #29) from ``unicodedata``,
for ``chat_markdown``'s cuts, which must never split what a reader sees as
one character (Effect uses ``Intl.Segmenter``).

The rules kept: CR LF, controls, Hangul syllables, Extend (marks, the zero
width joiner, variation selectors, emoji modifiers, tags), spacing marks, an
emoji ZWJ sequence, and regional indicator pairs. Prepend, which no chat
text in practice starts a cluster with, is left out.
"""

from __future__ import annotations

import re
import unicodedata
from bisect import bisect_right

_PRINTABLE_ASCII = re.compile("[ -~]+")

_ZWJ = 0x200D


def _is_control(code: int) -> bool:
    if code in (0x200C, _ZWJ):
        return False
    return unicodedata.category(chr(code)) in ("Cc", "Zl", "Zp", "Cf") or code in (0xD, 0xA)


def _is_extend(code: int) -> bool:
    return (
        unicodedata.category(chr(code)) in ("Mn", "Me", "Mc")
        or code in (0x200C, _ZWJ)
        or 0xFE00 <= code <= 0xFE0F
        or 0x1F3FB <= code <= 0x1F3FF
        or 0xE0020 <= code <= 0xE007F
        or 0xE0100 <= code <= 0xE01EF
    )


def _is_regional(code: int) -> bool:
    return 0x1F1E6 <= code <= 0x1F1FF


def _is_pictographic(code: int) -> bool:
    return (
        0x1F000 <= code <= 0x1FAFF
        or 0x2600 <= code <= 0x27BF
        or 0x2300 <= code <= 0x23FF
        or 0x2B00 <= code <= 0x2BFF
        or code in (0x00A9, 0x00AE, 0x203C, 0x2049, 0x2122, 0x2139, 0x3030, 0x303D)
    )


def _hangul(code: int) -> str | None:
    if 0x1100 <= code <= 0x115F or 0xA960 <= code <= 0xA97C:
        return "L"
    if 0x1160 <= code <= 0x11A7 or 0xD7B0 <= code <= 0xD7C6:
        return "V"
    if 0x11A8 <= code <= 0x11FF or 0xD7CB <= code <= 0xD7FB:
        return "T"
    if 0xAC00 <= code <= 0xD7A3:
        return "LV" if (code - 0xAC00) % 28 == 0 else "LVT"
    return None


def _hangul_joins(before: str | None, after: str | None) -> bool:
    if before is None or after is None:
        return False
    if before == "L":
        return after in ("L", "V", "LV", "LVT")
    if before in ("LV", "V"):
        return after in ("V", "T")
    return before in ("LVT", "T") and after == "T"


def starts(text: str) -> list[int]:
    """The index of every cluster's first code point, in order."""
    found: list[int] = []
    previous: int | None = None
    regional_run = 0
    # Whether the text before the current position is a pictographic emoji
    # followed by extends, so that a joiner then a pictograph continues it.
    emoji_run = False
    after_emoji_zwj = False
    index = 0
    while index < len(text):
        plain = _PRINTABLE_ASCII.match(text, index)
        if plain is not None:
            # Printable ASCII is no control, extend, regional indicator,
            # Hangul or pictograph, so each starts a cluster and ends any run.
            found.extend(range(index, plain.end()))
            index = plain.end()
            after_emoji_zwj = emoji_run = False
            regional_run = 0
            previous = ord(text[index - 1])
            continue
        code = ord(text[index])
        if previous is None:
            joins = False
        elif previous == 0xD and code == 0xA:
            joins = True
        elif _is_control(previous) or _is_control(code):
            joins = False
        elif (
            _hangul_joins(_hangul(previous), _hangul(code))
            or _is_extend(code)
            or (after_emoji_zwj and _is_pictographic(code))
        ):
            joins = True
        elif _is_regional(previous) and _is_regional(code):
            joins = regional_run % 2 == 1
        else:
            joins = False
        if not joins:
            found.append(index)
        after_emoji_zwj = emoji_run and code == _ZWJ
        if _is_pictographic(code):
            emoji_run = True
        elif not _is_extend(code):
            emoji_run = False
        regional_run = regional_run + 1 if _is_regional(code) else 0
        previous = code
        index += 1
    return found


def start_at(clusters: list[int], text: str, cut: int) -> int:
    """The cluster boundary at or before ``cut``."""
    if not 0 < cut < len(text):
        return cut
    return clusters[bisect_right(clusters, cut) - 1]


def end_of(clusters: list[int], text: str, index: int) -> int:
    """The end of the cluster that holds ``index``."""
    following = bisect_right(clusters, index)
    return clusters[following] if following < len(clusters) else len(text)
