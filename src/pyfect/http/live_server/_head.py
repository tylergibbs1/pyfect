"""Request heads (RFC 9112): the request line, the header fields and how
the body is framed. Parsing is strict, as Node's ``llhttp`` is: a head it
cannot read is a ``HeadError`` with the status to answer. Values are
trimmed of optional whitespace (SP and HTAB) only, the request-target is
one of the four forms of RFC 9112 §3.2, and ``Host`` is an authority."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal
from urllib.parse import urlsplit

from pyfect._digits import parse_digits
from pyfect.http._authority import ROOT, Authority, OriginForm, parse_authority, parse_origin_form
from pyfect.http.headers import Headers

_TOKEN = re.compile(rb"[!#$%&'*+\-.^_`|~0-9A-Za-z]+\Z")
_VERSION = re.compile(rb"HTTP/(\d)\.(\d)\Z")
_OWS = " \t"
_FIELD_VALUE = re.compile(rb"[\t\x20-\x7e\x80-\xff]*\Z")
_TARGET = re.compile(rb"[\x21-\x7e\x80-\xff]+\Z")


class HeadError(Exception):
    """A head that cannot be read: ``status`` is the response it gets."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status


@dataclass(frozen=True, slots=True)
class Length:
    """A body of ``size`` bytes (``0``: none)."""

    size: int


@dataclass(frozen=True, slots=True)
class Chunked:
    """A chunked body."""


type Framing = Length | Chunked


@dataclass(frozen=True, slots=True)
class RequestHead:
    """``target`` is the path and query (or ``*``; ``/`` for a
    ``CONNECT``); ``authority`` is where it was sent, from ``Host``, a
    ``CONNECT``'s target or an absolute-form target (which replaces
    ``host``)."""

    method: str
    target: OriginForm | Literal["*"]
    authority: Authority | None
    version: tuple[int, int]
    headers: Headers
    framing: Framing
    keep_alive: bool
    expect: Literal["continue", "none"]
    upgrade: str | None


def _items(value: str) -> list[str]:
    """The lowercase items of a comma-separated field value, trimmed of
    optional whitespace (SP and HTAB) only: ``str.strip()`` would also
    take NBSP and NEL, which a strict parser keeps as part of the item."""
    return [item.strip(_OWS).lower() for item in value.split(",")]


def _connection_tokens(headers: dict[str, str]) -> set[str]:
    return set(_items(headers.get("connection", "")))


def _framing(headers: dict[str, str], version: tuple[int, int]) -> Framing:
    transfer_encoding = headers.get("transfer-encoding")
    content_length = headers.get("content-length")
    if transfer_encoding is not None:
        if content_length is not None:
            raise HeadError(400, "Content-Length with Transfer-Encoding")
        codings = _items(transfer_encoding)
        if version < (1, 1) or codings[-1] != "chunked" or codings.count("chunked") != 1:
            raise HeadError(400, "Invalid Transfer-Encoding")
        if codings != ["chunked"]:
            raise HeadError(501, "Unsupported Transfer-Encoding")
        return Chunked()
    if content_length is None:
        return Length(0)
    values = set(_items(content_length))
    if len(values) != 1:
        raise HeadError(400, "Invalid Content-Length")
    length = parse_digits(values.pop())
    if length is None:
        raise HeadError(400, "Invalid Content-Length")
    return Length(length)


def _add(headers: dict[str, str], name: str, value: str) -> None:
    previous = headers.get(name)
    if previous is None:
        headers[name] = value
    elif name == "cookie":
        headers[name] = f"{previous}; {value}"
    elif name == "host":
        raise HeadError(400, "Duplicate Host")
    else:
        headers[name] = f"{previous}, {value}"


def _authority(text: str) -> Authority:
    authority = parse_authority(text)
    if authority is None:
        raise HeadError(400, "Invalid Host")
    return authority


def _target(
    method: str, target: str, headers: dict[str, str]
) -> tuple[OriginForm | Literal["*"], Authority | None]:
    """The path and query (or ``*``) and the authority the request was sent
    to: ``Host``, a ``CONNECT``'s target, or an absolute-form target, which
    replaces ``host`` (RFC 9112 §3.2.2)."""
    origin = parse_origin_form(target)
    if origin is not None or target == "*":
        host = _authority(headers["host"]) if headers.get("host") else None
        return origin or "*", host
    if method == "CONNECT":
        return ROOT, _authority(target)
    parts = urlsplit(target)
    if parts.scheme.lower() not in ("http", "https") or not target[len(parts.scheme) :].startswith(
        "://"
    ):
        raise HeadError(400, "Invalid request-target")
    authority = _authority(parts.netloc)
    headers["host"] = authority
    path = parts.path or "/"
    origin = parse_origin_form(f"{path}?{parts.query}" if parts.query else path)
    if origin is None:
        raise HeadError(400, "Invalid request-target")
    return origin, authority


def parse_field_line(line: bytes) -> tuple[str, str]:
    """A header or trailer field line (RFC 9112 §5): its lowercase name
    and its value without optional whitespace."""
    name, colon, value = line.partition(b":")
    if not colon or not _TOKEN.match(name):
        raise HeadError(400, "Invalid header field")
    value = value.strip(b" \t")
    if not _FIELD_VALUE.match(value):
        raise HeadError(400, "Invalid header value")
    return name.decode("ascii").lower(), value.decode("latin-1")


def parse_head(data: bytes) -> RequestHead:
    """The head ``data`` holds: the lines before the blank one, without
    their line ends."""
    lines = data.split(b"\r\n")
    parts = lines[0].split(b" ")
    if len(parts) != 3 or not _TOKEN.match(parts[0]) or not _TARGET.match(parts[1]):
        raise HeadError(400, "Invalid request line")
    version_match = _VERSION.match(parts[2])
    if version_match is None:
        raise HeadError(400, "Invalid HTTP version")
    version = (int(version_match[1]), int(version_match[2]))
    if version not in ((1, 0), (1, 1)):
        raise HeadError(505, "HTTP Version Not Supported")
    headers: dict[str, str] = {}
    for line in lines[1:]:
        _add(headers, *parse_field_line(line))
    if version == (1, 1) and "host" not in headers:
        raise HeadError(400, "Missing Host")
    method = parts[0].decode("ascii")
    target, authority = _target(method, parts[1].decode("latin-1"), headers)
    framing = _framing(headers, version)
    tokens = _connection_tokens(headers)
    keep_alive = "keep-alive" in tokens if version == (1, 0) else "close" not in tokens
    expect_header = headers.get("expect")
    if expect_header is not None and _items(expect_header) != ["100-continue"]:
        raise HeadError(417, "Expectation Failed")
    upgrade = headers.get("upgrade") if "upgrade" in tokens else None
    return RequestHead(
        method,
        target,
        authority,
        version,
        Headers._unsafe(headers),  # pyright: ignore[reportPrivateUsage]
        framing,
        keep_alive,
        "continue" if expect_header is not None and version == (1, 1) else "none",
        upgrade,
    )
