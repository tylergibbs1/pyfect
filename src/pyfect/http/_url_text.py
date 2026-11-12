"""Request-target and form-body text helpers (Effect's internal ``http/internal/urlParams``)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit

from pyfect._url import Url
from pyfect.http.url_params import UrlParams, parse

_ORIGIN_FORM = re.compile(r"/(?![/\\])")


@dataclass(frozen=True, slots=True)
class UrlParts:
    """``urlsplit``'s five parts; ``str()`` puts them back together."""

    scheme: str
    netloc: str
    path: str
    query: str
    fragment: str

    def __str__(self) -> str:
        return urlunsplit((self.scheme, self.netloc, self.path, self.query, self.fragment))


def split_url(url: str) -> UrlParts | None:
    """``urlsplit(url)``; ``None`` where it raises (a ``[`` with no ``]`` in the
    authority). Request-facing code splits URLs only through this
    (``tests/test_split_url_guard.py``): a raise there is a defect, a 500."""
    try:
        parts = urlsplit(url)
    except ValueError:
        return None
    return UrlParts(parts.scheme, parts.netloc, parts.path, parts.query, parts.fragment)


def strip_search_and_hash(url: str) -> str:
    """``url`` without its query and fragment."""
    ends = [index for index in (url.find("?"), url.find("#")) if index != -1]
    return url[: min(ends)] if ends else url


def to_path(url: str) -> str:
    """The path of a request target: an origin-form target or ``*`` without its query and
    fragment, an absolute URL (which can carry credentials) reduced to its pathname."""
    if url == "*" or _ORIGIN_FORM.match(url):
        return strip_search_and_hash(url)
    parsed = Url.parse(url, "http://localhost")
    return "<invalid URL>" if parsed is None else parsed.pathname


def params_from_body(data: bytes) -> UrlParams:
    """An ``application/x-www-form-urlencoded`` body as ``URLSearchParams`` reads it, but a
    leading U+FEFF and a leading ``?`` are form data, not a byte order mark or query prefix."""
    text = data.decode("utf-8", "replace")
    return parse("%3F" + text[1:] if text.startswith("?") else text)
