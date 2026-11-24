"""Markdown as a Bot Framework activity for Teams. A message is sent in one
of two forms, never mixed: text, when it has no actions, and an Adaptive
Card, when it has.

The renderer keeps to the rules that make ``_length.measure`` an upper
bound: a source line gives at most one element, a table row has at most one
cell more than it has pipes, each source unit is sent at most once, and
nothing is sent beyond the templates below and the source text. Every scan
is linear in the Markdown: lines are split once, and code spans are paired
from one list of backtick runs per line.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from pyfect._js import split_space, trim
from pyfect._js import to_well_formed as well_formed
from pyfect.chat.chat_ui import Action, Button, LinkButton

type Json = dict[str, object]

CARD_CONTENT_TYPE = "application/vnd.microsoft.card.adaptive"

ACTIONS_PER_ROW = 6
"""The most actions in one ``ActionSet`` row: the number Teams shows in a
row before it moves the rest into an overflow menu."""

_LINE_BREAK = re.compile(r"(\r\n|\r|\n)")


def escape_text(text: str) -> str:
    """Escapes ``<`` and ``&``, so that no HTML tag, ``<at>`` mention or
    entity forms in text Teams reads as Markdown."""
    return text.replace("&", "&amp;").replace("<", "&lt;")


def text_activity(markdown: str) -> Json:
    """The text form."""
    return {
        "type": "message",
        "text": escape_dollars(escape_text(well_formed(markdown))),
        "textFormat": "extendedmarkdown",
    }


def text_block(text: str) -> Json:
    return {"type": "TextBlock", "text": text, "wrap": True}


def code_block(code_snippet: str, language: str) -> Json:
    return {"type": "CodeBlock", "codeSnippet": code_snippet, "language": language}


COLUMN: Json = {"width": 1}


def table_cell(text: str) -> Json:
    return {"type": "TableCell", "items": [text_block(text)]}


def table_row(cells: Sequence[str]) -> Json:
    return {"type": "TableRow", "cells": [table_cell(cell) for cell in cells]}


def table(rows: Sequence[Sequence[str]]) -> Json:
    """A table with one column for each cell of its widest row."""
    width = max((len(row) for row in rows), default=0)
    return {
        "type": "Table",
        "firstRowAsHeaders": True,
        "columns": [COLUMN] * width,
        "rows": [table_row(row) for row in rows],
    }


def action_set(actions: Sequence[object]) -> Json:
    return {"type": "ActionSet", "actions": list(actions)}


def card(body: Sequence[object]) -> Json:
    return {
        "type": "AdaptiveCard",
        "version": "1.5",
        "body": list(body),
        "msteams": {"width": "Full"},
    }


def card_activity_of(body: Sequence[object]) -> Json:
    return {
        "type": "message",
        "attachments": [{"contentType": CARD_CONTENT_TYPE, "content": card(body)}],
    }


_STYLES = {"primary": "positive", "danger": "destructive"}


def button_action(button: Button, token: str) -> Json:
    """``Action.Execute``, with ``Action.Submit`` as the fallback for clients
    without Universal Actions. ``token`` carries the button's id and value."""
    title = well_formed(button.label)
    style = _STYLES.get(button.style or "")
    action: Json = {
        "type": "Action.Execute",
        "title": title,
        "verb": "effect",
        "data": {"effect": token},
    }
    if style is not None:
        action["style"] = style
    action["fallback"] = {"type": "Action.Submit", "title": title, "data": {"effect": token}}
    return action


def dialog_action(button: Button, token: str) -> Json:
    """A button that opens a dialog: an ``Action.Submit`` with ``task/fetch``,
    smaller than the ``Action.Execute`` and fallback the measure prices."""
    return {
        "type": "Action.Submit",
        "title": well_formed(button.label),
        "data": {"msteams": {"type": "task/fetch"}, "effect": token},
    }


def link_action(link: LinkButton) -> Json:
    return {
        "type": "Action.OpenUrl",
        "title": well_formed(link.label),
        "url": well_formed(link.url),
    }


def card_activity(
    markdown: str,
    actions: Sequence[Action],
    encode: Callable[[Button], str],
    opens_dialog: Callable[[Button], bool] = lambda _: False,
) -> Json:
    """The card form. Selects are not rendered: the adapter refuses them first."""
    body: list[object] = list(blocks(markdown))
    rendered: list[object] = []
    for action in actions:
        if isinstance(action, Button):
            token = encode(action)
            rendered.append(
                dialog_action(action, token)
                if opens_dialog(action)
                else button_action(action, token)
            )
        elif isinstance(action, LinkButton):
            rendered.append(link_action(action))
    body.extend(
        action_set(rendered[start : start + ACTIONS_PER_ROW])
        for start in range(0, len(rendered), ACTIONS_PER_ROW)
    )
    return card_activity_of(body)


# --- fences ----------------------------------------------------------------------------


@dataclass(frozen=True)
class _Fence:
    indent: int
    marker: str
    language: str


_FENCE_OPEN = re.compile("( {0,3})(`{3,}|~{3,})([^\u2028\u2029]*)")
_FENCE_CLOSE = re.compile(r" {0,3}(`{3,}|~{3,})[ \t]*")


def _fence_open(line: str) -> _Fence | None:
    match = _FENCE_OPEN.fullmatch(line)
    if match is None:
        return None
    spaces, marker, info = match.groups()
    if marker[0] == "`" and "`" in info:
        return None
    words = split_space(info)
    return _Fence(len(spaces), marker, words[0] if words else "PlainText")


def _strip_fence_indent(line: str, indent: int) -> str:
    i = 0
    while i < indent and i < len(line) and line[i] == " ":
        i += 1
    # An opening fence is at most three columns in, so a tab crossed here ends at column four.
    if i < indent and i < len(line) and line[i] == "\t":
        return " " * (4 - indent) + line[i + 1 :]
    return line[i:]


def _fence_closes(fence: _Fence, line: str) -> bool:
    match = _FENCE_CLOSE.fullmatch(line)
    return (
        match is not None
        and match.group(1)[0] == fence.marker[0]
        and len(match.group(1)) >= len(fence.marker)
    )


# --- dollars ---------------------------------------------------------------------------


def escape_dollars(markdown: str) -> str:
    """Escapes each ``$`` outside code as ``\\$``, so that Teams reads no
    math in the text form. A ``$`` the Markdown already escapes, after an
    odd run of backslashes, is left alone, and so is code: fenced blocks and
    code spans on one line. One unit per ``$`` at most, as
    ``_length.weight`` prices it."""
    parts = _LINE_BREAK.split(markdown)
    fence: _Fence | None = None
    for index in range(0, len(parts), 2):
        line = parts[index]
        if fence is not None:
            if _fence_closes(fence, line):
                fence = None
            continue
        fence = _fence_open(line)
        if fence is None:
            parts[index] = _escape_line(line)
    return "".join(parts)


_TICKS = re.compile(r"`+")


def _code_spans(line: str) -> dict[int, int]:
    """Where each code span of ``line`` ends, by where it opens: a run of
    backticks opens a span that closes at the next run of exactly its
    length, as CommonMark pairs them. One pass over the runs, keeping per
    length the runs still unpaired."""
    runs = [(match.start(), match.end() - match.start()) for match in _TICKS.finditer(line)]
    following: list[int | None] = [None] * len(runs)
    later: dict[int, int] = {}
    for index in range(len(runs) - 1, -1, -1):
        length = runs[index][1]
        following[index] = later.get(length)
        later[length] = index
    spans: dict[int, int] = {}
    index = 0
    while index < len(runs):
        start, length = runs[index]
        close = following[index]
        if close is None:
            index += 1
            continue
        spans[start] = runs[close][0] + length
        index = close + 1
    return spans


def _escape_line(line: str) -> str:
    spans = _code_spans(line)
    out: list[str] = []
    backslashes = 0
    i = 0
    while i < len(line):
        end = spans.get(i)
        if end is not None:
            out.append(line[i:end])
            backslashes = 0
            i = end
            continue
        char = line[i]
        if char == "$":
            out.append("\\$" if backslashes % 2 == 0 else "$")
        else:
            out.append(char)
        backslashes = backslashes + 1 if char == "\\" else 0
        i += 1
    return "".join(out)


# --- tables ----------------------------------------------------------------------------

_DELIMITER_CELL = re.compile(r":?-+:?")
_UNESCAPED_PIPE = re.compile(r"(?<!\\)\|")


def _is_delimiter(line: str) -> bool:
    """A table's delimiter row: cells of ``:?-+:?`` between pipes, the outer
    ones optional. Read cell by cell, so it is linear."""
    if "|" not in line:
        return False
    row = line.strip(" \t")
    row = row.removeprefix("|")
    row = row.removesuffix("|")
    cells = row.split("|")
    return all(_DELIMITER_CELL.fullmatch(cell.strip(" \t")) is not None for cell in cells)


def _cells(line: str) -> list[str]:
    """The cells of a table row. There are never more than its pipes plus one."""
    row = trim(line).removeprefix("|")
    if row.endswith("|") and not row.endswith("\\|"):
        row = row[:-1]
    return [escape_text(trim(cell).replace("\\|", "|")) for cell in _UNESCAPED_PIPE.split(row)]


# --- text ------------------------------------------------------------------------------

_QUOTE = re.compile(r" {0,3}> ?")
_LIST = re.compile(r"[ \t]*(?:[-*+]|[0-9]{1,9}[.)])(?:[ \t]+|\Z)")
_HEADING = re.compile(r" {0,3}#{1,6}(?:[ \t]+|\Z)")


def _flatten(line: str) -> str:
    """One line of a paragraph, with the block syntax a TextBlock cannot
    show taken off: quote markers and heading markers are dropped, and the
    first list marker is kept. ``> - # x`` becomes ``- x``. Markers are
    matched at a moving index, never by slicing, so it is linear."""
    at = 0
    marker = ""
    while True:
        quote = _QUOTE.match(line, at)
        if quote is not None:
            at = quote.end()
            continue
        if not marker:
            listed = _LIST.match(line, at)
            if listed is not None:
                marker = listed.group(0)
                at = listed.end()
                continue
        heading = _HEADING.match(line, at)
        if heading is not None:
            at = heading.end()
            continue
        return marker + line[at:]


def blocks(markdown: str) -> list[Json]:
    """The card body for Markdown: ``TextBlock``, ``CodeBlock`` and ``Table``
    elements in the order of the source. Consecutive lines of text share one
    ``TextBlock``, joined by ``\\n``."""
    lines = re.split(r"\r\n|\r|\n", well_formed(markdown))
    body: list[Json] = []
    text: list[str] = []

    def flush() -> None:
        start, end = 0, len(text)
        while start < end and not trim(text[start]):
            start += 1
        while end > start and not trim(text[end - 1]):
            end -= 1
        if start < end:
            body.append(text_block(escape_text("\n".join(text[start:end]))))
        text.clear()

    i = 0
    while i < len(lines):
        line = lines[i]
        fence = _fence_open(line)
        if fence is not None:
            flush()
            code: list[str] = []
            i += 1
            while i < len(lines) and not _fence_closes(fence, lines[i]):
                code.append(_strip_fence_indent(lines[i], fence.indent))
                i += 1
            i += 1
            body.append(code_block("\n".join(code), fence.language))
            continue
        if "|" in line and i + 1 < len(lines) and _is_delimiter(lines[i + 1]):
            flush()
            rows = [_cells(line)]
            i += 2
            while i < len(lines) and "|" in lines[i] and _fence_open(lines[i]) is None:
                rows.append(_cells(lines[i]))
                i += 1
            body.append(table(rows))
            continue
        text.append(_flatten(line))
        i += 1
    flush()
    return body
