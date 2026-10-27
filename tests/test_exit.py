"""Exit helpers that Exit.test.ts does not cover (Exit.ts is the spec)."""

from pyfect import exit
from pyfect.cause import Cause, Die, Fail, Interrupt
from pyfect.exit import Exit, Failure, Success

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
