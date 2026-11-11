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

    def get_shard_id(self, entity_id: EntityId, group: str, /) -> ShardId:
        """The shard of ``group`` that ``entity_id`` belongs to."""
        ...

    def has_shard_id(self, shard_id: ShardId, /) -> bool:
        """Whether this runner holds ``shard_id`` (never while shutting
        down)."""
        ...

    @property
    def get_snowflake(self) -> Effect[Snowflake]:
        """A new snowflake id, unique to this runner. Never fails."""
        ...

    @property
    def is_shutdown(self) -> Effect[bool]:
        """Whether sharding is shutting down. Never fails."""
        ...

    def make_client[T: Entity](self, entity: type[T], /) -> Effect[Callable[[str], T]]:
        """A function giving the client of ``entity`` for an entity id;
        its calls fail with ``MailboxFull``, ``AlreadyProcessingMessage``,
        ``PersistenceError`` or ``EntityNotAssignedToRunner``. Making it
        never fails."""
        ...

    def register_entity(
        self,
        entity: type[Entity],
        build: Effect[EntityHandlers[Any, Any], Never, Any],
        options: EntityOptions,
        /,
    ) -> Effect[None, Never, Any]:
        """Registers ``entity`` on this runner, its handlers built by
        ``build`` for each entity started, with ``options``, until the
        ``Scope`` closes. Never fails."""
        ...

    def register_singleton(
        self, name: str, run: Effect[None, Any, Any], shard_group: str | None, /
    ) -> Effect[None, Never, Any]:
        """Registers the singleton ``name``: ``run`` runs on the runner that
        holds its shard of ``shard_group`` (``None``: ``"default"``), until
        the ``Scope`` closes. Never fails; registering a name twice is a
        defect."""
        ...

    def send(
        self, message: Incoming, /
    ) -> Effect[None, EntityNotAssignedToRunner | MailboxFull | AlreadyProcessingMessage]:
        """Delivers ``message`` to its entity on this runner. Fails with
        ``EntityNotAssignedToRunner`` when its shard is not here,
        ``MailboxFull`` when the entity's mailbox is, and
        ``AlreadyProcessingMessage`` when the request is already being
        processed."""
        ...

    def send_outgoing(
        self, message: Outgoing, discard: bool, /
    ) -> Effect[
        None,
        MailboxFull | AlreadyProcessingMessage | PersistenceError | EntityNotAssignedToRunner,
    ]:
        """Routes ``message`` from a client to the runner of its entity
        (this one or another), persisting it first when it is persisted;
        ``discard`` drops its reply. Fails as ``send`` does, or with
        ``PersistenceError`` when storage fails."""
        ...

    def notify(
        self, message: Incoming, /, *, wait_until_read: bool = False
    ) -> Effect[None, EntityNotAssignedToRunner | AlreadyProcessingMessage]:
        """Tells sharding that ``message`` was persisted, so storage is read
        for it; with ``wait_until_read``, a request waits until that read
        has picked it up. Fails with ``EntityNotAssignedToRunner`` when its
        shard is not here, ``AlreadyProcessingMessage`` when the request is
        already being processed."""
        ...

    def reset(
        self, request_id: Snowflake, /, *, expected_reply_id: Snowflake | None = None
    ) -> Effect[bool]:
        """Clears the stored replies of ``request_id`` so it runs again;
        with ``expected_reply_id``, only while that is still its latest
        reply. ``False`` when storage failed (it never fails), else
        ``True``."""
        ...

    @property
    def poll_storage(self) -> Effect[None]:
        """Triggers a read of every unprocessed message in storage. Never
        fails."""
        ...

    @property
    def active_entity_count(self) -> Effect[int]:
        """How many entities are running on this runner. Never fails."""
        ...


class Sharding(Tag[ShardingService], key="effect/cluster/Sharding"):
    """The sharding service of this runner."""


__all__ = ["Sharding", "ShardingService"]
