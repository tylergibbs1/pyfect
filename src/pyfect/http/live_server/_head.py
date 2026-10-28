"""Request heads (RFC 9112): the request line, the header fields and how
the body is framed. Parsing is strict, as Node's ``llhttp`` is: a head it
cannot read is a ``HeadError`` with the status to answer."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from pyfect.http.headers import Headers

_TOKEN = re.compile(rb"[!#$%&'*+\-.^_`|~0-9A-Za-z]+\Z")
_VERSION = re.compile(rb"HTTP/(\d)\.(\d)\Z")
_DIGITS = re.compile(rb"\d+\Z")
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
    method: str
    target: str
    version: tuple[int, int]
    headers: Headers
    framing: Framing
    keep_alive: bool
    expect: Literal["continue", "none"]
    upgrade: str | None


def _connection_tokens(headers: dict[str, str]) -> set[str]:
    return {token.strip().lower() for token in headers.get("connection", "").split(",")}


def _framing(headers: dict[str, str], version: tuple[int, int]) -> Framing:
    transfer_encoding = headers.get("transfer-encoding")
    content_length = headers.get("content-length")
    if transfer_encoding is not None:
        if content_length is not None:
            raise HeadError(400, "Content-Length with Transfer-Encoding")
        codings = [coding.strip().lower() for coding in transfer_encoding.split(",")]
        if version < (1, 1) or codings[-1] != "chunked" or codings.count("chunked") != 1:
            raise HeadError(400, "Invalid Transfer-Encoding")
        if codings != ["chunked"]:
            raise HeadError(501, "Unsupported Transfer-Encoding")
        return Chunked()
    if content_length is None:
        return Length(0)
    values = {value.strip() for value in content_length.split(",")}
    if len(values) != 1:
        raise HeadError(400, "Invalid Content-Length")
    value = values.pop().encode()
    if not _DIGITS.match(value):
        raise HeadError(400, "Invalid Content-Length")
    return Length(int(value))


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
        name, colon, value = line.partition(b":")
        if not colon or not _TOKEN.match(name):
            raise HeadError(400, "Invalid header field")
        value = value.strip(b" \t")
        if not _FIELD_VALUE.match(value):
            raise HeadError(400, "Invalid header value")
        _add(headers, name.decode("ascii").lower(), value.decode("latin-1"))
    if version == (1, 1) and "host" not in headers:
        raise HeadError(400, "Missing Host")
    framing = _framing(headers, version)
    tokens = _connection_tokens(headers)
    keep_alive = "keep-alive" in tokens if version == (1, 0) else "close" not in tokens
    expect_header = headers.get("expect")
    if expect_header is not None and expect_header.strip().lower() != "100-continue":
        raise HeadError(417, "Expectation Failed")
    upgrade = headers.get("upgrade") if "upgrade" in tokens else None
    return RequestHead(
        parts[0].decode("ascii"),
        parts[1].decode("latin-1"),
        version,
        Headers._unsafe(headers),  # pyright: ignore[reportPrivateUsage]
        framing,
        keep_alive,
        "continue" if expect_header is not None and version == (1, 1) else "none",
        upgrade,
    )
