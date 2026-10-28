"""Conditional requests (RFC 9110 §13): ``If-None-Match``,
``If-Modified-Since`` and ``If-Range`` against a file response."""

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


def _matches_if_none_match(if_none_match: str, etag: str | None) -> bool:
    normalized = None if etag is None else _strip_weak(etag)
    for candidate in if_none_match.split(","):
        value = candidate.strip()
        if value == "":
            continue
        if value == "*" or (normalized is not None and _strip_weak(value) == normalized):
            return True
    return False


def _not_modified_since(if_modified_since: str, last_modified: str | None) -> bool:
    """An invalid date on either side disables the precondition."""
    if last_modified is None:
        return False
    since = parse_http_date(if_modified_since)
    modified = parse_http_date(last_modified)
    return isinstance(since, Ok) and isinstance(modified, Ok) and modified.value <= since.value


def matches_if_range(if_range: str, etag: str | None) -> bool:
    """Only a strong entity-tag matches: weak tags start with ``W/``, and
    dates never match, as file metadata cannot prove the file did not
    change twice within a second."""
    value = if_range.strip()
    return value.startswith('"') and value == etag


def _not_modified(response: HttpServerResponse) -> HttpServerResponse:
    kept = {
        name: value
        for name, value in (
            ("ETag", response.headers.get("etag")),
            ("Cache-Control", response.headers.get("cache-control")),
            ("Last-Modified", response.headers.get("last-modified")),
        )
        if value is not None
    }
    return empty(status=304, headers=kept)


def evaluate(request: ServerRequest, response: HttpServerResponse) -> HttpServerResponse | None:
    """The ``304`` the request's preconditions call for, if any."""
    if_none_match = request.headers.get("if-none-match")
    if if_none_match is not None:
        etag = response.headers.get("etag")
        return _not_modified(response) if _matches_if_none_match(if_none_match, etag) else None
    if_modified_since = request.headers.get("if-modified-since")
    last_modified = response.headers.get("last-modified")
    if if_modified_since is not None and _not_modified_since(if_modified_since, last_modified):
        return _not_modified(response)
    return None
