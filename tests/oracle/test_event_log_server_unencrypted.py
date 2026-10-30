"""Ports of Effect's ``effect/test/eventlog/EventLogServerUnencryptedRegressionTest.ts``
suite on the memory and SQLite storages (``sql-sqlite-node``'s
``RegressionTest.suite("SQLite", ...)``), and of ``EventLogServerUnencrypted.test.ts``.
Each test's docstring is the Effect test title."""

import itertools
import os
import uuid
from collections.abc import Generator, Sequence
from typing import Any, TypedDict

import pytest

import pyfect as fx
from pyfect import schema as S
from pyfect import testing
from pyfect.context import Context
from pyfect.effect import Effect
from pyfect.eventlog import event as Ev
from pyfect.eventlog import event_group as G
from pyfect.eventlog import event_journal as J
from pyfect.eventlog import event_log as L
from pyfect.eventlog import event_log_message as M
from pyfect.eventlog import event_log_server_unencrypted as U
from pyfect.eventlog import sql_event_log_server_unencrypted as SqlU
from pyfect.eventlog._identity_derivation import make_get_identity_root_secret_material
from pyfect.eventlog.event_journal import Entry, EntryId, StoreId
from pyfect.eventlog.event_log_encryption import layer_subtle
from pyfect.eventlog.event_log_session_auth import SessionAuthPayload, sign_session_auth_payload
from pyfect.reactivity import layer as reactivity_layer
from pyfect.redacted import value as reveal
from pyfect.rpc import test as rpc_test
from pyfect.sql import sqlite
from pyfect.sql.client import SqlClient

from ._postgres import PgServer


class KeyPayload(TypedDict):
    key: str


Set = Ev.make("Set", primary_key=lambda p: p["key"], payload=S.Struct(KeyPayload))
Other = Ev.make("Other", primary_key=lambda p: p["key"], payload=S.Struct(KeyPayload))
group = G.empty.add(Set).add(Other)


def make_entry(msecs: int, key: str, tag: str = "Set") -> Generator[Any, Any, Entry]:
    event = Set if tag == "Set" else Other
    payload = yield from S.encode_effect(event.payload_codec)({"key": key}).or_die()
    return Entry(
        id=J.make_entry_id_unsafe(msecs=msecs), event=tag, primary_key=key, payload=payload
    )


def entries_at(*specs: tuple[int, str] | tuple[int, str, str]) -> Effect[list[Entry]]:
    def make(spec: tuple[int, str] | tuple[int, str, str]) -> Effect[Entry]:
        return fx.gen(lambda: make_entry(spec[0], spec[1], *spec[2:]))

    return fx.for_each(specs, make)


class _AllowAll(U.EventLogServerAuthorizationService):
    def authorize_write(self, **_: Any) -> Effect[None, U.EventLogServerAuthError]:
        return fx.void

    def authorize_read(self, **_: Any) -> Effect[None, U.EventLogServerAuthError]:
        return fx.void

    def authorize_identity(self, **_: Any) -> Effect[None, U.EventLogServerAuthError]:
        return fx.void


class _Identity(U.StoreMappingService):
    def resolve(self, *, public_key: str, store_id: StoreId) -> Effect[StoreId, Any]:
        return fx.succeed(store_id)

    def has_store(self, **_: Any) -> Effect[bool, Any]:
        return fx.succeed(True)


class Client:
    def __init__(self, write: Any, handled: list[dict[str, Any]]) -> None:
        self.write = write
        self.handled = handled


def make_client(name: str) -> Generator[Any, Any, Client]:
    storage = yield from U.Storage()
    registry = yield from L.Registry().pipe(fx.provide(L.layer_registry))
    handled: list[dict[str, Any]] = []

    def record(i: L.HandlerInput[Any]) -> Effect[None]:
        return fx.sync(
            lambda: handled.append(
                {"key": i.entry.primary_key, "conflicts": [c.entry.id_string for c in i.conflicts]}
            )
        )

    for event in (Set, Other):
        registry.register_handler_unsafe(event.tag, L.HandlerItem(event, Context.empty(), record))
    handlers = (
        U.layer_rpc_handlers.pipe(fx.layer.provide(fx.layer.succeed(U.Storage, storage)))
        .pipe(fx.layer.provide(fx.layer.succeed(L.Registry, registry)))
        .pipe(fx.layer.provide(fx.layer.succeed(U.StoreMapping, _Identity())))
        .pipe(fx.layer.provide(fx.layer.succeed(U.EventLogServerAuthorization, _AllowAll())))
    )
    client = yield from rpc_test.make_client(M.EventLogRemoteRpcs).pipe(fx.provide(handlers))
    identity = yield from L.make_identity
    hello = yield from client.hello()
    material = yield from make_get_identity_root_secret_material()(identity)
    signature = yield from sign_session_auth_payload(
        SessionAuthPayload(
            remote_id=hello.remote_id,
            challenge=hello.challenge,
            public_key=identity.public_key,
            signing_public_key=material.signing_public_key,
        ),
        reveal(material.signing_private_key),
    )
    yield from client.authenticate(
        M.Authenticate(
            public_key=identity.public_key,
            signing_public_key=material.signing_public_key,
            signature=signature,
            algorithm="Ed25519",
        )
    )

    def write(entries: Sequence[Entry]) -> Effect[Any, Any]:
        request = M.WriteEntriesUnencrypted(
            public_key=identity.public_key, store_id=StoreId(name), entries=tuple(entries)
        )
        return request.encoded.flat_map(lambda data: client.write_single({"data": data}))

    return Client(write, handled)


_namespaces = itertools.count()


def _sql_storage(client: fx.Layer[SqlClient, Any]) -> fx.Layer[U.Storage, Any]:
    # Own tables: the PostgreSQL server is shared by the session.
    namespace = f"unencrypted_{os.getpid()}_{next(_namespaces)}"
    return (
        SqlU.layer_storage(
            entry_table_prefix=f"effect_events_{namespace}",
            remote_id_table=f"effect_remote_id_{namespace}",
        )
        .pipe(fx.layer.provide(client))
        .pipe(fx.layer.provide(reactivity_layer))
    )


@pytest.fixture
def storage(request: pytest.FixtureRequest) -> fx.Layer[U.Storage, Any]:
    """The memory storage, or the SQL storage on an in-memory SQLite database
    or the session's PostgreSQL server (skipped without one)."""
    match request.param:
        case "memory":
            return U.layer_storage_memory
        case "SQLite":
            return _sql_storage(sqlite.layer(sqlite.SqliteClientConfig(filename=":memory:")))
        case _:
            pytest.importorskip("psycopg")
            from pyfect.sql import pg

            server: PgServer = request.getfixturevalue("pg_server")
            return _sql_storage(pg.layer(pg.PgPoolConfig(url=server.url)))


STORAGES = pytest.mark.parametrize("storage", ["memory", "SQLite", "pg"], indirect=True)


def _run(body: Any, storage: fx.Layer[U.Storage, Any]) -> Effect[Any, Any, Any]:
    return fx.gen(body).pipe(fx.provide(fx.layer.merge(storage, layer_subtle)))


@STORAGES
@testing.effect
def test_full_history_when_batch_omitted(storage: fx.Layer[U.Storage, Any]):
    """returns full at-or-after history when batch is omitted"""

    def body():
        storage = yield from U.Storage()
        store_id = StoreId("history-without-batch")
        older, boundary, other_event, other_key, newer = yield from entries_at(
            (1_000, "key"),
            (2_000, "key"),
            (3_000, "key", "Other"),
            (4_000, "unrelated"),
            (5_000, "key"),
        )
        yield from storage.write(store_id, [older, other_key, boundary, other_event, newer])
        history = yield from storage.entries_after(store_id, boundary)
        assert [r.entry.id_string for r in history] == [
            other_key.id_string,
            boundary.id_string,
            other_event.id_string,
            newer.id_string,
        ]

    yield from _run(body, storage)


@STORAGES
@testing.effect
def test_acknowledges_out_of_order_duplicate(storage: fx.Layer[U.Storage, Any]):
    """acknowledges an out-of-order duplicate without invoking its handler"""

    def body():
        client = yield from make_client("out-of-order")
        older, newer = yield from entries_at((1_000, "older"), (2_000, "newer"))
        yield from client.write([newer])
        yield from client.write([older])
        acknowledged = isinstance((yield from client.write([older]).exit()), fx.Success)
        assert {"acknowledged": acknowledged, "calls": len(client.handled)} == {
            "acknowledged": True,
            "calls": 2,
        }

    yield from _run(body, storage)


@STORAGES
@testing.effect
def test_skips_equal_timestamp_duplicates(storage: fx.Layer[U.Storage, Any]):
    """skips all equal-timestamp duplicates in a retried batch"""

    def body():
        client = yield from make_client("equal-timestamps")
        entries = sorted((yield from entries_at((1_000, "a"), (1_000, "b"))), key=J.entry_order)
        assert entries[0].id_string != entries[1].id_string
        yield from client.write(entries)
        acknowledged = isinstance((yield from client.write(entries).exit()), fx.Success)
        assert {"acknowledged": acknowledged, "calls": len(client.handled)} == {
            "acknowledged": True,
            "calls": 2,
        }

    yield from _run(body, storage)


@STORAGES
@testing.effect
def test_reports_only_newer_same_key_conflicts(storage: fx.Layer[U.Storage, Any]):
    """reports only newer same-key conflicts regardless of storage order"""

    def body():
        x, y, z, v, w = yield from entries_at(
            (1_200, "a"), (2_000, "b"), (2_500, "a"), (1_100, "c"), (1_500, "a")
        )
        results: list[list[dict[str, Any]]] = []
        for index, history in enumerate([[x, y, z], [y, x, z]]):
            client = yield from make_client(f"conflicts-{index}")
            for entry in history:
                yield from client.write([entry])
            client.handled.clear()
            yield from client.write([v, w])
            results.append(client.handled)
        expected: list[dict[str, Any]] = [
            {"key": "c", "conflicts": []},
            {"key": "a", "conflicts": [z.id_string]},
        ]
        assert results == [expected, expected]

    yield from _run(body, storage)


@STORAGES
@testing.effect
def test_ignores_same_key_entries_from_another_event(storage: fx.Layer[U.Storage, Any]):
    """ignores same-key entries from a different event"""

    def body():
        client = yield from make_client("different-event")
        stored_other, stored_set, incoming_set, incoming_other = yield from entries_at(
            (2_000, "a", "Other"), (3_000, "a"), (1_000, "a"), (1_500, "a", "Other")
        )
        yield from client.write([stored_other])
        yield from client.write([stored_set])
        client.handled.clear()
        yield from client.write([incoming_set, incoming_other])
        assert client.handled == [
            {"key": "a", "conflicts": [stored_set.id_string]},
            {"key": "a", "conflicts": [stored_other.id_string]},
        ]

    yield from _run(body, storage)


@STORAGES
@testing.effect
def test_equal_timestamp_conflicts_only_for_greater_ids(storage: fx.Layer[U.Storage, Any]):
    """reports equal-timestamp conflicts only for stored entries with a greater id"""

    def body():
        lower, stored, higher = sorted(
            (yield from entries_at((1_000, "a"), (1_000, "a"), (1_000, "a"))), key=J.entry_order
        )
        results: list[list[list[str]]] = []
        for index, batch in enumerate([[lower], [higher], [lower, higher]]):
            client = yield from make_client(f"equal-timestamp-conflicts-{index}")
            yield from client.write([stored])
            client.handled.clear()
            yield from client.write(batch)
            results.append([h["conflicts"] for h in client.handled])
        # ``stored`` has the same timestamp as ``higher`` but a lower id, so it
        # never conflicts with ``higher``, whatever else is in the batch.
        assert results == [[[stored.id_string]], [[]], [[stored.id_string], []]]

    yield from _run(body, storage)


@STORAGES
@testing.effect
def test_lowest_id_applies_to_every_lookup(storage: fx.Layer[U.Storage, Any]):
    """applies the batch's lowest id to every lookup in a large batch"""

    def body():
        client = yield from make_client("large-batch")
        entries = sorted((yield from entries_at(*[(1_000, "x")] * 252)), key=J.entry_order)

        # ``stored`` sorts between the batch's first and last entries and only
        # shares a key with the batch's second entry, so the history must
        # start from the batch's lowest id.
        def with_key_b(e: Entry) -> Entry:
            return Entry(id=EntryId(e.id), event=e.event, primary_key="b", payload=e.payload)

        second = with_key_b(entries[1])
        stored = with_key_b(entries[2])
        yield from client.write([stored])
        client.handled.clear()
        yield from client.write([entries[0], second, *entries[3:]])
        assert client.handled[1] == {"key": "b", "conflicts": [stored.id_string]}

    yield from _run(body, storage)


@STORAGES
@testing.effect
def test_matches_long_primary_keys_exactly(storage: fx.Layer[U.Storage, Any]):
    """matches long primary keys exactly"""

    def body():
        client = yield from make_client("long-keys")
        prefix = "".join(str(uuid.uuid4()) for _ in range(125))
        stored, first, second = yield from entries_at(
            (2_000, f"{prefix}a"), (1_000, f"{prefix}a"), (1_500, f"{prefix}b")
        )
        yield from client.write([stored])
        client.handled.clear()
        yield from client.write([first, second])
        assert [h["conflicts"] for h in client.handled] == [[stored.id_string], []]

    yield from _run(body, storage)


@STORAGES
@testing.effect
def test_skips_stored_duplicate_in_mixed_batch(storage: fx.Layer[U.Storage, Any]):
    """skips a stored duplicate inside a mixed batch and persists the rest"""

    def body():
        client = yield from make_client("mixed-duplicate")
        stored, before, after, oldest = yield from entries_at(
            (2_000, "a"), (1_000, "a"), (2_500, "a"), (500, "a")
        )
        yield from client.write([stored])
        client.handled.clear()
        yield from client.write([before, stored, after])
        yield from client.write([oldest])
        # Conflicts are reported in id order, not upload order.
        assert client.handled == [
            {"key": "a", "conflicts": [stored.id_string]},
            {"key": "a", "conflicts": []},
            {"key": "a", "conflicts": [before.id_string, stored.id_string, after.id_string]},
        ]

    yield from _run(body, storage)


@STORAGES
@testing.effect
def test_no_conflicts_within_a_batch(storage: fx.Layer[U.Storage, Any]):
    """does not report conflicts between entries of the same batch"""

    def body():
        client = yield from make_client("same-batch")
        entries = yield from entries_at((2_000, "a"), (1_000, "a"), (1_000, "a"))
        yield from client.write(entries)
        assert [h["conflicts"] for h in client.handled] == [[], [], []]

    yield from _run(body, storage)


class ReproPayload(TypedDict):
    key: str
    value: int


ReproEvent = Ev.make("ReproEvent", primary_key=lambda p: p["key"], payload=S.Struct(ReproPayload))
ReproGroup = G.empty.add(ReproEvent)
OpaqueReproEvent = Ev.make(
    "ReproEvent", primary_key=lambda p: p["key"], payload=S.Struct(KeyPayload)
)
repro_store = StoreId("repro-store")


def _authenticate(identity: L.IdentityService, hello: M.HelloResponse):
    material = yield from make_get_identity_root_secret_material()(identity)
    signature = yield from sign_session_auth_payload(
        SessionAuthPayload(
            remote_id=hello.remote_id,
            challenge=hello.challenge,
            public_key=identity.public_key,
            signing_public_key=material.signing_public_key,
        ),
        reveal(material.signing_private_key),
    )
    return M.Authenticate(
        public_key=identity.public_key,
        signing_public_key=material.signing_public_key,
        signature=signature,
        algorithm="Ed25519",
    )


def _auth_client(
    storage: U.StorageService,
    authorization: U.EventLogServerAuthorizationService,
    registry: Any = None,
) -> Effect[M.EventLogRemoteRpcs, Any, Any]:
    registry_layer = (
        fx.layer.succeed(L.Registry, registry) if registry is not None else L.layer_registry
    )
    handlers = (
        U.layer_rpc_handlers.pipe(fx.layer.provide(fx.layer.succeed(U.Storage, storage)))
        .pipe(fx.layer.provide(registry_layer))
        .pipe(fx.layer.provide(fx.layer.succeed(U.StoreMapping, _Identity())))
        .pipe(fx.layer.provide(fx.layer.succeed(U.EventLogServerAuthorization, authorization)))
    )
    return rpc_test.make_client(M.EventLogRemoteRpcs).pipe(fx.provide(handlers))


@testing.effect
def test_indexes_conflicts_from_sliced_history():
    """indexes conflicts from the sliced history"""

    def make(msecs: int, key: str, value: int) -> Generator[Any, Any, Entry]:
        payload = yield from S.encode_effect(ReproEvent.payload_codec)(
            {"key": key, "value": value}
        ).or_die()
        return Entry(
            id=J.make_entry_id_unsafe(msecs=msecs),
            event="ReproEvent",
            primary_key=key,
            payload=payload,
        )

    def body():
        origin_a = yield from make(1_000, "other-origin", 10)
        old_same_key = yield from make(2_000, "key", 20)
        origin_b = yield from make(3_000, "key", 30)
        newer_other_key = yield from make(4_000, "other", 40)
        newer_same_key = yield from make(5_000, "key", 50)
        storage = yield from U.make_storage_memory
        yield from storage.write(repro_store, [old_same_key, newer_other_key, newer_same_key])
        registry = yield from L.Registry().pipe(fx.provide(L.layer_registry))
        seen: dict[int, list[Entry]] = {}

        def handle(i: L.HandlerInput[Any]) -> Effect[None]:
            return fx.sync(
                lambda: seen.__setitem__(i.payload["value"], [c.entry for c in i.conflicts])
            )

        registry.register_handler_unsafe(
            "ReproEvent", L.HandlerItem(ReproEvent, Context.empty(), handle)
        )
        client = yield from _auth_client(storage, _AllowAll(), registry)
        identity = yield from L.make_identity
        hello = yield from client.hello()
        yield from client.authenticate((yield from _authenticate(identity, hello)))
        data = yield from M.WriteEntriesUnencrypted(
            public_key=identity.public_key, store_id=repro_store, entries=(origin_a, origin_b)
        ).encoded
        yield from client.write_single({"data": data})
        assert [e.id_string for e in seen[10]] == []
        assert [e.id_string for e in seen[30]] == [newer_same_key.id_string]

    yield from fx.gen(body).pipe(fx.provide(layer_subtle))


@testing.effect
def test_compact_backlog_keeps_forwarded_entries_in_order():
    """compactBacklog keeps forwarded entries in batch order"""

    def make(key: str, value: int | None = None) -> Generator[Any, Any, Entry]:
        payload = yield from (
            S.encode_effect(OpaqueReproEvent.payload_codec)({"key": key})
            if value is None
            else S.encode_effect(ReproEvent.payload_codec)({"key": key, "value": value})
        ).or_die()
        return Entry(
            id=J.make_entry_id_unsafe(), event="ReproEvent", primary_key=key, payload=payload
        )

    # The opaque entry lacks ``value``, so the compactor cannot decode it.
    entries = [
        (yield from make("a", 0)),
        (yield from make("a")),
        (yield from make("b", 2)),
        (yield from make("a", 3)),
    ]
    remote_entries = [J.RemoteEntry(remote_sequence=i, entry=e) for i, e in enumerate(entries)]
    compaction = L.group_compaction(
        ReproGroup, lambda c: fx.for_each(c.entries, c.forward).as_void()
    )

    def body():
        registry = yield from L.Registry()
        return (yield from U.compact_backlog(remote_entries, registry.compactors))

    compacted = yield from fx.gen(body).pipe(
        fx.provide(compaction.pipe(fx.layer.provide_merge(L.layer_registry)))
    )

    def fields(r: J.RemoteEntry) -> tuple[int, str, bytes]:
        return (r.remote_sequence, r.entry.id_string, r.entry.payload)

    assert [fields(r) for r in compacted] == [fields(r) for r in remote_entries]


def _large_group(fallback: bool):
    count = 150_000
    remote_entries = [
        J.RemoteEntry(
            remote_sequence=index + 1,
            entry=Entry(
                id=J.make_entry_id_unsafe(msecs=index),
                event="ReproEvent",
                primary_key="large-group",
                payload=b"",
            ),
        )
        for index in range(count)
    ]

    def compact(entries: Sequence[Entry], write: Any) -> Effect[None]:
        def run():
            for entry in entries[0 if fallback else 1 :]:
                yield from write(entry, None)
            # More outputs than inputs cannot be projected onto remote sequences.
            if fallback:
                yield from write(entries[0], None)

        return fx.gen(run)

    def body():
        registry = yield from L.Registry()
        yield from registry.register_compaction(["ReproEvent"], compact)
        compacted = yield from U.compact_backlog(remote_entries, registry.compactors)
        assert len(compacted) == (count if fallback else count - 1)
        mismatches = 0
        for index, r in enumerate(compacted):
            want_entry = remote_entries[index if fallback else index + 1].entry
            want_sequence = count if not fallback and index == len(compacted) - 1 else index + 1
            if r.entry is not want_entry or r.remote_sequence != want_sequence:
                mismatches += 1
        assert mismatches == 0

    return fx.scoped(fx.gen(body)).pipe(fx.provide(L.layer_registry))


@testing.effect
def test_compact_backlog_large_group_projection():
    """compactBacklog handles large groups with projection"""
    yield from _large_group(False)


@testing.effect
def test_compact_backlog_large_group_fallback():
    """compactBacklog handles large groups with fallback"""
    yield from _large_group(True)


def _recording_storage(fail_first: bool = False):
    inner = yield from U.make_storage_memory
    calls = [0]
    original = inner.get_or_create_session_auth_binding

    def binding(public_key: str, signing_public_key: bytes) -> Effect[bytes]:
        def run() -> Effect[bytes]:
            calls[0] += 1
            if fail_first and calls[0] == 1:
                return fx.die(RuntimeError("transient storage error"))
            return original(public_key, signing_public_key)

        return fx.suspend(run)

    inner.get_or_create_session_auth_binding = binding
    return inner, calls


class _Policy(_AllowAll):
    def __init__(self) -> None:
        self.allowed = True
        self.calls: list[str] = []

    def authorize_identity(self, **options: Any) -> Effect[None, U.EventLogServerAuthError]:
        public_key: str = options["public_key"]
        self.calls.append(public_key)
        if self.allowed:
            return fx.void
        return fx.fail(
            U.EventLogServerAuthError("Forbidden", public_key, message="Identity denied")
        )


@testing.effect
def test_authenticate_retries_failed_binding_lookup():
    """Authenticate retries a failed binding lookup for the same identity"""

    def body():
        storage, calls = yield from _recording_storage(fail_first=True)
        client = yield from _auth_client(storage, _AllowAll())
        identity = yield from L.make_identity
        hello = yield from client.hello()
        error = yield from client.authenticate((yield from _authenticate(identity, hello))).flip()
        assert isinstance(error, M.EventLogProtocolError)
        assert error.code == "Forbidden"
        assert error.message == "Session auth binding lookup failed"
        assert calls[0] == 1
        retry_hello = yield from client.hello()
        retry = yield from client.authenticate(
            (yield from _authenticate(identity, retry_hello))
        ).exit()
        assert calls[0] == 2
        assert isinstance(retry, fx.Success)

    yield from fx.gen(body).pipe(fx.provide(layer_subtle))


@testing.effect
def test_authenticate_caches_successful_binding():
    """Authenticate caches successful binding lookups for the same identity"""

    def body():
        storage, calls = yield from _recording_storage()
        client = yield from _auth_client(storage, _AllowAll())
        identity = yield from L.make_identity
        for _ in range(2):
            hello = yield from client.hello()
            yield from client.authenticate((yield from _authenticate(identity, hello)))
            assert calls[0] == 1

    yield from fx.gen(body).pipe(fx.provide(layer_subtle))


@testing.effect
def test_authenticate_denies_first_use_identity():
    """Authenticate denies a first-use identity without creating a binding"""

    def body():
        storage, calls = yield from _recording_storage()
        policy = _Policy()
        policy.allowed = False
        client = yield from _auth_client(storage, policy)
        identity = yield from L.make_identity
        hello = yield from client.hello()
        error = yield from client.authenticate((yield from _authenticate(identity, hello))).flip()
        assert isinstance(error, M.EventLogProtocolError)
        assert error.code == "Forbidden"
        assert policy.calls == [identity.public_key]
        assert calls[0] == 0

    yield from fx.gen(body).pipe(fx.provide(layer_subtle))


@testing.effect
def test_authenticate_rechecks_identity_on_cached_binding():
    """Authenticate re-checks identity authorization on a cached binding"""

    def body():
        storage, calls = yield from _recording_storage()
        policy = _Policy()
        client = yield from _auth_client(storage, policy)
        identity = yield from L.make_identity
        hello = yield from client.hello()
        yield from client.authenticate((yield from _authenticate(identity, hello)))
        assert calls[0] == 1
        policy.allowed = False
        retry_hello = yield from client.hello()
        error = yield from client.authenticate(
            (yield from _authenticate(identity, retry_hello))
        ).flip()
        assert isinstance(error, M.EventLogProtocolError)
        assert error.code == "Forbidden"
        assert policy.calls == [identity.public_key, identity.public_key]
        assert calls[0] == 1

    yield from fx.gen(body).pipe(fx.provide(layer_subtle))
