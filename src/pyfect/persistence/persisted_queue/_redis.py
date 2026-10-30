"""``layer_store_redis``: queues in Redis lists, hashes and sorted sets,
claimed under per-element locks by Lua scripts."""

from __future__ import annotations

import re
import uuid
from collections.abc import Callable, Generator
from dataclasses import dataclass
from typing import Any, Final, Never, cast

from pyfect._concurrency import for_each
from pyfect._core import Effect
from pyfect._js import js_number
from pyfect._json_text import parse, stringify
from pyfect.cause import Cause
from pyfect.clock import ClockService, clock_with, sleep
from pyfect.duration import Duration, Seconds, to_millis
from pyfect.effect import gen, suspend, sync
from pyfect.exit import Exit, Success
from pyfect.layer import Layer
from pyfect.layer import effect as layer_effect
from pyfect.persistence.persisted_queue import _redis_scripts as scripts
from pyfect.persistence.persisted_queue._error import PersistedQueueError, dead_letter_from_cause
from pyfect.persistence.persisted_queue._mailbox import Mailbox, run_poller, take_from
from pyfect.persistence.persisted_queue._store import (
    PersistedQueueStore,
    PersistedQueueStoreService,
    QueueStates,
    TakenElement,
    TakeOptions,
    ack_retry_schedule,
    store_interval,
)
from pyfect.persistence.persistence._service import now_millis
from pyfect.persistence.redis import Redis, RedisError, RedisReply, RedisService
from pyfect.rc_map import RcMap
from pyfect.schedule import Schedule
from pyfect.scope import Scope, add_finalizer

_LONE_SURROGATE = re.compile("[\ud800-\udfff]")
_DEFAULT_POLL_INTERVAL: Final = Seconds(1)
_DEFAULT_LOCK_REFRESH_INTERVAL: Final = Seconds(30)
_DEFAULT_LOCK_EXPIRATION: Final = Seconds(90)


@dataclass(frozen=True, slots=True)
class _Element:
    id: str
    element: object
    attempts: int
    payload: str
    """The record as stored, so a requeue or retry does not re-encode it."""


@dataclass(frozen=True, slots=True)
class _Keys:
    queue: str
    pending: str
    failed: str
    delayed: str
    attempts: str
    ids: str
    lock_prefix: str

    def lock(self, id: str) -> str:
        """The claim lock of element ``id`` of this queue. Ids are unique per
        queue only, so the lock is too: the queue name, length-prefixed so
        no other queue's name and id spell the same key."""
        return f"{self.lock_prefix}{id}:lock"


def _offer_failed(error: RedisError) -> PersistedQueueError:
    return PersistedQueueError(
        message="Failed to offer element to persisted queue", cause=error.cause
    )


def _cleanup_failed(error: RedisError) -> PersistedQueueError:
    return PersistedQueueError(message="Failed to clean up persisted queue", cause=error.cause)


def _elements(results: list[RedisReply]) -> list[_Element]:
    elements: list[_Element] = []
    for i in range(0, len(results), 2):
        payload = cast("str", results[i])
        parsed = cast("dict[str, Any]", parse(payload))
        attempts = int(cast("str | int", results[i + 1]))
        elements.append(_Element(parsed["id"], parsed.get("element"), attempts, payload))
    return elements


@dataclass(frozen=True, slots=True)
class _Settings:
    prefix: str
    poll_interval: Seconds
    lock_refresh: Seconds
    lock_expiration_millis: float
    ack_schedule: Schedule[object, object]
    worker_id: str

    def keys(self, name: str) -> _Keys:
        base = f"{self.prefix}{name}"
        return _Keys(
            base,
            f"{base}:pending",
            f"{base}:failed",
            f"{base}:delayed",
            f"{base}:attempts",
            f"{base}:ids",
            f"{self.prefix}{len(name)}:{name}:",
        )


class _Scripts:
    """The store's scripts, run on one client."""

    __slots__ = (
        "complete",
        "expire_all",
        "failed",
        "offer",
        "offer_delayed",
        "requeue",
        "reset_queue",
        "retry",
        "take",
        "trim_failed",
    )

    def __init__(self, redis: RedisService) -> None:
        self.requeue = redis.eval(scripts.REQUEUE)
        self.complete = redis.eval(scripts.COMPLETE)
        self.failed = redis.eval(scripts.FAILED)
        self.retry = redis.eval(scripts.RETRY)
        self.reset_queue = redis.eval(scripts.RESET_QUEUE)
        self.offer = redis.eval(scripts.OFFER)
        self.offer_delayed = redis.eval(scripts.OFFER_DELAYED)
        self.take = redis.eval(scripts.TAKE)
        self.expire_all = redis.eval(scripts.EXPIRE_ALL)
        self.trim_failed = redis.eval(scripts.TRIM_FAILED)


def _lookup(
    settings: _Settings, run: _Scripts, states: QueueStates, clock: ClockService
) -> Callable[[str], Effect[Mailbox[_Element], Never, Scope]]:
    """The mailbox of queue ``name``: its poller, and a fiber that resets
    elements whose lock lapsed every lock refresh interval. Closing it puts
    the elements it holds back in the queue."""

    def lookup(name: str) -> Effect[Mailbox[_Element], Never, Scope]:
        keys = settings.keys(name)
        mailbox = Mailbox[_Element]()
        state = states.get(name)

        def release(elements: list[_Element]) -> Effect[object]:
            return for_each(
                elements,
                lambda e: run.requeue(
                    keys.queue,
                    keys.pending,
                    keys.lock(e.id),
                    keys.attempts,
                    e.id,
                    e.payload,
                ),
                concurrency="unbounded",
            ).or_die()

        reset = suspend(
            lambda: run.reset_queue(
                keys.queue,
                keys.pending,
                keys.attempts,
                keys.failed,
                keys.ids,
                keys.lock_prefix,
                state.max_attempts,
                now_millis(clock),
            )
        )

        def poll(size: int) -> Effect[list[_Element], RedisError]:
            return suspend(
                lambda: run.take(
                    keys.queue,
                    keys.pending,
                    keys.delayed,
                    keys.attempts,
                    keys.lock_prefix,
                    settings.worker_id,
                    size,
                    settings.lock_expiration_millis,
                    now_millis(clock),
                )
            ).map(lambda results: [] if results is None else _elements(results))

        return (
            add_finalizer(lambda _: mailbox.queue.clear().flat_map(release))
            .and_then(reset.and_then(sleep(settings.lock_refresh)).forever().fork_scoped())
            .and_then(
                run_poller(
                    mailbox, poll=poll, nudge=state.nudge, poll_interval=settings.poll_interval
                )
            )
            .as_(mailbox)
        )

    return lookup


class _RedisStore:
    __slots__ = ("_active_locks", "_clock", "_mailboxes", "_redis", "_run", "_settings", "_states")

    def __init__(  # noqa: PLR0917
        self,
        settings: _Settings,
        redis: RedisService,
        run: _Scripts,
        states: QueueStates,
        clock: ClockService,
        mailboxes: RcMap[str, Mailbox[_Element], Never],
        active_locks: dict[str, None],
    ) -> None:
        self._settings = settings
        self._redis = redis
        self._run = run
        self._states = states
        self._clock = clock
        self._mailboxes = mailboxes
        self._active_locks = active_locks

    def offer(
        self,
        *,
        name: str,
        id: str,
        element: object,
        is_custom_id: bool,
        delay: Seconds | None = None,
    ) -> Effect[None, PersistedQueueError]:
        keys = self._settings.keys(name)
        # replace lone surrogates as UTF-8 encoding does, so the id in the
        # payload matches the id keys
        id = _LONE_SURROGATE.sub("\ufffd", id)
        payload = stringify({"id": id, "element": element})

        def send() -> Effect[object, RedisError]:
            if delay is None:
                if is_custom_id:
                    return self._run.offer(keys.queue, keys.ids, id, payload)
                return self._redis.send("RPUSH", keys.queue, payload)
            visible_at = now_millis(self._clock) + to_millis(delay)
            if is_custom_id:
                return self._run.offer_delayed(keys.delayed, keys.ids, id, payload, visible_at)
            return self._redis.send("ZADD", keys.delayed, js_number(visible_at), payload)

        def nudge() -> None:
            state = self._states.peek(name)
            if state is not None:
                state.nudge.open_unsafe()

        return suspend(send).map_error(_offer_failed).flat_map(lambda _: sync(nudge))

    def take(self, options: TakeOptions) -> Effect[TakenElement, PersistedQueueError, Scope]:
        def claimed(element: _Element) -> Effect[TakenElement, Never, Scope]:
            lock = self._settings.keys(options.name).lock(element.id)
            self._active_locks[lock] = None
            return add_finalizer(lambda exit_: self._settle(options, element, exit_)).as_(
                TakenElement(element.id, element.attempts, element.element)
            )

        def body() -> Effect[TakenElement, Never, Scope]:
            self._states.get(options.name).max_attempts = options.max_attempts
            return take_from(self._mailboxes, options.name, claimed)

        return suspend(body)

    def _settle(
        self, options: TakeOptions, element: _Element, exit_: Exit[Any, Any]
    ) -> Effect[None]:
        keys = self._settings.keys(options.name)
        lock = keys.lock(element.id)
        now = now_millis(self._clock)
        run = self._run

        def ack(effect: Effect[object, RedisError]) -> Effect[None]:
            return (
                effect.retry(self._settings.ack_schedule)
                .or_die()
                .ensuring(sync(lambda: self._active_locks.pop(lock, None)))
                .as_void()
            )

        def fail_element(cause: Cause[Any]) -> Effect[None]:
            record = stringify(
                {
                    "id": element.id,
                    "element": element.element,
                    "attempts": element.attempts,
                    "lastFailure": cause.pretty(),
                    "failedAt": now,
                }
            )
            return ack(
                run.failed(
                    keys.pending, lock, keys.failed, keys.attempts, keys.ids, element.id, record
                )
            )

        if isinstance(exit_, Success):
            return ack(run.complete(keys.pending, lock, keys.attempts, keys.ids, element.id, now))
        dead = dead_letter_from_cause(exit_.cause)
        if dead is not None:
            return fail_element(dead.cause)
        if exit_.cause.has_interrupts_only:
            return ack(
                run.requeue(
                    keys.queue, keys.pending, lock, keys.attempts, element.id, element.payload
                )
            )
        if element.attempts >= options.max_attempts:
            return fail_element(exit_.cause)
        return options.retry_delay(element.attempts).flat_map(
            lambda delay: ack(
                run.retry(
                    keys.pending,
                    lock,
                    keys.delayed,
                    element.id,
                    element.payload,
                    now + to_millis(delay),
                )
            )
        )

    def _scan_keys(self, pattern: str) -> Effect[list[str], RedisError]:
        def body() -> Generator[Any, Any, list[str]]:
            found: list[str] = []
            cursor = "0"
            while True:
                reply = yield from self._redis.send(
                    "SCAN", cursor, "MATCH", pattern, "COUNT", "100"
                )
                next_cursor, batch = cast("list[Any]", reply)
                cursor = str(next_cursor)
                found.extend(cast("list[str]", batch))
                if cursor == "0":
                    return found

        return gen(body)

    def _trim_failed(self, key: str, cutoff: float) -> Effect[int, RedisError]:
        ids_key = key.removesuffix(":failed") + ":ids"
        # each call trims at most one batch, so drain until done
        return self._run.trim_failed(key, ids_key, cutoff).repeat(
            while_=lambda removed: removed >= scripts.TRIM_FAILED_BATCH_SIZE
        )

    def cleanup(
        self, *, time_to_live: Seconds, failed_time_to_live: Seconds | None
    ) -> Effect[None, PersistedQueueError]:
        prefix = self._settings.prefix

        def body() -> Generator[Any, Any]:
            now = now_millis(self._clock)
            ids_keys = yield from self._scan_keys(f"{prefix}*:ids")
            cutoff = f"({js_number(now - to_millis(time_to_live))}"
            yield from for_each(
                ids_keys,
                lambda key: self._redis.send("ZREMRANGEBYSCORE", key, "-inf", cutoff),
                concurrency=16,
            )
            if failed_time_to_live is not None:
                failed_cutoff = now - to_millis(failed_time_to_live)
                failed_keys = yield from self._scan_keys(f"{prefix}*:failed")
                yield from for_each(
                    failed_keys, lambda key: self._trim_failed(key, failed_cutoff), concurrency=16
                )

        return gen(body).map_error(_cleanup_failed)


def make_store_redis(
    *,
    prefix: str = "effectq:",
    poll_interval: Duration = _DEFAULT_POLL_INTERVAL,
    lock_refresh_interval: Duration = _DEFAULT_LOCK_REFRESH_INTERVAL,
    lock_expiration: Duration = _DEFAULT_LOCK_EXPIRATION,
) -> Effect[PersistedQueueStoreService, Never, Redis | Scope]:
    """A store on Redis. Each queue ``name`` keeps its elements under
    ``<prefix><name>`` (a list, with ``:pending``, ``:attempts``, ``:ids``,
    ``:delayed`` and ``:failed`` beside it). A claimed element is locked
    for ``lock_expiration``, renewed every ``lock_refresh_interval`` while
    it is processed; an element whose lock lapsed (its worker died) goes
    back to the queue, or to ``:failed`` if that was its last attempt.
    Retried and delayed elements wait in ``:delayed``, scored by the
    offering process's clock and released by the polling one's, so clock
    skew between hosts shifts them."""
    lock_expiration_seconds = store_interval(lock_expiration, _DEFAULT_LOCK_EXPIRATION)
    settings = _Settings(
        prefix=prefix,
        poll_interval=store_interval(poll_interval, _DEFAULT_POLL_INTERVAL),
        lock_refresh=store_interval(lock_refresh_interval, _DEFAULT_LOCK_REFRESH_INTERVAL),
        lock_expiration_millis=to_millis(lock_expiration_seconds),
        ack_schedule=ack_retry_schedule(lock_expiration_seconds),
        worker_id=str(uuid.uuid4()),
    )

    def build(redis: RedisService, clock: ClockService) -> Generator[Any, Any, Any]:
        run = _Scripts(redis)
        states = QueueStates()
        active_locks: dict[str, None] = {}
        mailboxes = yield from RcMap.make(
            _lookup(settings, run, states, clock), idle_time_to_live=30.0
        )

        def refresh_locks() -> Generator[Any, Any]:
            while True:
                yield from sleep(settings.lock_refresh)
                yield from run.expire_all(
                    list(active_locks), settings.lock_expiration_millis
                ).ignore()

        yield from (
            gen(refresh_locks)
            .annotate_logs({"module": "effect/persistence/PersistedQueue", "fiber": "refreshLocks"})
            .interruptible()
            .fork_scoped()
        )
        store = _RedisStore(settings, redis, run, states, clock, mailboxes, active_locks)
        return PersistedQueueStoreService(offer=store.offer, take=store.take, cleanup=store.cleanup)

    return Redis().flat_map(
        lambda redis: clock_with(lambda clock: gen(lambda: build(redis, clock)))
    )


def layer_store_redis(
    *,
    prefix: str = "effectq:",
    poll_interval: Duration = _DEFAULT_POLL_INTERVAL,
    lock_refresh_interval: Duration = _DEFAULT_LOCK_REFRESH_INTERVAL,
    lock_expiration: Duration = _DEFAULT_LOCK_EXPIRATION,
) -> Layer[PersistedQueueStore, Never, Redis]:
    """The store of ``make_store_redis``."""
    return layer_effect(
        PersistedQueueStore,
        make_store_redis(
            prefix=prefix,
            poll_interval=poll_interval,
            lock_refresh_interval=lock_refresh_interval,
            lock_expiration=lock_expiration,
        ),
    )
