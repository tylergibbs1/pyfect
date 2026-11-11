"""Exactly what ``Cause.pretty`` prints for each kind of error: values that
are no exception (Effect's ``causePrettyError``), errors never raised,
raised errors, cause chains with cycles, span frames and interruptions."""

import re
from decimal import Decimal
from typing import Any

import pytest

import pyfect as fx
from pyfect import cause, exit, scope
from pyfect.context import Context
from pyfect.tracer import InterruptorStackTrace, StackFrame, StackTrace

_OUTER = StackFrame("outer", lambda: None)
_INNER = StackFrame("inner", lambda: None, _OUTER)


@pytest.mark.parametrize(
    ("value", "rendered"),
    [
        # Effect: a falsy value is ``Unknown error: <value>``.
        (0, "Error: Unknown error: 0"),
        ("", "Error: Unknown error: "),
        (None, "Error: Unknown error: None"),
        # A string is the message itself; anything else is its JSON.
        ("oops", "Error: oops"),
        (1, "Error: 1"),
        ({"a": [1, 2]}, 'Error: {"a":[1,2]}'),
    ],
)
def test_a_typed_error_that_is_no_exception_renders_as_effect_makes_an_error_of_it(
    value: object, rendered: str
):
    assert cause.fail(value).pretty() == rendered


def test_unhandled_error_reads_as_the_string_or_the_repr_of_its_value():
    assert str(cause.UnhandledError("went wrong")) == "went wrong"
    assert str(cause.UnhandledError(Decimal("1.5"))) == "Decimal('1.5')"
    assert cause.UnhandledError({"a": 1}).error == {"a": 1}


def test_an_error_never_raised_renders_its_line_and_notes_without_a_trailing_newline():
    error = ValueError("boom")
    error.add_note("first note")
    error.add_note("second note")
    assert cause.fail(error).pretty() == "ValueError: boom\nfirst note\nsecond note"


def test_an_error_never_raised_keeps_its_message_exactly():
    """As Effect's ``${name}: ${message}``: trailing whitespace stays."""
    assert cause.fail(ValueError("boom  ")).pretty() == "ValueError: boom  "


class _Messaged(Exception):
    message = "the message"


def test_only_the_errors_own_line_takes_its_message_attribute():
    """A ``message`` attribute replaces the error's text on its line, not
    the same text in a note."""
    error = _Messaged("zzz")
    error.add_note("zzz twice zzz")
    assert cause.fail(error).pretty() == (
        "test_cause_rendering._Messaged: the message\nzzz twice zzz"
    )


def test_an_error_that_is_its_own_cause_renders_once():
    error = ValueError("a")
    error.__cause__ = error
    assert cause.fail(error).pretty() == "ValueError: a"


def test_a_cycle_deeper_in_the_cause_chain_stops_at_the_repeated_error():
    a, b, c = ValueError("a"), ValueError("b"), ValueError("c")
    a.__cause__, b.__cause__, c.__cause__ = b, c, b
    assert cause.fail(a).pretty() == (
        "ValueError: a {\n  [cause]: ValueError: b {\n    [cause]: ValueError: c\n  }\n}"
    )


def _raise_it() -> None:
    raise ValueError("raised")


def test_a_raised_error_renders_its_traceback_without_a_trailing_newline():
    with pytest.raises(ValueError) as caught:
        _raise_it()
    assert re.fullmatch(
        r"Traceback \(most recent call last\):\n"
        r"(?s:.*)"
        r"  File \".*test_cause_rendering\.py\", line \d+, in _raise_it\n"
        r"    raise ValueError\(\"raised\"\)\n"
        r"ValueError: raised",
        cause.die(caught.value).pretty(),
    )


def test_each_error_is_followed_by_its_frames_and_errors_are_separated_by_a_blank_line():
    traced = cause.fail("x").annotate(Context.make(StackTrace, _INNER))
    assert (traced + cause.die("y")).pretty_stacks() == (
        "Error: x\n    at inner\n    at outer",
        "Error: y",
    )
    assert (traced + cause.die("y")).pretty() == "Error: x\n    at inner\n    at outer\n\nError: y"


def test_interruptions_alone_render_one_error_noting_each_interruptor_and_its_frames():
    interrupted = cause.interrupt(3).annotate(Context.make(InterruptorStackTrace, _INNER))
    assert (interrupted + cause.interrupt()).pretty() == (
        "pyfect.cause.Interrupted: All fibers interrupted without error\n"
        "interrupted by fiber #3\n"
        "    at inner\n"
        "    at outer\n"
        "interrupted externally"
    )


def test_an_interruption_the_runtime_sends_notes_why():
    def program() -> fx.Effect[exit.Exit[None, Any]]:
        closed = scope.CloseableScope()
        return closed.close(exit.void).flat_map(
            lambda _: scope.fork_in(fx.void, closed).flat_map(lambda f: f.await_exit())
        )

    ex = fx.run_sync(program())
    assert isinstance(ex, exit.Failure)
    (note,) = ex.cause.raisable().__notes__
    assert re.fullmatch(
        r"interrupted by fiber #\d+ because the Scope is closed"
        r" \(used after the scope that owns it closed\)",
        note,
    )
