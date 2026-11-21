"""Every ``https://pyfect.dev/docs/...`` URL that the code (in an error
message, say), the changelog or a fragment in changes/ gives names a guide,
or an old URL the site redirects: a renamed guide must leave a redirect behind."""

from __future__ import annotations

import re

import _source

ROOT = _source.ROOT
DOCS = ROOT / "website" / "content" / "docs"
_URL = re.compile(r"https://pyfect\.dev(/docs[A-Za-z0-9_/-]*)")
_REDIRECT = re.compile(r"source: '(/docs[^']*)'")


def _given() -> set[str]:
    texts = [_source.text(p) for p in _source.files(ROOT / "src")]
    texts += [(ROOT / name).read_text() for name in ("CHANGELOG.md", "README.md")]
    texts += [fragment.read_text() for fragment in (ROOT / "changes").glob("*.md")]
    return {url.rstrip("/") for text in texts for url in _URL.findall(text)}


def _served() -> set[str]:
    # A section directory is served, even one whose pages are generated (reference/).
    pages = {"/docs"} | {"/docs/" + d.relative_to(DOCS).as_posix() for d in DOCS.rglob("*/")}
    for page in DOCS.rglob("*.mdx"):
        path = page.relative_to(DOCS).with_suffix("").as_posix()
        pages.add("/docs/" + path.removesuffix("/index").removesuffix("index").rstrip("/"))
    config = (ROOT / "website" / "next.config.mjs").read_text()
    return pages | set(_REDIRECT.findall(config))


def test_every_docs_url_the_code_gives_is_served() -> None:
    given = _given()
    assert "/docs/eventlog-upgrade-0-6-7" in given  # still linked from the 0.6.7 notes
    assert sorted(given - _served()) == []
