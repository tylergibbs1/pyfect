"""Exit helpers that Exit.test.ts does not cover (Exit.ts is the spec)."""

import pyfect as fx
from pyfect import exit
from pyfect.cause import Cause, Die, Fail, Interrupt
from pyfect.exit import Exit, Failure, Success
from pyfect.option import Some

boom = RuntimeError("boom")


def outcomes() -> tuple[Exit[int, str], Exit[int, str]]:
    return Success(1), exit.fail("e")


def test_map_and_as_void_touch_only_a_success() -> None:
    ok, failed = outcomes()
    assert ok.map(lambda n: n + 1) == Success(2)
    assert failed.map(lambda n: n + 1) is failed
    assert ok.as_void() == Success(None)
    assert failed.as_void() is failed


def test_match_hands_a_failure_its_whole_cause() -> None:
    ok, failed = outcomes()

    def describe(ex: Exit[int, str]) -> str:
        return ex.match(on_failure=lambda c: f"failed {c.failures}", on_success=str)

    assert describe(ok) == "1"
    assert describe(failed) == "failed ('e',)"


def test_guards_tell_success_from_failure() -> None:
    ok, failed = outcomes()
    assert exit.is_success(ok)
    assert not exit.is_success(failed)
    assert exit.is_failure(failed)
    assert not exit.is_failure(ok)


def test_as_void_all_collects_every_failed_reason_in_order() -> None:
    assert exit.as_void_all([]) == Success(None)
    assert exit.as_void_all([Success(1), Success("a")]) == Success(None)
    exits: list[Exit[object, str]] = [
        exit.fail("a"),
        Success(1),
        Failure(Cause((Die(boom), Interrupt(2)))),
        exit.fail("b"),
    ]
    assert exit.as_void_all(exits) == Failure(
        Cause((Fail("a"), Die(boom), Interrupt(2), Fail("b")))
    )


def test_fail_cause_and_void_build_exits() -> None:
    cause: Cause[str] = Cause((Fail("e"), Interrupt(1)))
    assert exit.fail_cause(cause) == Failure(cause)
    assert exit.void == Success(None)


def test_has_fails_dies_and_interrupts_read_a_failures_cause() -> None:
    ok, _ = outcomes()
    mixed: Exit[int, str] = Failure(Cause((Fail("e"), Interrupt(1))))
    died: Exit[int, str] = exit.die(boom)
    assert (ok.has_fails, ok.has_dies, ok.has_interrupts) == (False, False, False)
    assert (mixed.has_fails, mixed.has_dies, mixed.has_interrupts) == (True, False, True)
    assert (died.has_fails, died.has_dies, died.has_interrupts) == (False, True, False)


def test_filters_split_an_exit_into_ok_and_err() -> None:
    ok, failed = outcomes()
    assert ok.filter_success() == fx.Ok(ok)
    assert failed.filter_success() == fx.Err(failed)
    assert ok.filter_value() == fx.Ok(1)
    assert failed.filter_value() == fx.Err(failed)
    assert ok.filter_failure() == fx.Err(ok)
    assert failed.filter_failure() == fx.Ok(failed)
    assert ok.filter_cause() == fx.Err(ok)
    assert isinstance(failed, Failure)
    assert failed.filter_cause() == fx.Ok(failed.cause)


def test_find_error_passes_the_exit_through_when_there_is_no_typed_error() -> None:
    ok, failed = outcomes()
    died: Exit[int, str] = exit.die(boom)
    assert failed.find_error() == fx.Ok("e")
    assert ok.find_error() == fx.Err(ok)
    assert died.find_error() == fx.Err(died)


def test_find_defect_get_success_and_get_cause() -> None:
    ok, failed = outcomes()
    died: Exit[int, str] = exit.die(boom)
    assert died.find_defect() is boom
    assert failed.find_defect() is None
    assert ok.find_defect() is None
    assert ok.get_success() == Some(1)
    assert failed.get_success() is None
    assert ok.get_cause() is None
    assert isinstance(failed, Failure)
    assert failed.get_cause() == Some(failed.cause)
