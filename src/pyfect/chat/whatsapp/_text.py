"""Markdown to WhatsApp text (Effect's ``chat-whatsapp/internal/text.ts``).

Each construct the renderer knows has a candidate replacement, rendered
bottom-up, which is emitted only when it is no longer than the construct's
source in code points, UTF-16 units and UTF-8 bytes. Otherwise the source is
emitted as it is. Text between constructs is always kept, so the output is
never longer than the input in any of the three units.

Effect's scanner looks ahead from every unmatched delimiter, bracket and
backtick run, which is quadratic on text built for it, and recurses once per
nesting level. Here every step of a scan is counted against a budget linear
in the input, and nesting is capped: past either, the Markdown is sent as
typed, which the rule above allows. Ordinary Markdown never comes near.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from pyfect._js import text_encode

MESSAGE_LENGTH = 4096
"""The longest text message, and the measure's unit: UTF-16 code units, which
are never fewer than the code points Meta counts."""

SHORT_BODY_LENGTH = 1024
"""The longest caption, and the longest body beside reply buttons or a link
button."""

MAX_NESTING = 16
"""Emphasis and link labels nested deeper than this are kept as typed."""

_BUDGET_PER_CHAR = 64
_BUDGET_BASE = 4096


def utf16_length(text: str) -> int:
    """JavaScript's ``length``: UTF-16 code units."""
    return len(text.encode("utf-16-le", "surrogatepass")) // 2


def measure(markdown: str) -> int:
    """What a Markdown string costs against ``MESSAGE_LENGTH``: its UTF-16
    length."""
    return utf16_length(markdown)


def utf8_bytes(text: str) -> int:
    """The UTF-8 length of ``text``, a lone surrogate as U+FFFD (three bytes)."""
    return len(text_encode(text))


def fits(candidate: str, source: str) -> bool:
    """Whether ``candidate`` is no longer than ``source`` in all three units."""
    return (
        len(candidate) <= len(source)
        and utf16_length(candidate) <= utf16_length(source)
        and utf8_bytes(candidate) <= utf8_bytes(source)
    )


def _pick(candidate: str, source: str) -> str:
    return candidate if fits(candidate, source) else source


class _TooCostly(Exception):
    """The budget ran out: the Markdown goes as typed."""


class _Budget:
    __slots__ = ("left",)

    def __init__(self, size: int) -> None:
        self.left = _BUDGET_BASE + _BUDGET_PER_CHAR * size

    def spend(self, steps: int = 1) -> None:
        self.left -= steps
        if self.left < 0:
            raise _TooCostly


# JavaScript's ``\s`` and ``trim``: whitespace and line terminators.
_JS_SPACE = (
    "\t\n\x0b\x0c\r \xa0\u1680\u2000\u2001\u2002\u2003\u2004\u2005"
    "\u2006\u2007\u2008\u2009\u200a\u2028\u2029\u202f\u205f\u3000\ufeff"
)
_S = f"[{_JS_SPACE}]"
_NOT_S = f"[^{_JS_SPACE}"
# JavaScript's ``.``: anything but a line terminator.
_DOT = "[^\n\r\u2028\u2029]"

# The characters WhatsApp formats with, which a decoded reference must not produce.
_FORMATTING = frozenset("*_~`")

_ENTITIES = {
    "amp": "&",
    "lt": "<",
    "gt": ">",
    "quot": '"',
    "apos": "'",
    "nbsp": "\xa0",
    "copy": "©",
    "reg": "®",
    "trade": "™",
    "hellip": "…",
    "mdash": "—",
    "ndash": "\u2013",
    "lsquo": "\u2018",
    "rsquo": "\u2019",
    "ldquo": "“",
    "rdquo": "”",
    "laquo": "«",
    "raquo": "»",
    "bull": "•",
    "middot": "·",
    "deg": "°",
    "plusmn": "±",
    "times": "\xd7",
    "divide": "÷",
    "minus": "\u2212",
    "euro": "€",
    "pound": "£",
    "yen": "¥",
    "cent": "¢",
    "sect": "§",
    "para": "¶",
    "larr": "←",
    "rarr": "→",
    "uarr": "↑",
    "darr": "↓",
    "harr": "↔",
    "lArr": "⇐",
    "rArr": "⇒",
    "hArr": "⇔",
    "le": "≤",
    "ge": "≥",
    "ne": "≠",
    "asymp": "≈",
    "infin": "∞",
    "frac12": "½",
    "frac14": "¼",
    "frac34": "¾",
    "iexcl": "¡",
    "iquest": "¿",
}


def js_trim(text: str) -> str:
    """JavaScript's ``String.prototype.trim``."""
    return text.strip(_JS_SPACE)


def _decode_reference(reference: str) -> str | None:
    body = reference[1:-1]
    if body.startswith("#"):
        hexadecimal = body[1:2] in ("x", "X")
        code = int(body[2:], 16) if hexadecimal else int(body[1:], 10)  # noqa: FURB166
        decoded = (
            "\ufffd" if code == 0 or code > 0x10FFFF or 0xD800 <= code <= 0xDFFF else chr(code)
        )
    else:
        decoded = _ENTITIES.get(body)
    return None if decoded is None or decoded in _FORMATTING else decoded


def _is_whitespace(char: str | None) -> bool:
    return char is None or char in _JS_SPACE


def _is_punctuation(char: str | None) -> bool:
    # A character outside the Basic Multilingual Plane is two UTF-16 units in Effect,
    # and a lone unit is neither punctuation nor a symbol.
    return char is not None and ord(char) <= 0xFFFF and unicodedata.category(char)[0] in ("P", "S")


def _is_ascii_punctuation(char: str | None) -> bool:
    return char is not None and (
        "!" <= char <= "/" or ":" <= char <= "@" or "[" <= char <= "`" or "{" <= char <= "~"
    )


def _left_flanking(before: str | None, after: str | None) -> bool:
    return not _is_whitespace(after) and (
        not _is_punctuation(after) or _is_whitespace(before) or _is_punctuation(before)
    )


def _right_flanking(before: str | None, after: str | None) -> bool:
    return not _is_whitespace(before) and (
        not _is_punctuation(before) or _is_whitespace(after) or _is_punctuation(after)
    )


_AUTOLINK = re.compile(rf"<([A-Za-z][A-Za-z0-9+.-]{{1,31}}:{_NOT_S}<>]*)>")
_EMAIL_AUTOLINK = re.compile(
    r"<([A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
    r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)*+)>"
)
_HTML_TAG = re.compile(rf"</?[A-Za-z][A-Za-z0-9-]*(?:{_S}[^<>]*)?/?>")
_REFERENCE = re.compile(r"&(?:#[0-9]{1,7};|#[xX][0-9A-Fa-f]{1,6};|[A-Za-z][A-Za-z0-9]{1,31};)")


@dataclass(frozen=True, slots=True)
class _Atom:
    end: int
    text: str


class _Inline:
    """One string of inline Markdown, rendered at a nesting ``depth``. A
    position past either end reads as ``None``, as JavaScript's
    ``undefined``."""

    __slots__ = ("budget", "depth", "s")

    def __init__(self, s: str, depth: int, budget: _Budget) -> None:
        self.s = s
        self.depth = depth
        self.budget = budget

    def at(self, k: int) -> str | None:
        return self.s[k] if 0 <= k < len(self.s) else None

    def nested(self, text: str) -> str:
        return _render_inline(text, self.depth + 1, self.budget)

    def run_length(self, i: int, char: str) -> int:
        s = self.s
        j = i
        while j < len(s) and s[j] == char:
            j += 1
        self.budget.spend(j - i)
        return j - i

    def find(self, needle: str, start: int) -> int:
        found = self.s.find(needle, start)
        self.budget.spend((len(self.s) if found < 0 else found) - start)
        return found

    def code_span(self, i: int) -> _Atom:
        """A code span from the backtick run at ``i``, or the run itself when
        it has no match."""
        s = self.s
        n = self.run_length(i, "`")
        j = i + n
        while j < len(s):
            self.budget.spend()
            if s[j] != "`":
                j += 1
                continue
            m = self.run_length(j, "`")
            if m == n:
                return _Atom(j + m, s[i : j + m])
            j += m
        return _Atom(i + n, s[i : i + n])

    def close_bracket(self, i: int) -> int:
        """The index of the ``]`` closing the ``[`` at ``i``, skipping escapes
        and code spans."""
        s = self.s
        depth = 0
        j = i
        while j < len(s):
            self.budget.spend()
            char = s[j]
            if char == "\\":
                j += 2
            elif char == "`":
                j = self.code_span(j).end
            else:
                if char == "[":
                    depth += 1
                elif char == "]":
                    depth -= 1
                    if depth == 0:
                        return j
                j += 1
        return -1

    def destination(self, i: int) -> tuple[str, int] | None:  # noqa: PLR0912
        """An inline destination and optional title from the ``(`` at ``i``:
        the URL and the index after ``)``."""
        s = self.s
        at = self.at
        j = i + 1
        while at(j) in (" ", "\t"):
            j += 1
        if at(j) == "<":
            close = self.find(">", j)
            if close < 0 or "<" in s[j + 1 : close]:
                return None
            url = s[j + 1 : close]
            j = close + 1
        else:
            start = j
            depth = 0
            while j < len(s) and s[j] not in _JS_SPACE:
                self.budget.spend()
                if s[j] == "\\" and _is_ascii_punctuation(at(j + 1)):
                    j += 1
                elif s[j] == "(":
                    depth += 1
                elif s[j] == ")":
                    if depth == 0:
                        break
                    depth -= 1
                j += 1
            if depth != 0:
                return None
            url = s[start:j]
        after_url = j
        while at(j) in (" ", "\t"):
            j += 1
        opener = at(j)
        if j > after_url and opener in ('"', "'", "("):
            close = ")" if opener == "(" else opener
            k = j + 1
            while k < len(s) and s[k] != close:
                self.budget.spend()
                k += 2 if s[k] == "\\" else 1
            if k >= len(s):
                return None
            j = k + 1
            while at(j) in (" ", "\t"):
                j += 1
        return (url, j + 1) if at(j) == ")" else None

    def link(self, start: int, i: int) -> _Atom | None:
        """A link or image from the ``[`` at ``i``, ``start`` being the ``!``
        of an image."""
        s = self.s
        if self.at(i + 1) == "^":
            close = self.find("]", i)
            return None if close < 0 else _Atom(close + 1, s[start : close + 1])
        close = self.close_bracket(i)
        if close < 0:
            return None
        if self.at(close + 1) == "[":
            end = self.find("]", close + 1)
            return None if end < 0 else _Atom(end + 1, s[start : end + 1])
        # A shortcut reference, or plain brackets: either way it is kept as typed.
        verbatim = _Atom(close + 1, s[start : close + 1])
        if self.at(close + 1) != "(":
            return verbatim
        target = self.destination(close + 1)
        if target is None:
            return verbatim
        url, end = target
        label = s[i + 1 : close]
        shown = label if start < i else self.nested(label)
        candidate = url if label in ("", url) else f"{shown} ({url})"
        return _Atom(end, _pick(candidate, s[start:end]))

    def atom(self, i: int) -> _Atom | None:  # noqa: PLR0911
        """The construct at ``i`` that is kept or replaced as a whole, if any."""
        s = self.s
        char = s[i]
        if char == "\\":
            return _Atom(i + 2, s[i : i + 2]) if _is_ascii_punctuation(self.at(i + 1)) else None
        if char == "`":
            return self.code_span(i)
        if char == "<":
            match = _AUTOLINK.match(s, i) or _EMAIL_AUTOLINK.match(s, i)
            if match is not None:
                self.budget.spend(match.end() - i)
                return _Atom(match.end(), _pick(match.group(1), match.group(0)))
            if s.startswith("<!--", i):
                close = self.find("-->", i + 4)
                return None if close < 0 else _Atom(close + 3, s[i : close + 3])
            tag = _HTML_TAG.match(s, i)
            if tag is None:
                return None
            self.budget.spend(tag.end() - i)
            return _Atom(tag.end(), tag.group(0))
        if char == "!":
            return self.link(i, i + 1) if self.at(i + 1) == "[" else None
        if char == "[":
            return self.link(i, i)
        if char == "&":
            match = _REFERENCE.match(s, i, min(len(s), i + 40))
            if match is None:
                return None
            decoded = _decode_reference(match.group(0))
            text = match.group(0) if decoded is None else _pick(decoded, match.group(0))
            return _Atom(match.end(), text)
        return None

    def can_open(self, i: int, n: int) -> bool:
        before, after = self.at(i - 1), self.at(i + n)
        left = _left_flanking(before, after)
        if self.s[i] == "_":
            return left and (not _right_flanking(before, after) or _is_punctuation(before))
        return left

    def can_close(self, i: int, n: int) -> bool:
        before, after = self.at(i - 1), self.at(i + n)
        right = _right_flanking(before, after)
        if self.s[i] == "_":
            return right and (not _left_flanking(before, after) or _is_punctuation(after))
        return right

    def emphasis(self, i: int) -> _Atom | None:
        """Emphasis or strikethrough from the delimiter run at ``i``, if it has
        a closer."""
        s = self.s
        char = s[i]
        n = self.run_length(i, char)
        if n > 2 or not self.can_open(i, n):
            return None
        j = i + n
        while j < len(s):
            self.budget.spend()
            skipped = None if s[j] in ("*", "_", "~") else self.atom(j)
            if skipped is not None:
                j = skipped.end
                continue
            if s[j] != char:
                j += 1
                continue
            m = self.run_length(j, char)
            if m == n and j > i + n and self.can_close(j, m):
                marker = "~" if char == "~" else "*" if n == 2 else "_"
                candidate = marker + self.nested(s[i + n : j]) + marker
                return _Atom(j + m, _pick(candidate, s[i : j + m]))
            j += m
        return None

    def render(self) -> str:
        s = self.s
        out: list[str] = []
        i = 0
        while i < len(s):
            self.budget.spend()
            char = s[i]
            delimiter = char in ("*", "_", "~")
            found = self.emphasis(i) if delimiter else self.atom(i)
            if found is not None:
                out.append(found.text)
                i = found.end
            elif delimiter:
                n = self.run_length(i, char)
                out.append(s[i : i + n])
                i += n
            else:
                out.append(char)
                i += 1
        return "".join(out)


def _render_inline(s: str, depth: int, budget: _Budget) -> str:
    if depth > MAX_NESTING:
        return s
    return _Inline(s, depth, budget).render()


def inline(s: str) -> str:
    """One line of inline Markdown."""
    try:
        return _render_inline(s, 0, _Budget(len(s)))
    except _TooCostly:
        return s


# --- blocks ---------------------------------------------------------------------------
# Every pattern is matched at a position with ``match`` or ``fullmatch`` (``^`` and
# ``$`` would not anchor there), so no line is copied to be matched.

_FENCE_OPEN = re.compile(rf"( {{0,3}})(`{{3,}}|~{{3,}})({_DOT}*)")
_ATX_HEADING = re.compile(rf" {{0,3}}(#{{1,6}})(?:[ \t]+({_DOT}*))?")
_SETEXT_UNDERLINE = re.compile(r" {0,3}(?:=+|-+)[ \t]*")
_THEMATIC_BREAK = re.compile(r" {0,3}([-*_])(?:[ \t]*+\1){2,}+[ \t]*+")
_DEFINITION = re.compile(r" {0,3}\[[^\]]+\]:")
_BLOCK_START = re.compile(
    r"(?: {4}|\t| {0,3}(?:[>#|]|[-*+](?:[ \t]|\Z)|[0-9]{1,9}[.)](?:[ \t]|\Z)|`{3}|~{3}))"
)
_TABLE_DELIMITER = re.compile(
    r" {0,3}\|?[ \t]*+:?-++:?[ \t]*+(?:\|[ \t]*+:?-++:?[ \t]*+)*+\|?[ \t]*+"
)
_QUOTE_MARKER = re.compile(r" {0,3}>[ \t]?")
_LIST_MARKER = re.compile(r"( {0,3}(?:[-*+]|[0-9]{1,9}[.)]))([ \t]+|\Z)")
_EXPANDED_PREFIX = re.compile(r"[ >\-*+.)0-9\t]*")


def _cells(row: str) -> int:
    trimmed = js_trim(row)
    trimmed = trimmed.removeprefix("|")
    trimmed = trimmed.removesuffix("|")
    return trimmed.count("|") + 1


def _is_blank(text: str, pos: int = 0) -> bool:
    return not text[pos:].strip(_JS_SPACE)


def _containers(line: str, budget: _Budget) -> tuple[list[int], int]:
    """The quotes and list items a line opens, outermost first, and where the
    rest of the line starts. A quote is 0, and a list item the indentation its
    content needs."""
    stack: list[int] = []
    pos = 0
    while True:
        budget.spend()
        quote = _QUOTE_MARKER.match(line, pos)
        if quote is not None:
            stack.append(0)
            pos = quote.end()
            continue
        item = _LIST_MARKER.match(line, pos)
        if item is None or _THEMATIC_BREAK.fullmatch(line, pos) is not None:
            break
        marker, spaces = item.group(1), item.group(2)
        # Five spaces or more after the marker start indented code, whose content starts after one.
        whole = item.end() - pos
        width = len(marker) + 1 if spaces == "" or len(spaces) >= 5 else whole
        stack.append(width)
        pos += min(width, whole)
    return stack, pos


def _expand_indent(line: str) -> str:
    """A line with the tabs of its indentation and container markers expanded
    to the next multiple of four columns, so a tab only partly taken by a
    container leaves its other columns. Used to find blocks, never as output."""
    prefix_end = _EXPANDED_PREFIX.match(line).end()  # pyright: ignore[reportOptionalMemberAccess]
    if "\t" not in line[:prefix_end]:
        return line
    out: list[str] = []
    width = 0
    for char in line[:prefix_end]:
        if char == "\t":
            pad = 4 - width % 4
            out.append(" " * pad)
            width += pad
        else:
            out.append(char)
            width += 1
    return "".join(out) + line[prefix_end:]


def _inside(line: str, stack: list[int]) -> str | None:
    """What is left of a line inside the containers of ``stack``, or ``None``
    when the line ends one of them."""
    pos = 0
    for width in stack:
        if width == 0:
            quote = _QUOTE_MARKER.match(line, pos)
            if quote is None:
                return None
            pos = quote.end()
            continue
        if _is_blank(line, pos):
            return ""
        if not line.startswith(" " * width, pos):
            return None
        pos += width
    return line[pos:]


def _opens_block(line: str, budget: _Budget) -> bool:
    """Whether a line starts a block, which ends a definition or a table that
    was being kept as typed."""
    return (
        _FENCE_OPEN.fullmatch(line) is not None
        or _ATX_HEADING.fullmatch(line) is not None
        or _THEMATIC_BREAK.fullmatch(line) is not None
        or len(_containers(line, budget)[0]) > 0
    )


def _closes_fence(code: str, char: str, length: int) -> bool:
    """Whether ``code`` closes a fence of ``length`` ``char``: up to three
    spaces, at least ``length`` of ``char``, then only spaces and tabs."""
    i = len(code) - len(code.lstrip(" "))
    if i > 3:
        return False
    j = i
    while j < len(code) and code[j] == char:
        j += 1
    return j - i >= length and code[j:].strip(" \t") == ""


def _strip_closing_hashes(content: str) -> str:
    """``content`` without a closing sequence of ``#``: Effect's
    ``replace(/(?:^|[ \\t]+)#+[ \\t]*$/, "")``, without its backtracking."""
    k = len(content.rstrip(" \t"))
    h = len(content[:k].rstrip("#"))
    if h == k:
        return content
    if h == 0:
        return ""
    if content[h - 1] in " \t":
        return content[:h].rstrip(" \t")
    return content


def _split_lines(markdown: str) -> list[str]:
    """``markdown.split(/(?<=\\n)/)``: each line with its ``\\n``."""
    lines = markdown.split("\n")
    out = [line + "\n" for line in lines[:-1]]
    if lines[-1] != "" or not out:
        out.append(lines[-1])
    return out


def _render(markdown: str, budget: _Budget) -> str:  # noqa: PLR0912, PLR0915
    lines = _split_lines(markdown)

    def body(k: int) -> str:
        line = lines[k]
        if line.endswith("\r\n"):
            return line[:-2]
        return line.removesuffix("\n")

    def eol(k: int) -> str:
        return lines[k][len(body(k)) :]

    def inline_of(text: str) -> str:
        return _render_inline(text, 0, budget)

    out: list[str] = []
    i = 0
    while i < len(lines):
        budget.spend()
        line = body(i)
        expanded = _expand_indent(line)
        stack, rest_at = _containers(expanded, budget)
        rest = expanded[rest_at:]
        fence = _FENCE_OPEN.fullmatch(rest)
        if fence is not None and not (fence.group(2)[0] == "`" and "`" in fence.group(3)):
            # The closer is matched inside the opener's quotes and list items. A line outside
            # them ends the code too.
            char, length = fence.group(2)[0], len(fence.group(2))
            j = i + 1
            closed = False
            while j < len(lines):
                budget.spend()
                code = _inside(_expand_indent(body(j)), stack)
                if code is None:
                    break
                if _closes_fence(code, char, length):
                    closed = True
                    break
                j += 1
            if not closed:
                out.append("".join(lines[i:j]))
                i = j
                continue
            content = "".join(lines[i + 1 : j])
            source = "".join(lines[i : j + 1])
            candidate = "```" + eol(i) + content + "```" + eol(j)
            out.append(source if len(stack) > 0 or "```" in content else _pick(candidate, source))
            i = j + 1
            continue
        if _DEFINITION.match(rest) is not None:
            # A destination or title may continue on the next lines, up to a blank line or the
            # start of a block.
            out.append(lines[i])
            j = i + 1
            while j < len(lines):
                budget.spend()
                expanded_next = _expand_indent(body(j))
                inner = _inside(expanded_next, stack)
                next_line = expanded_next if inner is None else inner
                if _is_blank(next_line) or _opens_block(next_line, budget):
                    break
                out.append(lines[j])
                j += 1
            i = j
            continue
        if (
            i + 1 < len(lines)
            and "|" in line
            and _TABLE_DELIMITER.fullmatch(body(i + 1)) is not None
            and "|" in body(i + 1)
            and _cells(line) == _cells(body(i + 1))
        ):
            out.append(lines[i])
            j = i + 2
            while (
                j < len(lines)
                and not _is_blank(body(j))
                and not _opens_block(_expand_indent(body(j)), budget)
            ):
                budget.spend()
                out.append(lines[j])
                j += 1
            i = j
            continue
        heading = _ATX_HEADING.fullmatch(line)
        if heading is not None:
            content = js_trim(_strip_closing_hashes(heading.group(2) or ""))
            out.append((line if content == "" else _pick(f"*{inline_of(content)}*", line)) + eol(i))
            i += 1
            continue
        if (
            i + 1 < len(lines)
            and not _is_blank(line)
            and _BLOCK_START.match(line) is None
            and _THEMATIC_BREAK.fullmatch(line) is None
            and _DEFINITION.match(line) is None
            and (i == 0 or _is_blank(body(i - 1)))
            and _SETEXT_UNDERLINE.fullmatch(body(i + 1)) is not None
        ):
            source = line + eol(i) + body(i + 1)
            out.append(_pick(f"*{inline_of(js_trim(line))}*", source) + eol(i + 1))
            i += 2
            continue
        # Indented code, measured inside its quotes and list items with tabs expanded, is kept
        # as typed.
        if rest.startswith("    ") or _THEMATIC_BREAK.fullmatch(line) is not None:
            out.append(lines[i])
            i += 1
            continue
        # The text is cut from the line as typed, so the output keeps its tabs.
        text_at = _containers(line, budget)[1]
        out.append(line[:text_at] + inline_of(line[text_at:]) + eol(i))
        i += 1
    return "".join(out)


def render(markdown: str) -> str:
    """Markdown as WhatsApp text, never longer than the Markdown in code
    points, UTF-16 units or UTF-8 bytes. Past the work budget the Markdown is
    returned as typed."""
    try:
        return _render(markdown, _Budget(len(markdown)))
    except _TooCostly:
        return markdown
