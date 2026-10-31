"""The server side of RFC 6455's opening handshake and framing, as Node's
``ws`` speaks it with its server defaults (no extensions): the
``Sec-WebSocket-Accept`` key, unmasked frames out, and a parser of the
client's masked frames that turns them into messages, pings and the
close, or a ``ProtocolError`` with the close code ``ws`` sends for it."""

from __future__ import annotations

import base64
import hashlib
import re
import struct
from dataclasses import dataclass
from enum import Enum, IntEnum, auto

from pyfect._js import text_encode

_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
_KEY = re.compile(r"[+/0-9A-Za-z]{22}==")
_MAX_CONTROL_PAYLOAD = 125


class Opcode(IntEnum):
    CONTINUATION = 0x0
    TEXT = 0x1
    BINARY = 0x2
    CLOSE = 0x8
    PING = 0x9
    PONG = 0xA


def is_valid_key(key: str | None) -> bool:
    """A ``Sec-WebSocket-Key``: 16 bytes in base64 (``ws``'s ``keyRegex``)."""
    return key is not None and _KEY.fullmatch(key) is not None


def accept_key(key: str) -> str:
    """The ``Sec-WebSocket-Accept`` answering ``key`` (RFC 6455 §4.2.2)."""
    return base64.b64encode(hashlib.sha1((key + _GUID).encode("ascii")).digest()).decode("ascii")


def is_valid_close_code(code: int) -> bool:
    """A code a close frame may carry (``ws``'s ``isValidStatusCode``)."""
    return (1000 <= code <= 1014 and code not in (1004, 1005, 1006)) or 3000 <= code <= 4999


def encode_frame(opcode: Opcode, payload: bytes) -> bytes:
    """One final, unmasked frame."""
    size = len(payload)
    first = 0x80 | opcode
    if size < 126:
        head = struct.pack("!BB", first, size)
    elif size < 1 << 16:
        head = struct.pack("!BBH", first, 126, size)
    else:
        head = struct.pack("!BBQ", first, 127, size)
    return head + payload


def encode_message(data: bytes | str) -> bytes:
    """A text frame for ``str`` (as ``TextEncoder`` encodes it), else binary."""
    if isinstance(data, str):
        return encode_frame(Opcode.TEXT, text_encode(data))
    return encode_frame(Opcode.BINARY, data)


def encode_close(code: int | None, reason: str = "") -> bytes:
    """A close frame; without ``code`` its payload is empty."""
    if code is None:
        return encode_frame(Opcode.CLOSE, b"")
    return encode_frame(Opcode.CLOSE, struct.pack("!H", code) + text_encode(reason))


class ProtocolError(Exception):
    """The client broke the protocol; ``code`` is the close code to send."""

    def __init__(self, code: int, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class Message:
    data: bytes | str


@dataclass(frozen=True, slots=True)
class Ping:
    payload: bytes


@dataclass(frozen=True, slots=True)
class Close:
    """The client's close frame: 1005 when it carried no code."""

    code: int
    reason: str


type Event = Message | Ping | Close


class _NoEvent(Enum):
    NO_EVENT = auto()


_NO_EVENT = _NoEvent.NO_EVENT


def _unmask(data: bytes, mask: bytes) -> bytes:
    size = len(data)
    if not size:
        return b""
    key = (mask * (size // 4 + 1))[:size]
    return (int.from_bytes(data, "little") ^ int.from_bytes(key, "little")).to_bytes(size, "little")


def _parse_close(payload: bytes) -> Close:
    if not payload:
        return Close(1005, "")
    if len(payload) == 1:
        raise ProtocolError(1002, "invalid payload length 1")
    (code,) = struct.unpack("!H", payload[:2])
    if not is_valid_close_code(code):
        raise ProtocolError(1002, f"invalid status code {code}")
    try:
        reason = payload[2:].decode("utf-8")
    except UnicodeDecodeError:
        raise ProtocolError(1007, "invalid UTF-8 sequence") from None
    return Close(code, reason)


class FrameParser:
    """Feeds the client's bytes in, gives the events of the frames they
    complete. Messages longer than ``max_message_size`` bytes are a 1009
    ``ProtocolError``; once one is raised, or a close is parsed, the parser
    takes nothing more."""

    __slots__ = ("_buffer", "_done", "_fragments", "_max", "_message_opcode", "_message_size")

    def __init__(self, max_message_size: int) -> None:
        self._max = max_message_size
        self._buffer = bytearray()
        self._fragments: list[bytes] = []
        self._message_opcode: Opcode | None = None
        self._message_size = 0
        self._done = False

    def feed(self, data: bytes) -> list[Event]:
        if self._done:
            return []
        self._buffer += data
        events: list[Event] = []
        try:
            while (event := self._next()) is not None:
                if event is _NO_EVENT:
                    continue
                events.append(event)
                if isinstance(event, Close):
                    self._done = True
                    break
        except ProtocolError:
            self._done = True
            raise
        return events

    def _next(self) -> Event | _NoEvent | None:
        """The next frame's event (``_NO_EVENT`` for a frame without one);
        ``None`` until a whole frame is buffered."""
        buffer = self._buffer
        if len(buffer) < 2:
            return None
        first, second = buffer[0], buffer[1]
        if first & 0x70:
            raise ProtocolError(1002, "RSV1, RSV2 and RSV3 must be clear")
        try:
            opcode = Opcode(first & 0x0F)
        except ValueError:
            raise ProtocolError(1002, f"invalid opcode {first & 0x0F}") from None
        fin = bool(first & 0x80)
        if not second & 0x80:
            raise ProtocolError(1002, "MASK must be set")
        length = second & 0x7F
        offset = 2
        if length == 126:
            if len(buffer) < 4:
                return None
            (length,) = struct.unpack_from("!H", buffer, 2)
            offset = 4
        elif length == 127:
            if len(buffer) < 10:
                return None
            (length,) = struct.unpack_from("!Q", buffer, 2)
            offset = 10
        self._check(opcode, fin, length)
        end = offset + 4 + length
        if len(buffer) < end:
            return None
        mask = bytes(buffer[offset : offset + 4])
        payload = _unmask(bytes(buffer[offset + 4 : end]), mask)
        del buffer[:end]
        return self._event(opcode, fin, payload)

    def _check(self, opcode: Opcode, fin: bool, length: int) -> None:
        if opcode >= Opcode.CLOSE:
            if not fin:
                raise ProtocolError(1002, "FIN must be set")
            if length > _MAX_CONTROL_PAYLOAD:
                raise ProtocolError(1002, f"invalid payload length {length}")
            return
        if opcode == Opcode.CONTINUATION:
            if self._message_opcode is None:
                raise ProtocolError(1002, "invalid opcode 0")
        elif self._message_opcode is not None:
            raise ProtocolError(1002, f"invalid opcode {int(opcode)}")
        if self._message_size + length > self._max:
            raise ProtocolError(1009, "Max payload size exceeded")

    def _event(self, opcode: Opcode, fin: bool, payload: bytes) -> Event | _NoEvent:
        if opcode == Opcode.CLOSE:
            return _parse_close(payload)
        if opcode == Opcode.PING:
            return Ping(payload)
        if opcode == Opcode.PONG:
            return _NO_EVENT
        if opcode != Opcode.CONTINUATION:
            self._message_opcode = opcode
        self._fragments.append(payload)
        self._message_size += len(payload)
        if not fin:
            return _NO_EVENT
        data = b"".join(self._fragments)
        text = self._message_opcode == Opcode.TEXT
        self._fragments.clear()
        self._message_opcode = None
        self._message_size = 0
        if not text:
            return Message(data)
        try:
            return Message(data.decode("utf-8"))
        except UnicodeDecodeError:
            raise ProtocolError(1007, "invalid UTF-8 sequence") from None
