import sys
from typing import Never

import pytest

import pyfect as fx
from pyfect import interpreter_pool
from pyfect.cause import Die
from pyfect.exit import Failure

pytestmark = pytest.mark.skipif(
    sys.version_info < (3, 14), reason="needs Python 3.14's concurrent.interpreters"
)

RATE = 3


def run[A](eff: fx.Effect[A, Never, interpreter_pool.InterpreterPool]) -> A:
    return fx.run_blocking(eff.pipe(fx.provide(interpreter_pool.layer(size=1))))


def word_count(text: str) -> int:
    # Reads no globals: its code is copied across, wherever it is defined.
    import re

    return len(re.findall(r"\w+", text))


def test_a_function_reading_no_globals_crosses() -> None:
    assert run(interpreter_pool.call(word_count, "one two three")) == 3


def test_a_lambda_reading_no_globals_crosses() -> None:
    assert run(interpreter_pool.call(lambda x: x * 2, 21)) == 42


def test_a_lambda_reading_a_global_does_not() -> None:
    priced = interpreter_pool.call(lambda x: x * RATE, 14)
    ex = fx.run_blocking_exit(priced.pipe(fx.provide(interpreter_pool.layer(size=1))))
    assert isinstance(ex, Failure)
    [reason] = ex.cause.reasons
    assert isinstance(reason, Die)
    assert type(reason.defect).__name__ == "NotShareableError"
