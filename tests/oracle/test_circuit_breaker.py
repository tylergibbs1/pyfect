"""Ports of Effect's ``test/persistence/CircuitBreaker.test.ts``: the
``CircuitBreakerTest`` suite (``_circuit_breaker_suite``) on
``layer_store_memory`` with ``testing.adjust``, then the file's own
titles, plus the trip policy validation of ``CircuitBreaker.ts``.

Each test's docstring is the Effect test title. Durations are seconds.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

import pytest

import pyfect as fx
from pyfect import testing
from pyfect.cause import Cause, Die
from pyfect.duration import Seconds
from pyfect.exit import Failure, Success
from pyfect.persistence import circuit_breaker as cb
from pyfect.result import Ok

from . import _circuit_breaker_suite as suite


def _memory(body: suite.Body, *, idle: float = 3600) -> None:
    testing.run_test(
        fx.scoped(fx.gen(lambda: body(lambda seconds: testing.adjust(Seconds(seconds))))).pipe(
            fx.provide(cb.layer_store_memory(idle_time_to_live=Seconds(idle)))
        )
    )


@pytest.mark.parametrize(("title", "body"), suite.ALL, ids=suite.IDS)
def test_circuit_breaker_memory(title: str, body: suite.Body) -> None:
    """CircuitBreaker (memory) / ${title}"""
    _memory(body, idle=0.4 if body.__name__ in suite.IDLE else 3600)


# --- CircuitBreaker -------------------------------------------------------------------

_STORE_ERROR = cb.CircuitBreakerError(
    reason=cb.CircuitBreakerStoreError(message="store unavailable")
)


def _memory_store_with(**override: Any) -> fx.Layer[cb.CircuitBreakerStore]:
    def build(store: cb.CircuitBreakerStoreService) -> cb.CircuitBreakerStoreService:
        return replace(store, **override)

    return fx.layer.effect(cb.CircuitBreakerStore, cb.CircuitBreakerStore().map(build)).pipe(
        fx.provide(cb.layer_store_memory())
    )


class _Reports:
    def __init__(self) -> None:
        self.reports: list[tuple[fx.logger.Severity, Cause[object]]] = []

    def layer(self) -> fx.Layer[Any]:
        def record(options: Any) -> None:
            if options.log_level in {fx.LogLevel.WARN, fx.LogLevel.ERROR}:
                self.reports.append((options.log_level, options.cause))

        return fx.logger.layer([fx.Logger.make(record)])


def _run(effect: fx.Effect[Any, Any, Any], *layers: fx.Layer[Any, Any, Any]) -> None:
    for layer in layers:
        effect = effect.pipe(fx.provide(layer))
    testing.run_test(fx.scoped(effect))


def _unavailable(*_: object, **__: object) -> fx.Effect[Any, cb.CircuitBreakerError]:
    return fx.fail(_STORE_ERROR)


_UNAVAILABLE_ADMIT = {"admit": _unavailable}


def test_allow_an_admit_outage_runs_the_call_unrecorded_and_reports_the_cause() -> None:
    """onStoreError / allow: an admit outage runs the call unrecorded and reports the cause at
    UnhandledLogLevel"""
    logs = _Reports()

    def body():
        breaker = yield from cb.make(trip_policy=cb.consecutive(1), open_duration="1 minute")
        call = fx.succeed(42).pipe(breaker.execute(key="allow"))
        assert (yield from call) == 42
        assert (yield from call.pipe(fx.provide_service(fx.UnhandledLogLevel, None))) == 42

        # UnhandledLogLevel defaults to Error, and None silences the report.
        assert len(logs.reports) == 1
        level, cause = logs.reports[0]
        assert level == fx.LogLevel.ERROR
        assert cause.find_error() == Ok(_STORE_ERROR)

    _run(fx.gen(body), _memory_store_with(**_UNAVAILABLE_ADMIT), logs.layer())


def test_fail_an_admit_outage_fails_with_store_error_without_running_the_call() -> None:
    """onStoreError / fail: an admit outage fails with CircuitBreakerStoreError without running
    the call"""

    def body():
        breaker = yield from cb.make(
            trip_policy=cb.consecutive(1), open_duration="1 minute", on_store_error="fail"
        )
        ran: list[bool] = []
        error = (
            yield from fx.sync(lambda: ran.append(True)).pipe(breaker.execute(key="fail")).flip()
        )
        assert not ran
        assert isinstance(error, cb.CircuitBreakerError)
        assert isinstance(error.reason, cb.CircuitBreakerStoreError)

    _run(fx.gen(body), _memory_store_with(**_UNAVAILABLE_ADMIT))


def test_a_failed_record_never_replaces_the_result() -> None:
    """onStoreError / a failed record never replaces the result"""
    logs = _Reports()

    def body():
        breaker = yield from cb.make(
            trip_policy=cb.consecutive(1), open_duration="1 minute", on_store_error="fail"
        )
        success = yield from fx.succeed(42).pipe(breaker.execute(key="record"))
        failure = yield from fx.fail("boom").pipe(breaker.execute(key="record")).flip()
        assert success == 42
        assert failure == "boom"
        assert len(logs.reports) == 2

    store = _memory_store_with(record=_unavailable)
    _run(fx.gen(body), store, logs.layer())


def test_a_record_defect_alongside_a_store_failure_still_dies() -> None:
    """onStoreError / a record defect alongside a store failure still dies, whether or not it is
    reported"""
    bug = RuntimeError("bug")

    def body():
        breaker = yield from cb.make(trip_policy=cb.consecutive(1), open_duration="1 minute")
        call = fx.succeed(42).pipe(breaker.execute(key="record-defect")).exit()
        reported = yield from call
        silenced = yield from call.pipe(fx.provide_service(fx.UnhandledLogLevel, None))
        for exit in (reported, silenced):
            assert isinstance(exit, Failure)
            assert any(isinstance(r, Die) and r.defect is bug for r in exit.cause.reasons)

    def record(**_: object) -> fx.Effect[Any, cb.CircuitBreakerError]:
        return fx.fail_cause(fx.cause.fail(_STORE_ERROR) + fx.cause.die(bug))

    store = _memory_store_with(record=record)
    _run(fx.gen(body), store)


def test_a_classifier_defect_records_ignored_and_the_call_dies_with_the_combined_cause() -> None:
    """classify / a classifier defect records Ignored and the call dies with the combined
    cause"""
    thrown_error = RuntimeError("thrown")
    died_error = RuntimeError("died")

    def throwing(_: object) -> cb.Outcome:
        raise thrown_error

    def body():
        breaker = yield from cb.make(trip_policy=cb.consecutive(1), open_duration="1 minute")
        thrown = (
            yield from fx.succeed(1).pipe(breaker.execute(key="defect", classify=throwing)).exit()
        )
        died = yield from (
            fx.fail("boom")
            .pipe(breaker.execute(key="defect", classify=lambda _: fx.die(died_error)))
            .exit()
        )
        assert isinstance(thrown, Failure)
        assert isinstance(died, Failure)
        thrown_die = thrown.cause.find_die()
        assert isinstance(thrown_die, Ok)
        assert thrown_die.value.defect is thrown_error
        assert died.cause.find_error() == Ok("boom")
        died_die = died.cause.find_die()
        assert isinstance(died_die, Ok)
        assert died_die.value.defect is died_error
        assert isinstance((yield from breaker.state("defect")), cb.Closed)

    _run(fx.gen(body), cb.layer_store_memory())


def test_transitions_ends_when_the_breakers_scope_closes() -> None:
    """transitions ends when the breaker's scope closes"""

    def body():
        scope = fx.CloseableScope()
        breaker = yield from cb.make(trip_policy=cb.consecutive(1), open_duration="1 minute").pipe(
            fx.provide_service(fx.Scope, scope)
        )
        transitions = yield from breaker.transitions.run_collect().fork(start_immediately=True)
        yield from fx.fail("boom").pipe(breaker.execute(key="transitions")).ignore()
        yield from scope.close(fx.exit.succeed(None))

        collected = yield from transitions.join()
        assert [(t.from_, t.to) for t in collected] == [("Closed", "Open")]

    _run(fx.gen(body), cb.layer_store_memory())


def test_fences_a_permit_admitted_before_its_key_was_dropped_and_recreated() -> None:
    """memory retention / fences a permit admitted before its key was dropped and recreated"""

    def body():
        breaker = yield from cb.make(trip_policy=cb.consecutive(1), open_duration="1 minute")
        gate = yield from fx.Deferred[None].make()
        admitted = yield from fx.Deferred[None].make()
        stale = yield from (
            admitted.succeed(None)
            .and_then(gate.wait())
            .and_then(fx.fail("boom"))
            .pipe(breaker.execute(key="recreated"))
            .fork()
        )
        yield from admitted.wait()
        yield from testing.adjust("2 minutes")
        yield from fx.void.pipe(breaker.execute(key="recreated"))

        yield from gate.succeed(None)
        yield from stale.await_exit()
        assert isinstance((yield from breaker.state("recreated")), cb.Closed)

    _run(fx.gen(body), cb.layer_store_memory(idle_time_to_live="1 minute"))


# --- trip policies (CircuitBreaker.ts) ------------------------------------------------


@pytest.mark.parametrize("failures", [0, -1, 1.5])
def test_consecutive_rejects_a_failure_count_below_one_or_fractional(failures: Any) -> None:
    """consecutive: failures must be an integer >= 1"""
    with pytest.raises(ValueError, match="failures must be an integer >= 1"):
        cb.consecutive(failures)


@pytest.mark.parametrize(
    ("options", "message"),
    [
        ({"threshold": 1.5}, "threshold must be in"),
        ({"threshold": float("nan")}, "threshold must be in"),
        ({"size": 0}, "size must be an integer >= 1"),
        ({"size": 3, "minimum_calls": 4}, "minimumCalls must be an integer in"),
        ({"minimum_calls": 0}, "minimumCalls must be an integer in"),
    ],
)
def test_rate_validates_its_options(options: dict[str, Any], message: str) -> None:
    """rate: threshold in [0, 1], size >= 1, minimumCalls in [1, size]"""
    with pytest.raises(ValueError, match=message):
        cb.rate(**options)


def test_rate_defaults_to_half_of_the_last_hundred_calls() -> None:
    """rate: threshold 0.5, size 100, minimumCalls size by default"""
    assert cb.rate() == cb.Rate(threshold=0.5, minimum_calls=100, size=100)
    assert isinstance(cb.success, cb.SuccessOutcome)
    assert isinstance(Success(1), Success)
