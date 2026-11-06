"""Ports of the ``Effect.test.ts`` titles the section ports left out: the
finalization and acquireUseRelease cases, the interruption and
uninterruptibleMask block, the forEach worker cases, raceAll's election,
deep map continuations and the generator protocol.

Each test's docstring is the Effect test title. ``interruptUnsafe(id)`` is
``interrupt_as_unsafe(id)``; ``Latch.await`` is ``wait()``.

Omitted, with the reason:

- "gen with context": ``Effect.gen({ self }, f)`` binds JavaScript's
  ``this``; a generator method of a class closes over ``self`` already.
- "should pass structural comparison" / "should fail structural
  comparison": they ``deepEqual`` effect objects field by field; Python
  effects compare by identity.
- "AbortSignal is aborted": the ``abortSignal`` section 4 row (``callback``
  takes a cleanup effect instead).
- the three ``effectify`` titles: the ``effectify`` section 4 row (Node
  callback APIs).
- "Effectable.Class" titles: ported in ``test_effectable.py``.
- "Deferred.await resumes in the awaiter's context" and "Pool.get resumes in
  the waiter's context": ported in ``test_context_vars_resume.py`` with
  ``contextvars`` for ``AsyncLocalStorage``.
"""

import random
import threading
from collections.abc import Callable
from typing import Any, Never

import pyfect as fx
from pyfect import testing
from pyfect.cause import Die
from pyfect.exit import Exit, Failure
from pyfect.exit import die as exit_die
from pyfect.exit import fail as exit_fail


class ExampleError(Exception):
    pass


EXAMPLE = ExampleError("Oh noes!")


def _interrupted(ex: Exit[Any, Any] | None) -> bool:
    return isinstance(ex, Failure) and ex.cause.has_interrupts


def _set(flags: dict[str, Any], key: str, value: Any = True) -> fx.Effect[None]:
    return fx.sync(lambda: flags.__setitem__(key, value))


# --- finalization -----------------------------------------------------------------


@testing.effect
def test_fail_ensuring():
    """fail ensuring"""
    flags: dict[str, Any] = {}
    result = yield from fx.fail(EXAMPLE).ensuring(_set(flags, "finalized")).exit()
    assert result == exit_fail(EXAMPLE)
    assert flags == {"finalized": True}


@testing.effect
def test_fail_on_error():
    """fail on error"""
    flags: dict[str, Any] = {}
    result = yield from fx.fail(EXAMPLE).on_error(lambda _: _set(flags, "finalized")).exit()
    assert result == exit_fail(EXAMPLE)
    assert flags == {"finalized": True}


@testing.effect
def test_finalizer_errors_reported():
    """finalizer errors reported"""
    reported: list[Exit[int, Never]] = []
    fiber = yield from fx.succeed(42).ensuring(fx.die(EXAMPLE)).fork()
    ex = yield from fiber.await_exit()
    reported.append(ex)
    assert reported[0] == exit_die(EXAMPLE)


@testing.effect
def test_acquire_use_release_usage_result():
    """acquireUseRelease usage result"""
    result = yield from fx.acquire_use_release(
        fx.void, lambda _: fx.succeed(42), lambda _r, _e: fx.void
    )
    assert result == 42


@testing.effect
def test_error_in_just_acquisition():
    """error in just acquisition"""
    acquire: fx.Effect[None, ExampleError] = fx.fail(EXAMPLE)
    result = yield from fx.acquire_use_release(
        acquire, lambda _: fx.void, lambda _r, _e: fx.void
    ).exit()
    assert result == exit_fail(EXAMPLE)


@testing.effect
def test_error_in_just_release():
    """error in just release"""
    result = yield from fx.acquire_use_release(
        fx.void, lambda _: fx.void, lambda _r, _e: fx.die(EXAMPLE)
    ).exit()
    assert result == exit_die(EXAMPLE)


@testing.effect
def test_error_in_just_usage():
    """error in just usage"""
    use: fx.Effect[None, ExampleError] = fx.fail(EXAMPLE)
    result = yield from fx.acquire_use_release(
        fx.void, lambda _: use, lambda _r, _e: fx.void
    ).exit()
    assert result == exit_fail(EXAMPLE)


@testing.effect
def test_rethrown_caught_error_in_acquisition():
    """rethrown caught error in acquisition"""
    acquire: fx.Effect[None, ExampleError] = fx.fail(EXAMPLE)
    error = yield from fx.acquire_use_release(
        acquire, lambda _: fx.void, lambda _r, _e: fx.void
    ).flip()
    assert error is EXAMPLE


@testing.effect
def test_rethrown_caught_error_in_release():
    """rethrown caught error in release"""
    result = yield from fx.acquire_use_release(
        fx.void, lambda _: fx.void, lambda _r, _e: fx.die(EXAMPLE)
    ).exit()
    assert result == exit_die(EXAMPLE)


@testing.effect
def test_rethrown_caught_error_in_usage():
    """rethrown caught error in usage"""
    use: fx.Effect[None, ExampleError] = fx.fail(EXAMPLE)
    result = yield from fx.acquire_use_release(
        fx.void, lambda _: use, lambda _r, _e: fx.void
    ).exit()
    assert result == exit_fail(EXAMPLE)


@testing.effect
def test_on_result_ensures_that_a_cleanup_function_runs_when_an_effect_fails():
    """onResult - ensures that a cleanup function runs when an effect fails"""
    flags: dict[str, Any] = {}
    yield from (
        fx.die(RuntimeError("boom"))
        .on_exit(
            lambda ex: _set(flags, "ref") if isinstance(ex, Failure) and ex.has_dies else fx.void
        )
        .sandbox()
        .ignore()
    )
    assert flags == {"ref": True}


@testing.effect
def test_on_exit_callback_observes_interrupt_exit_when_the_fiber_is_interrupted():
    """onExit - callback observes interrupt exit when the fiber is interrupted"""
    flags: dict[str, Any] = {}
    fiber = yield from fx.never.on_exit(lambda ex: _set(flags, "interrupt", _interrupted(ex))).fork(
        start_immediately=True
    )
    yield from fiber.interrupt()
    assert flags == {"interrupt": True}


# --- interruption -----------------------------------------------------------------


@testing.effect
def test_catch_ensuring_interrupt():
    """catch + ensuring + interrupt"""
    flags: dict[str, Any] = {}
    handle = yield from (
        fx.never.catch_cause(lambda _: _set(flags, "catch_failure"))
        .ensuring(_set(flags, "ensuring"))
        .fork(start_immediately=True)
    )
    yield from handle.interrupt()
    assert flags == {"ensuring": True}


@testing.effect
def test_run_of_interruptible():
    """run of interruptible"""
    flags: dict[str, Any] = {}
    fiber = yield from (
        fx.never.interruptible()
        .exit()
        .flat_map(
            lambda ex: _set(
                flags, "recovered", isinstance(ex, Failure) and ex.cause.has_interrupts_only
            )
        )
        .uninterruptible()
        .fork(start_immediately=True)
    )
    yield from fiber.interrupt()
    assert flags == {"recovered": True}


@testing.effect
def test_alternating_interruptibility():
    """alternating interruptibility"""
    counter: list[int] = []
    bump = fx.sync(lambda: counter.append(1))
    fiber = yield from (
        fx.never.interruptible()
        .exit()
        .and_then(bump)
        .uninterruptible()
        .interruptible()
        .exit()
        .and_then(bump)
        .uninterruptible()
        .fork(start_immediately=True)
    )
    yield from fiber.interrupt()
    assert len(counter) == 2


@testing.live
def test_acquire_use_release_use_inherits_interrupt_status():
    """acquireUseRelease use inherits interrupt status"""
    flags: dict[str, Any] = {}
    fiber = yield from (
        fx.acquire_use_release(
            fx.succeed(123),
            lambda _: _set(flags, "ref").delay(0.01),
            lambda _r, _e: fx.void,
        )
        .uninterruptible()
        .fork(start_immediately=True)
    )
    yield from fiber.interrupt()
    assert flags == {"ref": True}


@testing.effect
def test_acquire_use_release_release_runs_when_use_is_interrupted():
    """acquireUseRelease release runs when use is interrupted"""
    flags: dict[str, Any] = {}

    def acquire() -> int:
        flags["acquired"] = True
        return 123

    def release(resource: int, ex: Exit[Never, Never]) -> fx.Effect[None]:
        assert resource == 123
        return _set(flags, "release_exit", ex)

    fiber = yield from fx.acquire_use_release(fx.sync(acquire), lambda _: fx.never, release).fork(
        start_immediately=True
    )
    yield from fiber.interrupt()
    assert flags["acquired"] is True
    assert _interrupted(flags["release_exit"])
    assert _interrupted(fiber.poll_unsafe())


@testing.live
def test_async_can_be_uninterruptible():
    """async can be uninterruptible"""
    flags: dict[str, Any] = {}
    fiber = yield from (
        fx.sleep(0.01).and_then(_set(flags, "ref")).uninterruptible().fork(start_immediately=True)
    )
    yield from fiber.interrupt()
    assert flags == {"ref": True}


@testing.live
def test_callback_cannot_resume_on_interrupt():
    """callback cannot resume on interrupt"""

    def register(resume: Callable[[fx.Effect[str]], None]) -> None:
        threading.Timer(0.01, resume, (fx.succeed("foo"),)).start()

    waiting: fx.Effect[str] = fx.callback(register)
    fiber = yield from (waiting.on_interrupt(fx.sleep(0.03)).fork(start_immediately=True))
    yield from fiber.interrupt()
    assert _interrupted(fiber.poll_unsafe())


@testing.effect
def test_handlers_inside_an_uninterruptible_region_recover_with_interruption_pending():
    """handlers inside an uninterruptible region recover with interruption pending"""
    latch = yield from fx.Latch.make()
    flags: dict[str, Any] = {}
    failing: fx.Effect[None, str] = latch.wait().and_then(fx.fail("error"))
    fiber = yield from (
        failing.catch_all(lambda _: _set(flags, "recovered"))
        .uninterruptible()
        .fork(start_immediately=True)
    )
    fiber.interrupt_as_unsafe(123)
    yield from latch.open()
    ex = yield from fiber.await_exit()
    assert flags == {"recovered": True}
    assert _interrupted(ex)


class _HashBomb(Exception):
    """A defect whose ``__hash__`` raises itself its first ``limit`` calls,
    as Effect's test throws the defect from ``Hash.symbol``."""

    def __init__(self, limit: int) -> None:
        super().__init__("bomb")
        self.limit = limit
        self.calls = 0

    def __hash__(self) -> int:
        self.calls += 1
        if self.calls <= self.limit:
            raise self
        return 0

    def __eq__(self, other: object) -> bool:
        return other is self


@testing.effect
def test_a_defect_that_throws_when_hashed_still_terminates_an_interrupted_fiber():
    """a defect that throws when hashed still terminates an interrupted fiber"""
    defect = _HashBomb(1_000)
    finalized: list[int] = []
    child = yield from (
        fx.never.on_interrupt(fx.die(defect)).ensuring(fx.sync(lambda: finalized.append(1))).fork()
    )
    yield from fx.yield_now()
    yield from child.interrupt()
    ex = yield from child.await_exit()
    # Effect under Node: one hash call, then [Die(defect), Interrupt].
    assert finalized == [1]
    assert defect.calls == 1
    assert isinstance(ex, Failure)
    assert [type(r) for r in ex.cause.reasons] == [Die, fx.cause.Interrupt]
    assert ex.cause.defects[0] is defect


def test_interrupting_a_fiber_does_not_call_math_random(monkeypatch: Any) -> None:
    """interrupting a fiber does not call Math.random"""
    calls: list[str] = []

    def forbidden(name: str) -> Any:
        def call(*_args: object) -> Never:
            calls.append(name)
            raise AssertionError(f"random.{name} is not allowed")

        return call

    class DefectError(Exception):
        pass

    @fx.gen
    def program():
        latch = yield from fx.Latch.make()
        child = yield from (
            latch.wait()
            .and_then(fx.die(DefectError()))
            .uninterruptible()
            .fork(start_immediately=True)
        )
        yield from latch.open()
        child.interrupt_as_unsafe(None)
        child.interrupt_as_unsafe(None)
        return (yield from child.await_exit())

    for name in ("random", "getrandbits", "randrange", "randint"):
        monkeypatch.setattr(random, name, forbidden(name))
    ex = fx.run_blocking(program)
    monkeypatch.undo()
    assert calls == []
    assert isinstance(ex, Failure)
    assert ex.cause.has_dies
    assert ex.cause.has_interrupts


# --- uninterruptibleMask ----------------------------------------------------------


@testing.effect
def test_defers_a_pending_interrupt_until_the_masked_region_completes():
    """defers a pending interrupt until the masked region completes"""
    masked = yield from fx.Latch.make()
    resume = yield from fx.Latch.make()
    events: list[str] = []

    @fx.gen
    def region():
        yield from masked.open()
        yield from resume.wait()
        events.append("masked region completed")

    child = yield from fx.uninterruptible_mask(lambda _restore: region).fork(start_immediately=True)
    yield from masked.wait()
    events.append("masked")
    child.interrupt_as_unsafe(123)
    events.append("interrupted")
    assert child.poll_unsafe() is None
    yield from resume.open()
    events.append("resumed")
    yield from fx.yield_now()
    yield from fx.yield_now()
    ex = child.poll_unsafe()
    assert isinstance(ex, Failure)
    assert ex.cause.interruptors == frozenset({123})
    assert events == ["masked", "interrupted", "resumed", "masked region completed"]


@testing.effect
def test_delivers_a_pending_interrupt_when_restore_re_enables_interruptibility():
    """delivers a pending interrupt when restore re-enables interruptibility"""
    masked = yield from fx.Latch.make()
    resume = yield from fx.Latch.make()
    events: list[str] = []

    def restored() -> fx.Effect[Never]:
        events.append("restored")
        return fx.never

    def region(restore: fx.Restore):
        @fx.gen
        def body():
            yield from masked.open()
            yield from resume.wait()
            return (yield from restore(fx.suspend(restored)))

        return body

    child = yield from fx.uninterruptible_mask(region).fork(start_immediately=True)
    yield from masked.wait()
    events.append("masked")
    child.interrupt_as_unsafe(123)
    events.append("interrupted")
    assert child.poll_unsafe() is None
    yield from resume.open()
    events.append("resumed")
    yield from fx.yield_now()
    yield from fx.yield_now()
    ex = child.poll_unsafe()
    assert isinstance(ex, Failure)
    assert ex.cause.interruptors == frozenset({123})
    assert events == ["masked", "interrupted", "resumed"]


@testing.effect
def test_region_after_a_restored_section_stays_uninterruptible():
    """region after a restored section stays uninterruptible"""
    after_restore = yield from fx.Latch.make()
    resume = yield from fx.Latch.make()
    events: list[str] = []

    def region(restore: fx.Restore):
        @fx.gen
        def body():
            yield from restore(fx.sync(lambda: events.append("restored section completed")))
            yield from after_restore.open()
            yield from resume.wait()
            events.append("masked region completed")

        return body

    child = yield from fx.uninterruptible_mask(region).fork(start_immediately=True)
    yield from after_restore.wait()
    events.append("after restore")
    child.interrupt_as_unsafe(123)
    events.append("interrupted")
    assert child.poll_unsafe() is None
    yield from resume.open()
    events.append("resumed")
    yield from fx.yield_now()
    yield from fx.yield_now()
    ex = child.poll_unsafe()
    assert isinstance(ex, Failure)
    assert ex.cause.interruptors == frozenset({123})
    assert events == [
        "restored section completed",
        "after restore",
        "interrupted",
        "resumed",
        "masked region completed",
    ]


# --- raceAll ----------------------------------------------------------------------


@testing.effect
def test_race_all_elects_typed_failures_when_all_racers_fail_and_one_dies():
    """raceAll elects typed failures when all racers fail and one dies"""
    failing: fx.Effect[Never, str] = fx.fail("error")
    defect = RuntimeError("defect")
    ex = yield from fx.race_all(failing, fx.die(defect)).exit()
    # Electing a typed error that is not an exception wraps it, so the defect
    # can be raised (section 4, ``Cause.squash``).
    assert isinstance(ex, Failure)
    first, second = ex.cause.reasons
    assert isinstance(first, Die)
    assert first.defect == "error"
    assert second == Die(defect)


# --- forEach ----------------------------------------------------------------------


class MapperDefect(Exception):
    pass


@testing.effect
def test_interrupts_started_workers_when_the_mapper_throws_during_initial_pumping():
    """interrupts started workers when the mapper throws during initial pumping"""
    interrupt_started = yield from fx.Deferred[None].make()
    interrupt_finished = yield from fx.Deferred[None].make()
    defect = MapperDefect("mapper defect")

    def work(i: int) -> fx.Effect[None]:
        if i == 0:
            return fx.never.on_interrupt(
                interrupt_started.succeed(None).and_then(interrupt_finished.wait())
            )
        raise defect

    fiber = yield from fx.for_each([0, 1], work, concurrency=2).fork(start_immediately=True)
    assert (yield from interrupt_started.is_done())
    assert fiber.poll_unsafe() is None
    yield from interrupt_finished.succeed(None)
    ex = fiber.poll_unsafe()
    assert ex == exit_die(defect)


@testing.effect
def test_preserves_a_sibling_cleanup_defect_when_the_mapper_throws():
    """preserves a sibling cleanup defect when the mapper throws"""
    mapper_defect = MapperDefect("mapper defect")
    cleanup_defect = MapperDefect("cleanup defect")
    cleaned_up: list[bool] = []

    def cleanup() -> Never:
        cleaned_up.append(True)
        raise cleanup_defect

    def work(i: int) -> fx.Effect[None]:
        if i == 0:
            return fx.callback(lambda _resume: fx.sync(cleanup))
        raise mapper_defect

    ex = yield from fx.for_each([0, 1], work, concurrency=2).exit()
    assert cleaned_up == [True]
    assert isinstance(ex, Failure)
    assert [r.defect for r in ex.cause.reasons if isinstance(r, Die)] == [
        mapper_defect,
        cleanup_defect,
    ]


@testing.effect
def test_interrupts_started_workers_when_observer_driven_refill_throws():
    """interrupts started workers when observer-driven refill throws"""
    release = yield from fx.Deferred[None].make()
    interrupt_started = yield from fx.Deferred[None].make()
    interrupt_finished = yield from fx.Deferred[None].make()
    defect = MapperDefect("refill defect")

    def work(i: int) -> fx.Effect[None]:
        if i == 0:
            return release.wait()
        if i == 1:
            return fx.never.on_interrupt(
                interrupt_started.succeed(None).and_then(interrupt_finished.wait())
            )
        raise defect

    fiber = yield from fx.for_each([0, 1, 2], work, concurrency=2).fork(start_immediately=True)
    assert fiber.poll_unsafe() is None
    yield from release.succeed(None)
    assert (yield from interrupt_started.is_done())
    assert fiber.poll_unsafe() is None
    yield from interrupt_finished.succeed(None)
    assert fiber.poll_unsafe() == exit_die(defect)


@testing.effect
def test_length_0():
    """length = 0"""
    empty: list[int] = []
    assert (yield from fx.for_each(empty, fx.succeed)) == []


# --- map, flatMap, gen ------------------------------------------------------------


def test_lazily_nested_map_continuations() -> None:
    """lazily nested map continuations"""

    def loop(n: int) -> fx.Effect[int]:
        if n == 0:
            return fx.succeed(0)
        return fx.suspend(lambda: loop(n - 1)).map(lambda m: m + 1)

    assert fx.run_blocking(loop(100_000)) == 100_000


def test_passes_only_the_value_to_callbacks_regardless_of_declared_arity() -> None:
    """passes only the value to callbacks regardless of declared arity"""

    def callback(*args: object) -> fx.Effect[int]:
        return fx.succeed(len(args))

    assert fx.run_blocking(fx.succeed(1).flat_map(callback)) == 1


def test_iterator_yields_the_effect_once_then_completes_with_the_sent_value() -> None:
    """iterator yields the effect once, then completes with the sent value"""
    effect = fx.succeed(1)
    iterator = iter(effect)
    assert next(iterator) is effect
    try:
        iterator.send(2)
    except StopIteration as stop:
        assert stop.value == 2
    else:
        raise AssertionError("the iterator did not complete")
    # A finished Python generator stops without a value (JavaScript's iterator
    # returns the sent value again).
    assert next(iterator, "done") == "done"
