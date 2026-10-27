"""Ports of the ``schedule``, ``repeat`` and ``retry`` sections of Effect's
``Effect.test.ts``.

Each test's docstring is the Effect test title. Every title is ported.
Effect's option objects (``{ times, while, until, schedule }``) are keyword
arguments: ``eff.repeat(times=2)``, ``eff.retry(schedule=..., until=...)``.
"""

import pyfect as fx
from pyfect import schedule, testing
from pyfect.cause import Die, Fail
from pyfect.duration import ZERO
from pyfect.schedule import CurrentMetadata, Decision, Metadata, Stop


@testing.effect
def test_schedule_and_schedule_from_preserve_source_done_failures():
    """schedule and scheduleFrom preserve source Done failures"""

    def done() -> fx.Effect[int, fx.Done[int]]:
        return fx.fail(fx.Done(42))

    source = fx.suspend(done)
    policy = schedule.recurs(3)
    scheduled = yield from source.schedule(policy).exit()
    assert isinstance(scheduled, fx.Failure)
    assert scheduled.cause.reasons == (Fail(fx.Done(42)),)
    from_zero = yield from source.schedule_from(0, policy).exit()
    assert isinstance(from_zero, fx.Failure)
    assert from_zero.cause.reasons == (Fail(fx.Done(42)),)


@testing.effect
def test_returns_the_schedule_output_without_running_the_source_after_completion():
    """returns the schedule output without running the source after completion"""
    eff, n = counter()
    assert (yield from eff.schedule_from(0, schedule.recurs(3))) == 3
    assert n[0] == 3


@testing.effect
def test_fails_with_a_done_raised_by_the_repeated_effect():
    """fails with a Done raised by the repeated effect"""
    ex = yield from fx.fail(fx.Done(42)).repeat(schedule.recurs(3)).exit()
    assert isinstance(ex, fx.Failure)
    assert ex.cause.reasons == (Fail(fx.Done(42)),)


@testing.effect
def test_is_interruptible():
    """is interruptible"""
    fiber = yield from fx.void.forever().timeout_option(0.05).fork()
    yield from testing.adjust(0.05)
    assert (yield from fiber.join()) is None


@testing.effect
def test_does_not_retry_typed_failures_accompanied_by_finalizer_defects():
    """does not retry typed failures accompanied by finalizer defects"""
    attempts = 0
    cleanup_failed = RuntimeError("cleanup failed")

    def source() -> fx.Effect[None, str]:
        nonlocal attempts
        attempts += 1
        return fx.fail("error").ensuring(fx.die(cleanup_failed))

    ex = yield from fx.suspend(source).retry(schedule.recurs(1)).exit()
    assert attempts == 1
    assert isinstance(ex, fx.Failure)
    # Effect dies with the raw error "error"; a pyfect defect is an exception,
    # so the unhandled typed error is wrapped in ``UnhandledError``.
    first, second = ex.cause.reasons
    assert isinstance(first, Die)
    assert isinstance(first.defect, fx.UnhandledError)
    assert first.defect.error == "error"
    assert second == Die(cleanup_failed)


@testing.effect
def test_preserves_finalizer_defects_accompanying_schedule_completion():
    """preserves finalizer defects accompanying schedule completion"""
    cleanup_failed = RuntimeError("cleanup failed")

    def step(_now: float, _input: object) -> fx.Effect[Decision[int]]:
        return fx.succeed(Stop(42)).ensuring(fx.die(cleanup_failed))

    policy = schedule.from_step(fx.succeed(step))
    ex = yield from fx.void.repeat(policy).exit()
    assert isinstance(ex, fx.Failure)
    assert ex.cause.reasons == (Die(cleanup_failed),)


@testing.effect
def test_repeat_or_else_passes_source_done_failures_and_iteration_metadata_to_or_else():
    """repeatOrElse passes source Done failures and iteration metadata to orElse"""
    n = 0
    seen: list[tuple[object, int | None]] = []

    def source() -> fx.Effect[int, fx.Done[int]]:
        nonlocal n
        n += 1
        return fx.succeed(n) if n < 3 else fx.fail(fx.Done(42))

    def or_else(error: fx.Done[int], meta: Metadata[int, int] | None) -> fx.Effect[int]:
        seen.append((error, None if meta is None else meta.attempt))
        return fx.succeed(-1)

    result = yield from fx.suspend(source).repeat_or_else(schedule.recurs(10), or_else)
    assert result == -1
    assert n == 3
    assert seen == [(fx.Done(42), 2)]


def countdown() -> tuple[fx.Effect[int], list[int]]:
    """Effect's ``decrement.pipe(Effect.tap(increment))`` from 10: each run
    returns the next lower number and counts itself."""
    state = [10, 0]

    def step() -> int:
        state[0] -= 1
        state[1] += 1
        return state[0]

    return fx.sync(step), state


@testing.effect
def test_repeat_until_repeats_until_a_condition_is_true():
    """repeat/until - repeats until a condition is true"""
    eff, state = countdown()
    assert (yield from eff.repeat(until=lambda n: n == 0)) == 0
    assert state[1] == 10


@testing.effect
def test_repeat_until_repeats_until_an_effectful_condition_is_true():
    """repeat/until - repeats until an effectful condition is true"""
    eff, state = countdown()
    assert (yield from eff.repeat(until=lambda n: fx.succeed(n == 0))) == 0
    assert state[1] == 10


@testing.effect
def test_repeat_until_always_evaluates_at_least_once():
    """repeat/until - always evaluates at least once"""
    eff, state = countdown()
    yield from eff.repeat(until=lambda _: True)
    assert state[1] == 1


@testing.effect
def test_repeat_while_repeats_while_a_condition_is_true():
    """repeat/while - repeats while a condition is true"""
    eff, state = countdown()
    assert (yield from eff.repeat(while_=lambda n: n > 0)) == 0
    assert state[1] == 10


@testing.effect
def test_repeat_while_repeats_while_an_effectful_condition_is_true():
    """repeat/while - repeats while an effectful condition is true"""
    eff, state = countdown()
    assert (yield from eff.repeat(while_=lambda n: fx.succeed(n > 0))) == 0
    assert state[1] == 10


@testing.effect
def test_repeat_while_always_evaluates_at_least_once():
    """repeat/while - always evaluates at least once"""
    eff, state = countdown()
    yield from eff.repeat(while_=lambda _: False)
    assert state[1] == 1


def counter() -> tuple[fx.Effect[int], list[int]]:
    """Effect's ``Effect.sync(() => ++n)``."""
    n = [0]

    def bump() -> int:
        n[0] += 1
        return n[0]

    return fx.sync(bump), n


@testing.effect
def test_repeat_times():
    """repeat/times"""
    eff, n = counter()
    assert (yield from eff.repeat(times=2)) == 3
    assert n[0] == 3


@testing.effect
def test_repeat_schedule_repeats_according_to_the_specified_schedule():
    """repeat/schedule - repeats according to the specified schedule"""
    eff, _ = counter()
    assert (yield from eff.repeat(schedule.recurs(3))) == 3


@testing.effect
def test_repeat_schedule_with_until():
    """repeat/schedule - with until"""
    eff, n = counter()
    assert (yield from eff.repeat(schedule=schedule.recurs(3), until=lambda x: x == 3)) == 3
    assert n[0] == 3


@testing.effect
def test_repeat_schedule_with_while():
    """repeat/schedule - with while"""
    eff, n = counter()
    assert (yield from eff.repeat(schedule=schedule.recurs(3), while_=lambda x: x < 3)) == 3
    assert n[0] == 3


@testing.live
def test_nothing_on_success():
    """nothing on success"""
    count = 0

    def bump() -> None:
        nonlocal count
        count += 1

    yield from fx.sync(bump).retry(times=10000)
    assert count == 1


@testing.effect
def test_retry_until_retries_until_a_condition_is_true():
    """retry/until - retries until a condition is true"""
    eff, state = countdown()
    assert (yield from eff.flip().retry(until=lambda n: n == 0).flip()) == 0
    assert state[1] == 10


@testing.effect
def test_retry_until_retries_until_an_effectful_condition_is_true():
    """retry/until - retries until an effectful condition is true"""
    eff, state = countdown()
    assert (yield from eff.flip().retry(until=lambda n: fx.succeed(n == 0)).flip()) == 0
    assert state[1] == 10


def failing_counter(start_after: bool) -> tuple[fx.Effect[None, int], list[int]]:
    """Effect's ``Effect.failSync(() => n++)`` (or ``++n``)."""
    n = [0]

    def bump() -> int:
        n[0] += 1
        return n[0] if start_after else n[0] - 1

    return fx.fail_sync(bump), n


@testing.effect
def test_retry_until_always_evaluates_at_least_once():
    """retry/until - always evaluates at least once"""
    eff, n = failing_counter(start_after=False)
    yield from eff.retry(until=lambda _: True).flip()
    assert n[0] == 1


@testing.effect
def test_retry_while_retries_while_a_condition_is_true():
    """retry/while - retries while a condition is true"""
    eff, state = countdown()
    assert (yield from eff.flip().retry(while_=lambda n: n > 0).flip()) == 0
    assert state[1] == 10


@testing.effect
def test_retry_while_retries_while_an_effectful_condition_is_true():
    """retry/while - retries while an effectful condition is true"""
    eff, state = countdown()
    assert (yield from eff.flip().retry(while_=lambda n: fx.succeed(n > 0)).flip()) == 0
    assert state[1] == 10


@testing.effect
def test_retry_while_always_evaluates_at_least_once():
    """retry/while - always evaluates at least once"""
    eff, n = failing_counter(start_after=False)
    yield from eff.retry(while_=lambda _: False).flip()
    assert n[0] == 1


@testing.effect
def test_retry_schedule_retries_according_to_the_specified_schedule():
    """retry/schedule - retries according to the specified schedule"""
    eff, n = failing_counter(start_after=False)
    yield from eff.retry(schedule.recurs(3)).flip()
    assert n[0] == 4


@testing.effect
def test_retry_schedule_with_until():
    """retry/schedule - with until"""
    eff, n = failing_counter(start_after=True)
    yield from eff.retry(schedule=schedule.recurs(3), until=lambda x: x == 3).flip()
    assert n[0] == 3


@testing.effect
def test_retry_schedule_until_errors():
    """retry/schedule - until errors"""
    eff, n = failing_counter(start_after=True)
    result = yield from eff.retry(
        schedule=schedule.recurs(3), until=lambda _: fx.fail("boom")
    ).flip()
    assert n[0] == 1
    assert result == "boom"


@testing.effect
def test_retry_schedule_with_while():
    """retry/schedule - with while"""
    eff, n = failing_counter(start_after=True)
    yield from eff.retry(schedule=schedule.recurs(3), while_=lambda x: x < 3).flip()
    assert n[0] == 3


@testing.effect
def test_retry_schedule_while_errors():
    """retry/schedule - while errors"""
    eff, n = failing_counter(start_after=True)
    result = yield from eff.retry(
        schedule=schedule.recurs(3), while_=lambda _: fx.fail("boom")
    ).flip()
    assert n[0] == 1
    assert result == "boom"


@testing.effect
def test_retry_schedule_current_metadata():
    """retry/schedule - CurrentMetadata"""
    metadata: list[Metadata[object, object]] = []
    record = CurrentMetadata().flat_map(lambda m: fx.sync(lambda: metadata.append(m)))
    yield from record.flip().retry(schedule.recurs(3)).flip()

    def at(attempt: int, output: object) -> Metadata[object, object]:
        return Metadata(
            input=None,
            output=output,
            duration=ZERO,
            attempt=attempt,
            start=0.0,
            now=0.0,
            elapsed=0.0,
            elapsed_since_previous=0.0,
        )

    assert metadata == [at(0, None), at(1, 0), at(2, 1), at(3, 2)]
