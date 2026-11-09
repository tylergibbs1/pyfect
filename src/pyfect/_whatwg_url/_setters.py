"""The setters of the URL Standard's ``URL`` API, each from a record to a
new record (the record itself when the setter changes nothing)."""

from __future__ import annotations

from dataclasses import replace

from pyfect._whatwg_url import _percent
from pyfect._whatwg_url._parser import State, parse, parse_from
from pyfect._whatwg_url._record import UrlRecord


def set_href(url: UrlRecord, value: str) -> UrlRecord | None:
    """``None`` when ``value`` is not a URL (``URL``'s setter throws)."""
    return parse(value)


def set_protocol(url: UrlRecord, value: str) -> UrlRecord:
    return parse_from(url, f"{value}:", State.SCHEME_START)


def set_username(url: UrlRecord, value: str) -> UrlRecord:
    if url.cannot_have_credentials_or_port:
        return url
    return replace(url, username=_percent.encode(value, _percent.USERINFO))


def set_password(url: UrlRecord, value: str) -> UrlRecord:
    if url.cannot_have_credentials_or_port:
        return url
    return replace(url, password=_percent.encode(value, _percent.USERINFO))


def set_host(url: UrlRecord, value: str) -> UrlRecord:
    if isinstance(url.path, str):
        return url
    return parse_from(url, value, State.HOST)


def set_hostname(url: UrlRecord, value: str) -> UrlRecord:
    if isinstance(url.path, str):
        return url
    return parse_from(url, value, State.HOSTNAME)


def set_port(url: UrlRecord, value: str) -> UrlRecord:
    if url.cannot_have_credentials_or_port:
        return url
    if value == "":
        return replace(url, port=None)
    return parse_from(url, value, State.PORT)


def set_pathname(url: UrlRecord, value: str) -> UrlRecord:
    if isinstance(url.path, str):
        return url
    return parse_from(replace(url, path=()), value, State.PATH_START)


def set_search(url: UrlRecord, value: str) -> UrlRecord:
    if value == "":
        return replace(url, query=None)
    return parse_from(replace(url, query=""), value.removeprefix("?"), State.QUERY)


def set_hash(url: UrlRecord, value: str) -> UrlRecord:
    if value == "":
        return replace(url, fragment=None)
    return parse_from(replace(url, fragment=""), value.removeprefix("#"), State.FRAGMENT)


def set_query(url: UrlRecord, serialized: str) -> UrlRecord:
    """The query ``URLSearchParams`` writes after a change: absent when it
    has no pairs."""
    return replace(url, query=serialized or None)
