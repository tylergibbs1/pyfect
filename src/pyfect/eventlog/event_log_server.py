"""The RPC handlers of an event log server (Effect's
``eventlog/EventLogServer``), shared by the encrypted and unencrypted
servers.

``layer_rpc_handlers`` answers ``Hello`` with a one-time challenge per
connection (30 seconds), verifies ``Authenticate`` against the identity's
bound signing key, joins chunked writes and splits large changes.
``ConnectionWrites`` keeps a connection's own writes out of its change
streams.
"""

from __future__ import annotations

import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

from pyfect._core import Effect
from pyfect._effect_args import require_effect
from pyfect.cache import Cache
from pyfect.context import Tag
from pyfect.effect import fail, gen, succeed, suspend, sync
from pyfect.eventlog import _uuid
from pyfect.eventlog._identity import Identity, IdentityService
from pyfect.eventlog.event_journal import EntryId, RemoteId, StoreId
from pyfect.eventlog.event_log_message import (
    CHUNK_SIZE,
    Authenticate,
    ChangesPayload,
    ChunkedMessage,
    EventLogAuthentication,
    EventLogProtocolError,
    EventLogRemoteRpcs,
    HelloResponse,
    JoinState,
    SingleMessage,
    WriteAck,
    WriteSinglePayload,
)
from pyfect.eventlog.event_log_session_auth import (
    SESSION_AUTH_CHALLENGE_TIME_TO_LIVE_SECONDS,
    SessionAuthPayload,
    make_session_auth_challenge,
    verify_session_authenticate_request,
)
from pyfect.exit import Exit, Success
from pyfect.layer import Layer, provide_merge
from pyfect.layer import succeed as layer_succeed
from pyfect.redacted import make as redacted
from pyfect.rpc import RpcRequest
from pyfect.rpc.group import HandlersFor
from pyfect.rpc.middleware import MiddlewareOptions
from pyfect.stream import Stream
from pyfect.stream import fail as stream_fail
from pyfect.stream import suspend as stream_suspend
from pyfect.stream._base import require_stream

__all__ = [
    "AuthenticatedIdentities",
    "Changes",
    "ChunkedMessageState",
    "ConnectionWrites",
    "OnWrite",
    "layer_auth_middleware",
    "layer_rpc_handlers",
]

_EMPTY_PRIVATE_KEY = redacted(bytes(32))


def _forbidden(request_tag: str, message: str, public_key: str | None = None):
    return EventLogProtocolError(
        request_tag=request_tag, code="Forbidden", message=message, public_key=public_key
    )


def _authentication(effect: Effect[Any, Any, Any], options: MiddlewareOptions) -> Effect[Any, Any]:
    identity = options.client.annotations.get_option(Identity)
    if identity is not None:
        from pyfect.effect import provide_service

        return effect.pipe(provide_service(Identity, identity.value))
    return fail(_forbidden(options.rpc.tag, "Unauthenticated request"))


layer_auth_middleware: Layer[EventLogAuthentication] = layer_succeed(
    EventLogAuthentication, _authentication
)
"""Provides the connection's authenticated ``Identity``, or fails
``Forbidden``."""


class AuthenticatedIdentities(
    Tag[frozenset[str]], key="effect/eventlog/EventLogServer/AuthenticatedIdentities"
):
    """The public keys a connection authenticated."""


class ChunkedMessageState(Tag[JoinState], key="effect/eventlog/EventLogServer/ChunkedMessageState"):
    """A connection's partially received chunked writes."""


@dataclass(slots=True)
class _ConnectionStream:
    # Outstanding occurrences of this connection's writes, by entry id.
    ids: dict[str, int] = field(default_factory=dict[str, int])
    position: int = -1


def _release(ids: dict[str, int], id: str) -> None:
    count = ids.get(id)
    if count is None:
        return
    if count <= 1:
        del ids[id]
    else:
        ids[id] = count - 1


class ConnectionWrites:
    """A connection's writes, kept out of its own change streams."""

    def __init__(self) -> None:
        self._streams: dict[tuple[str, str], set[int]] = {}
        self._states: dict[int, _ConnectionStream] = {}

    def track[E, R](
        self,
        *,
        public_key: str,
        store_id: StoreId,
        entry_ids: Sequence[EntryId],
        write: Effect[tuple[WriteAck, ...], E, R],
    ) -> Effect[tuple[WriteAck, ...], E, R]:
        """Run ``write``, so the connection's streams skip what it stores."""
        require_effect(write, "write")
        open_streams = self._streams.get((public_key, store_id))
        if not open_streams or not entry_ids:
            return write
        streams = [self._states[key] for key in open_streams]
        started = [stream.position for stream in streams]
        ids = [_uuid.stringify(entry_id) for entry_id in entry_ids]
        # Track before writing: storage can publish an entry before the
        # write returns. Each occurrence counts, as an id can be stored
        # more than once.
        for stream in streams:
            for id in ids:
                stream.ids[id] = stream.ids.get(id, 0) + 1

        def settle(exit: Exit[tuple[WriteAck, ...], E]) -> Effect[None]:
            def run() -> None:
                for stream, position in zip(streams, started, strict=True):
                    if not isinstance(exit, Success):
                        for id in ids:
                            _release(stream.ids, id)
                        continue
                    # Release occurrences the stream had passed when the write began.
                    for ack in exit.value:
                        if ack.sequence <= position:
                            _release(stream.ids, _uuid.stringify(ack.entry_id))

            return sync(run)

        return write.on_exit(settle)

    def filter[A, E, R](
        self,
        *,
        public_key: str,
        store_id: StoreId,
        entry_ids: Callable[[A], Sequence[EntryId]],
        sequence: Callable[[A], int],
        stream: Stream[A, E, R],
    ) -> Stream[A, E, R]:
        """``stream`` without the items this connection wrote."""
        require_stream(stream, "stream")

        def make() -> Stream[A, E, R]:
            key = (public_key, store_id)
            state = _ConnectionStream()
            self._states[id(state)] = state
            open_streams = self._streams.setdefault(key, set())
            open_streams.add(id(state))

            def keep(item: A) -> bool:
                position = sequence(item)
                state.position = max(state.position, position)
                if not state.ids:
                    return True
                # An item is written by one request: all of it is ours or none.
                ids = [_uuid.stringify(entry_id) for entry_id in entry_ids(item)]
                if not all(id in state.ids for id in ids):
                    return True
                for id in ids:
                    _release(state.ids, id)
                return False

            def close() -> None:
                open_streams.discard(id(state))
                del self._states[id(state)]
                if not open_streams:
                    self._streams.pop(key, None)

            return stream.filter(keep).ensuring(sync(close))

        return stream_suspend(make)


class _ConnectionWritesState(
    Tag[ConnectionWrites], key="effect/eventlog/EventLogServer/ConnectionWrites"
):
    pass


def _connection_writes(request: RpcRequest[object]) -> ConnectionWrites:
    client = request.client
    existing = client.annotations.get_option(_ConnectionWritesState)
    if existing is not None:
        return existing.value
    writes = ConnectionWrites()
    client.annotate(_ConnectionWritesState, writes)
    return writes


def _authenticated(request: RpcRequest[object]) -> frozenset[str]:
    found = request.client.annotations.get_option(AuthenticatedIdentities)
    return found.value if found is not None else frozenset()


type OnWrite = Callable[
    [bytes, frozenset[str], ConnectionWrites], Effect[tuple[WriteAck, ...], EventLogProtocolError]
]


type Changes = Callable[[str, StoreId, int, ConnectionWrites], Stream[bytes, object]]
"""A connection's changes: ``(public_key, store_id, start_sequence, writes)``."""


def layer_rpc_handlers(
    *,
    remote_id: RemoteId,
    get_or_create_session_auth_binding: Callable[[str, bytes], Effect[bytes, object]],
    on_write: OnWrite,
    changes: Changes,
    first_sequence: int | None = None,
    authorize_identity: Callable[[str], Effect[None, EventLogProtocolError]] | None = None,
) -> Layer[HandlersFor[EventLogRemoteRpcs] | EventLogAuthentication]:
    """The handlers of ``EventLogRemoteRpcs`` and the auth middleware.
    ``get_or_create_session_auth_binding`` gives the signing key bound to a
    public key (binding the presented one on first use)."""

    def make():
        def new_challenge(_client_id: int) -> Effect[bytes]:
            return make_session_auth_challenge.or_die()

        challenges = yield from Cache.make(
            new_challenge,
            capacity=sys.maxsize,
            time_to_live=SESSION_AUTH_CHALLENGE_TIME_TO_LIVE_SECONDS,
        )
        signing_keys: dict[str, bytes] = {}

        def bound_signing_key(
            public_key: str, presented: bytes
        ) -> Effect[bytes, EventLogProtocolError]:
            # Successful bindings are cached (at most 4096); failures are not.
            found = signing_keys.get(public_key)
            if found is not None:
                return succeed(found)

            def remember(key: bytes) -> bytes:
                if len(signing_keys) >= 4096:
                    del signing_keys[next(iter(signing_keys))]
                signing_keys[public_key] = key
                return key

            return (
                get_or_create_session_auth_binding(public_key, presented)
                .catch_cause(
                    lambda _: fail(
                        _forbidden("Authenticate", "Session auth binding lookup failed", public_key)
                    )
                )
                .map(remember)
            )

        chunk_ids = [0]

        def hello(request: RpcRequest[None]) -> Effect[HelloResponse]:
            return challenges.get(request.client.id).map(
                lambda challenge: HelloResponse(
                    remote_id=remote_id, challenge=challenge, first_sequence=first_sequence
                )
            )

        def authenticate(request: RpcRequest[Authenticate]) -> Effect[None, EventLogProtocolError]:
            payload = request.payload
            client = request.client

            def body():
                found = yield from challenges.get_option(client.id)
                if found is None:
                    return (
                        yield from fail(
                            _forbidden(
                                "Authenticate",
                                "Session auth challenge has expired",
                                payload.public_key,
                            )
                        )
                    )
                yield from challenges.invalidate(client.id)
                if authorize_identity is not None:
                    yield from authorize_identity(payload.public_key)
                signing_key = yield from bound_signing_key(
                    payload.public_key, payload.signing_public_key
                )
                verified = yield from verify_session_authenticate_request(
                    SessionAuthPayload(
                        remote_id=remote_id,
                        challenge=found.value,
                        public_key=payload.public_key,
                        signing_public_key=signing_key,
                    ),
                    payload.signature,
                    payload.algorithm,
                ).catch_all(lambda _: succeed(False))
                if not verified:
                    return (
                        yield from fail(
                            _forbidden(
                                "Authenticate",
                                "Session auth signature verification failed",
                                payload.public_key,
                            )
                        )
                    )
                client.annotate(
                    Identity, IdentityService(payload.public_key, _EMPTY_PRIVATE_KEY)
                ).annotate(
                    AuthenticatedIdentities, _authenticated(request) | {payload.public_key}
                ).annotate(ChunkedMessageState, ChunkedMessage.initial_join_state())

            return gen(body)

        def write_single(
            request: RpcRequest[WriteSinglePayload],
        ) -> Effect[tuple[WriteAck, ...], EventLogProtocolError]:
            return suspend(
                lambda: on_write(
                    request.payload["data"], _authenticated(request), _connection_writes(request)
                )
            )

        def write_chunked(
            request: RpcRequest[ChunkedMessage],
        ) -> Effect[tuple[WriteAck, ...], EventLogProtocolError]:
            def run() -> Effect[tuple[WriteAck, ...], EventLogProtocolError]:
                found = request.client.annotations.get_option(ChunkedMessageState)
                state = found.value if found is not None else ChunkedMessage.initial_join_state()
                if found is None:
                    request.client.annotate(ChunkedMessageState, state)
                data = ChunkedMessage.join(state, request.payload)
                if data is None:
                    return succeed(())
                return on_write(data, _authenticated(request), _connection_writes(request))

            return suspend(run)

        def to_messages(data: bytes) -> list[SingleMessage | ChunkedMessage]:
            if len(data) <= CHUNK_SIZE:
                return [SingleMessage(data=data)]
            chunk_ids[0] += 1
            return list(ChunkedMessage.split(chunk_ids[0] - 1, data))

        def changes_handler(
            request: RpcRequest[ChangesPayload],
        ) -> Stream[SingleMessage | ChunkedMessage, EventLogProtocolError]:
            payload = request.payload
            public_key = payload["public_key"]
            if public_key not in _authenticated(request):
                return stream_fail(
                    _forbidden("Changes", "Identity is not authenticated", public_key)
                )
            return (
                changes(
                    public_key,
                    payload["store_id"],
                    payload["start_sequence"],
                    _connection_writes(request),
                )
                .map_array(lambda chunk: tuple(m for data in chunk for m in to_messages(data)))
                .catch_cause(
                    lambda _: stream_fail(
                        EventLogProtocolError(
                            request_tag="Changes",
                            code="InternalServerError",
                            message="Decoding failure",
                            public_key=public_key,
                        )
                    )
                )
            )

        return (
            EventLogRemoteRpcs.handlers()
            .handle(EventLogRemoteRpcs.hello)(hello)
            .handle(EventLogRemoteRpcs.authenticate)(authenticate)
            .handle(EventLogRemoteRpcs.write_single)(write_single)
            .handle(EventLogRemoteRpcs.write_chunked)(write_chunked)
            .handle(EventLogRemoteRpcs.changes)(changes_handler)
        )

    return EventLogRemoteRpcs.to_layer_effect(gen(make)).pipe(provide_merge(layer_auth_middleware))
