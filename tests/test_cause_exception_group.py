"""A cause as an exception group: ``Cause.to_exception_group()`` and the opt-in
``run.unwrap_group``, which raises one for a cause holding several errors and
exactly what ``unwrap`` raises otherwise. ``unwrap`` and the run functions are
unchanged."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import pytest

import pyfect as fx
from pyfect import cause as fx_cause
from pyfect.cause import Cause, Die, EmptyCauseError, Fail, Interrupt, Interrupted, UnhandledError
from pyfect.errors import TaggedError
from pyfect.run import unwrap, unwrap_group


@dataclass(eq=False)
class NotFound(TaggedError):
    key: str


class Boom(Exception):
    pass


def raised_by(f: Callable[[], object]) -> BaseException:
    with pytest.raises(BaseException) as info:
        f()
    return info.value


def grouped(f: Callable[[], object]) -> tuple[Exception, ...]:
    """What ``f`` raises, which must be an ``ExceptionGroup``."""
    with pytest.raises(ExceptionGroup) as info:
        f()
    group: ExceptionGroup[Exception] = info.value
    return group.exceptions


def test_a_cause_of_several_errors_is_a_group_of_each_in_order() -> None:
    first, second = NotFound("a"), Boom("finalizer")
    group = Cause((Fail(first), Die(second))).to_exception_group()
    assert type(group) is ExceptionGroup
    assert group.exceptions == (first, second)
    assert group.message == "2 errors"
    assert Cause((Fail(first),)).to_exception_group("lookup").message == "lookup"


def test_the_group_holds_pretty_errors() -> None:
    cause: Cause[object] = Cause((Fail("not an exception"), Interrupt(3), Die(Boom("x"))))
    unhandled, boom = cause.to_exception_group().exceptions
    # The interruption beside errors is left out, as pretty_errors leaves it out.
    assert isinstance(unhandled, UnhandledError)
    assert unhandled.error == "not an exception"
    assert boom is cause.defects[0]
    [interrupted] = fx_cause.interrupt(3).to_exception_group().exceptions
    assert isinstance(interrupted, Interrupted)
    [empty] = fx_cause.empty.to_exception_group().exceptions
    assert isinstance(empty, EmptyCauseError)


def test_a_base_exception_makes_a_base_exception_group() -> None:
    group = Cause((Die(KeyboardInterrupt()), Die(Boom("x")))).to_exception_group()
    assert type(group) is BaseExceptionGroup


def test_unwrap_group_raises_a_failed_finalizer_beside_the_failure() -> None:
    error, finalizer = NotFound("k"), Boom("release")
    ex = fx.run_sync_exit(fx.fail(error).ensuring(fx.die(finalizer)))
    assert grouped(lambda: unwrap_group(ex)) == (error, finalizer)

    caught: list[tuple[str, tuple[BaseException, ...]]] = []
    try:
        unwrap_group(ex)
    except* NotFound as found:
        caught.append(("found", found.exceptions))
    except* Boom as released:
        caught.append(("released", released.exceptions))
    assert caught == [("found", (error,)), ("released", (finalizer,))]


def test_unwrap_group_raises_concurrent_failures_together() -> None:
    # The first sibling's failure interrupts the second, whose finalizer fails.
    a, b = Boom("a"), Boom("b")
    ex = fx.run_blocking_exit(
        fx.all(
            fx.yield_now().and_then(fx.die(a)),
            fx.never.ensuring(fx.die(b)),
            concurrency="unbounded",
        )
    )
    assert grouped(lambda: unwrap_group(ex)) == (a, b)


def raise_not_found() -> None:
    raise NotFound("raised")


EXITS: dict[str, Callable[[], fx.Exit[Any, Any]]] = {
    "a typed error": lambda: fx.run_sync_exit(fx.fail(NotFound("k"))),
    "a value that is no exception": lambda: fx.run_sync_exit(fx.fail("missing")),
    "a defect": lambda: fx.run_sync_exit(fx.die(Boom("bug"))),
    "a raised tagged error": lambda: fx.run_sync_exit(fx.sync(raise_not_found)),
    "an interruption": lambda: fx.exit.interrupt(5),
    "an error beside an interruption": lambda: fx.exit.fail_cause(
        Cause((Fail(NotFound("k")), Interrupt(7)))
    ),
}


@pytest.mark.parametrize("name", EXITS)
def test_one_error_raises_exactly_what_unwrap_raises(name: str) -> None:
    by_unwrap = raised_by(lambda: unwrap(EXITS[name]()))
    by_group = raised_by(lambda: unwrap_group(EXITS[name]()))
    assert type(by_group) is type(by_unwrap)
    assert str(by_group) == str(by_unwrap)
    assert getattr(by_group, "__notes__", None) == getattr(by_unwrap, "__notes__", None)


def test_unwrap_still_raises_the_first_error_of_several() -> None:
    error, finalizer = NotFound("k"), Boom("release")
    ex = fx.run_sync_exit(fx.fail(error).ensuring(fx.die(finalizer)))
    assert raised_by(lambda: unwrap(ex)) is error


def test_a_raised_tagged_error_in_a_group_gets_unwraps_hint() -> None:
    ex = fx.run_sync_exit(fx.sync(raise_not_found).ensuring(fx.die(Boom("release"))))
    raised = grouped(lambda: unwrap_group(ex))[0]
    assert isinstance(raised, NotFound)
    assert any("catch_tag never sees it" in note for note in raised.__notes__)
