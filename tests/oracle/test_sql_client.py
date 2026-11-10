"""Ports of Effect's ``sql/SqlClient.test.ts``.

Each test's docstring is the Effect test title. Effect's harness for
``makeWithTransaction`` passes a stub connection; here it is any object,
as the protocol is not checked at runtime.
"""
# pyright: reportPrivateUsage=false

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, cast

import pyfect as fx
from pyfect import reactivity, testing
from pyfect._core import _Locally
from pyfect.cause import Cause, Die, Fail, UnhandledError
from pyfect.context import Context, Tag
from pyfect.sql import client as sql_client
from pyfect.sql import statement as st
from pyfect.sql.connection import Connection, Row, TransformRows, ValueRow
from pyfect.sql.error import DeadlockError, SerializationError, SqlError, UnknownError
from pyfect.tracer import NativeSpan, SpanRequest, Tracer, TracerEnabled, TracerTimingEnabled
from pyfect.tracer._model import Ended


def _sql_error(message: str) -> SqlError:
    return SqlError(reason=UnknownError(cause=Exception(message), message=message))


def _reasons(cause: Cause[Any]) -> list[tuple[str, object]]:
    """The cause's failures and defects, as ``("fail" | "die", value)``."""
    out: list[tuple[str, object]] = []
    for reason in cause.reasons:
        if isinstance(reason, Fail):
            out.append(("fail", reason.error))
        elif isinstance(reason, Die):
            defect = reason.defect
            out.append(("die", defect.error if isinstance(defect, UnhandledError) else defect))
    return out


def _assert_typed_failure(ex: fx.Exit[Any, Any], error: object) -> None:
    assert isinstance(ex, fx.Failure)
    assert not ex.cause.has_dies, ex.cause.pretty()
    assert _reasons(ex.cause) == [("fail", error)]


# --- the makeWithTransaction harness ----------------------------------------------


@dataclass
class _Harness:
    calls: list[str]
    with_transaction: sql_client.WithTransaction


def _make_harness(
    *,
    span_attributes: tuple[tuple[str, object], ...] = (),
    acquire: fx.Effect[None] | None = None,
    during_begin: fx.Effect[None] | None = None,
    begin: SqlError | None = None,
    commit: Callable[[], fx.Effect[None, SqlError]] | None = None,
    on_commit_failure: Callable[[], fx.Effect[None, SqlError]] | None = None,
    savepoint: SqlError | None = None,
    rollback_savepoint: SqlError | None = None,
    release_savepoint: bool | SqlError = False,
) -> _Harness:
    calls: list[str] = []
    conn = cast("Connection", object())
    state = {"active": False}
    savepoints: list[int] = []

    def record(name: str) -> fx.Effect[None]:
        return fx.sync(lambda: calls.append(name))

    def do_begin(_conn: Connection, statement: str | None) -> fx.Effect[None, SqlError]:
        def after(_: object) -> fx.Effect[None, SqlError]:
            if begin is not None:
                return fx.fail(begin)
            state["active"] = True
            return during_begin or fx.void

        return record("begin" if statement is None else f"begin({statement})").flat_map(after)

    def do_savepoint(_conn: Connection, id_: int) -> fx.Effect[None, SqlError]:
        def after(_: object) -> fx.Effect[None, SqlError]:
            if savepoint is not None:
                return fx.fail(savepoint)
            savepoints.append(id_)
            return fx.void

        return record(f"savepoint({id_})").flat_map(after)

    def end_transaction(what: str) -> fx.Effect[None, SqlError]:
        if not state["active"]:
            return fx.fail(_sql_error(f"cannot {what} - no transaction is active"))
        state["active"] = False
        return fx.void

    def do_commit(_conn: Connection) -> fx.Effect[None, SqlError]:
        return record("commit").and_then(
            fx.suspend(lambda: commit() if commit is not None else end_transaction("commit"))
        )

    def do_rollback(_conn: Connection) -> fx.Effect[None, SqlError]:
        return record("rollback").and_then(fx.suspend(lambda: end_transaction("rollback")))

    def do_rollback_savepoint(_conn: Connection, id_: int) -> fx.Effect[None, SqlError]:
        def after(_: object) -> fx.Effect[None, SqlError]:
            if rollback_savepoint is not None:
                return fx.fail(rollback_savepoint)
            if id_ in savepoints:
                return fx.void
            return fx.fail(_sql_error(f"cannot rollback to savepoint {id_} - it does not exist"))

        return record(f"rollbackSavepoint({id_})").flat_map(after)

    def do_release(_conn: Connection, id_: int) -> fx.Effect[None, SqlError]:
        failure = release_savepoint if isinstance(release_savepoint, SqlError) else None
        return record(f"releaseSavepoint({id_})").and_then(
            fx.void if failure is None else fx.fail(failure)
        )

    def acquire_connection(_restore: Any) -> fx.Effect[Connection, SqlError, fx.Scope]:
        return (
            record("acquireConnection")
            .and_then(acquire or fx.void)
            .and_then(fx.add_finalizer(lambda _: record("closeConnection")))
            .as_(conn)
        )

    with_transaction = sql_client.make_with_transaction(
        sql_client.TransactionOptions(
            transaction_service=sql_client.transaction_connection(),
            span_attributes=span_attributes,
            acquire_connection=acquire_connection,
            begin=do_begin,
            savepoint=do_savepoint,
            commit=do_commit,
            on_commit_failure=None
            if on_commit_failure is None
            else lambda _conn: record("onCommitFailure").and_then(on_commit_failure()),
            rollback=do_rollback,
            rollback_savepoint=do_rollback_savepoint,
            release_savepoint=None if release_savepoint is False else do_release,
        )
    )
    return _Harness(calls, with_transaction)


# --- the client over a recording connection ----------------------------------------


class _RecordingConnection:
    def __init__(self, record: Callable[[str], fx.Effect[None]]) -> None:
        self._record = record

    def _run(self, sql: str) -> fx.Effect[list[Any]]:
        return self._record(sql).as_([])

    def execute(
        self, sql: str, params: Sequence[object], transform_rows: TransformRows | None, /
    ) -> fx.Effect[Sequence[Row], SqlError]:
        return self._run(f"prepared({sql})")

    def execute_raw(self, sql: str, params: Sequence[object], /) -> fx.Effect[object, SqlError]:
        return self._run(sql)

    def execute_values(
        self, sql: str, params: Sequence[object], /
    ) -> fx.Effect[Sequence[ValueRow], SqlError]:
        return self._run(sql)

    def execute_values_unprepared(
        self, sql: str, params: Sequence[object], /
    ) -> fx.Effect[Sequence[ValueRow], SqlError]:
        return self._run(sql)

    def execute_unprepared(
        self, sql: str, params: Sequence[object], transform_rows: TransformRows | None, /
    ) -> fx.Effect[Sequence[Row], SqlError]:
        return self._run(sql)

    def execute_stream(
        self, sql: str, params: Sequence[object], transform_rows: TransformRows | None, /
    ) -> fx.Stream[Row, SqlError]:
        return fx.stream.from_effect(self._run(sql)).flat_map(fx.stream.from_iterable)


@dataclass
class _Client:
    sql: sql_client.SqlClientService
    reactivity: reactivity.ReactivityService
    calls: list[str] = field(default_factory=list[str])

    def record(self, call: str) -> fx.Effect[None]:
        return fx.sync(lambda: self.calls.append(call))

    def after(self, name: str) -> fx.Effect[None]:
        return self.sql.after_commit(self.record(f"after({name})"))


def _make_client(
    *,
    acquire: fx.Effect[None, Any, fx.Scope] | None = None,
    commit: fx.Effect[None, SqlError] | None = None,
    prepare_transaction_controls: bool = False,
    release: fx.Effect[None] | None = None,
) -> fx.Effect[_Client]:
    calls: list[str] = []

    def record(call: str) -> fx.Effect[None]:
        return fx.sync(lambda: calls.append(call))

    connection = _RecordingConnection(record)
    acquirer = (
        (acquire or fx.void)
        .and_then(fx.add_finalizer(lambda _: record("release").and_then(release or fx.void)))
        .as_(connection)
    )

    def recorded_commit(_conn: Connection) -> fx.Effect[None, SqlError]:
        return record("COMMIT").and_then(commit or fx.void)

    built = sql_client.make(
        driver="test",
        acquirer=acquirer,
        compiler=st.make_compiler_sqlite(),
        prepare_transaction_controls=prepare_transaction_controls,
        commit="COMMIT" if commit is None else recorded_commit,
    )

    def body():
        sql = yield from built
        service = yield from reactivity.Reactivity()
        return _Client(sql, service, calls)

    return fx.gen(body).pipe(fx.provide(reactivity.layer))


@testing.effect
def test_interrupts_a_queued_transaction_before_the_connection_is_released():
    """interrupts a queued transaction before the connection is released without starting its body"""  # noqa: E501
    semaphore = fx.Semaphore(1)
    entered = fx.Deferred[None]()
    release = fx.Deferred[None]()
    interrupted = fx.Deferred[None]()
    lease = fx.uninterruptible_mask(
        lambda restore: restore(semaphore.take(1)).and_then(
            fx.add_finalizer(lambda _: semaphore.release(1))
        )
    )
    client = yield from _make_client(acquire=lease)
    sql = client.sql
    holder = yield from sql.with_transaction(entered.succeed(None).and_then(release.wait())).fork()
    yield from entered.wait()

    queued = yield from sql.with_transaction(client.record("queued body")).fork(
        start_immediately=True
    )
    interrupting = yield from queued.interrupt().and_then(interrupted.succeed(None)).fork()
    yield from fx.yield_now()
    interrupted_before_release = yield from interrupted.is_done()

    # Unblock both fibers before asserting, so the regression fails rather than hanging.
    yield from release.succeed(None)
    yield from holder.join()
    yield from interrupting.join()
    ex = yield from queued.await_exit()
    assert isinstance(ex, fx.Failure)
    assert ex.cause.has_interrupts
    assert "queued body" not in client.calls

    # A cancelled waiter must not retain the connection or its permit.
    yield from sql.with_transaction(client.record("reused"))
    assert interrupted_before_release, (
        "interruption must complete while the holder still owns the connection"
    )
    assert client.calls == ["BEGIN", "COMMIT", "release", "BEGIN", "reused", "COMMIT", "release"]


@testing.effect
def test_starts_only_top_level_transactions_with_the_begin_transaction_statement_unprepared():
    """starts only top-level transactions with the BeginTransaction statement, unprepared"""
    client = yield from _make_client(prepare_transaction_controls=True)
    sql = client.sql

    yield from sql.with_transaction(
        sql.with_transaction(fx.void).pipe(
            fx.provide_service(sql_client.BeginTransaction, "BEGIN READ ONLY")
        )
    ).pipe(fx.provide_service(sql_client.BeginTransaction, "BEGIN ISOLATION LEVEL SERIALIZABLE"))
    yield from sql.with_transaction(fx.void)

    assert client.calls == [
        "BEGIN ISOLATION LEVEL SERIALIZABLE",
        "prepared(SAVEPOINT effect_sql_1)",
        "prepared(COMMIT)",
        "release",
        "prepared(BEGIN)",
        "prepared(COMMIT)",
        "release",
    ]


# --- makeWithTransaction ----------------------------------------------------------------


@testing.effect
def test_recovers_a_failed_commit_with_catch_tag_after_successful_cleanup():
    """recovers a failed commit with catchTag after successful cleanup"""
    commit_error = _sql_error("commit rejected")
    harness = _make_harness(commit=lambda: fx.fail(commit_error), on_commit_failure=lambda: fx.void)

    ex = yield from (
        harness.with_transaction(fx.succeed("body")).pipe(fx.catch_tag(SqlError, fx.succeed)).exit()
    )

    assert ex == fx.Success(commit_error)
    assert harness.calls == [
        "acquireConnection",
        "begin",
        "commit",
        "onCommitFailure",
        "closeConnection",
    ]


@testing.effect
def test_keeps_both_commit_and_cleanup_errors_as_defects_despite_typed_recovery():
    """keeps both commit and cleanup errors as defects despite typed recovery"""
    commit_error = _sql_error("commit rejected")
    cleanup_error = _sql_error("cleanup rejected")
    harness = _make_harness(
        commit=lambda: fx.fail(commit_error), on_commit_failure=lambda: fx.fail(cleanup_error)
    )

    ex = yield from (
        harness.with_transaction(fx.void).pipe(fx.catch_tag(SqlError, lambda _: fx.void)).exit()
    )

    assert isinstance(ex, fx.Failure)
    assert _reasons(ex.cause) == [("die", commit_error), ("die", cleanup_error)]
    assert harness.calls == [
        "acquireConnection",
        "begin",
        "commit",
        "onCommitFailure",
        "closeConnection",
    ]


@testing.effect
def test_propagates_a_failed_begin_as_a_typed_error_without_rolling_back():
    """propagates a failed begin as a typed error without rolling back"""
    begin_error = _sql_error("database is locked")
    harness = _make_harness(begin=begin_error)
    executed: list[bool] = []

    ex = yield from harness.with_transaction(fx.sync(lambda: executed.append(True))).exit()

    _assert_typed_failure(ex, begin_error)
    assert not executed
    assert harness.calls == ["acquireConnection", "begin", "closeConnection"]


@testing.effect
def test_rolls_back_when_the_wrapped_effect_fails_after_a_successful_begin():
    """rolls back when the wrapped effect fails after a successful begin"""
    harness = _make_harness()

    ex = yield from harness.with_transaction(fx.fail("boom")).exit()

    _assert_typed_failure(ex, "boom")
    assert harness.calls == ["acquireConnection", "begin", "rollback", "closeConnection"]


@testing.effect
def test_propagates_a_failed_savepoint_as_a_typed_error_without_rolling_back():
    """propagates a failed savepoint as a typed error without rolling back"""
    savepoint_error = _sql_error("cannot create savepoint")
    harness = _make_harness(savepoint=savepoint_error)
    executed: list[bool] = []

    ex = yield from harness.with_transaction(
        harness.with_transaction(fx.sync(lambda: executed.append(True)))
    ).exit()

    _assert_typed_failure(ex, savepoint_error)
    assert not executed
    assert harness.calls == [
        "acquireConnection",
        "begin",
        "savepoint(1)",
        "rollback",
        "closeConnection",
    ]


@testing.effect
def test_releases_savepoints_after_nested_transactions_succeed_or_roll_back():
    """releases savepoints after nested transactions succeed or roll back"""
    harness = _make_harness(release_savepoint=True)

    def body():
        yield from harness.with_transaction(fx.void)
        return (yield from harness.with_transaction(fx.fail("boom")).exit())

    ex = yield from harness.with_transaction(fx.gen(body))

    _assert_typed_failure(ex, "boom")
    assert harness.calls == [
        "acquireConnection",
        "begin",
        "savepoint(1)",
        "releaseSavepoint(1)",
        "savepoint(1)",
        "rollbackSavepoint(1)",
        "releaseSavepoint(1)",
        "commit",
        "closeConnection",
    ]


@testing.effect
def test_does_not_release_savepoints_when_the_driver_does_not_opt_in():
    """does not release savepoints when the driver does not opt in"""
    harness = _make_harness()

    result = yield from harness.with_transaction(harness.with_transaction(fx.succeed(1)))

    assert result == 1
    assert harness.calls == [
        "acquireConnection",
        "begin",
        "savepoint(1)",
        "commit",
        "closeConnection",
    ]


@testing.effect
def test_skips_savepoint_release_when_rollback_fails():
    """skips savepoint release when rollback fails"""
    rollback_error = _sql_error("cannot roll back savepoint")
    harness = _make_harness(release_savepoint=True, rollback_savepoint=rollback_error)

    ex = yield from harness.with_transaction(harness.with_transaction(fx.fail("boom"))).exit()

    assert isinstance(ex, fx.Failure)
    assert _reasons(ex.cause) == [("die", "boom"), ("die", rollback_error)]
    assert harness.calls == [
        "acquireConnection",
        "begin",
        "savepoint(1)",
        "rollbackSavepoint(1)",
        "rollback",
        "closeConnection",
    ]


@testing.effect
def test_rolls_back_the_outer_transaction_when_a_savepoint_release_fails():
    """rolls back the outer transaction when a savepoint release fails"""
    release_error = _sql_error("cannot release savepoint")
    harness = _make_harness(release_savepoint=release_error)

    ex = yield from harness.with_transaction(harness.with_transaction(fx.void)).exit()

    assert isinstance(ex, fx.Failure)
    assert _reasons(ex.cause) == [("die", release_error)]
    assert harness.calls == [
        "acquireConnection",
        "begin",
        "savepoint(1)",
        "releaseSavepoint(1)",
        "rollback",
        "closeConnection",
    ]


@testing.effect
def test_passes_the_begin_transaction_statement_to_begin():
    """passes the BeginTransaction statement to begin"""
    harness = _make_harness()

    yield from harness.with_transaction(fx.void)
    yield from harness.with_transaction(fx.void).pipe(
        fx.provide_service(sql_client.BeginTransaction, "BEGIN READ ONLY")
    )

    assert [call for call in harness.calls if call.startswith("begin")] == [
        "begin",
        "begin(BEGIN READ ONLY)",
    ]


@testing.effect
def test_commits_and_returns_the_value_when_the_wrapped_effect_succeeds():
    """commits and returns the value when the wrapped effect succeeds"""
    harness = _make_harness()

    result = yield from harness.with_transaction(fx.succeed(1))

    assert result == 1
    assert harness.calls == ["acquireConnection", "begin", "commit", "closeConnection"]


@testing.effect
def test_replays_the_whole_transaction_when_effect_retry_recovers_a_serialization_failure():
    """replays the whole transaction when Effect.retry recovers a serialization failure at COMMIT"""
    commits = [0]

    def commit() -> fx.Effect[None, SqlError]:
        commits[0] += 1
        if commits[0] == 1:
            return fx.fail(
                SqlError(
                    reason=SerializationError(
                        cause=Exception("40001"), message="serialization failure"
                    )
                )
            )
        return fx.void

    client = yield from _make_client(commit=fx.suspend(commit))
    sql = client.sql

    def retryable(error: object) -> bool:
        return isinstance(error, SqlError) and isinstance(
            error.reason, SerializationError | DeadlockError
        )

    result = yield from (
        sql.with_transaction(client.record("body").and_then(client.after("1").as_("body")))
        .pipe(fx.provide_service(sql_client.BeginTransaction, "BEGIN ISOLATION LEVEL SERIALIZABLE"))
        .retry(while_=retryable, times=5)
    )

    assert result == "body"
    assert client.calls == [
        "BEGIN ISOLATION LEVEL SERIALIZABLE",
        "body",
        "COMMIT",
        "release",
        "BEGIN ISOLATION LEVEL SERIALIZABLE",
        "body",
        "COMMIT",
        "release",
        "after(1)",
    ]


# --- makeWithTransaction tracing ---------------------------------------------------------

_ATTR_WAIT_TIME = "db.client.connection.wait_time_ms"


def _recording() -> tuple[Tracer, list[NativeSpan]]:
    """A tracer collecting every span it starts, in order."""
    spans: list[NativeSpan] = []

    def make(request: SpanRequest) -> NativeSpan:
        span = NativeSpan(request)
        spans.append(span)
        return span

    return Tracer(make), spans


def _traced[A, E](effect: fx.Effect[A, E], tracer: Tracer, propagate: bool) -> fx.Effect[A, E]:
    return effect.with_tracer(tracer).pipe(fx.provide_service(st.SpanPropagationEnabled, propagate))


def _status(span: NativeSpan) -> str:
    return "Ended" if isinstance(span.status, Ended) else "Started"


@testing.effect
def test_traces_each_transaction_control_as_a_client_span_of_its_transaction_level():
    """traces each transaction control as a client span of its transaction level"""
    harness = _make_harness(release_savepoint=True, span_attributes=(("db.namespace", "app"),))
    tracer, spans = _recording()
    during_body: list[tuple[str, str]] = []

    def body():
        during_body.extend((span.name, _status(span)) for span in spans)
        yield from harness.with_transaction(fx.void)
        yield from harness.with_transaction(fx.fail("boom")).exit()

    yield from _traced(harness.with_transaction(fx.gen(body)), tracer, True)

    # BEGIN has ended before the body runs, and COMMIT only starts after it.
    assert during_body == [("sql.transaction", "Started"), ("BEGIN app", "Ended")]
    level = {"db.namespace": "app"}

    def control(operation: str) -> dict[str, object]:
        return {**level, "db.operation.name": operation}

    def parent_index(span: NativeSpan) -> int:
        return -1 if span.parent is None else spans.index(cast("NativeSpan", span.parent))

    assert [(s.name, parent_index(s), s.kind, dict(s.attributes)) for s in spans] == [
        ("sql.transaction", -1, "internal", {**level, _ATTR_WAIT_TIME: 0}),
        ("BEGIN app", 0, "client", control("BEGIN")),
        ("sql.transaction", 0, "internal", level),
        ("SAVEPOINT app", 2, "client", control("SAVEPOINT")),
        ("RELEASE SAVEPOINT app", 2, "client", control("RELEASE SAVEPOINT")),
        ("sql.transaction", 0, "internal", level),
        ("SAVEPOINT app", 5, "client", control("SAVEPOINT")),
        ("ROLLBACK TO SAVEPOINT app", 5, "client", control("ROLLBACK TO SAVEPOINT")),
        ("RELEASE SAVEPOINT app", 5, "client", control("RELEASE SAVEPOINT")),
        ("COMMIT app", 0, "client", control("COMMIT")),
    ]


@testing.effect
def test_ends_each_control_span_with_its_own_exit_when_the_body_or_commit_fails():
    """ends each control span with its own exit when the body or COMMIT fails"""

    def exits(spans: list[NativeSpan]) -> list[tuple[str, object]]:
        return [
            (span.name, span.status.exit if isinstance(span.status, Ended) else None)
            for span in spans
        ]

    rolled_back, rolled_back_spans = _recording()
    yield from _traced(_make_harness().with_transaction(fx.fail("boom")), rolled_back, True).exit()
    assert exits(rolled_back_spans) == [
        ("sql.transaction", fx.exit.fail("boom")),
        ("BEGIN", fx.exit.void),
        ("ROLLBACK", fx.exit.void),
    ]

    commit_error = _sql_error("commit rejected")
    failed_commit, failed_commit_spans = _recording()
    ex = yield from _traced(
        _make_harness(
            commit=lambda: fx.fail(commit_error), on_commit_failure=lambda: fx.void
        ).with_transaction(fx.void),
        failed_commit,
        True,
    ).exit()
    _assert_typed_failure(ex, commit_error)
    assert exits(failed_commit_spans) == [
        ("sql.transaction", fx.exit.fail(commit_error)),
        ("BEGIN", fx.exit.void),
        ("COMMIT", fx.exit.fail(commit_error)),
        ("ROLLBACK", fx.exit.void),
    ]


@testing.effect
def test_traces_controls_without_span_propagation_but_records_no_wait_time_or_events():
    """traces controls without span propagation, but records no wait time or events, and none without tracing"""  # noqa: E501
    harness = _make_harness()

    unpropagated, unpropagated_spans = _recording()
    yield from _traced(harness.with_transaction(fx.void), unpropagated, False)
    disabled, disabled_spans = _recording()
    yield from _traced(harness.with_transaction(fx.void), disabled, True).pipe(
        fx.provide_service(TracerEnabled, False)
    )

    assert [(s.name, dict(s.attributes), list(s.events)) for s in unpropagated_spans] == [
        ("sql.transaction", {}, []),
        ("BEGIN", {"db.operation.name": "BEGIN"}, []),
        ("COMMIT", {"db.operation.name": "COMMIT"}, []),
    ]
    assert disabled_spans == []


@testing.effect
def test_acquires_under_the_transaction_span_and_records_the_wait_for_the_connection():
    """acquires under the transaction span and records the wait for the connection, not BEGIN"""
    acquired_under: list[str | None] = []

    def acquire_body():
        span = yield from fx.tracer.current_span().option()
        acquired_under.append(None if span is None else span.value.span_id)
        yield from fx.sleep("30 millis")

    harness = _make_harness(acquire=fx.gen(acquire_body), during_begin=fx.sleep("20 millis"))

    def run(transaction: fx.Effect[None, Any], *, propagate: bool, timing: bool):
        tracer, spans = _recording()
        acquired_under.clear()
        fiber = yield from (
            _traced(transaction, tracer, propagate)
            .pipe(fx.provide_service(TracerTimingEnabled, timing))
            .fork()
        )
        yield from testing.adjust("50 millis")
        yield from fiber.join()
        transactions = [span for span in spans if span.name == "sql.transaction"]
        return (
            [span_id == transactions[0].span_id for span_id in acquired_under],
            [span.attributes.get(_ATTR_WAIT_TIME) for span in transactions],
        )

    nested = harness.with_transaction(harness.with_transaction(fx.void))

    results = [
        (yield from run(harness.with_transaction(fx.void), propagate=True, timing=True)),
        (yield from run(nested.with_span("outer"), propagate=True, timing=True)),
        (yield from run(nested.with_span("outer"), propagate=False, timing=True)),
        (yield from run(nested, propagate=True, timing=False)),
    ]
    assert results == [
        ([True], [30]),
        ([True], [30, None]),
        ([True], [None, None]),
        ([True], [None, None]),
    ]


# --- afterCommit -------------------------------------------------------------------------


class _Caller(Tag[str], key="test/afterCommit/Caller"):
    pass


@testing.effect
def test_runs_callbacks_in_order_with_the_services_they_were_registered_with():
    """runs callbacks in order after commit and release, with the services they were registered with"""  # noqa: E501
    client = yield from _make_client()
    sql = client.sql
    seen: list[object] = []

    def callback():
        seen.append((yield from fx.service_option(sql.transaction_service)))
        seen.append((yield from _Caller()))
        yield from client.record("after(2)")

    def body():
        yield from client.after("1")
        yield from sql.after_commit(fx.gen(callback))
        return "body"

    result = yield from sql.with_transaction(
        fx.gen(body).pipe(fx.provide_service(_Caller, "body"))
    ).pipe(fx.provide_service(_Caller, "caller"))

    assert result == "body"
    assert seen == [None, "body"]
    assert client.calls == ["BEGIN", "COMMIT", "release", "after(1)", "after(2)"]


@testing.effect
def test_runs_nothing_when_the_transaction_rolls_back_or_commit_fails():
    """runs nothing when the transaction rolls back or COMMIT fails"""
    rolled_back = yield from _make_client()
    yield from rolled_back.sql.with_transaction(
        rolled_back.after("1").and_then(fx.fail("boom"))
    ).exit()
    assert rolled_back.calls == ["BEGIN", "ROLLBACK", "release"]

    failed_commit = yield from _make_client(commit=fx.fail(_sql_error("commit rejected")))
    yield from failed_commit.sql.with_transaction(failed_commit.after("1")).exit()
    assert failed_commit.calls == ["BEGIN", "COMMIT", "release"]


@testing.effect
def test_drops_a_rolled_back_savepoints_callbacks_and_keeps_a_committed_savepoints():
    """drops a rolled-back savepoint's callbacks and keeps a committed savepoint's until the outer level ends"""  # noqa: E501
    client = yield from _make_client()
    sql = client.sql

    def dropped():
        yield from client.after("dropped")
        yield from sql.with_transaction(client.after("nested dropped"))
        return (yield from fx.fail("boom"))

    def body():
        yield from client.after("1")
        yield from sql.with_transaction(client.after("2"))
        yield from sql.with_transaction(fx.gen(dropped)).exit()
        yield from client.after("3")

    yield from sql.with_transaction(fx.gen(body))
    assert [call for call in client.calls if call.startswith("after")] == [
        "after(1)",
        "after(2)",
        "after(3)",
    ]

    rolled_back = yield from _make_client()

    def failing():
        yield from rolled_back.sql.with_transaction(rolled_back.after("inner"))
        return (yield from fx.fail("boom"))

    yield from rolled_back.sql.with_transaction(fx.gen(failing)).exit()
    assert "after(inner)" not in rolled_back.calls


@testing.effect
def test_runs_immediately_outside_a_transaction_and_after_the_transaction_service_is_omitted():
    """runs immediately outside a transaction and after the transaction service is omitted"""
    client = yield from _make_client()
    sql = client.sql
    yield from client.after("outside")
    assert client.calls == ["after(outside)"]

    def body():
        # Effect's ``updateContext``: run with the context replaced.
        omit = Context.omit(sql.transaction_service)
        yield from _Locally(client.after("omitted"), omit)
        return (yield from fx.fail("boom"))

    yield from sql.with_transaction(fx.gen(body)).exit()
    assert client.calls == ["after(outside)", "BEGIN", "after(omitted)", "ROLLBACK", "release"]


@testing.effect
def test_runs_callbacks_when_the_fiber_is_interrupted_during_commit_or_the_release_fails():
    """runs callbacks when the fiber is interrupted during COMMIT or the release fails"""
    committing = fx.Deferred[None]()
    resume = fx.Deferred[None]()
    interrupted = yield from _make_client(commit=committing.succeed(None).and_then(resume.wait()))
    fiber = yield from interrupted.sql.with_transaction(interrupted.after("1")).fork()
    yield from committing.wait()
    interrupting = yield from fiber.interrupt().fork()
    yield from fx.yield_now()
    yield from resume.succeed(None)
    yield from interrupting.join()
    assert interrupted.calls == ["BEGIN", "COMMIT", "release", "after(1)"]

    failed_release = yield from _make_client(release=fx.die(RuntimeError("release defect")))
    yield from failed_release.sql.with_transaction(failed_release.after("1")).exit()
    assert failed_release.calls == ["BEGIN", "COMMIT", "release", "after(1)"]


@testing.effect
def test_logs_a_callback_that_dies_and_runs_the_rest():
    """logs a callback that dies and runs the rest"""
    client = yield from _make_client()
    sql = client.sql
    logged: list[str] = []
    logger = fx.Logger.make(lambda options: logged.append(options.cause.pretty()))

    def body():
        yield from sql.after_commit(fx.die(RuntimeError("callback defect")))
        yield from client.after("3")
        return "body"

    result = yield from sql.with_transaction(fx.gen(body)).pipe(
        fx.provide(fx.logger.layer([logger]))
    )

    assert result == "body"
    assert "after(3)" in client.calls
    assert len(logged) == 1
    assert "callback defect" in logged[0]


@testing.effect
def test_dies_when_a_detached_fiber_registers_after_the_transaction_has_ended():
    """dies when a detached fiber registers after the transaction has ended"""
    client = yield from _make_client()
    sql = client.sql
    register = fx.Deferred[None]()
    late = yield from sql.with_transaction(
        register.wait().and_then(client.after("late")).fork_daemon()
    )
    yield from register.succeed(None)
    ex = yield from late.await_exit()
    assert isinstance(ex, fx.Failure)
    assert "the transaction has already ended" in ex.cause.pretty()

    entered = fx.Deferred[None]()
    register_nested = fx.Deferred[None]()

    def inner():
        yield from entered.succeed(None)
        yield from register_nested.wait()
        yield from client.after("late nested")

    def outer():
        child = yield from sql.with_transaction(fx.gen(inner)).fork_daemon()
        yield from entered.wait()
        return child

    nested = yield from sql.with_transaction(fx.gen(outer))
    yield from register_nested.succeed(None)
    nested_exit = yield from nested.await_exit()
    assert isinstance(nested_exit, fx.Failure)
    assert "the transaction has already ended" in nested_exit.cause.pretty()
    assert not any(call.startswith("after") for call in client.calls)


# --- Reactivity.mutation -----------------------------------------------------------------


@testing.effect
def test_invalidates_once_the_outermost_transaction_commits_dropping_rolled_back_work():
    """invalidates once the outermost transaction commits, dropping rolled-back work"""
    client = yield from _make_client()
    sql = client.sql
    calls = client.calls
    for key in ("users", "dropped"):
        client.reactivity.register_unsafe([key], lambda key=key: calls.append(f"invalidate({key})"))

    def nested():
        yield from sql.with_transaction(reactivity.mutation(sql("UPDATE users"), ["users"]))
        yield from sql.with_transaction(
            reactivity.mutation(sql("UPDATE dropped"), ["dropped"]).and_then(fx.fail("boom"))
        ).exit()
        assert "invalidate(users)" not in calls

    def body():
        yield from sql.with_transaction(
            reactivity.mutation(sql("UPDATE users"), ["users"]).and_then(fx.fail("boom"))
        ).exit()
        assert "invalidate(users)" not in calls
        yield from sql.with_transaction(fx.gen(nested))

    yield from fx.gen(body).pipe(fx.provide_service(reactivity.Reactivity, client.reactivity))

    assert calls[-3:] == ["COMMIT", "release", "invalidate(users)"]
    assert "invalidate(dropped)" not in calls
