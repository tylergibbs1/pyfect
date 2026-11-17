"""The ``application/vnd.amazon.eventstream`` framing of ConverseStream
responses (Effect's ``internal/eventStream.ts``), decoded by hand.

A frame is ``[total length u32][headers length u32][prelude CRC u32]
[headers][payload][message CRC u32]``, big-endian. The prelude CRC covers
the first 8 bytes, the message CRC everything before it. A header is
``[name length u8][name][value type u8][value]``; only string headers
(``:message-type``, ``:event-type``, ...) are kept.
"""

from __future__ import annotations

import zlib
from dataclasses import dataclass
from typing import Any

import pyfect as fx
from pyfect import stream as St
from pyfect._core import Effect
from pyfect._json_text import parse as parse_json_text
from pyfect.errors import TaggedError
from pyfect.stream import Stream


@dataclass(eq=False)
class EventStreamError(TaggedError):
    """A frame that cannot be decoded."""

    description: str

    @property
    def message(self) -> str:
        return self.description


@dataclass(frozen=True)
class Frame:
    """A frame's string headers and its payload."""

    headers: dict[str, str]
    payload: bytes


class _Malformed(Exception):
    def __init__(self, description: str) -> None:
        super().__init__(description)
        self.description = description


_MINIMUM_FRAME_LENGTH = 16
"""The prelude (12 bytes) and the message CRC (4 bytes)."""

_FIXED_VALUE_LENGTHS = {0: 0, 1: 0, 2: 1, 3: 2, 4: 4, 5: 8, 8: 8, 9: 16}
"""The byte length of each fixed-size header value, by type code (bool true
and false, byte, short, integer, long, timestamp, uuid)."""

_BYTE_ARRAY = 6
_STRING = 7


def _text(data: bytes) -> str:
    return data.decode("utf-8", "replace")


def _decode_headers(data: bytes) -> dict[str, str]:
    headers: dict[str, str] = {}
    offset = 0

    def take(length: int) -> bytes:
        nonlocal offset
        if offset + length > len(data):
            raise _Malformed("An event stream header runs past the end of the headers block")
        start = offset
        offset += length
        return data[start:offset]

    while offset < len(data):
        name = _text(take(take(1)[0]))
        value_type = take(1)[0]
        if value_type == _BYTE_ARRAY:
            take(int.from_bytes(take(2)))
        elif value_type == _STRING:
            headers[name] = _text(take(int.from_bytes(take(2))))
        else:
            length = _FIXED_VALUE_LENGTHS.get(value_type)
            if length is None:
                raise _Malformed(f"An event stream header has the unknown value type {value_type}")
            take(length)
    return headers


def _take_frames(buffer: bytes) -> tuple[list[Frame], bytes]:
    """Every complete frame at the front of ``buffer``, and the bytes left."""
    frames: list[Frame] = []
    while len(buffer) >= 4:
        total_length = int.from_bytes(buffer[0:4])
        if total_length < _MINIMUM_FRAME_LENGTH:
            raise _Malformed(
                f"An event stream frame declares a total length of {total_length} bytes, "
                "below the minimum of 16"
            )
        if len(buffer) < total_length:
            break
        headers_length = int.from_bytes(buffer[4:8])
        if _MINIMUM_FRAME_LENGTH + headers_length > total_length:
            raise _Malformed(
                f"An event stream frame declares {headers_length} bytes of headers "
                f"in a frame of {total_length} bytes"
            )
        if zlib.crc32(buffer[0:8]) != int.from_bytes(buffer[8:12]):
            raise _Malformed("The prelude CRC of an event stream frame does not match")
        message_end = total_length - 4
        if zlib.crc32(buffer[0:message_end]) != int.from_bytes(buffer[message_end:total_length]):
            raise _Malformed("The message CRC of an event stream frame does not match")
        headers_end = 12 + headers_length
        frames.append(
            Frame(_decode_headers(buffer[12:headers_end]), buffer[headers_end:message_end])
        )
        buffer = buffer[total_length:]
    return frames, buffer


def decode[E, R](chunks: Stream[bytes, E, R]) -> Stream[Frame, E | EventStreamError, R]:
    """The frames of a byte stream; one that ends inside a frame fails."""

    def run() -> Stream[Frame, E | EventStreamError, R]:
        buffer = b""

        def step(chunk: bytes) -> Effect[list[Frame], EventStreamError]:
            nonlocal buffer
            try:
                frames, buffer = _take_frames(buffer + chunk)
            except _Malformed as error:
                return fx.fail(EventStreamError(error.description))
            return fx.succeed(frames)

        def trailing() -> Stream[Frame, EventStreamError]:
            if not buffer:
                return St.empty
            return St.fail(
                EventStreamError(
                    f"The event stream ended with {len(buffer)} bytes of an incomplete frame"
                )
            )

        frames: Stream[Frame, E | EventStreamError, R] = chunks.map_effect(step).flatten_iterable()
        return frames.concat(St.suspend(trailing))

    return St.suspend(run)


def parse_json_payload(frame: Frame) -> Effect[Any, EventStreamError]:
    """A frame's payload as JSON."""
    text = _text(frame.payload)
    try:
        return fx.succeed(parse_json_text(text))
    except ValueError:
        return fx.fail(
            EventStreamError(f"The payload of an event stream frame is not JSON: {text}")
        )
