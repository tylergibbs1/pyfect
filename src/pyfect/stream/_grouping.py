"""The work behind ``Stream.group_by``, ``group_by_key`` and
``group_adjacent_by``.

``group_by`` and ``group_by_key`` run the upstream on a fiber in the
stream's scope. Each new key gets a queue of ``buffer_size`` (an ``RcMap``
entry, ended when the entry is released) and the outer stream writes
``(key, group)`` once, where ``group`` reads that queue and shuts it down
when it stops, so a group that stops early never blocks the others.
"""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from collections.abc import Callable, Generator, Hashable, Sequence
from functools import partial
from typing import Any

from pyfect import channel
from pyfect._core import (
    Effect,
    _FailCause,
    _FlatMap,
    _Gen,
    _MatchCause,
    _Succeed,
    _Suspend,
    _Sync,
    _WithFiber,
)
from pyfect._fiber import Fiber
from pyfect.cause import Cause
from pyfect.channel._base import end_with
from pyfect.duration import Input as DurationInput
from pyfect.duration import from_input_unsafe, infinity
from pyfect.effect import provide_service
from pyfect.errors import Done
from pyfect.queue import Queue
from pyfect.rc_map import RcMap
from pyfect.scope import CloseableScope, Scope, acquire_release, fork_in, scoped
from pyfect.stream._base import AnyStream
from pyfect.stream._stream import Stream, transform_pull, transform_pull_bracket

type AnyEffect = Effect[Any, Any, Any]
type Chunk = tuple[Any, ...]
type AnyStream_ = Stream[Any, Any, Any]
type Groups = RcMap[Any, Queue[Any, Done], Any]
type OfferChunk = Callable[[Chunk, Groups, dict[Any, Queue[Any, Done]]], AnyEffect]

_ENDED: AnyEffect = end_with(None)
_VOID: AnyEffect = _Succeed(None)


def from_queue_shutdown_on_end(queue: Queue[Any, Any]) -> AnyStream_:
    """A stream taking everything waiting in ``queue`` at each pull; it
    shuts the queue down when it stops."""

    def transform(_upstream: object, scope: CloseableScope) -> AnyEffect:
        take = queue.take_all().map(tuple)
        return scope.add_finalizer(lambda _: queue.shutdown()).as_(take)

    built: channel.Channel[Any, Any, Any, Any, Any, Any, Any] = channel.from_transform(transform)
    return Stream(built)


def _offer_groups(
    batch: Sequence[tuple[Any, list[Any]]],
    groups: Groups,
    open_queues: dict[Any, Queue[Any, Done]],
    start: int = 0,
) -> AnyEffect:
    """Effect's per-key ``RcMap.get`` (for a new key), ``RcMap.touch`` and
    ``Queue.offerAll``, from ``batch[start]`` on. A key whose group is open
    and has room for its values is served within this one step; the first
    that needs a new group or has to wait goes on as effects."""

    def offer(fiber: Fiber[Any, Any]) -> AnyEffect:
        for index in range(start, len(batch)):
            key, values = batch[index]
            queue = open_queues.get(key)
            if queue is None:
                return _Gen(partial(_offer_new_group, batch, groups, open_queues, index))
            groups.touch_unsafe(key, fiber)
            rest = queue.offer_all_unsafe(values)
            if rest:
                then = _offer_groups(batch, groups, open_queues, index + 1)
                return queue.offer_all(rest).and_then(then)
        return _VOID

    return _WithFiber(offer)


def _offer_new_group(
    batch: Sequence[tuple[Any, list[Any]]],
    groups: Groups,
    open_queues: dict[Any, Queue[Any, Done]],
    index: int,
) -> Generator[AnyEffect, Any]:
    key, values = batch[index]
    queue = yield scoped(groups.get(key))
    yield groups.touch(key)
    yield queue.offer_all(values)
    yield _offer_groups(batch, groups, open_queues, index + 1)


def _group_by(
    self: AnyStream,
    offer_chunk: OfferChunk,
    buffer_size: int,
    idle_time_to_live: DurationInput | None,
) -> AnyStream_:
    ttl = infinity if idle_time_to_live is None else from_input_unsafe(idle_time_to_live)

    def build(pull: AnyEffect, scope: CloseableScope, forked: CloseableScope) -> AnyEffect:
        def body() -> Generator[AnyEffect, Any, AnyEffect]:
            out: Queue[Any, Any] = Queue(None)
            yield scope.add_finalizer(lambda _: out.shutdown())
            open_queues: dict[Any, Queue[Any, Done]] = {}

            def lookup(key: Any) -> AnyEffect:
                def opened(queue: Queue[Any, Done]) -> AnyEffect:
                    open_queues[key] = queue
                    return out.offer((key, from_queue_shutdown_on_end(queue)))

                def release(queue: Queue[Any, Done], _: object) -> AnyEffect:
                    open_queues.pop(key, None)
                    return queue.end()

                made: Effect[Queue[Any, Done]] = _Sync(lambda: Queue(buffer_size))
                return acquire_release(made.tap(opened), release)

            make_groups = RcMap.make(lookup, idle_time_to_live=ttl)
            groups: Groups = yield make_groups.pipe(provide_service(Scope, forked))
            run = _FlatMap(pull, lambda chunk: offer_chunk(chunk, groups, open_queues)).forever(
                disable_yield=True
            )

            def stop(cause: Cause[Any]) -> AnyEffect:
                # Effect 4.1.2: the groups end too, so a reader of one never waits forever.
                for queue in list(open_queues.values()):
                    queue.end_unsafe()
                return out.fail_cause(cause)

            yield fork_in(run.catch_cause(stop), scope)
            return out.take_all().map(tuple)

        return _Gen(body)

    return transform_pull_bracket(self, build)


def group_by(
    self: AnyStream,
    f: Callable[[Any], Effect[tuple[Hashable, Any], Any, Any]],
    buffer_size: int,
    idle_time_to_live: DurationInput | None,
) -> AnyStream_:
    def offer_chunk(
        chunk: Chunk, groups: Groups, open_queues: dict[Any, Queue[Any, Done]]
    ) -> AnyEffect:
        def body() -> Generator[AnyEffect, Any]:
            for item in chunk:
                key, value = yield f(item)
                yield _offer_groups(((key, [value]),), groups, open_queues)

        return _Gen(body)

    return _group_by(self, offer_chunk, buffer_size, idle_time_to_live)


def group_by_key(
    self: AnyStream,
    f: Callable[[Any], Hashable],
    buffer_size: int,
    idle_time_to_live: DurationInput | None,
) -> AnyStream_:
    def offer_chunk(
        chunk: Chunk, groups: Groups, open_queues: dict[Any, Queue[Any, Done]]
    ) -> AnyEffect:
        batch: dict[Any, list[Any]] = {}
        for item in chunk:
            batch.setdefault(f(item), []).append(item)
        return _offer_groups(list(batch.items()), groups, open_queues)

    return _group_by(self, offer_chunk, buffer_size, idle_time_to_live)


def group_adjacent_by(self: AnyStream, f: Callable[[Any], object]) -> AnyStream_:
    def build(pull: AnyEffect, _scope: CloseableScope) -> AnyEffect:
        grouping = _GroupAdjacent(pull, f)
        loop: AnyEffect = _FlatMap(pull, grouping)
        pulled = _Suspend(
            lambda: loop if grouping.stopped is None else _FailCause(grouping.stopped)
        )
        return _Succeed(_MatchCause(pulled, grouping.flush, None))

    return transform_pull(self, build)


class _GroupAdjacent:
    """One run of ``group_adjacent_by``, called with each chunk."""

    __slots__ = ("f", "group", "key", "pull", "stopped")

    def __init__(self, pull: AnyEffect, f: Callable[[Any], object]) -> None:
        self.pull = pull
        self.f = f
        self.key: object = None
        self.group: list[Any] = []
        self.stopped: Cause[Any] | None = None

    def __call__(self, chunk: Chunk) -> AnyEffect:
        f = self.f
        ready: list[tuple[object, Chunk]] = []
        for item in chunk:
            item_key = f(item)
            if self.group and item_key != self.key:
                ready.append((self.key, tuple(self.group)))
                self.group = []
            if not self.group:
                self.key = item_key
            self.group.append(item)
        return _Succeed(tuple(ready)) if ready else _FlatMap(self.pull, self)

    def flush(self, cause: Cause[Any]) -> AnyEffect:
        """The upstream's end or failure: emit the group held first, then stop with it."""
        self.stopped = cause
        last, self.group = self.group, []
        return _Succeed(((self.key, tuple(last)),)) if last else _FailCause(cause)
