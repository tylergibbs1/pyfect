"""The strict JSON5 and JSONC parser behind ``json5`` and ``jsonc`` (Effect's
``internal/jsonParser``).

Iterative, so nesting deeper than the call stack still parses. Errors are
``ValueError("Invalid JSON5 at line L, column C")`` with the column counted in
UTF-16 code units, as Effect reports it, and never quote the input.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Literal, Never

from pyfect._js import SPACE, js_length

type Format = Literal["JSON5", "JSONC"]

_JSON5_LINES = re.compile("\r\n|[\n\r\u2028\u2029]")
_JSONC_LINES = re.compile("\r\n|[\n\r]")
_JSON5_SPACE = re.compile(f"(?:[{SPACE}]|//[^\n\r\u2028\u2029]*|/\\*.*?\\*/)*", re.DOTALL)
_JSONC_SPACE = re.compile(r"(?:[ \t\r\n]|//[^\r\n]*|/\*.*?\*/)*", re.DOTALL)
_JSON_NUMBER = re.compile(r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?")
_HEX_DIGITS = re.compile(r"[0-9a-fA-F]*")
_JSON5_DOUBLE = re.compile(r'[^"\\\n\r]*')
_JSON5_SINGLE = re.compile(r"[^'\\\n\r]*")
_JSON_DOUBLE = re.compile(r'[^"\\\x00-\x1f]*')

_ESCAPES = {'"': '"', "\\": "\\", "/": "/", "b": "\b", "f": "\f", "n": "\n", "r": "\r", "t": "\t"}

_ID_START_CATEGORIES = frozenset({"Lu", "Ll", "Lt", "Lm", "Lo", "Nl"})
_ID_PART_CATEGORIES = _ID_START_CATEGORIES | {"Mn", "Mc", "Nd", "Pc"}
_OTHER_ID_START = frozenset("\u1885\u1886\u2118\u212e\u309b\u309c")
_OTHER_ID_CONTINUE = frozenset(
    "\u00b7\u0387\u1369\u136a\u136b\u136c\u136d\u136e\u136f\u1370\u1371\u19da\u30fb\uff65"
)
# Pattern_Syntax characters whose general category would otherwise admit them.
_PATTERN_SYNTAX = frozenset("\u2e2f")


def _is_id_start(character: str) -> bool:
    """``/[$_\\p{ID_Start}]/u``."""
    if character in "$_":
        return character != ""
    if character in _PATTERN_SYNTAX:
        return False
    return unicodedata.category(character) in _ID_START_CATEGORIES or character in _OTHER_ID_START


def _is_id_part(character: str) -> bool:
    """``/[$\\u200C\\u200D\\p{ID_Continue}]/u``."""
    if character in "$\u200c\u200d":
        return character != ""
    if character in _PATTERN_SYNTAX:
        return False
    return (
        unicodedata.category(character) in _ID_PART_CATEGORIES
        or character in _OTHER_ID_START
        or character in _OTHER_ID_CONTINUE
    )


_DIGITS = frozenset("0123456789")
_ASCII_ID_PART = frozenset("$_0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ")


def _is_ascii_id_part(character: str) -> bool:
    return character in _ASCII_ID_PART


def syntax_error(text: str, at: int, format: Format) -> ValueError:
    """The error at code point ``at``, its column in UTF-16 code units."""
    lines = (_JSON5_LINES if format == "JSON5" else _JSONC_LINES).split(text[:at])
    return ValueError(f"Invalid {format} at line {len(lines)}, column {js_length(lines[-1]) + 1}")


def _well_formed_pairs(text: str) -> str:
    """Joins the surrogate pairs ``\\uXXXX`` escapes produced, as a
    JavaScript string would read them; lone surrogates stay."""
    if not any("\ud800" <= character <= "\udfff" for character in text):
        return text
    return text.encode("utf-16-le", "surrogatepass").decode("utf-16-le", "surrogatepass")


_INT_DIGITS = 4000
"""Past this many digits ``int`` refuses the text; JavaScript's ``Number``
reads it anyway, as a float."""


def _number_value(token: str) -> int | float:
    """``Number(token)`` as pyfect's JSON reads numbers: a token without a
    fraction or exponent is an ``int``."""
    if token[:2] in ("0x", "0X"):
        return int(token, 16)
    if "." in token or "e" in token or "E" in token or len(token) > _INT_DIGITS:
        return float(token)
    return int(token)


class _Frame:
    __slots__ = ("first", "key", "value")

    def __init__(self, value: dict[str, object] | list[object]) -> None:
        self.value = value
        self.key = ""
        self.first = True


class _Parser:
    """One parse of ``text``; ``index`` is a code point offset."""

    def __init__(self, text: str, format: Format) -> None:
        self.text = text
        self.format: Format = format
        self.json5 = format == "JSON5"
        self.space = _JSON5_SPACE if self.json5 else _JSONC_SPACE
        self.i = 0
        self.stack: list[_Frame] = []

    def char(self, at: int) -> str:
        return self.text[at] if at < len(self.text) else ""

    def fail(self, at: int) -> Never:
        raise syntax_error(self.text, at, self.format)

    def skip(self) -> None:
        """Skips whitespace and comments, rejecting a ``/`` that starts neither."""
        self.i = self.space.match(self.text, self.i).end()  # pyright: ignore[reportOptionalMemberAccess]
        if self.char(self.i) == "/":
            self.fail(len(self.text) if self.char(self.i + 1) == "*" else self.i + 1)

    def run(self, pattern: re.Pattern[str]) -> int:
        match = pattern.match(self.text, self.i)
        length = 0 if match is None else match.end() - self.i
        self.i += length
        return length

    def word[A](self, literal: str, result: A) -> A:
        if not self.text.startswith(literal, self.i):
            at = self.i
            while at - self.i < len(literal) and self.char(at) == literal[at - self.i]:
                at += 1
            self.fail(at)
        self.i += len(literal)
        return result

    def hex(self, count: int) -> str:
        value = 0
        end = self.i + count
        while self.i < end:
            character = self.char(self.i)
            if character == "" or character not in "0123456789abcdefABCDEF":
                self.fail(self.i)
            value = value * 16 + int(character, 16)
            self.i += 1
        return chr(value)

    def number(self) -> int | float:  # noqa: PLR0912 - one branch per token form, as Effect's
        text = self.text
        if not self.json5:
            start = self.i
            if self.run(_JSON_NUMBER) == 0:
                self.fail(self.i)
            return _number_value(text[start : self.i])
        sign = 1
        character = self.char(self.i)
        if character in ("+", "-") and character:
            sign = -1 if character == "-" else 1
            self.i += 1
            character = self.char(self.i)
        start = self.i
        if character == "I":
            return self.word("Infinity", sign * float("inf"))
        if character == "N":
            return self.word("NaN", float("nan"))
        if character == "0" and self.char(self.i + 1) in ("x", "X") and self.char(self.i + 1):
            self.i += 2
            if self.run(_HEX_DIGITS) == 0:
                self.fail(self.i)
            return sign * int(text[start + 2 : self.i], 16)
        if character == "0":
            self.i += 1
        elif character in _DIGITS:
            while self.char(self.i) in _DIGITS:
                self.i += 1
        elif character != ".":
            self.fail(self.i)
        character = self.char(self.i)
        if character == ".":
            self.i += 1
            fraction = self.i
            while self.char(self.i) in _DIGITS:
                self.i += 1
            # A leading decimal point needs digits after it; a trailing one does not.
            if self.i == fraction and fraction == start + 1:
                self.fail(self.i)
            character = self.char(self.i)
        if character in ("e", "E") and character:
            self.i += 1
            if self.char(self.i) in ("+", "-") and self.char(self.i):
                self.i += 1
            exponent = self.i
            while self.char(self.i) in _DIGITS:
                self.i += 1
            if self.i == exponent:
                self.fail(self.i)
        value = _number_value(text[start : self.i])
        return sign * value

    def string(self, quote: str) -> str:  # noqa: PLR0912 - one branch per token form, as Effect's
        json5 = self.json5
        plain = _JSON5_SINGLE if quote == "'" else _JSON5_DOUBLE if json5 else _JSON_DOUBLE
        text = self.text
        parts: list[str] = []
        self.i += 1
        while True:
            start = self.i
            self.run(plain)
            parts.append(text[start : self.i])
            character = self.char(self.i)
            self.i += 1
            if character == quote:
                return _well_formed_pairs("".join(parts))
            # Anything else that stops a plain run is an escape or a forbidden character.
            if character != "\\":
                self.fail(self.i - 1)
            escape = self.char(self.i)
            self.i += 1
            simple = _ESCAPES.get(escape) if escape else None
            if simple is not None:
                parts.append(simple)
            elif escape == "u":
                parts.append(self.hex(4))
            elif not json5 or self.i > len(text) or escape in "123456789":
                self.fail(self.i - 1)
            elif escape == "v":
                parts.append("\v")
            elif escape == "x":
                parts.append(self.hex(2))
            elif escape == "0":
                if self.char(self.i) in _DIGITS:
                    self.fail(self.i)
                parts.append("\0")
            elif escape == "\r":
                # A CR LF line continuation contributes nothing, like a single line terminator.
                if self.char(self.i) == "\n":
                    self.i += 1
            elif escape not in "\n\u2028\u2029":
                parts.append(escape)

    def identifier(self) -> str:  # noqa: PLR0912 - one branch per token form, as Effect's
        text = self.text
        start = self.i
        character = self.char(self.i)
        if character and _is_ascii_id_part(character) and character not in _DIGITS:
            while (character := self.char(self.i)) and _is_ascii_id_part(character):
                self.i += 1
            # Past an ASCII name, only an escape or a non-ASCII character can continue it.
            if character != "\\" and not (character and not character.isascii()):
                return text[start : self.i]
            self.i = start
        if (character := self.char(self.i)) and _is_id_start(character):
            self.i += 1
            while (character := self.char(self.i)) and _is_id_part(character):
                self.i += 1
        name = text[start : self.i]
        if name and self.char(self.i) != "\\":
            return name
        # Escapes are validated one code point at a time.
        while True:
            at = self.i
            valid = _is_id_start if name == "" else _is_id_part
            character = self.char(self.i)
            if character == "\\":
                if self.char(self.i + 1) != "u":
                    self.fail(self.i + 1)
                self.i += 2
                character = self.hex(4)
                if not valid(character):
                    self.fail(at)
            elif character and valid(character):
                self.i += 1
            elif name == "":
                self.fail(self.i)
            else:
                return name
            name += character

    def value(self) -> tuple[bool, object]:  # noqa: PLR0911 - one return per value kind
        """Reads a value at ``i``, already past any whitespace. Opening a
        collection pushes a frame and returns ``(False, None)``; the
        collection is completed later."""
        character = self.char(self.i)
        if character == "{":
            self.stack.append(_Frame({}))
            self.i += 1
            return False, None
        if character == "[":
            self.stack.append(_Frame([]))
            self.i += 1
            return False, None
        if character == '"':
            return True, self.string('"')
        if character == "'":
            return True, self.string("'") if self.json5 else self.fail(self.i)
        if character == "n":
            return True, self.word("null", None)
        if character == "t":
            return True, self.word("true", True)
        if character == "f":
            return True, self.word("false", False)
        if character and (character in "+-.IN" or character in _DIGITS):
            return True, self.number()
        return self.fail(self.i)

    def separated(self, close: str) -> None:
        """After a member: consumes a comma unless the collection ends."""
        self.skip()
        character = self.char(self.i)
        if character == close:
            return
        if character != ",":
            self.fail(self.i)
        self.i += 1
        self.skip()
        if not self.json5 and self.char(self.i) == close:
            self.fail(self.i)

    def parse(self) -> object:  # noqa: PLR0912 - one branch per token form, as Effect's
        stack = self.stack
        self.skip()
        _, result = self.value()
        # An explicit stack keeps deep nesting off the call stack.
        while stack:
            frame = stack[-1]
            value = frame.value
            close = "}" if isinstance(value, dict) else "]"
            if frame.first:
                self.skip()
            else:
                self.separated(close)
            if self.char(self.i) == close:
                stack.pop()
                self.i += 1
                if not stack:
                    result = value
                else:
                    parent = stack[-1]
                    if isinstance(parent.value, dict):
                        parent.value[parent.key] = value
                    else:
                        parent.value.append(value)
                continue
            frame.first = False
            if isinstance(value, list):
                done, item = self.value()
                if done:
                    value.append(item)
            else:
                quote = self.char(self.i)
                if not self.json5 and quote != '"':
                    self.fail(self.i)
                key = self.string(quote) if quote in ('"', "'") and quote else self.identifier()
                self.skip()
                if self.char(self.i) != ":":
                    self.fail(self.i)
                self.i += 1
                self.skip()
                done, item = self.value()
                if done:
                    value[key] = item
                else:
                    frame.key = key
        self.skip()
        if self.i < len(self.text):
            self.fail(self.i)
        return result


def parse(text: str, format: Format) -> object:
    """The value of ``text``; raises ``ValueError`` where it is invalid."""
    return _Parser(text, format).parse()
