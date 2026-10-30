"""``layer_store_memory``: queues in process memory."""

from __future__ import annotations

import math
from collections.abc import Generator
from dataclasses import dataclass, field
from typing import Any, Literal, Never

from pyfect._core import Effect
from pyfect.clock import ClockService, clock_with, sleep
from pyfect.duration import Seconds, to_millis
from pyfect.effect import gen, succeed, sync, void
from pyfect.exit import Exit, Success
from pyfect.latch import Latch
from pyfect.layer import Layer
from pyfect.layer import effect as layer_effect
from pyfect.persistence._seconds import millis
from pyfect.persistence.persisted_queue._error import PersistedQueueError, dead_letter_from_cause
from pyfect.persistence.persisted_queue._store import (
    PersistedQueueStore,
    PersistedQueueStoreService,
    TakenElement,
    TakeOptions,
)
from pyfect.persistence.persistence._service import now_millis
from pyfect.scope import Scope, add_finalizer

type _State = Literal["pending", "processing", "completed", "failed"]


@dataclass(eq=False, slots=True)
class _Entry:
    id: str
    element: object
    attempts: int
    state: _State
    visible_at: float
    state_changed_at: float


@dataclass(slots=True)
class _Queue:
    latch: Latch = field(default_factory=Latch)
    entries: dict[str, _Entry] = field(default_factory=dict[str, _Entry])
    """Every entry offered, for de-duplication."""
    pending: dict[_Entry, None] = field(default_factory=dict[_Entry, None])
    """The deliverable entries, in offer order, so a take does not scan the
    completed backlog."""


class _MemoryStore:
    __slots__ = ("_clock", "_queues")

    def __init__(self, clock: ClockService) -> None:
        self._clock = clock
        self._queues: dict[str, _Queue] = {}

    def _queue(self, name: str) -> _Queue:
        queue = self._queues.get(name)
        if queue is None:
            queue = self._queues[name] = _Queue()
        return queue

    def offer(
        self,
        *,
        name: str,
        id: str,
        element: object,
        is_custom_id: bool,
        delay: Seconds | None = None,
    ) -> Effect[None, PersistedQueueError]:
        def run() -> None:
            now = now_millis(self._clock)
            queue = self._queue(name)
            if id in queue.entries:
                return
            visible_at = now if delay is None else now + to_millis(delay)
            entry = _Entry(id, element, 0, "pending", visible_at, now)
            queue.entries[id] = entry
            queue.pending[entry] = None
            queue.latch.open_unsafe()

        return sync(run)

    def _settle(
        self, queue: _Queue, entry: _Entry, options: TakeOptions, exit_: Exit[Any, Any]
    ) -> Effect[None]:
        now = now_millis(self._clock)

        def finish(state: _State) -> Effect[None]:
            entry.state = state
            entry.state_changed_at = now
            return void

        def requeue() -> None:
            entry.state = "pending"
            queue.pending[entry] = None
            queue.latch.open_unsafe()

        def retry_after(delay: Seconds) -> None:
            entry.visible_at = now + to_millis(delay)
            requeue()

        if isinstance(exit_, Success):
            return finish("completed")
        if dead_letter_from_cause(exit_.cause) is not None:
            return finish("failed")
        if exit_.cause.has_interrupts_only:
            entry.attempts -= 1
            return sync(requeue)
        if entry.attempts >= options.max_attempts:
            return finish("failed")
        return options.retry_delay(entry.attempts).map(retry_after)

    def _claim(
        self, queue: _Queue, entry: _Entry, options: TakeOptions
    ) -> Effect[TakenElement, Never, Scope]:
        entry.state = "processing"
        entry.attempts += 1
        del queue.pending[entry]
        queue.latch.open_unsafe()
        return add_finalizer(lambda exit_: self._settle(queue, entry, options, exit_)).as_(
            TakenElement(entry.id, entry.attempts, entry.element)
        )

    def take(self, options: TakeOptions) -> Effect[TakenElement, PersistedQueueError, Scope]:
        def body() -> Generator[Any, Any, TakenElement]:
            queue = self._queue(options.name)
            while True:
                # close before scanning, so a change after the scan reopens it
                queue.latch.close_unsafe()
                now = now_millis(self._clock)
                next_visible_at = math.inf
                item: _Entry | None = None
                for entry in queue.pending:
                    if entry.attempts >= options.max_attempts:
                        continue
                    if entry.visible_at <= now:
                        item = entry
                        break
                    next_visible_at = min(next_visible_at, entry.visible_at)
                if item is not None:
                    return (yield from self._claim(queue, item, options))
                if math.isinf(next_visible_at):
                    yield from queue.latch.wait()
                else:
                    yield from queue.latch.wait().race(sleep(millis(next_visible_at - now)))

        return gen(body)

    def cleanup(
        self, *, time_to_live: Seconds, failed_time_to_live: Seconds | None
    ) -> Effect[None, PersistedQueueError]:
        def run() -> None:
            now = now_millis(self._clock)
            cutoffs: dict[_State, float] = {"completed": now - to_millis(time_to_live)}
            if failed_time_to_live is not None:
                cutoffs["failed"] = now - to_millis(failed_time_to_live)
            for queue in self._queues.values():
                for id, entry in list(queue.entries.items()):
                    cutoff = cutoffs.get(entry.state)
                    if cutoff is not None and entry.state_changed_at <= cutoff:
                        del queue.entries[id]

        return sync(run)


def make_store_memory(clock: ClockService) -> PersistedQueueStoreService:
    """A store whose queues live in dicts, timed by ``clock``. Delayed
    entries are scanned on every take, so it is for development and tests
    rather than large delayed backlogs."""
    store = _MemoryStore(clock)
    return PersistedQueueStoreService(offer=store.offer, take=store.take, cleanup=store.cleanup)


layer_store_memory: Layer[PersistedQueueStore] = layer_effect(
    PersistedQueueStore, clock_with(lambda clock: succeed(make_store_memory(clock)))
)
"""Queues in process memory, fresh each time the layer is built: failed
takes are retried on the queue's schedule until its attempts run out."""
