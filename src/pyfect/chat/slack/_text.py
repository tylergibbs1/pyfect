"""The ``text`` the adapter sends beside a ``markdown`` block on
``chat.postMessage`` and ``chat.update``. Slack decides who a message
mentions from this field, not from the blocks, so the adapter always builds
it itself: Slack's own would carry every token intact."""

from __future__ import annotations

import re
from bisect import bisect_right
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Literal

from pyfect.chat import _graphemes
from pyfect.chat.chat_ui import Action
from pyfect.chat.slack import _actions, _escape
from pyfect.chat.slack._escape import NOBODY, Notify
from pyfect.chat.slack._rich_text import escape_markdown

POST_TEXT_LENGTH = 16_000
"""The budget for ``text`` on ``chat.postMessage``, in code points. Slack
cuts a longer one there without an error, and the cut can split an entity or
a token."""

UPDATE_TEXT_BYTES = 3_800
"""The budget for ``text`` on ``chat.update``, in UTF-8 bytes. Slack refuses
a ``text`` over 4,000 bytes with ``msg_too_long``; this keeps a reserve for
Slack's own rewrites (it wraps a URL in ``<…>``)."""

type Unit = Literal["code_points", "utf8"]


@dataclass(frozen=True)
class Budget:
    unit: Unit
    limit: int


POST_BUDGET = Budget("code_points", POST_TEXT_LENGTH)
UPDATE_BUDGET = Budget("utf8", UPDATE_TEXT_BYTES)


def _char_bytes(char: str) -> int:
    code = ord(char)
    if code < 0x80:
        return 1
    if code < 0x800:
        return 2
    # A lone surrogate goes out as U+FFFD, which is three bytes too.
    return 4 if code > 0xFFFF else 3


def utf8_bytes(text: str) -> int:
    """The UTF-8 length of ``text`` as sent, a lone surrogate as U+FFFD (three
    bytes, as ``surrogatepass`` writes it)."""
    return len(text.encode("utf-8", "surrogatepass"))


def cost(text: str, unit: Unit) -> int:
    return utf8_bytes(text) if unit == "utf8" else len(text)


_MARKER = "\u2026"
_SEPARATOR = " "
_ENTITY = re.compile(r"&(?:lt|gt|amp);")
_LONGEST_ENTITY = len("&amp;")


@dataclass(frozen=True)
class Built:
    """The ``text``, and how many allowed tokens a cut had no room for."""

    text: str
    dropped: int


def build(markdown: str, notify: Notify, budget: Budget) -> Built:  # noqa: PLR0912
    """Builds the ``text`` for a Markdown body and cuts it to ``budget``.

    - Every ``<``, ``>`` and ``&`` is an entity, in code too. The tokens the
      notify options allow, outside code, stay intact, as they do in the
      block.
    - Past the budget, the text is cut on a grapheme cluster boundary that
      splits no entity and no token, and ends in ``…``. Each allowed token
      not in the kept part is appended once, in order, after a space. The
      marker and the spaces come out of the budget.
    - When the tokens alone don't fit, those that fit are kept and the rest
      counted in ``dropped``.
    """
    spans: list[tuple[int, int]] = []
    text = _escape.escape(
        markdown,
        notify,
        flush=True,
        entities=True,
        on_token=lambda start, end: spans.append((start, end)),
    ).sent
    tokens = [text[start:end] for start, end in spans]
    unit = budget.unit
    if cost(text, unit) <= budget.limit:
        return Built(text, 0)
    token_starts = [start for start, _ in spans]

    def inside(i: int) -> bool:
        """Whether ``i`` falls inside an entity or a token, where no cut may."""
        amp = text.rfind("&", max(0, i - _LONGEST_ENTITY + 1), i)
        if amp != -1 and (entity := _ENTITY.match(text, amp)) is not None and entity.end() > i:
            return True
        before = bisect_right(token_starts, i - 1) - 1
        return before >= 0 and spans[before][1] > i

    # The tail is the marker plus each distinct token not yet in the head.
    distinct = list(dict.fromkeys(tokens))

    def token_cost(token: str) -> int:
        return cost(_SEPARATOR + token, unit)

    tail = cost(_MARKER, unit) + sum(token_cost(token) for token in distinct)
    # A token leaves the tail once its first occurrence ends in the head.
    first_ends: list[int] = []
    left_tail: list[int] = [tail]
    seen: set[str] = set()
    for (_, end), token in zip(spans, tokens, strict=True):
        if token not in seen:
            seen.add(token)
            first_ends.append(end)
            left_tail.append(left_tail[-1] - token_cost(token))
    # The longest head within the budget alone, then back from it to the
    # first cut outside an entity or a token, on a grapheme cluster
    # boundary, where the head and the tail fit.
    if unit == "code_points":
        last = min(budget.limit, len(text))
        head = last
    else:
        prefixes = range(len(text) + 1)
        last = bisect_right(prefixes, budget.limit, key=lambda i: utf8_bytes(text[:i])) - 1
        head = utf8_bytes(text[:last])
    # Whether ``i`` starts a cluster depends only on ``text[: i + 1]``.
    boundaries = set(_graphemes.starts(text[: last + 1]))
    best = -1
    for i in range(last, -1, -1):
        if i < last:
            head -= 1 if unit == "code_points" else _char_bytes(text[i])
        if (
            i in boundaries
            and not inside(i)
            and head + left_tail[bisect_right(first_ends, i)] <= budget.limit
        ):
            best = i
            break
    if best >= 0:
        kept = text[:best]
        out = kept + _MARKER
        for token in distinct:
            if token not in kept:
                out += _SEPARATOR + token
        return Built(out, 0)
    # Not even the tokens fit: keep those that do, in order.
    out = _MARKER
    used = cost(_MARKER, unit)
    dropped = 0
    for token in distinct:
        extra = token_cost(token)
        if used + extra <= budget.limit:
            out += _SEPARATOR + token
            used += extra
        else:
            dropped += 1
    return Built(out, dropped)


type Block = Mapping[str, object]


@dataclass(frozen=True)
class Body:
    """The content of a ``chat.postMessage`` or ``chat.update``: the
    Markdown as sent in the block (for the length check), the blocks, the
    ``text`` and how many allowed tokens it dropped."""

    sent: str
    blocks: tuple[Block, ...]
    text: str
    dropped: int


def body(markdown: str, notify: Notify, budget: Budget, actions: Sequence[Action] = ()) -> Body:
    """The content of a ``chat.postMessage`` or ``chat.update``: the Markdown
    as one ``markdown`` block, then the elements as one ``actions`` block,
    and the ``text`` from ``build``.

    With elements and no Markdown there is no ``markdown`` block, and
    ``text`` is the button labels joined by a space, escaped."""
    if markdown == "" and actions:
        built = build(_actions.labels(actions), NOBODY, budget)
        return with_actions(Body("", (), built.text, built.dropped), actions)
    sent = _escape.escape(markdown, notify, flush=True).sent
    built = build(markdown, notify, budget)
    return with_actions(
        Body(sent, ({"type": "markdown", "text": sent},), built.text, built.dropped), actions
    )


def with_actions(content: Body, actions: Sequence[Action]) -> Body:
    """``content`` with the elements' ``actions`` block last, when there are
    any."""
    if not actions:
        return content
    return replace(content, blocks=(*content.blocks, _actions.block(actions)))


def has_actions(content: Body) -> bool:
    """Whether ``content`` has an ``actions`` block, which is content enough
    without ``text``."""
    return any(block.get("type") == "actions" for block in content.blocks)


def placeholder(names: Sequence[str], budget: Budget) -> Body:
    """The content of a post with files and no Markdown: the file names
    joined by ", ", escaped as Markdown in the block so they render as
    written, and with entities in ``text``. No token in a name is allowed."""
    joined = ", ".join(names)
    sent = _escape.escape(escape_markdown(joined), NOBODY, flush=True).sent
    built = build(joined, NOBODY, budget)
    return Body(sent, ({"type": "markdown", "text": sent},), built.text, built.dropped)
