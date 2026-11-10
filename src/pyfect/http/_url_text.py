"""Request-target and form-body text helpers (Effect's internal ``http/internal/urlParams``)."""

from __future__ import annotations

import re

from pyfect._url import Url
from pyfect.http.url_params import UrlParams, parse

_ORIGIN_FORM = re.compile(r"/(?![/\\])")


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
