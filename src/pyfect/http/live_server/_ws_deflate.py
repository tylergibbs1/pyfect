"""The ``permessage-deflate`` WebSocket extension (RFC 7692) on the live server, as Node's
``ws`` server speaks it when Effect's ``NodeHttpServer`` gets
``websocket: { perMessageDeflate: ... }``: ``ws``'s ``Sec-WebSocket-Extensions`` parser
and offer negotiation, raw DEFLATE per message with the ``00 00 ff ff`` tail removed,
messages under ``threshold`` bytes sent uncompressed, and the message size limit applied
to the inflated bytes."""

from __future__ import annotations

import re
import zlib
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

from pyfect.http.live_server._ws_extensions import Params, parse_extensions
from pyfect.http.live_server._ws_frames import ProtocolError

EXTENSION_NAME = "permessage-deflate"
_TRAILER = b"\x00\x00\xff\xff"
_DECIMAL = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?")
_RADIX = re.compile(r"0([xXoObB])([0-9A-Za-z]+)")


@dataclass(frozen=True, kw_only=True, slots=True)
class PerMessageDeflate:
    """``ws``'s ``perMessageDeflate`` server options. ``None`` takes the client's offer as
    it is; ``server_no_context_takeover=True`` / ``client_no_context_takeover=True`` ask for
    it, ``False`` refuses offers that ask for it; a window size (8 to 15) caps the offer,
    ``False`` refuses a ``server_max_window_bits`` offer (and drops
    ``client_max_window_bits``). Messages shorter than ``threshold`` bytes go uncompressed."""

    server_no_context_takeover: bool | None = None
    client_no_context_takeover: bool | None = None
    server_max_window_bits: int | Literal[False] | None = None
    client_max_window_bits: int | Literal[False] | None = None
    threshold: int = 1024

    def __post_init__(self) -> None:
        for bits in (self.server_max_window_bits, self.client_max_window_bits):
            if isinstance(bits, int) and not isinstance(bits, bool) and not 8 <= bits <= 15:
                raise ValueError(f"a window size is 8 to 15 bits, got {bits}")
        if self.threshold < 0:
            raise ValueError(f"threshold must not be negative, got {self.threshold}")


@dataclass(frozen=True, slots=True)
class WebSocketConfig:
    """The live server's WebSocket settings: the message size limit and, when set, the
    ``permessage-deflate`` options it accepts offers with."""

    max_message_size: int
    per_message_deflate: PerMessageDeflate | None = None


def _token_number(value: str) -> float | None:
    """JavaScript's ``+value`` for a token (``None`` for ``NaN``)."""
    radix = _RADIX.fullmatch(value)
    if radix is not None:
        base = {"x": 16, "o": 8, "b": 2}[radix[1].lower()]
        try:
            return int(radix[2], base)
        except ValueError:
            return None
    if _DECIMAL.fullmatch(value) is not None:
        return float(value)
    return None


type _Accepted = dict[str, int | Literal[True]]


def _normalize(offers: list[Params]) -> list[_Accepted]:
    normalized: list[_Accepted] = []
    for params in offers:
        out: _Accepted = {}
        for key, values in params.items():
            if len(values) > 1:
                raise ValueError(f'Parameter "{key}" must have only a single value')
            value = values[0]
            if key in ("client_max_window_bits", "server_max_window_bits"):
                if value is True and key == "client_max_window_bits":
                    out[key] = True
                    continue
                number = None if value is True else _token_number(value)
                if number is None or not number.is_integer() or not 8 <= number <= 15:
                    raise ValueError(f'Invalid value for parameter "{key}": {value}')
                out[key] = int(number)
            elif key in ("client_no_context_takeover", "server_no_context_takeover"):
                if value is not True:
                    raise ValueError(f'Invalid value for parameter "{key}": {value}')
                out[key] = True
            else:
                raise ValueError(f'Unknown parameter "{key}"')
        normalized.append(out)
    return normalized


def _acceptable(options: PerMessageDeflate, params: _Accepted) -> bool:
    server_bits = params.get("server_max_window_bits")
    client_bits = params.get("client_max_window_bits")
    wanted_server = _bits(options.server_max_window_bits)
    wanted_client = _bits(options.client_max_window_bits)
    if options.server_no_context_takeover is False and "server_no_context_takeover" in params:
        return False
    if server_bits is not None and (
        options.server_max_window_bits is False
        or (wanted_server is not None and wanted_server > server_bits)
    ):
        return False
    if wanted_client is not None:
        if client_bits is not None and client_bits is not True:
            return wanted_client <= client_bits
        return client_bits is not None
    return True


def _bits(value: int | Literal[False] | None) -> int | None:
    """A configured window size, or ``None`` for unset or ``False``."""
    return None if value is None or value is False else value


@dataclass(frozen=True, slots=True)
class Negotiated:
    """The accepted parameters, in ``ws``'s order."""

    params: Mapping[str, int | Literal[True]]
    threshold: int
    max_message_size: int

    def header(self) -> str:
        """The ``Sec-WebSocket-Extensions`` value the ``101`` carries."""
        parts = [EXTENSION_NAME]
        for key, value in self.params.items():
            parts.append(key if value is True else f"{key}={value}")
        return "; ".join(parts)

    def _bits(self, key: str) -> int:
        value = self.params.get(key)
        return value if isinstance(value, int) and value is not True else 15

    def inflater(self) -> Inflater:
        return Inflater(
            self._bits("client_max_window_bits"),
            "client_no_context_takeover" in self.params,
            self.max_message_size,
        )

    def deflater(self) -> Deflater:
        return Deflater(
            self._bits("server_max_window_bits"),
            "server_no_context_takeover" in self.params,
            self.threshold,
        )


def negotiate(options: PerMessageDeflate, header: str, max_message_size: int) -> Negotiated | None:
    """The accepted ``permessage-deflate`` offer of a ``Sec-WebSocket-Extensions`` header,
    ``None`` when it offers none; ``ValueError`` for a malformed or unacceptable header
    (``ws`` answers 400)."""
    offers = parse_extensions(header).get(EXTENSION_NAME)
    if offers is None:
        return None
    accepted = next((params for params in _normalize(offers) if _acceptable(options, params)), None)
    if accepted is None:
        raise ValueError("None of the extension offers can be accepted")
    if options.server_no_context_takeover:
        accepted["server_no_context_takeover"] = True
    if options.client_no_context_takeover:
        accepted["client_no_context_takeover"] = True
    if (server_bits := _bits(options.server_max_window_bits)) is not None:
        accepted["server_max_window_bits"] = server_bits
    if (client_bits := _bits(options.client_max_window_bits)) is not None:
        accepted["client_max_window_bits"] = client_bits
    elif accepted.get("client_max_window_bits") is True or options.client_max_window_bits is False:
        accepted.pop("client_max_window_bits", None)
    return Negotiated(accepted, options.threshold, max_message_size)


class Inflater:
    """Inflates the client's compressed messages, frame by frame."""

    __slots__ = ("_max", "_reset", "_stream", "_window")

    def __init__(self, window_bits: int, no_context_takeover: bool, max_message_size: int) -> None:
        self._window = window_bits
        self._reset = no_context_takeover
        self._max = max_message_size
        self._stream: zlib._Decompress | None = None  # pyright: ignore[reportPrivateUsage]

    def feed(self, payload: bytes, fin: bool, inflated_so_far: int) -> bytes:
        """The inflated bytes of one frame of a message; a 1009 ``ProtocolError`` once the
        message passes the size limit, a 1007 one for data that does not inflate."""
        stream = self._stream
        if stream is None:
            stream = self._stream = zlib.decompressobj(-self._window)
        room = self._max - inflated_so_far
        data = payload + _TRAILER if fin else payload
        try:
            out = stream.decompress(data, room + 1)
        except zlib.error as cause:
            self._stream = None
            raise ProtocolError(1007, str(cause)) from None
        if len(out) > room or stream.unconsumed_tail:
            self._stream = None
            raise ProtocolError(1009, "Max payload size exceeded")
        if stream.eof or (fin and self._reset):
            self._stream = None
        return out


class Deflater:
    """Compresses the server's messages; called on the event loop, in write order."""

    __slots__ = ("_reset", "_stream", "_threshold", "_window")

    def __init__(self, window_bits: int, no_context_takeover: bool, threshold: int) -> None:
        # zlib takes no 8-bit window for raw deflate; Node uses 9 for it too.
        self._window = max(window_bits, 9)
        self._reset = no_context_takeover
        self._threshold = threshold
        self._stream: zlib._Compress | None = None  # pyright: ignore[reportPrivateUsage]

    def compress(self, data: bytes) -> bytes | None:
        """The compressed payload of a whole message, ``None`` below the threshold."""
        if len(data) < self._threshold:
            return None
        stream = self._stream
        if stream is None:
            stream = self._stream = zlib.compressobj(
                zlib.Z_DEFAULT_COMPRESSION, zlib.DEFLATED, -self._window
            )
        out = stream.compress(data) + stream.flush(zlib.Z_SYNC_FLUSH)
        if self._reset:
            self._stream = None
        return out[:-4] if out.endswith(_TRAILER) else out
