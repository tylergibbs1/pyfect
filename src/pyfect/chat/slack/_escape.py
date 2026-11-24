"""Escaping for what the adapter sends Slack.

- The Markdown, in a ``markdown`` block or in ``markdown_text``: a ``<``
  outside inline and fenced code becomes ``&lt;``, unless the scoped notify
  options allow that token.
- The ``text`` beside a ``markdown`` block, from which Slack decides who is
  mentioned: every ``<``, ``>`` and ``&`` becomes an entity, in code too,
  and only the tokens the block keeps intact stay intact.
- A stream append, which has no ``text``: ``escape_stream`` puts U+200B
  after whatever spells the ``<`` of a token shape, in prose and in code
  alike.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class Notify:
    """Who a post may notify: these users and groups, and ``@here``,
    ``@channel`` and ``@everyone`` with ``broadcast``."""

    users: Sequence[str] = ()
    groups: Sequence[str] = ()
    broadcast: bool = False


NOBODY = Notify()


@dataclass(frozen=True)
class _Fence:
    char: str
    length: int


@dataclass(frozen=True)
class State:
    """Where an escaper left off: the fence open at the start of the current
    line, and the raw text of that line consumed so far."""

    fence: _Fence | None = None
    line: str = ""


INITIAL_STATE = State()


@dataclass(frozen=True)
class Escaped:
    """What to send for the consumed part of the input, how many characters
    of the input were consumed (the rest is held), and where it left off."""

    sent: str
    consumed: int
    state: State


_HOLD_BOUND = 300
"""Past this many held characters, an undecided ``<`` is escaped anyway."""

_TOKEN = re.compile(
    r"<(@([UW][A-Z0-9]+)|!subteam\^([A-Z0-9]+)|!(here|channel|everyone))(\|[^<>]*)?>"
)
_UNDECIDED = re.compile(r"<(@|!)?[\w^|]*", re.ASCII)
_TOKEN_START = re.compile(r"<[@!]")
_CODE_OR_TOKEN = re.compile(r"[`~]|<[@!]")
_CODE = re.compile(r"[`~]")
"""Where a token may start: once nothing is held, any other ``<`` is ``&lt;``."""


def _allows_any(notify: Notify) -> bool:
    return bool(notify.users) or bool(notify.groups) or notify.broadcast


def _allowed_token(line: str, at: int, notify: Notify) -> int:
    match = _TOKEN.match(line, at)
    if match is None:
        return 0
    token, user, group, broadcast = match[0], match[2], match[3], match[4]
    if user is not None:
        return len(token) if user in notify.users else 0
    if group is not None:
        return len(token) if group in notify.groups else 0
    return len(token) if broadcast is not None and notify.broadcast else 0


# JavaScript's ``.`` stops at \r, U+2028 and U+2029 as well as \n.
_OPENING_FENCE = re.compile(" {0,3}(`{3,}|~{3,})([^\r\u2028\u2029]*)")
_CLOSING_FENCE = re.compile(r" {0,3}(`{3,}|~{3,})[ \t]*\r?")


def _opens_fence(line: str) -> _Fence | None:
    match = _OPENING_FENCE.fullmatch(line)
    if match is None:
        return None
    marker = match[1]
    if marker[0] == "`" and "`" in match[2]:
        return None
    return _Fence(marker[0], len(marker))


def _closes_fence(line: str, fence: _Fence) -> bool:
    match = _CLOSING_FENCE.fullmatch(line)
    return match is not None and match[1][0] == fence.char and len(match[1]) >= fence.length


def _backtick_run(line: str, start: int) -> int:
    end = start
    while end < len(line) and line[end] == "`":
        end += 1
    return end - start


def _code_spans(line: str) -> tuple[list[tuple[int, int]], int]:
    """The code spans of one line, as ``[start, end)`` pairs, and the
    position of a backtick run that opens a span the line has not closed
    yet (-1 for none)."""
    spans: list[tuple[int, int]] = []
    open_ = -1
    i = line.find("`")
    while i != -1:
        length = _backtick_run(line, i)
        j = line.find("`", i + length)
        closed = -1
        while j != -1:
            run = _backtick_run(line, j)
            if run == length:
                closed = j
                break
            j = line.find("`", j + run)
        if closed == -1:
            if open_ == -1:
                open_ = i
            i = line.find("`", i + length)
        else:
            spans.append((i, closed + length))
            i = line.find("`", closed + length)
    return spans, open_


_ENTITY_OF = {"&": "&amp;", "<": "&lt;", ">": "&gt;"}


_ENTITY_TABLE = str.maketrans(_ENTITY_OF)


def _text_entities(text: str) -> str:
    return text.translate(_ENTITY_TABLE)


def escape(  # noqa: PLR0912, PLR0915
    text: str,
    notify: Notify,
    *,
    state: State = INITIAL_STATE,
    flush: bool = False,
    entities: bool = False,
    on_token: Callable[[int, int], None] | None = None,
) -> Escaped:
    """Escapes ``text``, continuing from ``state``. Without ``flush``, a
    ``<`` whose meaning the rest of the stream could still change is held:
    an unclosed token that the notify options might allow, or one after a
    backtick the line has not closed yet. With ``flush``, or once the held
    text passes a bound, it is escaped. With ``entities`` every ``<``,
    ``>`` and ``&`` is written as an entity, apart from allowed tokens;
    ``on_token`` is called with the span in the output of each allowed token
    kept intact."""
    full = state.line + text
    offset = len(state.line)
    any_allowed = _allows_any(notify)
    fence = state.fence
    out: list[str] = []
    out_length = 0
    line_start = 0

    def emit(start: int, end: int, piece: str | None = None, *, prose: bool = False) -> None:
        nonlocal out_length
        if end <= offset:
            return
        if piece is None:
            piece = full[max(start, offset) : end]
            if entities:
                piece = _text_entities(piece)
            elif prose:
                piece = piece.replace("<", "&lt;")
        out.append(piece)
        out_length += len(piece)

    # Complete lines outside a fence that hold no backtick, no tilde and no
    # ``<`` that may start an allowed token are prose with no held ``<``:
    # each run of them goes out in one piece.
    plain_until = _CODE_OR_TOKEN if any_allowed else _CODE
    while line_start <= len(full):
        if fence is None:
            special = plain_until.search(full, line_start)
            limit = len(full) if special is None else special.start()
            run_end = full.rfind("\n", line_start, limit) + 1
            if run_end > line_start:
                emit(line_start, run_end, prose=True)
                line_start = run_end
                continue
        newline = full.find("\n", line_start)
        complete = newline != -1
        line_end = newline if complete else len(full)
        line = full[line_start:line_end]
        if fence is not None:
            emit(line_start, line_end)
            if complete and _closes_fence(line, fence):
                fence = None
        else:
            opener = _opens_fence(line) if complete else None
            spans, open_ = _code_spans(line) if opener is None else ([], -1)
            i = 0
            span = 0
            while i < len(line):
                while span < len(spans) and spans[span][1] <= i:
                    span += 1
                if span < len(spans) and spans[span][0] <= i:
                    emit(line_start + i, line_start + spans[span][1])
                    i = spans[span][1]
                    continue
                # With ``flush`` no ``<`` is held, so only one that may start
                # a token stops the prose, and the others become ``&lt;``.
                if not flush:
                    following = line.find("<", i)
                elif any_allowed:
                    found = _TOKEN_START.search(line, i)
                    following = -1 if found is None else found.start()
                else:
                    following = -1
                stop = len(line) if following == -1 else following
                if span < len(spans):
                    stop = min(stop, spans[span][0])
                if stop > i:
                    emit(line_start + i, line_start + stop, prose=flush)
                    i = stop
                    continue
                at = line_start + i
                undecided = (
                    not flush
                    and not complete
                    and len(full) - at <= _HOLD_BOUND
                    and (
                        (open_ != -1 and open_ < i)
                        or (
                            any_allowed
                            and line.find(">", i) == -1
                            and _UNDECIDED.fullmatch(line, i) is not None
                        )
                    )
                )
                if undecided:
                    return Escaped("".join(out), at - offset, State(fence, full[line_start:at]))
                token = _allowed_token(line, i, notify)
                if token > 0:
                    start = out_length
                    emit(at, at + token, line[i : i + token] if at >= offset else None)
                    if at >= offset and on_token is not None:
                        on_token(start, out_length)
                    i += token
                else:
                    emit(at, at + 1, "&lt;" if at >= offset else None)
                    i += 1
            if opener is not None:
                fence = opener
        if not complete:
            return Escaped("".join(out), len(full) - offset, State(fence, line))
        emit(line_end, line_end + 1)
        line_start = line_end + 1
    return Escaped("".join(out), len(full) - offset, State(fence, ""))


_ZERO_WIDTH_SPACE = "\u200b"

# The character references a stream decodes for ``<``, ``@`` and ``!``, each
# only with its semicolon.
_REFERENCES: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"&(?:lt|LT|#0*60|#[xX]0*3[cC]);"), "<"),
    (re.compile(r"&(?:commat|#0*64|#[xX]0*40);"), "@"),
    (re.compile(r"&(?:excl|#0*33|#[xX]0*21);"), "!"),
)
_REFERENCE_NAMES = ("lt", "LT", "commat", "excl")
_NUMERIC_PREFIX = re.compile(r"#(?:[0-9]*|[xX][0-9a-fA-F]*)")
_UNCLOSED_TOKEN = re.compile(r"<[@!][\w^]*(?:\|[^<>]*)?", re.ASCII)
_LETTER = re.compile(r"[A-Za-z]")
_LT_OR_AMP = re.compile(r"[<&]")


def _unfinished_reference(text: str) -> bool:
    """Whether ``text``, from its ``&`` on, could still grow into one of the
    references."""
    body = text[1:]
    return _NUMERIC_PREFIX.fullmatch(body) is not None or any(
        name.startswith(body) for name in _REFERENCE_NAMES
    )


@dataclass(frozen=True)
class _Decoded:
    char: str
    # How many characters of the input spell it.
    length: int


def _decode_at(line: str, i: int) -> _Decoded:
    """The character at ``i`` in the decoded view of ``line``."""
    if line[i] == "&":
        for pattern, char in _REFERENCES:
            match = pattern.match(line, i)
            if match is not None:
                return _Decoded(char, len(match[0]))
    return _Decoded(line[i], 1)


_UNFINISHED = "unfinished"


def _decoded_at(line: str, i: int, ended: bool) -> _Decoded | str | None:
    """The character at ``i`` in the decoded view of ``line``: ``None`` past
    the end of the text, and ``"unfinished"`` where the next chunk could
    still change it."""
    if i >= len(line):
        return None if ended else _UNFINISHED
    decoded = _decode_at(line, i)
    if decoded.char == "&" and not ended and _unfinished_reference(line[i:]):
        return _UNFINISHED
    return decoded


def _decode_token(line: str, i: int) -> tuple[str, list[int]]:
    """``line`` from ``i`` to its first ``>``, or to its end, decoded, with
    the end in ``line`` of each decoded character."""
    close = line.find(">", i)
    end = len(line) if close == -1 else close + 1
    chars: list[str] = []
    ends: list[int] = []
    j = i
    while j < end:
        decoded = _decode_at(line, j)
        chars.append(decoded.char)
        j += decoded.length
        ends.append(j)
    return "".join(chars), ends


def escape_stream(  # noqa: PLR0911, PLR0912, PLR0915
    text: str, notify: Notify, *, state: State = INITIAL_STATE, flush: bool = False
) -> Escaped:
    """Escapes a stream's Markdown, continuing from ``state``. Slack decodes
    the character references for ``<``, ``@`` and ``!`` in a stream, joins
    one split across two appends, and has no ``text`` to send beside it, so:

    - Token shapes are found on the decoded view. A shape is ``<@``, or
      ``<!`` followed by an ASCII letter.
    - On a shape, U+200B goes straight after whatever spells the ``<``, and
      the rest is left as written. A token the notify options allow is sent
      as it is.
    - Every other ``<`` keeps the rule of ``escape``: ``&lt;`` outside code,
      as written inside it.

    Without ``flush``, it holds what the next chunk could still change. Past
    a bound, or with ``flush``, it decides with what it has."""
    full = state.line + text
    offset = len(state.line)
    any_allowed = _allows_any(notify)
    fence = state.fence
    out: list[str] = []
    line_start = 0

    def emit(start: int, end: int) -> None:
        if end > offset:
            out.append(full[max(start, offset) : end])

    while line_start <= len(full):
        newline = full.find("\n", line_start)
        complete = newline != -1
        line_end = newline if complete else len(full)
        line = full[line_start:line_end]
        in_fence = fence is not None
        opener = _opens_fence(line) if not in_fence and complete else None
        spans, open_ = ([], -1) if in_fence or opener is not None else _code_spans(line)

        def hold(i: int, line_start: int = line_start, fence: _Fence | None = fence) -> Escaped:
            at = line_start + i
            return Escaped("".join(out), at - offset, State(fence, full[line_start:at]))

        i = 0
        span = 0
        while i < len(line):
            found = _LT_OR_AMP.search(line, i)
            if found is None:
                emit(line_start + i, line_end)
                break
            emit(line_start + i, line_start + found.start())
            i = found.start()
            at = line_start + i
            # What an earlier write sent can't be held.
            ended = complete or flush or at < offset or len(full) - at > _HOLD_BOUND
            first = _decoded_at(line, i, ended)
            if first == _UNFINISHED:
                return hold(i)
            if not isinstance(first, _Decoded) or first.char != "<":
                # An ``&`` that spells no ``<``. What it spells is decided where it is used.
                emit(at, at + 1)
                i += 1
                continue
            second = _decoded_at(line, i + first.length, ended)
            if second == _UNFINISHED:
                return hold(i)
            second_decoded = second if isinstance(second, _Decoded) else None
            shape = second_decoded is not None and second_decoded.char == "@"
            # Where the text that makes it a shape ends.
            decided = i + first.length + (0 if second_decoded is None else second_decoded.length)
            if second_decoded is not None and second_decoded.char == "!":
                third = _decoded_at(line, decided, ended)
                if third == _UNFINISHED:
                    return hold(i)
                third_decoded = third if isinstance(third, _Decoded) else None
                shape = (
                    third_decoded is not None
                    and third_decoded.length == 1
                    and _LETTER.fullmatch(third_decoded.char) is not None
                )
                decided += 0 if third_decoded is None else third_decoded.length
            if shape:
                token_text, ends = _decode_token(line, i)
                length = _allowed_token(token_text, 0, notify)
                if length > 0:
                    emit(at, line_start + ends[length - 1])
                    i = ends[length - 1]
                    continue
                if not ended and any_allowed and _UNCLOSED_TOKEN.fullmatch(token_text):
                    return hold(i)
                # A shape an earlier write ended inside, which that write could not see,
                # gets the space at the start of this one: Slack reads the writes joined.
                if line_start + decided > offset:
                    emit(at, at + first.length)
                    out.append(_ZERO_WIDTH_SPACE)
                i += first.length
                continue
            if first.length > 1:
                # A reference for ``<`` that starts no token shape is left as written.
                emit(at, at + first.length)
                i += first.length
                continue
            while span < len(spans) and spans[span][1] <= i:
                span += 1
            in_code = in_fence or opener is not None or (span < len(spans) and spans[span][0] <= i)
            if not in_code and not ended and open_ != -1 and open_ < i:
                return hold(i)
            if in_code:
                emit(at, at + 1)
            elif at >= offset:
                out.append("&lt;")
            i += 1
        if fence is not None:
            if complete and _closes_fence(line, fence):
                fence = None
        elif opener is not None:
            fence = opener
        if not complete:
            return Escaped("".join(out), len(full) - offset, State(fence, line))
        emit(line_end, line_end + 1)
        line_start = line_end + 1
    return Escaped("".join(out), len(full) - offset, State(fence, ""))
