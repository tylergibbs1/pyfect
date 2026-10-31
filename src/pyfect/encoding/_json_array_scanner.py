"""The incremental scanner behind ``json_array.decode_string``.

The scanner walks the containers along the pointer and the selected
array. Every other value is captured whole (it may span chunks) and parsed
with ``json.loads``: elements are written, keys are matched against the
pointer, and the rest is checked and dropped. Offsets and sizes count
characters of the decoded text after a leading byte-order mark.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from enum import IntEnum, auto
from typing import ClassVar, Literal, Never

from pyfect import _json_text
from pyfect._digits import parse_digits
from pyfect._json_text import PARSE_ERRORS, Json, parse
from pyfect.errors import TaggedError


@dataclass(eq=False)
class JsonArrayError(TaggedError):
    """Encoding or decoding a JSON array failed.

    - ``"Syntax"``: the input is not JSON (an empty input, content after
      the document, a bad value).
    - ``"Limit"``: a value (an element, a key, or a value outside the
      selected array) passes ``max_depth`` or ``max_element_size``.
    - ``"Pointer"``: the pointer's target is missing or not an array, a
      value along it is not an object or array, or an object along it
      repeats the key it follows.
    - ``"Encode"``: a value has no JSON form.

    Decoding errors set ``offset``: the character offset of the bad value
    (or character) in the text after a leading byte-order mark. ``cause``
    is the exception ``json`` raised, when it raised one."""

    kind: Literal["Syntax", "Limit", "Pointer", "Encode"]
    message: str
    offset: int | None = None
    cause: Exception | None = None


_POINTER = re.compile(r"(?:/(?:[^~/]|~[01])*)*")


@dataclass(frozen=True)
class Config:
    """Parsed decoding options."""

    tokens: tuple[str, ...]
    indices: tuple[int, ...]
    """The array index each token selects, or -1 when it is not an index."""
    max_depth: int
    max_element_size: float


def make_config(pointer: str, max_depth: int, max_element_size: float) -> Config:
    """Parse the options; bad ones raise ``ValueError``."""
    if not _POINTER.fullmatch(pointer):
        raise ValueError(f"pointer must be an RFC 6901 JSON Pointer, got {pointer!r}")
    if max_depth < 0:
        raise ValueError(f"max_depth must be a non-negative integer, got {max_depth}")
    if not max_element_size >= 1:
        raise ValueError(f"max_element_size must be at least 1, got {max_element_size}")
    tokens = tuple(unescape(token) for token in pointer.split("/")[1:])
    indices = tuple(_index(token) for token in tokens)
    return Config(tokens, indices, max_depth, max_element_size)


def _index(token: str) -> int:
    index = parse_digits(token, unpadded=True)
    return -1 if index is None else index


def unescape(token: str) -> str:
    return token.replace("~1", "/").replace("~0", "~")


def escape(token: str) -> str:
    return token.replace("~", "~0").replace("/", "~1")


class _State(IntEnum):
    VALUE = auto()  # the value at the current pointer prefix
    OBJECT_START = auto()  # after ``{``: a key or ``}``
    OBJECT_KEY = auto()  # after ``,``: a key
    OBJECT_COLON = auto()  # after a key: ``:``
    OBJECT_VALUE = auto()  # after ``:`` for a key the pointer does not follow
    OBJECT_NEXT = auto()  # after a member: ``,`` or ``}``
    ARRAY_START = auto()  # after ``[``: a value or ``]``
    ARRAY_VALUE = auto()  # after ``,``: a value
    ARRAY_NEXT = auto()  # after an element: ``,`` or ``]``
    END = auto()  # after the document


class _Capture(IntEnum):
    NONE = auto()
    SKIP = auto()
    ELEMENT = auto()
    KEY = auto()


class _Frame:
    __slots__ = ("found", "index", "is_object", "target")

    def __init__(self, is_object: bool, target: bool) -> None:
        self.is_object = is_object
        self.target = target  # the selected array
        self.found = False  # the pointer's token for this container was seen
        self.index = 0


_VALUE_START = frozenset('"[{-0123456789fnt')
_NON_WHITESPACE = re.compile(r"[^ \t\n\r]")
_STRING_STOP = re.compile(r'["\\]')
_NESTED_STOP = re.compile(r'["\[\]{}]')
_ELEMENTS_STOP = re.compile(r'["\[\]{},]')
_SCALAR_END = re.compile(r"[ \t\n\r,\]}]")


class Scanner:
    """Feed it the document's text in chunks; it appends the selected
    array's elements to ``out`` and raises ``JsonArrayError``."""

    def __init__(self, config: Config) -> None:
        self.config = config
        self.state = _State.VALUE
        self.frames: list[_Frame] = []
        self.key = ""
        self.started = False
        self.base = 0  # the offset of the current chunk
        # The value being captured, which may span chunks.
        self.capture = _Capture.NONE
        self.start = 0
        self.buffer: list[str] = []
        self.buffered = 0
        self.scalar = False
        self.depth = 0
        self.in_string = False
        self.escape = False
        # The end of a batch of elements that failed to parse: the precise
        # scan handles the text before it, so it is not parsed again.
        self.slow = 0

    def fail(
        self,
        kind: Literal["Syntax", "Limit", "Pointer"],
        message: str,
        offset: int,
        cause: Exception | None = None,
    ) -> JsonArrayError:
        return JsonArrayError(kind, message, offset, cause)

    def pointer_prefix(self, length: int, *rest: str) -> str:
        tokens = (*self.config.tokens[:length], *rest)
        return _json_text.stringify("".join("/" + escape(token) for token in tokens))

    def subject(self) -> str:
        """The value being captured, for limit errors."""
        if self.capture is _Capture.ELEMENT:
            return "Element"
        depth = len(self.frames) - 1
        if self.capture is _Capture.KEY:
            return f"Key in {self.pointer_prefix(depth)}"
        frame = self.frames[depth]
        token = self.key if frame.is_object else str(frame.index - 1)
        return f"Value outside the selected array at {self.pointer_prefix(depth, token)}"

    def feed(self, text: str, out: list[Json]) -> None:
        if not self.started and text:
            self.started = True
            if text[0] == "﻿":
                text = text[1:]
        i = 0 if self.capture is _Capture.NONE else self.scan(text, 0, out)
        while True:
            found = _NON_WHITESPACE.search(text, i)
            if found is None:
                break
            i = self.step(text, found.start(), out)
        if self.capture is not _Capture.NONE:
            rest = text[max(self.start - self.base, 0) :]
            self.buffer.append(rest)
            self.buffered += len(rest)
            self.check_size(self.buffered)
        self.base += len(text)

    def end(self) -> None:
        if self.state is not _State.END or self.capture is not _Capture.NONE:
            raise self.fail("Syntax", "Unexpected end of input", self.base)

    def step(self, text: str, i: int, out: list[Json]) -> int:
        """Handle the structural character at ``i``; return the next index."""
        state = self.state
        after = None if state is _State.END else self._STEPS[state](self, text, i, out)
        if after is not None:
            return after
        message = (
            "Unexpected content after the document"
            if state is _State.END
            else f"Unexpected character {_json_text.stringify(text[i])}"
        )
        raise self.fail("Syntax", message, self.base + i)

    # Each state's step returns the next index, or ``None`` when the
    # character is unexpected there.

    def _value(self, text: str, i: int, _out: list[Json]) -> int | None:
        c = text[i]
        target = len(self.frames) == len(self.config.tokens)
        if c == "[" or (c == "{" and not target):
            self.frames.append(_Frame(c == "{", target))
            self.state = _State.OBJECT_START if c == "{" else _State.ARRAY_START
            return i + 1
        if c in _VALUE_START:
            expected = "an array" if target else "an object or array"
            prefix = self.pointer_prefix(len(self.frames))
            raise self.fail("Pointer", f"Expected {expected} at {prefix}", self.base + i)
        return None

    def _object_key(self, text: str, i: int, out: list[Json]) -> int | None:
        c = text[i]
        if c == '"':
            self.state = _State.OBJECT_COLON
            return self.begin(_Capture.KEY, text, i, out)
        if c == "}" and self.state is _State.OBJECT_START:
            return self.close(i)
        return None

    def _object_colon(self, text: str, i: int, _out: list[Json]) -> int | None:
        if text[i] != ":":
            return None
        frame = self.frames[-1]
        if self.key == self.config.tokens[len(self.frames) - 1]:
            if frame.found:
                message = f"Duplicate key {_json_text.stringify(self.key)} along the pointer"
                raise self.fail("Pointer", message, self.base + i)
            frame.found = True
            self.state = _State.VALUE
        else:
            self.state = _State.OBJECT_VALUE
        return i + 1

    def _object_value(self, text: str, i: int, out: list[Json]) -> int | None:
        if text[i] not in _VALUE_START:
            return None
        self.state = _State.OBJECT_NEXT
        return self.begin(_Capture.SKIP, text, i, out)

    def _next(self, text: str, i: int, _out: list[Json]) -> int | None:
        c = text[i]
        is_object = self.state is _State.OBJECT_NEXT
        if c == ",":
            self.state = _State.OBJECT_KEY if is_object else _State.ARRAY_VALUE
            return i + 1
        if c == ("}" if is_object else "]"):
            return self.close(i)
        return None

    def _array_element(self, text: str, i: int, out: list[Json]) -> int | None:
        c = text[i]
        if c == "]" and self.state is _State.ARRAY_START:
            return self.close(i)
        if c not in _VALUE_START:
            return None
        return self.array_value(text, i, out)

    _STEPS: ClassVar[dict[_State, Callable[[Scanner, str, int, list[Json]], int | None]]] = {
        _State.VALUE: _value,
        _State.OBJECT_START: _object_key,
        _State.OBJECT_KEY: _object_key,
        _State.OBJECT_COLON: _object_colon,
        _State.OBJECT_VALUE: _object_value,
        _State.OBJECT_NEXT: _next,
        _State.ARRAY_NEXT: _next,
        _State.ARRAY_START: _array_element,
        _State.ARRAY_VALUE: _array_element,
    }

    def array_value(self, text: str, i: int, out: list[Json]) -> int:
        frame = self.frames[-1]
        if frame.target:
            after = self.scan_elements(text, i, out)
            if after > i:
                return after
            self.state = _State.ARRAY_NEXT
            return self.begin(_Capture.ELEMENT, text, i, out)
        self.state = _State.ARRAY_NEXT
        index = frame.index
        frame.index += 1
        if index == self.config.indices[len(self.frames) - 1]:
            frame.found = True
            self.state = _State.VALUE
            return i
        return self.begin(_Capture.SKIP, text, i, out)

    def close(self, i: int) -> int:
        frame = self.frames.pop()
        if not frame.target and not frame.found:
            prefix = self.pointer_prefix(len(self.frames) + 1)
            raise self.fail("Pointer", f"No value at {prefix}", self.base + i)
        if not self.frames:
            self.state = _State.END
        else:
            self.state = _State.OBJECT_NEXT if self.frames[-1].is_object else _State.ARRAY_NEXT
        return i + 1

    def begin(self, mode: _Capture, text: str, i: int, out: list[Json]) -> int:
        """Start capturing the value that begins at ``i``."""
        c = text[i]
        self.capture = mode
        self.start = self.base + i
        self.in_string = c == '"'
        self.escape = False
        self.depth = 1 if c in "[{" else 0
        self.scalar = not self.in_string and self.depth == 0
        if self.depth > self.config.max_depth:
            self.fail_depth()
        return self.scan(text, i + 1, out)

    def scan(self, text: str, i: int, out: list[Json]) -> int:
        """Continue the captured value from ``i``, completing it if it ends
        in this chunk. Returns the index after the value, or the chunk's
        length."""
        end = self.scan_scalar(text, i) if self.scalar else self.scan_nested(text, i)
        if end == -1:
            return len(text)
        source = "".join(self.buffer) + text[max(self.start - self.base, 0) : end]
        self.check_size(len(source))
        mode = self.capture
        self.capture = _Capture.NONE
        self.buffer = []
        self.buffered = 0
        try:
            value = parse(source)
        except PARSE_ERRORS as cause:
            raise self.fail("Syntax", "Invalid JSON value", self.start, cause) from cause
        if mode is _Capture.ELEMENT:
            out.append(value)
        elif mode is _Capture.KEY:
            self.key = str(value)
        return end

    def scan_scalar(self, text: str, i: int) -> int:
        """A scalar ends at the first delimiter; ``json.loads`` checks it."""
        found = _SCALAR_END.search(text, i)
        return -1 if found is None else found.start()

    def scan_nested(self, text: str, i: int) -> int:
        """Track only strings and nesting; ``json.loads`` checks the rest.
        Returns the index after the value, or -1."""
        if self.in_string:
            i = self.scan_string(text, i, self.escape)
            if i == -1:
                return -1
            self.in_string = False
            if self.depth == 0:
                return i
        depth = self.depth
        while True:
            found = _NESTED_STOP.search(text, i)
            if found is None:
                break
            c = text[found.start()]
            i = found.end()
            if c == '"':
                i = self.scan_string(text, i, False)
                if i == -1:
                    self.in_string = True
                    break
            elif c in "[{":
                depth += 1
                if depth > self.config.max_depth:
                    self.fail_depth()
            else:
                depth -= 1
                if depth == 0:
                    self.depth = 0
                    return i
        self.depth = depth
        return -1

    def scan_string(self, text: str, i: int, escape: bool) -> int:
        """Scan a string's contents from ``i``. Returns the index after the
        closing quote, or -1 when the string goes on into the next chunk
        (recording in ``escape`` whether it ended mid-escape)."""
        n = len(text)
        if escape:
            if i >= n:
                self.escape = True
                return -1
            i += 1
        while True:
            found = _STRING_STOP.search(text, i)
            if found is None:
                self.escape = False
                return -1
            j = found.start()
            if text[j] == '"':
                return j + 1
            if j + 1 >= n:
                self.escape = True
                return -1
            i = j + 2

    def scan_elements(self, text: str, i: int, out: list[Json]) -> int:
        """Parse the elements from ``i`` up to the last comma or closing
        bracket at the array's level with one ``json.loads``: wrapped in
        brackets, that text parses only when every element and separator
        in it is valid. Returns ``i`` to leave anything else, errors too,
        to the precise scan."""
        if self.base + i < self.slow:
            return i
        cut, closes = self.batch_end(text, i)
        values: Json = None
        if cut != -1:
            try:
                values = parse("[" + text[i:cut] + "]")
            except PARSE_ERRORS:
                self.slow = self.base + cut
        if not isinstance(values, list):
            return i
        out.extend(values)
        if closes:
            return self.close(cut)
        self.state = _State.ARRAY_VALUE
        return cut + 1

    def batch_end(self, text: str, i: int) -> tuple[int, bool]:
        """Where a batch of elements from ``i`` ends: the index of its last
        comma or closing bracket at the array's level (-1: none), and
        whether that is the bracket. A batch stops before an element over
        the limits."""
        max_depth = self.config.max_depth
        max_size = self.config.max_element_size
        cut = -1
        start = i
        depth = 0
        j = i
        while (found := _ELEMENTS_STOP.search(text, j)) is not None:
            c = text[found.start()]
            j = found.end()
            if c == '"':
                j = self.scan_string(text, j, False)
                if j == -1:
                    break
            elif c in "[{":
                depth += 1
                if depth > max_depth:
                    break
            elif c in "]}":
                if depth > 0:
                    depth -= 1
                    continue
                # Counting the whitespace around it makes this a cautious size check.
                if c == "]" and j - 1 - start <= max_size:
                    return j - 1, True
                break
            elif depth == 0:
                if j - 1 - start > max_size:
                    break
                cut = j - 1
                start = j
        return cut, False

    def check_size(self, size: int) -> None:
        if size > self.config.max_element_size:
            limit = self.config.max_element_size
            message = f"{self.subject()} exceeds max_element_size of {limit}"
            raise self.fail("Limit", message, self.start)

    def fail_depth(self) -> Never:
        message = f"{self.subject()} exceeds max_depth of {self.config.max_depth}"
        raise self.fail("Limit", message, self.start)
