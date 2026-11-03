"""``get_error_exit_code`` and ``get_error_reported`` (Effect's
``Runtime.getErrorExitCode`` / ``getErrorReported``): any value may set
the attribute (Effect: the symbol key on any object); a value of the wrong
type, or none, gives the default (1 and ``True``)."""

from typing import ClassVar

import pytest

import pyfect as fx
from pyfect.run import get_error_exit_code, get_error_reported


class _Coded(Exception):
    exit_code = 3
    error_reported = False


class _Tagged(fx.TaggedError):
    exit_code: ClassVar[int] = 78


class _WrongTypes(Exception):
    exit_code = "3"
    error_reported = 0


@pytest.mark.parametrize(
    ("error", "code", "reported"),
    [
        (_Coded(), 3, False),
        (_Tagged(), 78, True),
        (_WrongTypes(), 1, True),
        (ValueError("x"), 1, True),
        ("a string", 1, True),
        (None, 1, True),
    ],
)
def test_reads_the_attributes_of_any_value(error: object, code: int, reported: bool):
    assert get_error_exit_code(error) == code
    assert get_error_reported(error) is reported


@pytest.mark.parametrize("flag", [True, False])
def test_a_bool_is_not_an_exit_code(flag: bool):
    # Effect checks ``typeof code === "number"``, which a boolean is not.
    class Flagged(Exception):
        exit_code = flag

    assert get_error_exit_code(Flagged()) == 1


def test_default_teardown_reads_the_exit_code_of_any_error():
    assert fx.default_teardown(fx.exit.die(_Coded())) == 3
