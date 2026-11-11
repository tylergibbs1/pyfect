"""The ``Runners`` service: how a runner talks to the others."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Never, Protocol, Self

from pyfect._core import Effect
from pyfect._service_copy import replaced
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

    def ping(self, address: RunnerAddress, /) -> Effect[None, RunnerUnavailable]:
        """Checks that the runner at ``address`` answers; fails with
        ``RunnerUnavailable`` when it cannot be reached."""
        ...

    def send_local(
        self, message: Outgoing, /, *, send: SendLocalFn, simulate_remote_serialization: bool
    ) -> Effect[None, LocalSendError | PersistenceError]:
        """Delivers ``message`` to an entity of this runner through
        ``send``, first encoding and decoding it as a remote send would
        when ``simulate_remote_serialization`` is set (a message that does
        not survive that gets a defect reply). Fails as ``send`` does:
        ``EntityNotAssignedToRunner``, ``MailboxFull`` or
        ``AlreadyProcessingMessage``."""
        ...

    def send(self, address: RunnerAddress, message: Outgoing, /) -> Effect[None, SendError]:
        """Sends ``message`` to the runner at ``address``, its replies
        going to the message's ``respond``. Fails with a ``SendError``:
        ``RunnerUnavailable`` when the runner cannot be reached, or the
        error the remote runner gave."""
        ...

    def notify(
        self, address: RunnerAddress | None, message: Outgoing, /, *, discard: bool
    ) -> Effect[None, SendError]:
        """Tells the runner at ``address`` (``None``: not known) that
        ``message`` is waiting, saving it to ``MessageStorage`` first when
        it is persisted; unless ``discard``, a request's replies are then
        recovered from storage. Fails with a ``SendError``
        (``PersistenceError`` when saving fails)."""
        ...

    def notify_local(
        self,
        message: Outgoing,
        /,
        *,
        notify: NotifyLocalFn,
        discard: bool,
        storage_only: bool = False,
    ) -> Effect[None, PersistenceError]:
        """Tells an entity of this runner through ``notify`` that
        ``message`` is waiting (ignoring ``EntityNotAssignedToRunner``),
        saving it to ``MessageStorage`` first when it is persisted; unless
        ``discard``, a request's replies then come back through storage
        (with ``storage_only``, only by polling it). Fails with
        ``PersistenceError`` when saving fails."""
        ...

    def on_runner_unavailable(self, address: RunnerAddress, /) -> Effect[None]:
        """Marks the runner at ``address`` unavailable, dropping its
        connection; never fails."""
        ...


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


class RpcClientProtocolService:
    """Makes the RPC client protocols of the RPC-based ``Runners``
    (Effect's ``Runners.RpcClientProtocol``)."""

    __slots__ = ("_codec_for", "_make")

    def __replace__(self, **changes: Any) -> Self:
        """A copy with ``changes`` to the constructor's arguments (``copy.replace``)."""
        return replaced(self, changes)

    def __init__(
        self,
        make: Callable[[RunnerAddress], Effect[ClientProtocolService, Never, Scope]],
        codec_for: CodecFor,
    ) -> None:
        self._make = make
        self._codec_for = codec_for

    def make(self, address: RunnerAddress) -> Effect[ClientProtocolService, Never, Scope]:
        """A client protocol connected to the runner at ``address``, open
        until the ``Scope`` closes; never fails (connection errors surface
        through the protocol's calls)."""
        return self._make(address)

    @property
    def codec_for(self) -> CodecFor:
        """``codec_for(schema)``: the codec for ``schema``'s values that
        every protocol from ``make`` shares (used when a local send
        simulates a remote one; encode caches compare it by identity)."""
        return self._codec_for


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
