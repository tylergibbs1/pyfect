"""The worker transport of an RPC client (Effect's ``makeProtocolWorker``):
requests go to a pool of workers, each serving the group with
``rpc.server.layer_protocol_worker_runner``."""

from __future__ import annotations

import itertools
from dataclasses import dataclass
from typing import Any, cast, overload

from pyfect import schedule
from pyfect import schema as S
from pyfect._core import Effect
from pyfect.cause import Cause
from pyfect.duration import Duration
from pyfect.effect import gen, service_option, succeed, suspend, sync
from pyfect.latch import Latch
from pyfect.layer import Layer
from pyfect.layer import effect as layer_effect
from pyfect.pool import Pool
from pyfect.result import Ok
from pyfect.rpc.client._protocol import (
    ClientProtocol,
    ClientProtocolParts,
    ClientProtocolService,
    Message,
    WriteTo,
    with_run_client,
)
from pyfect.rpc.client._transports import ConnectionHooks
from pyfect.rpc.client_error import RpcClientDefect, RpcClientError
from pyfect.rpc.message import MalformedMessage, ServerMessage, decode_from_server
from pyfect.rpc.serialization import CodecFor
from pyfect.rpc.worker import InitialMessage
from pyfect.scope import Scope, add_finalizer, fork_scoped, scoped
from pyfect.workers.worker import Spawner, Worker, WorkerPlatform, WorkerPlatformService
from pyfect.workers.worker_error import WorkerError

_VOID: Effect[None] = succeed(None)

type _Backing = Worker[Message, Any]


@dataclass(frozen=True, slots=True)
class _Entry:
    client_id: int
    worker: _Backing
    latch: Latch


def _codec_for(schema: Any) -> Any:
    # Worker messages are values, so they do not depend on RpcSerialization.
    return S.to_codec_json(schema)


class _WorkerClient:
    __slots__ = ("_client_ids", "_entries", "_ids", "_initial", "_platform", "_write")

    def __init__(
        self,
        write: WriteTo,
        client_ids: set[int],
        platform: WorkerPlatformService,
        initial: Effect[tuple[object, tuple[object, ...]]] | None,
    ) -> None:
        self._write = write
        self._client_ids = client_ids
        self._platform = platform
        self._initial = initial
        self._entries: dict[object, _Entry] = {}
        self._ids = itertools.count()

    def _broadcast(self, response: Message) -> Effect[None]:
        @gen
        def deliver():
            for client_id in list(self._client_ids):
                yield from self._write(client_id, response)

        return deliver

    def _on_message(self, backing: _Backing, message: object) -> Effect[None]:
        try:
            responses = decode_from_server([message])
        except MalformedMessage as cause:
            return self._fail(backing, RpcClientDefect("Error decoding message", cause))
        return _VOID if not responses else self._on_response(responses[0])

    def _on_response(self, response: ServerMessage) -> Effect[None]:
        if response["_tag"] == "Pong":
            return _VOID
        if response["_tag"] == "Defect":
            for entry in self._entries.values():
                entry.latch.open_unsafe()
            self._entries.clear()
            return self._broadcast(response)
        request_id = response["requestId"]
        if response["_tag"] == "Exit":
            entry = self._entries.pop(request_id, None)
            if entry is not None:
                entry.latch.open_unsafe()
        else:
            entry = self._entries.get(request_id)
        if entry is not None:
            return self._write(entry.client_id, response)
        return self._broadcast(response)

    def _fail(self, backing: _Backing, reason: Any) -> Effect[None]:
        """Release the requests on ``backing`` and fail the clients'."""
        for request_id, entry in list(self._entries.items()):
            if entry.worker is backing:
                del self._entries[request_id]
                entry.latch.open_unsafe()
        return self._broadcast({"_tag": "ClientProtocolError", "error": RpcClientError(reason)})

    def _on_cause(self, backing: _Backing, cause: Cause[Any]) -> Effect[None]:
        found = cause.find_error()
        if isinstance(found, Ok) and isinstance(found.value, WorkerError):
            reason: Any = found.value.reason
        else:
            reason = RpcClientDefect("Error in worker", cause.squash())
        return self._fail(backing, reason)

    def acquire(self) -> Effect[_Backing, WorkerError, Any]:
        @gen
        def acquire():
            backing: _Backing = yield from self._platform.spawn(next(self._ids))
            initial = self._initial
            on_spawn = (
                None
                if initial is None
                else initial.flat_map(
                    lambda made: backing.send(
                        {"_tag": "InitialMessage", "value": made[0]}, made[1]
                    ).or_die()
                )
            )
            running = (
                backing.run(lambda message: self._on_message(backing, message), on_spawn=on_spawn)
                .tap_cause(lambda cause: self._on_cause(backing, cause))
                .retry(schedule.spaced("1 second"))
                .annotate_logs({"module": "RpcClient", "method": "makeProtocolWorker"})
                .interruptible()
            )
            yield from fork_scoped(running)
            return backing

        return acquire

    def close(self) -> None:
        for entry in self._entries.values():
            entry.latch.open_unsafe()
        self._entries.clear()

    def send_with(self, pool: Pool[_Backing, WorkerError]) -> Any:
        def send(client_id: int, request: Message) -> Effect[None, RpcClientError]:
            def body() -> Effect[None, RpcClientError]:
                tag = request.get("_tag")
                if tag == "Request":

                    def lent(worker: _Backing) -> Effect[None, WorkerError]:
                        latch = Latch(False)
                        self._entries[request["id"]] = _Entry(client_id, worker, latch)
                        return worker.send(request).flat_map(lambda _: latch.wait())

                    return scoped(pool.get().flat_map(lent)).or_die()
                if tag == "Interrupt":
                    entry = self._entries.pop(request["requestId"], None)
                    if entry is None:
                        return _VOID
                    entry.latch.open_unsafe()
                    return entry.worker.send(request).or_die()
                if tag == "Ack":
                    entry = self._entries.get(request["requestId"])
                    if entry is None:
                        return _VOID
                    return entry.worker.send(request).or_die()
                return _VOID

            return suspend(body)

        return send


type _Requirements = Scope | WorkerPlatform | Spawner


@overload
def make_protocol_worker(
    *, size: int, concurrency: int = 1, target_utilization: float = 1.0
) -> Effect[ClientProtocolService, WorkerError, _Requirements]: ...
@overload
def make_protocol_worker(
    *,
    min_size: int,
    max_size: int,
    time_to_live: Duration,
    concurrency: int = 1,
    target_utilization: float = 1.0,
) -> Effect[ClientProtocolService, WorkerError, _Requirements]: ...
def make_protocol_worker(
    *,
    size: int | None = None,
    min_size: int | None = None,
    max_size: int | None = None,
    time_to_live: Duration | None = None,
    concurrency: int = 1,
    target_utilization: float = 1.0,
) -> Effect[ClientProtocolService, WorkerError, _Requirements]:
    """A client protocol over a pool of workers from the ``WorkerPlatform``:
    ``size`` of them, or between ``min_size`` and ``max_size`` with idle
    ones above ``min_size`` released after ``time_to_live``. Each worker
    serves ``concurrency`` requests at a time; a worker that fails is
    respawned a second later, and its requests get a
    ``ClientProtocolError``. An ``InitialMessage`` in the context is sent
    to each worker first."""
    ranged = (min_size, max_size, time_to_live)
    sized = size is not None and all(option is None for option in ranged)
    bounded = size is None and all(option is not None for option in ranged)
    if not (sized or bounded):
        raise TypeError(
            "make_protocol_worker takes size=, or min_size=, max_size= and time_to_live="
        )

    def parts(
        write: WriteTo, client_ids: set[int]
    ) -> Effect[ClientProtocolParts, WorkerError, Any]:
        @gen
        def make():
            platform = yield from WorkerPlatform()
            initial = yield from service_option(InitialMessage)
            hooks = yield from ConnectionHooks()
            client = _WorkerClient(
                write, client_ids, platform, None if initial is None else initial.value
            )
            acquire = client.acquire()
            if size is not None:
                pool = yield from Pool.make(
                    acquire,
                    size=size,
                    concurrency=concurrency,
                    target_utilization=target_utilization,
                )
            else:
                pool = yield from Pool.make_with_ttl(
                    acquire,
                    min=cast("int", min_size),
                    max=cast("int", max_size),
                    time_to_live=cast("Duration", time_to_live),
                    concurrency=concurrency,
                    target_utilization=target_utilization,
                )
            yield from add_finalizer(lambda _: sync(client.close))
            yield from scoped(pool.get())
            if hooks is not None:
                yield from hooks.on_connect
            return ClientProtocolParts(client.send_with(pool), True, cast("CodecFor", _codec_for))

        return make

    return cast("Effect[ClientProtocolService, WorkerError, _Requirements]", with_run_client(parts))


@overload
def layer_protocol_worker(
    *, size: int, concurrency: int = 1, target_utilization: float = 1.0
) -> Layer[ClientProtocol, WorkerError, WorkerPlatform | Spawner]: ...
@overload
def layer_protocol_worker(
    *,
    min_size: int,
    max_size: int,
    time_to_live: Duration,
    concurrency: int = 1,
    target_utilization: float = 1.0,
) -> Layer[ClientProtocol, WorkerError, WorkerPlatform | Spawner]: ...
def layer_protocol_worker(
    **options: Any,
) -> Layer[ClientProtocol, WorkerError, WorkerPlatform | Spawner]:
    """``make_protocol_worker`` as a layer."""
    return layer_effect(ClientProtocol, make_protocol_worker(**options))


__all__ = ["layer_protocol_worker", "make_protocol_worker"]
