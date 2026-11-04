"""Ports of Effect's ``sql-mssql/test/Binary.test.ts``.

Each test's docstring is the Effect test title. Effect's mocked tedious
``Connection`` is ``_mssql_fake`` with ``respond``: a ``MERGE`` answers the
entry ids it has not seen, ``SELECT MAX(last_sequence)`` answers null, any
other ``SELECT`` answers its parameters as ``value`` rows.

Adapted: an ``EntryId`` is ``bytes``, so Node's ``Buffer`` and
``Uint8Array`` are a ``bytes`` and a ``bytes`` made from a ``bytearray``,
equal but not the same object.
"""

from collections.abc import Sequence
from typing import Any

import pytest

pytest.importorskip("pytds")

import pyfect as fx
from pyfect import testing
from pyfect.eventlog import sql_event_log_server_encrypted as SqlServer
from pyfect.eventlog.event_journal import EntryId, StoreId
from pyfect.eventlog.event_log_encryption import EncryptedBatch, layer_subtle
from pyfect.reactivity import layer as reactivity_layer
from pyfect.sql import SqlClient, mssql
from pyfect.sql.mssql import TYPES
from pyfect.sql.mssql._driver import Rows, TypedValue

from . import _mssql_fake


def _mock_connection(fake: _mssql_fake.Fake) -> None:
    entry_ids: set[bytes] = set()

    def respond(sql: str, params: Sequence[TypedValue]) -> Rows:
        query = sql.lstrip()
        if query.startswith("MERGE"):
            rows: Rows = []
            for param in params:
                value = param.value
                if not isinstance(value, bytes) or value in entry_ids:
                    continue
                entry_ids.add(value)
                rows.append([("entry_id", value)])
            return rows
        if not query.startswith("SELECT"):
            return []
        if query.startswith("SELECT MAX(last_sequence)"):
            return [[("last_sequence", None)]]
        return [[("value", param.value)] for param in params]

    fake.respond = respond


def _client() -> fx.Effect[mssql.MssqlClientService, Any, Any]:
    return mssql.make(
        mssql.MssqlClientConfig(server="mock.invalid", min_connections=0, max_connections=1)
    )


@testing.live
def test_binds_an_interpolated_bytes_as_var_binary(monkeypatch: pytest.MonkeyPatch):
    """binds an interpolated Uint8Array as VarBinary"""
    fake = _mssql_fake.install(monkeypatch)
    _mock_connection(fake)

    def body():
        client = yield from _client()
        rows = yield from client("SELECT {} AS value", bytes([0, 128, 255]))
        value = rows[0]["value"]
        assert isinstance(value, bytes)
        assert list(value) == [0, 128, 255]
        [param] = fake.connections[0].params[-1]
        assert param.type == TYPES.VarBinary

    yield from fx.scoped(fx.gen(body)).pipe(fx.provide(reactivity_layer))


@testing.live
@pytest.mark.parametrize(
    ("ids", "expected"),
    [
        pytest.param(
            [b"\xff" * 16, b"\xfe" * 16], [0xFF, 0xFE], id="preserves distinct Buffer entry IDs"
        ),
        pytest.param(
            [b"\xff" * 16, bytes(bytearray([0xFF] * 16))],
            [0xFF],
            id="deduplicates the same entry ID across Buffer and Uint8Array",
        ),
    ],
)
def test_writes_entry_ids(monkeypatch: pytest.MonkeyPatch, ids: list[bytes], expected: list[int]):
    """preserves distinct Buffer entry IDs / deduplicates the same entry ID across Buffer and
    Uint8Array"""
    fake = _mssql_fake.install(monkeypatch)
    _mock_connection(fake)

    def body():
        client = yield from _client()
        storage = yield from SqlServer.make_storage().pipe(fx.provide_service(SqlClient, client))
        written = yield from storage.write(
            "public-key",
            StoreId("store-a"),
            [
                EncryptedBatch(
                    entry_ids=(EntryId(entry_id),), iv=bytes(12), encrypted_batch=bytes([index])
                )
                for index, entry_id in enumerate(ids)
            ],
        )
        assert [list(i) for batch in written for i in batch.entry_ids] == [
            [byte] * 16 for byte in expected
        ]

    yield from fx.scoped(fx.gen(body)).pipe(
        fx.provide(fx.layer.merge(reactivity_layer, layer_subtle))
    )
