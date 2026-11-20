"""``interpreter_pool``: pure functions in subinterpreters, results and failures
back as an ``Exit``, interruption abandoning the call (Python-only: Effect has
no interpreters to run work on)."""

import importlib
import operator
import subprocess
import sys
import textwrap
import threading
from pathlib import Path
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
        exit_ = yield from fiber.await_exit()
        # the interrupt returned while the call still waits; releasing the layer waits for it
        yield from fx.sync(lambda: gate.put(None))
        return exit_

    ex = _run(program)
    assert isinstance(ex, Success)
    assert ex.value.has_interrupts


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


def _interpreter_ids() -> set[int]:
    return {interpreter.id for interpreter in _interpreters().list_all()}


@needs_interpreters
def test_releasing_the_layer_closes_every_idle_interpreter() -> None:
    before = _interpreter_ids()
    created: set[int] = set()

    @fx.gen
    def program():
        calls = [interpreter_pool.call(operator.add, i, 1) for i in range(4)]
        sums = yield from fx.all(*calls, concurrency=4)
        created.update(_interpreter_ids() - before)
        return sums

    assert _run(program, size=4) == Success((1, 2, 3, 4))
    assert created
    assert not created & _interpreter_ids()


@needs_interpreters
def test_releasing_the_layer_waits_for_an_abandoned_call_to_return() -> None:
    gate = _interpreters().create_queue()
    before = _interpreter_ids()
    created: set[int] = set()

    @fx.gen
    def program():
        fiber = yield from interpreter_pool.call(_waits_then_returns, gate, 1).fork()
        yield from fx.sleep("50 millis")
        created.update(_interpreter_ids() - before)
        yield from fiber.interrupt()
        # the abandoned call returns only after the run has started releasing the layer
        threading.Timer(0.1, gate.put, (None,)).start()

    assert isinstance(_run(program), Success)
    assert created
    assert not created & _interpreter_ids()


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


# A script run as `python script.py`, its functions in `__main__`, written as the docs'
# snippets are: top-level code, no `if __name__ == "__main__":` guard unless a test adds one.
# It prints, per call, the exit's value or its reason's type and message.
SCRIPT_HEAD = """
import pyfect as fx
from pyfect import interpreter_pool
from pyfect.cause import Die
from pyfect.exit import Success

FACTOR = 2


def double(x: int) -> int:
    return x * FACTOR


def triple(x: int) -> int:
    return x * 3


def show(eff):
    ex = fx.run_blocking_exit(eff.pipe(fx.provide(interpreter_pool.layer(size=1))))
    if isinstance(ex, Success):
        print("value", ex.value)
        return
    [reason] = ex.cause.reasons
    error = reason.defect if isinstance(reason, Die) else reason.error
    print("die" if isinstance(reason, Die) else "fail", type(error).__name__, str(error))
"""

HANG_AFTER = 3.5
"""Seconds a script may take: one runs in about 1 s, and the hang it detects never ends."""


def _run_script(tmp_path: Path, body: str) -> list[str]:
    script = tmp_path / "main_script.py"
    script.write_text(SCRIPT_HEAD + textwrap.dedent(body))
    try:
        done = subprocess.run(
            [sys.executable, str(script)],
            capture_output=True,
            text=True,
            timeout=HANG_AFTER,
            cwd=tmp_path,
            check=False,
        )
    except subprocess.TimeoutExpired as hung:
        pytest.fail(f"the script hung for {HANG_AFTER} s; stderr: {hung.stderr!r}")
    assert done.returncode == 0, done.stdout + done.stderr
    assert not done.stderr, done.stderr
    return done.stdout.splitlines()


@needs_interpreters
def test_calling_a_function_of_an_unguarded_script_that_reads_globals_dies_at_once(
    tmp_path: Path,
) -> None:
    # CPython finds `double` by re-running the script in the subinterpreter, which reaches the
    # script's own run there: that run dies at once, and so does the call.
    lines = _run_script(
        tmp_path,
        """
        show(interpreter_pool.call(double, 21))
        show(interpreter_pool.try_call(double, 21))
        """,
    )
    assert len(lines) == 2
    for line in lines:
        assert line.startswith("die MainScriptRerunError "), line
        assert 'if __name__ == "__main__":' in line
        assert "importable module" in line
        assert "double" in line


@needs_interpreters
def test_an_unguarded_script_can_call_a_lambda_or_a_function_reading_no_globals(
    tmp_path: Path,
) -> None:
    lines = _run_script(
        tmp_path,
        """
        show(interpreter_pool.call(triple, 7))
        show(interpreter_pool.call(lambda x: x + 1, 41))
        """,
    )
    assert lines == ["value 21", "value 42"]


@needs_interpreters
def test_a_guarded_script_can_call_its_own_function_reading_globals(tmp_path: Path) -> None:
    lines = _run_script(
        tmp_path,
        """
        if __name__ == "__main__":
            show(interpreter_pool.call(double, 21))
        """,
    )
    assert lines == ["value 42"]


@needs_interpreters
def test_a_lambda_reading_a_global_cannot_cross(tmp_path: Path) -> None:
    lines = _run_script(tmp_path, "show(interpreter_pool.call(lambda x: x * FACTOR, 21))\n")
    [line] = lines
    assert line.startswith("die NotShareableError "), line


@needs_interpreters
def test_an_observer_of_a_new_interpreter_cannot_end_it_under_the_pool(tmp_path: Path) -> None:
    # concurrent.interpreters keeps one Interpreter object per id, and create() ends the
    # interpreter when the references those objects hold drop to zero. list_all() on another
    # thread, between create()'s making the interpreter and taking its own reference, makes that
    # object first, and create() hands it back without a reference of its own. When the
    # observer's copy is dropped (CI: the program's list_all() while a worker started), its
    # __del__ -> _decref ended the interpreter under the idle worker: the next call and the
    # release hung. The script makes that drop at a known moment instead of racing for it.
    lines = _run_script(
        tmp_path,
        """
        import operator
        from concurrent import interpreters

        import _interpreters

        real_create = _interpreters.create
        listed = []


        def create_while_listed(*args, **kwargs):
            new = real_create(*args, **kwargs)
            listed.extend(found for found in interpreters.list_all() if found.id == new)
            return new


        _interpreters.create = create_while_listed


        @fx.gen
        def program():
            first = yield from interpreter_pool.call(operator.add, 1, 2)
            [observed] = listed
            observed._decref()  # what its __del__ does once the observer drops it
            second = yield from interpreter_pool.call(operator.add, 3, 4)
            return first, second


        show(program)
        print("left", len(interpreters.list_all()) - 1)
        """,
    )
    assert lines == ["value (3, 7)", "left 0"]


@needs_interpreters
def test_a_worker_that_cannot_close_its_interpreter_fails_the_release(tmp_path: Path) -> None:
    # Something else closed the pool's interpreter: the worker's own close() raises, and the
    # release dies with that error instead of waiting forever for the worker it lost.
    lines = _run_script(
        tmp_path,
        """
        import operator
        from concurrent import interpreters


        @fx.gen
        def program():
            yield from interpreter_pool.call(operator.add, 1, 2)
            main = interpreters.get_main().id
            for interpreter in interpreters.list_all():
                if interpreter.id != main:
                    interpreter.close()


        show(program)
        """,
    )
    [line] = lines
    assert line.startswith("die InterpreterNotFoundError "), line
