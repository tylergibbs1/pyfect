"""Ports of Effect's ``effect/test/eventlog/EventLogMessage.test.ts``.
Each test's docstring is the Effect test title.

The "wire format" frames are the hex Effect's test pins.
"""

import re
from typing import TypedDict

import pyfect as fx
from pyfect import schema as S
from pyfect.encoding import schema_binary
from pyfect.eventlog import event_log_message as M
from pyfect.eventlog.event_journal import ENTRY_ARRAY_CODEC, Entry, EntryId, RemoteEntry, StoreId

_WIRE_ENTRIES = (
    "3020a8faeec3190301020380ae8dce1b10018f4a1e7b007000800000000000000180a1c68f630161f8899a8c7f03507574",
    "3020a8faeec3190080ae8dce1b10018f4a1e7b017000800000000000000280a1c68f630162f8899a8c7f0644656c657465",
)
_WIRE_CHANGES = (
    "7420023d0093af8fd60c5ea8faeec3190301020380ae8dce1b10018f4a1e7b007000800000000000000180a1c68f630161"
    "f8899a8c7f03507574a2f284a20d020e33015ea8faeec3190080ae8dce1b10018f4a1e7b017000800000000000000280a1c6"
    "8f630162f8899a8c7f0644656c6574650210"
)
_WIRE_WRITE = (
    "69209885f1a8260573746f726598af90d6374f023000a5efbd980306010203e0d5e1b90320018f4a1e7b0070008000000000"
    "00000190e4f8b10c02619fa1c3f10f065075741c010020018f4a1e7b017000800000000000000202620c44656c657465f8ef"
    "c0827a02706b"
)

_ENTRIES = (
    Entry(
        id=EntryId(bytes.fromhex("018f4a1e7b0070008000000000000001")),
        event="Put",
        primary_key="a",
        payload=bytes([1, 2, 3]),
    ),
    Entry(
        id=EntryId(bytes.fromhex("018f4a1e7b0170008000000000000002")),
        event="Delete",
        primary_key="b",
        payload=b"",
    ),
)


def test_splits_empty_data() -> None:
    """splits empty data into one chunk"""
    assert M.ChunkedMessage.split(1, b"") == [M.ChunkedMessage(id=1, part=(0, 1), data=b"")]


def test_ignores_duplicate_chunks() -> None:
    """ignores duplicate chunks when joining"""
    state = M.ChunkedMessage.initial_join_state()
    chunk = M.ChunkedMessage(id=1, part=(0, 2), data=b"\x01")
    assert M.ChunkedMessage.join(state, chunk) is None
    assert M.ChunkedMessage.join(state, chunk) is None
    last = M.ChunkedMessage(id=1, part=(1, 2), data=b"\x02")
    assert M.ChunkedMessage.join(state, last) == b"\x01\x02"


def test_entry_frames() -> None:
    """entry frames"""
    frames = tuple(bytes.fromhex(h) for h in _WIRE_ENTRIES)
    decoded = fx.run_blocking(S.decode_effect(ENTRY_ARRAY_CODEC)(frames).or_die())
    assert decoded == _ENTRIES
    assert isinstance(decoded[0], Entry)
    assert fx.run_blocking(S.encode_effect(ENTRY_ARRAY_CODEC)(_ENTRIES).or_die()) == frames


def test_changes_frame_round_trip() -> None:
    """unencrypted changes frame"""
    remote = (
        RemoteEntry(remote_sequence=7, entry=_ENTRIES[0]),
        RemoteEntry(remote_sequence=8, entry=_ENTRIES[1]),
    )
    decoded = fx.run_blocking(M.decode_changes_unencrypted(bytes.fromhex(_WIRE_CHANGES)).or_die())
    assert decoded == remote
    assert isinstance(decoded[0], RemoteEntry)
    assert isinstance(decoded[0].entry, Entry)
    assert fx.run_blocking(M.encode_changes_unencrypted(remote).or_die()).hex() == _WIRE_CHANGES


def test_write_frame_round_trip() -> None:
    """unencrypted write frame"""
    request = M.WriteEntriesUnencrypted(
        public_key="pk", store_id=StoreId("store"), entries=_ENTRIES
    )
    decoded = fx.run_blocking(M.WriteEntriesUnencrypted.decode(bytes.fromhex(_WIRE_WRITE)).or_die())
    assert decoded == request
    assert isinstance(decoded.entries[0], Entry)
    assert fx.run_blocking(request.encoded.or_die()).hex() == _WIRE_WRITE


def _missing_keys(error: Exception) -> list[str]:
    return sorted(re.findall(r"Missing key\n\s+at (.+)", str(error)))


class _Empty(TypedDict):
    pass


def test_decoders_forward_parse_options() -> None:
    """decoders forward parse options"""
    empty = S.Struct(_Empty)
    empty_struct = S.encode_sync(schema_binary.to_codec(empty))({})
    empty_entries = S.encode_sync(schema_binary.to_codec(S.Array(empty)))(({},))
    write = fx.run_blocking(
        M.WriteEntriesUnencrypted.decode(empty_struct, errors="all").flip().or_die()
    )
    assert _missing_keys(write) == ['["entries"]', '["publicKey"]', '["storeId"]']
    changes = fx.run_blocking(
        M.decode_changes_unencrypted(empty_entries, errors="all").flip().or_die()
    )
    assert _missing_keys(changes) == ['[0]["entry"]', '[0]["remoteSequence"]']
