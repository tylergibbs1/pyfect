"""Glob patterns compiled to an automaton (Effect's ``internal/glob.ts``,
compilation half): braces expanded, each pattern split into segment nodes,
all patterns laid out in one node list so a match state is an index."""

from __future__ import annotations

import re
from dataclasses import dataclass

MAX_EXPANSIONS = 10_000
MAX_EXPANDED_LENGTH = 2**22
MAX_BRACE_DEPTH = 64


@dataclass(frozen=True, slots=True)
class Char:
    code: int


@dataclass(frozen=True, slots=True)
class Any:
    pass


@dataclass(frozen=True, slots=True)
class Star:
    pass


@dataclass(frozen=True, slots=True)
class Class:
    """``ranges`` holds inclusive code point pairs: ``(from0, to0, from1, to1, ...)``."""

    ranges: tuple[int, ...]
    negated: bool


type Token = Char | Any | Star | Class


@dataclass(frozen=True, slots=True)
class Globstar:
    pass


@dataclass(frozen=True, slots=True)
class Literal:
    value: str


@dataclass(frozen=True, slots=True)
class Affixes:
    prefix: str
    suffix: str


@dataclass(frozen=True, slots=True)
class Wildcard:
    tokens: tuple[Token, ...]
    leading_dot: bool
    affixes: Affixes | None
    """Set when the segment is ``prefix*suffix``, which needs no backtracking."""


@dataclass(frozen=True, slots=True)
class End:
    """Ends one expanded pattern."""

    directory_only: bool


type Node = Globstar | Literal | Wildcard | End

GLOBSTAR = Globstar()


@dataclass(frozen=True, slots=True)
class Compiled:
    """Every expanded pattern's nodes in one list; ``initial`` holds the
    start of each pattern (after ``**`` closure)."""

    nodes: tuple[Node, ...]
    initial: frozenset[int]
    dot: bool


def closure(nodes: tuple[Node, ...] | list[Node], states: set[int]) -> set[int]:
    """``**`` also matches zero segments, so its successor is reachable too."""
    pending = list(states)
    while pending:
        state = pending.pop()
        if isinstance(nodes[state], Globstar) and state + 1 not in states:
            states.add(state + 1)
            pending.append(state + 1)
    return states


def compile(patterns: tuple[str, ...] | list[str], dot: bool) -> Compiled:
    nodes: list[Node] = []
    starts: set[int] = set()
    for pattern in patterns:
        for expanded in _expand_braces(pattern):
            start = len(nodes)
            if _compile_pattern(expanded, nodes):
                starts.add(start)
    frozen = tuple(nodes)
    return Compiled(frozen, frozenset(closure(frozen, starts)), dot)


def is_unc(path: str) -> bool:
    """UNC paths are rejected rather than collapsed into local absolute paths."""
    return path.startswith("//") and len(path) > 2 and path[2] != "/"


_DRIVE = re.compile(r"[A-Za-z]:")


def is_drive(segment: str) -> bool:
    return len(segment) == 2 and _DRIVE.match(segment) is not None


def is_root(name: str) -> bool:
    """The root of an absolute path: ``""`` or a drive such as ``C:/``."""
    return name == "" or (len(name) == 3 and name[2] == "/" and _DRIVE.match(name) is not None)


def is_absolute(path: str) -> bool:
    return path.startswith("/") or (
        len(path) > 2 and path[2] == "/" and _DRIVE.match(path) is not None
    )


def _compile_pattern(pattern: str, nodes: list[Node]) -> bool:
    """Append the pattern's nodes, or nothing when it can match no path."""
    if pattern == "" or is_unc(pattern):
        return False
    raw = _split_segments(pattern)
    if "**" in raw:
        globstar = raw.index("**")
        if any(segment in (".", "..") for segment in raw[globstar + 1 :]):
            return False
    segments, directory = normalize(raw)
    if not segments:
        return False
    for segment in segments:
        if segment != "**":
            nodes.append(_compile_segment(list(segment)))
        elif not nodes or nodes[-1] is not GLOBSTAR:
            nodes.append(GLOBSTAR)
    nodes.append(End(directory))
    return True


def _split_segments(pattern: str) -> list[str]:
    segments: list[str] = []
    start = 0
    i = 0
    while i < len(pattern):
        if pattern[i] == "\\":
            i += 1
        elif pattern[i] == "/":
            segments.append(pattern[start:i])
            start = i + 1
        i += 1
    segments.append(pattern[start:])
    return segments


def normalize(raw: list[str]) -> tuple[list[str], bool]:
    """Keep absolute roots and a lone ``.``; a trailing ``/`` or ``/.``
    marks a directory. Returns the segments and whether one is required."""
    segments: list[str] = []
    i = 0
    if len(raw) > 1 and (raw[0] == "" or is_drive(raw[0])):
        segments.append("" if raw[0] == "" else f"{raw[0]}/")
        i = 1
    directory = False
    last = len(raw) - 1
    for index in range(i, len(raw)):
        segment = raw[index]
        if segment in ("", "."):
            directory = index == last and len(segments) > 0
        else:
            segments.append(segment)
            directory = False
    if not segments and "." in raw:
        segments.append(".")
    return segments, directory


def _compile_segment(chars: list[str]) -> Node:
    tokens: list[Token] = []
    literal: list[str] = []
    magic = False
    # once a class fails to close, every later `[` in the segment is literal
    classes = True
    i = 0
    while i < len(chars):
        char = chars[i]
        if char == "\\" and i + 1 < len(chars):
            i += 1
            literal.append(chars[i])
            tokens.append(Char(ord(chars[i])))
        elif char == "*":
            magic = True
            if not tokens or not isinstance(tokens[-1], Star):
                tokens.append(Star())
        elif char == "?":
            magic = True
            tokens.append(Any())
        elif char == "[" and classes:
            parsed = parse_class(chars, i)
            if parsed is None:
                classes = False
                literal.append(char)
                tokens.append(Char(ord(char)))
            else:
                magic = True
                tokens.append(parsed[0])
                i = parsed[1]
        else:
            literal.append(char)
            tokens.append(Char(ord(char)))
        i += 1
    if not magic:
        return Literal("".join(literal))
    first = tokens[0]
    return Wildcard(
        tuple(tokens),
        isinstance(first, Char) and first.code == 0x2E,
        _compile_affixes(tokens),
    )


def _compile_affixes(tokens: list[Token]) -> Affixes | None:
    # Lone surrogates stay on the token path, as in Effect, where `startsWith`
    # would match them against half of a surrogate pair.
    prefix: list[str] = []
    suffix: list[str] | None = None
    for token in tokens:
        if isinstance(token, Star) and suffix is None:
            suffix = []
        elif isinstance(token, Char) and not 0xD800 <= token.code <= 0xDFFF:
            (prefix if suffix is None else suffix).append(chr(token.code))
        else:
            return None
    return None if suffix is None else Affixes("".join(prefix), "".join(suffix))


def _range(start: str, end: str) -> tuple[int, int]:
    return (ord(start), ord(end))


_POSIX_CLASSES: dict[str, tuple[int, ...]] = {
    "alnum": (*_range("0", "9"), *_range("A", "Z"), *_range("a", "z")),
    "alpha": (*_range("A", "Z"), *_range("a", "z")),
    "blank": (0x09, 0x09, 0x20, 0x20),
    "cntrl": (0x00, 0x1F, 0x7F, 0x7F),
    "digit": _range("0", "9"),
    "graph": (0x21, 0x7E),
    "lower": _range("a", "z"),
    "print": (0x20, 0x7E),
    "punct": (0x21, 0x2F, 0x3A, 0x40, 0x5B, 0x60, 0x7B, 0x7E),
    "space": (0x09, 0x0D, 0x20, 0x20),
    "upper": _range("A", "Z"),
    "word": (*_range("0", "9"), *_range("A", "Z"), 0x5F, 0x5F, *_range("a", "z")),
    "xdigit": (*_range("0", "9"), *_range("A", "F"), *_range("a", "f")),
}


def _parse_posix_class(chars: list[str], open: int) -> tuple[tuple[int, ...], int] | None:
    # POSIX class names are at most six characters.
    i = open + 2
    while i < len(chars) and i <= open + 8:
        if chars[i] == ":" and i + 1 < len(chars) and chars[i + 1] == "]":
            ranges = _POSIX_CLASSES.get("".join(chars[open + 2 : i]))
            return None if ranges is None else (ranges, i + 1)
        i += 1
    return None


def parse_class(chars: list[str], open: int) -> tuple[Class, int] | None:
    """The bracket class opening at ``open`` and the index of its ``]``, or
    ``None`` when it does not close (or crosses a ``/``). Brace expansion
    and segment compilation share these boundaries."""
    n = len(chars)
    i = open + 1
    negated = i < n and chars[i] in ("!", "^")
    if negated:
        i += 1
    ranges: list[int] = []
    first = True
    while i < n:
        char = chars[i]
        if char == "/":
            return None
        if char == "]" and not first:
            return Class(tuple(ranges), negated), i
        if char == "[" and i + 1 < n and chars[i + 1] == ":":
            posix = _parse_posix_class(chars, i)
            if posix is not None:
                ranges.extend(posix[0])
                i = posix[1] + 1
                first = False
                continue
        if char == "\\" and i + 1 < n:
            i += 1
            char = chars[i]
        if i + 1 < n and chars[i + 1] == "-" and i + 2 < n and chars[i + 2] != "]":
            following = i + 2
            if chars[following] == "/":
                return None
            if chars[following] == "\\" and following + 1 < n:
                following += 1
            ranges.extend(_range(char, chars[following]))
            i = following + 1
            first = False
            continue
        ranges.extend(_range(char, char))
        i += 1
        first = False
    return None


# --- braces ------------------------------------------------------------------

type _Sequence = list[str | list[_Sequence]]


def _js_length(text: str) -> int:
    """UTF-16 length, as Effect's limit counts."""
    return len(text) + sum(1 for c in text if ord(c) > 0xFFFF)


def _expand_braces(pattern: str) -> list[str]:
    chars = list(pattern)
    groups = _match_brace_groups(chars)
    if not groups:
        return [pattern]
    sequence = _parse_brace_sequence(chars, 0, len(chars), groups, 0)
    if sequence is None:
        return [pattern]
    count = _count_expansions(sequence)
    if count > MAX_EXPANSIONS or count * _js_length(pattern) > MAX_EXPANDED_LENGTH:
        return [pattern]
    return _expand_sequence(sequence)


def _match_brace_groups(chars: list[str]) -> dict[int, tuple[list[int], int]]:
    """Expandable brace groups by opening position (their commas and
    closing position), bracket classes skipped."""
    groups: dict[int, tuple[list[int], int]] = {}
    stack: list[tuple[int, list[int]]] = []
    classes = True
    i = 0
    while i < len(chars):
        char = chars[i]
        if char == "\\":
            i += 1
        elif char == "/":
            classes = True
        elif char == "[" and classes:
            parsed = parse_class(chars, i)
            if parsed is None:
                classes = False
            else:
                i = parsed[1]
        elif char == "{":
            stack.append((i, []))
        elif char == ",":
            if stack:
                stack[-1][1].append(i)
        elif char == "}" and stack:
            open, commas = stack.pop()
            if commas:
                groups[open] = (commas, i)
        i += 1
    return groups


def _parse_brace_sequence(
    chars: list[str],
    start: int,
    end: int,
    groups: dict[int, tuple[list[int], int]],
    depth: int,
) -> _Sequence | None:
    if depth > MAX_BRACE_DEPTH:
        return None
    parts: _Sequence = []
    text: list[str] = []
    i = start
    while i < end:
        group = groups.get(i)
        if group is None:
            if chars[i] == "\\" and i + 1 < end:
                text.append(chars[i])
                i += 1
            text.append(chars[i])
            i += 1
            continue
        commas, close = group
        alternatives: list[_Sequence] = []
        begin = i + 1
        for to in (*commas, close):
            alternative = _parse_brace_sequence(chars, begin, to, groups, depth + 1)
            if alternative is None:
                return None
            alternatives.append(alternative)
            begin = to + 1
        if text:
            parts.append("".join(text))
            text = []
        parts.append(alternatives)
        i = close + 1
    if text:
        parts.append("".join(text))
    return parts


def _count_expansions(sequence: _Sequence) -> float:
    count: float = 1
    for part in sequence:
        if not isinstance(part, str):
            count *= sum(_count_expansions(alternative) for alternative in part)
            if count > MAX_EXPANSIONS:
                return float("inf")
    return count


def _expand_sequence(sequence: _Sequence) -> list[str]:
    out = [""]
    for part in sequence:
        if isinstance(part, str):
            out = [prefix + part for prefix in out]
        else:
            alternatives = [text for alternative in part for text in _expand_sequence(alternative)]
            out = [prefix + alternative for prefix in out for alternative in alternatives]
    return out
