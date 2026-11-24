"""Slack emoji names and what Slack counts an emoji as.

Effect works on UTF-16 strings; a Python string holds code points, so a
sequence's length here is in code points and ``longest_at`` also gives
its UTF-16 length, which the costs charge.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import cache

from pyfect.chat.chat_message import utf16_length
from pyfect.chat.slack._emoji_data import EMOJI_DATA


@dataclass(frozen=True)
class _Entry:
    unified: str
    # skin_variations keyed by Slack tone digits: "3" or "23"
    variations: dict[str, str]


@dataclass(frozen=True)
class _Table:
    by_name: dict[str, _Entry]
    # Emoji string (unified or non_qualified, toned or not) to Slack name without colons
    by_sequence: dict[str, str]
    # First code point of a multi code point sequence to its lengths, longest first
    lengths_by_first: dict[int, tuple[int, ...]]
    # Cost of a lone surrogate, the highest cost of any single code point emoji
    lone_surrogate_cost: int


def _decode(sequence: str) -> str:
    return "".join(chr(int(point, 16)) for point in sequence.split("-"))


def _without_variation_selector(emoji: str) -> str:
    return emoji.replace("️", "")


def _tone_suffix(tones: str) -> str:
    return "".join("::skin-tone-" + tone for tone in tones)


@cache
def _table() -> _Table:
    by_name: dict[str, _Entry] = {}
    by_sequence: dict[str, str] = {}
    lengths: dict[int, set[int]] = {}
    lone_surrogate_cost = 0

    def add_sequence(emoji: str, name: str) -> None:
        nonlocal lone_surrogate_cost
        by_sequence[emoji] = name
        if len(emoji) > 1:
            lengths.setdefault(ord(emoji[0]), set()).add(len(emoji))
        else:
            lone_surrogate_cost = max(lone_surrogate_cost, len(name) + 2)

    for line in EMOJI_DATA.split("\n"):
        fields = line.split("|")
        short_names = fields[0].split(",")
        short_name = short_names[0]
        unified = _decode(fields[1])
        add_sequence(unified, short_name)
        non_qualified = fields[2]
        if non_qualified:
            add_sequence(
                _without_variation_selector(unified)
                if non_qualified == "!"
                else _decode(non_qualified),
                short_name,
            )
        variations: dict[str, str] = {}
        if len(fields) > 3:
            for group in fields[3].split(";"):
                keys, template, *rest = group.split(":")
                for tones in keys.split(","):
                    digits = iter(tones)
                    variation = _decode(
                        re.sub(
                            r"\*",
                            lambda _, digits=digits: format(0x1F3FB + int(next(digits)) - 2, "x"),
                            template,
                        )
                    )
                    variations[tones] = variation
                    name = short_name + _tone_suffix(tones)
                    add_sequence(variation, name)
                    if rest and rest[0] == "!":
                        add_sequence(_without_variation_selector(variation), name)
        entry = _Entry(unified, variations)
        for name in short_names:
            by_name[name] = entry

    lengths_by_first = {
        first: tuple(sorted(found, reverse=True)) for first, found in lengths.items()
    }
    return _Table(by_name, by_sequence, lengths_by_first, lone_surrogate_cost)


_SKIN_TONE = re.compile(r"skin-tone-([2-6])")


def from_name(name: str) -> str | None:
    """Resolve a Slack emoji name to its fully qualified emoji.

    Accepts any alias, with or without surrounding colons, followed by at
    most one ``::skin-tone-N`` suffix. A tone the emoji does not have, and a
    name with two tones, give ``None``."""
    bare = name[1:-1] if len(name) >= 2 and name.startswith(":") and name.endswith(":") else name
    parts = bare.split("::")
    entry = _table().by_name.get(parts[0])
    if entry is None:
        return None
    if len(parts) == 1:
        return entry.unified
    if len(parts) != 2:
        return None
    match = _SKIN_TONE.fullmatch(parts[1])
    if match is None:
        return None
    tone = match[1]
    return entry.variations.get(tone) or entry.variations.get(tone + tone)


def to_name(emoji: str) -> str | None:
    """Resolve an emoji (fully qualified or not, toned or not) to its
    primary Slack name without colons, for example ``+1::skin-tone-3``."""
    return _table().by_sequence.get(emoji)


@dataclass(frozen=True)
class Found:
    """An emoji found in a text: its name, and its length in code points
    and in UTF-16 units."""

    name: str
    length: int
    utf16: int


def longest_at(text: str, index: int) -> Found | None:
    """The longest emoji in the table that starts at ``index``."""
    table = _table()
    for length in table.lengths_by_first.get(ord(text[index]), ()):
        if index + length <= len(text):
            sequence = text[index : index + length]
            name = table.by_sequence.get(sequence)
            if name is not None:
                return Found(name, length, utf16_length(sequence))
    name = table.by_sequence.get(text[index])
    return None if name is None else Found(name, 1, utf16_length(text[index]))


# Code points that are never an emoji on their own but join or modify emoji
# sequences. Charging them more than one keeps blocks_cost subadditive: an
# emoji sequence split anywhere costs at least as much as the whole sequence.
_ZERO_WIDTH_JOINER = 0x200D
_COMBINING_ENCLOSING_KEYCAP = 0x20E3
_ZERO_WIDTH_JOINER_COST = 10
_COMBINING_ENCLOSING_KEYCAP_COST = 12
_REGIONAL_INDICATOR_COST = 6
# Slack charges a lone hair component 1, but with this split measure 1 would
# charge seven hair sequences below their names. 4 is the least that keeps
# every hair sequence at its name.
_HAIR_COMPONENT_COST = 4


def _code_point_cost(code: int, lone_surrogate_cost: int) -> int:
    if code == _ZERO_WIDTH_JOINER:
        return _ZERO_WIDTH_JOINER_COST
    if code == _COMBINING_ENCLOSING_KEYCAP:
        return _COMBINING_ENCLOSING_KEYCAP_COST
    if 0x1F1E6 <= code <= 0x1F1FF:
        return _REGIONAL_INDICATOR_COST
    if 0x1F9B0 <= code <= 0x1F9B3:
        return _HAIR_COMPONENT_COST
    if 0xD800 <= code <= 0xDFFF:
        return lone_surrogate_cost
    return 1


def blocks_cost(text: str) -> int:
    """Measure text the way Slack counts it against the 13,200 character
    ``msg_blocks_too_long`` limit: every emoji counts as its ``:short_name:``
    form, everything else as one per code point.

    The result is the cheapest split of the text into emoji and single code
    points, so ``blocks_cost(a + b) <= blocks_cost(a) + blocks_cost(b)``.
    Code points that only occur inside emoji sequences cost more than one
    when they stand alone, and so does a lone surrogate, to keep that true
    when a split lands inside an emoji."""
    table = _table()
    by_sequence = table.by_sequence
    length = len(text)
    # costs[i] is the cheapest cost of text[:i]
    costs = [-1] * (length + 1)
    costs[0] = 0
    for i in range(length):
        before = costs[i]
        code = ord(text[i])
        single = by_sequence.get(text[i])
        single_cost = before + (
            _code_point_cost(code, table.lone_surrogate_cost) if single is None else len(single) + 2
        )
        if costs[i + 1] < 0 or single_cost < costs[i + 1]:
            costs[i + 1] = single_cost
        for candidate in table.lengths_by_first.get(code, ()):
            end = i + candidate
            if end > length:
                continue
            name = by_sequence.get(text[i:end])
            if name is None:
                continue
            cost = before + len(name) + 2
            if costs[end] < 0 or cost < costs[end]:
                costs[end] = cost
    return costs[length]
