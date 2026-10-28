"""Path helpers of find-my-way."""

from __future__ import annotations

import re

_DUPLICATE_SLASHES = re.compile(r"//+")


def remove_duplicate_slashes(path: str) -> str:
    return _DUPLICATE_SLASHES.sub("/", path) if "//" in path else path


def trim_last_slash(path: str) -> str:
    return path[:-1] if len(path) > 1 and path.endswith("/") else path


def closing_parenthesis(path: str, index: int) -> int:
    """The index of the ``)`` closing the ``(`` at ``index``; ``\\`` skips
    a character. Unbalanced parentheses raise ``TypeError``."""
    depth = 1
    while index < len(path):
        index += 1
        char = path[index : index + 1]
        if char == "\\":
            index += 1
            continue
        if char == ")":
            depth -= 1
        elif char == "(":
            depth += 1
        if depth == 0:
            return index
    raise TypeError(f'Invalid regexp expression in "{path}"')


def trim_regex_anchors(regex: str) -> str:
    """``(^...$)`` without its ``^`` and ``$``."""
    if regex[1:2] == "^":
        regex = regex[0] + regex[2:]
    if regex[-2:-1] == "$":
        regex = regex[:-2] + regex[-1]
    return regex
