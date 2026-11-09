"""Ports of the error-handling sections of Effect's ``Effect.test.ts``.

Each test's docstring is the Effect test title. Omitted, with the reason:

- ``fromOption`` "from a none with a custom error data-last": Python has one
  call form, ``from_option(option, on_none)``.
- ``match`` "passes only the outcome to handlers": counts JS ``arguments``.
- ``tryPromise`` "does not allocate AbortController for zero-argument thunks":
  ``try_async`` cancels the task, so there is no signal to allocate.
- "typed recovery with mixed causes": ported in ``tests/test_cause_recovery.py``,
  which runs every recovery combinator through it.
"""

import asyncio
from collections.abc import Awaitable, Callable
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


def _defect(ex: fx.Exit[Any, Any]) -> object:
    assert isinstance(ex, fx.Failure)
    defect = ex.cause.find_defect()
    assert isinstance(defect, fx.Ok)
    return defect.value


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


# --- tryPromise (pyfect: try_async) -------------------------------------------------


def _run_async_exit[A, E](eff: fx.Effect[A, E]) -> fx.Exit[A, E]:
    return asyncio.run(testing.run_test_async_exit(eff, timeout="2 seconds"))


async def _resolve(value: int) -> int:
    return value


def test_succeeds_with_the_resolved_value_in_direct_thunk_form() -> None:
    """succeeds with the resolved value in direct-thunk form"""
    assert _run_async_exit(fx.try_async(lambda: _resolve(1))) == fx.Success(1)


def test_maps_synchronous_throws_to_unknown_error_in_direct_thunk_form() -> None:
    """maps synchronous throws to UnknownError in direct-thunk form"""
    thrown = ValueError("try")

    def make() -> Awaitable[int]:
        raise thrown

    error = _error(_run_async_exit(fx.try_async(make)))
    assert isinstance(error, fx.UnknownError)
    assert error.cause is thrown
    assert error.message == "An error occurred in try_async"


def test_maps_promise_rejections_to_unknown_error_in_direct_thunk_form() -> None:
    """maps promise rejections to UnknownError in direct-thunk form"""
    rejected = ValueError("reject")

    async def make() -> int:
        raise rejected

    error = _error(_run_async_exit(fx.try_async(make)))
    assert isinstance(error, fx.UnknownError)
    assert error.cause is rejected
    assert error.message == "An error occurred in try_async"


def test_succeeds_with_the_resolved_value_in_options_form() -> None:
    """succeeds with the resolved value in options form"""
    catch_called = False

    def catch(_: Exception) -> str:
        nonlocal catch_called
        catch_called = True
        return "error"

    assert _run_async_exit(fx.try_async(lambda: _resolve(1), catch)) == fx.Success(1)
    assert not catch_called


def test_maps_synchronous_throws_with_catch_in_options_form() -> None:
    """maps synchronous throws with catch in options form"""
    thrown = ValueError("try")
    mapped = {"cause": thrown}

    def make() -> Awaitable[int]:
        raise thrown

    ex = _run_async_exit(fx.try_async(make, lambda _: mapped))
    assert ex == fx.Failure(fx.cause.fail(mapped))


def test_maps_promise_rejections_with_catch_in_options_form() -> None:
    """maps promise rejections with catch in options form"""
    rejected = ValueError("reject")
    mapped = {"cause": rejected}

    async def make() -> int:
        raise rejected

    ex = _run_async_exit(fx.try_async(make, lambda _: mapped))
    assert ex == fx.Failure(fx.cause.fail(mapped))


def test_turns_a_throwing_catch_mapper_for_a_synchronous_throw_into_a_defect() -> None:
    """turns a throwing catch mapper for a synchronous throw into a defect"""
    defect = RuntimeError("catch")

    def make() -> Awaitable[int]:
        raise ValueError("try")

    def catch(_: Exception) -> Never:
        raise defect

    assert _defect(_run_async_exit(fx.try_async(make, catch))) is defect


def test_turns_a_throwing_catch_mapper_for_a_promise_rejection_into_a_defect() -> None:
    """turns a throwing catch mapper for a promise rejection into a defect"""
    defect = RuntimeError("catch")

    async def make() -> int:
        raise ValueError("reject")

    def catch(_: Exception) -> Never:
        raise defect

    assert _defect(_run_async_exit(fx.try_async(make, catch))) is defect


def test_aborts_the_provided_abort_signal_on_interruption() -> None:
    """aborts the provided AbortSignal on interruption"""
    cancelled = False
    started = asyncio.Event()

    async def forever() -> int:
        nonlocal cancelled
        started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled = True
            raise
        return 0

    @fx.gen
    def program():
        fiber = yield from fx.try_async(forever).fork()
        yield from fx.from_async(started.wait)
        yield from fiber.interrupt()

    assert _run_async_exit(program) == fx.Success(None)
    assert cancelled


# --- Effect.ignore / Effect.ignoreCause with log -----------------------------------------


@dataclass(frozen=True)
class _Captured:
    log_level: fx.LogLevel
    cause: Cause[object]
    message: tuple[object, ...]


def _run_ignoring(
    ignore: Callable[[fx.Effect[Never, str]], fx.Effect[None]],
    current_log_level: fx.logger.Severity = fx.LogLevel.INFO,
) -> list[_Captured]:
    captured: list[_Captured] = []
    capture = fx.Logger.make(lambda o: captured.append(_Captured(o.log_level, o.cause, o.message)))
    testing.run_test(
        ignore(fx.fail("boom"))
        .pipe(fx.provide(fx.logger.layer([capture])))
        .pipe(fx.provide_service(fx.MinimumLogLevel, fx.LogLevel.TRACE))
        .pipe(fx.provide_service(fx.CurrentLogLevel, current_log_level))
    )
    return captured


def _fails_with_boom(cause: Cause[object]) -> bool:
    return cause.failures == ("boom",)


def test_ignore_does_not_log_when_log_is_omitted() -> None:
    """does not log when log is omitted"""
    assert _run_ignoring(lambda eff: eff.ignore()) == []


def test_ignore_does_not_log_when_log_is_false() -> None:
    """does not log when log is false"""
    assert _run_ignoring(lambda eff: eff.ignore(log=False)) == []


def test_ignore_logs_with_the_current_level_when_log_is_true() -> None:
    """logs with the current level when log is true"""
    logs = _run_ignoring(lambda eff: eff.ignore(log=True), fx.LogLevel.WARN)
    assert len(logs) == 1
    assert logs[0].log_level is fx.LogLevel.WARN
    assert _fails_with_boom(logs[0].cause)


def test_ignore_logs_with_the_provided_level_when_log_is_a_log_level() -> None:
    """logs with the provided level when log is a LogLevel"""
    logs = _run_ignoring(lambda eff: eff.ignore(log=fx.LogLevel.ERROR), fx.LogLevel.WARN)
    assert len(logs) == 1
    assert logs[0].log_level is fx.LogLevel.ERROR
    assert _fails_with_boom(logs[0].cause)


def test_ignore_prepends_the_provided_message_when_logging() -> None:
    """prepends the provided message when logging"""
    logs = _run_ignoring(lambda eff: eff.ignore(log=True, message="Ignoring failure"))
    assert len(logs) == 1
    assert logs[0].message == ("Ignoring failure",)
    assert _fails_with_boom(logs[0].cause)


def test_ignore_with_log_keeps_defects() -> None:
    """A defect is not ignored, and not logged (Effect re-fails the cause)."""
    captured: list[object] = []
    eff = fx.die(RuntimeError("boom")).ignore(log=True)
    ex = testing.run_test_exit(eff.with_logger(fx.Logger.make(captured.append)))
    assert isinstance(ex, fx.Failure)
    assert captured == []


# --- Effect.ignoreCause --------------------------------------------------------------


def test_ignores_defects() -> None:
    """ignores defects"""
    assert testing.run_test_exit(fx.die(RuntimeError("boom")).ignore_cause()) == fx.Success(None)


def test_ignores_interrupts() -> None:
    """ignores interrupts"""
    assert testing.run_test_exit(fx.interrupt().ignore_cause()) == fx.Success(None)


def test_ignore_cause_does_not_log_when_log_is_omitted() -> None:
    """does not log when log is omitted"""
    assert _run_ignoring(lambda eff: eff.ignore_cause()) == []


def test_ignore_cause_does_not_log_when_log_is_false() -> None:
    """does not log when log is false"""
    assert _run_ignoring(lambda eff: eff.ignore_cause(log=False)) == []


def test_ignore_cause_logs_with_the_current_level_when_log_is_true() -> None:
    """logs with the current level when log is true"""
    logs = _run_ignoring(lambda eff: eff.ignore_cause(log=True), fx.LogLevel.WARN)
    assert len(logs) == 1
    assert logs[0].log_level is fx.LogLevel.WARN
    assert _fails_with_boom(logs[0].cause)


def test_ignore_cause_logs_with_the_provided_level_when_log_is_a_log_level() -> None:
    """logs with the provided level when log is a LogLevel"""
    logs = _run_ignoring(lambda eff: eff.ignore_cause(log=fx.LogLevel.ERROR), fx.LogLevel.WARN)
    assert len(logs) == 1
    assert logs[0].log_level is fx.LogLevel.ERROR
    assert _fails_with_boom(logs[0].cause)


def test_ignore_cause_prepends_the_provided_message_when_logging() -> None:
    """prepends the provided message when logging"""
    logs = _run_ignoring(lambda eff: eff.ignore_cause(log=True, message="Ignoring cause"))
    assert len(logs) == 1
    assert logs[0].message == ("Ignoring cause",)
    assert _fails_with_boom(logs[0].cause)


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


def test_tap_cause_if_filter_match_taps() -> None:
    """tapCauseIf > filter match taps"""
    tapped: list[str] = []
    eff = fx.fail("e1").tap_cause_filter(
        fx.Ok, lambda c, _: fx.sync(lambda: tapped.append(c.failures[0]))
    )
    assert testing.run_test(eff.exit()) == fx.exit.fail("e1")
    assert tapped == ["e1"]


def test_tap_cause_if_filter_no_match_skips_tap() -> None:
    """tapCauseIf > filter no match skips tap"""
    tapped: list[str] = []
    eff = fx.fail("e1").tap_cause_filter(fx.Err, lambda _v, _c: fx.sync(lambda: tapped.append("t")))
    assert testing.run_test(eff.exit()) == fx.exit.fail("e1")
    assert tapped == []


# --- catchCauseFilter ---------------------------------------------------------------------


def test_catch_cause_filter_first_argument_as_success() -> None:
    """catchCauseFilter > first argument as success"""
    eff = fx.succeed(1).catch_cause_filter(fx.Err, lambda _v, _c: fx.fail("e2"))
    assert testing.run_test_exit(eff) == fx.Success(1)


def test_catch_cause_filter_first_argument_as_failure_and_predicate_return_false() -> None:
    """catchCauseFilter > first argument as failure and predicate return false"""
    eff = fx.fail("e1").catch_cause_filter(fx.Err, lambda _v, _c: fx.fail("e2"))
    assert testing.run_test(eff.flip()) == "e1"


def test_catch_cause_filter_first_argument_as_failure_and_predicate_return_true() -> None:
    """catchCauseFilter > first argument as failure and predicate return true"""
    eff = fx.fail("e1").catch_cause_filter(fx.Ok, lambda _v, _c: fx.fail("e2"))
    assert testing.run_test(eff.flip()) == "e2"


# --- filter -------------------------------------------------------------------------------


def test_filter_preserves_input_order_with_concurrency_2() -> None:
    """filter > preserves input order with concurrency 2"""

    def keep(n: int) -> fx.Effect[bool]:
        return fx.sleep("20 millis").as_(True) if n == 1 else fx.succeed(n == 2)

    @fx.gen
    def program():
        fiber = yield from fx.filter([1, 2, 3], keep, concurrency=2).fork()
        yield from testing.adjust("20 millis")
        return (yield from fiber.join())

    assert testing.run_test(program) == [1, 2]


def test_filter_odd_numbers() -> None:
    """filter > odd numbers"""
    eff = fx.filter([1, 2, 3, 4, 5], lambda n: fx.succeed(n % 2 == 1))
    assert fx.run_blocking(eff) == [1, 3, 5]


def test_filter_iterable() -> None:
    """filter > iterable"""
    eff = fx.filter({1, 2, 3, 4, 5}, lambda n: fx.succeed(n % 2 == 1))
    assert sorted(fx.run_blocking(eff)) == [1, 3, 5]


def test_predicate_filters_iterable() -> None:
    """filter with predicate/refinement > predicate filters iterable"""
    assert testing.run_test(fx.filter([1, 2, 3, 4, 5], lambda n: n % 2 == 0)) == [2, 4]


def _is_int(x: int | str) -> TypeIs[int]:
    return isinstance(x, int)


def test_refinement_narrows_iterable() -> None:
    """filter with predicate/refinement > refinement narrows iterable"""
    mixed: list[int | str] = [1, "a", 2, "b", 3]
    assert testing.run_test(fx.filter(mixed, _is_int)) == [1, 2, 3]


def test_filter_filter_overload_maps_pass_values() -> None:
    """filter with predicate/refinement > Filter.Filter overload maps pass values"""

    def even(n: int) -> fx.Result[str, int]:
        return fx.Ok(f"n={n}") if n % 2 == 0 else fx.Err(n)

    assert testing.run_test(fx.filter_map([1, 2, 3, 4], even)) == ["n=2", "n=4"]


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

    ex = fx.run_blocking_exit(program.ensuring(fx.sync(finalize)))
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
