"""``ManagedRuntime[R, ER]``: a layer built once and kept, to run many
effects with its services, as Effect's ``ManagedRuntime``.

The layer is built on first use (or on entering the runtime as a context
manager) and shared by every run until the runtime is disposed. Disposal
interrupts and awaits the fibers the runtime started, then releases the
layer's resources; later runs die.

Built for an application's lifetime, such as a web server's lifespan::

    async with ManagedRuntime.make(AppLive) as runtime:   # builds AppLive
        ...
        response = await runtime.run_async(handle(request))  # per request
    # AppLive's resources are released here

Where runs go:

- ``run_async`` / ``run_async_exit``: on the running asyncio loop.
- ``run_blocking`` / ``run_blocking_exit``: on a scheduler the runtime owns,
  driven by the calling thread until the effect is done. These runs share it,
  one thread at a time, so fibers the layer forked go on running during
  each of them.
- ``run_sync`` / ``run_sync_exit``: the same scheduler, flushed once; an
  effect that waits dies with ``AsyncFiberError``, as Effect's ``runSync``.
- ``run_fork`` / ``run_callback``: on the current fiber's run, else the
  running loop, else the runtime's own scheduler (they then make progress
  while a sync run or ``dispose`` drives it).

Each run reads its caller's ``contextvars`` (a request id set before the
call), however many callers share the runtime.

``dispose`` (and a sync ``with``) blocks, so it raises inside a fiber or a
running asyncio loop, whose fibers it could never see finish: use
``dispose_effect`` or ``dispose_async`` (``async with``) there.
"""
# pyright: reportPrivateUsage=false

from __future__ import annotations

import asyncio
import threading
from collections.abc import Callable, Iterator
from types import TracebackType
from typing import Any, Generic, Never, Self, TypeVar
from weakref import WeakSet

from pyfect._core import Effect, Restore, _Locally, _Succeed, _WithFiber, uninterruptible_mask
from pyfect._effect_args import require_effect
from pyfect._fiber import Fiber, current_fiber, current_run_scheduler
from pyfect._layer_core import require_layer
from pyfect._root import loop_running_here, new_root, start_root
from pyfect.context import Context, Reference
from pyfect.deferred import Deferred
from pyfect.effect import die
from pyfect.exit import Exit, Failure, Success
from pyfect.layer import Layer, MemoMap
from pyfect.run import Interruptor, await_fiber, drive, flush_exit, unwrap
from pyfect.scheduler import AsyncioScheduler, Scheduler, SyncOnlyScheduler, SyncScheduler
from pyfect.scope import CloseableScope

R_contra = TypeVar("R_contra", contravariant=True)
ER_co = TypeVar("ER_co", covariant=True, default=Never)


class _DisposingRuntimes(Reference[frozenset[object]]):
    """The runtimes whose disposal the current fiber is running. Finalizers
    inherit it from the disposing fiber, so a finalizer that disposes a
    runtime being disposed (its own, or one disposing it in turn) does not
    wait for itself."""

    @classmethod
    def default(cls) -> frozenset[object]:
        return frozenset()


class ManagedRuntime(Generic[R_contra, ER_co]):
    """Runs effects needing ``R`` with the services of a layer that may
    fail with ``ER``. See the module docstring."""

    __slots__ = (
        "_build_fiber",
        "_build_lock",
        "_cached",
        "_context_effect",
        "_disposed",
        "_disposing",
        "_fiber_scope",
        "_layer",
        "_layer_scope",
        "_loop",
        "_managed",
        "_scope",
        "_sync",
        "_sync_lock",
        "memo_map",
    )

    def __init__(self, layer: Layer[R_contra, ER_co], *, memo_map: MemoMap | None = None) -> None:
        """Nothing is built until the first run. Runtimes given the same
        ``memo_map`` build each layer once between them."""
        require_layer(layer, "layer")
        self.memo_map = MemoMap() if memo_map is None else memo_map
        self._layer = layer
        self._scope = CloseableScope()
        self._layer_scope = self._scope.fork_unsafe()
        self._fiber_scope = self._scope.fork_unsafe("parallel")
        # Fibers the runtime started (requests and the layer build), and
        # fibers running its disposal: disposal must not wait for them.
        self._managed: WeakSet[Fiber[Any, Any]] = WeakSet()
        self._disposing: WeakSet[Fiber[Any, Any]] = WeakSet()
        self._build_fiber: Fiber[Context, Any] | None = None
        self._build_lock = threading.Lock()
        self._disposed: Deferred[None] | None = None
        self._cached: Context | None = None
        self._context_effect: Effect[Context, Any] = _WithFiber(self._context_in)
        self._sync = SyncOnlyScheduler()
        self._sync_lock = threading.RLock()
        self._loop: tuple[asyncio.AbstractEventLoop, AsyncioScheduler] | None = None

    @staticmethod
    def make[R, ER = Never](
        layer: Layer[R, ER], *, memo_map: MemoMap | None = None
    ) -> ManagedRuntime[R, ER]:
        return ManagedRuntime(layer, memo_map=memo_map)

    # --- the layer's services ---------------------------------------------------

    @property
    def context_effect(self) -> Effect[Context[R_contra], ER_co]:
        """Builds the layer once and succeeds with its services. Read after
        the runtime is disposed, it is an effect that dies. One read before
        disposal is not stopped by it, as in Effect: run later, it can still
        succeed, with services whose resources were released."""
        return self._context_effect

    async def context(self) -> Context[R_contra]:
        """The layer's services, building it on the running loop if needed."""
        if self._cached is not None:
            return self._cached
        return unwrap(await self._run_async_unmanaged(self._context_effect))

    def _context_in(self, fiber: Fiber[Any, Any]) -> Effect[Context, Any]:
        # Runs from sync runs on any thread and from loops: one build only.
        with self._build_lock:
            builder = self._build_fiber
            if builder is None:
                # On the requesting fiber's run and scheduler, as Effect's build.
                builder = new_root(
                    fiber._run_scheduler, Context.empty(), scheduler=fiber._scheduler
                )
                self._build_fiber = builder
                start = True
            else:
                start = False
        if start:
            build = self._layer.build_with_memo_map(self.memo_map, self._layer_scope).map(
                self._cache
            )
            start_root(builder, build)
            # Unlike a request, the build joins the fiber scope even if it
            # disposed the runtime, so disposal still interrupts it.
            self._managed.add(builder)
            builder.run_in(self._fiber_scope)
        return builder.join()

    def _cache(self, context: Context) -> Context:
        self._cached = context
        return context

    def _provided[A, E](self, eff: Effect[A, E, Any]) -> tuple[Context, Effect[A, Any, Any]]:
        """The context to start a request with, and what it runs."""
        if self._cached is not None:
            return self._cached, eff

        def with_services(built: Context) -> Effect[A, E, Any]:
            return _Locally(eff, lambda current: current.merge(built))

        provided = self._context_effect.flat_map(with_services)
        return Context.empty(), provided

    # --- running effects -----------------------------------------------------------

    def run_fork[A, E = Never](
        self,
        eff: Effect[A, E, R_contra],
        *,
        scheduler: Scheduler | None = None,
        uninterruptible: bool = False,
    ) -> Fiber[A, E | ER_co]:
        """Start ``eff`` with the layer's services and return its fiber
        (see the module docstring for where it runs)."""
        require_effect(eff, "eff")
        current = current_run_scheduler()
        if current is not None:
            run: Scheduler = current
        elif loop_running_here():
            run = self._loop_scheduler()
        else:
            # Another thread may be driving the runtime's scheduler: queue it.
            return self._start(
                self._sync, eff, scheduler=scheduler, uninterruptible=uninterruptible
            )
        return self._start(run, eff, scheduler=scheduler, uninterruptible=uninterruptible, now=True)

    def run_callback[A, E = Never](
        self,
        eff: Effect[A, E, R_contra],
        *,
        on_exit: Callable[[Exit[A, E | ER_co]], None] | None = None,
        scheduler: Scheduler | None = None,
        uninterruptible: bool = False,
    ) -> Interruptor:
        """``run_fork``, calling ``on_exit`` with the exit. Returns a
        function that interrupts the fiber."""
        require_effect(eff, "eff")
        fiber = self.run_fork(eff, scheduler=scheduler, uninterruptible=uninterruptible)
        if on_exit is not None:
            fiber.add_observer_unsafe(on_exit)

        def interrupt(by: int | None = None, /) -> None:
            fiber.interrupt_as_unsafe(by)

        return interrupt

    def run_sync_exit[A, E = Never](self, eff: Effect[A, E, R_contra]) -> Exit[A, E | ER_co]:
        require_effect(eff, "eff")
        scheduler = SyncOnlyScheduler() if current_run_scheduler() is self._sync else self._sync
        fiber = self._start(scheduler, eff)
        with self._sync_lock:
            return flush_exit(scheduler, fiber)

    def run_sync[A](self: ManagedRuntime[R_contra, Never], eff: Effect[A, Never, R_contra]) -> A:
        require_effect(eff, "eff")
        return unwrap(self.run_sync_exit(eff))

    def run_blocking_exit[A, E = Never](self, eff: Effect[A, E, R_contra]) -> Exit[A, E | ER_co]:
        require_effect(eff, "eff")
        # Called from one of the runtime's own sync fibers, driving its
        # scheduler would stall that fiber's run: the nested run gets its own.
        scheduler = SyncScheduler() if current_run_scheduler() is self._sync else self._sync
        fiber = self._start(scheduler, eff)
        with self._sync_lock:
            return drive(scheduler, fiber)

    def run_blocking[A](
        self: ManagedRuntime[R_contra, Never], eff: Effect[A, Never, R_contra]
    ) -> A:
        require_effect(eff, "eff")
        return unwrap(self.run_blocking_exit(eff))

    async def run_async_exit[A, E = Never](self, eff: Effect[A, E, R_contra]) -> Exit[A, E | ER_co]:
        """Run on the running loop. Cancelling the awaiting task interrupts
        the effect and waits for its finalizers."""
        require_effect(eff, "eff")
        # Started now, as Effect's ``runPromise`` evaluates it: after dispose
        # it dies before joining the closed fiber scope would interrupt it.
        return await await_fiber(self._start(self._loop_scheduler(), eff, now=True))

    async def run_async[A](
        self: ManagedRuntime[R_contra, Never], eff: Effect[A, Never, R_contra]
    ) -> A:
        require_effect(eff, "eff")
        return unwrap(await self.run_async_exit(eff))

    def _start[A, E](
        self,
        run: Scheduler,
        eff: Effect[A, E, Any],
        *,
        scheduler: Scheduler | None = None,
        uninterruptible: bool = False,
        now: bool = False,
    ) -> Fiber[A, Any]:
        context, target = self._provided(eff)
        fiber = new_root(run, context, scheduler=scheduler, uninterruptible=uninterruptible)
        start_root(fiber, target, now=now)
        self._managed.add(fiber)
        if fiber not in self._disposing:
            fiber.run_in(self._fiber_scope)
        return fiber

    def _loop_scheduler(self) -> AsyncioScheduler:
        loop = asyncio.get_running_loop()
        if self._loop is None or self._loop[0] is not loop:
            self._loop = (loop, AsyncioScheduler(loop))
        return self._loop[1]

    # --- disposal ----------------------------------------------------------------

    @property
    def dispose_effect(self) -> Effect[None]:
        """Dispose of the runtime, uninterruptibly. Calls made while a
        disposal runs wait for it, except from the fibers it interrupts or
        runs (requests, their children, the runtime's finalizers), which
        would wait for themselves. Interrupting a waiting call only stops
        the wait."""
        return uninterruptible_mask(
            lambda restore: _WithFiber(lambda fiber: self._dispose_in(fiber, restore))
        )

    def dispose(self) -> None:
        """Dispose, blocking until the layer's resources are released.
        Raises ``RuntimeError`` inside a fiber or a running asyncio loop,
        whose fibers it could never see finish."""
        _refuse_to_block("ManagedRuntime.dispose()", "await dispose_async()")
        fiber = new_root(self._sync, Context.empty())
        fiber._start(self.dispose_effect)
        with self._sync_lock:
            unwrap(drive(self._sync, fiber))

    async def dispose_async(self) -> None:
        """Dispose on the running loop."""
        unwrap(await self._run_async_unmanaged(self.dispose_effect))

    def _dispose_in(self, fiber: Fiber[Any, Any], restore: Restore) -> Effect[None]:
        """Runs uninterruptibly: once ``_disposed`` is set the close must
        run, or later calls would wait forever."""
        disposing: frozenset[object] = fiber._context.lookup(_DisposingRuntimes)[1]
        if self._disposed is not None:
            if self in disposing or any(f in self._managed for f in _lineage(fiber)):
                return _Succeed(None)
            return restore(self._disposed.wait())
        done = self._disposed = Deferred[None]()
        # Closing the fiber scope interrupts and awaits every request. Spare
        # the disposing fiber and its ancestors, which would await themselves.
        for f in _lineage(fiber):
            self._disposing.add(f)
            self._fiber_scope._remove(f)
        self._context_effect = die(RuntimeError("ManagedRuntime disposed"))
        self._cached = None
        close: Effect[None] = _Locally(
            self._scope.close(Success(None)),
            lambda ctx: ctx.add(_DisposingRuntimes, disposing | {self}),
        )
        return close.ensuring(done.done(Success(None)))

    async def _run_async_unmanaged[A](self, eff: Effect[A, Any]) -> Exit[A, Any]:
        """Run on the loop as a plain run, not one of the runtime's requests
        (Effect's ``runPromise``)."""
        fiber = new_root(self._loop_scheduler(), Context.empty())
        fiber._start(eff)
        return await await_fiber(fiber)

    # --- context managers ----------------------------------------------------------

    def __enter__(self) -> Self:
        """Build the layer, so startup errors surface here (disposing what
        was built before raising). Refused where ``dispose`` is."""
        _refuse_to_block("A sync `with` on a ManagedRuntime", "async with")
        fiber = new_root(self._sync, Context.empty())
        fiber._start(self._context_effect)
        with self._sync_lock:
            ex = drive(self._sync, fiber)
        if isinstance(ex, Failure):
            self.dispose()
            unwrap(ex)
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.dispose()

    async def __aenter__(self) -> Self:
        """Build the layer on the running loop (see ``__enter__``)."""
        ex = await self._run_async_unmanaged(self._context_effect)
        if isinstance(ex, Failure):
            await self.dispose_async()
            unwrap(ex)
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.dispose_async()


def _lineage(fiber: Fiber[Any, Any]) -> Iterator[Fiber[Any, Any]]:
    """The fiber and its ancestors (forked children, not daemons, have a
    parent)."""
    current: Fiber[Any, Any] | None = fiber
    while current is not None:
        yield current
        current = current._parent


def _refuse_to_block(call: str, on_a_loop: str) -> None:
    if current_fiber() is not None:
        raise RuntimeError(f"{call} blocks, and this thread is running a fiber: use dispose_effect")
    if loop_running_here():
        raise RuntimeError(f"{call} blocks the running asyncio loop: use {on_a_loop}")


__all__ = ["ManagedRuntime"]
