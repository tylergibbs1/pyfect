"""Discord's mention tokens: one token as the whole of a string, and every
token in ``content`` outside code, in one linear pass."""

from __future__ import annotations

import re
from bisect import bisect_left
from dataclasses import dataclass

from pyfect.chat.chat_message import MentionKind

_TOKEN = re.compile(r"<@!?([0-9]+)>|<@&([0-9]+)>|<#([0-9]+)>|@(everyone|here)")
"""A mention token as Discord writes it in ``content``. Digits are ASCII only,
as JavaScript's ``\\d``."""

_ESCAPABLE = re.compile(r"[^0-9A-Za-z\s﻿]")
"""What a backslash escapes: anything but a letter, a digit or whitespace
(JavaScript's ``\\s`` holds U+FEFF, Python's does not)."""


@dataclass(frozen=True, slots=True)
class Target:
    kind: MentionKind
    id: str


@dataclass(frozen=True, slots=True)
class Token:
    """A token in ``content`` outside code, with its offsets in code points."""

    kind: MentionKind
    id: str
    start: int
    end: int


def _target(match: re.Match[str]) -> Target:
    user, role, channel, broadcast = match.groups()
    if user is not None:
        return Target("user", user)
    if role is not None:
        return Target("role", role)
    if channel is not None:
        return Target("channel", channel)
    return Target("broadcast", broadcast)


def parse_token(text: str) -> Target | None:
    """Parses one token, ``<@id>``, ``<@!id>``, ``<@&id>``, ``<#id>``,
    ``@everyone`` or ``@here``, as the whole of ``text``."""
    match = _TOKEN.fullmatch(text)
    return None if match is None else _target(match)


class _Runs:
    """The maximal runs of backticks in ``text``, by length, for the closing
    run of an inline code span. A query's ``from_`` only grows, so each
    length's position moves forward and the whole scan stays linear."""

    def __init__(self, text: str) -> None:
        self._starts: dict[int, list[int]] = {}
        self._at: dict[int, int] = {}
        i = text.find("`")
        while i != -1:
            end = i
            while end < len(text) and text[end] == "`":
                end += 1
            self._starts.setdefault(end - i, []).append(i)
            i = text.find("`", end)

    def closing(self, from_: int, n: int) -> int:
        """The index past the first run of exactly ``n`` backticks at or
        after ``from_``, or -1."""
        starts = self._starts.get(n)
        if starts is None:
            return -1
        at = self._at.get(n, 0)
        while at < len(starts) and starts[at] < from_:
            at += 1
        self._at[n] = at
        return starts[at] + n if at < len(starts) else -1


def tokens(text: str) -> list[Token]:
    """The mention tokens in ``content``, in order, skipping code blocks,
    inline code and tokens escaped with a backslash, as Discord's Markdown
    does. Linear in the length of ``text``."""
    found: list[Token] = []
    runs: _Runs | None = None
    # Past this index there is no "```": a failed search is not repeated.
    no_fence_after = len(text) + 1
    i = 0
    length = len(text)
    while i < length:
        char = text[i]
        if char == "\\" and i + 1 < length and _ESCAPABLE.match(text, i + 1) is not None:
            i += 2
            continue
        if char == "`":
            n = 1
            while i + n < length and text[i + n] == "`":
                n += 1
            if n >= 3 and i + 3 < no_fence_after:
                end = text.find("```", i + 3)
                if end != -1:
                    i = end + 3
                    continue
                no_fence_after = i + 3
            if runs is None:
                runs = _Runs(text)
            end = runs.closing(i + n, n)
            i = i + n if end == -1 else end
            continue
        if char in "<@":
            match = _TOKEN.match(text, i)
            if match is not None:
                target = _target(match)
                found.append(Token(target.kind, target.id, i, match.end()))
                i = match.end()
                continue
        i += 1
    return found


def utf16_offsets(text: str, positions: list[int]) -> list[int]:
    """Each code point index of ``positions`` (ascending) as a UTF-16 offset,
    in one pass over the astral characters before the last of them."""
    if not positions:
        return []
    astral = [i for i, char in enumerate(text[: positions[-1]]) if ord(char) > 0xFFFF]
    return [position + bisect_left(astral, position) for position in positions]
