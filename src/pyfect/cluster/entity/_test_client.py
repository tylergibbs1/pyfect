"""In-memory clients of an entity layer (Effect's
``Entity.makeTestClient``): no sharding, no serialization, one server per
entity id."""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any, Never, overload

from pyfect import layer as layer_
from pyfect._core import Effect, _Locally
from pyfect._layer_core import require_layer
from pyfect.cluster._entity_activation import CurrentActivationScope
from pyfect.cluster._hash import shard_number
from pyfect.cluster._resource_map import ResourceMap
from pyfect.cluster.entity._request import Request
from pyfect.cluster.entity._services import CurrentAddress, CurrentRunnerAddress
from pyfect.cluster.entity_address import EntityAddress
from pyfect.cluster.entity_id import EntityId
from pyfect.cluster.message import Incoming, Outgoing
from pyfect.cluster.runner_address import RunnerAddress
from pyfect.cluster.shard_id import ShardId
from pyfect.cluster.sharding import Sharding
from pyfect.cluster.sharding_config import ShardingConfig
from pyfect.cluster.snowflake import Snowflake, make_generator
from pyfect.context import Context
from pyfect.effect import context, die, fn_untraced, gen
from pyfect.layer import Layer
from pyfect.rpc import message as rpc_message
from pyfect.rpc.client._core import ClientCore, ClientOptions, OnFromClient
from pyfect.rpc.client._core import make_no_serialization as make_client_core
from pyfect.rpc.message import FromServer
from pyfect.rpc.server._core import ServerOptions
from pyfect.rpc.server._core import make_no_serialization as make_server_core
from pyfect.scope import Scope
from pyfect.stream import Stream
from pyfect.stream import die as stream_die

if TYPE_CHECKING:
    from pyfect.cluster.entity._entity import Entity
    from pyfect.cluster.entity._handlers import Concurrency, EntityHandlers, EntityOptions
    from pyfect.cluster.sharding_registration_event import ShardingRegistrationEvent


@dataclass(frozen=True, slots=True)
class _Registered:
    context: Context[Any]
    concurrency: Concurrency
    disable_fatal_defects: bool
    build: Effect[Context[Any], Never, Any]


def _not_in_test(name: str) -> Effect[Never]:
    return die(RuntimeError(f"Sharding.{name} is not available to Entity.make_test_client"))


class _TestSharding:
    """A sharding that only records entity registrations."""

    __slots__ = ("registered",)

    def __init__(self) -> None:
        self.registered: dict[str, _Registered] = {}

    def register_entity(
        self,
        entity: type[Entity],
        build: Effect[EntityHandlers[Any, Any], Never, Any],
        options: EntityOptions,
        /,
    ) -> Effect[None, Never, Any]:
        def record(services: Context[Any]) -> None:
            self.registered[entity.type] = _Registered(
                services,
                options.concurrency,
                options.disable_fatal_defects,
                entity.to_handlers(build),
            )

        return context().map(record)

    def get_shard_id(self, entity_id: EntityId, group: str, /) -> ShardId:
        raise RuntimeError("Sharding.get_shard_id is not available to Entity.make_test_client")

    def has_shard_id(self, shard_id: ShardId, /) -> bool:
        return True

    @property
    def get_registration_events(self) -> Stream[ShardingRegistrationEvent]:
        return stream_die(
            RuntimeError(
                "Sharding.get_registration_events is not available to Entity.make_test_client"
            )
        )

    @property
    def get_snowflake(self) -> Effect[Snowflake]:
        return _not_in_test("get_snowflake")

    @property
    def is_shutdown(self) -> Effect[bool]:
        return _not_in_test("is_shutdown")

    def make_client[T: Entity](self, entity: type[T], /) -> Effect[Callable[[str], T]]:
        return _not_in_test("make_client")

    def register_singleton(
        self, name: str, run: Effect[None, Any, Any], shard_group: str | None, /
    ) -> Effect[None, Never, Any]:
        return _not_in_test("register_singleton")

    def send(self, message: Incoming, /) -> Effect[None, Any]:
        return _not_in_test("send")

    def send_outgoing(self, message: Outgoing, discard: bool, /) -> Effect[None, Any]:
        return _not_in_test("send_outgoing")

    def notify(self, message: Incoming, /, *, wait_until_read: bool = False) -> Effect[None, Any]:
        return _not_in_test("notify")

    def reset(
        self, request_id: Snowflake, /, *, expected_reply_id: Snowflake | None = None
    ) -> Effect[bool]:
        return _not_in_test("reset")

    @property
    def poll_storage(self) -> Effect[None]:
        return _not_in_test("poll_storage")

    @property
    def active_entity_count(self) -> Effect[int]:
        return _not_in_test("active_entity_count")


_RUNNER_ADDRESS = RunnerAddress(host="localhost", port=3000)


@overload
def make_test_client[T: Entity, E](
    entity: type[T], layer: Layer[Any, E, Sharding], /
) -> Effect[Callable[[str], Effect[T]], E, Scope | ShardingConfig]: ...
@overload
def make_test_client[T: Entity, E, R](
    entity: type[T], layer: Layer[Any, E, R | Sharding], /
) -> Effect[Callable[[str], Effect[T]], E, Scope | ShardingConfig | R]: ...
def make_test_client(entity: type[Entity], layer: Layer[Any, Any, Any], /) -> Effect[Any, Any, Any]:
    """Build ``layer`` against a sharding that records the entity's
    registration, and give a function making the client of an entity id:
    each id gets its own entity, started on first use and stopped when the
    current scope closes."""
    require_layer(layer, "layer")

    @gen
    def make():
        config = yield from ShardingConfig()
        snowflakes = yield from make_generator()
        sharding = _TestSharding()
        yield from layer.pipe(layer_.provide(layer_.succeed(Sharding, sharding))).build()
        entry = sharding.registered.get(entity.type)
        if entry is None:
            yield from die(
                RuntimeError(f"Entity.make_test_client: {entity.type} was not registered by layer")
            )
            return None
        registered = entry

        @fn_untraced
        def lookup(entity_id: str):
            id = EntityId(entity_id)
            address = EntityAddress(
                entity_type=entity.type,
                entity_id=id,
                shard_id=ShardId(
                    group=entity.get_shard_group(id),
                    id=shard_number(entity_id, config.shards_per_group),
                ),
            )
            scope = yield from Scope()
            handler_context = (
                registered.context.add(CurrentRunnerAddress, _RUNNER_ADDRESS)
                .add(CurrentAddress, address)
                .add(CurrentActivationScope, scope)
                .add(Scope, scope)
            )
            handlers = yield from _Locally(registered.build, lambda _: handler_context)
            cores: list[ClientCore] = []

            def on_from_server(response: FromServer) -> Effect[None]:
                return cores[0].write(response)

            server = yield from _Locally(
                make_server_core(
                    entity.protocol,
                    on_from_server,
                    ServerOptions(
                        concurrency=registered.concurrency,
                        disable_fatal_defects=registered.disable_fatal_defects,
                    ),
                ),
                lambda _: handler_context.merge(handlers),
            )

            def on_from_client(sent: OnFromClient) -> Effect[None, Any]:
                message = sent.message
                if isinstance(message, rpc_message.Request):
                    request = Request[Any](
                        request_id=Snowflake(int(message.id)),
                        address=address,
                        tag=message.tag,
                        payload=message.payload,
                        headers=message.headers,
                        trace_id=message.trace_id,
                        span_id=message.span_id,
                        sampled=message.sampled,
                    )
                    return server.write(0, replace(message, payload=request))
                return server.write(0, message)

            _, core = yield from make_client_core(
                entity.protocol,
                on_from_client,
                ClientOptions(supports_ack=True, generate_request_id=snowflakes.next_unsafe),
            )
            cores.append(core)
            client = entity()
            client._rpc_methods = core.methods(entity.protocol)
            return client

        clients = yield from ResourceMap.make(lookup)
        return clients.get

    return make


__all__ = ["make_test_client"]
