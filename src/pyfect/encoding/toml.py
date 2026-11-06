"""TOML text to nested dicts (Effect's ``encoding/Toml``, based on the ``toml``
4.1.2 package), which is laxer than ``tomllib``: a dotted key's table can be
declared afterwards, and a date is a space away from its time.

A date-time with an offset is a ``datetime`` in UTC (Effect's ``Date``, within the
years ``datetime`` holds); a local date, date-time or time stays text. Invalid text
raises ``ValueError`` with Effect's message, its position counted in UTF-16 code
units."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any, Never, cast

from pyfect import _js_date as js_date
from pyfect._js import SPACE

type _Table = dict[str, Any]

_ESCAPES = {"b": "\b", "t": "\t", "n": "\n", "f": "\f", "r": "\r", '"': '"', "\\": "\\"}
_DATE = r"\d{4}-\d{2}-\d{2}"
_TIME = r"\d{2}:\d{2}:\d{2}(?:\.\d+)?"
_SPACED_DATE_TIME = re.compile(f"({_DATE}) ({_TIME}(?:[Zz]|[+-]\\d{{2}}:\\d{{2}})?)", re.ASCII)
_OFFSET_DATE_TIME = re.compile(f"{_DATE}[Tt]{_TIME}(?:[Zz]|[+-]\\d{{2}}:\\d{{2}})", re.ASCII)
_LOCAL_DATE_TIME = re.compile(f"{_DATE}[Tt]{_TIME}|{_DATE}|{_TIME}", re.ASCII)
_RADIX = (
    (re.compile(r"0x[0-9A-Fa-f](?:_?[0-9A-Fa-f])*"), 16),
    (re.compile(r"0o[0-7](?:_?[0-7])*"), 8),
    (re.compile(r"0b[01](?:_?[01])*"), 2),
)
_INTEGER = re.compile(r"[+-]?(?:0|[1-9](?:_?\d)*)", re.ASCII)
_FLOAT = re.compile(
    r"[+-]?(?:(?:0|[1-9](?:_?\d)*)\.\d(?:_?\d)*(?:[eE][+-]?\d(?:_?\d)*)?"
    r"|(?:0|[1-9](?:_?\d)*)[eE][+-]?\d(?:_?\d)*)",
    re.ASCII,
)
_NON_FINITE = re.compile(r"[+-]?(?:inf|nan)")
_BARE_KEY = re.compile(r"[A-Za-z0-9_-]*")
_TOKEN = re.compile(f"[^{SPACE},#\\]}}]*")


def _number(token: str) -> int | float | None:
    normalized = token.replace("_", "")
    if _NON_FINITE.fullmatch(token):
        return float(normalized)
    for pattern, radix in _RADIX:
        if pattern.fullmatch(token):
            return int(normalized[2:], radix)
    if _INTEGER.fullmatch(token):
        return int(normalized)
    return float(normalized) if _FLOAT.fullmatch(token) else None


class _Parser:
    __slots__ = ("_column", "_current", "_explicit", "_index", "_input", "_line", "root")

    def __init__(self, text: str) -> None:
        self.root: _Table = {}
        self._input = text
        self._current = self.root
        self._index = 0
        self._line = 1
        self._column = 1
        self._explicit: set[int] = set()

    def parse(self) -> _Table:
        while True:
            self._skip_document_whitespace()
            if self._done:
                return self.root
            if self._peek() == "[":
                self._header()
            else:
                keys = self._key_path("=")
                self._skip_inline_whitespace()
                self._expect("=")
                self._skip_inline_whitespace()
                self._assign(self._current, keys, self._value())
                self._finish_statement()

    def _header(self) -> None:
        self._expect("[")
        array = self._peek() == "["
        if array:
            self._advance()
        self._skip_inline_whitespace()
        path = self._key_path("]")
        self._skip_inline_whitespace()
        self._expect("]")
        if array:
            self._expect("]")
        self._finish_statement()
        table = self._resolve_table(path, array)
        if not array:
            if id(table) in self._explicit:
                self._fail(f"Cannot redefine table '{'.'.join(path)}'")
            self._explicit.add(id(table))
        self._current = table

    def _resolve_table(self, path: list[str], array: bool) -> _Table:
        table = self.root
        for index, key in enumerate(path):
            value = table.get(key)
            redefined = f"Cannot redefine existing key '{'.'.join(path[: index + 1])}'"
            if index == len(path) - 1 and array:
                if value is None:
                    value = table[key] = []
                if not isinstance(value, list):
                    self._fail(redefined)
                following: _Table = {}
                cast("list[object]", value).append(following)
                return following
            if value is None:
                value = table[key] = {}
            if isinstance(value, list):
                entries = cast("list[object]", value)
                value = entries[-1] if entries else None
            if not isinstance(value, dict):
                self._fail(redefined)
            table = cast("_Table", value)
        return table

    def _assign(self, target: _Table, keys: list[str], value: object) -> None:
        table = target
        for index, key in enumerate(keys[:-1]):
            existing = table.get(key)
            if existing is None:
                existing = table[key] = {}
            if not isinstance(existing, dict):
                self._fail(f"Cannot redefine existing key '{'.'.join(keys[: index + 1])}'")
            table = cast("_Table", existing)
        if keys[-1] in table:
            self._fail(f"Cannot redefine existing key '{'.'.join(keys)}'")
        table[keys[-1]] = value

    def _key_path(self, stop: str) -> list[str]:
        keys: list[str] = []
        while True:
            self._skip_inline_whitespace()
            character = self._peek()
            if character == '"':
                keys.append(self._basic_string(multiline=False))
            elif character == "'":
                keys.append(self._literal_string(multiline=False))
            else:
                found = _BARE_KEY.match(self._input, self._index)
                key = found.group(0) if found else ""
                if not key:
                    self._fail("Expected a key")
                self._advance(len(key))
                keys.append(key)
            self._skip_inline_whitespace()
            if self._peek() == ".":
                self._advance()
                continue
            if self._peek() != stop:
                self._fail(f"Expected '{stop}'")
            return keys

    def _value(self) -> object:
        character = self._peek()
        if character == '"':
            return self._basic_string(multiline=self._input.startswith('"""', self._index))
        if character == "'":
            return self._literal_string(multiline=self._input.startswith("'''", self._index))
        if character == "[":
            return self._array()
        if character == "{":
            return self._inline_table()
        spaced = _SPACED_DATE_TIME.match(self._input, self._index)
        if spaced is not None:
            self._advance(len(spaced.group(0)))
            return self._date(f"{spaced.group(1)}T{spaced.group(2)}")
        return self._scalar()

    def _scalar(self) -> object:
        found = _TOKEN.match(self._input, self._index)
        token = found.group(0) if found else ""
        self._advance(len(token))
        if token == "true":
            return True
        if token == "false":
            return False
        if not token:
            self._fail("Expected a value")
        date = self._date(token)
        if date is not None:
            return date
        number = _number(token)
        if number is None:
            self._fail(f"Invalid value '{token}'")
        return number

    def _date(self, token: str) -> datetime | str | None:
        if _OFFSET_DATE_TIME.fullmatch(token):
            value = js_date.parse(token)
            if value is None:
                self._fail(f"Invalid date-time '{token}'")
            return value.astimezone(UTC)
        if _LOCAL_DATE_TIME.fullmatch(token):
            return token.replace("t", "T", 1)
        return None

    def _basic_string(self, *, multiline: bool) -> str:
        self._open('"', multiline)
        output: list[str] = []
        while not self._done:
            if multiline and self._input.startswith('"""', self._index):
                self._advance(3)
                return "".join(output)
            character = self._peek()
            if not multiline and character == '"':
                self._advance()
                return "".join(output)
            if not multiline and character in ("\n", "\r"):
                self._fail("Basic strings cannot contain newlines")
            if character != "\\":
                output.append(character)
                self._advance()
                continue
            self._advance()
            if multiline and self._peek() and self._peek() in " \t\r\n":
                self._skip_continuation()
                continue
            output.append(self._escape())
        self._fail("Unterminated basic string")

    def _skip_continuation(self) -> None:
        while self._peek() in (" ", "\t"):
            self._advance()
        if self._peek() not in ("\n", "\r"):
            self._fail("Invalid multiline string continuation")
        while self._peek() and self._peek() in " \t\r\n":
            self._advance()

    def _escape(self) -> str:
        escape = self._peek()
        if escape and ord(escape) <= 0xFFFF:
            self._advance()
        else:
            # Effect steps one UTF-16 code unit, even past the end of the text.
            self._column += 1
        if escape in _ESCAPES:
            return _ESCAPES[escape]
        if escape not in ("u", "U"):
            self._fail(f"Invalid escape '\\{escape}'")
        length = 4 if escape == "u" else 8
        digits = self._input[self._index : self._index + length]
        if not re.fullmatch(f"[0-9A-Fa-f]{{{length}}}", digits):
            self._fail("Invalid unicode escape")
        code_point = int(digits, 16)
        if 0xD800 <= code_point <= 0xDFFF or code_point > 0x10FFFF:
            self._fail("Invalid unicode escape")
        self._advance(length)
        return chr(code_point)

    def _literal_string(self, *, multiline: bool) -> str:
        self._open("'", multiline)
        start = self._index
        while not self._done:
            if multiline and self._input.startswith("'''", self._index):
                output = self._input[start : self._index]
                self._advance(3)
                return output
            if not multiline and self._peek() == "'":
                output = self._input[start : self._index]
                self._advance()
                return output
            if not multiline and self._peek() in ("\n", "\r"):
                self._fail("Literal strings cannot contain newlines")
            self._advance()
        self._fail("Unterminated literal string")

    def _open(self, quote: str, multiline: bool) -> None:
        self._expect(quote)
        if multiline:
            self._expect(quote)
            self._expect(quote)
            self._advance(
                2 if self._input.startswith("\r\n", self._index) else int(self._peek() == "\n")
            )

    def _array(self) -> list[object]:
        self._expect("[")
        output: list[object] = []
        while True:
            self._skip_document_whitespace()
            if self._peek() == "]":
                self._advance()
                return output
            output.append(self._value())
            self._skip_document_whitespace()
            if self._peek() == "]":
                self._advance()
                return output
            self._expect(",")

    def _inline_table(self) -> _Table:
        self._expect("{")
        output: _Table = {}
        self._skip_inline_whitespace()
        if self._peek() == "}":
            self._advance()
            return output
        while True:
            keys = self._key_path("=")
            self._skip_inline_whitespace()
            self._expect("=")
            self._skip_inline_whitespace()
            self._assign(output, keys, self._value())
            self._skip_inline_whitespace()
            if self._peek() == "}":
                self._advance()
                return output
            self._expect(",")
            self._skip_inline_whitespace()
            if self._peek() == "}":
                self._fail("Inline tables cannot end with a trailing comma")

    def _skip_document_whitespace(self) -> None:
        while not self._done:
            if self._peek() in " \t\r\n":
                self._advance()
            elif self._peek() == "#":
                self._skip_comment()
            else:
                return

    def _skip_inline_whitespace(self) -> None:
        while self._peek() in (" ", "\t"):
            self._advance()

    def _finish_statement(self) -> None:
        self._skip_inline_whitespace()
        if self._peek() == "#":
            self._skip_comment()
        if not self._done and self._peek() not in ("\n", "\r"):
            self._fail("Expected the end of the line")

    def _skip_comment(self) -> None:
        while not self._done and self._peek() != "\n":
            self._advance()

    def _expect(self, character: str) -> None:
        if self._peek() != character:
            self._fail(f"Expected '{character}'")
        self._advance()

    def _advance(self, count: int = 1) -> None:
        for character in self._input[self._index : self._index + count]:
            if character == "\n":
                self._line += 1
                self._column = 1
            else:
                self._column += 2 if ord(character) > 0xFFFF else 1
        self._index += count

    def _peek(self) -> str:
        return self._input[self._index] if self._index < len(self._input) else ""

    @property
    def _done(self) -> bool:
        return self._index >= len(self._input)

    def _fail(self, message: str) -> Never:
        raise ValueError(f"{message} at line {self._line}, column {self._column}")


def parse(text: str, /) -> dict[str, Any]:
    """The tables, keys and values of ``text``."""
    return _Parser(text.removeprefix("﻿")).parse()


__all__ = ["parse"]
