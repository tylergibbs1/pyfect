"""Ports of the compaction titles of Effect's
``effect/test/eventlog/EventLogServerEncrypted.test.ts``: the encrypted
server's compaction RPCs and policy, over the memory storage and
``rpc.test.make_client``. Each test's docstring is the Effect test title.

The server never decrypts, so a batch only needs its ids and a fresh iv.
"""

import os
from collections.abc import Generator, Sequence
from typing import Any

from hypothesis import strategies as st

import pyfect as fx
from pyfect import logger, testing
from pyfect.context import Context
from pyfect.eventlog import event_journal as J
from pyfect.eventlog import event_log as L
from pyfect.eventlog import event_log_message as M
from pyfect.eventlog import event_log_server_encrypted as Server
from pyfect.eventlog._identity_derivation import make_get_identity_root_secret_material
from pyfect.eventlog.event_journal import EntryId, StoreId
from pyfect.eventlog.event_log_encryption import EncryptedBatch, EncryptedRemoteBatch, layer_subtle
from pyfect.eventlog.event_log_session_auth import SessionAuthPayload, sign_session_auth_payload
from pyfect.redacted import value as reveal
from pyfect.rpc import test as rpc_test

store_id = StoreId("store-a")
HOUR = "1 hour"
# Long enough for a write's storage hour to pass the default 24 hour lag.
PAST_LAG = "26 hours"
get_material = make_get_identity_root_secret_material()

type EntryIds = Sequence[EntryId]
type Segments = Sequence[Sequence[EntryIds]]


def make_ids(count: int) -> list[EntryId]:
    return [J.make_entry_id_unsafe() for _ in range(count)]


def make_batch(entry_ids: EntryIds) -> EncryptedBatch:
    return EncryptedBatch(
        entry_ids=tuple(entry_ids), iv=os.urandom(12), encrypted_batch=bytes(len(entry_ids))
    )


def started(result: Any) -> M.CompactionStarted:
    assert isinstance(result, M.CompactionStarted), f"got {result}"
    return result


class Connection:
    """One authenticated connection of the server's identity."""

    def __init__(
        self, client: Server.EventLogEncryptedServerRpcs, hello: M.HelloResponse, public_key: str
    ) -> None:
        self.client = client
        self.hello = hello
        self.scope: M.CompactionScopePayload = {"public_key": public_key, "store_id": store_id}

    def write(self, *batches: EntryIds) -> fx.Effect[Sequence[M.WriteAck], Any]:
        request = M.WriteEntries(
            public_key=self.scope["public_key"],
            store_id=store_id,
            batches=tuple(make_batch(b) for b in batches),
        )
        return request.encoded.flat_map(lambda data: self.client.write_single({"data": data}))

    @property
    def status(self) -> fx.Effect[M.CompactionStatus, Any]:
        return self.client.compaction_status(self.scope)

    @property
    def begin(self) -> fx.Effect[M.CompactionBeginResult, Any]:
        return self.client.compaction_begin(self.scope)

    def stage(self, stage_id: str) -> M.CompactionStagePayload:
        return {**self.scope, "stage_id": stage_id}

    def input(self, stage_id: str) -> fx.Stream[Any, Any]:
        return self.client.compaction_input(self.stage(stage_id))

    def abort(self, stage_id: str) -> fx.Effect[None, Any]:
        return self.client.compaction_abort(self.stage(stage_id))

    def commit(self, stage_id: str, result: M.CompactionResult) -> fx.Effect[str, Any]:
        return self.client.compaction_commit({**self.stage(stage_id), "result": result})

    def upload(self, stage_id: str, segments: Segments) -> Generator[Any, Any]:
        for segment, batches in enumerate(segments):
            data = yield from M.encode_compaction_segment([make_batch(b) for b in batches]).or_die()
            for chunk in M.ChunkedMessage.split(segment, data):
                yield from self.client.compaction_part({**self.stage(stage_id), "chunk": chunk})

    def snapshot(self, stage_id: str, segments: Segments) -> Generator[Any, Any, str]:
        yield from self.upload(stage_id, segments)
        return (yield from self.commit(stage_id, M.CompactionSnapshot(segment_count=len(segments))))

    def changes(self, start_sequence: int) -> Generator[Any, Any, fx.Effect[Any, Any]]:
        """Subscribes to changes; an effect that takes the next frame's
        batches."""
        queue = yield from self.client.changes(
            {**self.scope, "start_sequence": start_sequence}, as_queue=True
        )

        def decode(frame: Any) -> fx.Effect[tuple[EncryptedRemoteBatch, ...]]:
            assert isinstance(frame, M.SingleMessage), "expected a single frame"
            return M.decode_changes_encrypted(frame.data).or_die()

        return queue.take().flat_map(decode)


class Server_:
    def __init__(self, storage: Server.StorageService, context: Context[Any], identity: Any):
        self.storage = storage
        self.context = context
        self.identity: L.IdentityService = identity
        self.public_key: str = identity.public_key

    @property
    def compaction(self) -> Server.StorageCompaction:
        assert self.storage.compaction is not None, "Storage does not provide compaction"
        return self.storage.compaction

    def connect(self) -> Generator[Any, Any, Connection]:
        client = yield from rpc_test.make_client(Server.EventLogEncryptedServerRpcs).pipe(
            fx.provide(self.context)
        )
        hello = yield from client.hello()
        material = yield from get_material(self.identity)
        signature = yield from sign_session_auth_payload(
            SessionAuthPayload(
                remote_id=hello.remote_id,
                challenge=hello.challenge,
                public_key=self.public_key,
                signing_public_key=material.signing_public_key,
            ),
            reveal(material.signing_private_key),
        )
        yield from client.authenticate(
            M.Authenticate(
                public_key=self.public_key,
                signing_public_key=material.signing_public_key,
                signature=signature,
                algorithm="Ed25519",
            )
        )
        return Connection(client, hello, self.public_key)

    def active_id(self) -> fx.Effect[str]:
        return self.compaction.history(self.public_key, store_id).map(
            lambda history: next(a for a in history if a.active).activation_id
        )

    def rollback(self) -> Generator[Any, Any, str]:
        active = yield from self.active_id()
        return (yield from self.compaction.rollback(self.public_key, store_id, active))


def make_server(compaction: Server.CompactionOptions) -> Generator[Any, Any, Server_]:
    context = yield from Server.layer_rpc_handlers.pipe(
        fx.layer.provide_merge(Server.layer_storage_memory_with(compaction))
    ).build()
    identity = yield from L.make_identity.pipe(fx.provide(layer_subtle))
    return Server_(context.get(Server.Storage), context, identity)


def with_snapshot(
    compaction: Server.CompactionOptions,
) -> Generator[Any, Any, tuple[Server_, Connection, list[EntryId], str]]:
    """Writes A = [e0, e1]@0, [e2, e3]@2, [e4]@4, [e5]@5, then two hours
    later B = [e6, e7, e8, e9]@6, and commits a snapshot keeping e1 and e3
    once A has passed the lag but B has not, so its base is 5."""
    server = yield from make_server(compaction)
    conn = yield from server.connect()
    ids = make_ids(10)
    yield from conn.write([ids[0], ids[1]], [ids[2], ids[3]], [ids[4]], [ids[5]])
    yield from testing.adjust("2 hours")
    yield from conn.write(ids[6:])
    yield from testing.adjust("23 hours")
    stage = started((yield from conn.begin))
    committed = yield from conn.snapshot(stage.stage_id, [[[ids[1]], [ids[3]]]])
    return server, conn, ids, committed


def _structured_logs() -> tuple[list[logger.StructuredLog], fx.Layer[Any]]:
    logs: list[logger.StructuredLog] = []
    return logs, logger.layer([logger.format_structured.map(logs.append)])


_TAGS = {
    M.CompactionStarted: "Started",
    M.CompactionBusy: "Busy",
    M.CompactionNotWanted: "NotWanted",
}


def contains_subset(annotations: dict[str, object], subset: dict[str, object]) -> bool:
    return all(key in annotations and annotations[key] == value for key, value in subset.items())


@testing.effect
def test_memory_storage_fails_unless_grace_is_longer():
    """memory storage fails to start unless grace is longer than the lag and the stage TTL"""

    def start(options: Server.CompactionOptions) -> fx.Effect[fx.Exit[Any, Any]]:
        return fx.scoped(Server.layer_storage_memory_with(options).build()).exit()

    exits = [
        (yield from start({"grace": "24 hours", "lag": "24 hours"})),
        (yield from start({"grace": "10 minutes", "stage_ttl": "10 minutes", "lag": "1 minute"})),
        (yield from start({"grace": "25 hours", "lag": "24 hours", "stage_ttl": "24 hours"})),
    ]
    assert [isinstance(e, fx.Success) for e in exits] == [False, False, True]


@testing.effect
def test_isolates_pending_segment_pieces():
    """isolates pending segment pieces and aborts by store on the same connection"""
    server = yield from make_server({"threshold_floor": 1})
    conn = yield from server.connect()
    ids = make_ids(2)
    yield from conn.write(ids)
    yield from testing.adjust(PAST_LAG)
    stage_id = started((yield from conn.begin)).stage_id
    data = yield from M.encode_compaction_segment([make_batch([ids[1]])])
    split = len(data) // 2
    other_store = StoreId("store-b")

    def part(store: StoreId, index: int, piece: bytes) -> fx.Effect[None, Any]:
        return conn.client.compaction_part(
            {
                "public_key": server.public_key,
                "store_id": store,
                "stage_id": stage_id,
                "chunk": M.ChunkedMessage(id=0, part=(index, 2), data=piece),
            }
        )

    yield from part(store_id, 0, data[:split])
    # A foreign scope must not join these junk bytes or clear A's pending
    # piece. The server may reject the unknown stage now or when it
    # assembles the segment.
    yield from part(other_store, 1, bytes([255])).exit()
    yield from conn.client.compaction_abort(
        {"public_key": server.public_key, "store_id": other_store, "stage_id": stage_id}
    ).exit()
    yield from part(store_id, 1, data[split:])
    assert (yield from conn.commit(stage_id, M.CompactionSnapshot(segment_count=1))) == "Committed"


@testing.effect
def test_logs_snapshot_commit_counts_and_activation_ids():
    """logs snapshot commit counts and the committed and rollback activation ids"""
    logs, log_layer = _structured_logs()

    def body():
        server = yield from make_server({"threshold_floor": 1})
        conn = yield from server.connect()
        ids = make_ids(3)
        yield from conn.write(ids)
        yield from testing.adjust(PAST_LAG)
        stage_id = started((yield from conn.begin)).stage_id
        assert (yield from conn.snapshot(stage_id, [[[ids[1]]]])) == "Committed"
        active = yield from server.active_id()
        rollback_id = yield from server.compaction.rollback(server.public_key, store_id, active)
        commit_log = next(log for log in logs if log["annotations"].get("activationId") == active)
        rollback_log = next(
            log for log in logs if log["annotations"].get("activationId") == rollback_id
        )
        assert commit_log["level"] == "INFO"
        assert contains_subset(
            commit_log["annotations"],
            {
                "publicKey": server.public_key,
                "storeId": store_id,
                "keptCount": 1,
                "through": 2,
                "activationId": active,
            },
        )
        assert rollback_log["level"] == "INFO"
        assert contains_subset(
            rollback_log["annotations"],
            {
                "publicKey": server.public_key,
                "storeId": store_id,
                "activationId": rollback_id,
                "withdrawnActivationId": active,
                "withdrawnBase": 2,
                "withdrawnKeptCount": 1,
                "base": -1,
                "keptCount": None,
            },
        )

    yield from fx.gen(body).pipe(fx.provide(log_layer))


@testing.effect
def test_loses_the_compare_and_swap_after_a_rollback():
    """loses the compare-and-swap after a rollback and frees busy on abort"""
    server, conn, ids, committed = yield from with_snapshot({"threshold_floor": 1})
    # B passes the lag, so the next input is the snapshot plus B.
    yield from testing.adjust("2 hours")
    second = started((yield from conn.begin))
    busy = yield from conn.begin
    yield from conn.abort(second.stage_id)
    third = started((yield from conn.begin))
    yield from server.rollback()
    lost = yield from conn.snapshot(third.stage_id, [[[ids[7]]]])
    assert conn.hello.compaction is True
    assert committed == "Committed"
    assert isinstance(busy, M.CompactionBusy)
    assert lost == "Superseded"


@testing.effect
def test_fails_input_with_not_found_once_the_pin_was_pruned():
    """fails Input with NotFound once the stage's pin was pruned"""
    server, conn, ids, _ = yield from with_snapshot(
        {"grace": "25 hours", "lag": "24 hours", "stage_ttl": "24 hours", "threshold_floor": 1}
    )

    def outcome(stage_id: str) -> fx.Effect[str]:
        return (
            conn.input(stage_id)
            .run_drain()
            .match(on_failure=lambda e: e.code, on_success=lambda _: "ok")
        )

    yield from testing.adjust("2 hours")
    stage_id = started((yield from conn.begin)).stage_id
    yield from server.rollback()
    before_prune = yield from outcome(stage_id)
    # A Part keeps the stage open past the withdrawn snapshot's grace.
    yield from testing.adjust("23 hours")
    yield from conn.upload(stage_id, [[[ids[1]]]])
    yield from testing.adjust("3 hours")
    after_prune = yield from outcome(stage_id)
    assert (before_prune, after_prune) == ("ok", "NotFound")


@testing.effect
def test_rejects_a_commit_whose_kept_ids_are_not_a_subsequence():
    """rejects a commit whose kept ids are not a non-empty, in-order subsequence of the pinned input"""  # noqa: E501
    server = yield from make_server({"threshold_floor": 1})
    conn = yield from server.connect()
    ids = make_ids(7)
    yield from conn.write([ids[0], ids[1]], [ids[2], ids[3]], [ids[4]], [ids[5]])
    yield from testing.adjust(PAST_LAG)
    # Stored after the pin's H.
    yield from conn.write([ids[6]])
    cases: list[Segments] = [
        [[[ids[1]], [ids[6]]]],
        [[[ids[1]], [ids[1], ids[3]]]],
        [[[ids[1], make_ids(1)[0]]]],
        [[[ids[3]], [ids[1]]]],
        [],
    ]
    rejections: list[str] = []
    for segments in cases:
        stage_id = started((yield from conn.begin)).stage_id
        error = yield from fx.gen(lambda s=segments, i=stage_id: conn.snapshot(i, s)).flip()
        yield from conn.abort(stage_id)
        rejections.append(error.code)
    assert rejections == ["InvalidRequest"] * 5


@testing.effect
def test_accepts_kept_ids_matched_to_a_later_occurrence():
    """accepts kept ids matched to a later occurrence of a repeated input id"""
    server = yield from make_server({"threshold_floor": 1})
    conn = yield from server.connect()
    a, b, c = make_ids(3)
    # A partly known batch stores a again, so the input is a@0, b@1, a@2, c@3.
    yield from conn.write([a, b])
    yield from conn.write([a, c])
    yield from testing.adjust(PAST_LAG)
    stage_id = started((yield from conn.begin)).stage_id
    committed = yield from conn.snapshot(stage_id, [[[b], [a], [c]]])
    served = yield from server.storage.changes(server.public_key, store_id, 0).take(3).run_collect()
    sequence_of_a = next(batch.sequence for batch in served if batch.entry_ids[0] == a)
    assert committed == "Committed"
    assert sequence_of_a >= 2


@testing.effect
def test_answers_begin_with_not_wanted_and_backs_off():
    """answers Begin with NotWanted below the threshold and logs no-ops while backing off multiplicatively"""  # noqa: E501
    logs, log_layer = _structured_logs()

    def body():
        server = yield from make_server({"threshold_floor": 4})
        conn = yield from server.connect()
        # Commits NoOp for any stage it opens.
        no_ops: list[str] = []

        def begin() -> Generator[Any, Any, str]:
            result = yield from conn.begin
            if isinstance(result, M.CompactionStarted):
                assert (yield from conn.commit(result.stage_id, M.CompactionNoOp())) == "Committed"
                no_ops.append(result.stage_id)
            return _TAGS[type(result)]

        def write_past_lag() -> Generator[Any, Any, str]:
            yield from conn.write(make_ids(4))
            yield from testing.adjust(PAST_LAG)
            return (yield from begin())

        yield from conn.write(make_ids(6))
        results = [(yield from begin())]
        yield from testing.adjust(PAST_LAG)
        # H = 5, then 9 (4 past the first no-op), 13 and 17 (8 past the second).
        results.append((yield from begin()))
        results.append((yield from begin()))
        results.append((yield from write_past_lag()))
        results.append((yield from write_past_lag()))
        results.append((yield from write_past_lag()))
        assert results == ["NotWanted", "Started", "NotWanted", "Started", "NotWanted", "Started"]
        for index, stage_id in enumerate(no_ops):
            stage_logs = [
                log
                for log in logs
                if log["annotations"].get("stageId") == stage_id and log["level"] == "INFO"
            ]
            assert len(stage_logs) == 1, "NoOp commit must emit exactly one audit record per stage"
            assert contains_subset(
                stage_logs[0]["annotations"],
                {
                    "publicKey": server.public_key,
                    "storeId": store_id,
                    "stageId": stage_id,
                    "through": [5, 9, 17][index],
                },
            )

    yield from fx.gen(body).pipe(fx.provide(log_layer))


@testing.effect
def test_keeps_activation_off_live_changes():
    """keeps activation off live changes and omits acks for re-uploads at or below the base"""
    server = yield from make_server({"threshold_floor": 1})
    writer = yield from server.connect()
    reader = yield from server.connect()
    ids = make_ids(8)
    yield from writer.write([ids[0], ids[1]], [ids[2], ids[3]], [ids[4]], [ids[5]])
    yield from testing.adjust(PAST_LAG)
    yield from writer.write([ids[6]])
    next_frame = yield from reader.changes(6)
    caught_up = yield from next_frame
    stage_id = started((yield from writer.begin)).stage_id
    committed = yield from writer.snapshot(stage_id, [[[ids[1]], [ids[3]]]])
    # e0 was dropped and e6 is in the tail.
    acks = yield from writer.write([ids[0]], [ids[6]])
    yield from writer.write([ids[7]])
    live = yield from next_frame

    def summarize(batches: Sequence[EncryptedRemoteBatch]) -> list[tuple[int, list[EntryId]]]:
        return [(batch.sequence, list(batch.entry_ids)) for batch in batches]

    assert summarize(caught_up) == [(6, [ids[6]])]
    assert committed == "Committed"
    assert [(ack.entry_id, ack.sequence) for ack in acks] == [(ids[6], 6)]
    assert summarize(live) == [(7, [ids[7]])]


_input = st.lists(st.lists(st.booleans(), min_size=1, max_size=4), min_size=1, max_size=6)
_batch_sizes = st.lists(st.integers(1, 3), min_size=1, max_size=4)


@testing.effect_prop(input=_input, batch_sizes=_batch_sizes, runs=50)
def test_places_every_snapshot_entry_within_its_bounds(
    input: list[list[bool]], batch_sizes: list[int]
):
    """places every snapshot entry at or after its input sequence and at or below the base, without overlap"""  # noqa: E501

    def body():
        server = yield from make_server({"threshold_floor": 1})
        conn = yield from server.connect()
        batches = [[J.make_entry_id_unsafe() for _ in flags] for flags in input]
        ids = [i for batch in batches for i in batch]
        flags = [f for batch in input for f in batch]
        kept = [i for i, flag in zip(ids, flags, strict=True) if flag]
        if not kept:
            return
        first_sequence = conn.hello.first_sequence or 0
        input_sequence = {i: first_sequence + n for n, i in enumerate(ids)}
        base = first_sequence + len(ids) - 1
        snapshot_batches: list[EntryIds] = []
        i = b = 0
        while i < len(kept):
            size = batch_sizes[b % len(batch_sizes)]
            snapshot_batches.append(kept[i : i + size])
            i += size
            b += 1
        yield from conn.write(*batches)
        yield from testing.adjust(PAST_LAG)
        stage_id = started((yield from conn.begin)).stage_id
        yield from conn.snapshot(stage_id, [snapshot_batches])
        served = yield from (
            server.storage.changes(server.public_key, store_id, first_sequence)
            .take(len(snapshot_batches))
            .run_collect()
        )
        previous_last = first_sequence - 1
        for batch in served:
            assert batch.sequence > previous_last
            for n, entry_id in enumerate(batch.entry_ids):
                assert batch.sequence + n >= input_sequence[entry_id]
                assert batch.sequence + n <= base
            previous_last = batch.sequence + len(batch.entry_ids) - 1
        assert [i for batch in served for i in batch.entry_ids] == kept

    return fx.scoped(fx.gen(body))
