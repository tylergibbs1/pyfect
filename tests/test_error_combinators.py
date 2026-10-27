"""Error combinators whose behavior Effect.test.ts doesn't pin directly.

Each follows the Effect v4 implementation named in its docstring.
"""

from dataclasses import dataclass
from typing import Any, Never, TypeIs

import pyfect as fx
from pyfect import testing
from pyfect.cause import Die, Fail, Interrupt, die, fail, from_reasons


@dataclass(eq=False)
class NotFound(fx.TaggedError):
    pass


@dataclass(eq=False)
class Invalid(fx.TaggedError):
    pass


@dataclass(eq=False)
class MissingUser(NotFound):
    pass


DEFECT = RuntimeError("boom")


def _cause(ex: fx.Exit[Any, Any]) -> fx.Cause[Any]:
    assert isinstance(ex, fx.Failure)
    return ex.cause


def test_catch_tag_or_else_does_not_catch_the_handlers_own_failure() -> None:
    """catchTag = catchIf(pred, f, orElse): orElse sees only unmatched errors."""

    def rest(_: Invalid) -> fx.Effect[str]:
        return fx.succeed("or_else")

    source: fx.Effect[Never, NotFound | Invalid] = fx.fail(NotFound())
    eff = source.pipe(fx.catch_tag(NotFound, lambda _: fx.fail(Invalid()), or_else=rest))
    assert _cause(testing.run_test_exit(eff)) == fail(Invalid())


def test_catch_tag_catches_subclasses_of_the_tag() -> None:
    eff = fx.fail(MissingUser()).pipe(fx.catch_tag(NotFound, lambda e: fx.succeed(type(e))))
    assert testing.run_test(eff) is MissingUser


def test_tap_error_tag_with_a_tuple_of_classes() -> None:
    seen: list[object] = []
    for error in (NotFound(), Invalid()):
        eff = fx.fail(error).tap_error_tag(
            (NotFound, Invalid), lambda e: fx.sync(lambda: seen.append(e))
        )
        testing.run_test_exit(eff)
    assert seen == [NotFound(), Invalid()]


def test_flip_swaps_value_and_error_but_not_defects() -> None:
    """flip = matchEffect({ onFailure: succeed, onSuccess: fail })."""
    assert testing.run_test(fx.fail("e").flip()) == "e"
    assert _cause(testing.run_test_exit(fx.succeed(1).flip())) == fail(1)
    assert _cause(testing.run_test_exit(fx.die(DEFECT).flip())) == die(DEFECT)


def test_sandbox_exposes_defects_as_the_typed_error() -> None:
    """sandbox = catchCause(self, fail)."""
    cause = testing.run_test(fx.die(DEFECT).sandbox().flip())
    assert cause == die(DEFECT)
    assert testing.run_test(fx.fail("e").sandbox().catch_all(fx.succeed)) == fail("e")


def test_map_both_maps_each_side_and_a_raising_mapper_is_a_defect() -> None:
    def boom(_: int) -> Never:
        raise DEFECT

    assert testing.run_test_exit(fx.succeed(1).map_both(on_failure=str, on_success=str)) == (
        fx.Success("1")
    )
    assert _cause(testing.run_test_exit(fx.fail(1).map_both(on_failure=str, on_success=str))) == (
        fail("1")
    )
    ex = testing.run_test_exit(fx.succeed(1).map_both(on_failure=str, on_success=boom))
    assert _cause(ex) == die(DEFECT)


def test_or_else_succeed_leaves_defects_alone() -> None:
    assert testing.run_test(fx.fail("e").or_else_succeed(len)) == 1
    assert _cause(testing.run_test_exit(fx.die(DEFECT).or_else_succeed(len))) == die(DEFECT)


def test_eventually_reruns_until_success() -> None:
    attempts = 0

    def attempt() -> fx.Effect[int, str]:
        nonlocal attempts
        attempts += 1
        return fx.succeed(attempts) if attempts == 3 else fx.fail("not yet")

    assert testing.run_test(fx.suspend(attempt).eventually()) == 3


def test_eventually_yields_between_attempts() -> None:
    """eventually = catch(self, () => flatMap(yieldNow, () => eventually(self))):
    other fibers run between attempts."""
    ready = False
    attempts = 0

    def set_ready() -> None:
        nonlocal ready
        ready = True

    def attempt() -> fx.Effect[str, str]:
        nonlocal attempts
        attempts += 1
        if attempts > 100:
            return fx.die(RuntimeError("the other fiber never ran"))
        return fx.succeed("ready") if ready else fx.fail("not yet")

    @fx.gen
    def program():
        yield from fx.sync(set_ready).fork()
        return (yield from fx.suspend(attempt).eventually())

    assert testing.run_test(program) == "ready"


def test_catch_tag_and_catch_if_keep_the_whole_cause_when_nothing_matches() -> None:
    """catchIf re-fails with failCause(cause), not just the error it looked at."""
    cause = from_reasons([Fail(Invalid()), Interrupt(7), Fail(NotFound())])
    source: fx.Effect[Never, NotFound | Invalid] = fx.fail_cause(cause)
    recoveries: list[fx.Effect[object, object]] = [
        source.pipe(fx.catch_tag(MissingUser, lambda _: fx.succeed(1))),
        source.pipe(fx.catch_tag((MissingUser, MissingUser), lambda _: fx.succeed(1))),
        source.pipe(fx.catch_if(_is_missing_user, lambda _: fx.succeed(1))),
        source.catch_if(lambda e: isinstance(e, MissingUser), lambda _: fx.succeed(1)),
    ]
    for eff in recoveries:
        assert _cause(testing.run_test_exit(eff)) == cause


def _is_missing_user(e: object) -> TypeIs[MissingUser]:
    return isinstance(e, MissingUser)


def test_option_keeps_a_present_none_apart_from_a_failure() -> None:
    assert testing.run_test(fx.succeed(None).option()) == fx.Some(None)
    assert testing.run_test(fx.fail("e").option()) is None
    assert _cause(testing.run_test_exit(fx.die(DEFECT).option())) == die(DEFECT)


def test_match_cause_sees_defects() -> None:
    eff = fx.die(DEFECT).match_cause(on_failure=lambda c: c.defects, on_success=lambda _: ())
    assert testing.run_test(eff) == (DEFECT,)


def test_tap_defect_observes_only_defects_and_keeps_the_failure() -> None:
    seen: list[BaseException] = []

    def record(d: BaseException) -> fx.Effect[None]:
        return fx.sync(lambda: seen.append(d))

    assert _cause(testing.run_test_exit(fx.die(DEFECT).tap_defect(record))) == die(DEFECT)
    assert _cause(testing.run_test_exit(fx.fail("e").tap_defect(record))) == fail("e")
    assert seen == [DEFECT]
    failing_tap = fx.die(DEFECT).tap_defect(lambda _: fx.fail("tap"))
    assert _cause(testing.run_test_exit(failing_tap)) == fail("tap")


def test_catch_defect_leaves_typed_errors_alone() -> None:
    assert testing.run_test(fx.die(DEFECT).catch_defect(fx.succeed)) is DEFECT
    eff = fx.fail("e").catch_defect(lambda _: fx.succeed("caught"))
    assert _cause(testing.run_test_exit(eff)) == fail("e")


def test_when_runs_only_on_true() -> None:
    ran: list[int] = []
    eff = fx.sync(lambda: ran.append(1))
    assert testing.run_test(eff.when(fx.succeed(False))) is None
    assert ran == []
    assert testing.run_test(eff.when(fx.succeed(True))) == fx.Some(None)
    assert ran == [1]


def test_filter_or_fail_and_filter_or_else() -> None:
    """filterOrFail fails with NoSuchElementError unless orFailWith is given."""
    ex = testing.run_test_exit(fx.succeed(-1).filter_or_fail(lambda n: n > 0))
    found = _cause(ex).find_fail()
    assert isinstance(found, Fail) and isinstance(found.error, fx.NoSuchElementException)
    assert testing.run_test_exit(fx.succeed(1).filter_or_fail(lambda n: n > 0)) == fx.Success(1)
    ex = testing.run_test_exit(fx.succeed(-1).filter_or_fail(lambda n: n > 0, lambda n: f"bad {n}"))
    assert _cause(ex) == fail("bad -1")
    eff = fx.succeed(-1).filter_or_else(lambda n: n > 0, lambda n: fx.succeed(-n))
    assert testing.run_test(eff) == 1


def test_fail_sync_and_fail_cause_sync_compute_on_each_run() -> None:
    calls = 0

    def make() -> int:
        nonlocal calls
        calls += 1
        return calls

    eff = fx.fail_sync(make)
    assert calls == 0
    assert [_cause(testing.run_test_exit(eff)) for _ in range(2)] == [fail(1), fail(2)]
    cause_eff = fx.fail_cause_sync(lambda: die(DEFECT))
    assert _cause(testing.run_test_exit(cause_eff)) == die(DEFECT)


def test_flatten_runs_the_inner_effect() -> None:
    assert testing.run_test(fx.succeed(fx.succeed(1)).flatten()) == 1
    assert _cause(testing.run_test_exit(fx.succeed(fx.fail("e")).flatten())) == fail("e")


def test_from_optional_fails_only_on_none() -> None:
    """fromNullishOr: only a missing value fails, not a falsy one."""
    assert testing.run_test_exit(fx.from_optional(0)) == fx.Success(0)
    found = _cause(testing.run_test_exit(fx.from_optional(None))).find_fail()
    assert isinstance(found, Fail) and isinstance(found.error, fx.NoSuchElementException)


def test_first_success_of_reads_the_iterable_on_each_run() -> None:
    """firstSuccessOf iterates inside suspend: the iterable is read at run time."""
    effects: list[fx.Effect[int, str]] = []
    eff = fx.first_success_of(effects).or_die()
    effects.extend([fx.fail("e1"), fx.succeed(1)])
    assert testing.run_test(eff) == 1
    effects[1] = fx.succeed(2)
    assert testing.run_test(eff) == 2


def test_first_success_of_stops_at_a_defect() -> None:
    """firstSuccessOf chains with catch, which never recovers a defect."""
    later: list[int] = []
    eff = fx.first_success_of([fx.die(DEFECT), fx.sync(lambda: later.append(1))])
    reasons = _cause(testing.run_test_exit(eff)).reasons
    assert reasons == (Die(DEFECT),)
    assert later == []


def test_unknown_error_reads_as_its_message() -> None:
    error = fx.UnknownError(ValueError("bad"), "An error occurred in try_")
    assert str(error) == "An error occurred in try_"
    assert str(fx.UnknownError(ValueError("bad"))) == "bad"


def test_try_blocking_without_catch_fails_with_unknown_error() -> None:
    thrown = ValueError("blocking")

    def boom() -> int:
        raise thrown

    ex = fx.run_sync_exit(fx.try_blocking(boom))
    assert isinstance(ex, fx.Failure)
    found = ex.cause.find_fail()
    assert isinstance(found, Fail)
    assert isinstance(found.error, fx.UnknownError)
    assert found.error.cause is thrown
    assert found.error.message == "An error occurred in try_blocking"


def test_a_raising_catch_in_try_blocking_is_a_defect() -> None:
    defect = RuntimeError("catch")

    def boom() -> int:
        raise ValueError("blocking")

    def catch(_: Exception) -> Never:
        raise defect

    ex = fx.run_sync_exit(fx.try_blocking(boom, catch))
    assert isinstance(ex, fx.Failure)
    assert ex.cause.find_defect() is defect
