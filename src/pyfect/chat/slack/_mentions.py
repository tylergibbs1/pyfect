"""The mentions of a Slack message, with offsets into its ``text`` in UTF-16
units (``Mention``'s unit)."""

from __future__ import annotations

import bisect
import re
from collections.abc import Sequence
from dataclasses import dataclass

from pyfect.chat.chat_message import Mention, MentionKind
from pyfect.chat.slack import _json

_TOKEN = re.compile(
    r"<(@([UW][A-Z0-9]+)|!subteam\^([A-Z0-9]+)|#(C[A-Z0-9]+|G[A-Z0-9]+)|!(here|channel|everyone))(\|[^<>]*)?>"
)
_CODE = re.compile(r"```[\s\S]*?```|`[^`\n]+`")


@dataclass(frozen=True)
class Target:
    kind: MentionKind
    id: str


def _target_of(match: re.Match[str]) -> Target:
    user, group, channel, broadcast = match[2], match[3], match[4], match[5]
    if user is not None:
        return Target("user", user)
    if group is not None:
        return Target("role", group)
    if channel is not None:
        return Target("channel", channel)
    return Target("broadcast", broadcast)


def parse_token(text: str) -> Target | None:
    """Parses one token, ``<@U123>``, ``<!subteam^S123|@team>``,
    ``<#C123|name>`` or ``<!here>``, as the whole of ``text``."""
    match = _TOKEN.fullmatch(text)
    return None if match is None else _target_of(match)


@dataclass(frozen=True)
class _Token:
    target: Target
    start: int
    end: int


def _tokens(text: str, skip_code: bool) -> list[_Token]:
    code = [(m.start(), m.end()) for m in _CODE.finditer(text)] if skip_code else []
    found: list[_Token] = []
    for match in _TOKEN.finditer(text):
        start = match.start()
        if any(lo <= start < hi for lo, hi in code):
            continue
        found.append(_Token(_target_of(match), start, match.end()))
    return found


@dataclass(frozen=True)
class _Item:
    target: Target
    real: bool


_ELEMENT_TARGETS: dict[str, tuple[str, MentionKind]] = {
    "user": ("user_id", "user"),
    "usergroup": ("usergroup_id", "role"),
    "channel": ("channel_id", "channel"),
    "broadcast": ("range", "broadcast"),
}


def _rich_text_items(blocks: object) -> list[_Item] | None:
    """The items of a message's ``rich_text`` blocks that a token in
    ``text`` can stand for, in order. A ``user``, ``usergroup``, ``channel``
    or ``broadcast`` element is a real mention, unless it has code style or
    sits in a preformatted section. A token-shaped string in text elements
    (adjacent ones joined) is a literal, as is a code-styled element.
    ``None`` when the message has no ``rich_text`` block."""
    if not _json.is_list(blocks):
        return None
    rich = [
        block
        for block in _json.as_list(blocks)
        if (obj := _json.as_object(block)) is not None and obj.get("type") == "rich_text"
    ]
    if not rich:
        return None
    items: list[_Item] = []
    pending: list[str] = []

    def flush_text() -> None:
        if pending:
            items.extend(_Item(token.target, False) for token in _tokens("".join(pending), False))
            pending.clear()

    # Depth first with a stack, so deep nesting costs no recursion. ``None``
    # marks the end of an element's children, where the text before it ends.
    stack: list[tuple[object, bool] | None] = [(block, False) for block in reversed(rich)]
    while stack:
        entry = stack.pop()
        if entry is None:
            flush_text()
            continue
        element, in_code = entry
        obj = _json.as_object(element)
        if obj is None:
            continue
        kind = obj.get("type")
        code = in_code or kind == "rich_text_preformatted"
        style = _json.as_object(obj.get("style"))
        literal = code or (style is not None and style.get("code") is True)
        if kind == "text":
            text = obj.get("text")
            if isinstance(text, str):
                pending.append(text)
            continue
        found = _ELEMENT_TARGETS.get(kind) if isinstance(kind, str) else None
        if found is not None:
            id = obj.get(found[0])
            if isinstance(id, str):
                flush_text()
                items.append(_Item(Target(found[1], id), not literal))
                continue
        children = obj.get("elements")
        if _json.is_list(children):
            flush_text()
            stack.append(None)
            stack.extend((child, code) for child in reversed(_json.as_list(children)))
    flush_text()
    return items


_MAX_ALIGNMENT = 1_000_000
"""Past this many item and token pairs, the alignment is skipped for the
fallback."""


def _align(items: list[_Item], found: list[_Token]) -> list[int] | None:
    """Aligns the tokens in ``text`` with the block's items, in order. Every
    real item takes a token it equals, a literal item may take one or be
    passed over, and a token may stand for no item. Of the alignments, the
    one that pairs the most items wins, the earliest pairing first. Gives
    the token index of each real item, or ``None`` when no alignment pairs
    them all."""
    n = len(items)
    m = len(found)
    if (n + 1) * (m + 1) > _MAX_ALIGNMENT:
        return None
    impossible = -1
    width = m + 1
    # best[i * width + j]: the most pairs for items i.. and tokens j.., or
    # impossible when some real item among i.. can't be paired.
    best = [0] * ((n + 1) * width)

    def pairs(i: int, j: int) -> int:
        if j == m or items[i].target != found[j].target:
            return impossible
        rest = best[(i + 1) * width + j + 1]
        return impossible if rest == impossible else rest + 1

    for i in range(n - 1, -1, -1):
        for j in range(m, -1, -1):
            score = pairs(i, j)
            if not items[i].real:
                score = max(score, best[(i + 1) * width + j])
            if j < m:
                score = max(score, best[i * width + j + 1])
            best[i * width + j] = score
    if best[0] == impossible:
        return None
    out: list[int] = []
    i = 0
    j = 0
    # Every step moves i or j forward, so this ends after n + m steps.
    while i < n:
        score = best[i * width + j]
        if pairs(i, j) == score:
            if items[i].real:
                out.append(j)
            i += 1
            j += 1
        elif not items[i].real and best[(i + 1) * width + j] == score:
            i += 1
        elif j < m and best[i * width + j + 1] == score:
            j += 1
        else:
            return None
    return out


def _utf16_offsets(text: str) -> list[int]:
    """The UTF-16 offset of every code point index of ``text``, and of its
    end: one pass, where measuring each mention's prefix would be quadratic."""
    offsets = [0] * (len(text) + 1)
    total = 0
    for index, char in enumerate(text):
        total += 2 if ord(char) > 0xFFFF else 1
        offsets[index + 1] = total
    return offsets


def extract(text: str, blocks: object, bot_user_id: str) -> list[Mention]:
    """The mentions of a message with offsets into ``text``.

    - With a ``rich_text`` block, the mentions are its real mention elements
      whose token is in ``text``, since Slack decides a mention from
      ``text``. Offsets come from aligning the tokens in ``text`` with the
      block's items, in order. When no alignment places every real item,
      each real item takes the next unused token it equals, and one with
      none left is not reported. ``text`` never adds a mention.
    - Without one, ``text`` is scanned, skipping backtick code spans and
      fences.
    """

    units = _utf16_offsets(text)

    def to_mention(token: _Token) -> Mention:
        return Mention(
            kind=token.target.kind,
            id=token.target.id,
            start=units[token.start],
            end=units[token.end],
            is_self=token.target.kind == "user" and token.target.id == bot_user_id,
        )

    items = _rich_text_items(blocks)
    if items is None:
        return [to_mention(token) for token in _tokens(text, True)]
    found = _tokens(text, False)
    aligned = _align(items, found)
    if aligned is not None:
        return [to_mention(found[index]) for index in aligned]
    unused = _Unused(found)
    chosen: list[_Token] = []
    start_from = 0
    for item in items:
        if not item.real:
            continue
        index = unused.take(item.target, start_from)
        if index is None:
            continue
        start_from = index + 1
        chosen.append(found[index])
    chosen.sort(key=lambda token: token.start)
    return [to_mention(token) for token in chosen]


class _Unused:
    """The tokens not yet taken, by target: ``take`` gives the first unused
    token equal to a target at or after an index, else the first unused one
    at all, in near constant time, so the fallback is linear in the tokens
    and items rather than their product."""

    def __init__(self, found: Sequence[_Token]) -> None:
        self._indexes: dict[Target, list[int]] = {}
        for index, token in enumerate(found):
            self._indexes.setdefault(token.target, []).append(index)
        # For each target, the next position not taken at or after each one
        # (its length when none is), as a union-find with path halving.
        self._next: dict[Target, list[int]] = {
            target: list(range(len(indexes) + 1)) for target, indexes in self._indexes.items()
        }

    def take(self, target: Target, start_from: int) -> int | None:
        indexes = self._indexes.get(target)
        if indexes is None:
            return None
        following = self._next[target]

        def free(position: int) -> int:
            while following[position] != position:
                following[position] = following[following[position]]
                position = following[position]
            return position

        position = free(bisect.bisect_left(indexes, start_from))
        if position == len(indexes):
            position = free(0)
            if position == len(indexes):
                return None
        following[position] = position + 1
        return indexes[position]
