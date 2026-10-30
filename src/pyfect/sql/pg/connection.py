"""PostgreSQL sessions (Effect's ``@effect/sql-pg`` ``PgConnection``) on
psycopg's asyncio API, driven on a loop thread of its own (``_loop``), so
they work under ``run_sync`` and ``run_async`` alike and no fiber blocks.

A session runs one statement at a time; fibers sharing it wait in turn.
``pin`` reserves it for one scope (transactions, streams and listeners
pin), and statements through the pinned connection skip the line.

Interrupting a statement sends PostgreSQL a cancel request and waits for
the statement to end. Unless PostgreSQL confirms the cancel (``57014``),
a pool replaces the session before its next use, since a late cancel
could hit the next statement; a statement still running five seconds
after the cancel closes the session.
"""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from collections.abc import Callable, Coroutine, Sequence
from typing import TYPE_CHECKING, Any, Final, Never

from pyfect._core import Effect, _Suspend
from pyfect._primitives import Restore, uninterruptible_mask
from pyfect._subscriber_queue import DEFAULT_CAPACITY, FellBehind, check_capacity
from pyfect._subscriber_queue import offer as offer_to_subscriber
from pyfect.clock import sleep
from pyfect.effect import fail, provide_service, succeed, sync, void
from pyfect.errors import Done
from pyfect.exit import Failure
from pyfect.queue import Dequeue, Queue
from pyfect.scope import CloseableScope, Scope, add_finalizer, fork_in
from pyfect.semaphore import Semaphore
from pyfect.sql.error import SqlError, UnknownError
from pyfect.sql.pg._loop import call
from pyfect.sql.pg._resolve import ResolvedConfig, resolve, resolve_password
from pyfect.sql.pg._session import (
    Field,
    Mailbox,
    Notification,
    Result,
    Session,
    next_notification,
)
from pyfect.sql.pg.config import PgConnectionConfig
from pyfect.sql.pg.error import catch, connection_error, validate_channel_name

if TYPE_CHECKING:
    from pyfect.stream import Stream

type Row = dict[str, Any]

_UNLISTEN_TIMEOUT = 5.0

DEFAULT_LISTEN_CAPACITY: Final = DEFAULT_CAPACITY
"""How many notifications a ``listen`` queue holds untaken by default."""


def _fell_behind(capacity: int) -> SqlError:
    behind = FellBehind("PgConnection.listen", capacity)
    return SqlError(reason=UnknownError(cause=behind, message=str(behind), operation="listen"))


_catch_query = catch("PgConnection: Query failed", "query")
_catch_connect = catch("PgConnection: Failed to connect", "connect")


def _pin_released() -> SqlError:
    return connection_error("PgConnection: Pinned connection was released", "query")


def _released_with_work() -> SqlError:
    return connection_error(
        "PgConnection: Pinned connection released with work outstanding", "query"
    )


def _escape_identifier(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


class _Shared:
    """What every view of one session shares."""

    __slots__ = (
        "base",
        "config",
        "dead_with",
        "listeners",
        "owner",
        "retire_hooks",
        "session",
        "wire",
    )

    def __init__(self, session: Session, config: PgConnectionConfig) -> None:
        self.base = PgConnection(self)
        self.session = session
        self.config = config
        self.owner = Semaphore(1)
        """Held by a pin, or by one statement outside pins."""
        self.wire = Semaphore(1)
        """Held by the statement or stream running through a pin."""
        self.dead_with: SqlError | None = None
        self.retire_hooks: list[Callable[[], Effect[None]]] = []
        self.listeners: set[Queue[Notification, SqlError]] = set()
        """The open listeners' queues; closing the session shuts them."""

    def fatal(self, error: SqlError) -> Effect[None]:
        """Mark the session dead with its first fatal error, and tell the
        pool."""

        def body() -> Effect[None]:
            if self.dead_with is not None:
                return void
            self.dead_with = error
            effect: Effect[None] = void
            for hook in self.retire_hooks:
                effect = effect.and_then(hook())
            return effect

        return _Suspend(body)

    def check(self, error: SqlError) -> Effect[None]:
        """After a failed statement: a closed session is dead."""
        return self.fatal(error) if self.session.closed else void

    def close(self) -> Effect[None]:
        session = self.session

        def shut_listeners() -> Effect[None]:
            queues, self.listeners = list(self.listeners), set()
            effect: Effect[object] = void
            for queue in queues:
                effect = effect.and_then(queue.shutdown())
            return effect.as_void()

        return call(session.close, _catch_query).ignore().and_then(_Suspend(shut_listeners))


class _Lease:
    """A pin: released when its scope closes."""

    __slots__ = ("in_flight", "listeners", "released")

    def __init__(self) -> None:
        self.released = False
        self.in_flight = 0
        self.listeners = 0


class PgConnection:
    """A connected, authenticated PostgreSQL session (or a pinned view of
    one)."""

    __slots__ = ("_lease", "_shared")

    def __init__(self, shared: _Shared, lease: _Lease | None = None) -> None:
        self._shared = shared
        self._lease = lease

    @property
    def config(self) -> PgConnectionConfig:
        return self._shared.config

    @property
    def process_id(self) -> int:
        """The backend's process id."""
        return self._shared.session.process_id

    @property
    def base(self) -> PgConnection:
        """The unpinned connection (a pool's item)."""
        return self._shared.base

    def __eq__(self, other: object) -> bool:
        return (
            isinstance(other, PgConnection)
            and other._shared is self._shared
            and other._lease is self._lease
        )

    def __hash__(self) -> int:
        return hash((id(self._shared), id(self._lease)))

    @property
    def is_dead(self) -> bool:
        """Whether the session has failed for good (or was closed)."""
        return self._shared.dead_with is not None or self._shared.session.closed

    @property
    def needs_retire(self) -> bool:
        """Whether a pool should replace the session: it is dead, or a
        cancel was not confirmed."""
        return self.is_dead or self._shared.session.retire

    def on_retire(self, hook: Callable[[], Effect[None]]) -> None:
        """Run ``hook`` once the session dies (a pool replaces it)."""
        self._shared.retire_hooks.append(hook)

    # --- ownership ------------------------------------------------------------

    @property
    def pin(self) -> Effect[PgConnection, Never, Scope]:
        """Reserve the session until the scope closes; statements through
        the connection given skip the line, those through this one wait.
        Pinning a pinned connection gives it back. Once released, the pinned
        connection fails every statement; releasing it while a statement or
        a listener is still open closes the session."""
        if self._lease is not None:
            return succeed(self)
        shared = self._shared

        def release(lease: _Lease) -> Effect[None]:
            def body() -> Effect[None]:
                lease.released = True
                closing: Effect[None] = void
                if lease.in_flight > 0 or lease.listeners > 0:
                    closing = shared.fatal(_released_with_work()).and_then(shared.close())
                return closing.and_then(shared.owner.release(1)).as_void()

            return _Suspend(body)

        def body(restore: Restore) -> Effect[PgConnection, Never, Scope]:
            lease = _Lease()
            taken: Effect[int] = restore(shared.owner.take(1))
            return taken.and_then(add_finalizer(lambda _: release(lease))).as_(
                PgConnection(shared, lease)
            )

        return uninterruptible_mask(body)

    def _statement[A](
        self, make: Callable[[Session], Coroutine[Any, Any, A]]
    ) -> Effect[A, SqlError]:
        shared = self._shared
        lease = self._lease

        def body() -> Effect[A, SqlError]:
            if shared.dead_with is not None:
                return fail(shared.dead_with)
            if lease is not None and lease.released:
                return fail(_pin_released())
            session = shared.session
            run = call(lambda: make(session), _catch_query, session.cancel_query).tap_error(
                shared.check
            )
            if lease is None:
                return shared.owner.with_permits(run)
            held = lease

            def done() -> None:
                held.in_flight -= 1

            def on_wire() -> Effect[A, SqlError]:
                # A statement still queued when the pin is released fails
                # here and never reaches the next owner's session.
                if shared.dead_with is not None:
                    return fail(shared.dead_with)
                if held.released:
                    return fail(_pin_released())
                held.in_flight += 1
                return run.ensuring(sync(done))

            return shared.wire.with_permits(_Suspend(on_wire))

        return _Suspend(body)

    # --- statements -----------------------------------------------------------

    def query(
        self, sql: str, params: Sequence[object] = (), prepare: bool = True
    ) -> Effect[Result, SqlError]:
        """Run ``sql`` with ``params`` bound to ``$1``, ``$2``, ...; rows by
        column name. ``prepare=False`` skips the prepared statements."""
        values = tuple(params)
        return self._statement(lambda session: session.query(sql, values, prepare))

    def query_values(
        self, sql: str, params: Sequence[object] = (), prepare: bool = True
    ) -> Effect[list[tuple[Any, ...]], SqlError]:
        """``query``, with rows as tuples in column order."""
        values = tuple(params)
        return self._statement(lambda session: session.query_values(sql, values, prepare))

    @property
    def interrupt(self) -> Effect[None]:
        """Ask PostgreSQL to cancel the running statement. Never fails;
        does nothing through a released pin."""
        shared = self._shared
        lease = self._lease

        def body() -> Effect[None]:
            if lease is not None and lease.released:
                return void
            return call(shared.session.interrupt, _catch_query).ignore()

        return _Suspend(body)

    def stream(self, sql: str, params: Sequence[object] = ()) -> Stream[Row, SqlError]:
        """The rows of ``sql``, read as the stream is pulled. The session is
        pinned while the stream runs; ending it early cancels the
        statement."""
        from pyfect import stream as stream_module

        values = tuple(params)

        def opened(pinned: PgConnection) -> Effect[Stream[Row, SqlError], SqlError, Scope]:
            return pinned._open_stream(sql, values)

        return stream_module.unwrap(self.pin.flat_map(opened))

    def _open_stream(
        self, sql: str, params: tuple[object, ...]
    ) -> Effect[Stream[Row, SqlError], SqlError, Scope]:
        from pyfect import stream as stream_module

        shared = self._shared
        lease = self._lease
        session = shared.session

        def body() -> Effect[Stream[Row, SqlError], SqlError, Scope]:
            if shared.dead_with is not None:
                return fail(shared.dead_with)
            if lease is not None and lease.released:
                return fail(_pin_released())

            def finish(rows: Any) -> Effect[None]:
                def done() -> None:
                    if lease is not None:
                        lease.in_flight -= 1

                return (
                    call(lambda: session.close_stream(rows), _catch_query)
                    .ignore()
                    .and_then(sync(done))
                )

            def build(rows: Any) -> Effect[Stream[Row, SqlError], Never, Scope]:
                def chunk(found: list[Row]) -> Effect[tuple[Row, ...], SqlError | Done]:
                    return succeed(tuple(found)) if found else fail(Done())

                pull = (
                    call(lambda: session.next_rows(rows), _catch_query)
                    .tap_error(shared.check)
                    .flat_map(chunk)
                )
                stream: Stream[Row, SqlError] = stream_module.from_pull(succeed(pull))
                if lease is not None:
                    lease.in_flight += 1
                return add_finalizer(lambda _: finish(rows)).as_(stream)

            opened = call(
                lambda: session.open_stream(sql, params), _catch_query, release=session.close_stream
            )
            return uninterruptible_mask(lambda restore: restore(opened).flat_map(build))

        if lease is None:
            return _Suspend(body)

        def on_wire(restore: Restore) -> Effect[Stream[Row, SqlError], SqlError, Scope]:
            taken: Effect[int] = restore(shared.wire.take(1))
            held = add_finalizer(lambda _: shared.wire.release(1))
            return taken.and_then(held).and_then(_Suspend(body))

        return uninterruptible_mask(on_wire)

    # --- notifications --------------------------------------------------------

    def listen(
        self, channel: str, *, capacity: int = DEFAULT_LISTEN_CAPACITY
    ) -> Effect[Dequeue[Notification, SqlError], SqlError, Scope]:
        """Listen on ``channel``: a queue of its notifications, once
        PostgreSQL confirmed ``LISTEN``. The session stays pinned until the
        scope closes, which runs ``UNLISTEN`` (closing a session that does
        not answer within five seconds) and shuts the queue down,
        interrupting its takers. If the session fails, the queue fails with
        its error. The queue holds at most ``capacity`` notifications not
        yet taken; one more fails it (after those) with an error saying the
        listener fell behind."""
        check_capacity(capacity)
        error = validate_channel_name(channel, "listen")
        if error is not None:
            return fail(error)
        connection = self

        def body(restore: Restore) -> Effect[Dequeue[Notification, SqlError], SqlError, Scope]:
            def in_scope(parent: CloseableScope) -> Effect[Any, SqlError, Scope]:
                return parent.fork().flat_map(
                    lambda scope: restore(
                        connection._listen_in(channel, capacity, scope)
                    ).tap_cause(lambda cause: scope.close(Failure(cause)))
                )

            return Scope().flat_map(in_scope)

        return uninterruptible_mask(body)

    def _listen_in(
        self, channel: str, capacity: int, scope: CloseableScope
    ) -> Effect[Dequeue[Notification, SqlError], SqlError]:
        shared = self._shared
        session = shared.session
        identifier = _escape_identifier(channel)

        def registered(pinned: PgConnection) -> Effect[Dequeue[Notification, SqlError], SqlError]:
            lease = pinned._lease
            assert lease is not None
            if shared.dead_with is not None:
                return fail(shared.dead_with)
            if lease.released:
                return fail(_pin_released())

            def with_queue(
                queue: Queue[Notification, SqlError],
            ) -> Effect[Dequeue[Notification, SqlError], SqlError]:
                async def subscribe() -> Any:
                    return session.subscribe(channel, capacity)

                async def drop(mailbox: Any) -> None:
                    session.unsubscribe(channel, mailbox)

                def registered(mailbox: Any) -> Effect[Any]:
                    lease.listeners += 1
                    shared.listeners.add(queue)
                    stop = scope.add_finalizer(
                        lambda _: pinned._unlisten(channel, identifier, mailbox, queue)
                    )
                    return stop.as_(mailbox)

                def started(mailbox: Any) -> Effect[Dequeue[Notification, SqlError], SqlError]:
                    deliver = fork_in(pinned._deliver(mailbox, queue), scope)
                    listening = pinned.query(f"LISTEN {identifier}")
                    return listening.and_then(deliver).as_(queue)

                # The mailbox is subscribed and its cleanup registered as one
                # step, so an interrupt cannot leave it behind.
                subscribed: Effect[Any, SqlError] = uninterruptible_mask(
                    lambda restore: restore(call(subscribe, _catch_query, release=drop)).flat_map(
                        registered
                    )
                )
                return subscribed.flat_map(started)

            return Queue[Notification, SqlError].dropping(capacity).flat_map(with_queue)

        return self.pin.flat_map(registered).pipe(provide_service(Scope, scope))

    def _deliver(self, mailbox: Mailbox, queue: Queue[Notification, SqlError]) -> Effect[None]:
        """Move notifications from the loop into ``queue``; the session's
        failure fails it."""
        shared = self._shared

        def behind() -> SqlError:
            return _fell_behind(mailbox.capacity)

        def handle(batch: list[Notification | BaseException]) -> Effect[bool]:
            notes = [item for item in batch if isinstance(item, Notification)]
            if not offer_to_subscriber(queue, notes, behind):
                return succeed(False)
            failures = [item for item in batch if not isinstance(item, Notification)]
            if not failures:
                return succeed(True)
            if isinstance(failures[0], FellBehind):
                return queue.fail(behind()).as_(False)
            error = _catch_query(failures[0])

            def failed() -> Effect[bool]:
                dead = shared.dead_with or error
                return queue.fail(dead).as_(False)

            return shared.fatal(error).and_then(_Suspend(failed))

        def loop(_: object = None) -> Effect[None]:
            pulled = call(lambda: next_notification(mailbox), _catch_query).flat_map(handle)
            stopped = pulled.catch_all(lambda _: succeed(False))
            return stopped.flat_map(lambda more: loop() if more else void)

        return _Suspend(loop)

    def _unlisten(
        self,
        channel: str,
        identifier: str,
        mailbox: Any,
        queue: Queue[Notification, SqlError],
    ) -> Effect[None]:
        shared = self._shared
        lease = self._lease
        assert lease is not None

        async def unsubscribe() -> bool:
            return shared.session.unsubscribe(channel, mailbox)

        def after(last: bool) -> Effect[None]:
            lease.listeners -= 1
            shared.listeners.discard(queue)
            return shared.wire.with_permits(_Suspend(on_wire)) if last else void

        def on_wire() -> Effect[None]:
            # Skipped once the pin is released: the session has moved on.
            if shared.dead_with is not None or lease.released:
                return void
            session = shared.session
            statement = call(
                lambda: session.query(f"UNLISTEN {identifier}", (), False),
                _catch_query,
                session.cancel_query,
            )
            # The timeout runs once UNLISTEN is sent; a session that does not
            # answer is closed, which ends the statement at once.
            unanswered = sleep(_UNLISTEN_TIMEOUT).and_then(
                shared.fatal(connection_error("PgConnection: UNLISTEN timed out", "query"))
                .and_then(shared.close())
                .uninterruptible()
            )
            lease.in_flight += 1

            def done() -> None:
                lease.in_flight -= 1

            return statement.ignore().race_first(unanswered).ensuring(sync(done))

        unlisten = (
            call(unsubscribe, _catch_query).catch_all(lambda _: succeed(False)).flat_map(after)
        )
        return unlisten.and_then(queue.shutdown()).as_void()


def _open(config: PgConnectionConfig, resolved: ResolvedConfig) -> Effect[PgConnection, SqlError]:
    cache = config.prepared_statement_cache_size if config.prepare else 0

    def connect(password: str | None) -> Effect[PgConnection, SqlError]:
        session = call(
            lambda: Session.connect(resolved.params, password, config.types, cache),
            _catch_connect,
            release=Session.close,
        )
        return session.map(lambda s: _Shared(s, config).base)

    return resolve_password(resolved.password).flat_map(connect)


def make(config: PgConnectionConfig) -> Effect[PgConnection, SqlError, Scope]:
    """Connect and authenticate one session; it closes with the scope.
    Resolving the password, connecting and authenticating are bounded by
    ``connect_timeout``."""

    def opened(resolved: ResolvedConfig) -> Effect[PgConnection, SqlError, Scope]:
        def body(restore: Restore) -> Effect[PgConnection, SqlError, Scope]:
            connected: Effect[PgConnection, SqlError] = restore(_open(config, resolved))
            return connected.flat_map(
                lambda conn: add_finalizer(lambda _: conn._shared.close()).as_(conn)
            )

        def timed_out() -> Effect[Never, SqlError]:
            return fail(connection_error("PgConnection: Connection timed out", "connect"))

        return uninterruptible_mask(body).timeout_or_else(resolved.connect_timeout, timed_out)

    return resolve(config).flat_map(opened)


__all__ = [
    "DEFAULT_LISTEN_CAPACITY",
    "Field",
    "Notification",
    "PgConnection",
    "Result",
    "Row",
    "make",
]
