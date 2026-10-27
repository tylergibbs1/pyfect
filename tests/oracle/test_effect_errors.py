"""Ports of the error-handling sections of Effect's ``Effect.test.ts``.

Each test's docstring is the Effect test title. Omitted, with the reason:

- ``fromOption`` "from a none with a custom error data-last": Python has one
  call form, ``from_option(option, on_none)``.
- ``match`` "passes only the outcome to handlers": counts JS ``arguments``.
- ``catchCauseFilter``, ``tapCauseIf`` "filter match taps" / "filter no match
  skips tap", ``filter`` "Filter.Filter overload maps pass values": the
  ``Filter`` module is not ported; ``catch_cause_if`` / ``tap_cause_if`` /
  ``filter`` take predicates.
- "typed recovery with mixed causes": ported in ``tests/test_cause_recovery.py``,
  which runs every recovery combinator through it.
"""

from dataclasses import dataclass
from typing import Any, Never, TypeIs

import pyfect as fx
from pyfect import testing
from pyfect.cause import Cause, Die, Fail


@dataclass(eq=False)
class ErrorA(fx.TaggedError):
    pass


@dataclass(eq=False)
class ErrorB(fx.TaggedError):
    pass


@dataclass(eq=False)
class ErrorC(fx.TaggedError):
    pass


def _defect(ex: fx.Exit[Any, Any]) -> BaseException:
    assert isinstance(ex, fx.Failure)
    defect = ex.cause.find_defect()
    assert defect is not None
    return defect


def _error(ex: fx.Exit[Any, Any]) -> object:
    assert isinstance(ex, fx.Failure)
    found = ex.cause.find_fail()
    assert isinstance(found, Fail)
    return found.error


# --- fromOption ---------------------------------------------------------------------


def test_from_a_some() -> None:
    """from a some"""
    assert testing.run_test(fx.from_option(fx.Some("A")).or_die()) == "A"


def test_from_a_none() -> None:
    """from a none"""
    error = testing.run_test(fx.from_option(None).flip())
    assert isinstance(error, fx.NoSuchElementException)


def test_from_a_none_with_a_custom_error() -> None:
    """from a none with a custom error"""
    error = ValueError("Missing value")
    assert testing.run_test(fx.from_option(None, lambda: error).flip()) is error


def test_evaluates_the_error_factory_on_each_execution_not_at_construction() -> None:
    """evaluates the error factory on each execution, not at construction"""
    calls = 0

    def make() -> ValueError:
        nonlocal calls
        calls += 1
        return ValueError(f"Missing value {calls}")

    eff = fx.from_option(None, make)
    assert calls == 0
    first = testing.run_test(eff.flip())
    second = testing.run_test(eff.flip())
    assert calls == 2
    assert first is not second


def test_captures_a_throwing_error_factory_as_a_runtime_defect() -> None:
    """captures a throwing error factory as a runtime defect"""
    defect = RuntimeError("Error factory failed")

    def make() -> Never:
        raise defect

    assert _defect(testing.run_test_exit(fx.from_option(None, make))) is defect


# --- transposeOption ----------------------------------------------------------------


def test_transposes_a_none() -> None:
    """transposes a none"""
    assert testing.run_test(fx.transpose_option(None)) is None


def test_transposes_a_some_containing_a_success() -> None:
    """transposes a some containing a success"""
    assert testing.run_test(fx.transpose_option(fx.Some(fx.succeed("A")))) == fx.Some("A")


def test_transposes_a_some_containing_a_failure() -> None:
    """transposes a some containing a failure"""
    eff = fx.transpose_option(fx.Some(fx.fail("error")))
    assert _error(testing.run_test_exit(eff)) == "error"


# --- fromResult ---------------------------------------------------------------------


def test_from_a_success() -> None:
    """from a success"""
    assert testing.run_test(fx.from_result(fx.Ok("A"))) == "A"


def test_from_a_failure() -> None:
    """from a failure"""
    assert testing.run_test(fx.from_result(fx.Err("error")).flip()) == "error"


# --- try ----------------------------------------------------------------------------


def test_succeeds_with_the_returned_value_in_direct_thunk_form() -> None:
    """succeeds with the returned value in direct-thunk form"""
    assert testing.run_test(fx.try_(lambda: 1).or_die()) == 1


def test_maps_thrown_values_to_unknown_error_in_direct_thunk_form() -> None:
    """maps thrown values to UnknownError in direct-thunk form"""
    thrown = ValueError("try")

    def boom() -> int:
        raise thrown

    error = _error(testing.run_test_exit(fx.try_(boom)))
    assert isinstance(error, fx.UnknownError)
    assert error.cause is thrown
    assert error.__cause__ is thrown
    assert error.message == "An error occurred in try_"


def test_succeeds_with_the_returned_value() -> None:
    """succeeds with the returned value"""
    catch_called = False

    def catch(_: Exception) -> str:
        nonlocal catch_called
        catch_called = True
        return "error"

    assert testing.run_test(fx.try_(lambda: 1, catch).or_die()) == 1
    assert not catch_called


def test_maps_thrown_values_into_typed_failures() -> None:
    """maps thrown values into typed failures"""
    thrown = ValueError("try")
    mapped = {"cause": thrown}

    def boom() -> int:
        raise thrown

    ex = testing.run_test_exit(fx.try_(boom, lambda _: mapped))
    assert ex == fx.Failure(fx.cause.fail(mapped))


def test_turns_a_throwing_catch_mapper_into_a_defect() -> None:
    """turns a throwing catch mapper into a defect"""
    defect = RuntimeError("catch")

    def boom() -> int:
        raise ValueError("try")

    def catch(_: Exception) -> Never:
        raise defect

    assert _defect(testing.run_test_exit(fx.try_(boom, catch))) is defect


# --- error handling -------------------------------------------------------------------


def test_catch_tag() -> None:
    """catchTag"""
    error: ErrorA | ErrorB | ErrorC = ErrorA()
    eff = (
        fx.fail_sync(lambda: error)
        .pipe(fx.catch_tag(ErrorA, lambda _: fx.succeed(1)))
        .pipe(fx.catch_tag(ErrorB, lambda _: fx.succeed(2)))
        .or_else_succeed(lambda _: 3)
    )
    assert testing.run_test(eff) == 1
    error = ErrorB()
    assert testing.run_test(eff) == 2
    error = ErrorC()
    assert testing.run_test(eff) == 3


def test_catch_tag_or_else() -> None:
    """catchTag orElse"""
    error: ErrorA | ErrorB | ErrorC = ErrorA()

    def rest(_: ErrorC) -> fx.Effect[int]:
        return fx.succeed(2)

    eff = fx.fail_sync(lambda: error).pipe(
        fx.catch_tag((ErrorA, ErrorB), lambda _: fx.succeed(1), or_else=rest)
    )
    assert testing.run_test(eff) == 1
    error = ErrorB()
    assert testing.run_test(eff) == 1
    error = ErrorC()
    assert testing.run_test(eff) == 2


def test_catch_tags_or_else() -> None:
    """catchTags orElse

    pyright can't remove several error types through a dict of handlers
    (PARITY 5.8), so the handlers are chained ``catch_tag`` calls and the last
    one takes ``or_else``."""
    error: ErrorA | ErrorB | ErrorC = ErrorA()

    def rest(_: ErrorC) -> fx.Effect[int]:
        return fx.succeed(3)

    eff = (
        fx.fail_sync(lambda: error)
        .pipe(fx.catch_tag(ErrorA, lambda _: fx.succeed(1)))
        .pipe(fx.catch_tag(ErrorB, lambda _: fx.succeed(2), or_else=rest))
    )
    assert testing.run_test(eff) == 1
    error = ErrorB()
    assert testing.run_test(eff) == 2
    error = ErrorC()
    assert testing.run_test(eff) == 3


def test_tap_error_tag() -> None:
    """tapErrorTag"""
    error: ErrorA | ErrorB | ErrorC = ErrorA()
    tapped: list[str] = []
    eff = (
        fx.fail_sync(lambda: error)
        .tap_error_tag(ErrorA, lambda _: fx.sync(lambda: tapped.append("A")))
        .tap_error_tag(ErrorB, lambda _: fx.sync(lambda: tapped.append("B")))
        .exit()
    )
    assert testing.run_test(eff) == fx.exit.fail(error)
    assert tapped == ["A"]

    tapped.clear()
    error = ErrorB()
    assert testing.run_test(eff) == fx.exit.fail(error)
    assert tapped == ["B"]

    tapped.clear()
    error = ErrorC()
    assert testing.run_test(eff) == fx.exit.fail(error)
    assert tapped == []


def _is_error_a(e: object) -> TypeIs[ErrorA]:
    return isinstance(e, ErrorA)


def test_catch_if_with_refinement() -> None:
    """catchIf with refinement"""
    eff: fx.Effect[Never, ErrorA | ErrorB] = fx.fail(ErrorB())
    result = testing.run_test(eff.pipe(fx.catch_if(_is_error_a, fx.succeed)).exit())
    assert result == fx.exit.fail(ErrorB())


def test_catch_if_with_refinement_or_else() -> None:
    """catchIf with refinement orElse"""

    def rest(_: ErrorB) -> fx.Effect[int]:
        return fx.succeed(1)

    eff: fx.Effect[Never, ErrorA | ErrorB] = fx.fail(ErrorB())
    assert testing.run_test(eff.pipe(fx.catch_if(_is_error_a, fx.succeed, or_else=rest))) == 1


def test_catch_no_such_element() -> None:
    """catchNoSuchElement"""
    some = testing.run_test(fx.from_optional("value").pipe(fx.catch_no_such_element))
    assert some == fx.Some("value")
    nothing: str | None = None
    none = testing.run_test(fx.from_optional(nothing).pipe(fx.catch_no_such_element))
    assert none is None


def test_catch_no_such_element_preserves_other_errors() -> None:
    """catchNoSuchElement preserves other errors"""
    error = ErrorA()
    result = testing.run_test(fx.fail(error).pipe(fx.catch_no_such_element).exit())
    assert result == fx.exit.fail(error)


# --- match ----------------------------------------------------------------------------


def test_preserves_handler_receivers_and_treats_thrown_exceptions_as_defects() -> None:
    """preserves handler receivers and treats thrown exceptions as defects

    JS ``this`` receivers have no Python counterpart; the defect half is ported."""
    boom = RuntimeError("boom")

    def throw(_: object) -> Never:
        raise boom

    assert (
        testing.run_test(fx.succeed(1).match(on_failure=lambda _: 0, on_success=lambda a: a)) == 1
    )
    assert (
        _defect(
            testing.run_test_exit(fx.succeed(1).match(on_failure=lambda _: 0, on_success=throw))
        )
        is boom
    )
    assert (
        _defect(
            testing.run_test_exit(
                fx.fail("e").match_cause(on_failure=throw, on_success=lambda a: a)
            )
        )
        is boom
    )


def test_passes_defects_through_without_calling_on_failure() -> None:
    """passes defects through without calling onFailure"""
    boom = RuntimeError("boom")
    eff = fx.die(boom).match(on_failure=lambda _: "handled", on_success=lambda _: "ok")
    assert _defect(testing.run_test_exit(eff)) is boom


# --- catchIf / catchCauseIf / tapCauseIf with predicate ---------------------------------


def test_catch_if_with_predicate_match_recovers() -> None:
    """catchIf with predicate > predicate match recovers"""
    eff = fx.fail("e1").catch_if(lambda e: e == "e1", lambda e: fx.succeed(f"recovered: {e}"))
    assert testing.run_test_exit(eff) == fx.Success("recovered: e1")


def test_catch_if_with_predicate_no_match_preserves_error() -> None:
    """catchIf with predicate > predicate no match preserves error"""
    eff = fx.fail("e1").catch_if(lambda _: False, lambda _: fx.succeed("recovered"))
    assert testing.run_test(eff.exit()) == fx.exit.fail("e1")


def test_catch_cause_if_with_predicate_match_recovers() -> None:
    """catchCauseIf with predicate > predicate match recovers"""
    eff = fx.fail("e1").catch_cause_if(
        lambda c: c.has_fails, lambda c: fx.succeed(f"recovered: {c.failures[0]}")
    )
    assert testing.run_test_exit(eff) == fx.Success("recovered: e1")


def test_catch_cause_if_with_predicate_no_match_preserves_error() -> None:
    """catchCauseIf with predicate > predicate no match preserves error"""
    eff = fx.fail("e1").catch_cause_if(lambda _: False, lambda _: fx.succeed("recovered"))
    assert testing.run_test(eff.exit()) == fx.exit.fail("e1")


def test_tap_cause_if_predicate_match_taps() -> None:
    """tapCauseIf > predicate match taps"""
    tapped: list[str] = []
    eff = fx.fail("e1").tap_cause_if(
        lambda c: c.has_fails, lambda c: fx.sync(lambda: tapped.append(c.failures[0]))
    )
    assert testing.run_test(eff.exit()) == fx.exit.fail("e1")
    assert tapped == ["e1"]


def test_tap_cause_if_predicate_no_match_skips_tap() -> None:
    """tapCauseIf > predicate no match skips tap"""
    tapped: list[str] = []
    eff = fx.fail("e1").tap_cause_if(lambda _: False, lambda _: fx.sync(lambda: tapped.append("t")))
    assert testing.run_test(eff.exit()) == fx.exit.fail("e1")
    assert tapped == []


def test_tap_cause_if_success_skips_tap() -> None:
    """tapCauseIf > success skips tap"""
    tapped: list[str] = []
    eff = fx.succeed(42).tap_cause_if(lambda _: True, lambda _: fx.sync(lambda: tapped.append("t")))
    assert testing.run_test(eff) == 42
    assert tapped == []


# --- filter -------------------------------------------------------------------------------


def test_filter_preserves_input_order_with_concurrency_2() -> None:
    """filter > preserves input order with concurrency 2"""

    def keep(n: int) -> fx.Effect[bool]:
        return fx.sleep(0.02).as_(True) if n == 1 else fx.succeed(n == 2)

    @fx.gen
    def program():
        fiber = yield from fx.filter([1, 2, 3], keep, concurrency=2).fork()
        yield from testing.adjust(0.02)
        return (yield from fiber.join())

    assert testing.run_test(program) == [1, 2]


def test_filter_odd_numbers() -> None:
    """filter > odd numbers"""
    eff = fx.filter([1, 2, 3, 4, 5], lambda n: fx.succeed(n % 2 == 1))
    assert fx.run_sync(eff) == [1, 3, 5]


def test_filter_iterable() -> None:
    """filter > iterable"""
    eff = fx.filter({1, 2, 3, 4, 5}, lambda n: fx.succeed(n % 2 == 1))
    assert sorted(fx.run_sync(eff)) == [1, 3, 5]


def test_predicate_filters_iterable() -> None:
    """filter with predicate/refinement > predicate filters iterable"""
    assert testing.run_test(fx.filter([1, 2, 3, 4, 5], lambda n: n % 2 == 0)) == [2, 4]


def _is_int(x: int | str) -> TypeIs[int]:
    return isinstance(x, int)


def test_refinement_narrows_iterable() -> None:
    """filter with predicate/refinement > refinement narrows iterable"""
    mixed: list[int | str] = [1, "a", 2, "b", 3]
    assert testing.run_test(fx.filter(mixed, _is_int)) == [1, 2, 3]


# --- catch / catchCause ---------------------------------------------------------------


def test_catch_first_argument_as_success() -> None:
    """catch > first argument as success"""
    assert testing.run_test_exit(fx.succeed(1).catch_all(lambda _: fx.fail("e2"))) == fx.Success(1)


def test_catch_first_argument_as_failure() -> None:
    """catch > first argument as failure"""
    assert testing.run_test(fx.fail("e1").catch_all(lambda _: fx.fail("e2")).flip()) == "e2"


def test_repeated_throwing_handlers_do_not_overflow_the_stack_and_run_finalizers() -> None:
    """catchCause > repeated throwing handlers do not overflow the stack and run finalizers"""
    handler_defect = RuntimeError("handler defect")

    def throw(_: Cause[Never]) -> fx.Effect[Never]:
        raise handler_defect

    program: fx.Effect[Never] = fx.die(RuntimeError("initial"))
    for _ in range(20_000):
        program = program.catch_cause(throw)
    finalized = 0

    def finalize() -> None:
        nonlocal finalized
        finalized += 1

    ex = fx.run_sync_exit(program.ensuring(fx.sync(finalize)))
    assert ex == fx.exit.die(handler_defect)
    assert finalized == 1


def test_catch_cause_first_argument_as_success() -> None:
    """catchCause > first argument as success"""
    eff = fx.succeed(1).catch_cause(lambda _: fx.fail("e2"))
    assert testing.run_test_exit(eff) == fx.Success(1)


def test_catch_cause_first_argument_as_failure() -> None:
    """catchCause > first argument as failure"""
    assert testing.run_test(fx.fail("e1").catch_cause(lambda _: fx.fail("e2")).flip()) == "e2"


# --- firstSuccessOf -------------------------------------------------------------------


def test_returns_the_first_success_and_does_not_run_later_effects() -> None:
    """firstSuccessOf > returns the first success and does not run later effects"""
    executed: list[str] = []
    eff = fx.first_success_of(
        [
            fx.sync(lambda: executed.append("first")).and_then(fx.fail("e1")),
            fx.sync(lambda: executed.append("second")).as_("success"),
            fx.sync(lambda: executed.append("third")).as_("unreachable"),
        ]
    )
    assert testing.run_test(eff.or_die()) == "success"
    assert executed == ["first", "second"]


def test_fails_with_the_last_failure_when_all_effects_fail() -> None:
    """firstSuccessOf > fails with the last failure when all effects fail"""
    eff = fx.first_success_of([fx.fail("e1"), fx.fail("e2"), fx.fail("e3")])
    assert testing.run_test(eff.flip()) == "e3"


def test_defects_on_an_empty_collection() -> None:
    """firstSuccessOf > defects on an empty collection"""
    empty: list[fx.Effect[Never]] = []
    cause = testing.run_test(fx.first_success_of(empty).sandbox().flip())
    reason = cause.reasons[0]
    assert isinstance(reason, Die)
    assert isinstance(reason.defect, Exception)
    assert str(reason.defect) == "Received an empty collection of effects"
