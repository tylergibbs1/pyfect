"""Running a compiled glob over path segments (Effect's ``internal/glob.ts``,
matching half): one segment at a time, a set of node indices as the state."""

from __future__ import annotations

from dataclasses import dataclass

from pyfect.glob._compile import (
    Any,
    Char,
    Class,
    Compiled,
    End,
    Globstar,
    Literal,
    Star,
    Token,
    Wildcard,
    closure,
    is_root,
    is_unc,
    normalize,
)

type States = frozenset[int] | set[int]


def _match_token(token: Token, code: int) -> bool:
    match token:
        case Char(code=expected):
            return expected == code
        case Any():
            return True
        case Star():
            return False
        case Class(ranges=ranges, negated=negated):
            found = any(ranges[i] <= code <= ranges[i + 1] for i in range(0, len(ranges), 2))
            return found != negated


def _match_wildcard(node: Wildcard, name: str, dot: bool) -> bool:
    """Backtracks only to the last ``*``, bounding retries by tokens times
    characters."""
    if name in (".", "..") or (name.startswith(".") and not dot and not node.leading_dot):
        return False
    if node.affixes is not None:
        prefix, suffix = node.affixes.prefix, node.affixes.suffix
        return (
            len(name) >= len(prefix) + len(suffix)
            and name.startswith(prefix)
            and name.endswith(suffix)
        )
    tokens = node.tokens
    t = c = 0
    star = -1
    resume = 0
    while c < len(name):
        if t < len(tokens) and isinstance(tokens[t], Star):
            star = t
            t += 1
            resume = c
            continue
        if t < len(tokens) and _match_token(tokens[t], ord(name[c])):
            t += 1
            c += 1
        elif star != -1:
            t = star + 1
            resume += 1
            c = resume
        else:
            return False
    while t < len(tokens) and isinstance(tokens[t], Star):
        t += 1
    return t == len(tokens)


@dataclass(frozen=True, slots=True)
class Step:
    explicit: set[int]
    """States reached by matching a literal or wildcard segment."""
    globstar: set[int]
    """States reached by a ``**`` consuming the name."""


def step(compiled: Compiled, states: States, name: str) -> Step:
    explicit: set[int] = set()
    via_globstar: set[int] = set()
    # only a literal segment can name the root of an absolute path
    root = is_root(name)
    for state in states:
        node = compiled.nodes[state]
        match node:
            case Globstar():
                if (
                    not root
                    and name not in (".", "..")
                    and (compiled.dot or not name.startswith("."))
                ):
                    via_globstar.add(state)
            case Literal(value=value):
                if value == name:
                    explicit.add(state + 1)
            case Wildcard():
                if not root and _match_wildcard(node, name, compiled.dot):
                    explicit.add(state + 1)
            case End():
                pass
    return Step(closure(compiled.nodes, explicit), closure(compiled.nodes, via_globstar))


def union(result: Step) -> set[int]:
    return result.explicit | result.globstar if result.globstar else result.explicit


def accepts(compiled: Compiled, states: States, is_directory: bool) -> bool:
    for state in states:
        node = compiled.nodes[state]
        if isinstance(node, End) and (is_directory or not node.directory_only):
            return True
    return False


def can_descend(compiled: Compiled, states: States) -> bool:
    return any(not isinstance(compiled.nodes[state], End) for state in states)


def needs_directory(compiled: Compiled, states: States) -> bool:
    for state in states:
        node = compiled.nodes[state]
        if isinstance(node, End) and node.directory_only:
            return True
    return False


def match(compiled: Compiled, path: str) -> bool:
    if path == "" or is_unc(path):
        return False
    segments, directory = normalize(path.split("/"))
    states: States = compiled.initial
    for name in segments:
        states = union(step(compiled, states, name))
        if not states:
            return False
    return accepts(compiled, states, directory)
