"""Every link in a docstring is an absolute URL.

The API reference on pyfect.dev renders docstrings as Markdown, so a link to a path
(``[Management key](/docs/guides/...)``) resolves against pyfect.dev, and an editor's hover
can't follow it at all. The generated OpenRouter client copied such links from OpenRouter's
OpenAPI spec and 45 reference pages linked to a pyfect.dev page that doesn't exist.
``website/scripts/check-links.mjs`` checks the built reference's links too."""

import ast
import re

import _source

_CODE = re.compile(r"``.*?``|`[^`\n]*`", re.DOTALL)
"""Inline code: ``Id[User]().key("name")`` reads like a link but isn't one."""
_LINK = re.compile(r"\]\(\s*<?([^)\s>]*)|\b(?:href|src)\s*=\s*[\"']([^\"']*)")
_ABSOLUTE = re.compile(r"[a-z][a-z0-9+.-]*:", re.IGNORECASE)
_URL_LIKE = re.compile(r"[\w./#?=&%~+-]+")
"""A target with no quotes, commas or parentheses: code like ``Parameter[str]("name", ...)``
in a literal block isn't a link."""


def relative_links(doc: str) -> list[str]:
    """The links in ``doc`` that a browser resolves against the page showing it."""
    found: list[str] = []
    for match in _LINK.finditer(_CODE.sub("", doc)):
        target = match.group(1) or match.group(2) or ""
        if target and not _ABSOLUTE.match(target) and _URL_LIKE.fullmatch(target):
            found.append(target)
    return found


def test_the_check_sees_a_relative_link_and_not_code() -> None:
    assert relative_links("A [Management key](/docs/guides/x) is required.") == ["/docs/guides/x"]
    assert relative_links("See [the guide](guides/x.md#y) or [top](#top).") == [
        "guides/x.md#y",
        "#top",
    ]
    assert relative_links('<a href="/docs/x">x</a>') == ["/docs/x"]
    assert relative_links("[guide](https://openrouter.ai/docs/x), [mail](mailto:a@b.c)") == []
    assert relative_links('``Id[User]().key("name")`` and ``derive[key](value)``') == []
    assert relative_links('    name = Parameter[str]("name", TYPES.NVarChar)') == []


def test_no_docstring_links_by_a_relative_url() -> None:
    bad = [
        f"{path.relative_to(_source.ROOT)}:{node.lineno}: {link}"
        for path in _source.files(_source.SRC)
        if _source.may_hold(path, "](") or _source.may_hold(path, "href")
        for node in _source.walk(path)
        if isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Constant)
        and isinstance(node.value.value, str)
        for link in relative_links(node.value.value)
    ]
    assert not bad, (
        "a docstring link resolves against pyfect.dev; link with an absolute URL (a generated "
        "package: give its target's docs_site in scripts/gen_ai_schemas.py):\n" + "\n".join(bad)
    )
