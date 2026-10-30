"""RPC annotations that change how a cluster delivers an entity's
messages (Effect's ``ClusterSchema``). Set them with ``rpc.annotate``."""

from __future__ import annotations

from collections.abc import Callable
from typing import Literal

from pyfect.cluster.entity_id import EntityId
from pyfect.context import Context, Reference


class Persisted(Reference[bool], key="effect/cluster/ClusterSchema/Persisted"):
    """Messages are written to message storage before delivery, so they
    survive a runner restart (default ``False``)."""

    @classmethod
    def default(cls) -> bool:
        return False


class WithTransaction(Reference[bool], key="effect/cluster/ClusterSchema/WithTransaction"):
    """The handler and the reply are saved in one storage transaction."""

    @classmethod
    def default(cls) -> bool:
        return False


type UninterruptibleMode = bool | Literal["client", "server"]


class Uninterruptible(
    Reference[UninterruptibleMode], key="effect/cluster/ClusterSchema/Uninterruptible"
):
    """``True`` (or ``"client"`` / ``"server"``, one side only): requests
    are not interrupted by the caller or by the runner."""

    @classmethod
    def default(cls) -> UninterruptibleMode:
        return False


class InterruptOnTermination(
    Reference[bool], key="effect/cluster/ClusterSchema/InterruptOnTermination"
):
    """Interrupt running requests when the entity terminates."""

    @classmethod
    def default(cls) -> bool:
        return False


def is_uninterruptible_for_server(annotations: Context) -> bool:
    value = annotations.get(Uninterruptible)
    return value is True or value == "server"


def is_uninterruptible_for_client(annotations: Context) -> bool:
    value = annotations.get(Uninterruptible)
    return value is True or value == "client"


def _default_group(_: EntityId) -> str:
    return "default"


class ShardGroup(
    Reference[Callable[[EntityId], str]], key="effect/cluster/ClusterSchema/ShardGroup"
):
    """The shard group of an entity id (default ``"default"``)."""

    @classmethod
    def default(cls) -> Callable[[EntityId], str]:
        return _default_group


class ClientTracingEnabled(
    Reference[bool], key="effect/cluster/ClusterSchema/ClientTracingEnabled"
):
    """Clients make a span for each request (default ``True``)."""

    @classmethod
    def default(cls) -> bool:
        return True


__all__ = [
    "ClientTracingEnabled",
    "InterruptOnTermination",
    "Persisted",
    "ShardGroup",
    "Uninterruptible",
    "UninterruptibleMode",
    "WithTransaction",
    "is_uninterruptible_for_client",
    "is_uninterruptible_for_server",
]
