"""The parent side of workers (Effect's ``Worker``).

A ``Worker[O, I]`` sends ``I`` messages to a worker and runs a handler for
each ``O`` it sends back. ``WorkerPlatform`` spawns workers by numeric id,
finding the platform's worker for each id with the ``Spawner`` function in
the context (``layer_spawner``). ``make_platform(setup=, listen=)`` builds a
platform from a transport's two hooks: ``setup`` starts the worker and
returns its port, ``listen`` hands what the worker sends to ``emit`` and
fails the run through ``deferred`` when the worker goes away. Messages sent
before the worker says it is ready are kept and sent once it is.

``python_worker.layer`` is the platform for Python threads and child
processes (Effect's ``NodeWorker``).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, Literal, Never, Protocol, cast

from pyfect._core import Effect, Restore, uninterruptible_mask
from pyfect._effect_args import require_effect
from pyfect.context import Tag
from pyfect.deferred import Deferred
from pyfect.effect import gen, provide_service, succeed, suspend, sync, try_
from pyfect.fiber_set import FiberSet
from pyfect.latch import Latch
from pyfect.layer import Layer
from pyfect.layer import succeed as layer_succeed
from pyfect.scope import CloseableScope, Scope, scoped_with
from pyfect.workers.worker_error import WorkerError, WorkerSendError

type PlatformMessage = tuple[Literal[0]] | tuple[Literal[1], object]
"""What a worker sends its parent: ``(0,)`` when it is ready, ``(1, data)``
for a message."""

type Transfers = Sequence[object]
"""Values a platform may move rather than copy with a message (Effect's
transfer list). The Python platforms copy or share every message and
ignore them."""

type SendFn = Callable[[Any, Transfers], Effect[None, WorkerError]]
type RunFn = Callable[
    [Callable[[Any], Effect[Any, Any, Any]], Effect[None] | None], Effect[Never, Any, Any]
]

_VOID: Effect[None] = succeed(None)


class Worker[O = Any, I = Any]:
    """A spawned worker: ``send`` a message, ``run`` a handler for its
    replies. ``run`` starts the worker and never returns; it fails when
    the worker goes away or the handler fails."""

    __slots__ = ("_run", "_send")

    def __init__(self, *, send: SendFn, run: RunFn) -> None:
        self._send = send
        self._run = run

    def send(self, message: I, transfers: Transfers = ()) -> Effect[None, WorkerError]:
        return self._send(message, transfers)

    def run[A, E = Never, R = Never](
        self,
        handler: Callable[[O], Effect[A, E, R]],
        *,
        on_spawn: Effect[None] | None = None,
    ) -> Effect[Never, E | WorkerError, R]:
        """Start the worker and handle each of its messages on a fiber of
        its own; ``on_spawn`` runs once the worker is ready."""
        if on_spawn is not None:
            require_effect(on_spawn, "on_spawn")
        return cast("Effect[Never, E | WorkerError, R]", self._run(handler, on_spawn))


def make_unsafe(
    *,
    send: SendFn,
    run: Callable[[Callable[[PlatformMessage], Effect[Any, Any, Any]]], Effect[Never, Any, Any]],
) -> Worker[Any, Any]:
    """A ``Worker`` over a platform's raw ``send`` and ``run``: ``run``'s
    handler gets the ``PlatformMessage``s, and a ready message runs
    ``on_spawn``."""

    def run_worker(
        handler: Callable[[Any], Effect[Any, Any, Any]], on_spawn: Effect[None] | None
    ) -> Effect[Never, Any, Any]:
        spawned = _VOID if on_spawn is None else on_spawn

        def on_message(message: PlatformMessage) -> Effect[Any, Any, Any]:
            return spawned if message[0] == 0 else handler(message[1])

        return run(on_message)

    return Worker(send=send, run=run_worker)


type SpawnerFn = Callable[[int], object]
"""Gives the platform's worker for a worker id."""


class Spawner(Tag[SpawnerFn], key="effect/workers/Worker/Spawner"):
    """How the ``WorkerPlatform`` finds the worker for each id."""


def layer_spawner(spawner: SpawnerFn) -> Layer[Spawner]:
    return layer_succeed(Spawner, spawner)


@dataclass(frozen=True, slots=True)
class WorkerPlatformService:
    """``spawn(id)`` gives the worker for ``id`` (from the ``Spawner``); it
    starts when it is run."""

    spawn: Callable[[int], Effect[Worker[Any, Any], WorkerError, Spawner]]


class WorkerPlatform(Tag[WorkerPlatformService], key="effect/workers/Worker/WorkerPlatform"):
    """Spawns the workers of the current platform."""


class Port(Protocol):
    """What a platform's ``setup`` gives: where messages to the worker go."""

    def post_message(self, message: object, transfers: Transfers) -> None: ...


@dataclass(frozen=True, slots=True)
class SetupOptions[W]:
    worker: W
    scope: CloseableScope


@dataclass(frozen=True, slots=True)
class ListenOptions[P]:
    """``emit`` each ``PlatformMessage`` the worker sends (on the runtime's
    thread); complete ``deferred`` with a ``WorkerError`` when it goes
    away. ``scope`` closes when the run ends."""

    port: P
    emit: Callable[[PlatformMessage], None]
    deferred: Deferred[None, WorkerError]
    scope: CloseableScope


class _Spawned[P: Port]:
    __slots__ = ("buffer", "listen", "port", "setup", "worker")

    def __init__(
        self,
        worker: Callable[[], object],
        setup: Callable[[SetupOptions[Any]], Effect[P, WorkerError]],
        listen: Callable[[ListenOptions[P]], Effect[None]],
    ) -> None:
        self.worker = worker
        self.setup = setup
        self.listen = listen
        self.port: P | None = None
        self.buffer: list[tuple[object, Transfers]] = []

    def send_to_port(
        self, port: P, message: object, transfers: Transfers
    ) -> Effect[None, WorkerError]:
        def post() -> None:
            port.post_message((0, message), transfers)

        return try_(
            post,
            lambda cause: WorkerError(
                reason=WorkerSendError(message="Failed to send message to worker", cause=cause)
            ),
        )

    def send(self, message: object, transfers: Transfers) -> Effect[None, WorkerError]:
        def body() -> Effect[None, WorkerError]:
            if self.port is None:
                self.buffer.append((message, transfers))
                return _VOID
            return self.send_to_port(self.port, message, transfers)

        return suspend(body)

    def run(
        self, handler: Callable[[Any], Effect[Any, Any, Any]], on_spawn: Effect[None] | None
    ) -> Effect[Never, Any, Any]:
        return uninterruptible_mask(
            lambda restore: scoped_with(
                lambda scope: self._running(handler, on_spawn, restore, scope)
            )
        )

    def _forget_port(self) -> None:
        self.port = None

    def _running(
        self,
        handler: Callable[[Any], Effect[Any, Any, Any]],
        on_spawn: Effect[None] | None,
        restore: Restore,
        scope: CloseableScope,
    ) -> Effect[Never, Any, Any]:
        @gen
        def body():
            port = yield from self.setup(SetupOptions(self.worker(), scope))
            yield from scope.add_finalizer(lambda _: sync(self._forget_port))
            fiber_set = yield from FiberSet[Any, Any].make().pipe(provide_service(Scope, scope))
            run = yield from fiber_set.runtime()
            ready = Latch(False)

            def emit(data: PlatformMessage) -> None:
                if data[0] == 0:
                    if on_spawn is None:
                        ready.open_unsafe()
                    else:
                        run(on_spawn.ensuring(ready.open()))
                    return
                run(handler(data[1]))

            yield from self.listen(ListenOptions(port, emit, fiber_set.deferred, scope))
            # Fail fast if the worker goes away before it is ready, and stay
            # interruptible while waiting for it.
            yield from restore(ready.wait().race_first(fiber_set.join()))
            self.port = port
            pending, self.buffer = self.buffer, []
            for message, transfers in pending:
                yield from self.send_to_port(port, message, transfers)
            yield from restore(fiber_set.join())
            return cast("Never", None)

        return body


def make_platform[W, P: Port](
    *,
    setup: Callable[[SetupOptions[W]], Effect[P, WorkerError]],
    listen: Callable[[ListenOptions[P]], Effect[None]],
) -> WorkerPlatformService:
    """A ``WorkerPlatform`` from a transport's hooks (Effect's
    ``makePlatform``). ``setup`` starts the worker the ``Spawner`` gave and
    returns its port, adding to ``scope`` whatever stops it (each run asks
    the ``Spawner`` for a new worker); ``listen``
    wires the port's messages and failures."""

    def spawn(worker_id: int) -> Effect[Worker[Any, Any], WorkerError, Spawner]:
        def made(spawner: SpawnerFn) -> Worker[Any, Any]:
            spawned = _Spawned[P](lambda: spawner(worker_id), cast("Any", setup), listen)
            return Worker(send=spawned.send, run=spawned.run)

        return Spawner().map(made)

    return WorkerPlatformService(spawn)


__all__ = [
    "ListenOptions",
    "PlatformMessage",
    "Port",
    "RunFn",
    "SendFn",
    "SetupOptions",
    "Spawner",
    "SpawnerFn",
    "Transfers",
    "Worker",
    "WorkerError",
    "WorkerPlatform",
    "WorkerPlatformService",
    "layer_spawner",
    "make_platform",
    "make_unsafe",
]
