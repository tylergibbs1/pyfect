"""Collecting requests into batches and running them (Effect's
``internal/request.ts``).

A request joins its resolver's pending batch for its key, or starts one.
A new batch starts a root fiber that waits out the resolver's ``delay``
and then runs the batch; a request that makes ``collect_while`` say no
interrupts that wait and runs the batch at once. A batch runs on a root
fiber with the services of the request that started it.

An interrupted caller leaves its batch; the last one to leave interrupts
the batch's wait, so the batch never runs.

Pending batches are kept per run as well as per key: a ``run_blocking``'s
scheduler stops when the run ends, so a batch a daemon left behind there
would never run, and a later run joining it would wait forever.
"""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from collections.abc import Callable, Hashable
from dataclasses import dataclass
from types import NoneType
from typing import Any, Final, final

from pyfect._core import Effect, _Callback, _FromExit, _Succeed, _Suspend, _Sync, _WithFiber
from pyfect._fiber import Fiber
from pyfect._root import new_root, run_identity, start_root
from pyfect.batching._request import Entry, EqualKeys
from pyfect.batching._resolver import RequestResolver
from pyfect.context import Context
from pyfect.exit import Exit, Failure
from pyfect.exit import die as exit_die
from pyfect.exit import interrupt as exit_interrupt
from pyfect.scheduler import Scheduler

_VOID: Final[Effect[None]] = _Succeed(None)


class UncompletedRequestError(RuntimeError):
    """The defect a request dies with when its batch ran to the end
    without completing it."""

    def __init__(self, request: object) -> None:
        super().__init__(f"Effect.request: RequestResolver did not complete request {request!r}")
        self.request = request


@dataclass(frozen=True, slots=True)
class Origin:
    """Where a request was made: the services and run of its fiber, the
    fiber's id (``None`` outside a fiber) and whether a root fiber started
    from there runs at once."""

    context: Context
    run_scheduler: Scheduler
    fiber_id: int | None
    now: bool = False

    def slot(self, key: Hashable) -> Slot:
        """Where the pending batch for ``key`` made from here is kept."""
        return (run_identity(self.run_scheduler), key)


@final
class _ByReference:
    """A key that matches only itself, and keeps it alive while it is pending."""

    __slots__ = ("key",)

    def __init__(self, key: object) -> None:
        self.key = key

    def __eq__(self, other: object) -> bool:
        return isinstance(other, _ByReference) and other.key is self.key

    def __hash__(self) -> int:
        return id(self.key)


def _slot_key(resolver: RequestResolver[Any, Any], key: Hashable) -> Hashable:
    if isinstance(resolver.batch_key, EqualKeys) or isinstance(
        key, (str, bytes, int, float, NoneType)
    ):
        return key
    return _ByReference(key)


type Slot = tuple[object, Hashable]
"""A pending batch's place in its resolver: its run and its key."""


class Batch:
    """A resolver's batch for one key. ``entries`` are what ``run_all``
    gets; ``pending`` are the entries whose callers still wait for this
    batch to complete them."""

    __slots__ = ("entries", "fiber", "key", "origin", "pending", "resolver", "slot")

    def __init__(self, resolver: RequestResolver[Any, Any], key: Hashable, origin: Origin) -> None:
        self.resolver = resolver
        self.key = key
        self.origin = origin
        self.slot = origin.slot(_slot_key(resolver, key))
        # Dicts as insertion-ordered sets.
        self.entries: dict[Entry[Any], None] = {}
        self.pending: dict[Entry[Any], None] = {}
        self.fiber: Fiber[Any, Any] | None = None

    def wait_then_run(self) -> Effect[None]:
        """The delay fiber's effect."""

        def wait(fiber: Fiber[Any, Any]) -> Effect[None]:
            # A delay that makes requests itself may fill this batch and
            # interrupt this fiber before ``start_root`` returns.
            self.fiber = fiber
            return self.resolver.delay

        return _WithFiber(wait).flat_map(lambda _: self.take())

    def take(self) -> Effect[None, Any]:
        """Remove the batch from its resolver and give the effect that runs
        it, unless it was removed already (cancelled, or run)."""
        batches = self.resolver._batches
        if batches.get(self.slot) is not self:
            return _VOID
        del batches[self.slot]
        return _Suspend(lambda: self.resolver.run_all(list(self.entries), self.key)).on_exit(
            self._finish
        )

    def _finish(self, ex: Exit[None, Any]) -> Effect[None]:
        for entry in list(self.pending):
            entry._complete(
                exit_die(UncompletedRequestError(entry.request))
                if not isinstance(ex, Failure)
                else ex
            )
        self.entries.clear()
        return _VOID


def add_entry(
    resolver: RequestResolver[Any, Any],
    request: object,
    resume: Callable[[Exit[Any, Any]], None],
    origin: Origin,
) -> Entry[Any]:
    """Add a request to its batch. ``resume`` gets its exit, once, unless
    the caller left first."""
    batch: Batch | None = None
    completed = False

    def complete(ex: Exit[Any, Any]) -> None:
        nonlocal completed
        if completed:
            return
        completed = True
        # A removed entry still reaches resolver hooks (``with_cache``
        # wraps this function), but not its caller, who has left.
        if batch is not None:
            if entry not in batch.pending:
                return
            del batch.pending[entry]
        resume(ex)

    entry = Entry[Any](request, context=origin.context, complete_unsafe=complete)
    if resolver.pre_check is not None and not resolver.pre_check(entry):
        return entry
    key = resolver.batch_key(entry)
    slot = origin.slot(_slot_key(resolver, key))
    batches = resolver._batches
    batch = batches.get(slot)
    if batch is None:
        batch = batches[slot] = Batch(resolver, key, origin)
        batch.pending[entry] = None
        batch.entries[entry] = None
        delay_fiber: Fiber[Any, Any] = new_root(origin.run_scheduler, origin.context)
        batch.fiber = delay_fiber
        start_root(delay_fiber, batch.wait_then_run(), now=origin.now)
        # A delay that ended at once has run (and removed) the batch.
        if completed or batches.get(slot) is not batch:
            return entry
    else:
        batch.pending[entry] = None
        batch.entries[entry] = None
    if resolver.collect_while(batch.entries.keys()):
        return entry
    assert batch.fiber is not None
    batch.fiber.interrupt_as_unsafe(origin.fiber_id)
    first = batch.origin
    start_root(new_root(first.run_scheduler, first.context), batch.take(), now=origin.now)
    return entry


def remove_entry(resolver: RequestResolver[Any, Any], entry: Entry[Any], origin: Origin) -> None:
    """The caller of ``entry`` (made from ``origin``) left: take the entry
    out of its batch and interrupt the batch's wait if no entry is left."""
    if entry.uninterruptible:
        return
    slot = origin.slot(_slot_key(resolver, resolver.batch_key(entry)))
    batch = resolver._batches.get(slot)
    if batch is None or entry not in batch.entries:
        return
    del batch.entries[entry]
    batch.pending.pop(entry, None)
    abandoned = None
    if not batch.entries:
        del resolver._batches[slot]
        abandoned = batch.fiber
    # The wait's finalizers may make requests, so complete the entry first.
    entry._complete(exit_interrupt())
    if abandoned is not None:
        abandoned.interrupt_as_unsafe(None)


def request_with(req: object, resolver: RequestResolver[Any, Any]) -> Effect[Any, Any, Any]:
    """Make ``req`` from the running fiber and wait for its exit."""

    def body(fiber: Fiber[Any, Any]) -> Effect[Any, Any, Any]:
        origin = Origin(fiber._context, fiber._run_scheduler, fiber.id)

        def register(resume: Callable[[Effect[Any, Any, Any]], None]) -> Effect[None]:
            entry = add_entry(resolver, req, lambda ex: resume(_FromExit(ex)), origin)
            return _Sync(lambda: remove_entry(resolver, entry, origin))

        return _Callback(register)

    return _WithFiber(body)
