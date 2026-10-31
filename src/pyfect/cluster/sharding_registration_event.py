"""What ``Sharding.get_registration_events`` streams (Effect's
``ShardingRegistrationEvent``): an entity or a singleton was registered on
this runner."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from pyfect.cluster.singleton_address import SingletonAddress

if TYPE_CHECKING:
    from pyfect.cluster.entity import Entity


@dataclass(frozen=True, slots=True)
class EntityRegistered:
    entity: type[Entity]


@dataclass(frozen=True, slots=True)
class SingletonRegistered:
    address: SingletonAddress


type ShardingRegistrationEvent = EntityRegistered | SingletonRegistered

__all__ = ["EntityRegistered", "ShardingRegistrationEvent", "SingletonRegistered"]
