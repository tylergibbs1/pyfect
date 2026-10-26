"""TaggedError: structural equality, message and cause, like Effect's
``Data.TaggedError``."""

from dataclasses import dataclass

import pytest

import pyfect as fx


@dataclass
class NotFound(fx.TaggedError):
    key: str


@dataclass
class Forbidden(fx.TaggedError):
    key: str


class Boom(fx.TaggedError):
    pass


class Bang(fx.TaggedError):
    pass


@dataclass
class WithMessage(fx.TaggedError):
    message: str
    cause: BaseException | None = None


def test_dataclass_errors_compare_and_hash_by_fields():
    """Effect Data.test.ts "structural equality via Equal.equals" and
    "not equal when fields differ"."""
    assert NotFound("x") == NotFound("x")
    assert NotFound("x") != NotFound("y")
    assert hash(NotFound("x")) == hash(NotFound("x"))
    assert NotFound("x") in frozenset([NotFound("x")])


def test_plain_errors_compare_and_hash_by_args():
    assert Boom() == Boom()
    assert Boom("a") == Boom("a")
    assert Boom("a") != Boom("b")
    assert hash(Boom()) == hash(Boom())


def test_different_tags_are_not_equal():
    """Effect Data.test.ts "different tags produce non-equal errors"."""
    assert NotFound("x") != Forbidden("x")
    assert Boom() != Bang()


def test_subclass_of_a_dataclass_error_is_a_different_tag():
    @dataclass
    class Sub(NotFound):
        pass

    assert Sub("x") != NotFound("x")
    assert Sub("x") == Sub("x")
    assert hash(Sub("x")) == hash(Sub("x"))


def test_an_explicit_eq_is_kept():
    class Never(fx.TaggedError):
        def __eq__(self, other: object) -> bool:
            return False

        __hash__ = fx.TaggedError.__hash__

    assert Never() != Never()


def test_message_field_is_the_string_form():
    """Effect Data.test.ts Error "assigns fields": ``e.message`` is the
    message argument."""
    assert str(WithMessage("not found")) == "not found"


def test_cause_field_sets_dunder_cause():
    inner = ValueError("inner")
    e = WithMessage("boom", inner)
    assert e.__cause__ is inner
    assert WithMessage("boom").__cause__ is None


def test_cause_chain_shows_in_tracebacks():
    import traceback

    try:
        raise WithMessage("outer", ValueError("inner"))
    except WithMessage as e:
        rendered = "".join(traceback.format_exception(e))
    assert "ValueError: inner" in rendered
    assert "direct cause" in rendered


def test_errors_without_message_still_list_fields():
    assert str(NotFound("k")) == "key='k'"


def test_errors_with_message_and_cause_compare_structurally():
    inner = ValueError("inner")
    assert WithMessage("a", inner) == WithMessage("a", inner)
    assert WithMessage("a") != WithMessage("b")


@pytest.mark.parametrize("error", [NotFound("k"), Boom("x")])
def test_exit_code_defaults_to_one(error: fx.TaggedError):
    assert error.exit_code == 1


def test_message_slot_is_the_string_form():
    """A ``slots=True`` dataclass keeps ``message`` in a slot, not ``__dict__``."""

    @dataclass(slots=True)
    class Slotted(fx.TaggedError):
        message: str

    assert str(Slotted("hello")) == "hello"


def test_absent_cause_keeps_the_implicit_exception_context():
    """Only a cause that is set replaces ``__context__`` in tracebacks: an
    error raised while handling another, with ``cause=None``, still shows
    "During handling of the above exception"."""
    import traceback

    try:
        try:
            raise KeyError("first")
        except KeyError:
            raise WithMessage("second")  # noqa: B904
    except WithMessage as e:
        rendered = "".join(traceback.format_exception(e))
    assert "During handling of the above exception" in rendered


def test_clearing_the_cause_clears_dunder_cause():
    e = WithMessage("boom", ValueError("inner"))
    e.cause = None
    assert e.__cause__ is None
    assert not e.__suppress_context__


def test_subclass_inherits_an_explicit_eq():
    class AllEqual(fx.TaggedError):
        def __eq__(self, other: object) -> bool:
            return isinstance(other, AllEqual)

        __hash__ = fx.TaggedError.__hash__

    class Child(AllEqual):
        pass

    assert Child("a") == Child("b")
