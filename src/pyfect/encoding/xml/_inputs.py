"""The machines behind the channels: a machine's ``push`` and ``end`` add output
to ``out`` and raise ``XmlError``."""

from __future__ import annotations

from typing import Protocol

from pyfect.encoding.xml._chars import to_units
from pyfect.encoding.xml._model import Event
from pyfect.encoding.xml._parser import Parser


class Machine[In, Out](Protocol):
    @property
    def out(self) -> list[Out]: ...

    @out.setter
    def out(self, out: list[Out]) -> None: ...

    def push(self, value: In, /) -> None: ...

    def end(self) -> None: ...


class TextInput:
    def __init__(self, parser: Parser) -> None:
        self._parser = parser
        # A high surrogate at the end of a chunk, which pairs with the next chunk
        self._surrogate = ""

    @property
    def out(self) -> list[Event]:
        return self._parser.out

    @out.setter
    def out(self, out: list[Event]) -> None:
        self._parser.out = out

    def push(self, value: str, /) -> None:
        chunk = self._surrogate + to_units(value)
        self._surrogate = ""
        if chunk and "\ud800" <= chunk[-1] <= "\udbff":
            self._surrogate = chunk[-1]
            chunk = chunk[:-1]
        self._parser.feed(chunk)

    def end(self) -> None:
        # An unpaired high surrogate fails as an invalid character
        self._parser.feed(self._surrogate)
        self._parser.end()


def _utf8_length(lead: int) -> int:
    return 4 if lead >= 0xF0 else 3 if lead >= 0xE0 else 2 if lead >= 0xC0 else 1


class Utf8Input:
    """Decodes UTF-8 without streaming state, so that the position of invalid
    bytes is known: an incomplete sequence at the end of a chunk is carried over."""

    def __init__(self, parser: Parser) -> None:
        self._parser = parser
        self._carry: bytes | None = None
        self._started = False

    @property
    def out(self) -> list[Event]:
        return self._parser.out

    @out.setter
    def out(self, out: list[Event]) -> None:
        self._parser.out = out

    def push(self, value: bytes, /) -> None:
        carry = self._carry
        if not self._started and value:
            first = value[0] if carry is None else carry[0]
            second = (value[1] if len(value) > 1 else None) if carry is None else value[0]
            if (first == 0xFE and second == 0xFF) or (first == 0xFF and second == 0xFE):
                raise self._parser.error(
                    "Unsupported",
                    "UTF-16 is not supported for byte input, decode the bytes to text first",
                    0,
                )
            # Keep a lone BOM prefix pending in the UTF-8 carry below
            self._started = second is not None or first not in (0xFE, 0xFF)
        start = 0
        if carry is not None:
            need = _utf8_length(carry[0]) - len(carry)
            head = carry + value[:need]
            if len(value) < need:
                self._carry = head
                return
            self._carry = None
            self._decode(head)
            start = need
        n = len(value)
        end = n
        for k in range(1, 4):
            if n - k < start:
                break
            b = value[n - k]
            if b & 0xC0 == 0x80:
                continue
            if b >= 0xC0 and k < _utf8_length(b):
                end = n - k
            break
        if end < n:
            self._carry = value[end:]
        if end > start:
            self._decode(value if start == 0 and end == n else value[start:end])

    def end(self) -> None:
        # The carried bytes may also be an invalid sequence, such as a single 0xFF
        if self._carry is not None:
            self._parser.feed("", True)
            raise self._parser.error("Syntax", "invalid UTF-8", self._parser.received)
        self._parser.end()

    def _decode(self, value: bytes) -> None:
        try:
            text = value.decode()
        except UnicodeDecodeError as error:
            self._parser.feed(to_units(value[: error.start].decode()), True)
            raise self._parser.error("Syntax", "invalid UTF-8", self._parser.received) from None
        self._parser.feed(to_units(text))
