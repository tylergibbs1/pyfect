"""Transactions: ``BEGIN`` / savepoints, commit or rollback, and the
callbacks that run after the outermost commit (Effect's
``SqlClient.makeWithTransaction``)."""
# pyright: reportPrivateUsage=false

from __future__ import annotations

import itertools
import types
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Never, cast
from weakref import WeakKeyDictionary

from pyfect._core import Effect, _FailCause, _Locally, _MatchCause, _Succeed, _Suspend, _WithFiber
from pyfect._effect_args import require_effect
from pyfect._effect_resources import _run_finalizer
from pyfect._primitives import Restore, uninterruptible_mask
from pyfect.cause import Cause, Die, Fail, from_reasons
from pyfect.clock import Clock
from pyfect.context import Context, Reference, Tag
from pyfect.effect import die
from pyfect.exit import Exit, Failure, Success
from pyfect.logger._log import log_with_level
from pyfect.logger._refs import UnhandledLogLevel
from pyfect.reactivity import Keys, Reactivity, ReactivityService
from pyfect.scope import CloseableScope, Scope
from pyfect.semaphore import Semaphore
from pyfect.sql.connection import Connection
from pyfect.sql.error import SqlError
from pyfect.tracer._refs import ParentSpan
from pyfect.tracer._spans import use_span

if TYPE_CHECKING:
    from pyfect._fiber import Fiber
    from pyfect.tracer._model import Span


@dataclass(frozen=True, slots=True, eq=False, weakref_slot=True)
class TransactionLevel:
    """The open transaction of a fiber: its connection and its depth (0 for
    the outermost, then one more per savepoint)."""

    connection: Connection
    depth: int


class TransactionConnection(Tag[TransactionLevel], base=True):
    """The open transaction of one client. Each client has its own subclass
    (``transaction_connection``), so transactions of different clients
    don't mix."""


_client_ids = itertools.count()


def transaction_connection(client_id: int | None = None) -> type[TransactionConnection]:
    """A new transaction tag, for client ``client_id`` (the next free id by
    default)."""
    client_id = next(_client_ids) if client_id is None else client_id
    key = f"effect/sql/SqlClient/TransactionConnection/{client_id}"
    return cast(
        "type[TransactionConnection]",
        types.new_class(
            f"TransactionConnection{client_id}", (TransactionConnection,), {"key": key}
        ),
    )


class SafeIntegers(Reference[bool], key="effect/sql/SqlClient/SafeIntegers"):
    """Drivers that read large integers lossily read them exactly instead.
    Python's integers are exact, so the SQLite driver ignores it."""

    @classmethod
    def default(cls) -> bool:
        return False


class BeginTransaction(Reference[str | None], key="effect/sql/SqlClient/BeginTransaction"):
    """The statement that starts outermost transactions in place of the
    client's ``BEGIN``, such as ``BEGIN ISOLATION LEVEL SERIALIZABLE``. It
    runs unprepared; savepoints ignore it. Provide it around the one
    ``with_transaction`` it is for, and never build it from untrusted
    input."""

    @classmethod
    def default(cls) -> str | None:
        return None


# --- after commit ------------------------------------------------------------------


@dataclass(slots=True, eq=False)
class _AfterCommitBuffer:
    """The ``after_commit`` callbacks of one transaction level. A committed
    savepoint hands them to its parent; the outermost level runs them."""

    parent: _AfterCommitBuffer | None
    callbacks: list[Effect[None]] = field(default_factory=list[Effect[None]])
    open: bool = True


# Keyed by the level, so a context without the transaction tag has no
# buffer, and transactions not started by ``make_with_transaction`` have none.
_buffers: WeakKeyDictionary[TransactionLevel, _AfterCommitBuffer] = WeakKeyDictionary()


def _run_after_commit[R](effect: Effect[None, Never, R]) -> Effect[None, Never, R]:
    def logged(cause: Cause[Never]) -> Effect[None]:
        def body(fiber: Fiber[Any, Any]) -> Effect[None]:
            level = fiber.get_ref(UnhandledLogLevel)
            if level is None:
                return _Succeed(None)
            return log_with_level(level, "Unhandled error in SqlClient.afterCommit callback", cause)

        return _WithFiber(body)

    return _MatchCause(effect, logged, lambda _: _Succeed(None))


type AfterCommit = Callable[[Effect[None, Never, Any]], Effect[None, Never, Any]]


def make_after_commit(
    transaction_service: type[TransactionConnection],
) -> Callable[[Effect[None, Never, Any]], Effect[None]]:
    """``after_commit`` for the transactions of ``transaction_service``:
    buffer the effect until the outermost commit, or run it now outside a
    transaction."""

    def after_commit(effect: Effect[None, Never, Any]) -> Effect[None]:
        def body(fiber: Fiber[Any, Any]) -> Effect[None]:
            services: Context[Any] = fiber._context
            found, level = services.lookup(transaction_service)
            buffer = _buffers.get(level) if found else None
            if buffer is None:
                return _run_after_commit(effect)
            current: _AfterCommitBuffer | None = buffer
            while current is not None:
                if not current.open:
                    return die(
                        RuntimeError("SqlClient.afterCommit: the transaction has already ended")
                    )
                current = current.parent
            # Runs later with the services in scope now, minus the transaction.
            without = services.pipe(Context.omit(transaction_service))
            buffer.callbacks.append(_Locally(effect, lambda _: without))
            return _Succeed(None)

        return _WithFiber(body)

    return after_commit


# --- transactions -------------------------------------------------------------------


def _failures_to_defects(cause: Cause[Any]) -> Cause[Never]:
    """A failed ``COMMIT`` whose cleanup failed too leaves the connection
    unsafe: both errors become defects, so typed recovery can't hide them."""
    return from_reasons(
        Die(
            r.error if isinstance(r.error, BaseException) else RuntimeError(r.error),
            annotations=r.annotations,
        )
        if isinstance(r, Fail)
        else r
        for r in cause.reasons
    )


class _DeferredReactivity(ReactivityService):
    """Reactivity inside a transaction: invalidations wait for the commit."""

    __slots__ = ("_after_commit", "_inner")

    def __init__(
        self, inner: ReactivityService, after_commit: Callable[[Effect[None]], Effect[None]]
    ) -> None:
        super().__init__()
        self._inner = inner
        self._after_commit = after_commit
        self._handlers = inner._handlers

    def invalidate(self, keys: Keys) -> Effect[None]:
        return self._after_commit(_Suspend(lambda: _Succeed(self._inner.invalidate_unsafe(keys))))


type Control = Callable[[Connection], Effect[None, SqlError]]
type LevelControl = Callable[[Connection, int], Effect[None, SqlError]]

_semaphore_ids = itertools.count()


@dataclass(frozen=True, slots=True, kw_only=True)
class TransactionOptions:
    """How a driver runs its transactions.

    - ``acquire_connection(restore)``: the connection of an outermost
      transaction; it runs masked, so wrap the wait in ``restore``. Its
      scope closes with the transaction.
    - ``begin(conn, statement)``: start one (``statement`` is the
      ``BeginTransaction`` provided, if any)
    - ``savepoint`` / ``rollback_savepoint`` / ``release_savepoint``:
      nested levels (``release_savepoint`` is optional)
    - ``commit``, ``rollback``; ``on_commit_failure`` cleans up the
      connection when ``COMMIT`` fails
    """

    transaction_service: type[TransactionConnection]
    span_attributes: tuple[tuple[str, object], ...]
    acquire_connection: Callable[[Restore], Effect[Connection, SqlError, Scope]]
    begin: Callable[[Connection, str | None], Effect[None, SqlError]]
    savepoint: LevelControl
    commit: Control
    rollback: Control
    rollback_savepoint: LevelControl
    release_savepoint: LevelControl | None = None
    on_commit_failure: Control | None = None


class WithTransaction:
    """Runs effects in a transaction (see ``SqlClientService.with_transaction``)."""

    __slots__ = ("_after_commit", "_options", "_semaphore_tag")

    def __init__(self, options: TransactionOptions) -> None:
        self._options = options
        semaphore_id = next(_semaphore_ids)
        self._semaphore_tag = cast(
            "type[Tag[Semaphore]]",
            types.new_class(
                f"TransactionSemaphore{semaphore_id}",
                (Tag[Semaphore],),
                {"key": f"effect/sql/SqlClient/TransactionSemaphore/{semaphore_id}"},
            ),
        )
        self._after_commit = make_after_commit(options.transaction_service)

    def __call__[A, E, R](self, effect: Effect[A, E, R]) -> Effect[A, E | SqlError, R]:
        require_effect(effect, "effect")
        return uninterruptible_mask(
            lambda restore: use_span(
                "sql.transaction",
                lambda span: _WithFiber(lambda fiber: self._run(effect, restore, span, fiber)),
                kind="internal",
            )
        )

    def _run[A, E, R](
        self, effect: Effect[A, E, R], restore: Restore, span: Span, fiber: Fiber[Any, Any]
    ) -> Effect[A, E | SqlError, R]:
        opts = self._options
        for key, value in opts.span_attributes:
            span.attribute(key, value)
        services: Context[Any] = fiber._context
        clock = fiber.get_ref(Clock)
        found, outer = services.lookup(opts.transaction_service)
        parent: TransactionLevel | None = outer if found else None
        depth = 0 if parent is None else parent.depth + 1
        buffer = _AfterCommitBuffer(None if parent is None else _buffers.get(parent))
        committed = False

        def in_level(conn: Connection) -> Effect[A, E | SqlError, R]:
            level = TransactionLevel(conn, depth)
            _buffers[level] = buffer
            found_reactivity, reactivity = services.lookup(Reactivity)
            inner = services.add(opts.transaction_service, level)
            if found_reactivity:
                inner = inner.add(Reactivity, _DeferredReactivity(reactivity, self._after_commit))
            inner = inner.add(self._semaphore_tag, Semaphore(1)).add(ParentSpan, span)
            body: Effect[A, E, R] = _Locally(restore(effect), lambda _: inner)

            def finish(exit_: Exit[A, E]) -> Effect[A, E | SqlError, R]:
                end = self._end(conn, depth, exit_, span, clock.now_nanos_unsafe())

                def done(_: object) -> Effect[A, E]:
                    nonlocal committed
                    committed = isinstance(exit_, Success)
                    return (
                        _Succeed(exit_.value)
                        if isinstance(exit_, Success)
                        else _FailCause(exit_.cause)
                    )

                return _MatchCause(end, _merge_failure(exit_), done)

            return _MatchCause(body, lambda c: finish(Failure(c)), lambda a: finish(Success(a)))

        def start(conn: Connection) -> Effect[None, SqlError]:
            if depth == 0:
                return opts.begin(conn, fiber.get_ref(BeginTransaction))
            return opts.savepoint(conn, depth)

        transaction: Effect[A, E | SqlError, R]
        if parent is not None:
            conn = parent.connection
            transaction = start(conn).flat_map(lambda _: in_level(conn))
        else:
            scope = CloseableScope()

            acquire: Effect[Connection, SqlError] = _Locally(
                opts.acquire_connection(restore), lambda ctx: ctx.add(Scope, scope)
            )
            transaction = _MatchCause(
                acquire,
                lambda c: _run_finalizer(scope.close(Failure(c)), Failure(c)),
                lambda conn: _on_exit(start(conn).flat_map(lambda _: in_level(conn)), scope.close),
            )

        def settle(_: Exit[Any, Any]) -> Effect[None]:
            buffer.open = False
            if not committed or not buffer.callbacks:
                return _Succeed(None)
            if buffer.parent is not None:
                buffer.parent.callbacks.extend(buffer.callbacks)
                return _Succeed(None)
            run: Effect[None] = _Succeed(None)
            for callback in buffer.callbacks:
                run = run.and_then(_run_after_commit(callback))
            return run

        settled = _on_exit(transaction, settle)
        if parent is None:
            return settled
        semaphore: Semaphore = services.get_unsafe(self._semaphore_tag)
        return semaphore.with_permits(settled)

    def _end(
        self, conn: Connection, depth: int, exit_: Exit[Any, Any], span: Span, now: int
    ) -> Effect[None, SqlError]:
        opts = self._options
        end: Effect[None, SqlError]
        if isinstance(exit_, Success):
            if depth == 0:
                span.event("effect.sql.transaction.commit", now)
                end = _commit(opts, conn)
            else:
                span.event("effect.sql.transaction.savepoint", now)
                end = _Succeed(None)
        else:
            span.event("effect.sql.transaction.rollback", now)
            end = (
                opts.rollback_savepoint(conn, depth) if depth > 0 else opts.rollback(conn)
            ).or_die()
        release = opts.release_savepoint
        if depth > 0 and release is not None:
            end = end.and_then(release(conn, depth).or_die())
        return end


def _commit(opts: TransactionOptions, conn: Connection) -> Effect[None, SqlError]:
    on_commit_failure = opts.on_commit_failure
    if on_commit_failure is None:
        return opts.commit(conn)

    def failed(commit_cause: Cause[SqlError]) -> Effect[None, SqlError]:
        return _MatchCause(
            on_commit_failure(conn),
            lambda cleanup_cause: _FailCause(_failures_to_defects(commit_cause + cleanup_cause)),
            lambda _: _FailCause(commit_cause),
        )

    return _MatchCause(opts.commit(conn), failed, lambda _: _Succeed(None))


def _merge_failure(exit_: Exit[Any, Any]) -> Callable[[Cause[Any]], Effect[Never, Any]]:
    """A failed end of a transaction: added to the body's failure, if any."""

    def on_failure(cause: Cause[Any]) -> Effect[Never, Any]:
        return cast("Effect[Never, Any]", _run_finalizer(_FailCause(cause), exit_))

    return on_failure


def _on_exit[A, E, R](
    effect: Effect[A, E, R], f: Callable[[Exit[A, E]], Effect[object, Any, Any]]
) -> Effect[A, E, R]:
    """``f(exit)`` after ``effect`` (already masked), then its exit; a
    failure of ``f`` is added to the result."""
    return cast(
        "Effect[A, E, R]",
        _MatchCause(
            effect,
            lambda c: _run_finalizer(f(Failure(c)), Failure(c)),
            lambda a: _run_finalizer(f(Success(a)), Success(a)),
        ),
    )


def make_with_transaction(options: TransactionOptions) -> WithTransaction:
    """Runs effects in transactions: outermost ones ``BEGIN`` and commit on
    success; nested ones use savepoints. Failures and interruptions roll
    back."""
    return WithTransaction(options)


__all__ = [
    "AfterCommit",
    "BeginTransaction",
    "SafeIntegers",
    "TransactionConnection",
    "TransactionLevel",
    "TransactionOptions",
    "WithTransaction",
    "make_after_commit",
    "make_with_transaction",
    "transaction_connection",
]
