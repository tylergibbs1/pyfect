"""Cause.pretty: what run boundaries and loggers print."""

from dataclasses import dataclass

import pytest

import pyfect as fx
from pyfect import cause


def user_code() -> None:
    raise ValueError("boom")


@dataclass
class Wrapped(fx.TaggedError):
    message: str
    cause: BaseException | None = None


def test_defect_shows_the_raising_function():
    """Effect Cause.test.ts "cuts the stack of a defect at the internal frame
    that called user code": the rendered defect names ``userCode``."""
    ex = fx.run_sync_exit(fx.sync(user_code))
    assert isinstance(ex, fx.Failure)
    rendered = ex.cause.pretty()
    assert "user_code" in rendered
    assert "ValueError: boom" in rendered


def test_typed_exception_error_shows_its_cause_chain():
    with pytest.raises(ValueError) as caught:
        user_code()
    rendered = cause.fail(Wrapped("outer", caught.value)).pretty()
    assert "Wrapped: outer" in rendered
    assert "ValueError: boom" in rendered
    assert "user_code" in rendered


def test_fail_with_a_plain_value_renders_it():
    """Effect Cause.test.ts "renders a Fail cause as a string"."""
    assert "something went wrong" in cause.fail("something went wrong").pretty()


def test_interrupt_only_cause_says_so():
    """Effect Cause.test.ts "returns InterruptError for interrupt-only cause"."""
    rendered = cause.interrupt(3).pretty()
    assert "All fibers interrupted without error" in rendered
    assert "#3" in rendered


def test_empty_cause_renders_a_string():
    """Effect Cause.test.ts "returns a string for empty cause"."""
    assert isinstance(cause.Cause(()).pretty(), str)


def test_a_defect_decoded_from_json_renders_with_the_name_it_was_written_with():
    """A defect that crossed a JSON boundary renders as Effect renders the
    decoded error: ``name: message``, the name it was written with."""
    from pyfect.schema import DecodedDefect, ErrorInstance

    decoded = DecodedDefect(ErrorInstance("cause=boom", name="MalformedMessage"))
    rendered = cause.die(decoded).pretty()
    assert rendered.startswith("MalformedMessage: cause=boom")
