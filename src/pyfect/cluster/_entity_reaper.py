"""Stops idle entities (Effect's ``internal/entityReaper``): every entity
manager with a finite idle time registers its entities, and a loop
removes those idle for longer, checking at least every five seconds."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Never

from pyfect import layer as layer_
from pyfect._core import Effect
from pyfect.clock import Clock, now_millis_unsafe, sleep
from pyfect.cluster._resource_map import ResourceMap
from pyfect.cluster.entity_address import EntityAddress
from pyfect.cluster.entity_id import EntityId
from pyfect.context import Tag
from pyfect.duration import Seconds
from pyfect.effect import gen, suspend
from pyfect.latch import Latch
from pyfect.layer import Layer
from pyfect.scope import Scope, fork_scoped

if TYPE_CHECKING:
    from pyfect.cluster._entity_manager._state import EntityState


@dataclass(frozen=True, slots=True)
class _Registered:
    max_idle_millis: float
    servers: dict[EntityId, EntityState]
    entities: ResourceMap[EntityAddress, EntityState, Any]


class EntityReaperService:
    __slots__ = ("_latch", "_registered", "_resolution")

    def __init__(self, latch: Latch) -> None:
        self._latch = latch
        self._registered: list[_Registered] = []
        self._resolution = 30_000.0

    def register(
        self,
        *,
        max_idle_millis: float,
        servers: dict[EntityId, EntityState],
        entities: ResourceMap[EntityAddress, EntityState, Any],
    ) -> Effect[None]:
        """Remove the entities of ``servers`` idle for ``max_idle_millis``."""

        def run() -> Effect[None]:
            self._resolution = max(min(self._resolution, max_idle_millis), 5000)
            self._registered.append(_Registered(max_idle_millis, servers, entities))
            return self._latch.open().as_void()

        return suspend(run)

    def _loop(self) -> Effect[Never]:
        @gen
        def loop():
            clock = yield from Clock()
            while True:
                yield from sleep(Seconds(self._resolution / 1000))
                now = now_millis_unsafe(clock)
                for registered in list(self._registered):
                    for state in list(registered.servers.values()):
                        idle = now - state.last_active_check
                        if (
                            state.keep_alive_enabled
                            or state.active_requests
                            or idle < registered.max_idle_millis
                        ):
                            continue
                        yield from registered.entities.remove_ignore(state.address).fork()

        return self._latch.when_open(loop)


class EntityReaper(Tag[EntityReaperService], key="effect/cluster/EntityReaper"):
    """The idle-entity reaper of this runner."""


@gen
def make():
    reaper = EntityReaperService(Latch())
    yield from fork_scoped(reaper._loop())  # pyright: ignore[reportPrivateUsage]
    return reaper


make_effect: Effect[EntityReaperService, Never, Scope] = make

layer: Layer[EntityReaper] = layer_.effect(EntityReaper, make_effect)

__all__ = ["EntityReaper", "EntityReaperService", "layer", "make_effect"]
