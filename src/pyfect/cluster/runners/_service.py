"""The ``Runners`` service: how a runner talks to the others."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Never, Protocol

from pyfect._core import Effect
from pyfect.cluster.cluster_error import (
    AlreadyProcessingMessage,
    EntityNotAssignedToRunner,
    MailboxFull,
    PersistenceError,
    RunnerUnavailable,
)
from pyfect.cluster.message import IncomingLocal, Outgoing
from pyfect.cluster.runner_address import RunnerAddress
from pyfect.context import Tag
from pyfect.rpc.client._protocol import ClientProtocolService
from pyfect.rpc.serialization import CodecFor
from pyfect.scope import Scope

type LocalSendError = EntityNotAssignedToRunner | MailboxFull | AlreadyProcessingMessage
"""How delivering to a local entity fails."""

type SendError = (
    EntityNotAssignedToRunner
    | RunnerUnavailable
    | MailboxFull
    | AlreadyProcessingMessage
    | PersistenceError
)
"""How sending to a runner fails."""

type SendLocalFn = Callable[[IncomingLocal], Effect[None, LocalSendError]]
type NotifyLocalFn = Callable[[IncomingLocal], Effect[None, EntityNotAssignedToRunner]]


class RunnersService(Protocol):
    """Pings runners, sends them messages and tells them a persisted
    message is waiting. ``send_local`` and ``notify_local`` deliver to this
    runner's entities, through storage when the message is persisted."""

    def ping(self, address: RunnerAddress, /) -> Effect[None, RunnerUnavailable]: ...

    def send_local(
        self, message: Outgoing, /, *, send: SendLocalFn, simulate_remote_serialization: bool
    ) -> Effect[None, LocalSendError | PersistenceError]: ...

    def send(self, address: RunnerAddress, message: Outgoing, /) -> Effect[None, SendError]: ...

    def notify(
        self, address: RunnerAddress | None, message: Outgoing, /, *, discard: bool
    ) -> Effect[None, SendError]: ...

    def notify_local(
        self,
        message: Outgoing,
        /,
        *,
        notify: NotifyLocalFn,
        discard: bool,
        storage_only: bool = False,
    ) -> Effect[None, PersistenceError]: ...

    def on_runner_unavailable(self, address: RunnerAddress, /) -> Effect[None]: ...


class Runners(Tag[RunnersService], key="effect/cluster/Runners"):
    """How this runner talks to the others."""


@dataclass(frozen=True, slots=True, kw_only=True)
class RunnersTransport:
    """The remote half of a ``Runners`` service, which ``make`` completes
    with local delivery: ``notify`` gets the runner (``None`` when unknown),
    the message and whether its caller discards the reply; ``codec_for``
    encodes payloads when local sends simulate a remote one."""

    codec_for: CodecFor
    ping: Callable[[RunnerAddress], Effect[None, RunnerUnavailable]]
    send: Callable[[RunnerAddress, Outgoing], Effect[None, SendError]]
    notify: Callable[[RunnerAddress | None, Outgoing, bool], Effect[None, SendError]]
    on_runner_unavailable: Callable[[RunnerAddress], Effect[None]]


@dataclass(frozen=True, slots=True)
class RpcClientProtocolService:
    """Makes the RPC client protocol of a runner address; ``codec_for`` is
    the codec its protocols share."""

    make: Callable[[RunnerAddress], Effect[ClientProtocolService, Never, Scope]]
    codec_for: CodecFor


class RpcClientProtocol(
    Tag[RpcClientProtocolService], key="effect/cluster/Runners/RpcClientProtocol"
):
    """The client transport of the RPC-based ``Runners``."""


__all__ = [
    "LocalSendError",
    "NotifyLocalFn",
    "RpcClientProtocol",
    "RpcClientProtocolService",
    "Runners",
    "RunnersService",
    "RunnersTransport",
    "SendError",
    "SendLocalFn",
]
