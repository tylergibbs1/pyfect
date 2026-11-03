"""The URL value every pyfect API gives back, and URL parsing as WHATWG's
``URL.canParse`` sees it, for ``config.url`` and the schema codecs."""

from __future__ import annotations

import re
from urllib.parse import SplitResult, urlsplit

_SCHEME = re.compile(r"[A-Za-z][A-Za-z0-9+.\-]*")
_SPECIAL_SCHEMES = frozenset({"http", "https", "ws", "wss", "ftp"})
# Schemes whose URLs always have an authority (``//``), even an empty one.
_AUTHORITY_SCHEMES = _SPECIAL_SCHEMES | {"file"}


class Url(SplitResult):
    """A URL: a ``urllib.parse.SplitResult`` whose ``str()`` is the URL
    written out (``f"{url}/items"`` builds a URL), as JavaScript's ``URL``
    writes its ``href``. ``Url(*urlsplit(text))`` makes one from text that
    is not checked; ``http.url.from_string`` parses and normalizes it."""

    __slots__ = ()

    def __str__(self) -> str:
        return write(self)


def write(url: SplitResult) -> str:
    """``url`` written out, as ``URL.href``."""
    authority = f"//{url.netloc}" if url.netloc or url.scheme in _AUTHORITY_SCHEMES else ""
    query = f"?{url.query}" if url.query else ""
    fragment = f"#{url.fragment}" if url.fragment else ""
    return f"{url.scheme}:{authority}{url.path}{query}{fragment}"


def as_url(url: SplitResult) -> Url:
    """``url`` as a ``Url`` (itself when it is one)."""
    return url if isinstance(url, Url) else Url._make(url)


def parse_url(text: str) -> Url | None:
    """``text`` as a URL: an absolute one with a valid scheme, a host for
    the special schemes and a numeric port in range; ``None`` otherwise."""
    if any(ch <= " " or ch == "\x7f" for ch in text):
        return None
    try:
        url = urlsplit(text)
        _ = url.port  # raises ValueError for a port that is not a number in range
    except ValueError:
        return None
    if not _SCHEME.fullmatch(url.scheme):
        return None
    if url.scheme.lower() in _SPECIAL_SCHEMES and not url.hostname:
        return None
    return Url._make(url)
