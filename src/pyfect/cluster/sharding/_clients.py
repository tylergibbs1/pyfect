"""Entity clients: one RPC client per entity type, whose messages are
routed by ``send_outgoing`` and whose replies come back through each
request's ``respond``."""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from typing import TYPE_CHECKING, Any, Never

from pyfect._concurrency import for_each
from pyfect._core import Effect, _WithFiber
from pyfect._fiber import Fiber
from pyfect.cluster import _interruptors as active_teardown
from pyfect.cluster._resource_map import ResourceMap
from pyfect.cluster.cluster_schema import (
    ClientTracingEnabled,
    Persisted,
    is_uninterruptible_for_client,
)
from pyfect.cluster.entity._services import CurrentAddress
from pyfect.cluster.entity_address import EntityAddress
from pyfect.cluster.entity_id import EntityId
from pyfect.cluster.envelope import AckChunk, Interrupt, make_request
from pyfect.cluster.message import OutgoingEnvelope, OutgoingRequest, dynamic_annotations
from pyfect.cluster.reply import Chunk, Reply
from pyfect.cluster.snowflake import Snowflake
from pyfect.context import Context, Tag
from pyfect.effect import gen, succeed, suspend, sync
from pyfect.rpc import message as rpc_message
from pyfect.rpc._methods import CallOptions, StreamMethod, UnaryMethod
from pyfect.rpc.client._core import ClientCore, ClientOptions, OnFromClient
from pyfect.rpc.client._core import make_no_serialization as make_client_core
from pyfect.scope import Scope

from ._routing import Routing
from ._singletons import SingletonShard
from ._state import ClientRequestEntry, ShardingState

if TYPE_CHECKING:
    from pyfect.cluster.entity import Entity

_VOID: Effect[None] = succeed(None)


class ClientAddress(Tag[EntityAddress], key="effect/cluster/Sharding/ClientAddress"):
    """The address a client call is for."""


def _respond_discard(_: Reply) -> Effect[None]:
    return _VOID


class Clients:
    __slots__ = ("_clients", "_routing", "_state")

    def __init__(
        self,
        state: ShardingState,
        routing: Routing,
        clients: ResourceMap[type[Entity], Callable[[str], Any], Never],
    ) -> None:
        self._state = state
        self._routing = routing
        self._clients = clients

    @staticmethod
    def make(state: ShardingState, routing: Routing) -> Effect[Clients, Never, Scope]:
        holder: list[Clients] = []

        def lookup(entity: type[Entity]) -> Effect[Callable[[str], Any], Never, Scope]:
            return holder[0]._make_client(entity)

        def build(clients: ResourceMap[type[Entity], Callable[[str], Any], Never]) -> Clients:
            made = Clients(state, routing, clients)
            holder.append(made)
            return made

        return ResourceMap.make(lookup).map(build)

    def get(self, entity: type[Entity]) -> Effect[Callable[[str], Any]]:
        return self._clients.get(entity)

    # --- abandoning callers ---------------------------------------------------------------

    def abandon_undelivered(
        self, address: EntityAddress, is_delivered: Callable[[Snowflake], bool]
    ) -> Effect[None]:
        """During shutdown, abandon local callers parked on persisted
        requests a retiring entity never started: the next owner serves
        them. On a runner that keeps running they stay waiting."""
        state = self._state

        def run() -> Effect[None]:
            if not state.is_shutdown:
                return _VOID
            abandon: list[Effect[None]] = []
            for request_id, entry in list(state.client_requests.items()):
                if (
                    not entry.message.annotations.get(Persisted)
                    or entry.message.envelope.address != address
                    or is_delivered(request_id)
                ):
                    continue
                abandon.append(state.storage.unregister_reply_handler(request_id, interrupt=True))
            return for_each(abandon, lambda effect: effect).as_void()

        return suspend(run)

    # --- one entity type ------------------------------------------------------------------

    def _on_from_client(  # noqa: PLR0911
        self, entity: type[Entity], cores: list[ClientCore], sent: OnFromClient
    ) -> Effect[None, Any]:
        state = self._state
        routing = self._routing
        address = sent.context.get_unsafe(ClientAddress)
        message = sent.message
        if isinstance(message, rpc_message.Request):
            request = message

            def body(fiber: Fiber[Any, Any]) -> Effect[None, Any]:
                request_id = Snowflake(int(request.id))
                rpc = entity.rpcs[request.tag]
                envelope = make_request(
                    request_id=request_id,
                    address=address,
                    tag=request.tag,
                    payload=request.payload,
                    headers=request.headers,
                    trace_id=request.trace_id,
                    span_id=request.span_id,
                    sampled=request.sampled,
                )
                entry: ClientRequestEntry

                def respond(reply: Reply) -> Effect[None]:
                    if isinstance(reply, Chunk):
                        entry.last_chunk_id = reply.id
                        return cores[0].write(
                            rpc_message.ResponseChunk(0, reply.request_id, reply.values)
                        )
                    state.client_requests.pop(reply.request_id, None)
                    return cores[0].write(rpc_message.ResponseExit(0, reply.request_id, reply.exit))

                outgoing = OutgoingRequest(
                    envelope=envelope,
                    last_received_reply=None,
                    rpc=rpc,
                    context=fiber._context,
                    respond=_respond_discard if sent.discard else respond,
                    annotations=dynamic_annotations(rpc, envelope),
                )
                if not sent.discard:
                    entry = ClientRequestEntry(rpc, fiber._context, outgoing)
                    state.client_requests[request_id] = entry
                return routing.send_outgoing(outgoing, sent.discard)

            return _WithFiber(body)
        if isinstance(message, rpc_message.Ack):
            request_id = Snowflake(int(message.request_id))
            entry = state.client_requests.get(request_id)
            if entry is None or entry.last_chunk_id is None:
                return _VOID
            ack = OutgoingEnvelope(
                envelope=AckChunk(
                    id=state.snowflakes.next_unsafe(),
                    address=address,
                    request_id=request_id,
                    reply_id=entry.last_chunk_id,
                ),
                rpc=entry.rpc,
            )
            return routing.send_outgoing(ack, False, None, entry.runner)
        if isinstance(message, rpc_message.Interrupt):
            request_id = Snowflake(int(message.request_id))
            entry = state.client_requests.pop(request_id, None)
            if entry is None:
                return _VOID
            if is_uninterruptible_for_client(entry.message.annotations):
                return _VOID
            # Durable messages ignore interrupts on shutdown or from a shard
            # being reassigned.
            caller = entry.context.get_option(CurrentAddress)
            singleton_shard = entry.context.get_option(SingletonShard)
            transient = (
                state.is_shutdown
                or (caller is not None and active_teardown.is_active(caller.value))
                or (
                    singleton_shard is not None
                    and active_teardown.is_shard_active(singleton_shard.value)
                )
            )
            if transient and entry.message.annotations.get(Persisted):
                return _VOID
            interrupt = OutgoingEnvelope(
                envelope=Interrupt(
                    id=state.snowflakes.next_unsafe(), address=address, request_id=request_id
                ),
                rpc=entry.rpc,
            )
            return routing.send_outgoing(interrupt, False, 3, entry.runner).ignore()
        return _VOID

    def _make_client(self, entity: type[Entity]) -> Effect[Callable[[str], Any], Never, Scope]:
        state = self._state
        clients = self

        def run():
            scope = yield from Scope()
            yield from scope.add_finalizer(
                lambda _: sync(lambda: active_teardown.release_entity_type(entity.type))
            )
            cores: list[ClientCore] = []
            _, core = yield from make_client_core(
                entity.protocol,
                lambda sent: clients._on_from_client(entity, cores, sent),
                ClientOptions(
                    span_prefix=f"{entity.type}.client",
                    disable_tracing=not entity.annotations.get(ClientTracingEnabled),
                    supports_ack=True,
                    generate_request_id=state.snowflakes.next_unsafe,
                ),
            )
            cores.append(core)
            yield from scope.add_finalizer(
                lambda _: sync(lambda: active_teardown.acquire_entity_type(entity.type))
            )

            def client_for(entity_id: str) -> Any:
                id = EntityId(entity_id)
                address = EntityAddress(
                    shard_id=state.get_shard_id(id, entity.get_shard_group(id)),
                    entity_id=id,
                    entity_type=entity.type,
                )
                address_context = Context.make(ClientAddress, address)

                def with_address(call: CallOptions) -> CallOptions:
                    merged = (
                        address_context
                        if call.context is None
                        else call.context.merge(address_context)
                    )
                    return replace(call, context=merged)

                methods: dict[str, Any] = {}
                for rpc in entity.rpcs.values():
                    if rpc.is_stream:
                        methods[rpc.tag] = StreamMethod[Any, Any, Any](
                            lambda payload, call, rpc=rpc: core.open_stream(
                                rpc, payload, with_address(call)
                            )
                        )
                    else:
                        methods[rpc.tag] = UnaryMethod[Any, Any, Any](
                            lambda payload, call, rpc=rpc: core.call(
                                rpc, payload, with_address(call)
                            )
                        )
                client = entity()
                client._rpc_methods = methods
                return client

            return client_for

        return gen(run)


__all__ = ["ClientAddress", "Clients"]
