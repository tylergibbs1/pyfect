"""Ports of platform-node's ``test/cluster-integration/Persistence.test.ts``
on the cluster harness (``_cluster_harness``), on SQLite and on the
throwaway PostgreSQL server where Effect uses PostgreSQL and MySQL. Each
test's docstring is the Effect test title, without its backend prefix.

Adapted, with the reason:
- The ``MalformedMessage`` checks: Effect reads the error's name in
  ``Cause.pretty`` text; a defect that crossed the wire is a
  ``DecodedDefect`` here, whose ``ErrorInstance`` carries that name
  (``malformed``).
- "persists a non-JSON Error as a serializable defect": the handler fails
  with a ``RuntimeError`` (Effect's ``new Error``), which the ``Unknown``
  error schema cannot write as JSON.
"""

from __future__ import annotations

import json
from collections.abc import Generator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Never

import pyfect as fx
from pyfect import exit as Exit
from pyfect import schema as S
from pyfect import stream, testing
from pyfect.cause import Cause
from pyfect.cluster.cluster_schema import Persisted, Uninterruptible
from pyfect.cluster.entity import Entity, Request
from pyfect.cluster.entity_id import EntityId
from pyfect.context import Context
from pyfect.latch import Latch
from pyfect.rpc import make as make_rpc
from pyfect.rpc import rpc_schema
from pyfect.schema import DecodedDefect, ErrorInstance
from pyfect.scope import Scope

from ._cluster_harness import ClusterDatabase, MessageCounts, make


class KeyedPayload(S.Class, identifier="ClusterPersistenceKeyedPayload"):
    id: str

    def primary_key(self) -> str:
        return self.id


class ScheduledPayload(S.Class, identifier="ClusterPersistenceScheduledPayload"):
    deliver_at_millis: float
    id: str

    def primary_key(self) -> str:
        return self.id

    def deliver_at(self) -> datetime:
        return datetime.fromtimestamp(self.deliver_at_millis / 1000, UTC)


class PersistenceEntity(
    Entity, type="ClusterIntegrationPersistence", rpc_annotations=Context.make(Persisted, True)
):
    persisted = make_rpc("Persisted", payload=KeyedPayload, success=S.String)
    stored_reply = make_rpc("StoredReply", payload=KeyedPayload, success=S.String)
    uninterruptible = make_rpc("Uninterruptible", payload=KeyedPayload, success=S.String).annotate(
        Uninterruptible, True
    )
    volatile = make_rpc("Volatile", payload=KeyedPayload, success=S.String).annotate(
        Persisted, False
    )
    typed_failure = make_rpc("TypedFailure", payload=KeyedPayload, success=S.Never, error=S.String)
    defect = make_rpc("Defect", payload=KeyedPayload, success=S.Never)
    healthy = make_rpc("Healthy", payload=KeyedPayload, success=S.String)
    unencodable = make_rpc("Unencodable", payload=KeyedPayload, success=S.Unknown)
    non_json_failure = make_rpc(
        "NonJsonFailure", payload=KeyedPayload, success=S.Never, error=S.Unknown
    )
    streamed = make_rpc(
        "Streamed", payload=KeyedPayload, success=rpc_schema.Stream(S.Number, S.Never)
    )
    scheduled = make_rpc("Scheduled", payload=ScheduledPayload, success=S.Number)


@dataclass
class State:
    completed_uninterruptible: int = 0
    completed_volatile: int = 0
    counts: dict[str, int] = field(default_factory=lambda: {})
    healthy_entered: Latch = field(default_factory=Latch)
    healthy_gate: Latch = field(default_factory=Latch)
    scheduled_deliveries: list[float] = field(default_factory=lambda: [])
    stream_terminal_entered: Latch = field(default_factory=Latch)
    stream_terminal_gate: Latch = field(default_factory=Latch)
    stream_third_entered: Latch = field(default_factory=Latch)
    stream_third_gate: Latch = field(default_factory=Latch)
    uninterruptible_entered: Latch = field(default_factory=Latch)
    uninterruptible_gate: Latch = field(default_factory=Latch)
    volatile_entered: Latch = field(default_factory=Latch)
    volatile_gate: Latch = field(default_factory=Latch)


state = State()


def reset_state() -> None:
    vars(state).update(vars(State()))


def increment(tag: str, id: str) -> int:
    key = f"{tag}:{id}"
    state.counts[key] = state.counts.get(key, 0) + 1
    return state.counts[key]


def count(tag: str, id: str) -> int:
    return state.counts.get(f"{tag}:{id}", 0)


def now_millis() -> fx.Effect[float]:
    return fx.clock.now().map(lambda seconds: seconds * 1000)


def malformed(cause: Cause[Any]) -> bool:
    """The cause is a ``MalformedMessage`` defect, read back from storage or
    the wire."""
    return (
        any(
            isinstance(defect, DecodedDefect)
            and isinstance(defect.value, ErrorInstance)
            and defect.value.name == "MalformedMessage"
            for defect in cause.defects
        )
        or "MalformedMessage" in cause.pretty()
    )


def assert_stored_as_defect(request: fx.Effect[Any, Any], tag: str, id: str) -> fx.Effect[None]:
    @fx.gen
    def check():
        for _ in range(2):
            exit = yield from request.exit()
            assert isinstance(exit, Exit.Failure)
            assert malformed(exit.cause)
        assert count(tag, id) == 1

    return check


def _defect(request: Request[KeyedPayload]) -> fx.Effect[Never]:
    return fx.sync(lambda: increment("Defect", request.payload.id)).and_then(
        fx.die(RuntimeError(f"defect:{request.payload.id}"))
    )


def _healthy(request: Request[KeyedPayload]) -> fx.Effect[str]:
    id = request.payload.id

    @fx.gen
    def run():
        increment("Healthy", id)
        if id.endswith("-blocked"):
            state.healthy_entered.open_unsafe()
            yield from state.healthy_gate.wait()
        return f"healthy:{id}"

    return run


def _non_json_failure(request: Request[KeyedPayload]) -> fx.Effect[Never, object]:
    return fx.sync(lambda: increment("NonJsonFailure", request.payload.id)).and_then(
        fx.fail(RuntimeError(f"non-json:{request.payload.id}"))
    )


def _persisted(request: Request[KeyedPayload]) -> fx.Effect[str]:
    def run() -> str:
        increment("Persisted", request.payload.id)
        return f"persisted:{request.payload.id}"

    return fx.sync(run)


def _scheduled(request: Request[ScheduledPayload]) -> fx.Effect[float]:
    @fx.gen
    def run():
        increment("Scheduled", request.payload.id)
        delivered_at = yield from now_millis()
        state.scheduled_deliveries.append(delivered_at)
        return delivered_at

    return run


def _stored_reply(request: Request[KeyedPayload]) -> fx.Effect[str]:
    def run() -> str:
        increment("StoredReply", request.payload.id)
        return f"stored:{request.payload.id}"

    return fx.sync(run)


def _streamed(request: Request[KeyedPayload]) -> stream.Stream[float]:
    id = request.payload.id
    increment("Streamed", id)
    last = request.last_sent_chunk_value
    start = 0 if last is None else int(last) + 1
    values = [0] if id.endswith("-terminal-race") else [0, 1, 2, 3, 4]

    def each(value: int) -> fx.Effect[float]:
        if id.endswith("-restart") and value == 2:
            state.stream_third_entered.open_unsafe()
            return state.stream_third_gate.wait().as_(float(value))
        return fx.succeed(float(value))

    values_stream = stream.from_iterable(values[start:]).map_effect(each).rechunk(1)
    if not id.endswith("-terminal-race"):
        return values_stream
    terminal = stream.from_effect(
        fx.sync(state.stream_terminal_entered.open_unsafe).and_then(
            state.stream_terminal_gate.wait()
        )
    ).drain()
    return values_stream.concat(terminal)


def _typed_failure(request: Request[KeyedPayload]) -> fx.Effect[Never, str]:
    return fx.sync(lambda: increment("TypedFailure", request.payload.id)).and_then(
        fx.fail(f"typed:{request.payload.id}")
    )


def _uninterruptible(request: Request[KeyedPayload]) -> fx.Effect[str]:
    @fx.gen
    def run():
        increment("Uninterruptible", request.payload.id)
        state.uninterruptible_entered.open_unsafe()
        yield from state.uninterruptible_gate.wait()
        state.completed_uninterruptible += 1
        return f"uninterruptible:{request.payload.id}"

    return run


def _unencodable(request: Request[KeyedPayload]) -> fx.Effect[object]:
    def run() -> object:
        increment("Unencodable", request.payload.id)
        return RuntimeError(f"unencodable:{request.payload.id}")

    return fx.sync(run)


def _volatile(request: Request[KeyedPayload]) -> fx.Effect[str]:
    @fx.gen
    def run():
        increment("Volatile", request.payload.id)
        state.volatile_entered.open_unsafe()
        yield from state.volatile_gate.wait()
        state.completed_volatile += 1
        return f"volatile:{request.payload.id}"

    return run


E = PersistenceEntity
persistence_entity_layer = E.to_layer(
    E.handlers()
    .handle(E.defect)(_defect)
    .handle(E.healthy)(_healthy)
    .handle(E.non_json_failure)(_non_json_failure)
    .handle(E.persisted)(_persisted)
    .handle(E.scheduled)(_scheduled)
    .handle(E.stored_reply)(_stored_reply)
    .handle(E.streamed)(_streamed)
    .handle(E.typed_failure)(_typed_failure)
    .handle(E.uninterruptible)(_uninterruptible)
    .handle(E.unencodable)(_unencodable)
    .handle(E.volatile)(_volatile),
    disable_fatal_defects=True,
)

type Body = Generator[fx.Effect[Any, Any, Any], Any]


def run(body: Any) -> fx.Effect[None, Any]:
    reset_state()
    return fx.scoped(fx.gen(body))


@testing.live(timeout=60)
def test_delivers_a_persisted_request_sent_while_its_runner_is_down_exactly_once(
    cluster_db: ClusterDatabase,
):
    """delivers a persisted request sent while its runner is down exactly once"""
    backend = cluster_db.backend

    def body() -> Body:
        cluster = yield from make(cluster_db, entities=persistence_entity_layer)
        yield from cluster.start(1)
        yield from cluster.wait_for_stable_assignments()
        owner = yield from cluster.owner_of_entity(E, "restart")
        assert owner is not None
        yield from cluster.kill(owner)

        client = yield from cluster.get_client(E)
        reply = (
            yield from client("restart")
            .persisted(KeyedPayload(id=f"{backend}-restart"))
            .fork(start_immediately=True)
        )
        yield from cluster.wait_until(
            "The request was not persisted while the runner was down",
            cluster.unprocessed_message_count.map(lambda value: value == 1),
        )

        yield from cluster.start(1)
        yield from cluster.wait_for_stable_assignments()
        assert (yield from reply.join()) == f"persisted:{backend}-restart"
        yield from cluster.wait_until(
            "The persisted reply was not recorded",
            cluster.replied_message_count.map(lambda value: value == 1),
        )
        assert count("Persisted", f"{backend}-restart") == 1
        assert (yield from cluster.message_counts()) == MessageCounts(0, 1, 0)

    yield from run(body)


@testing.live(timeout=60)
def test_serves_primary_key_duplicates_from_the_stored_reply(cluster_db: ClusterDatabase):
    """serves primary-key duplicates from the stored reply"""
    backend = cluster_db.backend

    def body() -> Body:
        cluster = yield from make(cluster_db, entities=persistence_entity_layer)
        yield from cluster.start(2)
        yield from cluster.wait_for_stable_assignments()
        client = yield from cluster.get_client(E)
        id = f"{backend}-stored"
        payload = KeyedPayload(id=id)

        assert (yield from client("stored").stored_reply(payload)) == f"stored:{id}"
        first_owner = yield from cluster.owner_of_entity(E, "stored")
        assert first_owner is not None
        yield from cluster.kill(first_owner)
        yield from cluster.wait_for_stable_assignments()

        assert (yield from client("stored").stored_reply(payload)) == f"stored:{id}"
        assert count("StoredReply", id) == 1
        assert (yield from cluster.message_counts()) == MessageCounts(0, 1, 0)

    yield from run(body)


@testing.live(timeout=60)
def test_does_not_lose_an_uninterruptible_request_during_runner_shutdown(
    cluster_db: ClusterDatabase,
):
    """does not lose an uninterruptible request during runner shutdown"""
    backend = cluster_db.backend

    def body() -> Body:
        cluster = yield from make(
            cluster_db,
            entities=persistence_entity_layer,
            config={"entity_termination_timeout": fx.duration.Seconds(0.1)},
        )
        [owner] = yield from cluster.start(1)
        yield from cluster.wait_for_stable_assignments()
        client = yield from cluster.get_client(E)
        id = f"{backend}-uninterruptible"
        reply = (
            yield from client("uninterruptible")
            .uninterruptible(KeyedPayload(id=id))
            .fork(start_immediately=True)
        )
        yield from cluster.wait_until(
            "The uninterruptible handler did not start",
            state.uninterruptible_entered.wait().as_(True),
        )

        stopping = yield from cluster.stop(owner).fork(start_immediately=True)
        yield from cluster.start(1)
        yield from cluster.wait_for_stable_assignments()
        yield from cluster.wait_until(
            "The uninterruptible request was not resumed by the replacement runner",
            fx.sync(lambda: count("Uninterruptible", id) >= 2),
        )
        state.uninterruptible_gate.open_unsafe()
        yield from cluster.wait_until(
            "The resumed uninterruptible request did not complete",
            fx.sync(lambda: state.completed_uninterruptible == 1),
        )

        assert (yield from reply.join()) == f"uninterruptible:{id}"
        yield from stopping.join()
        assert (yield from cluster.replied_message_count) == 1

    yield from run(body)


@testing.live(timeout=60)
def test_does_not_store_or_redeliver_a_volatile_request_after_runner_failure(
    cluster_db: ClusterDatabase,
):
    """does not store or redeliver a volatile request after runner failure"""
    backend = cluster_db.backend

    def body() -> Body:
        cluster = yield from make(
            cluster_db,
            entities=persistence_entity_layer,
            config={"entity_termination_timeout": fx.duration.Seconds(0.1)},
        )
        [owner] = yield from cluster.start(1)
        yield from cluster.wait_for_stable_assignments()
        client = yield from cluster.get_client(E)
        id = f"{backend}-volatile"
        request = (
            yield from client("volatile")
            .volatile.discard(KeyedPayload(id=id))
            .fork(start_immediately=True)
        )
        yield from cluster.wait_until(
            "The volatile handler did not start", state.volatile_entered.wait().as_(True)
        )

        yield from cluster.kill(owner)
        yield from request.interrupt()
        state.volatile_gate.open_unsafe()
        yield from cluster.start(1)
        yield from cluster.wait_for_stable_assignments()
        deadline = (yield from now_millis()) + 1000
        yield from cluster.wait_until(
            "The volatile redelivery observation window did not elapse",
            now_millis().map(lambda now: now >= deadline),
            2,
        )

        assert count("Volatile", id) == 1
        assert state.completed_volatile == 0
        assert (yield from cluster.message_counts()) == MessageCounts(0, 0, 0)

    yield from run(body)


@testing.live(timeout=60)
def test_completes_a_discarded_volatile_caller_while_the_handler_is_still_blocked(
    cluster_db: ClusterDatabase,
):
    """completes a discarded volatile caller while the handler is still blocked"""
    backend = cluster_db.backend

    def body() -> Body:
        cluster = yield from make(
            cluster_db,
            entities=persistence_entity_layer,
            config={"entity_termination_timeout": fx.duration.Seconds(0.1)},
        )
        yield from cluster.start(1)
        yield from cluster.wait_for_stable_assignments()
        client = yield from cluster.get_client(E)
        id = f"{backend}-discarded-volatile"
        caller = (
            yield from client("discarded-volatile")
            .volatile.discard(KeyedPayload(id=id))
            .fork(start_immediately=True)
        )
        yield from cluster.wait_until(
            "The discarded volatile handler did not start",
            state.volatile_entered.wait().as_(True),
        )
        yield from cluster.wait_until(
            "The discarded volatile caller waited for the blocked handler",
            fx.sync(lambda: caller.poll_unsafe() is not None),
        )

        yield from caller.join()
        assert count("Volatile", id) == 1

    yield from run(body)


@testing.live(timeout=60)
def test_stores_an_unencodable_persisted_reply_as_a_defect(cluster_db: ClusterDatabase):
    """stores an unencodable persisted reply as a defect and does not hang the caller"""
    backend = cluster_db.backend

    def body() -> Body:
        cluster = yield from make(cluster_db, entities=persistence_entity_layer)
        yield from cluster.start(2)
        yield from cluster.wait_for_stable_assignments()
        client = yield from cluster.get_client(E)
        id = f"{backend}-unencodable"

        yield from assert_stored_as_defect(
            client("unencodable").unencodable(KeyedPayload(id=id)), "Unencodable", id
        )
        assert (yield from cluster.message_counts()) == MessageCounts(1, 0, 0)

    yield from run(body)


@testing.live(timeout=60)
def test_isolates_a_reply_encoding_failure_so_a_sibling_request_succeeds(
    cluster_db: ClusterDatabase,
):
    """isolates a reply-encoding failure so a sibling request on the same connection succeeds"""
    backend = cluster_db.backend

    def body() -> Body:
        cluster = yield from make(cluster_db, entities=persistence_entity_layer)
        yield from cluster.start(1)
        yield from cluster.wait_for_stable_assignments()
        client = yield from cluster.get_client(E)
        healthy_id = f"{backend}-healthy-blocked"
        healthy = (
            yield from client(f"{backend}-encoding-sibling")
            .healthy(KeyedPayload(id=healthy_id))
            .fork(start_immediately=True)
        )
        yield from cluster.wait_until(
            "The sibling request did not start", state.healthy_entered.wait().as_(True)
        )

        bad_id = f"{backend}-encoding-failure"
        bad = (
            yield from client(f"{backend}-encoding-bad").unencodable(KeyedPayload(id=bad_id)).exit()
        )
        assert isinstance(bad, Exit.Failure)
        assert malformed(bad.cause)

        state.healthy_gate.open_unsafe()
        assert (yield from healthy.join()) == f"healthy:{healthy_id}"
        assert count("Unencodable", bad_id) == 1
        assert count("Healthy", healthy_id) == 1
        assert (yield from cluster.message_counts()) == MessageCounts(1, 1, 0)

    yield from run(body)


@testing.live(timeout=60)
def test_persists_a_non_json_error_as_a_serializable_defect(cluster_db: ClusterDatabase):
    """persists a non-JSON Error as a serializable defect"""
    backend = cluster_db.backend

    def body() -> Body:
        cluster = yield from make(cluster_db, entities=persistence_entity_layer)
        yield from cluster.start(2)
        yield from cluster.wait_for_stable_assignments()
        client = yield from cluster.get_client(E)
        id = f"{backend}-non-json-failure"

        yield from assert_stored_as_defect(
            client("non-json-failure").non_json_failure(KeyedPayload(id=id)),
            "NonJsonFailure",
            id,
        )
        assert (yield from cluster.message_counts()) == MessageCounts(1, 0, 0)

    yield from run(body)


@testing.live(timeout=60)
def test_persists_typed_failures_and_defects_without_wedging_the_mailbox(
    cluster_db: ClusterDatabase,
):
    """persists typed failures and defects without wedging the mailbox"""
    backend = cluster_db.backend

    def body() -> Body:
        cluster = yield from make(cluster_db, entities=persistence_entity_layer)
        yield from cluster.start(2)
        yield from cluster.wait_for_stable_assignments()
        client = yield from cluster.get_client(E)
        typed_id = f"{backend}-typed"
        defect_id = f"{backend}-defect"
        failures = client("failures")

        for _ in range(2):
            error = yield from failures.typed_failure(KeyedPayload(id=typed_id)).flip()
            assert error == f"typed:{typed_id}"
        assert count("TypedFailure", typed_id) == 1

        for _ in range(2):
            defect = yield from failures.defect(KeyedPayload(id=defect_id)).exit()
            assert isinstance(defect, Exit.Failure)
            assert f"defect:{defect_id}" in defect.cause.pretty()
        assert count("Defect", defect_id) == 1

        healthy = yield from failures.healthy(KeyedPayload(id=f"{backend}-healthy"))
        assert healthy == f"healthy:{backend}-healthy"
        yield from cluster.wait_until(
            "The failure replies were not persisted",
            cluster.message_counts().map(lambda c: c.failed == 2 and c.replied == 1),
        )
        assert (yield from cluster.message_counts()) == MessageCounts(2, 1, 0)

    yield from run(body)


@testing.live(timeout=60)
def test_defects_a_malformed_persisted_envelope_without_wedging_the_mailbox(
    cluster_db: ClusterDatabase,
):
    """defects a malformed persisted envelope without wedging the mailbox"""
    backend = cluster_db.backend

    def body() -> Body:
        cluster = yield from make(cluster_db, entities=persistence_entity_layer)
        malformed_id = f"{backend}-malformed-stored"
        entity_id = EntityId(malformed_id)
        shard = cluster.client_sharding.get_shard_id(entity_id, E.get_shard_group(entity_id))
        yield from cluster.insert_message(
            {
                "deliver_at": None,
                "entity_id": malformed_id,
                "entity_type": E.type,
                "headers": json.dumps({"invalid": 1}),
                "id": "1",
                "kind": 0,
                "message_id": None,
                "payload": json.dumps({"id": malformed_id}),
                "reply_id": None,
                "request_id": "1",
                "sampled": None,
                "shard_id": str(shard),
                "span_id": None,
                "tag": "Healthy",
                "trace_id": None,
            }
        )

        yield from cluster.start(1)
        yield from cluster.wait_for_stable_assignments()
        yield from cluster.wait_until(
            "The malformed persisted envelope was not stored as a defect",
            cluster.failed_message_count.map(lambda value: value == 1),
        )
        assert count("Healthy", malformed_id) == 0

        client = yield from cluster.get_client(E)
        healthy_id = f"{backend}-malformed-stored-healthy"
        reply = yield from client("malformed-stored-healthy").healthy(KeyedPayload(id=healthy_id))
        assert reply == f"healthy:{healthy_id}"
        assert count("Healthy", healthy_id) == 1
        assert (yield from cluster.message_counts()) == MessageCounts(1, 1, 0)

    yield from run(body)


@testing.live(timeout=60)
def test_abandons_a_stream_chunk_acknowledgement_during_shutdown(cluster_db: ClusterDatabase):
    """abandons a stream chunk acknowledgement during shutdown without stranding either runner"""
    backend = cluster_db.backend

    def body() -> Body:
        cluster = yield from make(cluster_db, entities=persistence_entity_layer)
        runners = yield from cluster.start(2)
        yield from cluster.wait_for_stable_assignments()
        client = yield from cluster.get_client(E)
        entity_id = f"{backend}-shutdown-stream"
        id = f"{entity_id}-restart"
        owner = yield from cluster.owner_of_entity(E, entity_id)
        assert owner is not None
        peer = next(r for r in runners if r is not owner)
        values = (
            yield from client(entity_id)
            .streamed(KeyedPayload(id=id))
            .run_collect()
            .fork(start_immediately=True)
        )
        yield from cluster.wait_until(
            "The stream handler did not reach its third chunk",
            state.stream_third_entered.wait().as_(True),
        )

        stopping = yield from cluster.stop(owner).fork(start_immediately=True)
        state.stream_third_gate.open_unsafe()
        yield from stopping.join()
        yield from cluster.wait_for_stable_assignments()

        healthy_id = f"{backend}-shutdown-stream-healthy"
        reply = yield from client(entity_id).healthy(KeyedPayload(id=healthy_id))
        assert reply == f"healthy:{healthy_id}"
        assert list((yield from values.join())) == [0, 1, 2, 3, 4]
        assert (yield from cluster.owner_of_entity(E, entity_id)) is peer

    yield from run(body)


@testing.live(timeout=60)
def test_round_trips_a_chunked_reply_through_storage(cluster_db: ClusterDatabase):
    """round-trips a chunked reply through storage"""
    backend = cluster_db.backend

    def body() -> Body:
        cluster = yield from make(cluster_db, entities=persistence_entity_layer)
        yield from cluster.start(2)
        yield from cluster.wait_for_stable_assignments()
        client = yield from cluster.get_client(E)
        id = f"{backend}-stream"
        values = yield from client("stream").streamed(KeyedPayload(id=id)).run_collect()
        assert list(values) == [0, 1, 2, 3, 4]
        yield from cluster.wait_until(
            "The terminal stream reply was not persisted",
            cluster.replied_message_count.map(lambda value: value == 1),
        )
        assert count("Streamed", id) == 1

    yield from run(body)


@testing.live(timeout=60)
def test_resumes_a_persisted_stream_after_its_runner_is_killed(cluster_db: ClusterDatabase):
    """resumes a persisted stream after its runner is killed"""
    backend = cluster_db.backend

    def body() -> Body:
        cluster = yield from make(cluster_db, entities=persistence_entity_layer)
        [owner] = yield from cluster.start(1)
        yield from cluster.wait_for_stable_assignments()
        client = yield from cluster.get_client(E)
        id = f"{backend}-stream-restart"
        received: list[float] = []
        values = yield from (
            client("stream-restart")
            .streamed(KeyedPayload(id=id))
            .tap(lambda value: fx.sync(lambda: received.append(value)))
            .run_collect()
            .fork(start_immediately=True)
        )
        yield from cluster.wait_until(
            "The stream did not deliver two chunks before blocking the third",
            fx.sync(lambda: received == [0, 1]),
        )
        yield from cluster.wait_until(
            "The stream handler did not block before delivering its third chunk",
            state.stream_third_entered.wait().as_(True),
        )

        yield from cluster.kill(owner)
        yield from cluster.start(1)
        yield from cluster.wait_for_stable_assignments()
        yield from cluster.wait_until(
            "The replacement runner did not resume the persisted stream",
            fx.sync(lambda: count("Streamed", id) == 2),
        )
        state.stream_third_gate.open_unsafe()

        assert list((yield from values.join())) == [0, 1, 2, 3, 4]
        yield from cluster.wait_until(
            "The terminal stream reply was not persisted after recovery",
            cluster.message_counts().map(lambda c: c.replied == 1 and c.unprocessed == 0),
        )
        assert (yield from cluster.message_counts()) == MessageCounts(0, 1, 0)

    yield from run(body)


@testing.live(timeout=60)
def test_resumes_a_terminal_stream_on_the_replacement_owner(cluster_db: ClusterDatabase):
    """resumes a terminal stream on the replacement owner and persists exactly one reply"""
    backend = cluster_db.backend

    def body() -> Body:
        scope = yield from Scope()
        yield from scope.add_finalizer(lambda _: fx.sync(state.stream_terminal_gate.open_unsafe))
        cluster = yield from make(cluster_db, entities=persistence_entity_layer)
        runners = yield from cluster.start(2)
        yield from cluster.wait_for_stable_assignments()
        client = yield from cluster.get_client(E)
        entity_id = f"{backend}-terminal-race"
        id = entity_id
        owner = yield from cluster.owner_of_entity(E, entity_id)
        assert owner is not None
        peer = next(r for r in runners if r is not owner)
        received: list[float] = []
        values = yield from (
            client(entity_id)
            .streamed(KeyedPayload(id=id))
            .tap(lambda value: fx.sync(lambda: received.append(value)))
            .run_collect()
            .fork(start_immediately=True)
        )
        yield from cluster.wait_until(
            "The first owner did not reach terminal stream completion",
            state.stream_terminal_entered.wait().as_(True),
        )
        yield from cluster.wait_until(
            "The client did not receive the final stream value before owner death",
            fx.sync(lambda: len(received) == 1),
        )
        assert received == [0]

        yield from cluster.kill(owner)
        yield from cluster.wait_for_entity_owner(E, entity_id, peer)
        yield from cluster.wait_until(
            "The replacement owner did not resume the terminal stream",
            fx.sync(lambda: count("Streamed", id) == 2),
        )
        state.stream_terminal_gate.open_unsafe()

        assert list((yield from values.join())) == [0]
        yield from cluster.wait_until(
            "The surviving terminal stream reply was not persisted",
            cluster.message_counts().map(lambda c: c.replied == 1 and c.unprocessed == 0),
        )
        assert count("Streamed", id) == 2
        assert (yield from cluster.owner_of_entity(E, entity_id)) is peer

    yield from run(body)


@testing.live(timeout=60)
def test_delivers_scheduled_messages_only_after_their_deadline(cluster_db: ClusterDatabase):
    """delivers scheduled messages only after their deadline"""
    backend = cluster_db.backend

    def body() -> Body:
        cluster = yield from make(cluster_db, entities=persistence_entity_layer)
        yield from cluster.start(2)
        yield from cluster.wait_for_stable_assignments()
        client = yield from cluster.get_client(E)
        id = f"{backend}-scheduled"
        deliver_at = (yield from now_millis()) + 1500
        reply = (
            yield from client("scheduled")
            .scheduled(ScheduledPayload(deliver_at_millis=deliver_at, id=id))
            .fork(start_immediately=True)
        )

        yield from cluster.wait_until(
            "The early-delivery observation point was not reached",
            now_millis().map(lambda now: now >= deliver_at - 500),
            2,
        )
        assert count("Scheduled", id) == 0
        assert state.scheduled_deliveries == []

        yield from cluster.wait_until(
            "The scheduled message was not delivered after its deadline",
            fx.sync(lambda: len(state.scheduled_deliveries) == 1),
            5,
        )
        yield from cluster.wait_until(
            "The scheduled reply was not persisted",
            cluster.replied_message_count.map(lambda value: value == 1),
        )
        delivered_at = yield from reply.join()
        assert delivered_at >= deliver_at
        assert state.scheduled_deliveries[0] == delivered_at

    yield from run(body)
