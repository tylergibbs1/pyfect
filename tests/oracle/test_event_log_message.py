"""Ports of Effect's ``effect/test/eventlog/EventLogMessage.test.ts``.
Each test's docstring is the Effect test title.

SchemaBinary is not ported (frames are the schemas' JSON as UTF-8, see
``eventlog._binary``), so "unencrypted changes frame" and "unencrypted
write frame" check the round trip and the decoded classes, not pinned
bytes. Omitted: "entry frames" (it only pins SchemaBinary's bytes of
``Entry.encodeArray``, which has no pyfect counterpart).
"""

import re

import pyfect as fx
from pyfect.eventlog import event_log_message as M
from pyfect.eventlog.event_journal import Entry, EntryId, RemoteEntry, StoreId

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


def test_changes_frame_round_trip() -> None:
    """unencrypted changes frame"""
    remote = (
        RemoteEntry(remote_sequence=7, entry=_ENTRIES[0]),
        RemoteEntry(remote_sequence=8, entry=_ENTRIES[1]),
    )
    data = fx.run_sync(M.encode_changes_unencrypted(remote).or_die())
    decoded = fx.run_sync(M.decode_changes_unencrypted(data).or_die())
    assert decoded == remote
    assert isinstance(decoded[0], RemoteEntry)
    assert isinstance(decoded[0].entry, Entry)


def test_write_frame_round_trip() -> None:
    """unencrypted write frame"""
    request = M.WriteEntriesUnencrypted(
        public_key="pk", store_id=StoreId("store"), entries=_ENTRIES
    )
    encoded = fx.run_sync(request.encoded.or_die())
    decoded = fx.run_sync(M.WriteEntriesUnencrypted.decode(encoded).or_die())
    assert decoded == request
    assert isinstance(decoded.entries[0], Entry)


def _missing_keys(error: Exception) -> list[str]:
    return sorted(re.findall(r"Missing key\n\s+at (.+)", str(error)))


def test_decoders_forward_parse_options() -> None:
    """decoders forward parse options"""
    write = fx.run_sync(M.WriteEntriesUnencrypted.decode(b"{}", errors="all").flip().or_die())
    assert _missing_keys(write) == ['["entries"]', '["public_key"]', '["store_id"]']
    changes = fx.run_sync(M.decode_changes_unencrypted(b"[{}]", errors="all").flip().or_die())
    assert _missing_keys(changes) == ['[0]["entry"]', '[0]["remote_sequence"]']
