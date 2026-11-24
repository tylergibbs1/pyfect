"""Rich Markdown for ``sendRichMessage`` (Effect's ``internal/markdown.ts``):
the escaping that keeps consumer Markdown from reaching Telegram's raw HTML,
images, math, spoilers and non-web links, and the ``measure`` that bounds
what it costs.

The port follows Effect line for line, with JavaScript's semantics where
Python's differ (``\\s``, ``.``, ``$``, ``trim``, ``i``, ``decodeURIComponent``),
and keeps it linear where Effect is not: a code span is found through an
index of backtick runs instead of a scan from every run, a line's thematic
break is tested once instead of once per spaced emphasis run, and every
match is anchored at a position instead of on a copied slice.
"""

from __future__ import annotations

import bisect
import re
from dataclasses import dataclass, field
from itertools import accumulate

BLOCK = 65
"""What one line break or block marker costs, so that a message in budget
stays under 500 blocks."""

RICH_LIMIT = 32_768
"""Telegram's rich message limit. It counts rendered characters, which
UTF-8 bytes of the source bound."""

FILES_PER_MESSAGE = 10
MAX_DEPTH = 16
"""The most nesting Telegram renders."""
MAX_COLUMNS = 20
"""The most table columns Telegram renders."""


def media_reference(n: int) -> str:
    """The reference to the ``n``th file of a post, at the end of the
    Markdown."""
    return f"\n\n![](tg://document?id=f{n})"


RESERVATION = FILES_PER_MESSAGE * (32 + BLOCK) + BLOCK + 8
"""What the budget keeps back for media references and the fence a post with
files may need to close."""

MESSAGE_LENGTH = RICH_LIMIT - RESERVATION

MAX_INLINE_NODES = 4000
"""The inline nodes one paragraph may hold. Telegram refuses a paragraph past
about 4,387."""

MAX_FOOTNOTE_REFERENCES = 700
"""The footnote references one message may hold."""

_FOOTNOTE_NODES = 3
_MAX_DESTINATION_DEPTH = 3
_MAX_LABEL_LENGTH = 999

_TWO_BYTE_ESCAPES = frozenset("$=|![]*_~`")
_BLOCK_MARKERS = frozenset(">-+*.)")

# JavaScript's ``\s``, which Python's differs from (U+001C to U+001F, U+0085).
_JS_SPACE = (
    "\t\n\x0b\x0c\r \xa0\u1680\u2000\u2001\u2002\u2003\u2004\u2005"
    "\u2006\u2007\u2008\u2009\u200a\u2028\u2029\u202f\u205f\u3000\ufeff"
)
_S = f"[{_JS_SPACE}]"
_NOT_S = f"[^{_JS_SPACE}]"
# JavaScript's ``.``: anything but a line terminator.
_DOT = "[^\n\r\u2028\u2029]"


def js_trim(text: str) -> str:
    """JavaScript's ``String.prototype.trim``."""
    return text.strip(_JS_SPACE)


def measure(markdown: str) -> int:  # noqa: PLR0912
    """A sum of per-character costs, each fixed or depending only on what
    comes before the character on its own line, which makes it subadditive.

    - A code point in the Basic Multilingual Plane costs its UTF-8 length,
      and each UTF-16 surrogate 3 (an astral code point is two), enough for
      the U+FFFD a lone one becomes. NUL costs 3 too.
    - ``<`` costs 4, a backslash 5, and ``$ = | ! [ ] * _ ~`` and the
      backtick 2.
    - ``\\n`` and ``\\r`` cost ``BLOCK``, as does a block marker before any
      other text on its line.
    """
    cost = 0
    prefix = True
    for c in markdown:
        code = ord(c)
        if c in "\n\r":
            cost += BLOCK
            prefix = True
            continue
        if code > 0xFFFF or 0xD800 <= code <= 0xDFFF:
            cost += 6 if code > 0xFFFF else 3
            prefix = False
            continue
        if prefix:
            if c in " \t0123456789":
                cost += 1
                continue
            if c in _BLOCK_MARKERS:
                cost += BLOCK
                continue
            prefix = False
        if c == "\\":
            cost += 5
        elif code == 0:
            cost += 3
        elif c == "<":
            cost += 4
        elif c in _TWO_BYTE_ESCAPES:
            cost += 2
        elif code < 0x80:
            cost += 1
        elif code < 0x800:
            cost += 2
        else:
            cost += 3
    return cost


def _punctuation(c: str) -> bool:
    return len(c) == 1 and (
        "!" <= c <= "/" or ":" <= c <= "@" or "[" <= c <= "`" or "{" <= c <= "~"
    )


def _at(line: str, i: int) -> str:
    """``line[i]``, or ``""`` past either end, as JavaScript's ``undefined``."""
    return line[i] if 0 <= i < len(line) else ""


# --- fences ---------------------------------------------------------------------------------

_FENCE_OPEN = re.compile(rf"( {{0,3}})(`{{3,}}|~{{3,}})({_DOT}*)")
_FENCE_CLOSE = re.compile(r" {0,3}(`+|~+)[ \t]*")


@dataclass(frozen=True)
class _Fence:
    char: str
    length: int
    indent: int


def _opens(line: str) -> _Fence | None:
    match = _FENCE_OPEN.fullmatch(line)
    if match is None or (match[2][0] == "`" and "`" in match[3]):
        return None
    return _Fence(match[2][0], len(match[2]), len(match[1]))


def _closes(line: str, fence: _Fence) -> bool:
    match = _FENCE_CLOSE.fullmatch(line)
    return match is not None and match[1][0] == fence.char and len(match[1]) >= fence.length


# --- block structure ------------------------------------------------------------------------

_CONTAINER = re.compile(r"[ \t>]*(?:[-+*]|[0-9]{1,9}[.)])(?:[ \t]|\Z)|[ \t>]*\[\^")
_BLOCK_START = re.compile(r"(?: {0,3}[#>\-*+_~`<=\[]| {0,3}[0-9]{1,9}[.)]| {4}| {0,3}\t)")
_QUOTES = re.compile(r"(?: {0,3}> ?)*+ {0,3}")
_HEADING_OR_BULLET = re.compile(rf"(?:#{{1,6}}(?: |\Z)|[-+*] +{_NOT_S})")
_ORDERED_ITEM = re.compile(rf"([0-9]{{1,9}})([.)]) +{_NOT_S}")
_DELIMITER_ROW = re.compile(
    r" {0,3}\|?[ \t]*+:?-++:?[ \t]*+(?:\|[ \t]*+:?-++:?[ \t]*+)*+\|?[ \t]*+"
)
_BLANK = re.compile(r"[ \t]*")
_HEADING = re.compile(r"#{1,6}(?: |\Z)")
_LEADING_SPACE = re.compile(_S)
_DASH_ITEM = re.compile(rf" {{0,3}}-[ \t]+{_NOT_S}")
_SETEXT = re.compile(r" {0,3}=+[ \t]*")
_THEMATIC_BREAK = re.compile(r" {0,3}([-*_])(?:[ \t]*+\1){2,}+[ \t]*+")


def _starts_block(line: str, previous_item: str | None) -> str | bool | None:
    """Whether a line starts a block wherever it is: an ATX heading, or a
    list item with content that may interrupt a paragraph. ``True``, the
    key of an ordered item, or ``None``."""
    rest_at = _QUOTES.match(line).end()  # pyright: ignore[reportOptionalMemberAccess]
    if _HEADING_OR_BULLET.match(line, rest_at):
        return True
    item = _ORDERED_ITEM.match(line, rest_at)
    if item is None:
        return None
    key = line[:rest_at] + item[2]
    return key if item[1] == "1" or key == previous_item else None


def _cell_count(line: str) -> int:
    """The cells of a table row, split at unescaped pipes as GFM does, even
    inside code."""
    count = 1
    i = 0
    while i < len(line):
        if line[i] == "\\":
            i += 1
        elif line[i] == "|":
            count += 1
        i += 1
    trimmed = js_trim(line)
    if trimmed.startswith("|"):
        count -= 1
    if len(trimmed) > 1 and trimmed.endswith("|") and not trimmed.endswith("\\|"):
        count -= 1
    return count


def _is_blank(line: str) -> bool:
    """Only spaces and tabs, as CommonMark defines a blank line."""
    return _BLANK.fullmatch(line) is not None


def _has_pipe(line: str) -> bool:
    trimmed = js_trim(line)
    return (_cell_count(line) > 1 or trimmed.startswith("|")) and trimmed != "|"


# --- links ----------------------------------------------------------------------------------

_ESCAPED = re.compile(r"\\([!-/:-@\[-`{-~])")
_DECIMAL_REFERENCE = re.compile(r"&#([0-9]{1,7});")
_HEX_REFERENCE = re.compile(r"&#[xX]([0-9a-fA-F]{1,6});")
_NAMED_SAFE = re.compile(r"&(amp|lt|gt|quot|apos);")
_NAMED_ANY = re.compile(r"&[A-Za-z][A-Za-z0-9]*;")
_NAMED = {"amp": "&", "lt": "<", "gt": ">", "quot": '"', "apos": "'"}
_PERCENT_RUN = re.compile(r"(?:%[0-9A-Fa-f]{2})++")
_ALLOWED_SCHEME = re.compile(r"(?:https?://|mailto:)", re.IGNORECASE | re.ASCII)
_MENTION = re.compile(r"tg://user\?id=([0-9]{1,20})")


def _decode_uri_component(text: str) -> str | None:
    """JavaScript's ``decodeURIComponent``, or ``None`` where it throws: a
    ``%`` without two hex digits, or bytes that are not UTF-8."""
    out: list[str] = []
    at = 0
    for match in _PERCENT_RUN.finditer(text):
        if "%" in text[at : match.start()]:
            return None
        out.append(text[at : match.start()])
        try:
            out.append(bytes.fromhex(match[0].replace("%", "")).decode("utf-8"))
        except UnicodeDecodeError:
            return None
        at = match.end()
    if "%" in text[at:]:
        return None
    out.append(text[at:])
    return "".join(out)


@dataclass(frozen=True)
class _Destination:
    unescaped: str
    decoded: str


def _decode_destination(raw: str) -> _Destination | None:
    """A link destination as a Markdown parser and then a URL parser read it."""
    unescaped = _ESCAPED.sub(r"\1", raw)
    unescaped = _DECIMAL_REFERENCE.sub(lambda m: chr(min(int(m[1]), 0x10FFFF)), unescaped)
    unescaped = _HEX_REFERENCE.sub(lambda m: chr(min(int(m[1], 16), 0x10FFFF)), unescaped)
    unescaped = _NAMED_SAFE.sub(lambda m: _NAMED[m[1]], unescaped)
    # Any other named reference could be one of HTML's many, such as ``&colon;``.
    if _NAMED_ANY.search(unescaped):
        return None
    decoded = _decode_uri_component(unescaped)
    return None if decoded is None else _Destination(unescaped, decoded)


def _allowed_destination(raw: str, mentions: frozenset[str]) -> bool:
    """Whether a link to ``raw`` may stay: http, https and mailto, or a
    mention the post allows."""
    destination = _decode_destination(raw)
    if destination is None:
        return False
    if _ALLOWED_SCHEME.match(destination.unescaped) and _ALLOWED_SCHEME.match(destination.decoded):
        return True
    mention = _MENTION.fullmatch(destination.decoded)
    return (
        mention is not None
        and destination.unescaped == destination.decoded
        and mention[1] in mentions
    )


def _blank_char(c: str) -> bool:
    return c in (" ", "\t")


@dataclass(frozen=True)
class _Tail:
    destination: str
    end: int


def _destination_and_title(line: str, start: int) -> _Tail | None:  # noqa: PLR0912
    """The destination and optional title from ``start`` when they are on
    this line: a destination not in angle brackets, up to a space, a control
    character or a ``)`` it did not open, its parentheses balanced and at
    most three deep, then a title after a space."""
    i = start
    while _blank_char(_at(line, i)):
        i += 1
    if _at(line, i) == "<":
        return None
    begin = i
    depth = 0
    while i < len(line):
        c = line[i]
        if c == "\\" and _punctuation(_at(line, i + 1)):
            i += 2
            continue
        code = ord(c)
        if code <= 0x20 or code == 0x7F:
            break
        if c == "(":
            depth += 1
            if depth > _MAX_DESTINATION_DEPTH:
                return None
        elif c == ")":
            if depth == 0:
                break
            depth -= 1
        i += 1
    if depth > 0:
        return None
    destination = line[begin:i]
    spaced = _blank_char(_at(line, i))
    while _blank_char(_at(line, i)):
        i += 1
    opener = _at(line, i)
    if spaced and opener in ('"', "'", "("):
        close = ")" if opener == "(" else opener
        i += 1
        while i < len(line) and line[i] != close:
            if line[i] == "\\" and _punctuation(_at(line, i + 1)):
                i += 1
            elif opener == "(" and line[i] == "(":
                return None
            i += 1
        if i >= len(line):
            return None
        i += 1
        while _blank_char(_at(line, i)):
            i += 1
    return _Tail(destination, i)


def _link_tail(line: str, start: int) -> _Tail | None:
    """A link's ``(destination "title")`` from the ``(`` at ``start``, when
    all of it is on this line."""
    tail = _destination_and_title(line, start + 1)
    if tail is None or _at(line, tail.end) != ")":
        return None
    return _Tail(tail.destination, tail.end + 1)


_HONORED = frozenset("!#$()*+-.=>[\\_`{|}~")
"""The punctuation whose backslash escape Telegram honors."""


def _escape_of(c: str) -> str:
    """A consumer's escape of ``c`` as Telegram reads it: kept, or a numeric
    character reference."""
    return "\\" + c if c in _HONORED else f"&#{ord(c)};"


_PERCENT_ENCODED = {"(": "%28", ")": "%29", "\\": "%5C", "<": "%3C", ">": "%3E"}
_DESTINATION_CHARS = re.compile(r"\\([!-/:-@\[-`{-~])|<")


def _destination_of(raw: str) -> str:
    """A kept destination as Telegram reads it, verbatim: escapes decoded,
    a parenthesis, backslash or ``<`` percent-encoded."""

    def replace(match: re.Match[str]) -> str:
        c = match[1] if match[1] is not None else match[0]
        return _PERCENT_ENCODED.get(c, c)

    return _DESTINATION_CHARS.sub(replace, raw)


def _definition_destination(line: str, start: int) -> str | None:
    tail = _destination_and_title(line, start)
    return tail.destination if tail is not None and tail.end == len(line) else None


def _rendered_label_bound(text: str) -> int:
    """The most UTF-16 units the renderer can make of a simple label."""
    n = 0
    i = 0
    while i < len(text):
        c = text[i]
        if c == "\\":
            n += 7
            i += 1
        else:
            n += 2 if c in "$=|*_~" or ord(c) > 0xFFFF else 1
        i += 1
    return n


_SIMPLE_LABEL = re.compile(rf"(?:[^\\\[\]`<]|\\{_DOT})*+")


@dataclass(frozen=True)
class _Definition:
    close: int
    destination: str


def _kept_definition(line: str, start: int, mentions: frozenset[str]) -> _Definition | None:
    close = line.find("]", start)
    if close < 0:
        return None
    text = line[start + 1 : close]
    if (
        _at(line, close + 1) != ":"
        or _SIMPLE_LABEL.fullmatch(text) is None
        or _is_blank(text)
        or text.startswith("^")
        or _rendered_label_bound(text) > _MAX_LABEL_LENGTH
    ):
        return None
    destination = _definition_destination(line, close + 2)
    if destination is None or not _allowed_destination(destination, mentions):
        return None
    return _Definition(close, destination)


class _CodeSpans:
    """Where each code span on a line ends, as CommonMark finds it: the next
    run of exactly as many backticks. The runs are indexed by length once,
    so each lookup is a binary search instead of a scan of the rest of the
    line (Effect's scan is quadratic on many unmatched runs)."""

    def __init__(self, line: str) -> None:
        self._line = line
        self._runs: dict[int, list[int]] = {}
        i = 0
        while i < len(line):
            if line[i] != "`":
                i += 1
                continue
            start = i
            while i < len(line) and line[i] == "`":
                i += 1
            self._runs.setdefault(i - start, []).append(start)
        self._pipes = list(accumulate((c == "|" for c in line), initial=0))

    def end(self, start: int, table_row: bool) -> int | None:
        """The end of the span whose opening backticks are at ``start``, or
        ``None`` when the run has no partner on the line. In a table row a
        span holding a pipe is refused."""
        line = self._line
        length = 0
        while _at(line, start + length) == "`":
            length += 1
        # Every run after the opening one is preceded by a non-backtick, so it
        # is one of the indexed runs.
        runs = self._runs.get(length, [])
        k = bisect.bisect_left(runs, start + length)
        if k == len(runs):
            return None
        j = runs[k]
        if table_row and self._pipes[j] - self._pipes[start] > 0:
            return None
        return j + length


_BARE_URL = re.compile(r"(?:https?://|www\.)", re.IGNORECASE | re.ASCII)
_AUTOLINK = re.compile(rf"<([A-Za-z][A-Za-z0-9+.-]{{1,31}}):[^{_JS_SPACE}<>`\x00-\x1f\x7f-\x9f]*>")
_WEB_AUTOLINK = re.compile(r"(?:https?|mailto)", re.IGNORECASE | re.ASCII)
_FOOTNOTE_DEFINITION = re.compile(r"\[\^[A-Za-z0-9_-]+\]:")
_SPACES = re.compile(r"[ \t]*")
_MARKER = re.compile(r"(?:>|[-+*](?=[ \t]|\Z)|[0-9]{1,9}[.)](?=[ \t]|\Z))")


@dataclass
class _Inline:
    """What one paragraph may already nest: every delimiter that could open
    emphasis, the most container depth of its lines, and its inline nodes."""

    open: int = 0
    containers: int = 0
    nodes: int = 0


@dataclass
class _Message:
    """What the whole message has used, and whether a definition may start
    the next line."""

    mentions: frozenset[str]
    footnotes: int = 0
    definitions_allowed: bool = True
    inline: _Inline = field(default_factory=_Inline)


@dataclass(frozen=True)
class _Prefix:
    text: str
    rest: int
    depth: int


def _render_prefix(line: str) -> _Prefix:
    """The container markers at the start of a line, with those past the
    depth limit escaped, and where the line's text starts."""
    out: list[str] = []
    i = 0
    depth = 0
    indent = 0
    while True:
        space = _SPACES.match(line, i).end() - i  # pyright: ignore[reportOptionalMemberAccess]
        indent += space
        out.append(line[i : i + space])
        i += space
        marker = _MARKER.match(line, i)
        if marker is None:
            break
        depth += 1
        token = marker[0]
        escape = depth + indent // 2 >= MAX_DEPTH
        out.append(token[:-1] + "\\" + token[-1] if escape else token)
        i += len(token)
    return _Prefix("".join(out), i, depth + indent // 2)


class _Out:
    """The rendered line, with its length kept, since positions in it mark
    labels that may need escaping at the end."""

    def __init__(self, start: str) -> None:
        self.parts = [start]
        self.length = len(start)

    def add(self, text: str) -> None:
        self.parts.append(text)
        self.length += len(text)

    def text(self) -> str:
        return "".join(self.parts)


def _escaped_run(run: str) -> str:
    return "".join("\\" + c for c in run)


def _render_line(  # noqa: PLR0912, PLR0915
    line: str,
    message: _Message,
    *,
    table_row: bool,
    cells: bool,
    wide_pipes: bool,
    setext: bool,
) -> str:
    prefix = _render_prefix(line)
    head = line[: prefix.rest]
    indent = head[len(head.rstrip(" \t")) :]
    footnote = (
        "\t" not in indent
        and len(indent) < 4
        and _FOOTNOTE_DEFINITION.match(line, prefix.rest) is not None
    )
    inline = message.inline
    inline.containers = max(inline.containers, prefix.depth)
    limit = max(0, MAX_DEPTH - 1 - inline.containers)

    def node(n: int) -> bool:
        if inline.nodes + n > MAX_INLINE_NODES:
            return False
        inline.nodes += n
        return True

    starts_label = _at(line, prefix.rest) == "["
    search_from = line.find("]:", prefix.rest) + 2 if footnote else prefix.rest
    shaped = starts_label and line.find("]:", search_from) >= 0
    definition = (
        _kept_definition(line, prefix.rest, message.mentions)
        if shaped and message.definitions_allowed and prefix.depth == 0
        else None
    )
    message.definitions_allowed = False
    label = len(prefix.text) if starts_label else None
    opener: int | None = None
    unclosed: list[int] = []
    out = _Out(prefix.text)
    spans = _CodeSpans(line)
    thematic: bool | None = None
    url_end = -1
    i = prefix.rest
    if shaped and definition is None:
        out.add("\\[")
        i += 1
    while i < len(line):
        c = line[i]
        after = _at(line, i + 1)
        if i >= url_end and _BARE_URL.match(line, i):
            url_end = i
            while url_end < len(line) and line[url_end] not in " \t":
                url_end += 1
        in_url = i < url_end
        if c == "\\" and in_url and _punctuation(after):
            out.add("%5C")
            i += 1
            continue
        if c == "\\" and _punctuation(after):
            out.add(_escape_of(after))
            i += 2
            continue
        if c == "`":
            end = None if in_url else spans.end(i, cells)
            if end is not None and node(1):
                out.add(line[i:end])
                i = end
                continue
            while _at(line, i) == "`":
                out.add("\\`")
                i += 1
            continue
        if c == "<":
            match = None if in_url else _AUTOLINK.match(line, i)
            if match is not None and _WEB_AUTOLINK.fullmatch(match[1]) and node(1):
                out.add(match[0])
                i = match.end()
            else:
                out.add("&lt;")
                i += 1
            continue
        if c == "$":
            out.add("\\$")
            i += 1
            continue
        if c == "=":
            out.add("=" if setext else "\\=")
            i += 1
            continue
        if c == "|":
            out.add("|" if table_row and not wide_pipes else "\\|")
            i += 1
            continue
        if c == "!":
            out.add("\\!" if after == "[" else "!")
            i += 1
            continue
        if c == "[":
            if after == "^" and not (footnote and i == prefix.rest):
                if message.footnotes >= MAX_FOOTNOTE_REFERENCES or not node(_FOOTNOTE_NODES):
                    out.add("\\[")
                    i += 1
                    continue
                message.footnotes += 1
                opener = None
            elif not in_url:
                if not node(1):
                    out.add("\\[")
                    i += 1
                    continue
                opener = i
            unclosed.append(out.length)
            out.add("[")
            i += 1
            continue
        if c == "]":
            plain = opener is not None and _at(line, opener - 1) != "]"
            label_opener = opener
            opener = None
            if unclosed:
                unclosed.pop()
            if after == "(":
                tail = _link_tail(line, i + 1)
                if (
                    plain
                    and tail is not None
                    and _allowed_destination(tail.destination, message.mentions)
                ):
                    out.add("](" + _destination_of(tail.destination) + ")")
                    i = tail.end
                    continue
                out.add("]\\(")
                i += 2
                continue
            if definition is not None and i == definition.close and label_opener == prefix.rest:
                message.definitions_allowed = True
                return out.text() + "]: " + _destination_of(definition.destination)
            out.add("]")
            i += 1
            continue
        if c in "*_~":
            end = i
            while _at(line, end) == c:
                end += 1
            run = line[i:end]
            following = _at(line, end)
            before = "" if i == prefix.rest else _at(line, i - 1)
            if before in ("", " ", "\t") and following in ("", " ", "\t"):
                if thematic is None:
                    thematic = _THEMATIC_BREAK.fullmatch(line) is not None
                if not thematic:
                    out.add(_escaped_run(run))
                    i = end
                    continue
            if following not in ("", " ", "\t"):
                if inline.open + len(run) > limit:
                    out.add(_escaped_run(run))
                    i = end
                    continue
                inline.open += len(run)
            out.add(run)
            i = end
            continue
        out.add(c)
        i += 1
    text = out.text()
    if label is not None and unclosed and unclosed[0] == label:
        text = text[:label] + "\\" + text[label:]
    return text


_NEWLINES = re.compile(r"\r\n?")


def _fenced_lines(lines: list[str]) -> tuple[list[bool], _Fence | None]:
    fenced: list[bool] = []
    fence: _Fence | None = None
    containers = False
    verbatim = True
    for line in lines:
        if fence is not None:
            fenced.append(True)
            if _closes(line, fence):
                fence = None
            continue
        opened = _opens(line) if verbatim else None
        if opened is not None and opened.indent > 0 and containers:
            verbatim = False
        elif opened is not None:
            fence = opened
            fenced.append(True)
            continue
        if _CONTAINER.match(line):
            containers = True
        fenced.append(False)
    return fenced, fence


def _tables(lines: list[str], fenced: list[bool]) -> tuple[dict[int, bool], set[int]]:
    """Each table row, with whether it is too wide to keep its pipes, and
    the lines GFM may still read as rows past a table's end."""
    rows: dict[int, bool] = {}
    cell_lines: set[int] = set()
    i = 0
    while i + 1 < len(lines):
        header, delimiter = lines[i], lines[i + 1]
        above = "" if i == 0 else lines[i - 1]
        if (
            fenced[i]
            or fenced[i + 1]
            or i in rows
            or _BLOCK_START.match(header)
            or _LEADING_SPACE.match(header)
            or _LEADING_SPACE.match(delimiter)
            or not (_is_blank(above) or _HEADING.match(above))
            or _DELIMITER_ROW.fullmatch(delimiter) is None
            or "|" not in delimiter
            or not _has_pipe(header)
            or _DASH_ITEM.match(delimiter)
        ):
            i += 1
            continue
        columns = _cell_count(header)
        if columns != _cell_count(delimiter):
            i += 1
            continue
        end = i + 2
        while (
            end < len(lines)
            and not fenced[end]
            and not _is_blank(lines[end])
            and not _BLOCK_START.match(lines[end])
        ):
            end += 1
        for row in range(i, end):
            rows[row] = columns > MAX_COLUMNS or _cell_count(lines[row]) > MAX_COLUMNS
        k = end
        while k < len(lines) and not fenced[k] and not _is_blank(lines[k]):
            cell_lines.add(k)
            k += 1
        i = end
    return rows, cell_lines


def render(markdown: str, *, mentions: frozenset[str] = frozenset(), files: int = 0) -> str:
    """Consumer Markdown as rich Markdown that keeps to what ``measure``
    charged: no raw HTML, image, math, spoiler or link that is not http,
    https, mailto or an allowed ``tg://user`` mention; nesting, tables and
    inline nodes within Telegram's limits; and ``files`` references at the
    end, after closing a fence left open. See Effect's ``render``."""
    lines = _NEWLINES.sub("\n", markdown).replace("\0", "\ufffd").split("\n")
    fenced, fence = _fenced_lines(lines)
    rows, cell_lines = _tables(lines, fenced)
    message = _Message(mentions)
    inline = message.inline
    item: str | None = None
    plain = True
    out: list[str] = []
    for i, line in enumerate(lines):
        blank = _is_blank(line)
        setext = (
            plain and i > 0 and not _is_blank(lines[i - 1]) and _SETEXT.fullmatch(line) is not None
        )
        plain = not fenced[i] and (
            blank
            or (
                plain
                and not _LEADING_SPACE.match(line)
                and not _BLOCK_START.match(line)
                and "|" not in line
            )
        )
        if fenced[i]:
            message.definitions_allowed = False
            out.append(line)
            continue
        wide = rows.get(i)
        starts = None if blank else _starts_block(line, item)
        item = starts if isinstance(starts, str) else None
        if blank or starts is not None or wide is not None:
            inline.open = 0
            inline.containers = 0
            inline.nodes = 0
        out.append(
            _render_line(
                line,
                message,
                table_row=wide is not None,
                cells=wide is not None or i in cell_lines,
                wide_pipes=wide is True,
                setext=setext,
            )
        )
        if blank:
            message.definitions_allowed = True
    text = "\n".join(out)
    if files > 0:
        if fence is not None:
            text += "\n" + fence.char * fence.length
        text += "".join(media_reference(n) for n in range(1, files + 1))
    return text
