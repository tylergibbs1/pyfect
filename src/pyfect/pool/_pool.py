"""``Pool[A, E]``: borrow, invalidate and reserve pooled items."""
# pyright: reportPrivateUsage=false

from __future__ import annotations

import math
from collections.abc import Callable, Generator
from typing import Any, Final, Literal, Never, overload

from pyfect._core import (
    Effect,
    Frame,
    Restore,
    Step,
    _Callback,
    _FailCause,
    _FlatMap,
    _FromExit,
    _Gen,
    _Locally,
    _SetInterruptible,
    _Succeed,
    _Suspend,
    _Sync,
    _WithFiber,
    uninterruptible_mask,
)
from pyfect._effect_args import require_effect
from pyfect._fiber import Fiber
from pyfect._interrupt_reason import closed
from pyfect._unsubscripted import Unsubscripted
from pyfect.cause import Cause
from pyfect.cause import interrupt as interrupt_cause
from pyfect.clock import Clock, ClockService
from pyfect.context import Context
from pyfect.duration import Duration, to_seconds
from pyfect.exit import Exit, Failure, Success
from pyfect.logger._log import log_unhandled
from pyfect.pool._state import PoolConfig, PoolItem, PoolState, Strategy
from pyfect.pool._waiters import Waiter
from pyfect.scope import CloseableScope, Scope, acquire_release, fork_in
from pyfect.semaphore import Semaphore

_VOID: Final[Effect[None]] = _Succeed(None)

type TimeToLiveStrategy = Literal["creation", "usage"]

# Hands a borrower an item it may use: ``(item, value, fiber, restore)``.
type _Lease[A, E, X, R] = Callable[[PoolItem[A, E], A, Fiber[Any, Any], Restore], Effect[X, Any, R]]


class Pool[A = Unsubscripted, E = Never]:
    """Items acquired with a scoped effect and lent to fibers. Make one with
    ``Pool.make`` / ``make_with_ttl`` / ``make_with_strategy`` inside a
    scope; closing that scope shuts the pool down, waiting for borrowed
    items to come back before releasing everything."""

    __slots__ = ("_acquire", "_clock", "_context", "config", "state")

    def __init__(
        self,
        acquire: Effect[A, E, Any],
        context: Context,
        clock: ClockService,
        config: PoolConfig[A, E],
        state: PoolState[A, E],
    ) -> None:
        self._acquire = acquire
        self._context = context
        self._clock = clock
        self.config = config
        self.state = state

    # --- constructors ---------------------------------------------------------

    @overload
    @classmethod
    def make[T, X = Never, R = Never](
        cls: type[Pool[Unsubscripted, Any]],
        acquire: Effect[T, X, R],
        *,
        size: int,
        concurrency: int = 1,
        target_utilization: float = 1.0,
    ) -> Effect[Pool[T, X], Never, Scope | R]: ...
    @overload
    @classmethod
    def make[R = Never](
        cls,
        acquire: Effect[A, E, R],
        *,
        size: int,
        concurrency: int = 1,
        target_utilization: float = 1.0,
    ) -> Effect[Pool[A, E], Never, Scope | R]: ...
    @classmethod
    def make[T, X = Never, R = Never](
        cls,
        acquire: Effect[T, X, R],
        *,
        size: int,
        concurrency: int = 1,
        target_utilization: float = 1.0,
    ) -> Effect[Pool[T, X], Never, Scope | R]:
        """A pool of ``size`` items, acquired in the background at once.
        Each item serves up to ``concurrency`` borrowers at a time."""
        return Pool.make_with_strategy(
            acquire,
            min=size,
            max=size,
            strategy=_NOOP,
            concurrency=concurrency,
            target_utilization=target_utilization,
        )

    @overload
    @classmethod
    def make_with_ttl[T, X = Never, R = Never](
        cls: type[Pool[Unsubscripted, Any]],
        acquire: Effect[T, X, R],
        *,
        min: int,
        max: int,
        time_to_live: Duration,
        time_to_live_strategy: TimeToLiveStrategy = "usage",
        concurrency: int = 1,
        target_utilization: float = 1.0,
    ) -> Effect[Pool[T, X], Never, Scope | R]: ...
    @overload
    @classmethod
    def make_with_ttl[R = Never](
        cls,
        acquire: Effect[A, E, R],
        *,
        min: int,
        max: int,
        time_to_live: Duration,
        time_to_live_strategy: TimeToLiveStrategy = "usage",
        concurrency: int = 1,
        target_utilization: float = 1.0,
    ) -> Effect[Pool[A, E], Never, Scope | R]: ...
    @classmethod
    def make_with_ttl[T, X = Never, R = Never](
        cls,
        acquire: Effect[T, X, R],
        *,
        min: int,
        max: int,
        time_to_live: Duration,
        time_to_live_strategy: TimeToLiveStrategy = "usage",
        concurrency: int = 1,
        target_utilization: float = 1.0,
    ) -> Effect[Pool[T, X], Never, Scope | R]:
        """A pool between ``min`` and ``max`` items, growing with demand.
        Items above ``min`` are released once they have been idle
        (``"usage"``) or alive (``"creation"``) for ``time_to_live``."""
        from pyfect.pool._ttl import creation_ttl, usage_ttl

        require_effect(acquire, "acquire")
        _check_sizes(min, max, concurrency)
        ttl = to_seconds(time_to_live)
        make_strategy = creation_ttl if time_to_live_strategy == "creation" else usage_ttl
        strategy: Effect[Strategy[T, X]] = make_strategy(ttl)
        return strategy.flat_map(
            lambda s: Pool.make_with_strategy(
                acquire,
                min=min,
                max=max,
                strategy=s,
                concurrency=concurrency,
                target_utilization=target_utilization,
            )
        )

    @overload
    @classmethod
    def make_with_strategy[T, X = Never, R = Never](
        cls: type[Pool[Unsubscripted, Any]],
        acquire: Effect[T, X, R],
        *,
        min: int,
        max: int,
        strategy: Strategy[T, X],
        concurrency: int = 1,
        target_utilization: float = 1.0,
    ) -> Effect[Pool[T, X], Never, Scope | R]: ...
    @overload
    @classmethod
    def make_with_strategy[R = Never](
        cls,
        acquire: Effect[A, E, R],
        *,
        min: int,
        max: int,
        strategy: Strategy[A, E],
        concurrency: int = 1,
        target_utilization: float = 1.0,
    ) -> Effect[Pool[A, E], Never, Scope | R]: ...
    @classmethod
    def make_with_strategy[T, X = Never, R = Never](
        cls,
        acquire: Effect[T, X, R],
        *,
        min: int,
        max: int,
        strategy: Strategy[T, X],
        concurrency: int = 1,
        target_utilization: float = 1.0,
    ) -> Effect[Pool[T, X], Never, Scope | R]:
        """A pool between ``min`` and ``max`` items, resized by
        ``strategy``."""
        require_effect(acquire, "acquire")
        _check_sizes(min, max, concurrency)
        bounds = (min, max)

        def body(restore: Restore) -> Effect[Pool[T, X]]:
            def with_fiber(fiber: Fiber[Any, Any]) -> Effect[Pool[T, X]]:
                context = fiber._context
                scope = context.get_unsafe(Scope)
                config = PoolConfig(
                    acquire=_Locally(acquire, context.merge),
                    concurrency=concurrency,
                    is_fixed=bounds[0] == bounds[1],
                    min_size=bounds[0],
                    max_size=bounds[1],
                    strategy=strategy,
                    target_utilization=_clamp(target_utilization, 0.1, 1.0),
                )
                state: PoolState[T, X] = PoolState(scope, Semaphore(1))
                pool = Pool(acquire, context, context.lookup(Clock)[1], config, state)
                return _Gen(lambda: pool._start(scope, restore))

            return _WithFiber(with_fiber)

        return uninterruptible_mask(body)

    def _start(
        self, scope: CloseableScope, restore: Restore
    ) -> Generator[Effect[Any, Any, Any], Any, Pool[A, E]]:
        yield from scope.add_finalizer(lambda _: self._shutdown())
        if self.config.min_size > 0:
            resizing = yield from restore(self._resize()).fork_daemon(start_immediately=True)
            yield from scope.add_finalizer(lambda _: resizing.interrupt())
        if self.config.strategy is not _NOOP:
            running = yield from restore(self.config.strategy.run(self)).fork_daemon()
            yield from scope.add_finalizer(lambda _: running.interrupt())
        return self

    # --- borrowing ------------------------------------------------------------

    def get(self) -> Effect[A, E, Scope]:
        """Borrow an item until the current scope closes, waiting for one
        if none is free. Fails with the acquisition's error if acquiring
        the item failed; interrupted once the pool is shutting down."""

        def body(fiber: Fiber[Any, Any]) -> Effect[A, E, Scope]:
            fast = self._fast_item()
            if fast is not None:
                item, value = fast
                return self._lease_scoped(item, value, fiber)
            return self._get_slow(
                lambda item, value, fiber, _restore: self._lease_scoped(item, value, fiber)
            )

        return _WithFiber(body)

    def use[B, E2 = Never, R2 = Never](
        self, f: Callable[[A], Effect[B, E2, R2]]
    ) -> Effect[B, E | E2, R2]:
        """Borrow an item for as long as ``f(item)`` runs."""

        def body(fiber: Fiber[Any, Any]) -> Effect[B, E | E2, R2]:
            fast = self._fast_item()
            if fast is not None:
                item, value = fast
                return self._use_item(item, value, f, fiber, None)
            return self._get_slow(
                lambda item, value, fiber, restore: self._use_item(item, value, f, fiber, restore)
            )

        return _WithFiber(body)

    def invalidate(self, item: A) -> Effect[None]:
        """Release ``item`` once nobody borrows it, and acquire a
        replacement. The item is found by identity (``is``), as Effect's
        ``===``."""

        def body() -> Effect[None]:
            if self.state.is_shutting_down:
                return _VOID
            pool_item = self._find(item)
            if pool_item is None:
                return _VOID
            pool_item.disable_reclaim = True
            return self._invalidate_item(pool_item).uninterruptible()

        return _Suspend(body)

    def reserve(self, item: A) -> Effect[None, Never, Scope]:
        """Keep ``item`` from new borrowers until the current scope closes,
        counting it as fully used, without extending existing leases. A
        no-op when each item serves one borrower. The item is found by
        identity (``is``)."""
        state = self.state
        concurrency = self.config.concurrency

        def take() -> PoolItem[A, E] | None:
            if concurrency == 1:
                return None
            pool_item = self._find(item)
            if pool_item is None:
                return None
            if pool_item.reservations == 0:
                state.usage += concurrency - 1
            pool_item.reservations += 1
            state._remove_available(pool_item)
            return pool_item

        def give_back(pool_item: PoolItem[A, E] | None) -> Effect[None]:
            def run(fiber: Fiber[Any, Any]) -> Effect[None]:
                if pool_item is None:
                    return _VOID
                pool_item.reservations -= 1
                if pool_item.reservations > 0:
                    return _VOID
                state.usage -= concurrency - 1
                if (
                    not state.is_shutting_down
                    and pool_item in state.items
                    and pool_item not in state.invalidated
                    and pool_item.ref_count < concurrency
                ):
                    state._add_available_front(pool_item)
                    self._wake_waiters(fiber, concurrency - pool_item.ref_count)
                return _VOID

            return _WithFiber(run)

        return acquire_release(_Sync(take), lambda pool_item, _: give_back(pool_item)).as_void()

    def _find(self, value: A) -> PoolItem[A, E] | None:
        """The pool item holding ``value`` itself; an equal value is another item."""
        for pool_item in self.state.items:
            if isinstance(pool_item.exit, Success) and pool_item.exit.value is value:
                return pool_item
        return None

    # --- leases ---------------------------------------------------------------

    def _fast_item(self) -> tuple[PoolItem[A, E], A] | None:
        """The item a borrower takes without waiting, counted in ``usage``,
        if one is free, nobody waits and the pool need not grow first."""
        state = self.state
        head = state.available_head
        if state.is_shutting_down or state.waiters or head is None:
            return None
        if not isinstance(head.exit, Success):
            return None
        state.usage += 1
        if self.config.is_fixed or self._target_size() <= self._active_size():
            return head, head.exit.value
        state.usage -= 1
        return None

    def _bookkeep(self, item: PoolItem[A, E]) -> None:
        item.ref_count += 1
        if item.ref_count >= self.config.concurrency:
            self.state._remove_available(item)

    def _lease_scoped(self, item: PoolItem[A, E], value: A, fiber: Fiber[Any, Any]) -> Effect[A]:
        self._bookkeep(item)
        scope = fiber._context.get_unsafe(Scope)
        if scope.is_closed:
            fiber._push(_Release(self._release_item(item)))
        else:
            scope._add(object(), lambda _: self._release_item(item))
        return _Succeed(value)

    def _use_item[B, E2, R2](
        self,
        item: PoolItem[A, E],
        value: A,
        f: Callable[[A], Effect[B, E2, R2]],
        fiber: Fiber[Any, Any],
        restore: Restore | None,
    ) -> Effect[B, E2, R2]:
        # Count the lease and install its release in the same step.
        self._bookkeep(item)
        fiber._push(_Release(self._release_item(item)))
        body: Effect[B, E2, R2] = _Suspend(lambda: f(value))
        return body if restore is None else restore(body)

    def _get_slow[X, R](self, lease: _Lease[A, E, X, R]) -> Effect[X, Any, R]:
        def body(restore: Restore) -> Effect[X, Any, R]:
            state = self.state
            state.usage += 1
            waiter = Waiter()

            def leave(fiber: Fiber[Any, Any]) -> Effect[None]:
                state.usage -= 1
                # Only a woken waiter is still registered here: one cancelled
                # while asleep already left. It passes its wake on, so the
                # capacity it was woken for is not stranded.
                if state.waiters.leave(waiter):
                    self._wake_waiters(fiber, 1)
                return _VOID

            wait: Effect[X, Any, R] = (
                restore(self._wait_for_item(waiter))
                .on_error(lambda _: _WithFiber(leave))
                .flat_map(lambda _: loop)
            )

            def attempt(fiber: Fiber[Any, Any]) -> Effect[X, Any, R]:
                if state.is_shutting_down:
                    state.usage -= 1
                    return _FailCause(interrupt_cause(fiber.id).annotate(closed("Pool")))
                # A borrower that has not waited yet queues behind those
                # already waiting, who keep their place until they take an
                # item.
                if state.waiters and waiter not in state.waiters:
                    return wait
                # Replace failed slots only when the pool cannot grow.
                item = state._first_healthy_available()
                if item is None and self._target_size() <= self._active_size():
                    item = state.available_head
                if item is None:
                    return wait
                if isinstance(item.exit, Failure):
                    state._remove(item)
                    return loop
                state.waiters.leave(waiter)
                return lease(item, item.exit.value, fiber, restore)

            step: Effect[X, Any, R] = _WithFiber(attempt)

            def grow(fiber: Fiber[Any, Any]) -> Effect[X, Any, R]:
                if state.is_shutting_down:
                    state.usage -= 1
                    return _FailCause(interrupt_cause(fiber.id).annotate(closed("Pool")))
                if self._target_size() <= self._active_size():
                    return step
                resize = fork_in(self._resize().interruptible(), state.scope)
                return state.resize_semaphore.with_permits_if_available(resize).and_then(step)

            loop: Effect[X, Any, R] = _WithFiber(grow)
            return loop

        return uninterruptible_mask(body)

    def _wait_for_item(self, waiter: Waiter) -> Effect[None, Any]:
        state = self.state

        def register(resume: Callable[[Effect[None, Any]], None]) -> Effect[None] | None:
            if state.is_shutting_down or (
                not state.waiters and state._first_healthy_available() is not None
            ):
                resume(_VOID)
                return None
            state.waiters.park(waiter, resume)
            return _Sync(lambda: state.waiters.cancel(waiter))

        return _Callback(register)

    def _release_item(self, item: PoolItem[A, E]) -> Effect[None]:
        def run(fiber: Fiber[Any, Any]) -> Effect[None]:
            state = self.state
            item.ref_count -= 1
            state.usage -= 1
            if item.ref_count == 0:
                item.idle_since = self._clock.now_nanos_unsafe()
            if item in state.invalidated:
                return self._invalidate_item(item)
            # Every release frees one slot, so it admits one waiter.
            if item.ref_count < self.config.concurrency:
                state._add_available_front(item)
                self._wake_waiters(fiber, 1)
            return _VOID

        return _WithFiber(run)

    def _wake_waiters(self, fiber: Fiber[Any, Any], count: int) -> None:
        state = self.state
        state.waiters.wake(fiber._scheduler, count, lambda: state.available_head is not None)

    # --- sizing ---------------------------------------------------------------

    def _target_size(self) -> int:
        if self.state.is_shutting_down:
            return 0
        config = self.config
        if config.is_fixed:
            return config.min_size
        target = math.ceil(self.state.usage / config.target_utilization / config.concurrency)
        return _clamp(target, config.min_size, config.max_size)

    def _active_size(self) -> int:
        return len(self.state.items) - len(self.state.invalidated)

    def _invalidate_item(self, item: PoolItem[A, E]) -> Effect[None]:
        state = self.state

        def body() -> Effect[None]:
            if item not in state.items:
                return _VOID
            resize = fork_in(
                self._resize().interruptible(), state.scope, start_immediately=True
            ).as_void()
            if item.ref_count == 0:
                state._remove(item)
                return item.finalizer.and_then(resize)
            # An invalidated item stops counting towards the active size, so
            # the pool tops itself up now: borrowers already queued would
            # otherwise wait for an item that is never coming back.
            state.invalidated[item] = None
            state._remove_available(item)
            return resize

        return _Suspend(body)

    def _resize(self) -> Effect[None]:
        resize = self.state.resize_semaphore.with_permits(self._resize_loop())
        return resize.and_then(_WithFiber(self._after_resize))

    def _after_resize(self, fiber: Fiber[Any, Any]) -> Effect[None]:
        # A borrower that found this resize running parked without starting
        # one. Effect resumes the resize as its acquisitions finish, so it is
        # done by then; here it resumes later, so if the pool still needs to
        # grow, the borrowers retry and start the next resize.
        if self._target_size() > self._active_size():
            self.state.waiters.wake_all(fiber._scheduler)
        return _VOID

    def _resize_loop(self) -> Effect[None]:
        def body() -> Effect[None]:
            active = self._active_size()
            target = self._target_size()
            if active >= target:
                return _VOID
            to_acquire = target - active
            acquire_one = self._acquire_one()
            fixed = self.config.is_fixed
            if to_acquire == 1:
                if fixed:
                    return acquire_one.as_void()
                return acquire_one.flat_map(
                    lambda item: _VOID if isinstance(item.exit, Failure) else self._resize_loop()
                )
            acquired = acquire_one.replicate_effect(to_acquire, concurrency=to_acquire)
            if fixed:
                return acquired.as_void()
            return acquired.flat_map(
                lambda items: (
                    _VOID
                    if any(isinstance(i.exit, Failure) for i in items)
                    else self._resize_loop()
                )
            )

        return _Suspend(body)

    def _acquire_one(self) -> Effect[PoolItem[A, E]]:
        """One item, reclaimed or acquired. Waiters are woken as each item
        arrives, not once the whole batch is in."""
        strategy = self.config.strategy
        state = self.state

        def rejoin(item: PoolItem[A, E] | None) -> Effect[PoolItem[A, E]]:
            if item is None:
                return self._allocate()
            # A reclaimed item rejoins circulation like a released one.
            if item in state.items and item not in state.invalidated:
                state._add_available_front(item)
            return _Succeed(item)

        item = self._allocate() if strategy is _NOOP else strategy.reclaim(self).flat_map(rejoin)

        def wake(fiber: Fiber[Any, Any], item: PoolItem[A, E]) -> Effect[None]:
            # A failed acquisition wakes everyone to retry it. A new item
            # serves as many waiters as it has slots.
            if isinstance(item.exit, Failure):
                self.state.waiters.wake_all(fiber._scheduler)
            else:
                self._wake_waiters(fiber, self.config.concurrency)
            return _VOID

        return item.tap(lambda i: _WithFiber(lambda fiber: wake(fiber, i)))

    def _allocate(self) -> Effect[PoolItem[A, E]]:
        def body(restore: Restore) -> Effect[PoolItem[A, E]]:
            scope = CloseableScope()
            context = self._context.add(Scope, scope)
            acquire: Effect[A, E] = _Locally(self._acquire, lambda _: context)
            acquired = acquire.exit().flat_map(lambda ex: self._track(ex, scope))
            return restore(acquired).on_exit(
                lambda ex: scope.close(ex) if isinstance(ex, Failure) else _VOID
            )

        return uninterruptible_mask(body)

    def _track(self, ex: Exit[A, E], scope: CloseableScope) -> Effect[PoolItem[A, E]]:
        state = self.state
        strategy = self.config.strategy
        item = PoolItem(
            ex,
            scope.close(ex).catch_cause(_report_finalizer_failure),
            self._clock.now_nanos_unsafe(),
        )

        def on_acquire() -> Effect[None]:
            # A borrower may have removed the item before this runs.
            return strategy.on_acquire(item) if item in state.items else _VOID

        if isinstance(ex, Success):
            state.items[item] = None
            state._add_available(item)
            return _Succeed(item) if strategy is _NOOP else _Suspend(on_acquire).as_(item)
        # Hand a waiting borrower its own failure; otherwise keep the slot.
        waiter = (
            state.waiters.first_sleeping() if state._first_healthy_available() is None else None
        )
        if waiter is not None:
            waiter(_FailCause(ex.cause))
        else:
            state.items[item] = None
            state._add_available(item)
        # Cleanup must not delay a replacement acquisition.
        cleanup = item.finalizer.and_then(_Suspend(on_acquire))
        return fork_in(cleanup, state.scope, start_immediately=True).as_(item)

    # --- shutdown -------------------------------------------------------------

    def _shutdown(self) -> Effect[None]:
        def body() -> Generator[Effect[Any, Any, Any], Any]:
            state = self.state
            if state.is_shutting_down:
                return
            state.is_shutting_down = True
            size = len(state.items)
            returned = Semaphore(size)
            for item in list(state.items):
                if item.ref_count > 0:
                    item.finalizer = item.finalizer.and_then(returned.release(1).as_void())
                    state.invalidated[item] = None
                    yield from returned.take(1)
                else:
                    state._remove(item)
                    yield from item.finalizer
            state.waiters.release_all()
            # Wait for every borrowed item to come back and be released.
            yield from returned.take(size)

        return _Gen(body)


class _Release(Frame):
    """Below a lease's body: returns the item however the body ends. The
    release runs uninterruptibly, then the borrower ends as its body did."""

    __slots__ = ("release",)

    def __init__(self, release: Effect[None]) -> None:
        self.release = release

    def _on_success(self, value: Any, fiber: Fiber[Any, Any]) -> Step:
        return self._run(Success(value), fiber)

    def _on_failure(self, cause: Cause[Any], fiber: Fiber[Any, Any]) -> Step:
        return self._run(Failure(cause), fiber)

    def _run(self, ex: Exit[Any, Any], fiber: Fiber[Any, Any]) -> Step:
        # Stepped here, not returned: an interrupted fiber would turn a
        # returned effect into a failure before it could run.
        return _SetInterruptible(_FlatMap(self.release, lambda _: _FromExit(ex)), False)._step(
            fiber
        )


def _report_finalizer_failure(cause: Cause[Any]) -> Effect[None]:
    return log_unhandled("Unhandled error in pool finalizer", cause)


def _clamp[N: (int, float)](value: N, low: N, high: N) -> N:
    return low if value < low else high if value > high else value


def _check_sizes(minimum: int, maximum: int, concurrency: int) -> None:
    if minimum < 0 or maximum < 1 or maximum < minimum:
        raise ValueError(f"pool sizes need 0 <= min <= max and max >= 1, got {minimum}, {maximum}")
    if concurrency < 1:
        raise ValueError(f"concurrency must be >= 1, got {concurrency}")


def _noop_run(_: Pool[Any, Any]) -> Effect[None]:
    return _VOID


def _noop_on_acquire(_: PoolItem[Any, Any]) -> Effect[None]:
    return _VOID


def _noop_reclaim(_: Pool[Any, Any]) -> Effect[PoolItem[Any, Any] | None]:
    return _Succeed(None)


_NOOP: Final[Strategy[Any, Any]] = Strategy(_noop_run, _noop_on_acquire, _noop_reclaim)
