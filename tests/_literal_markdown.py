"""Whether Markdown shows as plain text: a CommonMark parse (with
strikethrough) that finds one paragraph of text and nothing else, no link,
emphasis, code, HTML or block. Used to check that an adapter's
``escape_markdown`` keeps user text from forming syntax."""

from __future__ import annotations

from markdown_it import MarkdownIt

_PARSER = MarkdownIt("commonmark").enable("strikethrough")
_PLAIN = frozenset({"text", "softbreak"})


def literal(markdown: str) -> str | None:
    """The text ``markdown`` shows, when it is one paragraph of text alone;
    otherwise ``None``."""
    tokens = _PARSER.parse(markdown)
    if [token.type for token in tokens] != ["paragraph_open", "inline", "paragraph_close"]:
        return None
    children = tokens[1].children or []
    if any(child.type not in _PLAIN for child in children):
        return None
    return "".join("\n" if child.type == "softbreak" else child.content for child in children)
