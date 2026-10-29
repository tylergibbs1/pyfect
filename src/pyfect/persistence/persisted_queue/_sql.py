"""``layer_store_sql``: queues in one SQL table, rows claimed under a
lock per poll."""

from __future__ import annotations

import uuid
from collections.abc import Callable, Generator, Sequence
from typing import Any, Final, Never

from pyfect._concurrency import for_each
from pyfect._core import Effect
from pyfect._json_text import PARSE_ERRORS, parse, stringify
from pyfect.cause import Cause
from pyfect.cause import die as cause_die
from pyfect.duration import Duration, Seconds
from pyfect.effect import fail, gen, succeed, suspend, sync
from pyfect.exit import Exit, Success
from pyfect.layer import Layer
from pyfect.layer import effect as layer_effect
from pyfect.logger import log_warning
from pyfect.persistence._columns import column_int
from pyfect.persistence.persisted_queue._error import PersistedQueueError, dead_letter_from_cause
from pyfect.persistence.persisted_queue._mailbox import Mailbox, run_poller, take_from
from pyfect.persistence.persisted_queue._sql_migrations import migrations
from pyfect.persistence.persisted_queue._sql_statements import (
    CleanupBatch,
    Dialect,
    Element,
    OfferStatement,
    Settlements,
    cleanup_statement,
    offer_statement,
    poll_statement,
    store_text,
)
from pyfect.persistence.persisted_queue._store import (
    PersistedQueueStore,
    PersistedQueueStoreService,
    QueueStates,
    TakenElement,
    TakeOptions,
    ack_retry_schedule,
    store_interval,
)
from pyfect.persistence.persistence._sql import SQL_CLEANUP_BATCH_SIZE
from pyfect.rc_map import RcMap
from pyfect.schedule import fixed, spaced
from pyfect.scope import Scope, add_finalizer
from pyfect.sql import migrator
from pyfect.sql.client import SqlClient
from pyfect.sql.connection import Row
from pyfect.sql.error import SqlError
from pyfect.sql.statement import Fragment

_CLEANUP_BATCH_DELAY: Final = 0.01
_DEFAULT_POLL_INTERVAL: Final = Seconds(1)
_DEFAULT_LOCK_REFRESH_INTERVAL: Final = Seconds(30)
_DEFAULT_LOCK_EXPIRATION: Final = Seconds(120)


def _offer_failed(cause: Cause[Any]) -> Effect[Never, PersistedQueueError]:
    return fail(
        PersistedQueueError(
            message="Failed to offer element to persisted queue", cause=cause.squash()
        )
    )


def _cleanup_failed(cause: Cause[Any]) -> Effect[Never, PersistedQueueError]:
    return fail(
        PersistedQueueError(message="Failed to clean up persisted queue", cause=cause.squash())
    )


def _sequence(value: object) -> int | str:
    return value if isinstance(value, int | str) else str(value)


def _lookup(  # noqa: PLR0917
    dialect: Dialect,
    table_name: str,
    expires_at: Fragment,
    poll_every: Seconds,
    lock_refresh: Seconds,
    states: QueueStates,
    settlements: Settlements,
) -> Callable[[str], Effect[Mailbox[Element], Never, Scope]]:
    """The mailbox of queue ``name``: its poller, and a fiber that marks
    failed every lock refresh interval the rows whose worker crashed on
    their last attempt. Closing it releases the claims it holds."""
    sql = dialect.sql
    claim = poll_statement(dialect, table_name, expires_at)

    def lookup(name: str) -> Effect[Mailbox[Element], Never, Scope]:
        state = states.get(name)
        max_attempts = state.max_attempts
        mailbox = Mailbox[Element]()

        # no finalizer will ever settle these rows
        flip_exhausted = sql(
            "UPDATE {} SET state = 'failed', acquired_at = NULL, acquired_by = NULL, "
            "updated_at = {}, "
            "last_failure = COALESCE(last_failure, 'Lock expired after final attempt') "
            "WHERE queue_name = {} AND state = 'pending' AND attempts >= {} "
            "AND (acquired_at IS NULL OR acquired_at < {})",
            sql.identifier(table_name),
            dialect.now,
            name,
            max_attempts,
            expires_at,
        )

        def poll(size: int) -> Effect[list[Element], SqlError]:
            lock = str(uuid.uuid4())

            def claimed(rows: Sequence[Row]) -> list[Element]:
                elements = [
                    Element(
                        sequence=_sequence(row["sequence"]),
                        id=str(row["id"]),
                        element=str(row["element"]),
                        attempts=column_int(row["attempts"]),
                        lock=lock,
                    )
                    for row in rows
                ]
                settlements.held.update(dict.fromkeys(elements))
                return elements

            return claim(name, max_attempts, size, dialect.string_literal(lock)).map(claimed)

        return (
            add_finalizer(
                lambda _: mailbox.queue.clear().flat_map(
                    lambda elements: for_each(
                        elements, settlements.interrupt, concurrency="unbounded"
                    )
                )
            )
            .and_then(
                flip_exhausted.tap_cause(log_warning)
                .ignore()
                .schedule(spaced(lock_refresh))
                .interruptible()
                .fork_scoped()
            )
            .and_then(run_poller(mailbox, poll=poll, nudge=state.nudge, poll_interval=poll_every))
            .as_(mailbox)
        )

    return lookup


class _SqlStore:
    __slots__ = ("_cleanup_batch", "_dialect", "_mailboxes", "_offer", "_settlements", "_states")

    def __init__(  # noqa: PLR0917
        self,
        dialect: Dialect,
        offer: OfferStatement,
        cleanup_batch: CleanupBatch,
        settlements: Settlements,
        states: QueueStates,
        mailboxes: RcMap[str, Mailbox[Element], Never],
    ) -> None:
        self._dialect = dialect
        self._offer = offer
        self._cleanup_batch = cleanup_batch
        self._settlements = settlements
        self._states = states
        self._mailboxes = mailboxes

    def offer(
        self,
        *,
        name: str,
        id: str,
        element: object,
        is_custom_id: bool,
        delay: Seconds | None = None,
    ) -> Effect[None, PersistedQueueError]:
        dialect = self._dialect

        def send() -> Effect[object, SqlError]:
            visible_at = dialect.now if delay is None else dialect.delayed_visible_at(delay)
            return self._offer(store_text(id), name, stringify(element), visible_at)

        def nudge() -> None:
            state = self._states.peek(name)
            if state is not None:
                state.nudge.unsafe_open()

        # wake takers once the offer is committed
        return (
            suspend(send)
            .catch_cause(_offer_failed)
            .flat_map(lambda _: dialect.sql.after_commit(sync(nudge)))
        )

    def _settle(
        self, options: TakeOptions, element: Element, exit_: Exit[Any, Any]
    ) -> Effect[None]:
        settlements = self._settlements
        if isinstance(exit_, Success):
            return settlements.complete(element)
        dead = dead_letter_from_cause(exit_.cause)
        if dead is not None:
            return settlements.fail(element, dead.cause)
        if exit_.cause.has_interrupts_only:
            return settlements.interrupt(element)
        if element.attempts >= options.max_attempts:
            return settlements.fail(element, exit_.cause)
        return options.retry_delay(element.attempts).flat_map(
            lambda delay: settlements.retry(element, delay, exit_.cause)
        )

    def take(self, options: TakeOptions) -> Effect[TakenElement, PersistedQueueError, Scope]:
        def claimed(element: Element) -> Effect[TakenElement | None, Never, Scope]:
            try:
                parsed = parse(element.element)
            except PARSE_ERRORS as defect:
                # a row that cannot be parsed never succeeds: dead-letter it,
                # and the loop takes the next one
                return self._settlements.fail(element, cause_die(defect)).as_(None)
            return add_finalizer(lambda exit_: self._settle(options, element, exit_)).as_(
                TakenElement(element.id, element.attempts, parsed)
            )

        def next_or_retry(taken: TakenElement | None) -> Effect[TakenElement, Never, Scope]:
            return suspend(loop) if taken is None else succeed(taken)

        def loop() -> Effect[TakenElement, Never, Scope]:
            return take_from(self._mailboxes, options.name, claimed).flat_map(next_or_retry)

        def body() -> Effect[TakenElement, Never, Scope]:
            self._states.get(options.name).max_attempts = options.max_attempts
            return loop()

        return suspend(body)

    def _cleanup_state(self, state: str, time_to_live: Seconds) -> Effect[int, SqlError]:
        return self._cleanup_batch(state, time_to_live).repeat(
            schedule=spaced(_CLEANUP_BATCH_DELAY),
            while_=lambda deleted: deleted == SQL_CLEANUP_BATCH_SIZE,
        )

    def cleanup(
        self, *, time_to_live: Seconds, failed_time_to_live: Seconds | None
    ) -> Effect[None, PersistedQueueError]:
        def body() -> Generator[Any, Any]:
            yield from self._cleanup_state("completed", time_to_live)
            if failed_time_to_live is not None:
                yield from self._cleanup_state("failed", failed_time_to_live)

        return gen(body).catch_cause(_cleanup_failed)


def make_store_sql(
    *,
    table_name: str = "effect_queue",
    poll_interval: Duration = _DEFAULT_POLL_INTERVAL,
    lock_refresh_interval: Duration = _DEFAULT_LOCK_REFRESH_INTERVAL,
    lock_expiration: Duration = _DEFAULT_LOCK_EXPIRATION,
) -> Effect[PersistedQueueStoreService, SqlError, SqlClient | Scope]:
    """A store in the table ``table_name`` (made and migrated if needed) of
    the ``SqlClient``. Each poll claims rows under a lock of its own,
    renewed every ``lock_refresh_interval`` while they are processed; a row
    whose lock is older than ``lock_expiration`` (its worker died) is
    claimed again, or marked failed if that was its last attempt. A
    settlement or renewal only applies to the claim a handler received, so
    a handler whose lock lapsed still settles its row until another poll
    claims it. Delays use the database's clock, rounded up to whole
    seconds."""
    poll_every = store_interval(poll_interval, _DEFAULT_POLL_INTERVAL)
    lock_refresh = store_interval(lock_refresh_interval, _DEFAULT_LOCK_REFRESH_INTERVAL)
    lock_expiration_seconds = store_interval(lock_expiration, _DEFAULT_LOCK_EXPIRATION)

    def build() -> Generator[Any, Any, PersistedQueueStoreService]:
        sql = (yield from SqlClient()).without_transforms()
        yield from migrator.make()(
            loader=migrations(table_name), table=f"{table_name}_migrations"
        ).or_die()
        dialect = Dialect(sql)
        expires_at = dialect.seconds_ago(lock_expiration_seconds)
        settlements = Settlements(dialect, table_name, ack_retry_schedule(lock_expiration_seconds))
        yield from (
            suspend(settlements.refresh_locks)
            .tap_cause(log_warning)
            .retry(spaced(0.5))
            .schedule(fixed(lock_refresh))
            .annotate_logs(
                {
                    "package": "@effect/sql",
                    "module": "SqlPersistedQueue",
                    "fiber": "refreshLocks",
                }
            )
            .fork_scoped()
        )
        states = QueueStates()
        mailboxes = yield from RcMap.make(
            _lookup(dialect, table_name, expires_at, poll_every, lock_refresh, states, settlements),
            idle_time_to_live=30.0,
        )
        store = _SqlStore(
            dialect,
            offer_statement(dialect, table_name),
            cleanup_statement(dialect, table_name),
            settlements,
            states,
            mailboxes,
        )
        return PersistedQueueStoreService(offer=store.offer, take=store.take, cleanup=store.cleanup)

    return gen(build)


def layer_store_sql(
    *,
    table_name: str = "effect_queue",
    poll_interval: Duration = _DEFAULT_POLL_INTERVAL,
    lock_refresh_interval: Duration = _DEFAULT_LOCK_REFRESH_INTERVAL,
    lock_expiration: Duration = _DEFAULT_LOCK_EXPIRATION,
) -> Layer[PersistedQueueStore, SqlError, SqlClient]:
    """The store of ``make_store_sql``."""
    return layer_effect(
        PersistedQueueStore,
        make_store_sql(
            table_name=table_name,
            poll_interval=poll_interval,
            lock_refresh_interval=lock_refresh_interval,
            lock_expiration=lock_expiration,
        ),
    )
