"""Parameters bound into SQL text, for MySQL's text protocol.

asyncmy sends statements as text, so the client puts each parameter's
escaped literal where its ``?`` is, as MySQL's own tokenizer reads the
statement for a prepared one: a ``?`` inside a quoted string or name or a
comment is text, not a placeholder.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence

_TOKEN = re.compile(
    r"""
      '(?:[^'\\]|\\.|'')*'?      # 'string', with \ escapes and ''
    | "(?:[^"\\]|\\.|"")*"?      # "string"
    | `(?:[^`]|``)*`?            # `name`
    | /\*.*?(?:\*/|\Z)           # /* comment */
    | (?:--[ \t]|\#)[^\n]*       # -- comment and # comment
    | \?                         # a placeholder
    """,
    re.VERBOSE | re.DOTALL,
)


class PlaceholderMismatch(Exception):
    """The statement has a different number of ``?`` than parameters."""


def bind(sql: str, params: Sequence[object], escape: Callable[[object], str]) -> str:
    """``sql`` with its placeholders replaced by ``escape`` of ``params``,
    in order; raises ``PlaceholderMismatch`` unless there is one parameter
    per placeholder."""
    index = 0

    def replace(found: re.Match[str]) -> str:
        nonlocal index
        token = found.group(0)
        if token != "?":
            return token
        if index >= len(params):
            raise PlaceholderMismatch(
                f"the statement has more placeholders than the {len(params)} parameters"
            )
        index += 1
        return escape(params[index - 1])

    bound = _TOKEN.sub(replace, sql)
    if index != len(params):
        raise PlaceholderMismatch(
            f"the statement has {index} placeholders for {len(params)} parameters"
        )
    return bound


__all__ = ["PlaceholderMismatch", "bind"]
