"""YAML text to Python values (Effect's ``encoding/Yaml``, based on the
``yaml`` 2.9.0 package).

One document: block and flow collections, indentless sequence values,
multiline plain and quoted scalars, block scalars, anchors and aliases, with
the YAML 1.2 core schema (``null`` / ``~``, booleans, ints including ``0x``
and ``0o``, floats, ``.inf``, ``.nan``; dates stay strings). Unlike YAML 1.2,
a multiline flow collection's closing bracket may sit at its parent's
indentation.

Not supported, as in Effect: compact nested block sequences (``- - value``),
multiline quoted scalars in flow collections, explicit complex keys, tags and
directives, recursive aliases, and document streams. Mapping keys are
strings. Malformed or unsupported text raises ``ValueError``.
"""

from __future__ import annotations

import math
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Never

from pyfect._js import LINE_END, SPACE, js_number, trim, trim_end, trim_start

type _Record = dict[str, object]

_IS_SPACE = re.compile(f"[{SPACE}]")
_ANCHOR_NAME_END = re.compile(f"[{SPACE},\\[\\]{{}}]")
_ALIAS_END = re.compile(f"[,\\]}}{SPACE}]")
_FLOW_SCALAR_END = re.compile(r"[,\]}]")
_FLOW_KEY_END = re.compile(":")
_OPEN_BRACKET = re.compile(r"[\[{]")
_CLOSE_BRACKET = re.compile(r"[\]}]")
_FLOW_FOLD = re.compile(r"[ \t]*\n((?:[ \t]*\n)*)[ \t]*")
_TRAILING_BACKSLASHES = re.compile(r"\\*\Z")
_TRAILING_BLANKS = re.compile(r"[ \t]+\Z")
_NULL = re.compile(r"(?:null|~)", re.IGNORECASE)
_TRUE = re.compile("true", re.IGNORECASE)
_FALSE = re.compile("false", re.IGNORECASE)
_INFINITY = re.compile(r"[+-]?\.inf", re.IGNORECASE)
_NAN = re.compile(r"\.nan", re.IGNORECASE)
_HEX = re.compile(r"[+-]?0x[0-9a-f]+", re.IGNORECASE)
_OCTAL = re.compile(r"[+-]?0o[0-7]+", re.IGNORECASE)
_INT = re.compile(r"[+-]?(?:0|[1-9][0-9]*)")
_FLOAT = re.compile(
    r"[+-]?(?:(?:0|[1-9][0-9]*)?\.[0-9]+|(?:0|[1-9][0-9]*)\.?[0-9]*[eE][+-]?[0-9]+)"
)
_NODE_ANCHOR = re.compile(f"&([^{SPACE},\\[\\]{{}}]+)(?:[{SPACE}]+([^{LINE_END}]*))?")
_BLOCK_INDICATOR = re.compile(r"[|>](?:[1-9]?[+-]?|[+-]?[1-9]?)")
_COLON_SPACE = re.compile(f":(?:[{SPACE}]|\\Z)")
_DOCUMENT_MARKER = re.compile(f"(?:---|\\.\\.\\.)(?:[{SPACE}]|\\Z)")
_CONTINUATION_COMMENT = re.compile(r"(?:^|[ \t])#")
_COMMENT_AFTER_QUOTE = re.compile(r"[ \t]+#")
_NOT_SPACE = re.compile("[^ ]")
_HEX_DIGITS = {length: re.compile(f"[0-9A-Fa-f]{{{length}}}") for length in (2, 4, 8)}

_ESCAPES = {
    "0": "\0",
    "a": "\x07",
    "b": "\b",
    "t": "\t",
    "n": "\n",
    "v": "\v",
    "f": "\f",
    "r": "\r",
    "e": "\x1b",
    " ": " ",
    '"': '"',
    "/": "/",
    "\\": "\\",
    "N": "\u0085",
    "_": "\u00a0",
    "L": "\u2028",
    "P": "\u2029",
}


@dataclass(frozen=True, slots=True)
class _Line:
    raw: str
    text: str
    indent: int
    number: int
    tab_indent: bool


def _is_space(character: str) -> bool:
    return character != "" and _IS_SPACE.fullmatch(character) is not None


def _closing_quote(text: str, quote: str, start: int) -> int:
    index = start
    while index < len(text):
        character = text[index]
        if quote == '"' and character == "\\":
            index += 1
        elif character == quote:
            if quote == "'" and text[index + 1 : index + 2] == quote:
                index += 1
            else:
                return index
        index += 1
    return -1


def _find_indicator(text: str, indicator: str, depth: int = 0) -> int:  # noqa: PLR0912
    """Where ``indicator`` (``:`` or ``#``) is outside quotes and, for
    ``:``, outside flow collections; ``depth`` collections are already open."""
    token_start = True
    index = 0
    while index < len(text):
        character = text[index]
        following = text[index + 1 : index + 2]
        if token_start and character in "'\"":
            index = _closing_quote(text, character, index + 1)
            if index == -1:
                return -1
            token_start = False
        elif token_start and character == "&":
            while index + 1 < len(text) and not _ANCHOR_NAME_END.match(text[index + 1]):
                index += 1
        elif character == "#" and (index == 0 or _is_space(text[index - 1])):
            return index if indicator == "#" else -1
        elif token_start and character in "[{":
            depth += 1
        elif depth > 0 and character in "]}":
            depth -= 1
            token_start = False
        elif depth > 0 and character == ",":
            token_start = True
        elif character == ":" and (depth > 0 or following == "" or _is_space(following)):
            if depth == 0 and indicator == ":":
                return index
            token_start = True
        elif token_start and character == "-" and _is_space(following):
            pass
        elif not _is_space(character):
            token_start = False
        index += 1
    return -1


def _strip_comment(text: str, depth: int = 0) -> str:
    index = _find_indicator(text, "#", depth)
    return text if index == -1 else trim_end(text[:index])


def _mapping_separator(text: str) -> int:
    return _find_indicator(text, ":")


def _is_sequence_entry(text: str) -> bool:
    return text == "-" or text.startswith("- ")


def _fold_line_break(blank_lines: int) -> str:
    return " " if blank_lines == 0 else "\n" * blank_lines


def _fold_flow_lines(text: str) -> str:
    """Folds the line breaks of a multiline plain flow scalar."""
    return _FLOW_FOLD.sub(lambda m: _fold_line_break(m.group(1).count("\n")), text)


def _ends_with_escape(text: str) -> bool:
    match = _TRAILING_BACKSLASHES.search(text)
    return match is not None and len(match.group()) % 2 == 1


def _trim_folded_end(line: str, quote: str) -> str:
    """Escaped trailing spaces are content, not folding whitespace."""
    trailing = _TRAILING_BLANKS.search(line)
    if trailing is None:
        return line
    escaped = quote == '"' and _ends_with_escape(line[: trailing.start()])
    return line[: trailing.start() + (1 if escaped else 0)]


def _parse_double_quoted(text: str) -> str:
    if not text.endswith('"') or len(text) < 2:
        raise ValueError("Unterminated double-quoted YAML string")
    output: list[str] = []
    index = 1
    while index < len(text) - 1:
        character = text[index]
        if character != "\\":
            output.append(character)
            index += 1
            continue
        index += 1
        escape = text[index]
        if escape in _ESCAPES:
            output.append(_ESCAPES[escape])
        elif escape in "xuU":
            length = 2 if escape == "x" else 4 if escape == "u" else 8
            digits = text[index + 1 : index + 1 + length]
            if not _HEX_DIGITS[length].fullmatch(digits):
                raise ValueError("Invalid unicode escape in YAML string")
            output.append(chr(int(digits, 16)))
            index += length
        else:
            raise ValueError(f"Invalid YAML escape '\\{escape}'")
        index += 1
    return "".join(output)


def _parse_scalar(text: str) -> object:  # noqa: PLR0911 - one return per scalar kind
    value = trim(text)
    if not value:
        return None
    if value.startswith('"') and value.endswith('"'):
        return _parse_double_quoted(value)
    if value.startswith("'") and value.endswith("'"):
        return value[1:-1].replace("''", "'")
    if _NULL.fullmatch(value):
        return None
    if _TRUE.fullmatch(value):
        return True
    if _FALSE.fullmatch(value):
        return False
    if _INFINITY.fullmatch(value):
        return -math.inf if value[0] == "-" else math.inf
    if _NAN.fullmatch(value):
        return math.nan
    normalized = value.replace("_", "")
    sign = -1 if normalized.startswith("-") else 1
    if _HEX.fullmatch(normalized):
        return sign * int(normalized.lstrip("+-")[2:], 16)
    if _OCTAL.fullmatch(normalized):
        return sign * int(normalized.lstrip("+-")[2:], 8)
    if _INT.fullmatch(normalized):
        return int(normalized)
    if _FLOAT.fullmatch(normalized):
        return float(normalized)
    return value


def _key_text(value: object) -> str:
    """A parsed key as JavaScript's ``String`` writes it."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float):
        return js_number(value)
    return str(value)


def _parse_key(text: str) -> str:
    return _key_text(_parse_scalar(text))


def _fold_block(content: list[str]) -> str:
    """A folded (``>``) block scalar's lines joined: a single break becomes a
    space except around more-indented lines; blank lines are kept."""
    output = ""
    blank_lines = 0
    previous_more_indented: bool | None = None
    for line in content:
        if not line:
            blank_lines += 1
            continue
        more_indented = line.startswith((" ", "\t"))
        hard_break = more_indented or previous_more_indented is True
        if previous_more_indented is None:
            output += "\n" * blank_lines
        elif blank_lines == 0:
            output += "\n" if hard_break else " "
        else:
            output += "\n" * (blank_lines + (1 if hard_break else 0))
        output += line
        blank_lines = 0
        previous_more_indented = more_indented
    return output


class _FlowParser:
    def __init__(
        self, text: str, anchors: dict[str, object], next_line: Callable[[int], str | None]
    ) -> None:
        self._input = text
        self._anchors = anchors
        self._next_line = next_line
        self._index = 0
        self._depth = 0

    def parse(self) -> object:
        value = self._value()
        self._skip_whitespace()
        if self._index != len(self._input):
            self._fail("Unexpected flow collection content")
        return value

    def _value(self) -> object:
        self._skip_whitespace()
        character = self._peek()
        if character in ("[", "{"):
            self._depth += 1
            collection = self._sequence() if character == "[" else self._mapping()
            self._depth -= 1
            return collection
        if character in ('"', "'"):
            return _parse_scalar(self._read_quoted(character))
        if character == "*":
            self._index += 1
            name = self._read_until(_ALIAS_END)
            if name not in self._anchors:
                self._fail(f"Unknown alias '*{name}'")
            return self._anchors[name]
        if character == "&":
            self._index += 1
            name = self._read_until(_ANCHOR_NAME_END)
            if name == "" or _OPEN_BRACKET.match(self._peek()):
                self._fail("Invalid anchor")
            self._skip_whitespace()
            if self._peek() == "&":
                self._fail("Multiple anchors on one node")
            value = self._value()
            self._anchors[name] = value
            return value
        return _parse_scalar(trim(_fold_flow_lines(self._read_until(_FLOW_SCALAR_END))))

    def _close(self, bracket: str) -> bool:
        self._skip_whitespace()
        if self._peek() == bracket:
            self._index += 1
            return True
        return False

    def _sequence(self) -> list[object]:
        self._expect("[")
        output: list[object] = []
        if self._close("]"):
            return output
        while True:
            output.append(self._value())
            if self._close("]"):
                return output
            self._expect(",")
            if self._close("]"):
                return output

    def _mapping(self) -> _Record:
        self._expect("{")
        output: _Record = {}
        if self._close("}"):
            return output
        while True:
            key = self._key()
            self._skip_whitespace()
            self._expect(":")
            if key in output:
                self._fail(f"Duplicate key '{key}'")
            output[key] = self._value()
            if self._close("}"):
                return output
            self._expect(",")
            if self._close("}"):
                return output

    def _key(self) -> str:
        self._skip_whitespace()
        character = self._peek()
        if character in ('"', "'"):
            return _parse_key(self._read_quoted(character))
        return trim(_fold_flow_lines(self._read_until(_FLOW_KEY_END)))

    def _read_quoted(self, quote: str) -> str:
        start = self._index
        end = _closing_quote(self._input, quote, start + 1)
        if end == -1:
            self._fail("Unterminated quoted scalar")
        self._index = end + 1
        return self._input[start : self._index]

    def _read_until(self, stop: re.Pattern[str]) -> str:
        start = self._index
        while not stop.match(self._peek()) and self._index < len(self._input):
            self._index += 1
        return self._input[start : self._index]

    def _skip_whitespace(self) -> None:
        while _is_space(self._peek()):
            self._index += 1

    def _expect(self, character: str) -> None:
        if self._peek() != character:
            self._fail(f"Expected '{character}'")
        self._index += 1

    def _peek(self) -> str:
        # Inside a collection, the end of the line continues on the next line.
        if self._index == len(self._input) and self._depth > 0:
            line = self._next_line(self._depth)
            if line is not None:
                self._input += f"\n{line}"
        return self._input[self._index : self._index + 1]

    def _fail(self, message: str) -> Never:
        raise ValueError(f"{message} at flow offset {self._index}")


class _Parser:
    def __init__(self, lines: list[_Line]) -> None:
        self._lines = lines
        self._index = 0
        self._document_started = False
        self._anchors: dict[str, object] = {}

    def _line(self, index: int) -> _Line | None:
        return self._lines[index] if 0 <= index < len(self._lines) else None

    def parse(self) -> object:
        self._skip_ignored()
        if self._index >= len(self._lines):
            return None
        self._document_started = True
        value = self._node(self._lines[self._index].indent)
        self._skip_ignored()
        if self._index < len(self._lines):
            self._fail(self._lines[self._index], "Unexpected content")
        return value

    def _node(self, indent: int, parent_indent: int | None = None) -> object:
        parent = indent - 1 if parent_indent is None else parent_indent
        self._skip_ignored()
        line = self._line(self._index)
        if line is None:
            return None
        if line.indent != indent:
            self._fail(line, f"Expected indentation of {indent} spaces")
        if _is_sequence_entry(line.text):
            return self._sequence(indent)
        if _mapping_separator(line.text) != -1:
            return self._mapping(indent)
        self._index += 1
        return self._node_value(line.text, parent)

    def _mapping(self, indent: int, output: _Record | None = None) -> _Record:
        mapping: _Record = {} if output is None else output
        while True:
            self._skip_ignored()
            line = self._line(self._index)
            if line is None or line.indent < indent:
                return mapping
            if line.indent > indent:
                self._fail(line, f"Unexpected indentation of {line.indent} spaces")
            separator = _mapping_separator(line.text)
            if separator == -1:
                return mapping
            self._index += 1
            self._mapping_entry(mapping, line.text, separator, indent, line)

    def _mapping_entry(
        self, output: _Record, text: str, separator: int, indent: int, line: _Line
    ) -> None:
        key = _parse_key(trim(text[:separator]))
        raw_value = trim_start(text[separator + 1 :])
        value = self._node_value(raw_value, indent, allow_indentless=True)
        if key in output:
            self._fail(line, f"Duplicate key '{key}'")
        output[key] = value

    def _sequence(self, indent: int) -> list[object]:
        output: list[object] = []
        while True:
            self._skip_ignored()
            line = self._line(self._index)
            if line is None or line.indent < indent:
                return output
            if line.indent > indent:
                self._fail(line, f"Unexpected indentation of {line.indent} spaces")
            if not _is_sequence_entry(line.text):
                return output
            self._index += 1
            item = trim_start(line.text[1:])
            if _is_sequence_entry(item):
                self._fail(line, "Compact nested block sequences are not supported")
            separator = _mapping_separator(item)
            if separator == -1:
                output.append(self._node_value(item, indent))
            else:
                mapping: _Record = {}
                self._mapping_entry(mapping, item, separator, indent + 2, line)
                output.append(self._mapping(indent + 2, mapping))

    def _node_value(
        self, raw_value: str, parent_indent: int, *, allow_indentless: bool = False
    ) -> object:
        anchor = _NODE_ANCHOR.fullmatch(raw_value)
        if anchor is None:
            return self._value(raw_value, parent_indent, allow_indentless)
        value = self._value(anchor.group(2) or "", parent_indent, allow_indentless)
        self._anchors[anchor.group(1)] = value
        return value

    def _value(self, value: str, parent_indent: int, allow_indentless: bool) -> object:  # noqa: PLR0911
        text = trim_end(value)
        if not text:
            self._skip_ignored()
            following = self._line(self._index)
            if following is None:
                return None
            if following.indent > parent_indent:
                return self._node(following.indent, parent_indent)
            if (
                allow_indentless
                and following.indent == parent_indent
                and _is_sequence_entry(following.text)
            ):
                return self._sequence(parent_indent)
            return None
        if _BLOCK_INDICATOR.fullmatch(text):
            return self._block_scalar(text, parent_indent)
        # Keep escaped trailing whitespace in quoted values.
        if value.startswith(('"', "'")):
            return self._quoted_value(value, parent_indent)
        if text.startswith("*"):
            name = trim(text[1:])
            if name not in self._anchors:
                raise ValueError(f"Unknown YAML alias '*{name}'")
            return self._anchors[name]
        if text.startswith(("[", "{")):
            return self._flow_value(text, parent_indent)
        return self._plain_value(text, parent_indent)

    def _flow_value(self, text: str, parent_indent: int) -> object:
        def next_line(depth: int) -> str | None:
            following = self._line(self._index)
            if following is None or (
                following.indent == 0 and _DOCUMENT_MARKER.match(following.text)
            ):
                return None
            # Continuation lines are more indented than the parent; a closing
            # bracket may sit at its indentation.
            content = len(trim(following.text)) > 0
            if content and following.indent < parent_indent:
                return None
            if (
                content
                and following.indent == parent_indent
                and not _CLOSE_BRACKET.match(following.text)
            ):
                return None
            self._index += 1
            # Strip comments again knowing the open collections, so a quoted
            # ``#`` after a comma is kept.
            return _strip_comment(following.raw[following.indent :], depth)

        return _FlowParser(text, self._anchors, next_line).parse()

    def _plain_value(self, value: str, parent_indent: int) -> object:
        first = self._lines[self._index - 1]
        if _COLON_SPACE.search(value):
            self._fail(first, "Invalid colon in plain scalar")
        output = value
        terminated = _find_indicator(first.raw, "#") != -1
        while not terminated:
            blank_lines = self._skip_blank_lines()
            following = self._line(self._index)
            if following is None or following.indent <= parent_indent:
                break
            self._reject_tab_indent(following)
            # Quotes in plain continuations are literal.
            content = following.raw[following.indent :]
            comment = _CONTINUATION_COMMENT.search(content)
            text = trim_end(content if comment is None else content[: comment.start()])
            if not text or (following.indent == 0 and _DOCUMENT_MARKER.match(text)):
                break
            if _COLON_SPACE.search(text):
                self._fail(following, "Invalid colon in plain scalar")
            self._reject_tab_indented_blank_lines(blank_lines, parent_indent)
            output += _fold_line_break(blank_lines) + text
            self._index += 1
            terminated = comment is not None
        return _parse_scalar(output)

    def _quoted_value(self, value: str, parent_indent: int) -> object:
        quote = value[0]
        output = quote
        line = value[1:]
        while True:
            end = _closing_quote(line, quote, 0)
            if end != -1:
                rest = line[end + 1 :]
                if trim(rest) and not _COMMENT_AFTER_QUOTE.match(rest):
                    raise ValueError("Unexpected content after quoted YAML scalar")
                return _parse_scalar(output + line[: end + 1])
            if quote == '"' and _ends_with_escape(line):
                output += line[:-1]
            else:
                blank_lines = self._skip_blank_lines()
                self._reject_tab_indented_blank_lines(blank_lines, parent_indent)
                output += _trim_folded_end(line, quote) + _fold_line_break(blank_lines)
            following = self._line(self._index)
            self._index += 1
            if following is None:
                raise ValueError("Unterminated quoted YAML scalar")
            self._reject_tab_indent(following)
            if trim(following.raw) and following.indent <= parent_indent:
                self._fail(following, "Invalid quoted scalar indentation")
            line = trim_start(following.raw)

    def _block_scalar(self, indicator: str, parent_indent: int) -> str:
        style = indicator[0]
        chomp = "strip" if "-" in indicator else "keep" if "+" in indicator else "clip"
        explicit = re.sub("[^1-9]", "", indicator)
        start = self._index
        end = start
        content_indent = parent_indent + int(explicit) if explicit else None
        has_content = False

        while end < len(self._lines):
            line = self._lines[end]
            # Only spaces make a line empty; a tab after the indentation is content.
            if _NOT_SPACE.search(line.raw):
                if content_indent is None and line.indent > parent_indent:
                    # The first non-empty line sets the indentation, which no
                    # leading empty line may exceed.
                    for empty in self._lines[start:end]:
                        if empty.indent > line.indent:
                            self._fail(
                                empty,
                                "Leading empty lines cannot be more indented than the block"
                                " scalar content",
                            )
                    content_indent = line.indent
                if content_indent is not None and line.indent >= content_indent:
                    has_content = True
                else:
                    self._reject_tab_indent(line)
                    # A less indented line or comment ends the scalar.
                    if line.indent <= parent_indent or not line.text:
                        break
                    self._fail(
                        line, f"Expected block scalar indentation of {content_indent} spaces"
                    )
            end += 1

        # Whitespace past the indentation is content only once the scalar has
        # a content line.
        cut = content_indent or 0
        content = [line.raw[cut:] if has_content else "" for line in self._lines[start:end]]
        self._index = end

        content_end = len(content)
        while content_end > 0 and not content[content_end - 1]:
            content_end -= 1
        trailing_breaks = max(
            0, len(content) - content_end - (1 if end == len(self._lines) else 0)
        ) + (1 if content_end > 0 and start + content_end < len(self._lines) else 0)
        del content[content_end:]

        output = "\n".join(content) if style == "|" else _fold_block(content)
        if chomp == "keep":
            return output + "\n" * trailing_breaks
        return (
            f"{output}\n" if chomp == "clip" and content_end > 0 and trailing_breaks > 0 else output
        )

    def _reject_tab_indent(self, line: _Line) -> None:
        if line.tab_indent:
            self._fail(line, "Tabs cannot be used for YAML indentation")

    def _reject_tab_indented_blank_lines(self, count: int, parent_indent: int) -> None:
        for index in range(self._index - count, self._index):
            line = self._lines[index]
            if line.indent <= parent_indent:
                self._reject_tab_indent(line)

    def _skip_blank_lines(self) -> int:
        start = self._index
        while self._index < len(self._lines) and not trim(self._lines[self._index].raw):
            self._index += 1
        return self._index - start

    def _skip_ignored(self) -> None:
        while self._index < len(self._lines):
            line = self._lines[self._index]
            text = trim_end(line.text)
            if not text or text.startswith("%"):
                self._index += 1
            elif line.indent == 0 and text == "---":
                if self._document_started:
                    self._fail(line, "Multiple YAML documents are not supported")
                self._document_started = True
                self._index += 1
            elif line.indent == 0 and text == "...":
                self._index += 1
                while self._index < len(self._lines) and not trim_end(
                    self._lines[self._index].text
                ):
                    self._index += 1
                if self._index < len(self._lines):
                    self._fail(
                        self._lines[self._index], "Multiple YAML documents are not supported"
                    )
            else:
                self._reject_tab_indent(line)
                return

    def _fail(self, line: _Line, message: str) -> Never:
        raise ValueError(f"{message} at line {line.number}")


def _make_line(raw: str, index: int) -> _Line:
    indentation = len(raw) - len(raw.lstrip(" "))
    return _Line(
        raw,
        _strip_comment(raw[indentation:]),
        indentation,
        index + 1,
        # Rejected where the line is read as structure; block scalar content
        # may hold tabs.
        raw[indentation : indentation + 1] == "\t",
    )


def parse(text: str) -> object:
    """One YAML document as Python values: mappings are ``dict[str, ...]``,
    sequences ``list``, scalars ``None``, ``bool``, ``int``, ``float`` or
    ``str``. Raises ``ValueError`` for malformed or unsupported text."""
    source = re.sub(r"\r\n?", "\n", text.removeprefix("\ufeff"))
    return _Parser([_make_line(raw, i) for i, raw in enumerate(source.split("\n"))]).parse()


__all__ = ["parse"]
