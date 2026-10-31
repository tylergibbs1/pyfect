"""Runners for a single runner (Effect's ``Runners.makeNoop``): nothing
is remote, sends to another runner fail with
``EntityNotAssignedToRunner``."""

from __future__ import annotations

from typing import Never

from pyfect import layer as layer_
from pyfect._core import Effect
from pyfect.cluster import snowflake
from pyfect.cluster.cluster_error import EntityNotAssignedToRunner
from pyfect.cluster.message import Outgoing, codec_for_json
from pyfect.cluster.message_storage import MessageStorage
from pyfect.cluster.runner_address import RunnerAddress
from pyfect.cluster.runners._local import make
from pyfect.cluster.runners._service import Runners, RunnersService, RunnersTransport
from pyfect.cluster.sharding_config import ShardingConfig
from pyfect.cluster.snowflake import Generator
from pyfect.effect import fail, succeed
from pyfect.layer import Layer
from pyfect.scope import Scope

_VOID: Effect[None] = succeed(None)


def _send(_: RunnerAddress, message: Outgoing) -> Effect[None, EntityNotAssignedToRunner]:
    return fail(EntityNotAssignedToRunner(address=message.envelope.address))


def _notify(_: RunnerAddress | None, __: Outgoing, ___: bool) -> Effect[None]:
    return _VOID


def _void(_: RunnerAddress) -> Effect[None]:
    return _VOID


make_noop: Effect[RunnersService, Never, MessageStorage | Generator | ShardingConfig | Scope] = (
    make(
        RunnersTransport(
            codec_for=codec_for_json,
            send=_send,
            notify=_notify,
            ping=_void,
            on_runner_unavailable=_void,
        )
    )
)
"""Runners that deliver locally only."""

layer_noop: Layer[Runners, Never, ShardingConfig | MessageStorage] = layer_.effect(
    Runners, make_noop
).pipe(layer_.provide(snowflake.layer_generator))
"""``make_noop`` as a layer, with its own snowflake generator."""

__all__ = ["layer_noop", "make_noop"]
