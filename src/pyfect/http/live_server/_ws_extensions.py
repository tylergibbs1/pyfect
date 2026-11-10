"""``ws``'s ``Sec-WebSocket-Extensions`` parser (``extension.parse``, ws 8): each
extension's offers, each a map of its parameters' values, ``True`` for a bare parameter."""

from __future__ import annotations

import re
from typing import Literal

type Value = str | Literal[True]
type Params = dict[str, list[Value]]
type Offers = dict[str, list[Params]]

_TCHAR = re.compile(r"[!#$%&'*+\-.^_`|~0-9A-Za-z]")


def _is_tchar(char: str) -> bool:
    return _TCHAR.fullmatch(char) is not None


def _unexpected(index: int) -> ValueError:
    return ValueError(f"Unexpected character at index {index}")


class _Parser:
    """One pass over the header: the extension name, then its parameter names, then a
    parameter's value, each read token by token as ``ws`` reads them."""

    def __init__(self, header: str) -> None:
        self.header = header
        self.offers: Offers = {}
        self.params: Params = {}
        self.extension: str | None = None
        self.param: str | None = None
        self.start = self.end = -1
        self.must_unescape = self.escaping = self.in_quotes = False

    def _token(self, index: int, char: str) -> bool:
        """Extend the current token by ``char``, or mark where it ended; ``False`` when
        ``char`` is neither part of a token nor the blank after one."""
        if self.end == -1 and _is_tchar(char):
            if self.start == -1:
                self.start = index
            return True
        if char in " \t" and (self.extension is not None or index != 0):
            if self.end == -1 and self.start != -1:
                self.end = index
            return True
        return False

    def _close_token(self, index: int) -> str:
        if self.start == -1:
            raise _unexpected(index)
        if self.end == -1:
            self.end = index
        token = self.header[self.start : self.end]
        self.start = self.end = -1
        return token

    def _end_offer(self, name: str) -> None:
        self.offers.setdefault(name, []).append(self.params)
        self.params = {}
        self.extension = None

    def extension_char(self, index: int, char: str) -> None:
        if self._token(index, char):
            return
        if char not in ";,":
            raise _unexpected(index)
        name = self._close_token(index)
        if char == ",":
            self._end_offer(name)
        else:
            self.extension = name

    def param_char(self, index: int, char: str, extension: str) -> None:
        if self._token(index, char):
            return
        if char in ";,":
            self.params.setdefault(self._close_token(index), []).append(True)
            if char == ",":
                self._end_offer(extension)
        elif char == "=" and self.start != -1 and self.end == -1:
            self.param = self.header[self.start : index]
            self.start = self.end = -1
        else:
            raise _unexpected(index)

    def quoted_char(self, index: int, char: str) -> None:
        if self.escaping:
            # A quoted-string must unescape to a token (RFC 6455 §9.1).
            if not _is_tchar(char):
                raise _unexpected(index)
            if self.start == -1:
                self.start = index
            else:
                self.must_unescape = True
            self.escaping = False
        elif _is_tchar(char):
            if self.start == -1:
                self.start = index
        elif char == '"' and self.start != -1:
            self.in_quotes = False
            self.end = index
        elif char == "\\":
            self.escaping = True
        else:
            raise _unexpected(index)

    def value_char(self, index: int, char: str, extension: str, param: str) -> None:
        if self.escaping or self.in_quotes:
            self.quoted_char(index, char)
        elif char == '"' and index > 0 and self.header[index - 1] == "=":
            self.in_quotes = True
        elif self.end == -1 and _is_tchar(char):
            if self.start == -1:
                self.start = index
        elif self.start != -1 and char in " \t":
            if self.end == -1:
                self.end = index
        elif char in ";,":
            self.params.setdefault(param, []).append(self._value(self._close_token(index)))
            self.param = None
            if char == ",":
                self._end_offer(extension)
        else:
            raise _unexpected(index)

    def _value(self, token: str) -> str:
        if self.must_unescape:
            self.must_unescape = False
            return token.replace("\\", "")
        return token

    def finish(self, last: str) -> Offers:
        if self.start == -1 or self.in_quotes or last in (" ", "\t"):
            raise ValueError("Unexpected end of input")
        if self.end == -1:
            self.end = len(self.header)
        token = self.header[self.start : self.end]
        if self.extension is None:
            self.offers.setdefault(token, []).append(self.params)
            return self.offers
        if self.param is None:
            self.params.setdefault(token, []).append(True)
        else:
            self.params.setdefault(self.param, []).append(self._value(token))
        self.offers.setdefault(self.extension, []).append(self.params)
        return self.offers


def parse_extensions(header: str) -> Offers:
    """The offers of a ``Sec-WebSocket-Extensions`` header; ``ValueError`` for a
    malformed one."""
    parser = _Parser(header)
    for index, char in enumerate(header):
        extension, param = parser.extension, parser.param
        if extension is None:
            parser.extension_char(index, char)
        elif param is None:
            parser.param_char(index, char, extension)
        else:
            parser.value_char(index, char, extension, param)
    return parser.finish(header[-1:])
