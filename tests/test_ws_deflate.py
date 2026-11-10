"""The live server's ``permessage-deflate`` negotiation against Node's ``ws``: 150
``Sec-WebSocket-Extensions`` headers under five server option sets, as ws 8.22.1's
``extension.parse`` and ``PerMessageDeflate.accept`` answer them
(``tests/oracle/fixtures/ws_deflate_node.json``), and the compressor and inflater."""

from __future__ import annotations

import json
import zlib
from pathlib import Path
from typing import Any

import pytest

from pyfect.http.live_server import PerMessageDeflate
from pyfect.http.live_server._ws_deflate import Deflater, Inflater, negotiate
from pyfect.http.live_server._ws_frames import ProtocolError

_FIXTURE = Path(__file__).parent / "oracle" / "fixtures" / "ws_deflate_node.json"
_CASES: list[dict[str, Any]] = json.loads(_FIXTURE.read_text())["cases"]


def _options(ws: dict[str, Any]) -> PerMessageDeflate:
    return PerMessageDeflate(
        server_no_context_takeover=ws.get("serverNoContextTakeover"),
        client_no_context_takeover=ws.get("clientNoContextTakeover"),
        server_max_window_bits=ws.get("serverMaxWindowBits"),
        client_max_window_bits=ws.get("clientMaxWindowBits"),
    )


@pytest.mark.parametrize("case", _CASES, ids=lambda case: f"{case['options']}|{case['header']}")
def test_negotiates_as_ws(case: dict[str, Any]) -> None:
    try:
        negotiated = negotiate(_options(case["options"]), case["header"], 100)
    except ValueError:
        got: dict[str, Any] = {"error": True}
    else:
        got = {"none": True} if negotiated is None else {"ok": negotiated.header()}
    assert got == case["result"]


def test_rejects_window_sizes_outside_8_to_15() -> None:
    with pytest.raises(ValueError, match="8 to 15"):
        PerMessageDeflate(server_max_window_bits=16)
    with pytest.raises(ValueError, match="8 to 15"):
        PerMessageDeflate(client_max_window_bits=7)


def test_round_trips_through_the_deflater_and_inflater() -> None:
    deflater = Deflater(15, no_context_takeover=False, threshold=10)
    inflater = Inflater(15, no_context_takeover=False, max_message_size=1 << 20)
    assert deflater.compress(b"short") is None
    for message in (b"x" * 5000, b"y" * 5000, b"x" * 5000):
        compressed = deflater.compress(message)
        assert compressed is not None
        assert not compressed.endswith(b"\x00\x00\xff\xff")
        assert inflater.feed(compressed, True, 0) == message


def test_inflates_frame_by_frame_and_counts_the_message() -> None:
    deflate = zlib.compressobj(6, zlib.DEFLATED, -15)
    payload = (deflate.compress(b"q" * 4000) + deflate.flush(zlib.Z_SYNC_FLUSH))[:-4]
    inflater = Inflater(15, no_context_takeover=True, max_message_size=4000)
    first = inflater.feed(payload[:5], False, 0)
    assert first + inflater.feed(payload[5:], True, len(first)) == b"q" * 4000
    with pytest.raises(ProtocolError) as error:
        Inflater(15, False, 3999).feed(payload, True, 0)
    assert error.value.code == 1009


def test_data_that_does_not_inflate_is_a_1007() -> None:
    with pytest.raises(ProtocolError) as error:
        Inflater(15, False, 1000).feed(b"\xff\xff\xff\xff", True, 0)
    assert error.value.code == 1007
