"""The two ends of a Python worker's transport, as the platforms see them.

The parent holds a ``WorkerPort``: it posts messages to the worker, and the
worker's messages, receive errors and exit arrive in ``events``. The worker
holds a ``ParentPort``: it posts to the parent, and the parent's messages
arrive in ``inbox``. Each backend (a thread, a child process) implements
both; the threads moving messages only ever put into a ``Mailbox``.
"""

from __future__ import annotations

import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass

from pyfect.process._os import Latch
from pyfect.workers._mailbox import Mailbox


@dataclass(frozen=True, slots=True)
class Received:
    """A message arrived."""

    data: object


@dataclass(frozen=True, slots=True)
class Unreadable:
    """A message arrived that could not be read (Node's ``messageerror``)."""

    cause: BaseException


@dataclass(frozen=True, slots=True)
class Raised:
    """The worker raised (Node's ``error`` event)."""

    cause: BaseException


@dataclass(frozen=True, slots=True)
class Exited:
    """The worker has exited."""

    code: int


@dataclass(frozen=True, slots=True)
class Disconnected:
    """The parent went away."""


type WorkerEvent = Received | Unreadable | Raised | Exited
type ParentEvent = Received | Unreadable | Disconnected


class WorkerPort(ABC):
    """The parent's end of one worker."""

    __slots__ = ("_finished", "events", "exited")

    def __init__(self) -> None:
        self.events: Mailbox[WorkerEvent] = Mailbox()
        self.exited: Latch[int] = Latch(waits_for="event")
        self._finished = threading.Lock()

    @abstractmethod
    def post(self, message: object) -> None:
        """Send ``message`` without waiting; raises if it cannot be sent."""

    @abstractmethod
    def kill(self) -> None:
        """Stop the worker now."""

    def finish(self, code: int) -> None:
        """Report the exit, once."""
        if self._finished.acquire(blocking=False):
            self.events.put(Exited(code))
            self.exited.set(code)


class ParentPort(ABC):
    """The worker's end of its parent."""

    __slots__ = ("inbox",)

    def __init__(self) -> None:
        self.inbox: Mailbox[ParentEvent] = Mailbox()

    @abstractmethod
    def post(self, message: object) -> None:
        """Send ``message`` to the parent without waiting."""

    @abstractmethod
    def close(self) -> None:
        """Stop receiving: the parent closed the worker."""


class WorkerHandle(ABC):
    """A worker that has not started yet: what a ``Spawner`` gives the
    Python platform. ``start`` runs it."""

    __slots__ = ()

    @abstractmethod
    def start(self) -> WorkerPort: ...
