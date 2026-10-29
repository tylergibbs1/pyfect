"""The ``Redis`` service and what its clients provide."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Never, Protocol

from pyfect._core import Effect
from pyfect.context import Tag
from pyfect.duration import Duration
from pyfect.persistence.redis._error import RedisError
from pyfect.persistence.redis._script import RedisReply, Script
from pyfect.queue import Dequeue
from pyfect.scope import Scope


@dataclass(frozen=True, slots=True)
class RedisMessage:
    """A message published to ``channel``."""

    channel: str
    message: str


class RedisConnection(Protocol):
    """Sends commands and runs scripts."""

    def send(self, command: str, *args: str) -> Effect[RedisReply, RedisError]:
        """Send ``command`` with ``args`` and give its reply."""
        ...

    def eval[**P, A](self, script: Script[P, A]) -> Callable[P, Effect[A, RedisError]]:
        """A function running ``script`` with ``EVALSHA``, loading it first
        (and again when Redis answers ``NOSCRIPT``)."""
        ...


class RedisService(RedisConnection, Protocol):
    """A Redis client: commands and scripts on shared connections,
    subscriptions, and connections of its own (``reserve``)."""

    def subscribe(self, channel: str) -> Effect[Dequeue[RedisMessage, RedisError], Never, Scope]:
        """Messages published to ``channel`` until the scope closes; a
        failed subscription fails the dequeue."""
        ...

    @property
    def reserve(self) -> Effect[RedisConnection, RedisError, Scope]:
        """A connection for this scope alone, for blocking commands
        (``XREAD BLOCK``, ``BLPOP``) that would hold up the shared ones.
        One released with a command still running, or after a failed
        command, is closed instead of reused."""
        ...


class Redis(Tag[RedisService], key="effect/persistence/Redis"):
    """A Redis client."""


@dataclass(frozen=True, slots=True, kw_only=True)
class PoolOptions:
    """The pool behind ``reserve``: at most ``max_connections`` (default
    10), at least ``min_connections`` kept open (default 0), one idle for
    ``idle_timeout`` closed (default 60 seconds), and ``acquire_timeout``
    to wait for a free one before failing (default: no limit)."""

    max_connections: int = 10
    min_connections: int = 0
    idle_timeout: Duration = 60.0
    acquire_timeout: Duration | None = None


class Send(Protocol):
    """Sends ``command`` with ``args`` and gives its reply."""

    def __call__(self, command: str, /, *args: str) -> Effect[RedisReply, RedisError]: ...


@dataclass(frozen=True, slots=True)
class OpenConnection:
    """A connection ``connect`` opened: ``send`` commands on it, ``close``
    it (failing a command still running on it)."""

    send: Send
    close: Effect[None]


type Subscribe = Callable[
    [str, Callable[[RedisMessage], object]], Effect[Effect[None, RedisError], RedisError, Scope]
]
"""``subscribe(channel, on_message)``: subscribes until the scope closes
and gives the effect that delivers its messages to ``on_message`` (on the
fiber running it) until the subscription fails."""
