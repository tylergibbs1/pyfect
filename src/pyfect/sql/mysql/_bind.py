"""Parameters bound into SQL text, for MySQL's text protocol.

asyncmy sends statements as text, so the client puts each parameter's
escaped literal where its ``?`` is, as MySQL's own tokenizer reads the
statement for a prepared one: a ``?`` inside a quoted string or name or a
comment is text, not a placeholder.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from typing import cast

_OUTSIDE_STRINGS = r"""
    | `(?:[^`]|``)*`?              # `name`
    | /\*(?!M?!).*?(?:\*/|\Z)      # /* comment */, but /*! and /*M! hold statement text
    | --(?=[\x00-\x20\x7f]|\Z)[^\n]* # -- then whitespace or a control character
    | \#[^\n]*                     # comment
    | \?                           # a placeholder
"""
_TOKEN = re.compile(
    r"""
      '(?:[^'\\]|\\.|'')*'?        # 'string', with \ escapes and ''
    | "(?:[^"\\]|\\.|"")*"?        # "string"
    """
    + _OUTSIDE_STRINGS,
    re.VERBOSE | re.DOTALL,
)
_TOKEN_NO_BACKSLASH_ESCAPES = re.compile(
    r"""
      '(?:[^']|'')*'?              # 'string', where \ is plain text
    | "(?:[^"]|"")*"?              # "string"
    """
    + _OUTSIDE_STRINGS,
    re.VERBOSE | re.DOTALL,
)


_SCAN = r"""
    | [A-Za-z0-9_]+                # a word
    | \s+
    | .
"""
_TOKENS = re.compile(_TOKEN.pattern + _SCAN, re.VERBOSE | re.DOTALL)
_TOKENS_NO_BACKSLASH_ESCAPES = re.compile(
    _TOKEN_NO_BACKSLASH_ESCAPES.pattern + _SCAN, re.VERBOSE | re.DOTALL
)
# mysql2's sql-escaper: words that end a SET assignment list.
_SET_LIST_ENDS = frozenset(
    (
        "where",
        "order",
        "group",
        "having",
        "limit",
        "union",
        "returning",
        "into",
        "for",
        "lock",
        "offset",
        "window",
        "procedure",
        "on",
    )
)


class PlaceholderMismatch(Exception):
    """The statement has a different number of ``?`` than parameters."""


def _opaque(token: str) -> bool:
    """A string, a quoted name or a comment."""
    return token[0] in "'\"`#" or token.startswith(("/*", "--"))


def _word(token: str) -> bool:
    return token[0].isascii() and (token[0].isalnum() or token[0] == "_")


def _set_list_starts(tokens: list[str]) -> list[int]:
    """The index after each ``SET`` / ``KEY UPDATE`` keyword."""
    starts: list[int] = []
    words = [(i, t.lower()) for i, t in enumerate(tokens) if _word(t)]
    for n, (i, word) in enumerate(words):
        if word == "set":
            starts.append(i + 1)
        elif word == "key" and n + 1 < len(words) and words[n + 1][1] == "update":
            following = words[n + 1][0]
            if all(t.isspace() for t in tokens[i + 1 : following]):
                starts.append(following + 1)
    return starts


def _in_set_list(tokens: list[str], start: int, placeholder: int) -> bool:
    """Whether the placeholder at ``placeholder`` begins an assignment of the
    list opened at ``start`` (sql-escaper's ``isInSetAssignmentList``)."""
    depth = 0
    content = False
    after_comma = False
    for token in tokens[start:placeholder]:
        if token.isspace():
            continue
        if _opaque(token) or token == "?":
            content, after_comma = True, False
        elif token == "(":
            depth += 1
            content, after_comma = True, False
        elif token == ")":
            depth -= 1
            if depth < 0:
                return False
            content, after_comma = True, False
        elif _word(token):
            if depth == 0 and token[0] not in "0123456789" and token.lower() in _SET_LIST_ENDS:
                return False
            content, after_comma = True, False
        elif depth == 0 and token == ";":
            return False
        elif depth == 0 and token == ",":
            content, after_comma = True, True
        else:
            content, after_comma = True, False
    return depth == 0 and (not content or after_comma)


def _assigns(tokens: list[str], chunk: int, placeholder: int, starts: list[int]) -> bool:
    """Whether a placeholder stands for assignments, as sql-escaper decides for an
    object: after a keyword or a comma, inside the nearest ``SET`` list."""
    previous = next((t for t in reversed(tokens[chunk:placeholder]) if not t.isspace()), None)
    if previous is None or not (
        previous == "," or (previous[-1].isascii() and previous[-1].isalpha())
    ):
        return False
    nearest = max((s for s in starts if s <= placeholder), default=None)
    return nearest is not None and _in_set_list(tokens, nearest, placeholder)


def bind(
    sql: str,
    params: Sequence[object],
    literal: Callable[[object, bool], str],
    *,
    no_backslash_escapes: bool,
) -> str:
    """``sql`` with its placeholders replaced by ``literal`` of ``params``,
    in order; raises ``PlaceholderMismatch`` unless there is one parameter
    per placeholder. ``literal``'s second argument says whether a dict there
    would be a ``SET`` assignment list, as mysql2 reads one.
    ``no_backslash_escapes`` is the session's SQL mode of that name, under
    which a backslash in a string is plain text."""
    pattern = _TOKENS_NO_BACKSLASH_ESCAPES if no_backslash_escapes else _TOKENS
    tokens = pattern.findall(sql)
    placeholders = [i for i, token in enumerate(tokens) if token == "?"]
    if len(placeholders) != len(params):
        raise PlaceholderMismatch(
            f"the statement has {len(placeholders)} placeholders for {len(params)} parameters"
        )
    starts: list[int] | None = None
    chunk = 0
    for placeholder, param in zip(placeholders, params, strict=True):
        assigns = False
        if isinstance(param, dict):
            starts = _set_list_starts(tokens) if starts is None else starts
            assigns = _assigns(tokens, chunk, placeholder, starts)
        tokens[placeholder] = literal(cast("object", param), assigns)
        chunk = placeholder + 1
    return "".join(tokens)


__all__ = ["PlaceholderMismatch", "bind"]
