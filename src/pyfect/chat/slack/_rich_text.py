"""Renders a message's ``rich_text`` blocks as Markdown, for the ``text`` of
the bot's own messages. Slack stores the adapter's ``markdown`` block as
``rich_text``, and the stored ``text`` is the adapter's ``text``, which may
be cut. Rendering the blocks gives the whole message back, with its
newlines.

The renderer is total: an element it does not know gives its ``text``, or
nothing. Mention offsets are in UTF-16 units, ``Mention``'s unit.
"""

from __future__ import annotations

import bisect
import copy
import math
import re
from collections.abc import Sequence
from dataclasses import dataclass, field

from pyfect._js import js_number
from pyfect.chat.chat_message import Mention, MentionKind, utf16_length
from pyfect.chat.slack import _emoji, _json
from pyfect.chat.slack._json import JsonObject


def _elements_of(obj: JsonObject) -> list[object]:
    return _json.as_list(obj.get("elements"))


def has_rich_text(blocks: object) -> bool:
    """Whether ``blocks`` holds a ``rich_text`` block."""
    return any(
        (obj := _json.as_object(block)) is not None and obj.get("type") == "rich_text"
        for block in (_json.as_list(blocks))
    )


@dataclass(frozen=True)
class _Style:
    bold: bool = False
    italic: bool = False
    strike: bool = False
    code: bool = False


_PLAIN = _Style()


def _style_of(element: JsonObject) -> _Style:
    style = _json.as_object(element.get("style"))
    if style is None:
        return _PLAIN
    return _Style(
        bold=style.get("bold") is True,
        italic=style.get("italic") is True,
        strike=style.get("strike") is True,
        code=style.get("code") is True,
    )


def _opening(style: _Style) -> str:
    return (
        ("**" if style.bold else "")
        + ("*" if style.italic else "")
        + ("~~" if style.strike else "")
    )


def _closing(style: _Style) -> str:
    return (
        ("~~" if style.strike else "")
        + ("*" if style.italic else "")
        + ("**" if style.bold else "")
    )


def _longest_run(text: str, char: str) -> int:
    longest = run = 0
    for c in text:
        run = run + 1 if c == char else 0
        longest = max(longest, run)
    return longest


@dataclass(frozen=True)
class _Text:
    text: str
    markdown: bool = False


@dataclass(frozen=True)
class _MentionPiece:
    token: str
    kind: MentionKind
    id: str


type _Piece = _Text | _MentionPiece

_HEX = re.compile(r"[0-9a-f]+", re.IGNORECASE)


def _emoji_text(element: JsonObject) -> str:
    unicode = _json.any_string(element, "unicode")
    hexes = None if unicode is None else unicode.split("-")
    if hexes is not None and all(_HEX.fullmatch(hex) for hex in hexes):
        points = [int(hex, 16) for hex in hexes]
        if all(point <= 0x10FFFF for point in points):
            return "".join(map(chr, points))
    name = _json.any_string(element, "name")
    if name is None:
        return ""
    tone = _json.number(element, "skin_tone")
    full = name if tone is None else f"{name}::skin-tone-{js_number(tone)}"
    return _emoji.from_name(full) or _emoji.from_name(name) or f":{full}:"


def _link_destination(url: str) -> str:
    """CommonMark accepts unescaped parentheses in a destination only when
    they nest in pairs."""
    depth = 0
    for char in url:
        if char == "(":
            depth += 1
        if char == ")":
            depth -= 1
            if depth < 0:
                break
    return url if depth == 0 else re.sub(r"[()\\]", lambda m: "\\" + m[0], url)


_SCHEME = re.compile(r"^[a-z][a-z0-9+.-]*://", re.IGNORECASE)

_MENTION_ELEMENTS: dict[str, tuple[str, str, str, MentionKind]] = {
    "user": ("user_id", "<@", ">", "user"),
    "usergroup": ("usergroup_id", "<!subteam^", ">", "role"),
    "channel": ("channel_id", "<#", ">", "channel"),
    "broadcast": ("range", "<!", ">", "broadcast"),
}


def _piece_of(element: JsonObject, in_code: bool) -> _Piece:  # noqa: PLR0911
    kind = element.get("type")
    match kind:
        case "text":
            return _Text(_json.any_string(element, "text") or "")
        case "link":
            url = _json.any_string(element, "url") or ""
            text = _json.any_string(element, "text")
            # Slack stores a bare URL as a link whose text is the URL without its scheme.
            bare = text is None or text in ("", url) or text == _SCHEME.sub("", url, count=1)
            destination = url if in_code else _link_destination(url)
            return _Text(
                url if bare else f"[{_escape_inline(text or '')}]({destination})", markdown=True
            )
        case "emoji":
            return _Text(_emoji_text(element))
        case "date":
            return _Text(_json.any_string(element, "fallback") or "")
        case "color":
            return _Text(_json.any_string(element, "value") or "")
        case str() if kind in _MENTION_ELEMENTS:
            key, before, after, mention_kind = _MENTION_ELEMENTS[kind]
            id = _json.any_string(element, key)
            if id is not None:
                return _MentionPiece(before + id + after, mention_kind, id)
        case _:
            pass
    return _Text(_json.any_string(element, "text") or "")


def _piece_text(piece: _Piece) -> str:
    return piece.text if isinstance(piece, _Text) else piece.token


_WORD_CHAR = re.compile(r"[^\W_]")
_ASCII_PUNCTUATION = re.compile(r"[!-/:-@\[-`{-~]")
_INLINE = re.compile(r"[*_`~\[\]\\]")


def _escape_inline(text: str) -> str:
    """Backslash-escapes what Markdown would read as inline syntax, so a text
    element's ``*literal*`` reads back literal. An underscore between two
    letters or digits opens nothing and is left alone, as is a backslash
    before anything but punctuation or a line end."""

    def replace(match: re.Match[str]) -> str:
        char = match[0]
        at = match.start()
        before = text[at - 1] if at > 0 else ""
        after = text[at + 1] if at + 1 < len(text) else ""
        if char == "_" and _WORD_CHAR.fullmatch(before) and _WORD_CHAR.fullmatch(after):
            return char
        if char == "\\" and after not in ("", "\n") and not _ASCII_PUNCTUATION.fullmatch(after):
            return char
        return "\\" + char

    return _INLINE.sub(replace, text)


_BLOCK_START = re.compile(
    r"^( {0,3})(?:([#]{1,6}|[-+])(?=[ \t]|$)|(>)|(\d{1,9})([.)])(?=[ \t]|$)|([-=])(?=[-= \t]*$))",
    re.ASCII,
)


def _escape_line_start(line: str) -> str:
    def replace(match: re.Match[str]) -> str:
        indent, marker, quote, digits, delimiter, rule = match.groups()
        if marker is not None:
            return indent + "\\" + marker
        if quote is not None:
            return indent + "\\>"
        if digits is not None:
            return indent + digits + "\\" + delimiter
        return indent + "\\" + rule

    return _BLOCK_START.sub(replace, line, count=1)


def _literal(text: str, at_line_start: bool) -> str:
    """A text element's content as Markdown that reads back as the same
    text."""
    lines = _escape_inline(text).split("\n")
    return "\n".join(
        _escape_line_start(line) if index > 0 or at_line_start else line
        for index, line in enumerate(lines)
    )


def escape_markdown(text: str) -> str:
    """Markdown that renders ``text`` as written, as the start of a
    message."""
    return _literal(text, True)


@dataclass(frozen=True)
class _Mark:
    """Where the output stood: its part count, UTF-16 length and mention count."""

    part: int
    units: int
    mention: int


@dataclass
class _Writer:
    """The output as parts, with its UTF-16 length kept as it grows, so a
    mention's offset and a list item's rewrite cost what they add, not the
    whole output so far."""

    bot_user_id: str
    parts: list[str] = field(default_factory=list[str])
    units: int = 0
    mentions: list[Mention] = field(default_factory=list[Mention])

    def write(self, text: str) -> None:
        if text:
            self.parts.append(text)
            self.units += utf16_length(text)

    def at_line_start(self) -> bool:
        return not self.parts or self.parts[-1].endswith("\n")

    def mark(self) -> _Mark:
        return _Mark(len(self.parts), self.units, len(self.mentions))

    def text(self) -> str:
        return "".join(self.parts)

    def piece(self, piece: _Piece, text: str | None = None) -> None:
        """Writes a piece outside code: a link as built, other text
        escaped, a mention as its token."""
        if isinstance(piece, _MentionPiece):
            start = self.units
            self.write(piece.token)
            self.mentions.append(
                Mention(
                    kind=piece.kind,
                    id=piece.id,
                    start=start,
                    end=start + utf16_length(piece.token),
                    is_self=piece.kind == "user" and piece.id == self.bot_user_id,
                )
            )
            return
        content = piece.text if text is None else text
        if piece.markdown:
            self.write(content)
        else:
            self.write(_literal(content, self.at_line_start()))

    def newline(self) -> None:
        """Starts a new line unless the output is empty or already ends one."""
        if not self.at_line_start():
            self.write("\n")


_LEADING_SPACE = re.compile(r"^\s*")
_TRAILING_SPACE = re.compile(r"\s*$")


def _inline(writer: _Writer, elements: Sequence[object]) -> None:
    """Inline elements, grouped into runs of one style so markers wrap a run
    and not each element. Whitespace at either end of a styled run goes
    outside its markers, where Markdown needs it. Code is a span, and a
    token in it is a literal."""
    items: list[tuple[_Piece, _Style]] = []
    for element in elements:
        obj = _json.as_object(element)
        if obj is not None:
            style = _style_of(obj)
            items.append((_piece_of(obj, style.code), style))
    i = 0
    while i < len(items):
        style = items[i][1]
        j = i + 1
        while j < len(items) and items[j][1] == style:
            j += 1
        run = [piece for piece, _ in items[i:j]]
        i = j
        if style.code:
            content = "".join(map(_piece_text, run))
            fence = "`" * (_longest_run(content, "`") + 1)
            # A backtick at either end would join the fence, and Markdown strips
            # one space from each end of a span that starts and ends with one.
            pad = (
                " "
                if content.startswith("`")
                or content.endswith("`")
                or (content.startswith(" ") and content.endswith(" ") and content.strip() != "")
                else ""
            )
            writer.write(_opening(style) + fence + pad + content + pad + fence + _closing(style))
            continue
        open_ = _opening(style)
        if open_ == "":
            for piece in run:
                writer.piece(piece)
            continue
        first = run[0]
        last = run[-1]
        lead = _match_text(_LEADING_SPACE, first.text) if isinstance(first, _Text) else ""
        trail = _match_text(_TRAILING_SPACE, last.text) if isinstance(last, _Text) else ""
        if len(run) == 1 and isinstance(first, _Text) and len(lead) == len(first.text):
            writer.piece(first)
            continue
        writer.write(lead + open_)
        for k, piece in enumerate(run):
            text = _piece_text(piece)
            if k == 0:
                text = text[len(lead) :]
            if k == len(run) - 1:
                text = text[: len(text) - len(trail)]
            writer.piece(piece, text)
        writer.write(_closing(style) + trail)


def _match_text(pattern: re.Pattern[str], text: str) -> str:
    found = pattern.search(text)
    return "" if found is None else found[0]


def _prefix_lines(writer: _Writer, mark: _Mark, first: str, rest: str) -> None:
    """Prefixes each line written since ``mark``, and moves the mentions in
    it to match."""
    lines = "".join(writer.parts[mark.part :]).split("\n")
    starts: list[int] = []
    shifts: list[int] = []
    rewritten: list[str] = []
    position = mark.units
    shift = 0
    for index, line in enumerate(lines):
        prefix = first if index == 0 else rest
        shift += utf16_length(prefix)
        starts.append(position)
        shifts.append(shift)
        rewritten.append(prefix + line)
        position += utf16_length(line) + 1
    del writer.parts[mark.part :]
    writer.units = mark.units
    writer.write("\n".join(rewritten))
    for m in range(mark.mention, len(writer.mentions)):
        mention = writer.mentions[m]
        moved = shifts[bisect.bisect_right(starts, mention.start) - 1]
        writer.mentions[m] = copy.replace(
            mention, start=mention.start + moved, end=mention.end + moved
        )


_MAX_INDENT = 32
"""The deepest list indent rendered: Slack nests lists a few levels deep, and
an untrusted ``indent`` must not size a string."""

_MAX_DEPTH = 32
"""The deepest list inside a list item rendered. Slack's own lists are flat,
with an ``indent``; a deeper one from a peer must not size the recursion or
the output, which grows with depth times length."""


def _whole(value: float | None, lo: int, hi: int) -> int:
    """``value`` truncated and clamped to ``lo..hi``; 0 when it is missing or
    not finite."""
    if value is None or not math.isfinite(value):
        return 0
    return min(hi, max(lo, int(value)))


def _block(writer: _Writer, element: object, depth: int = 0) -> None:
    obj = _json.as_object(element)
    if obj is None or depth > _MAX_DEPTH:
        return
    match obj.get("type"):
        case "rich_text_section":
            _inline(writer, _elements_of(obj))
            return
        case "rich_text_preformatted":
            # A fence holds no mention: every token is literal.
            content = "".join(
                _piece_text(_piece_of(child, True))
                for item in _elements_of(obj)
                if (child := _json.as_object(item)) is not None
            )
            fence = "`" * max(3, _longest_run(content, "`") + 1)
            ending = "" if content.endswith("\n") else "\n"
            writer.write(fence + "\n" + content + ending + fence)
            return
        case "rich_text_quote":
            mark = writer.mark()
            _inline(writer, _elements_of(obj))
            _prefix_lines(writer, mark, "> ", "> ")
            return
        case "rich_text_list":
            indent = "  " * _whole(_json.number(obj, "indent"), 0, _MAX_INDENT)
            ordered = obj.get("style") == "ordered"
            offset = _whole(_json.number(obj, "offset"), -(2**53), 2**53)
            for index, item in enumerate(_elements_of(obj)):
                if index > 0:
                    writer.write("\n")
                marker = f"{offset + index + 1}. " if ordered else "- "
                mark = writer.mark()
                _block(writer, item, depth + 1)
                _prefix_lines(writer, mark, indent + marker, indent + " " * len(marker))
            return
        case _:
            pass
    text = _json.any_string(obj, "text")
    if text is not None:
        writer.write(text)


@dataclass(frozen=True)
class Rendered:
    text: str
    mentions: tuple[Mention, ...]


def render(blocks: Sequence[object], bot_user_id: str) -> Rendered:
    """The Markdown of a message's blocks, with the mentions at the offsets
    the renderer wrote. A mention is a ``user``, ``usergroup``, ``channel``
    or ``broadcast`` element outside code. Blocks other than ``rich_text``
    give their ``text`` when it is a string, and nothing otherwise."""
    writer = _Writer(bot_user_id)
    for item in blocks:
        obj = _json.as_object(item)
        if obj is None:
            continue
        if obj.get("type") == "rich_text":
            for element in _elements_of(obj):
                writer.newline()
                _block(writer, element)
        else:
            text = _json.any_string(obj, "text")
            if text:
                writer.newline()
                writer.write(text)
    return Rendered(writer.text(), tuple(writer.mentions))
