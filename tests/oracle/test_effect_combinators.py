"""Ports of the structural and concurrency sections of Effect's
``Effect.test.ts`` (all, partition, validate, zip, zipWith, cached,
cachedWithTTL, cachedInvalidateWithTTL, timeoutOrElse, timeoutOption,
timeout, raceAllFirst, acquireDisposable) and of the ``interruptibleMask``
case of ``Fiber.test.ts``.

Each test's docstring is the Effect test title. Effect's
``forkChild({ startImmediately: true })`` is ``fork(start_immediately=True)``.
Omitted, with the reason:

- ``all`` "iterable": ``fx.all`` is variadic; an iterable is spread
  (``fx.all(*effects)``) or collected with ``for_each``.
- ``timeoutOrElse`` "data-first" / "pipe" forms: Python has one call form,
  so "factory and body follow cleanup and replay" is ported once.
- "cached / cachedInvalidateWithTTL never strands a second caller when the
  owner yields before registering cleanup" sweeps a custom ``Scheduler``'s
  ``shouldYield`` points; pyfect's schedulers have no ``should_yield`` (the
  budget is ``MaxOpsBeforeYield``), and the case it guards is covered in
  ``tests/test_structural_combinators.py``.
"""

import asyncio
import warnings
from contextlib import contextmanager
from types import TracebackType
from typing import Any

import pyfect as fx
from pyfect import testing
from pyfect.duration import Duration, millis
from pyfect.exit import fail as exit_fail
from pyfect.exit import succeed as exit_succeed


def _interrupted(ex: fx.Exit[Any, Any]) -> bool:
    return isinstance(ex, fx.Failure) and ex.cause.has_interrupts


# --- all ----------------------------------------------------------------------------


def test_record_preserves_input_key_order_with_concurrency_2() -> None:
    """record preserves input key order with concurrency 2"""

    @fx.gen
    def program():
        fiber = yield from fx.all_dict(
            {"a": fx.sleep("20 millis").as_(1), "b": fx.succeed(2)}, concurrency=2
        ).fork()
        yield from testing.adjust("20 millis")
        return (yield from fiber.join())

    results = testing.run_test(program)
    assert list(results) == ["a", "b"]
    assert results == {"a": 1, "b": 2}


def test_record_result_mode_preserves_input_key_order_with_unbounded_concurrency() -> None:
    """record result mode preserves input key order with unbounded concurrency"""

    @fx.gen
    def program():
        fiber = yield from fx.all_dict(
            {"a": fx.sleep("20 millis").as_(1), "b": fx.fail("boom")},
            concurrency="unbounded",
            mode="result",
        ).fork()
        yield from testing.adjust("20 millis")
        return (yield from fiber.join())

    results = testing.run_test(program)
    assert list(results) == ["a", "b"]
    assert results == {"a": fx.Ok(1), "b": fx.Err("boom")}


def test_tuple() -> None:
    """tuple"""
    eff = fx.all(fx.succeed(1), fx.succeed(2), fx.succeed(3))
    assert testing.run_test(eff) == (1, 2, 3)


def test_record() -> None:
    """record"""
    eff = fx.all_dict({"a": fx.succeed(1), "b": fx.succeed("2"), "c": fx.succeed(True)})
    assert testing.run_test(eff) == {"a": 1, "b": "2", "c": True}


def test_record_discard() -> None:
    """record discard"""
    eff = fx.all_dict(
        {"a": fx.succeed(1), "b": fx.succeed("2"), "c": fx.succeed(True)}, discard=True
    )
    assert testing.run_test(eff) is None


def test_tuple_result_mode() -> None:
    """tuple result mode"""
    executed: list[int] = []

    def push(n: int) -> fx.Effect[int]:
        return fx.sync(lambda: executed.append(n) or n)

    eff = fx.all(push(1), push(2).and_then(fx.fail("boom")), push(3), mode="result")
    assert testing.run_test(eff) == (fx.Ok(1), fx.Err("boom"), fx.Ok(3))
    assert executed == [1, 2, 3]


def test_record_result_mode() -> None:
    """record result mode"""
    eff = fx.all_dict(
        {"a": fx.succeed(1), "b": fx.fail("boom"), "c": fx.succeed(True)}, mode="result"
    )
    assert testing.run_test(eff) == {"a": fx.Ok(1), "b": fx.Err("boom"), "c": fx.Ok(True)}


def test_concurrency_interrupts_started_siblings_on_failure() -> None:
    """concurrency interrupts started siblings on failure"""
    started: list[int] = []
    interrupted: list[int] = []

    def make(i: int) -> fx.Effect[int]:
        return (
            fx.suspend(lambda: fx.sync(lambda: started.append(i)).and_then(fx.sleep("500 millis")))
            .as_(i)
            .on_interrupt(fx.sync(lambda: interrupted.append(i)))
        )

    @fx.gen
    def program():
        fiber = yield from fx.all(
            make(1), fx.fail("boom").delay("100 millis"), make(3), make(4), concurrency=3
        ).fork()
        yield from testing.adjust("100 millis")
        return (yield from fiber.await_exit())

    assert testing.run_test(program) == exit_fail("boom")
    assert started == [1, 3]
    assert interrupted == [1, 3]


# --- partition ------------------------------------------------------------------------


def test_collects_only_successes() -> None:
    """collects only successes"""
    values = [0, 1, 2, 3, 4]
    assert testing.run_test(fx.partition(values, fx.succeed)) == (values, [])


def test_collects_only_failures() -> None:
    """collects only failures"""
    values = [0, 1, 2, 3, 4]
    assert testing.run_test(fx.partition(values, fx.fail)) == ([], values)


def _odd_or_fail(n: int) -> fx.Effect[int, int]:
    return fx.fail(n) if n % 2 == 0 else fx.succeed(n)


def test_collects_successes_and_failures() -> None:
    """collects successes and failures"""
    eff = fx.partition([0, 1, 2, 3, 4, 5], _odd_or_fail)
    assert testing.run_test(eff) == ([1, 3, 5], [0, 2, 4])


def test_supports_concurrency_option() -> None:
    """supports concurrency option"""
    eff = fx.partition([0, 1, 2, 3, 4, 5], _odd_or_fail, concurrency="unbounded")
    assert testing.run_test(eff) == ([1, 3, 5], [0, 2, 4])


# --- validate -------------------------------------------------------------------------


def test_collects_successes_when_all_effects_succeed() -> None:
    """collects successes when all effects succeed"""
    values = [0, 1, 2, 3, 4]
    assert testing.run_test(fx.validate(values, fx.succeed)) == values


def test_accumulates_all_failures() -> None:
    """accumulates all failures"""
    eff = fx.validate([0, 1, 2, 3, 4, 5], _odd_or_fail).flip().or_die()
    assert testing.run_test(eff) == (0, 2, 4)


def test_supports_discard_option() -> None:
    """supports discard option"""
    assert testing.run_test(fx.validate([1, 2, 3], fx.succeed, discard=True)) is None


# --- zip / zipWith ----------------------------------------------------------------------


def _ordered_tasks(order: list[str]) -> tuple[fx.Effect[str], fx.Effect[int]]:
    task1 = fx.succeed("a").delay("50 millis").tap(lambda _: fx.sync(lambda: order.append("task1")))
    task2 = fx.succeed(1).delay("1 millis").tap(lambda _: fx.sync(lambda: order.append("task2")))
    return task1, task2


def test_zip_concurrent_false() -> None:
    """concurrent: false"""
    order: list[str] = []
    task1, task2 = _ordered_tasks(order)

    @fx.gen
    def program():
        fiber = yield from task1.zip(task2).fork()
        yield from testing.adjust("51 millis")
        return (yield from fiber.join())

    assert testing.run_test(program) == ("a", 1)
    assert order == ["task1", "task2"]


def test_zip_concurrent_true() -> None:
    """concurrent: true"""
    order: list[str] = []
    task1, task2 = _ordered_tasks(order)

    @fx.gen
    def program():
        fiber = yield from task1.zip(task2, concurrent=True).fork()
        yield from testing.adjust("50 millis")
        return (yield from fiber.join())

    assert testing.run_test(program) == ("a", 1)
    assert order == ["task2", "task1"]


def test_zip_concurrent_true_interrupts_the_other_side_on_failure() -> None:
    """concurrent: true interrupts the other side on failure"""
    interrupted: list[str] = []
    task1 = fx.never.on_interrupt(fx.sync(lambda: interrupted.append("task1")))
    task2 = fx.fail("boom").delay("10 millis")

    @fx.gen
    def program():
        fiber = yield from task1.zip(task2, concurrent=True).fork()
        yield from testing.adjust("10 millis")
        return (yield from fiber.await_exit())

    assert testing.run_test(program) == exit_fail("boom")
    assert interrupted == ["task1"]


def test_zip_with_concurrent_false() -> None:
    """concurrent: false"""
    order: list[str] = []
    task1, task2 = _ordered_tasks(order)

    @fx.gen
    def program():
        fiber = yield from task1.zip_with(task2, lambda a, b: f"{a}{b}").fork()
        yield from testing.adjust("51 millis")
        return (yield from fiber.join())

    assert testing.run_test(program) == "a1"
    assert order == ["task1", "task2"]


def test_zip_with_concurrent_true() -> None:
    """concurrent: true"""
    order: list[str] = []
    task1, task2 = _ordered_tasks(order)

    @fx.gen
    def program():
        fiber = yield from task1.zip_with(task2, lambda a, b: f"{a}{b}", concurrent=True).fork()
        yield from testing.adjust("50 millis")
        return (yield from fiber.join())

    assert testing.run_test(program) == "a1"
    assert order == ["task2", "task1"]


def test_zip_with_concurrent_true_interrupts_the_other_side_on_failure() -> None:
    """concurrent: true interrupts the other side on failure"""
    interrupted: list[str] = []
    task1 = fx.fail("boom").delay("10 millis")
    task2 = fx.never.on_interrupt(fx.sync(lambda: interrupted.append("task2")))

    @fx.gen
    def program():
        fiber = yield from task1.zip_with(task2, lambda a, b: f"{a}{b}", concurrent=True).fork()
        yield from testing.adjust("10 millis")
        return (yield from fiber.await_exit())

    assert testing.run_test(program) == exit_fail("boom")
    assert interrupted == ["task2"]


# --- cached ---------------------------------------------------------------------------


def test_runs_the_effect_once_for_concurrent_callers() -> None:
    """runs the effect once for concurrent callers"""
    count = 0

    def bump() -> int:
        nonlocal count
        count += 1
        return count

    @fx.gen
    def program():
        release = yield from fx.Deferred[None].make()
        cached = yield from fx.sync(bump).tap(lambda _: release.wait()).cached()
        fibers = yield from fx.for_each([1, 2, 3], lambda _: cached.fork(start_immediately=True))
        counted = count
        yield from release.succeed(None)
        exits = yield from fx.Fiber.await_all(fibers)
        return counted, exits

    counted, exits = testing.run_test(program)
    assert counted == 1
    assert exits == [exit_succeed(1)] * 3


def test_shares_the_in_flight_run_when_the_body_synchronously_wakes_a_re_entrant_caller() -> None:
    """shares the in-flight run when the body synchronously wakes a re-entrant caller"""

    @fx.gen
    def program():
        gate = yield from fx.Deferred[None].make()
        cached = yield from gate.succeed(None).as_(42).cached()
        waiter = yield from gate.wait().and_then(cached).fork(start_immediately=True)
        first = yield from cached
        return first, (yield from waiter.join())

    assert testing.run_test(program) == (42, 42)


def test_replays_failures() -> None:
    """replays failures"""
    count = 0

    def bump() -> None:
        nonlocal count
        count += 1

    @fx.gen
    def program():
        cached = yield from fx.sync(bump).and_then(fx.fail("boom")).cached()
        return (yield from cached.exit()), (yield from cached.exit())

    assert testing.run_test(program) == (exit_fail("boom"), exit_fail("boom"))
    assert count == 1


def test_interrupting_a_waiter_leaves_the_owner_running() -> None:
    """interrupting a waiter leaves the owner running"""

    @fx.gen
    def program():
        started = yield from fx.Deferred[None].make()
        release = yield from fx.Deferred[None].make()
        cached = yield from started.succeed(None).and_then(release.wait()).as_(42).cached()
        owner = yield from cached.fork(start_immediately=True)
        yield from started.wait()
        waiter = yield from cached.fork(start_immediately=True)
        yield from waiter.interrupt()
        waiter_exit = yield from waiter.await_exit()
        yield from release.succeed(None)
        return waiter_exit, (yield from owner.join()), (yield from cached)

    waiter_exit, owner_value, again = testing.run_test(program)
    assert _interrupted(waiter_exit)
    assert (owner_value, again) == (42, 42)


def test_shares_a_run_until_every_caller_is_interrupted_then_starts_fresh() -> None:
    """shares a run until every caller is interrupted, then starts fresh"""
    runs = 0

    @fx.gen
    def program():
        started = yield from fx.Deferred[None].make()
        finalizing = yield from fx.Deferred[None].make()
        finish_finalizer = yield from fx.Deferred[None].make()

        def body() -> fx.Effect[int]:
            nonlocal runs
            runs += 1
            if runs > 1:
                return fx.succeed(runs)
            return (
                started.succeed(None)
                .and_then(fx.never)
                .on_interrupt(finalizing.succeed(None).and_then(finish_finalizer.wait()))
            )

        cached = yield from fx.suspend(body).cached()
        first = yield from cached.fork(start_immediately=True)
        yield from started.wait()
        second = yield from cached.fork(start_immediately=True)
        yield from first.interrupt()
        finalizing_early = yield from finalizing.poll()

        # A call made while the abandoned run finalizes starts a fresh run.
        interrupt_second = yield from second.interrupt().fork(start_immediately=True)
        yield from finalizing.wait()
        fresh = yield from cached.fork(start_immediately=True)
        yield from finish_finalizer.succeed(None)
        yield from interrupt_second.join()
        return finalizing_early, (yield from fresh.await_exit())

    finalizing_early, fresh_exit = testing.run_test(program)
    assert finalizing_early is None
    assert fresh_exit == exit_succeed(2)


# --- cachedWithTTL ------------------------------------------------------------------------


def test_skips_the_ttl_callback_on_interruption_and_invokes_it_once_on_next_success() -> None:
    """skips the ttl callback on interruption and invokes it once on the next successful run"""
    runs = 0
    exits: list[fx.Exit[int, Any]] = []

    def body() -> fx.Effect[int]:
        nonlocal runs
        runs += 1
        return fx.interrupt() if runs == 1 else fx.succeed(runs)

    def ttl(ex: fx.Exit[int, Any]) -> float:
        exits.append(ex)
        return millis(60_000)

    @fx.gen
    def program():
        cached = yield from fx.suspend(body).cached_with_ttl(ttl)
        first = yield from cached.exit()
        exits_after_first = list(exits)
        return first, exits_after_first, (yield from cached), (yield from cached)

    first, exits_after_first, second, third = testing.run_test(program)
    assert _interrupted(first)
    assert exits_after_first == []
    assert (second, third) == (2, 2)
    assert exits == [exit_succeed(2)]


def test_selects_ttl_from_each_fresh_exit_without_evaluating_on_cache_hits() -> None:
    """selects ttl from each fresh exit without evaluating on cache hits"""
    count = 0
    exits: list[fx.Exit[int, Any]] = []

    def bump() -> int:
        nonlocal count
        count += 1
        return count

    def ttl(ex: fx.Exit[int, Any]) -> float:
        exits.append(ex)
        return millis(1000) if ex == exit_succeed(1) else millis(3000)

    @fx.gen
    def program():
        cached = yield from fx.sync(bump).cached_with_ttl(ttl)
        seen = [count, len(exits)]
        seen.append((yield from cached))
        yield from testing.adjust("999 millis")
        seen.append((yield from cached))
        seen.append(len(exits))
        yield from testing.adjust("1 millis")
        seen.append((yield from cached))
        yield from testing.adjust("1 second")
        seen.append((yield from cached))
        yield from testing.adjust("2 seconds")
        seen.append((yield from cached))
        return seen

    assert testing.run_test(program) == [0, 0, 1, 1, 1, 2, 2, 3]
    assert exits == [exit_succeed(1), exit_succeed(2), exit_succeed(3)]


def test_supports_a_piped_callback_that_skips_failures_and_caches_successes() -> None:
    """supports a piped callback that skips failures and caches successes"""
    count = 0
    exits: list[fx.Exit[int, str]] = []

    def body() -> fx.Effect[int, str]:
        nonlocal count
        count += 1
        return fx.fail("boom") if count == 1 else fx.succeed(count)

    def ttl(ex: fx.Exit[int, str]) -> float:
        exits.append(ex)
        return 0 if isinstance(ex, fx.Failure) else millis(1000)

    @fx.gen
    def program():
        cached = yield from fx.suspend(body).cached_with_ttl(ttl)
        seen: list[object] = [(yield from cached.exit()), (yield from cached), (yield from cached)]
        seen.append(list(exits))
        yield from testing.adjust("1 second")
        seen.append((yield from cached))
        return seen

    assert testing.run_test(program.or_die()) == [
        exit_fail("boom"),
        2,
        2,
        [exit_fail("boom"), exit_succeed(2)],
        3,
    ]
    assert exits == [exit_fail("boom"), exit_succeed(2), exit_succeed(3)]


def test_starts_ttl_from_value_creation() -> None:
    """starts ttl from value creation"""
    count = 0

    def bump() -> int:
        nonlocal count
        count += 1
        return count

    @fx.gen
    def program():
        cached = (
            yield from fx.sleep("2 seconds").and_then(fx.sync(bump)).cached_with_ttl("1 second")
        )
        first_fiber = yield from cached.fork()
        yield from fx.yield_now()
        yield from testing.adjust("2 seconds")
        first = yield from first_fiber.join()
        second_fiber = yield from cached.fork()
        yield from fx.yield_now()
        yield from testing.adjust("2 seconds")
        return first, (yield from second_fiber.join())

    assert testing.run_test(program) == (1, 1)
    assert count == 1


# --- cachedInvalidateWithTTL ------------------------------------------------------------


def test_invalidate_supports_a_piped_callback_that_skips_failures_and_caches_successes() -> None:
    """supports a piped callback that skips failures and caches successes"""
    count = 0
    exits: list[fx.Exit[int, str]] = []

    def body() -> fx.Effect[int, str]:
        nonlocal count
        count += 1
        return fx.fail("boom") if count == 1 else fx.succeed(count)

    def ttl(ex: fx.Exit[int, str]) -> float:
        exits.append(ex)
        return 0 if isinstance(ex, fx.Failure) else millis(1000)

    @fx.gen
    def program():
        cached, _ = yield from fx.suspend(body).cached_invalidate_with_ttl(ttl)
        seen: list[object] = [(yield from cached.exit()), (yield from cached), (yield from cached)]
        yield from testing.adjust("1 second")
        seen.append((yield from cached))
        return seen

    assert testing.run_test(program.or_die()) == [exit_fail("boom"), 2, 2, 3]
    assert exits == [exit_fail("boom"), exit_succeed(2), exit_succeed(3)]


def test_keeps_existing_callers_on_the_invalidated_run_without_replacing_the_new_value() -> None:
    """keeps existing callers on the invalidated run without letting it replace the new value"""
    runs = 0

    @fx.gen
    def program():
        release = yield from fx.Deferred[None].make()

        @fx.gen
        def body():
            nonlocal runs
            runs += 1
            run = runs
            if run == 1:
                yield from release.wait()
            return run

        cached, invalidate = yield from body.cached_invalidate_with_ttl("1 hour")
        owner = yield from cached.fork(start_immediately=True)
        seen = [runs]
        yield from invalidate
        fresh = yield from cached.fork(start_immediately=True)
        seen.append(runs)
        seen.append((yield from fresh.join()))
        yield from release.succeed(None)
        seen.append((yield from owner.join()))
        seen.append((yield from cached))
        seen.append(runs)
        return seen

    assert testing.run_test(program) == [1, 2, 2, 1, 2, 2]


def test_interrupts_an_invalidated_run_when_its_last_caller_is_interrupted() -> None:
    """interrupts an invalidated run when its last caller is interrupted"""
    runs = 0
    interrupted: list[int] = []

    def body() -> fx.Effect[int]:
        nonlocal runs
        runs += 1
        run = runs
        return fx.never.on_interrupt(fx.sync(lambda: interrupted.append(run)))

    @fx.gen
    def program():
        cached, invalidate = yield from fx.suspend(body).cached_invalidate_with_ttl("1 hour")
        first = yield from cached.fork(start_immediately=True)
        yield from invalidate
        second = yield from cached.fork(start_immediately=True)
        yield from first.interrupt()
        seen: list[object] = [list(interrupted)]
        third = yield from cached.fork(start_immediately=True)
        seen.append(runs)
        yield from second.interrupt()
        seen.append(list(interrupted))
        yield from third.interrupt()
        seen.append(list(interrupted))
        return seen

    assert testing.run_test(program) == [[1], 2, [1], [1, 2]]


# --- timeoutOrElse ------------------------------------------------------------------------


def test_factory_and_body_follow_cleanup_and_replay() -> None:
    """data-first: factory and body follow cleanup and replay"""
    stopped = False
    factories = 0
    bodies = 0
    order: list[str] = []
    value = {"fallback": True}

    def stop() -> None:
        nonlocal stopped
        stopped = True
        order.append("stopped")

    def body() -> dict[str, bool]:
        nonlocal bodies
        bodies += 1
        order.append(f"body:{stopped}")
        return value

    def or_else() -> fx.Effect[dict[str, bool]]:
        nonlocal factories
        factories += 1
        order.append(f"factory:{stopped}")
        return fx.sync(body)

    program = fx.never.ensuring(fx.sync(stop)).timeout_or_else(0, or_else)
    before = [factories, bodies]
    first = fx.run_blocking(program)
    first_stopped = stopped
    stopped = False
    second = fx.run_blocking(program)
    assert before == [0, 0]
    assert (factories, bodies) == (2, 2)
    assert (first_stopped, stopped) == (True, True)
    assert (first is value, second is value) == (True, True)
    assert order == [
        "stopped",
        "factory:True",
        "body:True",
        "stopped",
        "factory:True",
        "body:True",
    ]


def test_a_ready_source_value_is_not_confused_with_a_zero_duration_timeout() -> None:
    """a ready source value is not confused with a zero-duration timeout"""
    calls = 0

    def or_else() -> fx.Effect[fx.Option[str]]:
        nonlocal calls
        calls += 1
        return fx.succeed(fx.Some("unexpected fallback"))

    result = fx.run_blocking(fx.succeed(None).timeout_or_else(0, or_else))
    assert (result, calls) == (None, 0)


def test_slow_fallback_cannot_let_the_original_source_win_after_timeout() -> None:
    """slow fallback cannot let the original source win after timeout"""
    value = {"fallback": True}
    fallback_interrupted = False

    def mark_interrupted() -> None:
        nonlocal fallback_interrupted
        fallback_interrupted = True

    @fx.gen
    def program():
        source_gate = yield from fx.Deferred[None].make()
        source_stopped = yield from fx.Deferred[None].make()
        fallback_started = yield from fx.Deferred[None].make()
        fallback_release = yield from fx.Deferred[None].make()
        source_completed = yield from fx.Ref.make(False)
        source = (
            source_gate.wait()
            .and_then(source_completed.set(True))
            .as_({"source": True})
            .ensuring(source_stopped.succeed(None))
        )
        fallback = (
            fallback_started.succeed(None)
            .and_then(fallback_release.wait())
            .as_(value)
            .on_interrupt(fx.sync(mark_interrupted))
        )
        fiber = yield from source.timeout_or_else(0, lambda: fallback).fork()
        yield from fallback_started.wait()
        yield from source_gate.succeed(None)
        yield from source_stopped.wait()
        yield from fallback_release.succeed(None)
        completed = yield from source_completed.get()
        result = yield from fiber.join()
        return result is value, completed

    assert fx.run_blocking(program) == (True, False)
    assert fallback_interrupted is False


class SourceService(fx.Tag[str]): ...


class FallbackService(fx.Tag[str]): ...


class Local(fx.Reference[str]):
    @classmethod
    def default(cls) -> str:
        return "default"


def test_source_and_fallback_inherit_caller_context() -> None:
    """source and fallback inherit caller context"""
    observed: list[object] = []

    @fx.gen
    def caller():
        caller_id = yield from fx.fiber_id()
        parent_span = yield from fx.current_span().or_die()

        @fx.gen
        def source_body():
            observed.append((yield from SourceService()))
            observed.append((yield from Local()))
            observed.append((yield from fx.current_span().or_die()) is parent_span)
            return (yield from fx.never)

        @fx.gen
        def fallback():
            annotations = yield from fx.CurrentLogAnnotations()
            observed.append((yield from fx.fiber_id()) == caller_id)
            observed.append((yield from Local()))
            observed.append((yield from fx.current_span().or_die()) is parent_span)
            observed.append(annotations["request"])
            return (yield from FallbackService())

        source = source_body.pipe(fx.provide_service(Local, "source-local"))
        value = yield from source.timeout_or_else(0, lambda: fallback)
        observed.append((yield from Local()))
        observed.append((yield from fx.current_span().or_die()) is parent_span)
        return value

    program = (
        caller.pipe(fx.provide_service(SourceService, "source service"))
        .pipe(fx.provide_service(FallbackService, "fallback service"))
        .pipe(fx.provide_service(Local, "parent-local"))
        .annotate_logs({"request": "request-value"})
        .with_span("timeout-parent")
    )
    assert fx.run_blocking(program) == "fallback service"
    assert observed == [
        "source service",
        "source-local",
        True,
        True,
        "parent-local",
        True,
        "request-value",
        "parent-local",
        True,
    ]


def test_external_interruption_stops_a_pending_fallback() -> None:
    """external interruption stops a pending fallback"""
    source_stopped = False
    fallback_stopped = False
    calls = 0

    def stop_source() -> None:
        nonlocal source_stopped
        source_stopped = True

    def stop_fallback() -> None:
        nonlocal fallback_stopped
        fallback_stopped = True

    @fx.gen
    def program():
        started = yield from fx.Deferred[None].make()

        def or_else() -> fx.Effect[None]:
            nonlocal calls
            calls += 1
            return started.succeed(None).and_then(fx.never).ensuring(fx.sync(stop_fallback))

        fiber = (
            yield from fx.never.ensuring(fx.sync(stop_source)).timeout_or_else(0, or_else).fork()
        )
        yield from started.wait()
        yield from fiber.interrupt()
        return (yield from fiber.await_exit())

    ex = fx.run_blocking(program)
    assert [_interrupted(ex), source_stopped, fallback_stopped, calls] == [True, True, True, 1]


# --- timeoutOption ------------------------------------------------------------------------


def test_timeout_option_timeout_a_long_computation() -> None:
    """timeout a long computation"""
    eff = fx.sleep("1 minute").and_then(fx.succeed(True)).timeout_option("10 millis")
    assert fx.run_blocking(eff) is None


def test_timeout_a_long_computation_with_a_failure() -> None:
    """timeout a long computation with a failure"""
    error = RuntimeError("boom")
    eff = (
        fx.sleep("5 seconds")
        .and_then(fx.succeed(True))
        .timeout_or_else("10 millis", lambda: fx.die(error))
        .sandbox()
        .flip()
        .or_die()
    )
    assert fx.run_blocking(eff) == fx.cause.die(error)


def test_timeout_repetition_of_uninterruptible_effect() -> None:
    """timeout repetition of uninterruptible effect"""

    @fx.gen
    def program():
        fiber = yield from fx.void.uninterruptible().forever().timeout_option("10 millis").fork()
        yield from testing.adjust("10 millis")
        return (yield from fiber.join())

    with warnings.catch_warnings():
        warnings.simplefilter("error", testing.BusyFiberWarning)
        assert testing.run_test(program, warning_delay="10 millis") is None


def test_timeout_in_uninterruptible_region() -> None:
    """timeout in uninterruptible region"""
    assert testing.run_test(fx.void.timeout_option("20 seconds").uninterruptible()) == fx.Some(None)


# --- timeout ------------------------------------------------------------------------------


def test_timeout_produces_a_useful_error_message() -> None:
    """timeout produces a useful error message"""

    @fx.gen
    def program():
        fiber = yield from fx.never.timeout("1500 millis").flip().fork()
        yield from testing.adjust("2 seconds")
        return (yield from fiber.join())

    assert "Operation timed out after '1s 500ms'" in str(testing.run_test(program))


def test_timeout_timeout_a_long_computation() -> None:
    """timeout a long computation"""
    error = fx.run_blocking(
        fx.sleep("1 minute").and_then(fx.succeed(True)).timeout("10 millis").flip().or_die()
    )
    assert isinstance(error, fx.TimeoutException)
    assert str(error) == "Operation timed out after '10ms'"


def test_timeout_interrupts_the_effect() -> None:
    """timeout interrupts the effect"""
    interrupted = False

    def mark() -> None:
        nonlocal interrupted
        interrupted = True

    @fx.gen
    def program():
        fiber = yield from fx.never.on_interrupt(fx.sync(mark)).timeout("10 millis").flip().fork()
        yield from testing.adjust("10 millis")
        return (yield from fiber.join())

    error = testing.run_test(program)
    assert str(error) == "Operation timed out after '10ms'"
    assert interrupted


# --- raceAllFirst -------------------------------------------------------------------------


def test_race_all_first() -> None:
    """raceAllFirst"""
    interrupted: list[int] = []

    def racer(ms: int) -> fx.Effect[int, str]:
        eff: fx.Effect[int, str] = fx.fail("boom") if ms == 0 else fx.succeed(ms)
        return eff.delay(Duration(ms / 1000)).on_interrupt(fx.sync(lambda: interrupted.append(ms)))

    @fx.gen
    def program():
        racers = [racer(ms) for ms in (500, 300, 200, 0, 100)]
        fiber = yield from fx.race_all_first(*racers).exit().fork()
        yield from testing.adjust("500 millis")
        return (yield from fiber.join())

    assert testing.run_test(program) == exit_fail("boom")
    # 100 is interrupted before it starts, so its finalizer never runs.
    assert interrupted == [500, 300, 200]


# --- acquireDisposable --------------------------------------------------------------------


def test_releases_disposables() -> None:
    """releases disposables"""
    released: list[str] = []

    @contextmanager
    def resource():
        yield "r"
        released.append("r")

    assert fx.run_blocking(fx.scoped(fx.acquire_context(fx.sync(resource)))) == "r"
    assert released == ["r"]


def test_releases_async_disposables() -> None:
    """releases async disposables"""
    released: list[str] = []

    class Resource:
        async def __aenter__(self) -> str:
            return "r"

        async def __aexit__(
            self,
            exc_type: type[BaseException] | None,
            exc: BaseException | None,
            tb: TracebackType | None,
        ) -> None:
            released.append("r")

    eff = fx.scoped(fx.acquire_async_context(fx.sync(Resource)))
    assert asyncio.run(fx.run_async(eff)) == "r"
    assert released == ["r"]


# --- Fiber.test.ts: interruptibleMask -----------------------------------------------------


def test_delivers_a_pending_interrupt_when_interruptible_mask_restores_interruptibility() -> None:
    """delivers a pending interrupt when interruptibleMask restores interruptibility"""
    events: list[str] = []

    def body() -> fx.Effect[None]:
        events.append("interruptibleMask")
        return fx.never

    @fx.gen
    def program():
        # Latches, as in Effect: ``open`` wakes its waiters in a scheduled
        # task, so "resumed" is logged before the child goes on.
        masked = yield from fx.Latch.make()
        resume = yield from fx.Latch.make()

        @fx.gen
        def child_body():
            yield from masked.open()
            yield from resume.wait()
            return (yield from fx.interruptible_mask(lambda _restore: body()))

        child = yield from child_body.uninterruptible().fork(start_immediately=True)
        yield from masked.wait()
        events.append("masked")
        yield from fx.sync(lambda: child.interrupt_as_unsafe(123))
        events.append("interrupted")
        polled_early = child.poll_unsafe()
        yield from resume.open()
        events.append("resumed")
        yield from fx.yield_now()
        yield from fx.yield_now()
        return polled_early, child.poll_unsafe()

    polled_early, ex = testing.run_test(program)
    assert polled_early is None
    assert ex is not None
    assert isinstance(ex, fx.Failure)
    assert ex.cause.interruptors == frozenset({123})
    assert events == ["masked", "interrupted", "resumed", "interruptibleMask"]


@testing.effect
def test_timed_uses_monotonic_time_when_wall_time_moves_backward():
    """Effect.test.ts "timed > uses monotonic time when wall time moves backward"."""
    yield from testing.set_time(1_000)

    @fx.gen
    def body():
        yield from testing.adjust("100 millis")
        yield from testing.set_time(0)
        return "done"

    duration, result = yield from body.timed()
    assert result == "done"
    assert duration == 0.1


@testing.effect
def test_cached_with_ttl_expires_exactly_at_the_deadline():
    """Not an Effect title (checked against Effect's millisecond deadline,
    ``now < expiresAt``): computed at 100 ms with a 200 ms TTL, the value
    is recomputed at 300 ms. In float seconds ``0.1 + 0.2 > 0.3`` kept it."""
    runs: list[int] = []
    cached = yield from fx.sync(lambda: runs.append(1) or len(runs)).cached_with_ttl("200 millis")
    yield from testing.adjust("100 millis")
    assert (yield from cached) == 1
    yield from testing.adjust("200 millis")
    assert (yield from cached) == 2


@testing.effect
def test_unbounded_fail():
    """forEach / unbounded fail"""
    done: list[int] = []

    def visit(i: int) -> fx.Effect[int, str]:
        def run() -> fx.Effect[int, str]:
            done.append(i)
            return fx.fail("error") if i == 3 else fx.succeed(i)

        return fx.suspend(run).delay(Duration(i * 0.1))

    handle = yield from fx.for_each([1, 2, 3, 4, 5], visit, concurrency="unbounded").fork()
    yield from testing.adjust("500 millis")
    assert (yield from handle.await_exit()) == fx.exit.fail("error")
    assert done == [1, 2, 3]
