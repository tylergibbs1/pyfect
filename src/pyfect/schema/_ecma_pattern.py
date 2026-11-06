"""ECMAScript patterns in Unicode mode (the ``u`` flag), JSON Schema's regular
expressions, run on Python's ``re``.

``translate`` rewrites a pattern to one ``re`` reads the same way and rejects
what Unicode mode rejects; ``$`` ends the string, ``.`` skips the four line
terminators, ``\\d`` is ASCII and a reference to a group that took no part in the
match is empty. What ``re`` cannot match alike is refused, not approximated:
``\\p{...}``, a reference to a group opened later or still open, or to one a loop
would clear, a variable width behind and a group name used twice.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache

from pyfect._digits import is_digits
from pyfect.schema._checks_string import string_filter
from pyfect.schema.ast import Filter

_ERROR = "Cannot import pattern using ECMAScript Unicode mode."

_SYNTAX = frozenset("^$\\.*+?()[]{}|/")
_NOT_LINE_TERMINATOR = "[^\\n\\r\\u2028\\u2029]"
_SPACE = (
    "\\t\\n\\x0b\\x0c\\r \\u00a0\\u1680\\u2000-\\u200a\\u2028\\u2029\\u202f\\u205f\\u3000\\ufeff"
)
_NOT_SPACE = (
    "\\x00-\\x08\\x0e-\\x1f\\x21-\\x9f\\xa1-\\u167f\\u1681-\\u1fff\\u200b-\\u2027\\u202a-\\u202e"
    "\\u2030-\\u205e\\u2060-\\u2fff\\u3001-\\ufefe\\uff00-\\U0010ffff"
)
_QUANTIFIER = re.compile(r"\{[0-9]+(?:,[0-9]*)?\}")
_SIMPLE_ESCAPES = {"t": r"\t", "n": r"\n", "v": r"\x0b", "f": r"\x0c", "r": r"\r"}


class EcmaPatternError(ValueError):
    """A pattern that is not valid in Unicode mode, or that ``re`` cannot run."""


def _is_hex(text: str) -> bool:
    return len(text) > 0 and all(c in "0123456789abcdefABCDEF" for c in text)


@dataclass(slots=True)
class _Group:
    is_assertion: bool = False
    number: int | None = None
    captures_inside: set[int] = field(default_factory=set[int])


def _repeats(quantifier: str) -> bool:
    """Whether ``quantifier`` (from its first character) may take a second turn."""
    if quantifier in {"*", "+", "?"}:
        return quantifier != "?"
    bounds = quantifier.strip("{}").split(",")
    return bounds[-1] == "" or int(bounds[-1]) > 1


class _Translation:
    def __init__(self, source: str) -> None:
        self.source = source
        self.at = 0
        self.out: list[str] = []
        self.groups: list[_Group] = []
        self.capture_count = 0
        self.names: dict[str, int] = {}
        self.referenced: set[int] = set()
        self.cleared_by_a_loop: set[int] = set()

    def group_name(self, start: int) -> str:
        """The name from ``start`` up to its ``>``, moving past it."""
        end = self.source.find(">", start)
        name = self.source[start:end] if end >= 0 else ""
        # ``$`` is the one identifier character of JavaScript's that Python's lacks.
        if not name.replace("$", "_").isidentifier():
            raise EcmaPatternError(_ERROR)
        self.at = end + 1
        return name

    def quantifier(self) -> str | None:
        """The quantifier at ``at``, if any, without moving."""
        if self.peek() in {"*", "+", "?"}:
            return self.peek()
        found = _QUANTIFIER.match(self.source, self.at)
        return None if found is None else found.group()

    def reference(self, number: int) -> str:
        """A group that took no part in the match is empty in JavaScript and
        fails in ``re``. A number past the groups so far does not compile."""
        self.referenced.add(number)
        return f"(?({number})\\{number})"

    def peek(self, offset: int = 0) -> str:
        index = self.at + offset
        return self.source[index] if index < len(self.source) else ""

    def literal(self, code_point: int) -> str:
        return re.escape(chr(code_point))

    def run(self) -> str:
        while self.at < len(self.source):
            self.atom()
        if self.groups or self.referenced & self.cleared_by_a_loop:
            raise EcmaPatternError(_ERROR)
        return "".join(self.out)

    def atom(self) -> None:
        char = self.peek()
        match char:
            case "\\":
                self.at += 1
                self.out.append(self.escape(in_class=False))
            case ".":
                self.at += 1
                self.out.append(_NOT_LINE_TERMINATOR)
            case "$":
                self.at += 1
                self.out.append(r"\Z")
            case "(":
                self.group()
            case ")":
                self.close_group()
            case "[":
                self.character_class()
            case "*" | "+" | "?":
                self.at += 1
                self.out.append(char)
                self.after_quantifier()
            case "{":
                quantifier = _QUANTIFIER.match(self.source, self.at)
                if quantifier is None:
                    raise EcmaPatternError(_ERROR)
                self.at = quantifier.end()
                self.out.append(quantifier.group())
                self.after_quantifier()
            case "}" | "]":
                raise EcmaPatternError(_ERROR)
            case _:
                self.at += 1
                self.out.append(char)

    def after_quantifier(self) -> None:
        """A lazy ``?`` may follow; ``re``'s possessive ``a*+`` is not ECMAScript."""
        if self.peek() == "?":
            self.at += 1
            self.out.append("?")
        if self.quantifier() is not None:
            raise EcmaPatternError(_ERROR)

    def open_capture(self) -> int:
        self.capture_count += 1
        self.groups.append(_Group(number=self.capture_count))
        return self.capture_count

    def group(self) -> None:
        rest = self.source[self.at :]
        for opening in ("(?:", "(?=", "(?!", "(?<=", "(?<!"):
            if rest.startswith(opening):
                self.at += len(opening)
                self.out.append(opening)
                self.groups.append(_Group(is_assertion=opening != "(?:"))
                return
        if rest.startswith("(?<"):
            name = self.group_name(self.at + 3)
            if name in self.names:
                raise EcmaPatternError(_ERROR)
            self.names[name] = self.open_capture()
            self.out.append(f"(?P<{name}>" if name.isidentifier() else "(")
            return
        if rest.startswith("(?"):
            raise EcmaPatternError(_ERROR)
        self.at += 1
        self.open_capture()
        self.out.append("(")

    def close_group(self) -> None:
        if not self.groups:
            raise EcmaPatternError(_ERROR)
        group = self.groups.pop()
        self.at += 1
        self.out.append(")")
        if self.groups:
            own = () if group.number is None else (group.number,)
            self.groups[-1].captures_inside.update(group.captures_inside, own)
        quantifier = self.quantifier()
        if quantifier is None:
            return
        if group.is_assertion:
            raise EcmaPatternError(_ERROR)
        if _repeats(quantifier):
            self.cleared_by_a_loop |= group.captures_inside

    def code_point_escape(self) -> int:
        """The code point of ``\\uXXXX`` or ``\\u{X...}``, at the ``u``; a
        surrogate pair of escapes is one code point."""
        self.at += 1
        if self.peek() == "{":
            end = self.source.find("}", self.at)
            digits = self.source[self.at + 1 : end] if end > 0 else ""
            if not _is_hex(digits) or int(digits, 16) > 0x10FFFF:
                raise EcmaPatternError(_ERROR)
            self.at = end + 1
            return int(digits, 16)
        digits = self.source[self.at : self.at + 4]
        if len(digits) != 4 or not _is_hex(digits):
            raise EcmaPatternError(_ERROR)
        self.at += 4
        high = int(digits, 16)
        low_digits = self.source[self.at + 2 : self.at + 6]
        if (
            0xD800 <= high <= 0xDBFF
            and self.source.startswith("\\u", self.at)
            and len(low_digits) == 4
            and _is_hex(low_digits)
            and 0xDC00 <= int(low_digits, 16) <= 0xDFFF
        ):
            self.at += 6
            return 0x10000 + ((high - 0xD800) << 10) + (int(low_digits, 16) - 0xDC00)
        return high

    def escape(self, *, in_class: bool) -> str:  # noqa: PLR0911, PLR0912
        """The translation of the escape after a backslash at ``at``."""
        char = self.peek()
        if char == "":
            raise EcmaPatternError(_ERROR)
        if char == "u":
            return self.literal(self.code_point_escape())
        self.at += 1
        match char:
            case "d" | "D" | "w" | "W":
                return f"\\{char}"
            case "s":
                return _SPACE if in_class else f"[{_SPACE}]"
            case "S":
                return _NOT_SPACE if in_class else f"[{_NOT_SPACE}]"
            case "b":
                return r"\x08" if in_class else r"\b"
            case "B":
                if in_class:
                    raise EcmaPatternError(_ERROR)
                return r"\B"
            case "t" | "n" | "v" | "f" | "r":
                return _SIMPLE_ESCAPES[char]
            case "0":
                if is_digits(self.peek()):
                    raise EcmaPatternError(_ERROR)
                return r"\x00"
            case "c":
                letter = self.peek()
                if not (letter.isascii() and letter.isalpha()):
                    raise EcmaPatternError(_ERROR)
                self.at += 1
                return self.literal(ord(letter) % 32)
            case "x":
                digits = self.source[self.at : self.at + 2]
                if len(digits) != 2 or not _is_hex(digits):
                    raise EcmaPatternError(_ERROR)
                self.at += 2
                return self.literal(int(digits, 16))
            case "k" if not in_class:
                if self.peek() != "<":
                    raise EcmaPatternError(_ERROR)
                number = self.names.get(self.group_name(self.at + 1))
                if number is None:
                    raise EcmaPatternError(_ERROR)
                return self.reference(number)
            case _ if is_digits(char) and not in_class:
                digits = char
                while is_digits(self.peek()):
                    digits += self.peek()
                    self.at += 1
                return self.reference(int(digits))
            case "-" if in_class:
                return r"\-"
            case _ if char in _SYNTAX:
                return f"\\{char}"
            case _:
                raise EcmaPatternError(_ERROR)

    def character_class(self) -> None:
        self.at += 1
        negated = self.peek() == "^"
        if negated:
            self.at += 1
        if self.peek() == "]":
            self.at += 1
            self.out.append(r"(?s:.)" if negated else r"(?!)")
            return
        parts = ["[^" if negated else "["]
        while self.peek() != "]":
            start, start_is_set = self.class_atom()
            parts.append(start)
            if self.peek() == "-" and self.peek(1) not in {"", "]"}:
                self.at += 1
                end, end_is_set = self.class_atom()
                if start_is_set or end_is_set:
                    raise EcmaPatternError(_ERROR)
                parts.append(f"-{end}")
        self.at += 1
        parts.append("]")
        self.out.append("".join(parts))

    def class_atom(self) -> tuple[str, bool]:
        """The translation of a class member at ``at``, and whether it is a set
        (``\\d``), which a range may not end at."""
        char = self.peek()
        if char == "":
            raise EcmaPatternError(_ERROR)
        self.at += 1
        if char == "\\":
            is_set = self.peek() in {"d", "D", "w", "W", "s", "S"}
            return self.escape(in_class=True), is_set
        # ``re`` warns of future set syntax on these, and they are literals here.
        return (f"\\{char}" if char in "[&~|-" else char), False


def translate(source: str) -> str:
    """``source`` as a ``re`` pattern for ``re.ASCII``; raises
    ``EcmaPatternError`` for what is not valid in Unicode mode."""
    return _Translation(source).run()


@lru_cache(maxsize=256)
def compile_ecma(source: str) -> re.Pattern[str]:
    """``source`` compiled; raises ``EcmaPatternError``."""
    try:
        return re.compile(translate(source), re.ASCII)
    except re.error as error:
        raise EcmaPatternError(_ERROR) from error


_TERMINATORS = {"\n": "n", "\r": "r", "\u2028": "u2028", "\u2029": "u2029"}


def canonical_source(source: str) -> str:
    """``source`` as JavaScript's ``RegExp.source`` spells it: ``/`` and line
    terminators escaped, ``(?:)`` for the empty pattern."""
    if not source:
        return "(?:)"
    out: list[str] = []
    after_backslash = False
    in_class = False
    for char in source:
        terminator = _TERMINATORS.get(char)
        if terminator is not None:
            out.append(terminator if after_backslash else f"\\{terminator}")
            after_backslash = False
            continue
        if not after_backslash:
            in_class = (char == "[") or (in_class and char != "]")
            if char == "/" and not in_class:
                out.append("\\")
        out.append(char)
        after_backslash = char == "\\" and not after_backslash
    return "".join(out)


def is_ecma_pattern(source: str, /, **annotations: object) -> Filter[str]:
    """A string the ECMAScript pattern ``source`` finds a match in, read in
    Unicode mode (``/source/u``). JSON Schema's ``pattern`` holds these, and
    this check writes one back. Unlike ``is_pattern``, it behaves as Effect's
    ``isPattern(new RegExp(source, "u"))``. Raises ``EcmaPatternError`` for a
    pattern that does not compile."""
    regex = compile_ecma(source)
    canonical = canonical_source(source)
    return string_filter(
        lambda s: regex.search(s) is not None,
        f"a string matching the RegExp {canonical}",
        "isPattern",
        {"source": canonical, "flags": "u"},
        annotations,
    )
