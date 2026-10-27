"""URL parsing as WHATWG's ``URL.canParse`` sees it, for ``config.url`` and
the schema codecs: a ``SplitResult``, or ``None``."""

from __future__ import annotations

import re
from urllib.parse import SplitResult, urlsplit

_SCHEME = re.compile(r"[A-Za-z][A-Za-z0-9+.\-]*")
_SPECIAL_SCHEMES = frozenset({"http", "https", "ws", "wss", "ftp"})


def parse_url(text: str) -> SplitResult | None:
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
    return url
