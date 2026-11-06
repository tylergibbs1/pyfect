"""Ports of Effect's ``effect/test/eventlog/EventLogRemote.test.ts``. Each
test's docstring is the Effect test title.

The harness's RPC client is a fake ``EventLogRemoteRpcs`` whose calls park
until the test resumes them (Effect's ``RpcTest`` client over callback
handlers): a call's effect waits on a ``Deferred`` the test completes. The
server-backed titles connect ``rpc`` ``make_no_serialization`` clients to one
``make_no_serialization`` server over memory storage, as Effect's do.
"""

from __future__ import annotations

from collections.abc import Callable, Generator, Sequence
from dataclasses import dataclass
from typing import Any

import pyfect as fx
from pyfect import testing
from pyfect.context import Context
from pyfect.deferred import Deferred
from pyfect.eventlog import event_journal as J
from pyfect.eventlog import event_log as L
from pyfect.eventlog import event_log_message as M
from pyfect.eventlog import event_log_server_encrypted as E
from pyfect.eventlog import event_log_server_unencrypted as U
from pyfect.eventlog._identity_derivation import make_get_identity_root_secret_material
from pyfect.eventlog.event_journal import Entry, RemoteEntry, StoreId
from pyfect.eventlog.event_log_encryption import EventLogEncryption, layer_subtle
from pyfect.eventlog.event_log_remote import (
    EventLogRemoteClient,
    EventLogRemoteError,
    EventLogRemoteService,
    make_encrypted,
    make_unencrypted,
)
from pyfect.eventlog.event_log_server import ConnectionWrites
from pyfect.eventlog.event_log_session_auth import (
    SessionAuthPayload,
    verify_session_authenticate_request,
)
from pyfect.option import Some
from pyfect.queue import Dequeue
from pyfect.rpc.client._core import ClientOptions
from pyfect.rpc.client._core import make_no_serialization as make_rpc_client
from pyfect.rpc.message import FromServer
from pyfect.rpc.server._core import RpcServer
from pyfect.rpc.server._core import make_no_serialization as make_rpc_server
from pyfect.stream import from_queue

default_store_id = StoreId("default")
remote_id = J.make_remote_id_unsafe()
challenge = bytes([1] * 16)
get_material = make_get_identity_root_secret_material()


@dataclass(frozen=True)
class Request:
    tag: str
    request: Any
    _done: Deferred[Any, Any]

    def resume(self, response: fx.Effect[Any, Any]) -> fx.Effect[bool]:
        return self._done.complete_with(response)


class _ParkingClient:
    """Every call is offered to ``requests`` and waits for its resume."""

    def __init__(self, requests: fx.Queue[Request]) -> None:
        self._requests = requests

    def _call(self, tag: str, request: Any) -> fx.Effect[Any, Any]:
        def run():
            done = Deferred[Any, Any]()
            yield from self._requests.offer(Request(tag, request, done))
            return (yield from done.wait())

        return fx.gen(run)

    def hello(self) -> fx.Effect[Any, Any]:
        return self._call("EventLog.Hello", None)

    def authenticate(self, request: Any) -> fx.Effect[Any, Any]:
        return self._call("EventLog.Authenticate", request)

    def write_chunked(self, request: Any) -> fx.Effect[Any, Any]:
        return self._call("EventLog.WriteChunked", request)

    def write_single(self, request: Any) -> fx.Effect[Any, Any]:
        return self._call("EventLog.WriteSingle", request)

    def changes(self, request: Any, **_: object) -> fx.Effect[Any, Any]:
        return self._call("EventLog.Changes", request)


@dataclass(frozen=True)
class Harness:
    remote: EventLogRemoteService
    take: fx.Effect[Request]


def make_harness(make_client: fx.Effect[Any, Any, Any]) -> Generator[Any, Any, Harness]:
    requests = yield from fx.Queue[Request].unbounded()
    client: Any = _ParkingClient(requests)
    remote = yield from (
        make_client.pipe(fx.provide_service(EventLogRemoteClient, client))
        .pipe(fx.provide(fx.layer.merge(layer_subtle, L.layer_registry)))
        .fork()
    )
    hello = yield from requests.take()
    assert hello.tag == "EventLog.Hello"
    yield from hello.resume(fx.succeed(M.HelloResponse(remote_id=remote_id, challenge=challenge)))
    return Harness((yield from remote.join()), requests.take())


def make_entry(payload_size: int = 4, primary_key: str = "user-1") -> Entry:
    return Entry(
        id=J.make_entry_id_unsafe(),
        event="UserCreated",
        primary_key=primary_key,
        payload=bytes([1] * payload_size),
    )


def authenticate(harness: Harness, identity: L.IdentityService):
    auth = yield from harness.take
    assert auth.tag == "EventLog.Authenticate"
    payload: M.Authenticate = auth.request
    material = yield from get_material(identity)
    assert payload.public_key == identity.public_key
    assert payload.algorithm == "Ed25519"
    assert payload.signing_public_key == material.signing_public_key
    verified = yield from verify_session_authenticate_request(
        SessionAuthPayload(
            remote_id=remote_id,
            challenge=challenge,
            public_key=payload.public_key,
            signing_public_key=payload.signing_public_key,
        ),
        payload.signature,
        payload.algorithm,
    )
    assert verified
    yield from auth.resume(fx.void)


def _run(body: Any) -> fx.Effect[Any, Any]:
    return fx.scoped(fx.gen(body)).pipe(fx.provide(layer_subtle))


@testing.effect
def test_retries_wrapped_forbidden_authentication_errors():
    """retries wrapped Forbidden authentication errors"""

    def body():
        harness = yield from make_harness(make_unencrypted)
        identity = yield from L.make_identity
        attempts = [0]

        def serve():
            request = yield from harness.take
            if request.tag == "EventLog.Hello":
                yield from request.resume(
                    fx.succeed(M.HelloResponse(remote_id=remote_id, challenge=challenge))
                )
            elif request.tag == "EventLog.Authenticate":
                attempts[0] += 1
                yield from request.resume(
                    fx.fail(
                        M.EventLogProtocolError(
                            request_tag="Authenticate",
                            public_key=None,
                            code="Forbidden",
                            message="Session auth challenge has expired",
                        )
                    )
                    if attempts[0] == 1
                    else fx.void
                )
            elif request.tag == "EventLog.WriteSingle":
                yield from request.resume(fx.void)

        yield from fx.gen(serve).forever().fork_scoped()
        yield from harness.remote.write(
            identity=identity, store_id=default_store_id, entries=[make_entry()]
        )
        assert attempts[0] == 2

    yield from _run(body)


@testing.effect
def test_make_unencrypted_authenticates_before_writing():
    """makeUnencrypted authenticates before writing plaintext entries"""

    def body():
        harness = yield from make_harness(make_unencrypted)
        identity = yield from L.make_identity
        entry = make_entry()
        write = yield from harness.remote.write(
            identity=identity, store_id=default_store_id, entries=[entry]
        ).fork_scoped()
        yield from authenticate(harness, identity)
        request = yield from harness.take
        assert request.tag == "EventLog.WriteSingle"
        decoded = yield from M.WriteEntriesUnencrypted.decode(request.request["data"])
        assert decoded.public_key == identity.public_key
        assert decoded.store_id == default_store_id
        assert [e.id_string for e in decoded.entries] == [entry.id_string]
        acks = [M.WriteAck(entry_id=entry.id, sequence=5)]
        yield from request.resume(fx.succeed(acks))
        assert (yield from write.join()) == acks

    yield from _run(body)


@testing.effect
def test_pipelines_at_most_four_chunks():
    """pipelines at most four chunks and retains completion acks before a later empty response"""

    def body():
        harness = yield from make_harness(make_unencrypted)
        identity = yield from L.make_identity
        entry = make_entry(payload_size=M.CHUNK_SIZE * 4)
        write = yield from harness.remote.write(
            identity=identity, store_id=default_store_id, entries=[entry]
        ).fork_scoped()
        yield from authenticate(harness, identity)
        first = yield from harness.take
        assert first.tag == "EventLog.WriteChunked"

        # A virtual deadline turns a sequential sender into an assertion
        # failure, rather than hanging while the first response is withheld.
        def take_chunk():
            pending = yield from harness.take.timeout_option(1).fork_scoped()
            yield from testing.adjust(1)
            result = yield from pending.join()
            assert isinstance(result, Some), "expected another chunk before acknowledging"
            assert result.value.tag == "EventLog.WriteChunked"
            return result.value

        second = yield from take_chunk()
        third = yield from take_chunk()
        fourth = yield from take_chunk()
        pending_fifth = yield from harness.take.timeout_option(1).fork_scoped()
        yield from testing.adjust(1)
        assert (yield from pending_fifth.join()) is None, "the fifth chunk waits for a response"
        yield from second.resume(fx.succeed([]))
        fifth = yield from take_chunk()
        parts: list[M.ChunkedMessage] = [r.request for r in [first, second, third, fourth, fifth]]
        assert [p.part for p in parts] == [(0, 5), (1, 5), (2, 5), (3, 5), (4, 5)]
        assert all(p.id == parts[0].id for p in parts)
        # Part 0 completes the message; part 4 has a delayed empty reply.
        yield from third.resume(fx.succeed([]))
        yield from fourth.resume(fx.succeed([]))
        acks = [M.WriteAck(entry_id=entry.id, sequence=5)]
        yield from first.resume(fx.succeed(acks))
        yield from testing.adjust(1)
        yield from fifth.resume(fx.succeed([]))
        assert (yield from write.join()) == acks

    yield from _run(body)


@testing.effect
def test_make_encrypted_authenticates_before_writing():
    """makeEncrypted authenticates before writing encrypted entries"""

    def body():
        harness = yield from make_harness(make_encrypted)
        identity = yield from L.make_identity
        write = yield from harness.remote.write(
            identity=identity, store_id=default_store_id, entries=[make_entry()]
        ).fork_scoped()
        yield from authenticate(harness, identity)
        request = yield from harness.take
        assert request.tag == "EventLog.WriteSingle"
        decoded = yield from M.WriteEntries.decode(request.request["data"])
        assert decoded.public_key == identity.public_key
        assert decoded.store_id == default_store_id
        assert [len(b.entry_ids) for b in decoded.batches] == [1]
        yield from request.resume(fx.void)
        yield from write.join()

    yield from _run(body)


@dataclass(frozen=True)
class _Item:
    entry_ids: tuple[J.EntryId, ...]
    sequence: int


@testing.effect
def test_keeps_concurrent_overlapping_writes_suppressed():
    """keeps concurrent overlapping writes suppressed after the first write completes"""

    def body():
        writes = ConnectionWrites()
        options: dict[str, Any] = {"public_key": "writer", "store_id": default_store_id}
        input_ = yield from fx.Queue[_Item].unbounded()
        output = yield from fx.Queue[_Item].unbounded()
        yield from (
            writes.filter(
                **options,
                entry_ids=lambda item: item.entry_ids,
                sequence=lambda item: item.sequence,
                stream=from_queue(input_),
            )
            .run_for_each(output.offer)
            .fork_scoped()
        )

        def marker(sequence: int) -> _Item:
            return _Item((J.make_entry_id_unsafe(),), sequence)

        yield from input_.offer(marker(0))
        yield from output.take()
        a, b, c = (J.make_entry_id_unsafe() for _ in range(3))
        started = yield from fx.Queue[None].unbounded()
        first_done = Deferred[tuple[M.WriteAck, ...]]()
        second_done = Deferred[tuple[M.WriteAck, ...]]()

        def track(entry_ids: list[J.EntryId], done: Deferred[tuple[M.WriteAck, ...]]):
            return fx.suspend(
                lambda: writes.track(
                    **options, entry_ids=entry_ids, write=started.offer(None).and_then(done.wait())
                )
            ).fork_scoped()

        first = yield from track([a, b], first_done)
        second = yield from track([a, c], second_done)
        yield from started.take_n(2)

        yield from input_.offer(_Item((a, b), 2))
        first_marker = marker(3)
        yield from input_.offer(first_marker)
        assert (yield from output.take()) == first_marker
        yield from first_done.succeed(
            (M.WriteAck(entry_id=a, sequence=1), M.WriteAck(entry_id=b, sequence=2))
        )
        yield from first.join()

        yield from input_.offer(_Item((a, c), 5))
        second_marker = marker(6)
        yield from input_.offer(second_marker)
        assert (yield from output.take()) == second_marker
        yield from second_done.succeed(
            (M.WriteAck(entry_id=a, sequence=4), M.WriteAck(entry_id=c, sequence=5))
        )
        yield from second.join()

    yield from fx.scoped(fx.gen(body))


@testing.effect
def test_write_wraps_authentication_failures_in_a_write_error():
    """pyfect: write wraps every failure, an authentication one included, in a
    "write" EventLogRemoteError, and authentication wraps a failed hello
    (Effect maps both without unwrapping)"""

    def body():
        harness = yield from make_harness(make_unencrypted)
        identity = yield from L.make_identity
        denied = M.EventLogProtocolError(
            request_tag="Authenticate",
            public_key=None,
            code="InternalServerError",
            message="denied",
        )
        write = yield from harness.remote.write(
            identity=identity, store_id=default_store_id, entries=[make_entry()]
        ).fork_scoped()
        auth = yield from harness.take
        assert auth.tag == "EventLog.Authenticate"
        yield from auth.resume(fx.fail(denied))
        exit_ = yield from write.await_exit()
        assert isinstance(exit_, fx.Failure)
        error = exit_.cause.find_error()
        assert isinstance(error, fx.Ok)
        assert isinstance(error.value, EventLogRemoteError)
        assert error.value.method == "write"
        inner = error.value.cause
        assert isinstance(inner, EventLogRemoteError)
        assert inner.method == "authenticate"
        assert inner.cause is denied

    yield from _run(body)


# --- server-backed: one RPC server shared by connections with distinct client ids ---


@dataclass
class Connection:
    remote: EventLogRemoteService
    write_batches: Callable[[list[Any]], fx.Effect[list[M.WriteAck], Any, Any]]
    write_single: Callable[[list[Entry]], fx.Effect[list[M.WriteAck], Any, Any]]
    write_chunked: Callable[[list[Entry]], fx.Effect[list[M.WriteAck], Any, Any]]


def _allow_all() -> U.EventLogServerAuthorizationService:
    class AllowAll(U.EventLogServerAuthorizationService):
        def authorize_write(self, **_: Any) -> fx.Effect[None, U.EventLogServerAuthError]:
            return fx.void

        def authorize_read(self, **_: Any) -> fx.Effect[None, U.EventLogServerAuthError]:
            return fx.void

        def authorize_identity(self, **_: Any) -> fx.Effect[None, U.EventLogServerAuthError]:
            return fx.void

    return AllowAll()


def make_server(
    encrypted: bool,
) -> Generator[Any, Any, Callable[[L.IdentityService], fx.Effect[Connection, Any, Any]]]:
    if encrypted:
        handlers_layer: fx.Layer[Any, Any, Any] = E.layer_rpc_handlers.pipe(
            fx.layer.provide(E.layer_storage_memory)
        )
    else:
        handlers_layer = (
            U.layer_rpc_handlers.pipe(fx.layer.provide(U.layer_storage_memory))
            .pipe(fx.layer.provide(L.layer_registry))
            .pipe(fx.layer.provide(U.layer_store_mapping_static(store_id=default_store_id)))
            .pipe(fx.layer.provide(fx.layer.succeed(U.EventLogServerAuthorization, _allow_all())))
        )
    handlers: Context[Any] = yield from handlers_layer.build()
    connections: dict[int, Any] = {}

    def on_from_server(response: FromServer) -> fx.Effect[None]:
        return connections[response.client_id](response)

    server: RpcServer = yield from make_rpc_server(M.EventLogRemoteRpcs, on_from_server).pipe(
        fx.provide(handlers)
    )
    client_ids = iter(range(1_000))

    def connect(identity: L.IdentityService) -> fx.Effect[Connection, Any, Any]:
        def body() -> Generator[Any, Any, Connection]:
            client_id = next(client_ids)
            client, core = yield from make_rpc_client(
                M.EventLogRemoteRpcs,
                lambda sent: server.write(client_id, sent.message),
                ClientOptions(supports_ack=True),
            )
            connections[client_id] = core.write
            make: fx.Effect[EventLogRemoteService, Any, Any] = (
                make_encrypted if encrypted else make_unencrypted
            )
            remote: EventLogRemoteService = yield from make.pipe(
                fx.provide_service(EventLogRemoteClient, client)
            ).pipe(fx.provide(L.layer_registry))
            yield from remote.when_authenticated(fx.void).pipe(
                fx.provide_service(L.Identity, identity)
            )

            def encode_write(entries: list[Entry]) -> Generator[Any, Any, bytes]:
                if encrypted:
                    encryption = yield from EventLogEncryption()
                    batches = yield from encryption.encrypt(identity, default_store_id, entries)
                    request: M.WriteEntries | M.WriteEntriesUnencrypted = M.WriteEntries(
                        public_key=identity.public_key,
                        store_id=default_store_id,
                        batches=tuple(batches),
                    )
                else:
                    request = M.WriteEntriesUnencrypted(
                        public_key=identity.public_key,
                        store_id=default_store_id,
                        entries=tuple(entries),
                    )
                return (yield from request.encoded)

            def write_batches(batches: list[Any]) -> fx.Effect[Any, Any, Any]:
                return M.WriteEntries(
                    public_key=identity.public_key,
                    store_id=default_store_id,
                    batches=tuple(batches),
                ).encoded.flat_map(lambda data: client.write_single({"data": data}))

            def write_single(entries: list[Entry]) -> fx.Effect[Any, Any, Any]:
                return fx.gen(lambda: encode_write(entries)).flat_map(
                    lambda data: client.write_single({"data": data})
                )

            # Reverse arrival order: index 0, not the highest index, completes the write.
            def write_chunked(entries: list[Entry]) -> fx.Effect[Any, Any, Any]:
                def run():
                    data = yield from encode_write(entries)
                    parts = list(reversed(M.ChunkedMessage.split(client_id, data)))
                    assert len(parts) > 1
                    responses: list[Any] = []
                    for part in parts:
                        response = yield from client.write_chunked(part)
                        responses.append(response)
                    # Earlier parts acknowledge nothing.
                    assert [list(r) for r in responses[:-1]] == [[] for _ in parts[1:]]
                    return responses[-1]

                return fx.gen(run)

            return Connection(remote, write_batches, write_single, write_chunked)

        return fx.gen(body)

    return connect


def _acks(delivered: Sequence[RemoteEntry]) -> list[M.WriteAck]:
    return [M.WriteAck(entry_id=r.entry.id, sequence=r.remote_sequence) for r in delivered]


def _ordered_duplicate_acks(encrypted: bool) -> Generator[Any, Any]:
    connect = yield from make_server(encrypted)
    identity = yield from L.make_identity
    writer = yield from connect(identity)
    reader = yield from connect(identity)
    assert (writer.remote.first_sequence or 0) == (0 if encrypted else 1)

    def subscribe(connection: Connection) -> fx.Effect[Dequeue[RemoteEntry, Any], Any, Any]:
        return connection.remote.changes(
            identity=identity, store_id=default_store_id, start_sequence=0
        )

    writer_changes = yield from subscribe(writer)
    reader_changes = yield from subscribe(reader)
    # A third connection's entry makes both subscriptions live.
    seed = make_entry()
    yield from (yield from connect(identity)).write_single([seed])
    yield from writer_changes.take()
    yield from reader_changes.take()

    a = make_entry()
    b = make_entry(payload_size=M.ChunkedMessage.chunk_size)
    acks = list((yield from writer.write_single([a, b])))
    assert list((yield from writer.write_chunked([b, a]))) == list(reversed(acks))
    delivered = yield from reader_changes.take_n(2)
    assert [r.entry.id_string for r in delivered] == [a.id_string, b.id_string]
    assert acks == _acks(delivered)

    marker = make_entry()
    yield from reader.write_single([marker])
    assert (yield from writer_changes.take()).entry.id_string == marker.id_string
    replay = yield from subscribe((yield from connect(identity)))
    assert [r.entry.id_string for r in (yield from replay.take_n(3))] == [
        seed.id_string,
        a.id_string,
        b.id_string,
    ]


@testing.effect
def test_encrypted_ordered_duplicate_acks():
    """encrypted: ordered duplicate acks, out-of-order chunk reassembly and
    connection-scoped echoes"""
    yield from _run(lambda: _ordered_duplicate_acks(True))


@testing.effect
def test_unencrypted_ordered_duplicate_acks():
    """unencrypted: ordered duplicate acks, out-of-order chunk reassembly and
    connection-scoped echoes"""
    yield from _run(lambda: _ordered_duplicate_acks(False))


@testing.effect
def test_acknowledges_each_occurrence_in_overlapping_encrypted_batches():
    """acknowledges and suppresses each occurrence in overlapping encrypted batches"""

    def body():
        connect = yield from make_server(True)
        identity = yield from L.make_identity
        writer = yield from connect(identity)
        reader = yield from connect(identity)
        writer_changes = yield from writer.remote.changes(
            identity=identity, store_id=default_store_id, start_sequence=0
        )
        yield from reader.write_single([make_entry()])
        yield from writer_changes.take()
        reader_changes = yield from reader.remote.changes(
            identity=identity, store_id=default_store_id, start_sequence=1
        )
        encryption = yield from EventLogEncryption()
        a, b = make_entry(), make_entry()
        acks = yield from writer.write_batches(
            [
                *(yield from encryption.encrypt(identity, default_store_id, [a])),
                *(yield from encryption.encrypt(identity, default_store_id, [a, b])),
            ]
        )
        delivered = yield from reader_changes.take_n(3)
        marker = make_entry()
        yield from reader.write_single([marker])
        assert {
            "acks": list(acks),
            "next_for_writer": (yield from writer_changes.take()).entry.id_string,
        } == {"acks": _acks(delivered), "next_for_writer": marker.id_string}

    yield from _run(body)
