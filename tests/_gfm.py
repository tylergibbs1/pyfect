"""What a GFM parse of rendered Markdown holds that the Telegram renderer
promises it never will (Effect's ``chat/telegram/test/gfm.ts``, which uses
micromark). Here the parser is markdown-it-py with GFM tables,
strikethrough, autolink literals and footnotes, which follows the same
CommonMark spec.

markdown-it keeps no source offsets for inline tokens, so ``active`` and
``unhonored`` read each paragraph's source once, left to right, skipping
code spans, autolinks and link destinations as a CommonMark parser does."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from markdown_it import MarkdownIt
from markdown_it.token import Token
from mdit_py_plugins.footnote import footnote_plugin

_PARSER = MarkdownIt("gfm-like").use(footnote_plugin)

_HONORED = frozenset("!#$()*+-.=>[\\_`{|}~")
"""Punctuation whose backslash escape Telegram honors."""
_PUNCTUATION = frozenset("!\"#$%&'()*+,-./:;<=>?@[\\]^_`{|}~")
_ACTIVE = frozenset("|$=")
"""Telegram's spoiler, math and mark syntax."""
_AUTOLINK = re.compile(r"<[A-Za-z][A-Za-z0-9+.-]{1,31}:[^<>\x00-\x20]*+>")
_EMAIL_AUTOLINK = re.compile(r"<[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]++@[A-Za-z0-9.-]++>")

_NESTING = frozenset({"blockquote_open", "list_item_open", "em_open", "strong_open", "s_open"})
_CLOSING = frozenset({"blockquote_close", "list_item_close", "em_close", "strong_close", "s_close"})
_BLOCKS = frozenset(
    {
        "paragraph_open",
        "heading_open",
        "fence",
        "code_block",
        "hr",
        "list_item_open",
        "tr_open",
        "blockquote_open",
        "html_block",
    }
)


@dataclass
class Findings:
    html: list[str] = field(default_factory=list[str])
    images: int = 0
    links: list[str] = field(default_factory=list[str])
    max_depth: int = 0
    max_columns: int = 0
    blocks: int = 0
    active: list[str] = field(default_factory=list[str])
    """Text that reached the parser with an unescaped ``|``, ``$`` or ``=``."""
    unhonored: list[str] = field(default_factory=list[str])
    """Text holding a backslash escape Telegram does not honor, which it shows
    as a backslash and then reads the character as syntax (live check 2)."""
    inline: int = 0
    """The most inline nodes in one paragraph, as the renderer counts them:
    code spans, links written with ``[`` or ``<``, and footnote references
    at three each. Bare URLs are not counted."""


def _skip_run(source: str, i: int) -> int:
    """Past a code span opening at ``i``, or past its backticks when it has
    no closing run."""
    end = i
    while end < len(source) and source[end] == "`":
        end += 1
    run = source[i:end]
    j = end
    while True:
        found = source.find(run, j)
        if found < 0:
            return end
        after = found + len(run)
        if after < len(source) and source[after] == "`":
            j = after
            while j < len(source) and source[j] == "`":
                j += 1
            continue
        if found > 0 and source[found - 1] == "`":
            j = after
            continue
        return after


def _skip_destination(source: str, i: int) -> int:
    """Past ``(...)`` at ``i``, balancing parentheses."""
    depth = 0
    j = i
    while j < len(source):
        char = source[j]
        if char == "\\":
            j += 2
            continue
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return j + 1
        elif char in " \n":
            return j
        j += 1
    return j


def _scan(source: str, findings: Findings, *, cell: bool) -> None:
    active = False
    i = 0
    while i < len(source):
        char = source[i]
        if char == "\\":
            following = source[i + 1] if i + 1 < len(source) else ""
            if following in _PUNCTUATION and following not in _HONORED:
                findings.unhonored.append(source)
            i += 2
            continue
        if char == "`":
            i = _skip_run(source, i)
            continue
        if char == "<":
            match = _AUTOLINK.match(source, i) or _EMAIL_AUTOLINK.match(source, i)
            if match is not None:
                i = match.end()
                continue
        if char == "]" and source.startswith("](", i):
            i = _skip_destination(source, i + 1)
            continue
        # A table cell's ``\\|`` reaches the inline parser as ``|``: an unescaped one
        # would have ended the cell.
        if char in _ACTIVE and not (cell and char == "|"):
            active = True
        i += 1
    if active:
        findings.active.append(source)


def _count(children: list[Token]) -> int:
    total = 0
    for child in children:
        if child.type == "code_inline":
            total += 1
        elif child.type == "footnote_ref":
            total += 3
        elif child.type == "link_open" and child.markup != "linkify":
            total += 1
    return total


def inspect(markdown: str) -> Findings:  # noqa: PLR0912
    findings = Findings()
    env: dict[str, Any] = {}
    tokens = _PARSER.parse(markdown, env)
    depth = 0
    columns = 0
    cell = False
    for token in tokens:
        if token.type in _NESTING:
            depth += 1
            findings.max_depth = max(findings.max_depth, depth)
        elif token.type in _CLOSING:
            depth -= 1
        if token.type in _BLOCKS:
            findings.blocks += 1
        if token.type == "html_block":
            findings.html.append(token.content)
        if token.type in ("th_close", "td_close"):
            cell = False
        if token.type == "tr_open":
            columns = 0
        elif token.type in ("th_open", "td_open"):
            cell = True
            columns += 1
            findings.max_columns = max(findings.max_columns, columns)
        if token.type != "inline":
            continue
        children = token.children or []
        findings.inline = max(findings.inline, _count(children))
        _scan(token.content, findings, cell=cell)
        inline_depth = depth
        for child in children:
            if child.type in _NESTING:
                inline_depth += 1
                findings.max_depth = max(findings.max_depth, inline_depth)
            elif child.type in _CLOSING:
                inline_depth -= 1
            if child.type == "html_inline":
                findings.html.append(child.content)
            elif child.type == "image":
                findings.images += 1
            elif child.type == "link_open":
                findings.links.append(str(child.attrs.get("href", "")))
    references: dict[str, dict[str, str]] = env.get("references", {})
    findings.links.extend(reference["href"] for reference in references.values())
    return findings
