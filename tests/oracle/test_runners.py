"""Ports of Effect's ``test/cluster/Runners.test.ts``. Each test's
docstring is the Effect test title.

"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable, Mapping
from dataclasses import replace
from typing import Any, Never, TypedDict, cast
from urllib.parse import SplitResult

import pyfect as fx
from pyfect import exit as Exit
from pyfect import schema as S
from pyfect import stream, testing
from pyfect.cluster import envelope, http_runner, sharding_config, snowflake
from pyfect.cluster.cluster_error import (
    MalformedMessage,
    PersistenceError,
    RunnerUnavailable,
)
from pyfect.cluster.cluster_schema import Persisted
from pyfect.cluster.entity import Entity
from pyfect.cluster.entity_address import EntityAddress
from pyfect.cluster.entity_id import EntityId
from pyfect.cluster.entity_type import EntityType
from pyfect.cluster.message import IncomingLocal, IncomingRequestLocal, OutgoingRequest, serialize
from pyfect.cluster.message_storage import (
    MessageStorage,
    MessageStorageService,
    SaveResult,
    StorageBase,
    layer_memory,
    layer_noop,
)
from pyfect.cluster.reply import Reply, ReplyWithContext, WithExit
from pyfect.cluster.runner_address import RunnerAddress
from pyfect.cluster.runners import (
    RpcClientProtocol,
    RpcClientProtocolService,
    Rpcs,
    Runners,
    layer_rpc,
)
from pyfect.cluster.runners import (
    layer_noop as runners_layer_noop,
)
from pyfect.cluster.shard_id import ShardId
from pyfect.cluster.snowflake import Generator, Snowflake
from pyfect.context import Context
from pyfect.deferred import Deferred
from pyfect.duration import Seconds
from pyfect.errors import Done
from pyfect.http import client as http_client
from pyfect.http import response as http_response
from pyfect.http.client import HttpClient
from pyfect.http.request import HttpClientRequest
from pyfect.layer import Layer
from pyfect.rpc import client as rpc_client
from pyfect.rpc import make as make_rpc
from pyfect.rpc import rpc_schema, serialization
from pyfect.rpc.client import ClientProtocolService
from pyfect.rpc.client_error import RpcClientError
from pyfect.rpc.group import RpcGroup
from pyfect.rpc.serialization import CodecFor
from pyfect.rpc.test import make_client
from pyfect.scope import fork_scoped
from pyfect.socket import SocketCloseError, WebSocketConstructor

from ._runner_server_handlers import make_handlers, make_request

runner_address = RunnerAddress(host="localhost", port=42_000)

test_config = replace(
    sharding_config.DEFAULTS,
    entity_mailbox_capacity=10,
    entity_termination_timeout=fx.duration.Seconds(0),
    entity_message_poll_interval=fx.duration.Seconds(5),
    send_retry_interval=fx.duration.Seconds(0.1),
    refresh_assignments_interval=fx.duration.Seconds(0),
)


class IdPayload(S.Class):
    id: int


TestRpc = make_rpc("TestRpc", success=S.Int, payload=IdPayload).annotate(Persisted, False)
TestRpcPersisted = make_rpc("TestRpcPersisted", success=S.Int, payload=IdPayload).annotate(
    Persisted, True
)


def _make_outgoing_request(
    rpc: Any, request_id: Snowflake, respond: Callable[[Reply], fx.Effect[None]]
) -> OutgoingRequest:
    return OutgoingRequest(
        envelope=envelope.make_request(
            request_id=request_id,
            address=EntityAddress(
                shard_id=ShardId(group="default", id=1),
                entity_type=EntityType("TestRpcEntity"),
                entity_id=EntityId("1"),
            ),
            tag=rpc.tag,
            payload=IdPayload(id=1),
        ),
        rpc=rpc,
        context=Context.empty(),
        last_received_reply=None,
        respond=respond,
        annotations=Context.empty(),
    )


def _ignore(_: Reply) -> fx.Effect[None]:
    return fx.void


def _codec_for_json(schema: S.Top) -> S.Codec[Any, Any, Any, Any]:
    return S.to_codec_json(schema)


def _codec_for_json_string(schema: S.Top) -> S.Codec[Any, Any, Any, Any]:
    """Observably unlike JSON: the encoded value is JSON text."""
    return S.from_json_string(S.to_codec_json(schema))


type _Write = Callable[[Mapping[str, Any]], fx.Effect[None]]
type _OnRequest = Callable[[Mapping[str, Any], _Write], fx.Effect[None, RpcClientError]]


def _layer_fake_protocol(
    on_request: _OnRequest, codec_for: CodecFor = _codec_for_json
) -> Layer[RpcClientProtocol]:
    def make(_: RunnerAddress) -> fx.Effect[ClientProtocolService]:
        writes: list[_Write] = []

        def run(_client_id: int, f: _Write) -> fx.Effect[Never]:
            writes.append(f)
            return fx.never

        def send(_client_id: int, request: Mapping[str, Any]) -> fx.Effect[None, RpcClientError]:
            return on_request(request, writes[-1])

        return fx.sync(lambda: ClientProtocolService(run, send, True, codec_for))

    return fx.layer.succeed(RpcClientProtocol, RpcClientProtocolService(make, codec_for))


def _layer_runners(
    protocol: Layer[RpcClientProtocol],
) -> Layer[Runners | Generator | MessageStorage]:
    return (
        layer_rpc.pipe(fx.layer.provide_merge(snowflake.layer_generator))
        .pipe(fx.layer.provide(protocol))
        .pipe(fx.layer.provide_merge(layer_noop))
        .pipe(fx.layer.provide(sharding_config.layer(test_config)))
    )


class _WrappedBase:
    """A storage base with some methods replaced."""

    def __init__(self, base: Any, **overrides: Callable[..., Any]) -> None:
        self._base = base
        self._overrides = overrides

    def __getattr__(self, name: str) -> Any:
        found = self._overrides.get(name)
        return getattr(self._base, name) if found is None else found


def _layer_local_runners(
    wrap: Callable[[MessageStorageService], MessageStorageService] = lambda storage: storage,
) -> Layer[Runners | MessageStorage | Generator]:
    wrapped = fx.layer.effect(MessageStorage, MessageStorage().map(wrap)).pipe(
        fx.layer.provide(layer_memory)
    )
    config = replace(sharding_config.DEFAULTS, entity_reply_poll_interval=fx.duration.Seconds(3600))
    return (
        runners_layer_noop.pipe(fx.layer.provide_merge(wrapped))
        .pipe(fx.layer.provide_merge(snowflake.layer_generator))
        .pipe(fx.layer.provide(sharding_config.layer(config)))
    )


def _wrap(storage: MessageStorageService, **overrides: Callable[..., Any]) -> MessageStorageService:
    return MessageStorageService(cast("StorageBase", _WrappedBase(storage.base, **overrides)))


def _save_reply(
    storage: MessageStorageService, message: OutgoingRequest, id: Snowflake
) -> fx.Effect[None, PersistenceError | MalformedMessage]:
    return storage.save_reply(
        ReplyWithContext(
            WithExit(request_id=message.envelope.request_id, id=id, exit=Exit.succeed(42)),
            message.context,
            message.rpc,
        )
    )


def _exits(replies: list[Exit.Exit[Any, Any]]) -> Callable[[Reply], fx.Effect[None]]:
    def respond(reply: Reply) -> fx.Effect[None]:
        def record() -> None:
            if isinstance(reply, WithExit):
                replies.append(reply.exit)

        return fx.sync(record)

    return respond


def _no_notify(_: IncomingLocal) -> fx.Effect[None]:
    return fx.void


@testing.effect
def test_delivers_a_persisted_local_reply_completed_before_save_request_returns():
    """delivers a persisted local reply completed before saveRequest returns"""
    complete: list[fx.Effect[None]] = [fx.void]

    def wrap(storage: MessageStorageService) -> MessageStorageService:
        def save_request(message: OutgoingRequest) -> fx.Effect[SaveResult, Any]:
            return storage.base.save_request(message).tap(lambda _: complete[0])

        return _wrap(storage, save_request=save_request)

    @fx.gen
    def body():
        runners = yield from Runners()
        storage = yield from MessageStorage()
        snowflakes = yield from Generator()
        replies: list[Exit.Exit[Any, Any]] = []
        message = _make_outgoing_request(
            TestRpcPersisted, snowflakes.next_unsafe(), _exits(replies)
        )
        complete[0] = _save_reply(storage, message, snowflakes.next_unsafe()).or_die()
        pending = yield from fork_scoped(
            runners.notify_local(message, notify=_no_notify, discard=False).timeout_option(
                "1 second"
            )
        )
        yield from testing.adjust("1 second")
        assert (yield from pending.join()) is not None, "the caller must complete"
        assert replies == [Exit.succeed(42)]

    yield from body.pipe(fx.provide(_layer_local_runners(wrap)))


@testing.effect
def test_answers_a_fresh_local_request_without_reading_or_polling_storage():
    """answers a fresh local request without reading or polling storage"""
    reads = [0]

    def wrap(storage: MessageStorageService) -> MessageStorageService:
        def replies_for(messages: Iterable[OutgoingRequest]) -> fx.Effect[list[Reply], Any]:
            def run() -> fx.Effect[list[Reply], Any]:
                reads[0] += 1
                return storage.base.replies_for(messages)

            return fx.suspend(run)

        return _wrap(storage, replies_for=replies_for)

    @fx.gen
    def body():
        runners = yield from Runners()
        storage = yield from MessageStorage()
        snowflakes = yield from Generator()
        replies: list[Exit.Exit[Any, Any]] = []
        message = _make_outgoing_request(
            TestRpcPersisted, snowflakes.next_unsafe(), _exits(replies)
        )
        pending = yield from fork_scoped(
            runners.notify_local(message, notify=_no_notify, discard=False).timeout_option(
                Seconds(4 * 3600)
            )
        )
        # Pass three one-hour poll intervals while the request waits.
        yield from testing.adjust(Seconds(3 * 3600))
        assert reads[0] == 0, "a parked fresh local request must not be read from storage"
        yield from _save_reply(storage, message, snowflakes.next_unsafe())
        yield from testing.adjust(0)
        assert (yield from pending.join()) is not None, "the caller must complete"
        assert replies == [Exit.succeed(42)]
        assert reads[0] == 0, "reply delivery must not read storage"

    yield from body.pipe(fx.provide(_layer_local_runners(wrap)))


@testing.effect
def test_keeps_a_duplicate_local_waiter_alive_when_the_first_caller_cancels():
    """keeps a duplicate local waiter alive when the first caller cancels"""

    @fx.gen
    def body():
        runners = yield from Runners()
        storage = yield from MessageStorage()
        snowflakes = yield from Generator()
        request_id = snowflakes.next_unsafe()
        first_replies: list[Reply] = []
        duplicate_replies: list[Exit.Exit[Any, Any]] = []

        def record_first(reply: Reply) -> fx.Effect[None]:
            return fx.sync(lambda: first_replies.append(reply))

        first = _make_outgoing_request(TestRpcPersisted, request_id, record_first)
        duplicate = _make_outgoing_request(TestRpcPersisted, request_id, _exits(duplicate_replies))

        def notify(message: OutgoingRequest) -> fx.Effect[None, PersistenceError]:
            return runners.notify_local(message, notify=_no_notify, discard=False)

        a = yield from fork_scoped(notify(first))
        yield from testing.adjust(0)
        b = yield from fork_scoped(notify(duplicate).timeout_option("1 second"))
        yield from testing.adjust(0)
        yield from a.interrupt()
        yield from _save_reply(storage, first, snowflakes.next_unsafe())
        # Drain runnable work without reaching the one-hour polling deadline.
        yield from testing.adjust(0)
        assert first_replies == []
        assert duplicate_replies == [Exit.succeed(42)]
        assert (yield from b.join()) is not None, (
            "the surviving caller must complete without polling"
        )

    yield from body.pipe(fx.provide(_layer_local_runners()))


@testing.effect
def test_uses_the_client_protocol_codec_for_simulated_remote_serialization():
    """uses the client protocol codec for simulated remote serialization"""
    codec_calls = [0]

    def codec_for(schema: S.Top) -> S.Codec[Any, Any, Any, Any]:
        codec_calls[0] += 1
        return S.from_json_string(S.to_codec_json(schema))

    @fx.gen
    def body():
        runners = yield from Runners()
        snowflakes = yield from Generator()
        message = _make_outgoing_request(TestRpc, snowflakes.next_unsafe(), _ignore)

        def send(incoming: IncomingLocal) -> fx.Effect[None]:
            def check() -> None:
                assert isinstance(incoming, IncomingRequestLocal)
                assert incoming.envelope.payload.id == 1

            return fx.sync(check)

        yield from runners.send_local(message, send=send, simulate_remote_serialization=True)
        assert codec_calls[0] == 2
        assert message.encoded_cache is not None
        assert message.encoded_cache.codec_for is codec_for
        encoded = yield from serialize(message, _codec_for_json)
        assert isinstance(encoded, envelope.Request)
        assert encoded.payload == {"id": 1}
        assert message.encoded_cache.codec_for is _codec_for_json

    protocol = _layer_fake_protocol(lambda _request, _write: fx.void, codec_for)
    yield from body.pipe(fx.provide(_layer_runners(protocol)))


def _respond_with_defect(request: Mapping[str, Any], write: _Write) -> fx.Effect[None]:
    if request["_tag"] == "Request":
        return write({"_tag": "Defect", "defect": "boom"})
    return fx.void


def _fail_transport(_request: Mapping[str, Any], _write: _Write) -> fx.Effect[None, RpcClientError]:
    return fx.fail(RpcClientError(reason=SocketCloseError(code=1006)))


@testing.effect
def test_a_server_delivered_defect_resolves_the_request_instead_of_runner_unavailable():
    """a server-delivered defect resolves the request instead of RunnerUnavailable"""

    @fx.gen
    def body():
        runners = yield from Runners()
        snowflakes = yield from Generator()
        replies: list[Reply] = []

        def record(reply: Reply) -> fx.Effect[None]:
            return fx.sync(lambda: replies.append(reply))

        message = _make_outgoing_request(TestRpc, snowflakes.next_unsafe(), record)
        exit = yield from runners.send(runner_address, message).exit()
        assert isinstance(exit, Exit.Success), (
            "send must not fail with RunnerUnavailable for a delivered defect"
        )
        assert len(replies) == 1
        reply = replies[0]
        assert isinstance(reply, WithExit) and isinstance(reply.exit, Exit.Failure)
        assert "boom" in str(reply.exit.cause.squash()), "the reply must carry the server defect"

    yield from body.pipe(fx.provide(_layer_runners(_layer_fake_protocol(_respond_with_defect))))


@testing.effect
def test_transport_failures_still_map_to_runner_unavailable():
    """transport failures still map to RunnerUnavailable"""

    @fx.gen
    def body():
        runners = yield from Runners()
        snowflakes = yield from Generator()
        message = _make_outgoing_request(TestRpc, snowflakes.next_unsafe(), _ignore)
        exit = yield from runners.send(runner_address, message).exit()
        assert isinstance(exit, Exit.Failure), "send must fail for a transport failure"
        assert isinstance(exit.cause.squash(), RunnerUnavailable)

    yield from body.pipe(fx.provide(_layer_runners(_layer_fake_protocol(_fail_transport))))


@testing.effect
def test_volatile_notification_transport_failures_map_to_runner_unavailable():
    """volatile notification transport failures map to RunnerUnavailable"""

    @fx.gen
    def body():
        runners = yield from Runners()
        snowflakes = yield from Generator()
        message = _make_outgoing_request(TestRpc, snowflakes.next_unsafe(), _ignore)
        exit = yield from runners.notify(runner_address, message, discard=True).exit()
        assert isinstance(exit, Exit.Failure), "volatile notification must fail when delivery fails"
        assert isinstance(exit.cause.squash(), RunnerUnavailable)

    yield from body.pipe(fx.provide(_layer_runners(_layer_fake_protocol(_fail_transport))))


@testing.effect
def test_persisted_notification_transport_failures_are_ignored():
    """persisted notification transport failures are ignored"""

    @fx.gen
    def body():
        runners = yield from Runners()
        snowflakes = yield from Generator()
        message = _make_outgoing_request(TestRpcPersisted, snowflakes.next_unsafe(), _ignore)
        yield from runners.notify(runner_address, message, discard=True)

    yield from body.pipe(fx.provide(_layer_runners(_layer_fake_protocol(_fail_transport))))


@testing.effect
def test_a_delivered_defect_for_a_persisted_request_maps_to_runner_unavailable():
    """a delivered defect for a persisted request maps to RunnerUnavailable for storage recovery"""

    @fx.gen
    def body():
        runners = yield from Runners()
        snowflakes = yield from Generator()
        message = _make_outgoing_request(TestRpcPersisted, snowflakes.next_unsafe(), _ignore)
        exit = yield from runners.send(runner_address, message).exit()
        assert isinstance(exit, Exit.Failure), (
            "send must fail for a delivered defect on a persisted request"
        )
        assert isinstance(exit.cause.squash(), RunnerUnavailable)

    yield from body.pipe(fx.provide(_layer_runners(_layer_fake_protocol(_respond_with_defect))))


@testing.effect
def test_encodes_the_entity_payload_with_the_protocol_codec_and_leaves_the_hole_untouched():
    """encodes the entity payload with the protocol codec and leaves the hole untouched"""
    sent: list[Mapping[str, Any]] = []

    def on_request(request: Mapping[str, Any], write: _Write) -> fx.Effect[None]:
        sent.append(request)
        # the defect hole is filled by the same codec
        if request["_tag"] == "Request":
            return write({"_tag": "Defect", "defect": json.dumps("boom")})
        return fx.void

    @fx.gen
    def body():
        runners = yield from Runners()
        snowflakes = yield from Generator()
        message = _make_outgoing_request(TestRpc, snowflakes.next_unsafe(), _ignore)
        yield from runners.send(runner_address, message)
        assert len(sent) == 1
        request = sent[0]
        assert request["_tag"] == "Request", "expected a runner Request"
        # the outer runner payload is filled by the protocol codec
        assert isinstance(request["payload"], str)
        outer = json.loads(request["payload"])
        # the entity payload was encoded with the same codec and carried
        # through the opaque hole without being re-encoded
        assert outer["request"]["payload"] == json.dumps({"id": 1}, separators=(",", ":"))

    protocol = _layer_fake_protocol(on_request, _codec_for_json_string)
    yield from body.pipe(fx.provide(_layer_runners(protocol)))


class _PingRpcs(RpcGroup):
    ping = make_rpc("Ping", success=S.String)


_http_runner_address = RunnerAddress(host="localhost", port=8080)


@testing.effect
def test_http_runner_preserves_a_leading_slash_in_http_client_paths():
    """preserves a leading slash in HTTP client paths"""
    urls: list[str] = []

    def send(request: HttpClientRequest, url: SplitResult, _signal: Any, _fiber: Any) -> Any:
        def respond() -> Any:
            urls.append(request.url)
            body = '[{"_tag":"Exit","requestId":"0","exit":{"_tag":"Success","value":"pong"}}]'
            return http_response.make(request, body)

        return fx.sync(respond)

    @fx.gen
    def body():
        runner_protocol = yield from RpcClientProtocol()
        protocol = yield from runner_protocol.make(_http_runner_address)
        client = yield from rpc_client.make(
            _PingRpcs, rpc_client.ClientOptions(generate_request_id=lambda: "0")
        ).pipe(fx.provide_service(rpc_client.ClientProtocol, protocol))
        yield from client.ping()
        assert urls == ["http://localhost:8080/runner/"]

    yield from fx.scoped(
        body.pipe(fx.provide(http_runner.layer_client_protocol_http(path="/runner")))
        .pipe(fx.provide(serialization.layer_json))
        .pipe(fx.provide_service(HttpClient, http_client.make(send)))
    )


class _OpenWebSocket:
    ready_state = 1

    def add_event_listener(self, type: Any, listener: Any, *, once: bool = False) -> None:
        pass

    def remove_event_listener(self, type: Any, listener: Any) -> None:
        pass

    def close(self, code: int | None = None, reason: str | None = None) -> None:
        pass

    def send(self, data: bytes | str) -> None:
        pass


@testing.effect
def test_http_runner_preserves_a_leading_slash_in_websocket_client_paths():
    """preserves a leading slash in WebSocket client paths"""
    urls: list[str] = []

    def construct(url: str, _options: Any) -> _OpenWebSocket:
        urls.append(url)
        return _OpenWebSocket()

    @fx.gen
    def body():
        connected = yield from Deferred[None, Never].make()
        hooks = rpc_client.ConnectionHooksService(connected.succeed(None).as_void(), fx.void)

        @fx.gen
        def connect():
            runner_protocol = yield from RpcClientProtocol()
            protocol = yield from runner_protocol.make(_http_runner_address)
            yield from fork_scoped(protocol.run(0, lambda _: fx.void))
            yield from connected.wait()
            assert urls == ["ws://localhost:8080/runner"]

        yield from fx.scoped(
            connect.pipe(fx.provide(http_runner.layer_client_protocol_websocket(path="/runner")))
            .pipe(fx.provide(serialization.layer_json))
            .pipe(fx.provide_service(WebSocketConstructor, construct))
            .pipe(fx.provide_service(rpc_client.ConnectionHooks, hooks))
        )

    yield from body


# --- RunnerServer ----------------------------------------------------------------------


class _IdPayload(TypedDict):
    id: float


class BadReplyEntity(Entity, type="BadReplyEntity"):
    """An entity whose replies cannot be serialized: the handlers return
    non-integers for an ``S.Int`` success schema, so ``Reply.serialize``
    fails on encode."""

    bad_reply = make_rpc("BadReply", success=S.Int, payload=S.Struct(_IdPayload))
    bad_stream = make_rpc(
        "BadStream", success=rpc_schema.Stream(S.Int, S.Never), payload=S.Struct(_IdPayload)
    )


BadReplyEntityVolatile = BadReplyEntity.annotate_rpcs(Persisted, False)

_bad_reply_handlers = make_handlers(
    BadReplyEntityVolatile.to_layer(
        BadReplyEntityVolatile.handlers()
        .handle(BadReplyEntityVolatile.bad_reply)(lambda _: fx.succeed(cast("int", 1.5)))
        .handle(BadReplyEntityVolatile.bad_stream)(lambda _: stream.make(cast("int", 2.5)))
    )
)


@testing.effect
def test_a_reply_that_fails_to_serialize_fails_only_its_own_request():
    """a reply that fails to serialize fails only its own request"""

    @fx.gen
    def body():
        yield from testing.adjust("1 millis")
        client = yield from make_client(Rpcs)
        request = yield from make_request(BadReplyEntityVolatile, "bad-1", tag="BadReply")
        exit = yield from client.effect({"request": request, "persisted": False}).exit()
        assert isinstance(exit, Exit.Success), (
            "Effect rpc must not defect on a reply serialization failure"
        )
        reply = cast("dict[str, Any]", exit.value)
        assert reply["_tag"] == "WithExit"
        assert reply["exit"]["_tag"] == "Failure", "expected a WithExit reply with a failure exit"
        assert reply["requestId"] == str(request.request_id)
        dies = [r for r in reply["exit"]["cause"] if r["_tag"] == "Die"]
        assert dies, "the reply exit must carry the encode failure as a defect"
        assert "MalformedMessage" in json.dumps(dies[0]), (
            "the defect must identify the encode failure"
        )

    yield from fx.scoped(body).pipe(fx.provide(_bad_reply_handlers))


@testing.effect
def test_a_stream_reply_that_fails_to_serialize_ends_the_stream_with_the_defect():
    """a stream reply that fails to serialize ends the stream with the defect"""

    @fx.gen
    def body():
        yield from testing.adjust("1 millis")
        client = yield from make_client(Rpcs)
        request = yield from make_request(BadReplyEntityVolatile, "bad-2", tag="BadStream")
        queue = yield from client.stream({"request": request, "persisted": False}, as_queue=True)
        replies: list[Any] = []
        yield from (
            queue.take().map(replies.append).forever().pipe(fx.catch_tag(Done, lambda _: fx.void))
        )
        assert len(replies) == 1
        last = cast("dict[str, Any]", replies[0])
        assert last["_tag"] == "WithExit"
        assert last["exit"]["_tag"] == "Failure", (
            "expected a terminal WithExit reply with a failure exit"
        )
        assert last["requestId"] == str(request.request_id)
        assert "MalformedMessage" in json.dumps(last["exit"]["cause"]), (
            "the defect must identify the encode failure"
        )

    yield from fx.scoped(body).pipe(fx.provide(_bad_reply_handlers))
