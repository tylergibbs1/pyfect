"""The ``Sharding`` service interface and tag."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Never, Protocol

from pyfect._core import Effect
from pyfect.cluster.cluster_error import (
    AlreadyProcessingMessage,
    EntityNotAssignedToRunner,
    MailboxFull,
    PersistenceError,
)
from pyfect.cluster.entity_id import EntityId
from pyfect.cluster.message import Incoming, Outgoing
from pyfect.cluster.shard_id import ShardId
from pyfect.cluster.snowflake import Snowflake
from pyfect.context import Tag

if TYPE_CHECKING:
    from pyfect.cluster.entity import Entity, EntityHandlers, EntityOptions
    from pyfect.cluster.sharding_registration_event import ShardingRegistrationEvent
    from pyfect.stream import Stream


class ShardingService(Protocol):
    """What ``Sharding`` provides. ``send`` delivers a message to a local
    entity, ``notify`` tells it a persisted message is waiting, and
    ``send_outgoing`` routes a message from a client."""

    @property
    def get_registration_events(self) -> Stream[ShardingRegistrationEvent]:
        """The entities and singletons registered from now on."""
        ...

    def get_shard_id(self, entity_id: EntityId, group: str, /) -> ShardId: ...

    def has_shard_id(self, shard_id: ShardId, /) -> bool: ...

    @property
    def get_snowflake(self) -> Effect[Snowflake]: ...

    @property
    def is_shutdown(self) -> Effect[bool]: ...

    def make_client[T: Entity](self, entity: type[T], /) -> Effect[Callable[[str], T]]: ...

    def register_entity(
        self,
        entity: type[Entity],
        build: Effect[EntityHandlers[Any, Any], Never, Any],
        options: EntityOptions,
        /,
    ) -> Effect[None, Never, Any]: ...

    def register_singleton(
        self, name: str, run: Effect[None, Any, Any], shard_group: str | None, /
    ) -> Effect[None, Never, Any]: ...

    def send(
        self, message: Incoming, /
    ) -> Effect[None, EntityNotAssignedToRunner | MailboxFull | AlreadyProcessingMessage]: ...

    def send_outgoing(
        self, message: Outgoing, discard: bool, /
    ) -> Effect[
        None,
        MailboxFull | AlreadyProcessingMessage | PersistenceError | EntityNotAssignedToRunner,
    ]: ...

    def notify(
        self, message: Incoming, /, *, wait_until_read: bool = False
    ) -> Effect[None, EntityNotAssignedToRunner | AlreadyProcessingMessage]: ...

    def reset(
        self, request_id: Snowflake, /, *, expected_reply_id: Snowflake | None = None
    ) -> Effect[bool]: ...

    @property
    def poll_storage(self) -> Effect[None]: ...

    @property
    def active_entity_count(self) -> Effect[int]: ...


class Sharding(Tag[ShardingService], key="effect/cluster/Sharding"):
    """The sharding service of this runner."""


__all__ = ["Sharding", "ShardingService"]
