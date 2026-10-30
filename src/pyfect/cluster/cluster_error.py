"""The errors of a cluster (Effect's ``ClusterError``). Each is a schema
class, so it crosses the wire as an RPC failure."""

from __future__ import annotations

from pyfect import schema as S
from pyfect._core import Effect
from pyfect._effect_args import require_effect
from pyfect.cluster.entity_address import EntityAddress
from pyfect.cluster.runner_address import RunnerAddress
from pyfect.cluster.snowflake import Snowflake, SnowflakeFromString
from pyfect.effect import fail

_ID = "~effect/cluster/ClusterError"


class EntityNotAssignedToRunner(S.TaggedError, identifier=f"{_ID}/EntityNotAssignedToRunner"):
    """The entity's shard is not assigned to the runner that got the message."""

    address: EntityAddress


class MalformedMessage(S.TaggedError, identifier=f"{_ID}/MalformedMessage"):
    """A message could not be decoded or encoded."""

    cause: object = S.field(S.Defect())

    @staticmethod
    def refail[A, R](effect: Effect[A, object, R]) -> Effect[A, MalformedMessage, R]:
        """``effect`` with its failure wrapped in ``MalformedMessage``."""
        require_effect(effect, "effect")
        return effect.map_error(lambda cause: MalformedMessage(cause=cause))


class PersistenceError(S.TaggedError, identifier=f"{_ID}/PersistenceError"):
    """Message or runner storage failed."""

    cause: object = S.field(S.Defect())

    @staticmethod
    def refail[A, R](effect: Effect[A, object, R]) -> Effect[A, PersistenceError, R]:
        """``effect`` with any failure or defect squashed into a
        ``PersistenceError``."""
        require_effect(effect, "effect")
        return effect.catch_cause(lambda cause: fail(PersistenceError(cause=cause.squash())))


class RunnerNotRegistered(S.TaggedError, identifier=f"{_ID}/RunnerNotRegistered"):
    """The runner is not registered with runner storage."""

    address: RunnerAddress


class RunnerUnavailable(S.TaggedError, identifier=f"{_ID}/RunnerUnavailable"):
    """The runner could not be reached."""

    address: RunnerAddress


class MailboxFull(S.TaggedError, identifier=f"{_ID}/MailboxFull"):
    """The entity's mailbox is at ``entity_mailbox_capacity``."""

    address: EntityAddress


class AlreadyProcessingMessage(S.TaggedError, identifier=f"{_ID}/AlreadyProcessingMessage"):
    """The entity is already processing the message with this id."""

    envelope_id: Snowflake = S.field(SnowflakeFromString)
    address: EntityAddress


__all__ = [
    "AlreadyProcessingMessage",
    "EntityNotAssignedToRunner",
    "MailboxFull",
    "MalformedMessage",
    "PersistenceError",
    "RunnerNotRegistered",
    "RunnerUnavailable",
]
