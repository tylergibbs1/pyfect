"""The URL Standard's basic URL parser: a state machine over the input's
code points, which the setters also run from a given state over a copy of
an existing URL."""

from __future__ import annotations

import contextlib
import re
from enum import Enum, auto

from pyfect._whatwg_url import _host, _percent
from pyfect._whatwg_url._record import SPECIAL_PORTS, UrlRecord

_ALPHA = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ")
_DIGITS = frozenset("0123456789")
_SCHEME_CHARS = _ALPHA | _DIGITS | frozenset("+-.")
_TAB_OR_NEWLINE = re.compile("[\t\n\r]")
_STRIP = "".join(chr(i) for i in range(0x21))
# Runs of characters a state only collects, consumed at once: the
# characters that end the run, by whether the URL is special (``\`` ends
# it too) and, for paths, whether a setter runs (``?`` and ``#`` do not).
_AUTHORITY_RUN = {False: re.compile(r"[^@/?#]+"), True: re.compile(r"[^@/?#\\]+")}
_PATH_RUN = {
    (False, False): re.compile(r"[^/?#]+"),
    (True, False): re.compile(r"[^/?#\\]+"),
    (False, True): re.compile(r"[^/]+"),
    (True, True): re.compile(r"[^/\\]+"),
}
_OPAQUE_PATH_RUN = re.compile(r"[^?# ]+")
_HOST_RUN = {False: re.compile(r"[^\[\]:/?#]+"), True: re.compile(r"[^\[\]:/?#\\]+")}
_SCHEME_RUN = re.compile(r"[A-Za-z0-9+.\-]+")
_SINGLE_DOT = frozenset((".", "%2e"))
_DOUBLE_DOT = frozenset(("..", ".%2e", "%2e.", "%2e%2e"))


class State(Enum):
    SCHEME_START = auto()
    SCHEME = auto()
    NO_SCHEME = auto()
    SPECIAL_RELATIVE_OR_AUTHORITY = auto()
    PATH_OR_AUTHORITY = auto()
    RELATIVE = auto()
    RELATIVE_SLASH = auto()
    SPECIAL_AUTHORITY_SLASHES = auto()
    SPECIAL_AUTHORITY_IGNORE_SLASHES = auto()
    AUTHORITY = auto()
    HOST = auto()
    HOSTNAME = auto()
    PORT = auto()
    FILE = auto()
    FILE_SLASH = auto()
    FILE_HOST = auto()
    PATH_START = auto()
    PATH = auto()
    OPAQUE_PATH = auto()
    QUERY = auto()
    FRAGMENT = auto()


class _Failure(Exception):
    pass


class _Url:
    """The record being built; ``path`` is a list until it is opaque."""

    __slots__ = ("fragment", "host", "password", "path", "port", "query", "scheme", "username")

    def __init__(self, record: UrlRecord) -> None:
        self.scheme = record.scheme
        self.username = record.username
        self.password = record.password
        self.host = record.host
        self.port = record.port
        self.path: str | list[str] = (
            record.path if isinstance(record.path, str) else list(record.path)
        )
        self.query = record.query
        self.fragment = record.fragment

    def freeze(self) -> UrlRecord:
        return UrlRecord(
            self.scheme,
            self.username,
            self.password,
            self.host,
            self.port,
            self.path if isinstance(self.path, str) else tuple(self.path),
            self.query,
            self.fragment,
        )

    @property
    def special(self) -> bool:
        return self.scheme in SPECIAL_PORTS

    def list_path(self) -> list[str]:
        assert isinstance(self.path, list)
        return self.path

    def shorten_path(self) -> None:
        path = self.list_path()
        if self.scheme == "file" and len(path) == 1 and _is_drive(path[0], normalized=True):
            return
        if path:
            path.pop()


def _is_drive(text: str, normalized: bool = False) -> bool:
    return len(text) == 2 and text[0] in _ALPHA and text[1] in (":" if normalized else ":|")


def _starts_with_drive(rest: str) -> bool:
    return len(rest) >= 2 and _is_drive(rest[:2]) and (len(rest) == 2 or rest[2] in "/\\?#")


def parse(text: str, base: UrlRecord | None = None) -> UrlRecord | None:
    """``text`` parsed (against ``base`` when given); ``None`` on failure."""
    text = text.strip(_STRIP)
    url = _Url(UrlRecord(""))
    try:
        _run(text, base, url, None)
    except _Failure:
        return None
    return url.freeze()


def parse_from(record: UrlRecord, text: str, state: State) -> UrlRecord:
    """``record`` with ``text`` parsed into it from ``state`` (a setter).
    As ``URL``'s setters change the URL in place, what the parser set before
    it failed stays set (``host = "example.com:65536"`` sets the host)."""
    url = _Url(record)
    with contextlib.suppress(_Failure):
        _run(text, None, url, state)
    return url.freeze()


def _run(  # noqa: PLR0911, PLR0912, PLR0915
    text: str, base: UrlRecord | None, url: _Url, override: State | None
) -> None:
    chars = _TAB_OR_NEWLINE.sub("", text)
    end = len(chars)
    state = override or State.SCHEME_START
    buffer = ""
    at_sign_seen = inside_brackets = password_token_seen = False
    pointer = 0

    def remaining_starts(prefix: str) -> bool:
        return chars.startswith(prefix, pointer + 1)

    while True:
        c = chars[pointer] if pointer < end else ""  # "" is the end of input
        match state:
            case State.SCHEME_START:
                if c != "" and c in _ALPHA:
                    buffer += c.lower()
                    state = State.SCHEME
                elif override is None:
                    state = State.NO_SCHEME
                    pointer -= 1
                else:
                    raise _Failure
            case State.SCHEME:
                if c != "" and c in _SCHEME_CHARS:
                    run = _SCHEME_RUN.match(chars, pointer)
                    assert run is not None
                    buffer += run[0].lower()
                    pointer = run.end() - 1
                elif c == ":":
                    if override is not None:
                        if url.special != (buffer in SPECIAL_PORTS):
                            return
                        if (
                            url.username != "" or url.password != "" or url.port is not None
                        ) and buffer == "file":
                            return
                        if url.scheme == "file" and url.host == "":
                            return
                    url.scheme = buffer
                    if override is not None:
                        if url.port == SPECIAL_PORTS.get(url.scheme):
                            url.port = None
                        return
                    buffer = ""
                    if url.scheme == "file":
                        state = State.FILE
                    elif url.special and base is not None and base.scheme == url.scheme:
                        state = State.SPECIAL_RELATIVE_OR_AUTHORITY
                    elif url.special:
                        state = State.SPECIAL_AUTHORITY_SLASHES
                    elif remaining_starts("/"):
                        state = State.PATH_OR_AUTHORITY
                        pointer += 1
                    else:
                        url.path = ""
                        state = State.OPAQUE_PATH
                elif override is None:
                    buffer = ""
                    state = State.NO_SCHEME
                    pointer = -1
                else:
                    raise _Failure
            case State.NO_SCHEME:
                opaque_base = base is not None and isinstance(base.path, str)
                if base is None or (opaque_base and c != "#"):
                    raise _Failure
                if opaque_base and c == "#":
                    url.scheme, url.query = base.scheme, base.query
                    url.path = base.path if isinstance(base.path, str) else list(base.path)
                    url.fragment = ""
                    state = State.FRAGMENT
                elif base.scheme != "file":
                    state = State.RELATIVE
                    pointer -= 1
                else:
                    state = State.FILE
                    pointer -= 1
            case State.SPECIAL_RELATIVE_OR_AUTHORITY:
                if c == "/" and remaining_starts("/"):
                    state = State.SPECIAL_AUTHORITY_IGNORE_SLASHES
                    pointer += 1
                else:
                    state = State.RELATIVE
                    pointer -= 1
            case State.PATH_OR_AUTHORITY:
                if c == "/":
                    state = State.AUTHORITY
                else:
                    state = State.PATH
                    pointer -= 1
            case State.RELATIVE:
                assert base is not None
                url.scheme = base.scheme
                if c == "/" or (url.special and c == "\\"):
                    state = State.RELATIVE_SLASH
                else:
                    url.username, url.password = base.username, base.password
                    url.host, url.port = base.host, base.port
                    url.path = list(base.path)
                    url.query = base.query
                    if c == "?":
                        url.query = ""
                        state = State.QUERY
                    elif c == "#":
                        url.fragment = ""
                        state = State.FRAGMENT
                    elif c != "":
                        url.query = None
                        url.shorten_path()
                        state = State.PATH
                        pointer -= 1
            case State.RELATIVE_SLASH:
                if url.special and c in ("/", "\\"):
                    state = State.SPECIAL_AUTHORITY_IGNORE_SLASHES
                elif c == "/":
                    state = State.AUTHORITY
                else:
                    assert base is not None
                    url.username, url.password = base.username, base.password
                    url.host, url.port = base.host, base.port
                    state = State.PATH
                    pointer -= 1
            case State.SPECIAL_AUTHORITY_SLASHES:
                state = State.SPECIAL_AUTHORITY_IGNORE_SLASHES
                if c == "/" and remaining_starts("/"):
                    pointer += 1
                else:
                    pointer -= 1
            case State.SPECIAL_AUTHORITY_IGNORE_SLASHES:
                if c not in ("/", "\\"):
                    state = State.AUTHORITY
                    pointer -= 1
            case State.AUTHORITY:
                if c == "@":
                    if at_sign_seen:
                        buffer = "%40" + buffer
                    at_sign_seen = True
                    for ch in buffer:
                        if ch == ":" and not password_token_seen:
                            password_token_seen = True
                            continue
                        encoded = _percent.encode(ch, _percent.USERINFO)
                        if password_token_seen:
                            url.password += encoded
                        else:
                            url.username += encoded
                    buffer = ""
                elif c in ("", "/", "?", "#") or (url.special and c == "\\"):
                    if at_sign_seen and buffer == "":
                        raise _Failure
                    pointer -= len(buffer) + 1
                    buffer = ""
                    state = State.HOST
                else:
                    run = _AUTHORITY_RUN[url.special].match(chars, pointer)
                    assert run is not None
                    buffer += run[0]
                    pointer = run.end() - 1
            case State.HOST | State.HOSTNAME:
                if override is not None and url.scheme == "file":
                    pointer -= 1
                    state = State.FILE_HOST
                elif c == ":" and not inside_brackets:
                    if buffer == "" or override is State.HOSTNAME:
                        raise _Failure
                    host = _host.parse(buffer, not url.special)
                    if host is None:
                        raise _Failure
                    url.host, buffer, state = host, "", State.PORT
                elif c in ("", "/", "?", "#") or (url.special and c == "\\"):
                    pointer -= 1
                    if url.special and buffer == "":
                        raise _Failure
                    if (
                        override is not None
                        and buffer == ""
                        and (url.username != "" or url.password != "" or url.port is not None)
                    ):
                        raise _Failure
                    host = _host.parse(buffer, not url.special)
                    if host is None:
                        raise _Failure
                    url.host, buffer, state = host, "", State.PATH_START
                    if override is not None:
                        return
                elif c in "[]":
                    inside_brackets = c == "["
                    buffer += c
                elif c == ":":  # inside brackets
                    buffer += c
                else:
                    run = _HOST_RUN[url.special].match(chars, pointer)
                    assert run is not None
                    buffer += run[0]
                    pointer = run.end() - 1
            case State.PORT:
                if c != "" and c in _DIGITS:
                    buffer += c
                elif (
                    c in ("", "/", "?", "#") or (url.special and c == "\\") or override is not None
                ):
                    if buffer != "":
                        digits = buffer.lstrip("0") or "0"
                        if len(digits) > 5 or int(digits) > 65535:
                            raise _Failure
                        port = int(digits)
                        url.port = None if port == SPECIAL_PORTS.get(url.scheme) else port
                        buffer = ""
                        if override is not None:
                            return
                    if override is not None:
                        raise _Failure
                    state = State.PATH_START
                    pointer -= 1
                else:
                    raise _Failure
            case State.FILE:
                url.scheme = "file"
                url.host = ""
                if c in ("/", "\\"):
                    state = State.FILE_SLASH
                elif base is not None and base.scheme == "file":
                    url.host = base.host
                    url.path = list(base.path)
                    url.query = base.query
                    if c == "?":
                        url.query = ""
                        state = State.QUERY
                    elif c == "#":
                        url.fragment = ""
                        state = State.FRAGMENT
                    elif c != "":
                        url.query = None
                        if not _starts_with_drive(chars[pointer:]):
                            url.shorten_path()
                        else:
                            url.path = []
                        state = State.PATH
                        pointer -= 1
                else:
                    state = State.PATH
                    pointer -= 1
            case State.FILE_SLASH:
                if c in ("/", "\\"):
                    state = State.FILE_HOST
                else:
                    if base is not None and base.scheme == "file":
                        url.host = base.host
                        if (
                            not _starts_with_drive(chars[pointer:])
                            and not isinstance(base.path, str)
                            and base.path
                            and _is_drive(base.path[0], normalized=True)
                        ):
                            url.list_path().append(base.path[0])
                    state = State.PATH
                    pointer -= 1
            case State.FILE_HOST:
                if c in ("", "/", "\\", "?", "#"):
                    pointer -= 1
                    if override is None and _is_drive(buffer):
                        state = State.PATH
                    elif buffer == "":
                        url.host = ""
                        if override is not None:
                            return
                        state = State.PATH_START
                    else:
                        host = _host.parse(buffer, not url.special)
                        if host is None:
                            raise _Failure
                        url.host = "" if host == "localhost" else host
                        if override is not None:
                            return
                        buffer = ""
                        state = State.PATH_START
                else:
                    buffer += c
            case State.PATH_START:
                if url.special:
                    state = State.PATH
                    if c not in ("/", "\\"):
                        pointer -= 1
                elif override is None and c == "?":
                    url.query = ""
                    state = State.QUERY
                elif override is None and c == "#":
                    url.fragment = ""
                    state = State.FRAGMENT
                elif c != "":
                    state = State.PATH
                    if c != "/":
                        pointer -= 1
                elif override is not None and url.host is None:
                    url.list_path().append("")
            case State.PATH:
                slash = c == "/" or (url.special and c == "\\")
                if c == "" or slash or (override is None and c in ("?", "#")):
                    lower = buffer.lower()
                    path = url.list_path()
                    if lower in _DOUBLE_DOT:
                        url.shorten_path()
                        if not slash:
                            path.append("")
                    elif lower in _SINGLE_DOT:
                        if not slash:
                            path.append("")
                    else:
                        if url.scheme == "file" and not path and _is_drive(buffer):
                            buffer = buffer[0] + ":"
                        path.append(buffer)
                    buffer = ""
                    if c == "?":
                        url.query = ""
                        state = State.QUERY
                    elif c == "#":
                        url.fragment = ""
                        state = State.FRAGMENT
                else:
                    run = _PATH_RUN[url.special, override is not None].match(chars, pointer)
                    assert run is not None
                    buffer += _percent.encode(run[0], _percent.PATH)
                    pointer = run.end() - 1
            case State.OPAQUE_PATH:
                assert isinstance(url.path, str)
                if c == "?":
                    url.query = ""
                    state = State.QUERY
                elif c == "#":
                    url.fragment = ""
                    state = State.FRAGMENT
                elif c == " ":
                    after = chars[pointer + 1 : pointer + 2]
                    url.path += "%20" if after in ("?", "#") else " "
                elif c != "":
                    run = _OPAQUE_PATH_RUN.match(chars, pointer)
                    assert run is not None
                    url.path += _percent.encode(run[0], _percent.C0_CONTROL)
                    pointer = run.end() - 1
            case State.QUERY:
                if (override is None and c == "#") or c == "":
                    encode_set = _percent.SPECIAL_QUERY if url.special else _percent.QUERY
                    url.query = (url.query or "") + _percent.encode(buffer, encode_set)
                    buffer = ""
                    if c == "#":
                        url.fragment = ""
                        state = State.FRAGMENT
                else:
                    stop = chars.find("#", pointer) if override is None else -1
                    stop = end if stop == -1 else stop
                    buffer += chars[pointer:stop]
                    pointer = stop - 1
            case State.FRAGMENT:
                if c != "":
                    rest = _percent.encode(chars[pointer:], _percent.FRAGMENT)
                    url.fragment = (url.fragment or "") + rest
                    pointer = end - 1
        if pointer >= end:
            return
        pointer += 1
