"""Port of Effect's ``packages/chat/whatsapp/test/text.test.ts``: Markdown
renders to WhatsApp's formatting and never grows, in code points, UTF-16 units
or UTF-8 bytes. The last tests are pyfect's: text built to make the scanner
quadratic, or to nest it past Python's stack, renders in linear time."""

from __future__ import annotations

from collections.abc import Callable

import pytest
from _growth import assert_near_linear
from hypothesis import given, settings
from hypothesis import strategies as st

from pyfect.chat.whatsapp._text import MAX_NESTING, fits, render

CASES = [
    ("**b** and __b__", "*b* and *b*"),
    ("*i* and _i_", "_i_ and _i_"),
    ("~~s~~ and ~s~", "~s~ and ~s~"),
    ("**a *b* c**", "*a _b_ c*"),
    ('[label](https://e.com "title")', "label (https://e.com)"),
    ("![alt](https://e.com/a.png)", "alt (https://e.com/a.png)"),
    ("[](https://e.com)", "https://e.com"),
    ("<https://e.com>", "https://e.com"),
    ("# Title #", "*Title*"),
    ("Title\n===\n", "*Title*\n"),
    ("#", "#"),
    ("| a | b |\n|---|---|\n| 1 | 2 |", "| a | b |\n| 1 | 2 |"),
    ("~~~ts\n**x**\n~~~\n", "```\n**x**\n```\n"),
    ("&amp; &lt; &#233; &#x1F600;", "& < é \U0001f600"),
    ("&nGt; &nLt; &ast; &#42;", "&nGt; &nLt; &ast; &#42;"),
    ("[a][r] and [r]\n\n[r]: https://e.com", "[a][r] and [r]\n\n[r]: https://e.com"),
    ("`**x**` ``a`` \\*x\\* <b>**x**</b>", "`**x**` ``a`` \\*x\\* <b>*x*</b>"),
    ("a_b_c and 2*3*4", "a_b_c and 2_3_4"),
    ("    **indented**", "    **indented**"),
    ("- **item**\n> **quote**", "- *item*\n> *quote*"),
    (
        "[**x**] and ![**y**]\n\n[**x**]: https://e.com",
        "[**x**] and ![**y**]\n\n[**x**]: https://e.com",
    ),
    ('[r]:\n  <https://e.com>\n  "**t**"\n\n**x**', '[r]:\n  <https://e.com>\n  "**t**"\n\n*x*'),
    ("> ~~~js\n> **x**\n> ~~~\n\n**y**", "> ~~~js\n> **x**\n> ~~~\n\n*y*"),
    ("- ```\n  **x**\n  ```", "- ```\n  **x**\n  ```"),
    ("> ~~~js\n> > ~~~\n> **x**\n> ~~~\n\n**y**", "> ~~~js\n> > ~~~\n> **x**\n> ~~~\n\n*y*"),
    ("- > ~~~\n  >       ~~~\n  > **x**\n  > ~~~", "- > ~~~\n  >       ~~~\n  > **x**\n  > ~~~"),
    ("> ~~~\n> **x**\n\n**y**", "> ~~~\n> **x**\n\n*y*"),
    ("[r]: /url\n~~~js\n\n**x**\n~~~", "[r]: /url\n```\n\n**x**\n```"),
    ("| a |\n|---|\n~~~\n\n**x**\n~~~", "| a |\n```\n\n**x**\n```"),
    ("- ~~~js\n\t  ~~~\n  **x**\n  ~~~", "- ~~~js\n\t  ~~~\n  **x**\n  ~~~"),
    (">\t  ~~~\n>\t  **x**\n>\t  ~~~", ">\t  ~~~\n>\t  **x**\n>\t  ~~~"),
]


def _longer(markdown: str) -> str | None:
    output = render(markdown)
    return None if fits(output, markdown) else output


@pytest.mark.parametrize(("markdown", "expected"), CASES)
def test_renders_each_construct(markdown: str, expected: str) -> None:
    """render / renders each construct"""
    assert render(markdown) == expected


_TOKENS = [
    "*",
    "**",
    "_",
    "__",
    "~",
    "~~",
    "`",
    "```",
    "#",
    "# ",
    "[",
    "]",
    "(",
    ")",
    "![",
    "<",
    ">",
    "&",
    ";",
    "\\",
    "|",
    "|---|",
    "-",
    "=",
    "\n",
    " ",
    "a",
    "é",
    "\U0001f600",
    "https://e.com",
    "&amp;",
    "&#",
    "&nGt;",
    "~~~",
    "x",
    "> ",
    "- ",
    "  ",
    "[r]: u",
]


@settings(max_examples=300, deadline=None)
@given(st.lists(st.sampled_from(_TOKENS), max_size=40))
def test_never_grows_markdown_in_code_points_utf16_units_or_utf8_bytes(tokens: list[str]) -> None:
    """render / never grows Markdown, in code points, UTF-16 units or UTF-8 bytes"""
    assert _longer("".join(tokens)) is None


def test_never_grows_a_character_reference() -> None:
    """render / never grows a character reference"""
    numbers = [0, 1, 0x2A, 0x7F, 0x80, 0x7FF, 0x800, 0xD800, 0xFFFF, 0x10000, 0x10FFFF, 0x110000]
    names = ["amp", "lt", "nbsp", "hellip", "mdash", "frac34", "iquest", "nGt", "ast"]
    references = [f"&{name}" for name in names] + [
        reference for n in numbers for reference in (f"&#{n}", f"&#x{n:x}")
    ]
    for reference in references:
        for markdown in (reference, reference + ";"):
            assert _longer(markdown) is None, markdown


# --- pyfect: bounded work on text built against the scanner ------------------------------

ADVERSARIAL: dict[str, Callable[[int], str]] = {
    "unmatched brackets": lambda n: "[" * n,
    "unmatched openers": lambda n: "*a " * (n // 3),
    "backtick runs": lambda n: "".join("`" * (1 + i % 7) + " " for i in range(n // 5)),
    "comment openers": lambda n: "<!--" * (n // 4),
    "footnote openers": lambda n: "[^" * (n // 2),
    "references": lambda n: "[a][" * (n // 4),
    "angle destinations": lambda n: "[a](<" * (n // 5),
    "titles": lambda n: '[a](u "' * (n // 7),
    "html openers": lambda n: "<a " * (n // 3),
}


@pytest.mark.parametrize("name", ADVERSARIAL)
def test_text_built_to_be_quadratic_renders_in_linear_time_and_never_grows(name: str) -> None:
    build = ADVERSARIAL[name]
    markdown = build(4000)
    assert fits(render(markdown), markdown)

    def make(n: int) -> Callable[[], object]:
        text = build(n)
        return lambda: render(text)

    assert_near_linear(make, 2000)


def test_nesting_past_the_cap_is_kept_as_typed_not_a_recursion_error() -> None:
    # Each level opens a link label: Effect recurses once per level, which in Python
    # would run out of stack long before the input does.
    depth = 2000
    markdown = "[" * depth + "x" + "](u)" * depth
    output = render(markdown)
    assert fits(output, markdown)
    shallow = "[" * (MAX_NESTING - 2) + "**x**" + "](u)" * (MAX_NESTING - 2)
    assert "*x*" in render(shallow)


def test_ordinary_markdown_is_rendered_not_given_up_on() -> None:
    paragraph = "Some **bold**, some _italic_, a [link](https://e.com) and `code`. " * 60
    output = render(paragraph)
    assert "**" not in output
    assert "*bold*" in output
