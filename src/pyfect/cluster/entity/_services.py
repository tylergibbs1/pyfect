"""The services an entity handler can read."""

from __future__ import annotations

from pyfect.cluster.entity_address import EntityAddress
from pyfect.cluster.runner_address import RunnerAddress
from pyfect.context import Tag
from pyfect.latch import Latch


class CurrentAddress(Tag[EntityAddress], key="effect/cluster/Entity/EntityAddress"):
    """The address of the entity handling the current request."""


class CurrentRunnerAddress(Tag[RunnerAddress], key="effect/cluster/Entity/RunnerAddress"):
    """The address of the runner the entity runs on."""


class KeepAliveLatch(Tag[Latch], key="effect/cluster/Entity/KeepAliveLatch"):
    """Closed while ``keep_alive(True)`` keeps the entity alive."""


__all__ = ["CurrentAddress", "CurrentRunnerAddress", "KeepAliveLatch"]
