"""Port of Effect's ``packages/chat/telegram/test/markdown.test.ts``: the
rendered Markdown stays within what ``measure`` charged and Telegram's
limits, and carries no raw HTML, image, math, spoiler or link outside http,
https and mailto. A GFM parser (``tests/_gfm.py``) reads the output."""

from __future__ import annotations

import re

import pytest
from _gfm import inspect
from hypothesis import given, settings
from hypothesis import strategies as st

from pyfect.chat.telegram._markdown import (
    MAX_COLUMNS,
    MAX_DEPTH,
    MAX_FOOTNOTE_REFERENCES,
    MAX_INLINE_NODES,
    MESSAGE_LENGTH,
    RESERVATION,
    measure,
    render,
)

MENTIONS = frozenset({"2"})
"""The users whose ``tg://user`` links stay links."""

_ALLOWED_LINK = re.compile(r"(?:https?://|mailto:)", re.IGNORECASE | re.ASCII)


def assert_inert(source: str) -> None:
    """Fails with what a GFM parse of ``render(source)`` finds that the
    renderer promises it never holds."""
    out = render(source, mentions=MENTIONS)
    found = inspect(out)
    context = f"{source!r} rendered {out!r}"
    assert found.html == [], context
    assert found.images == 0, context
    assert [
        url for url in found.links if not _ALLOWED_LINK.match(url) and url != "tg://user?id=2"
    ] == [], context
    assert found.active == [], context
    assert found.unhonored == [], context
    assert found.max_depth <= MAX_DEPTH, context
    assert found.max_columns <= MAX_COLUMNS, context
    assert found.inline <= MAX_INLINE_NODES, context
    # The most blocks Telegram renders in one message.
    if measure(source) <= MESSAGE_LENGTH:
        assert found.blocks <= 500, context


# Live check 2 found that Telegram ignores the escapes ``\]`` and ``\<``, reads
# destinations verbatim, reads definitions more loosely than CommonMark and
# opens emphasis between spaces.
CORPUS = [
    (
        "<b>hi</b> <https://e.com> <javascript:alert(1)>",
        "&lt;b>hi&lt;/b> <https://e.com> &lt;javascript:alert(1)>",
    ),
    ("![a](https://e.com/a.png) ![b][r]", "\\![a](https://e.com/a.png) \\![b][r]"),
    (
        "[me](tg://user?id=1) [ok](tg://user?id=2)",
        "[me]\\(tg://user?id\\=1) [ok](tg://user?id=2)",
    ),
    ("| a | b |\n|---|---|\n| 1 | 2 |", "| a | b |\n|---|---|\n| 1 | 2 |"),
    (">>>>>>>>>>>>>>>>> x", ">>>>>>>>>>>>>>>\\>\\> x"),
    (
        "[x\\](tg://resolve?domain=telegram) \\<b>x\\</b>",
        "\\[x&#93;(tg://resolve?domain\\=telegram) &#60;b>x&#60;/b>",
    ),
    (
        '[a](https://e.com/?q=1&x=2 "t") [b](https://e.com/a_b*c\\(d\\))',
        "[a](https://e.com/?q=1&x=2) [b](https://e.com/a_b*c%28d%29)",
    ),
    (
        "[a][b]: tg://x\n\n [c]: tg://x\n\ntext\n[d]: https://e.com",
        "\\[a][b]: tg://x\n\n \\[c]: tg://x\n\ntext\n\\[d]: https://e.com",
    ),
    ("2 * 3 * 4 a _ b\n\n***", "2 \\* 3 \\* 4 a \\_ b\n\n***"),
    # a definition is refused once, keeps no title, and loses no text
    (
        (
            '[a[b]: https://e.com\n\n[^ a]: https://e.com\n\n[c]: https://e.com "t"\n'
            "[d]: https://e.com d"
        ),
        (
            "\\[a[b]: https://e.com\n\n\\[^ a]: https://e.com\n\n[c]: https://e.com\n"
            "\\[d]: https://e.com d"
        ),
    ),
    # a label that renders to 999 characters stays a definition, one of 1,000 does not
    ("[" + "$" * 499 + "]: mailto:x", "[" + "\\$" * 499 + "]: mailto:x"),
    ("[" + "$" * 500 + "]: mailto:x", "\\[" + "\\$" * 500 + "]: mailto:x"),
    # a destination keeps parentheses three deep, not four
    ("[a](https://e.com/(((x))))", "[a](https://e.com/(((x))))"),
    ("[a](https://e.com/((((x)))))", "[a]\\(https://e.com/((((x)))))"),
]


@pytest.mark.parametrize(("source", "expected"), CORPUS)
def test_escapes_the_hostile_corpus(source: str, expected: str):
    """render / escapes the hostile corpus"""
    assert render(source, mentions=MENTIONS) == expected


INERT = [
    # a fence may be indented up to three spaces
    " ~~~\nx\n~~~\n[ping](tg://user?id=123) <b>",
    # a heading ends a table
    "| a | b |\n|---|---|\n# heading\n||secret||",
    # a lazy continuation line stays in the containers it does not repeat
    ">" * 15 + " x\n" + "_" * 14 + "x" + "_" * 14,
    "2. <\n x_\n=",
    # a footnote's text is no table
    "[^a]: x|y\n---|---\n||secret||",
    # nor a lone pipe a header
    "|\n-|",
    # a table goes on past a line it does not end at
    "|a|\n|---|\n[a]: mailto:x\nb `<b>|`",
    # a line of U+00A0 is text, so it ends no paragraph
    ">" * 15 + " x\n\u00a0\n" + "_" * 14 + "x" + "_" * 14,
    # a reference may turn the outer link into text, and its destination into Markdown
    "[a][inner](mailto:[pwn](tg://user?id=1))\n\n[inner]: https://safe.com",
    # unbalanced parentheses end no destination
    "[](mailto:$(> )",
    # a code span or an autolink hides no label's end from CommonMark
    "[>\\]: mailto:]:[^a]",
    # indented, a footnote's label is a definition's
    "[a]: mailto:x\n    [^a]: tg://x",
    # nor is an autolink with a control character one
    "<https://e.com|\u0001|>",
]

_HOSTILE_UNITS = [
    *"<>$=|![]()*_~`#-+.:/\\&;\n \t\"'0a",
    "~~~",
    "```",
    " ~~~",
    "- ",
    "> ",
    "1. ",
    "https://e.com",
    "www.e.co",
    "x@e.co",
    "tg://user?id=1",
    "<b>",
    "](",
    "[^",
    "[^a]: ",
    "|---|",
    "\\]",
    "\\<",
    "\\`",
    "[a]",
    "\n[a]: mailto:x\n",
    # whitespace that is not a blank line to CommonMark
    "\u00a0",
    "\u3000",
    "\v",
    "\f",
]


@pytest.mark.parametrize("source", INERT)
def test_leaves_a_gfm_parser_no_html_image_foreign_link_math_spoiler_or_excess_nesting(
    source: str,
):
    """render / leaves a GFM parser no HTML, image, foreign link, math, spoiler or excess nesting"""
    assert_inert(source)


@settings(max_examples=500, deadline=None)
@given(st.lists(st.sampled_from(_HOSTILE_UNITS), max_size=60).map("".join))
def test_leaves_a_gfm_parser_nothing_active_for_hostile_input(source: str):
    """render / leaves a GFM parser no HTML, image, foreign link, math, spoiler or excess
    nesting (property)"""
    assert_inert(source)


@pytest.mark.parametrize("line", ["- - - a\n", "1. a\n"])
def test_keeps_output_that_fills_the_budget_under_500_blocks(line: str):
    """render / keeps output that fills the budget under 500 blocks"""
    # The most copies of ``line`` that fit, found by bisection.
    low, high = 0, MESSAGE_LENGTH
    while low < high:
        middle = (low + high + 1) // 2
        if measure(line * middle) <= MESSAGE_LENGTH:
            low = middle
        else:
            high = middle - 1
    assert_inert(line * low)


def test_caps_the_code_spans_references_and_footnote_references_telegram_refuses_past_a_limit():
    """render / caps the code spans, references and footnote references Telegram refuses
    past a limit"""
    spans = render("`a` " * (MAX_INLINE_NODES + 10))
    assert len(re.findall(r"(?<!\\)`a(?<!\\)`", spans)) == MAX_INLINE_NODES
    shortcuts = "[a] " * (MAX_INLINE_NODES + 10) + "\n\n[a]: https://e.com"
    assert measure(shortcuts) <= MESSAGE_LENGTH
    assert inspect(render(shortcuts)).inline == MAX_INLINE_NODES
    references = render("\n\n".join("x[^1]" * 100 for _ in range(10)) + "\n\n[^1]: n")
    assert len(re.findall(r"(?<!\\)\[\^1\]", references)) == MAX_FOOTNOTE_REFERENCES + 1


def test_escapes_the_pipes_of_a_table_wider_than_20_columns():
    """render / escapes the pipes of a table wider than 20 columns"""

    def row(cell: str) -> str:
        return "|" + f" {cell} |" * 21

    assert re.search(r"(^|[^\\])\|", render(row("c") + "\n" + row("-"))) is None


def test_closes_an_open_fence_before_the_media_references():
    """render / closes an open fence before the media references"""
    assert render("```\n<b>", files=1) == "```\n<b>\n```\n\n![](tg://document?id=f1)"


_MEASURE_UNITS = st.one_of(
    st.sampled_from(
        [
            *"<>$=|![]()*_~`#-+.:/\\&;\n\r \t0123456789abc",
            "\x00",
            "é",
            "€",
            "😀",
            "\ud800",
            "tg://",
            "https://",
        ]
    ),
    st.text(max_size=3),
)


def _utf8_length(text: str) -> int:
    return len(text.encode("utf-8", "surrogatepass"))


@settings(max_examples=100, deadline=None)
@given(st.lists(_MEASURE_UNITS, max_size=200).map("".join), st.integers(0, 10))
def test_never_exceeds_measure_with_the_reservation_for_files(source: str, files: int):
    """render / never exceeds measure, with the reservation for files"""
    assert _utf8_length(render(source)) <= measure(source)
    assert _utf8_length(render(source, files=files)) <= measure(source) + RESERVATION
