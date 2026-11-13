"""``PersistedQueue``: the queue over a ``PersistedQueueStore``, its factory
service and the cleanup layer."""

from __future__ import annotations

import uuid
from collections.abc import Callable, Generator
from dataclasses import dataclass
from typing import Any, Never, cast

from pyfect._core import Effect
from pyfect.cause import Cause
from pyfect.context import Tag
from pyfect.duration import Duration, from_input_unsafe, to_millis, zero
from pyfect.duration import Input as DurationInput
from pyfect.effect import fail, fail_cause, gen, provide_service, succeed, suspend
from pyfect.layer import Layer, effect_discard
from pyfect.layer import effect as layer_effect
from pyfect.logger import log_warning
from pyfect.persistence.persisted_queue._error import (
    DeadLetter,
    PersistedQueueError,
    is_dead_letter,
)
from pyfect.persistence.persisted_queue._store import (
    PersistedQueueStore,
    PersistedQueueStoreService,
    TakeOptions,
    is_infinite,
    positive_delay,
)
from pyfect.schedule import Schedule, Stop, exponential, min, spaced, to_step
from pyfect.schema import (
    Codec,
    SchemaError,
    decode_unknown_effect,
    encode_unknown_effect,
    to_codec_json,
)
from pyfect.scope import CloseableScope, Scope, scoped_with

type RetrySchedule = Schedule[object, int]
"""A queue's retry schedule: its input is the attempt number, its delay
how long a failed element waits before it is visible again."""

DEFAULT_RETRY_SCHEDULE: RetrySchedule = min(exponential("1 second"), spaced("300 seconds"))
"""Exponential from 1 second, capped at 5 minutes."""

DEFAULT_MAX_ATTEMPTS = 10


@dataclass(frozen=True, slots=True)
class Metadata:
    """What a ``take`` handler learns of its element: ``attempts`` counts
    this delivery, from 1."""

    id: str
    attempts: int


def retry_delay(schedule: RetrySchedule, attempts: int) -> Effect[Duration]:
    """The delay after failed attempt ``attempts``: a fresh run of
    ``schedule`` replayed up to it, with time simulated from the summed
    delays, so delays keep growing when retries run in different
    processes. A schedule that stops keeps its last delay."""

    def body() -> Generator[Any, Any, Duration]:
        step = yield from to_step(schedule)
        now = 0.0
        delay = zero
        for attempt in range(1, attempts + 1):
            decision = yield from step(now, attempt)
            if isinstance(decision, Stop):
                break
            delay = decision.delay
            now += to_millis(delay)
        return delay

    return gen(body)


class PersistedQueue[A, R = Never]:
    """A durable queue of ``A`` values, stored as their schema's JSON.

    Delivery is at-least-once: a crash between a handler's success and its
    acknowledgement delivers the element again, so handlers must be
    idempotent. Make one with ``make``."""

    __slots__ = ("_decode", "_encode", "_name", "_store", "_take_options")

    def __init__(
        self,
        store: PersistedQueueStoreService,
        *,
        name: str,
        schema: Codec[A, Any, Any, Any],
        max_attempts: int,
        retry_schedule: RetrySchedule,
    ) -> None:
        json_schema = to_codec_json(schema)
        self._encode = encode_unknown_effect(
            cast("Codec[object, object, object, Any]", json_schema)
        )
        self._decode = decode_unknown_effect(cast("Codec[A, object, Any, object]", json_schema))
        self._store = store
        self._name = name
        self._take_options = TakeOptions(
            name=name,
            max_attempts=max_attempts,
            retry_delay=lambda attempts: retry_delay(retry_schedule, attempts),
        )

    def offer(
        self, value: A, *, id: str | None = None, delay: DurationInput | None = None
    ) -> Effect[str, PersistedQueueError | SchemaError, R]:
        """Add ``value`` and give its id: ``id``, or a new UUID. An id the
        queue already has (even completed, until ``layer_cleanup`` removes
        it) adds nothing, and that offer's ``delay`` is ignored.

        ``delay`` postpones the first delivery, measured by the store's
        clock (SQL: the database's, rounded up to whole seconds); zero or
        negative is none. An infinite delay stores nothing: the id is
        given back, and may be offered again."""

        def body() -> Effect[str, PersistedQueueError | SchemaError, R]:
            element_id = id if id is not None else str(uuid.uuid4())
            seconds = positive_delay(delay)
            if is_infinite(seconds):
                return succeed(element_id)
            return self._encode(value).flat_map(
                lambda element: self._store.offer(
                    name=self._name,
                    id=element_id,
                    element=element,
                    is_custom_id=id is not None,
                    delay=seconds,
                ).as_(element_id)
            )

        return suspend(body)

    def take[XA, XE = Never, XR = Never](
        self, f: Callable[[A, Metadata], Effect[XA, XE, XR]]
    ) -> Effect[XA, XE | PersistedQueueError, R | XR]:
        """Run ``f`` on the next element, waiting while there is none. If
        ``f`` succeeds the element is done; if it fails it is retried on
        the queue's retry schedule, and marked failed once its attempts run
        out; if it is interrupted it is released for another take, without
        counting the attempt. An element its schema cannot decode is marked
        failed and the next one taken."""

        def decode_failed(cause: Cause[SchemaError]) -> Effect[Never, Any]:
            if cause.has_interrupts_only:
                return fail_cause(cause)
            return fail(DeadLetter(cause))

        def attempt(scope: CloseableScope) -> Effect[XA, Any, Any]:
            return (
                self._store.take(self._take_options)
                .pipe(provide_service(Scope, scope))
                .flat_map(
                    lambda item: (
                        self._decode(item.element)
                        .catch_cause(decode_failed)
                        .flat_map(lambda value: f(value, Metadata(item.id, item.attempts)))
                    )
                )
            )

        return suspend(lambda: _take_loop(attempt))


def _take_loop[XA](
    attempt: Callable[[CloseableScope], Effect[XA, Any, Any]],
) -> Effect[XA, Any, Any]:
    """Take until an element decodes; module-level, as a closure calling
    itself would keep ``f`` alive after the take."""
    return scoped_with(attempt).catch_if(
        is_dead_letter, lambda _: suspend(lambda: _take_loop(attempt))
    )


class PersistedQueueFactoryService:
    """Makes queues over one ``PersistedQueueStore``."""

    __slots__ = ("_store",)

    def __init__(self, store: PersistedQueueStoreService) -> None:
        self._store = store

    def make[A, RR = Never](
        self,
        *,
        name: str,
        schema: Codec[A, Any, RR, RR],
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
        retry_schedule: RetrySchedule = DEFAULT_RETRY_SCHEDULE,
    ) -> Effect[PersistedQueue[A, RR]]:
        """The queue ``name`` of ``schema``'s values. See ``make``."""
        return succeed(
            PersistedQueue[A, RR](
                self._store,
                name=name,
                schema=schema,
                max_attempts=max_attempts,
                retry_schedule=retry_schedule,
            )
        )


class PersistedQueueFactory(
    Tag[PersistedQueueFactoryService],
    key="effect/persistence/PersistedQueue/PersistedQueueFactory",
):
    """Makes named persisted queues."""


def make[A, RR = Never](
    *,
    name: str,
    schema: Codec[A, Any, RR, RR],
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    retry_schedule: RetrySchedule = DEFAULT_RETRY_SCHEDULE,
) -> Effect[PersistedQueue[A, RR], Never, PersistedQueueFactory]:
    """The queue ``name`` of ``schema``'s values, from the factory.

    An element failing ``max_attempts`` times is marked failed. After each
    failure it waits the ``retry_schedule``'s delay for its attempt: the
    schedule is replayed up to the element's stored attempt count (with
    time simulated from the summed delays, so ``up_to(duration=)`` caps
    the summed delays, not real time)."""
    return PersistedQueueFactory().flat_map(
        lambda factory: factory.make(
            name=name, schema=schema, max_attempts=max_attempts, retry_schedule=retry_schedule
        )
    )


make_factory: Effect[PersistedQueueFactoryService, Never, PersistedQueueStore] = (
    PersistedQueueStore().map(PersistedQueueFactoryService)
)
"""A factory over the current store."""

layer: Layer[PersistedQueueFactory, Never, PersistedQueueStore] = layer_effect(
    PersistedQueueFactory, make_factory
)
"""The factory over the current store."""


def layer_cleanup(
    *,
    interval: DurationInput = "1 hour",
    time_to_live: DurationInput = "30 days",
    failed_time_to_live: DurationInput | None = None,
) -> Layer[Never, Never, PersistedQueueStore]:
    """Run the store's ``cleanup`` every ``interval`` (default an hour),
    logging a failure. Completed elements are kept ``time_to_live``
    (default 30 days) so their ids stay de-duplicated; failed ones are the
    dead letters, kept unless ``failed_time_to_live`` is given.

    Run it in one instance of a deployment: racing ones are harmless but
    redundant."""
    ttl = from_input_unsafe(time_to_live)
    failed_ttl = None if failed_time_to_live is None else from_input_unsafe(failed_time_to_live)
    every = from_input_unsafe(interval)

    def start(store: PersistedQueueStoreService) -> Effect[object, Never, Scope]:
        return (
            store.cleanup(time_to_live=ttl, failed_time_to_live=failed_ttl)
            .catch_cause(lambda cause: log_warning("Failed to clean up persisted queue", cause))
            .repeat(spaced(every))
            .annotate_logs({"module": "effect/persistence/PersistedQueue", "fiber": "cleanup"})
            .interruptible()
            .fork_scoped()
        )

    return effect_discard(PersistedQueueStore().flat_map(start))
