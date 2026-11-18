"""``interpreter_pool``: pure functions in subinterpreters, results and failures
back as an ``Exit``, interruption abandoning the call (Python-only: Effect has
no interpreters to run work on)."""

import importlib
import operator
import sys
from types import ModuleType
from typing import Any

import pytest

import pyfect as fx
from pyfect import interpreter_pool
from pyfect.cause import Die, Fail
from pyfect.errors import UnknownError
from pyfect.exit import Exit, Failure, Success

needs_interpreters = pytest.mark.skipif(
    sys.version_info < (3, 14), reason="needs Python 3.14's concurrent.interpreters"
)


def _interpreters() -> Any:
    return importlib.import_module("concurrent.interpreters")


def _run[A, E](eff: fx.Effect[A, E, interpreter_pool.InterpreterPool], size: int = 2) -> Exit[A, E]:
    return fx.run_blocking_exit(eff.pipe(fx.provide(interpreter_pool.layer(size))))


# The functions below read no globals, so they cross into a subinterpreter as
# they are, without an import of this file there.


def _raises_value_error(text: str) -> int:
    raise ValueError(text)


def _raises_unpicklable() -> None:
    class Local(Exception):
        pass

    raise Local("cannot cross")


def _waits_then_returns(gate: Any, value: int) -> int:
    gate.get()
    return value


def _marks(marks: Any) -> None:
    marks.put(1)


@needs_interpreters
def test_call_returns_the_function_result() -> None:
    assert _run(interpreter_pool.call(operator.mul, 6, 7)) == Success(42)


@needs_interpreters
def test_a_raised_exception_is_a_defect_with_the_exception_itself() -> None:
    ex = _run(interpreter_pool.call(_raises_value_error, "bad"))
    assert isinstance(ex, Failure)
    [reason] = ex.cause.reasons
    assert isinstance(reason, Die)
    assert isinstance(reason.defect, ValueError)
    assert reason.defect.args == ("bad",)


@needs_interpreters
def test_an_exception_that_cannot_cross_comes_back_as_execution_failed() -> None:
    ex = _run(interpreter_pool.call(_raises_unpicklable))
    assert isinstance(ex, Failure)
    [reason] = ex.cause.reasons
    assert isinstance(reason, Die)
    assert isinstance(reason.defect, _interpreters().ExecutionFailed)
    assert "cannot cross" in str(reason.defect)


@needs_interpreters
def test_try_call_fails_with_an_unknown_error_or_what_catch_makes() -> None:
    ex = _run(interpreter_pool.try_call(_raises_value_error, "bad"))
    assert isinstance(ex, Failure)
    [reason] = ex.cause.reasons
    assert isinstance(reason, Fail)
    assert isinstance(reason.error, UnknownError)
    assert isinstance(reason.error.cause, ValueError)

    caught = _run(interpreter_pool.try_call(_raises_value_error, "bad", catch=str))
    assert caught == fx.run_blocking_exit(fx.fail("bad"))


@needs_interpreters
def test_interrupting_a_running_call_abandons_it_at_once() -> None:
    gate = _interpreters().create_queue()

    @fx.gen
    def program():
        fiber = yield from interpreter_pool.call(_waits_then_returns, gate, 1).fork()
        yield from fx.sleep("50 millis")
        yield from fiber.interrupt()
        return (yield from fiber.await_exit())

    try:
        ex = _run(program)
        assert isinstance(ex, Success)
        assert ex.value.has_interrupts
    finally:
        gate.put(None)  # lets the abandoned call return, so its worker exits


@needs_interpreters
def test_interrupting_a_queued_call_withdraws_it() -> None:
    gate = _interpreters().create_queue()
    marks = _interpreters().create_queue()

    @fx.gen
    def program():
        running = yield from interpreter_pool.call(_waits_then_returns, gate, 1).fork()
        queued = yield from interpreter_pool.call(_marks, marks).fork()
        yield from fx.sleep("50 millis")
        yield from queued.interrupt()
        yield from fx.sync(lambda: gate.put(None))
        return (yield from running.join())

    assert _run(program, size=1) == Success(1)
    assert marks.empty()


@needs_interpreters
def test_releasing_the_layer_closes_every_idle_interpreter() -> None:
    before = len(_interpreters().list_all())
    calls = [interpreter_pool.call(operator.add, i, 1) for i in range(4)]
    assert _run(fx.all(*calls, concurrency=4), size=4) == Success((1, 2, 3, 4))
    assert len(_interpreters().list_all()) == before


@needs_interpreters
def test_a_call_after_the_layer_is_released_dies() -> None:
    @fx.gen
    def kept():
        return (yield from interpreter_pool.InterpreterPool())

    pool = fx.run_blocking(kept.pipe(fx.provide(interpreter_pool.layer(1))))
    ex = fx.run_blocking_exit(pool.call(operator.add, 1, 2))
    assert isinstance(ex, Failure)
    [reason] = ex.cause.reasons
    assert isinstance(reason, Die)
    assert isinstance(reason.defect, interpreter_pool.InterpreterPoolClosedError)


def test_the_layer_dies_where_concurrent_interpreters_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real = importlib.import_module

    def without_interpreters(name: str, package: str | None = None) -> ModuleType:
        if name == "concurrent.interpreters":
            raise ModuleNotFoundError(name)
        return real(name, package)

    monkeypatch.setattr(importlib, "import_module", without_interpreters)
    ex = _run(interpreter_pool.call(operator.add, 1, 2))
    assert isinstance(ex, Failure)
    [reason] = ex.cause.reasons
    assert isinstance(reason, Die)
    assert isinstance(reason.defect, interpreter_pool.InterpretersUnavailableError)


def test_a_pool_needs_at_least_one_interpreter() -> None:
    with pytest.raises(ValueError, match="at least one"):
        interpreter_pool.layer(0)
