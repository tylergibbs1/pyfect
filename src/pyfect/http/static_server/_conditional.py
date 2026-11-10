"""Conditional requests (RFC 9110 §13): ``If-Match``, ``If-Unmodified-Since``,
``If-None-Match``, ``If-Modified-Since`` and ``If-Range`` against a file response."""

from __future__ import annotations

import re

from pyfect.http.headers import parse_http_date
from pyfect.http.server_request import ServerRequest
from pyfect.http.server_response import HttpServerResponse, empty
from pyfect.result import Ok

_WEAK = re.compile(r"w/", re.IGNORECASE)


def _strip_weak(value: str) -> str:
    trimmed = value.strip()
    return trimmed[2:] if _WEAK.match(trimmed) else trimmed


# If-Match compares strongly (RFC 9110 §13.1.1), so weak tags never match. Tags may hold
# commas, so the list is checked whole rather than split; a malformed list matches nothing.
_ENTITY_TAG_LIST = re.compile(r'[\s,]*(?:(?:W/)?"[^"]*"\s*(?:,[\s,]*|\Z))*\Z')
_ENTITY_TAG = re.compile(r'(?:W/)?"[^"]*"')


def _matches_if_match(if_match: str, etag: str | None) -> bool:
    if if_match.strip() == "*":
        return True
    if etag is None or not etag.startswith('"') or not _ENTITY_TAG_LIST.match(if_match):
        return False
    return etag in _ENTITY_TAG.findall(if_match)


def _matches_if_none_match(if_none_match: str, etag: str | None) -> bool:
    normalized = None if etag is None else _strip_weak(etag)
    for candidate in if_none_match.split(","):
        value = candidate.strip()
        if value == "":
            continue
        if value == "*" or (normalized is not None and _strip_weak(value) == normalized):
            return True
    return False


def _modified_since(since: str, last_modified: str | None) -> bool | None:
    """Whether the file changed after ``since``; ``None`` when either date is missing or
    invalid, which disables the precondition (RFC 9110 §13.1.3-4)."""
    if last_modified is None:
        return None
    since_date = parse_http_date(since)
    modified = parse_http_date(last_modified)
    if not isinstance(since_date, Ok) or not isinstance(modified, Ok):
        return None
    return modified.value > since_date.value


def matches_if_range(if_range: str, etag: str | None) -> bool:
    """Only a strong entity-tag matches: weak tags start with ``W/``, and
    dates never match, as file metadata cannot prove the file did not
    change twice within a second."""
    value = if_range.strip()
    return value.startswith('"') and value == etag


# The headers a 304 repeats from the 200 (RFC 9110 §15.4.5), and Last-Modified for revalidation.
_NOT_MODIFIED_HEADERS = (
    "cache-control",
    "content-location",
    "date",
    "etag",
    "expires",
    "last-modified",
    "vary",
)


def _not_modified(response: HttpServerResponse) -> HttpServerResponse:
    kept = {
        name: value
        for name in _NOT_MODIFIED_HEADERS
        if (value := response.headers.get(name)) is not None
    }
    return empty(status=304, headers=kept)


HEADERS = ("if-match", "if-unmodified-since", "if-none-match", "if-modified-since")
"""The request headers that make a request conditional."""


def evaluate(request: ServerRequest, response: HttpServerResponse) -> HttpServerResponse | None:
    """The ``412`` or ``304`` the request's preconditions call for, if any. ``If-Match``
    and ``If-Unmodified-Since`` come before the cache validators and ranges."""
    etag = response.headers.get("etag")
    last_modified = response.headers.get("last-modified")
    if_match = request.headers.get("if-match")
    if if_match is not None:
        if not _matches_if_match(if_match, etag):
            return empty(status=412)
    else:
        if_unmodified_since = request.headers.get("if-unmodified-since")
        if (
            if_unmodified_since is not None
            and _modified_since(if_unmodified_since, last_modified) is True
        ):
            return empty(status=412)
    if_none_match = request.headers.get("if-none-match")
    if if_none_match is not None:
        return _not_modified(response) if _matches_if_none_match(if_none_match, etag) else None
    if_modified_since = request.headers.get("if-modified-since")
    if if_modified_since is not None and _modified_since(if_modified_since, last_modified) is False:
        return _not_modified(response)
    return None
