"""An incremental parser of a part's header block (``Name: value`` lines
ending with an empty line), across chunks, with Effect's limits: 100
headers, 16 KiB."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

type FailureReason = Literal[
    "TooManyHeaders", "HeaderTooLarge", "InvalidHeaderName", "InvalidHeaderValue"
]
type PartHeaders = dict[str, str | list[str]]


@dataclass(frozen=True, slots=True)
class Continue:
    """More bytes are needed."""


@dataclass(frozen=True, slots=True)
class Failure:
    reason: FailureReason
    headers: PartHeaders


@dataclass(frozen=True, slots=True)
class Parsed:
    """The headers, and where the body starts in the chunk."""

    headers: PartHeaders
    end_position: int


type ReturnValue = Continue | Failure | Parsed

_MAX_PAIRS = 100
_MAX_SIZE = 16 * 1024
_CONTINUE = Continue()

_NAME_CHARS = frozenset(
    b"!#$%&'*+-.^_`|~0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
)
_VALUE_CHARS = frozenset([9, *range(32, 127), *range(128, 256)])

_KEY, _WHITESPACE, _VALUE = 0, 1, 2


def _at(chunk: bytes, i: int) -> int:
    return chunk[i] if 0 <= i < len(chunk) else -1


def _decode(data: bytes) -> str:
    return data.decode("utf-8", "replace")


class HeadersParser:
    __slots__ = ("_crlf", "_headers", "_key", "_pairs", "_previous", "_size", "_state", "_value")

    def __init__(self) -> None:
        self._reset()

    def _reset(self) -> None:
        self._state = _KEY
        self._headers: PartHeaders = {}
        self._key = ""
        self._value: bytes | None = None
        self._crlf = 0
        self._previous: bytes | None = None
        self._pairs = 0
        self._size = 0

    def _error(self, reason: FailureReason) -> Failure:
        headers = self._headers
        self._reset()
        return Failure(reason, headers)

    def _add(self, value: str) -> None:
        current = self._headers.get(self._key)
        if current is None:
            self._headers[self._key] = value
        elif isinstance(current, str):
            self._headers[self._key] = [current, value]
        else:
            current.append(value)

    def write(self, chunk: bytes, start: int) -> ReturnValue:  # noqa: PLR0911, PLR0912, PLR0915
        end_offset = 0
        previous_cursor: int | None = None
        if self._previous is not None:
            end_offset = len(self._previous)
            previous_cursor = end_offset
            chunk = self._previous + chunk
            self._previous = None
        end = len(chunk)

        while start < end:
            if self._state == _KEY:
                i = start
                while i < end:
                    self._size += 1
                    if self._size - 1 > _MAX_SIZE:
                        return self._error("HeaderTooLarge")
                    if chunk[i] == 58:
                        self._key += _decode(chunk[start:i]).lower()
                        if not self._key:
                            return self._error("InvalidHeaderName")
                        after, second = _at(chunk, i + 1), _at(chunk, i + 2)
                        if after == 32 and second not in (32, 9):
                            start = i + 2
                            self._state = _VALUE
                            self._size += 1
                        elif after not in (32, 9):
                            start = i + 1
                            self._state = _VALUE
                        else:
                            start = i + 1
                            self._state = _WHITESPACE
                        break
                    if chunk[i] not in _NAME_CHARS:
                        return self._error("InvalidHeaderName")
                    i += 1
                if i == end:
                    self._key += _decode(chunk[start:end]).lower()
                    return _CONTINUE

            if self._state == _WHITESPACE:
                while start < end:
                    self._size += 1
                    if self._size - 1 > _MAX_SIZE:
                        return self._error("HeaderTooLarge")
                    if chunk[start] not in (32, 9):
                        self._state = _VALUE
                        break
                    start += 1
                if start == end:
                    return _CONTINUE

            if self._state == _VALUE:
                i = start
                if previous_cursor is not None:
                    i = previous_cursor
                    previous_cursor = None
                restart = False
                while i < end:
                    self._size += 1
                    if self._size - 1 > _MAX_SIZE:
                        return self._error("HeaderTooLarge")
                    if chunk[i] == 13 or self._crlf > 0:
                        byte = chunk[i]
                        if byte == 13 and self._crlf == 0:
                            self._crlf = 1
                            i += 1
                            self._size += 1
                            byte = _at(chunk, i)
                        if byte == 10 and self._crlf == 1:
                            self._crlf = 2
                            i += 1
                            self._size += 1
                            byte = _at(chunk, i)
                        if byte == 13 and self._crlf == 2:
                            self._crlf = 3
                            i += 1
                            self._size += 1
                            byte = _at(chunk, i)
                        if byte == 10 and self._crlf == 3:
                            self._crlf = 4
                            i += 1
                            self._size += 1
                        if self._crlf < 4 and i >= end:
                            self._previous = chunk[start:]
                            return _CONTINUE
                        if self._crlf >= 2:
                            piece = chunk[start : i - self._crlf]
                            self._value = piece if self._value is None else self._value + piece
                            self._add(_decode(self._value))
                            start = i
                            self._size -= 1
                            if self._crlf != 4 and self._pairs == _MAX_PAIRS:
                                return self._error("TooManyHeaders")
                            if self._crlf == 3:
                                return self._error("InvalidHeaderValue")
                            if self._crlf == 4:
                                headers = self._headers
                                self._reset()
                                return Parsed(headers, start - end_offset)
                            self._pairs += 1
                            self._key = ""
                            self._value = None
                            self._crlf = 0
                            self._state = _KEY
                            restart = True
                            break
                    elif chunk[i] not in _VALUE_CHARS:
                        return self._error("InvalidHeaderValue")
                    i += 1
                if restart:
                    continue
                if i == end:
                    piece = chunk[start:end]
                    self._value = piece if self._value is None else self._value + piece
                    return _CONTINUE

        if start > end:
            self._size += end - start
        return _CONTINUE
