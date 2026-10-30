"""Deferred completion API, named as in Effect v4: done, complete, complete_with."""

import pyfect as fx
from pyfect.exit import fail as fail_exit
from pyfect.exit import interrupt as interrupt_exit
from pyfect.exit import succeed as succeed_exit
from pyfect.testing import run_test as run
from pyfect.testing import run_test_exit as run_exit


def _counter(step: int, box: list[int]) -> fx.Effect[int]:
    def bump() -> int:
        box[0] += step
        return box[0]

    return fx.sync(bump)


def test_complete_memoizes_the_result_of_the_effect():
    """Effect: Deferred.test.ts 'complete - should memoize the result of the provided
    effect'."""
    box = [0]

    @fx.gen
    def program():
        d = yield from fx.Deferred[int].make()
        first = yield from d.complete(_counter(1, box))
        second = yield from d.complete(_counter(1, box))
        return first, second, (yield from d.wait()), (yield from d.wait())

    assert run(program) == (True, False, 1, 1)
    assert box == [1]


def test_complete_does_not_run_the_effect_when_already_done():
    log: list[str] = []

    @fx.gen
    def program():
        d = yield from fx.Deferred[int].make()
        yield from d.succeed(1)
        return (yield from d.complete(fx.sync(lambda: log.append("ran") or 2)))

    assert run(program) is False
    assert log == []


def test_complete_stores_the_interrupt_when_the_completing_fiber_is_interrupted():
    @fx.gen
    def program():
        d = yield from fx.Deferred[int].make()
        completer = yield from d.complete(fx.never).fork()
        yield from fx.yield_now()
        yield from completer.interrupt()
        return (yield from d.wait().exit())

    ex = run(program)
    assert isinstance(ex, fx.Failure) and ex.cause.has_interrupts_only


def test_complete_with_does_not_memoize_the_effect():
    """Effect: Deferred.test.ts 'completeWith - should not memoize the provided effect'."""
    box = [0]

    @fx.gen
    def program():
        d = yield from fx.Deferred[int].make()
        first = yield from d.complete_with(_counter(1, box))
        second = yield from d.complete_with(_counter(10, box))
        ran_before_wait = box[0]
        return first, second, ran_before_wait, (yield from d.wait()), (yield from d.wait())

    assert run(program) == (True, False, 0, 1, 2)


def test_done_completes_with_an_exit():
    @fx.gen
    def program():
        d = yield from fx.Deferred[int, str].make()
        first = yield from d.done(fail_exit("boom"))
        second = yield from d.done(succeed_exit(1))
        return first, second, (yield from d.wait())

    ex = run_exit(program)
    assert isinstance(ex, fx.Failure) and ex.cause.failures == ("boom",)


def test_done_with_an_interrupt_resumes_every_waiter():
    """Effect: Deferred.test.ts 'done with an interrupt cause resumes every suspended
    waiter'."""

    @fx.gen
    def program():
        d = yield from fx.Deferred[int].make()
        waiters = yield from fx.for_each(range(2), lambda _: d.wait().fork())
        yield from fx.yield_now()
        yield from d.done(interrupt_exit())
        return (yield from fx.for_each(waiters, lambda f: f.await_exit()))

    exits = run(program)
    assert all(isinstance(ex, fx.Failure) and ex.cause.has_interrupts_only for ex in exits)


def test_poll_returns_the_stored_effect():
    """Effect: Deferred.test.ts 'poll - should return Option.none when the deferred is
    incomplete' and 'poll - should return Option.some when the deferred was completed'."""

    @fx.gen
    def program():
        d = yield from fx.Deferred[int].make()
        before = yield from d.poll()
        yield from d.succeed(3)
        after = yield from d.poll()
        assert after is not None
        return before, (yield from after)

    assert run(program) == (None, 3)


@fx.testing.effect
def test_into_runs_the_effect_even_when_already_done():
    """Unlike ``complete``, Effect's ``Deferred.into`` runs its effect
    whatever the state; only the first completion counts."""
    log: list[str] = []
    d = yield from fx.Deferred[int].make()
    assert (yield from fx.succeed(1).pipe(d.into)) is True
    assert (yield from fx.sync(lambda: log.append("ran") or 2).pipe(d.into)) is False
    assert log == ["ran"]
    assert (yield from d.wait()) == 1


@fx.testing.effect
def test_lazy_completions_evaluate_once_when_run():
    calls: list[str] = []

    def value() -> int:
        calls.append("sync")
        return 7

    d = yield from fx.Deferred[int].make()
    complete = d.sync(value)
    assert calls == []
    assert (yield from complete) is True
    assert (yield from d.wait()) == 7
    assert calls == ["sync"]


@fx.testing.effect
def test_failure_shorthands_store_the_matching_cause():
    boom = ValueError("boom")
    died = yield from fx.Deferred[int].make()
    yield from died.die_sync(lambda: boom)
    failed = yield from fx.Deferred[int, str].make()
    yield from failed.fail_sync(lambda: "bad")
    failed_cause = yield from fx.Deferred[int, str].make()
    yield from failed_cause.fail_cause_sync(lambda: fx.cause.fail("worse"))

    assert (yield from died.wait().exit()) == fx.exit.die(boom)
    assert (yield from failed.wait().exit()) == fail_exit("bad")
    assert (yield from failed_cause.wait().exit()) == fail_exit("worse")
    assert died.is_done_unsafe()


@fx.testing.effect
def test_interrupt_is_attributed_to_the_current_fiber():
    d = yield from fx.Deferred[int].make()
    yield from d.interrupt()
    me = yield from fx.fiber_id()
    assert (yield from d.wait().exit()) == interrupt_exit(me)
