"""Ports of Effect's ``Scope.test.ts``.

Each test's docstring is the Effect test title. ``Scope.makeUnsafe`` is
``CloseableScope(strategy)``, ``Scope.forkUnsafe`` is ``scope._fork_now()``
and ``closeUnsafe`` is ``close_unsafe``. Effect's ``state._tag`` checks read
``is_empty`` (Effect's "Empty": open, no finalizers), ``finalizer_count``
and ``is_closed``. An ``AbortController`` signal is the cancellation of the asyncio
task awaiting ``run_async_exit``.

"a sole throwing finalizer keeps the scoped effect's failure" is ported in
``tests/test_cause_recovery.py`` next to the other defect-election cases.
"""
# pyright: reportPrivateUsage=false

import asyncio
from typing import Any, Literal

import pytest

import pyfect as fx
from pyfect import testing
from pyfect.scope import CloseableScope

type Strategy = Literal["sequential", "parallel"]
STRATEGIES: list[Strategy] = ["sequential", "parallel"]


def _reasons(ex: fx.Exit[Any, Any]) -> list[str]:
    if isinstance(ex, fx.Success):
        return []
    out: list[str] = []
    for reason in ex.cause.reasons:
        match reason:
            case fx.cause.Fail(error=error):
                out.append(f"fail:{error}")
            case fx.cause.Die(defect=defect):
                out.append(f"die:{defect}")
            case _:
                out.append("interrupt")
    return out


@testing.effect
def test_executes_finalizers_in_parallel():
    """executes finalizers in parallel"""
    scope = CloseableScope("parallel")
    for _ in range(3):
        yield from scope.add_finalizer(lambda _: fx.sleep(1.0))
    fiber = yield from scope.close(fx.Success(None)).fork(start_immediately=True)
    assert fiber.poll_unsafe() is None
    yield from testing.adjust(1.0)
    assert fiber.poll_unsafe() is not None


@pytest.mark.parametrize("strategy", STRATEGIES)
def test_completes_a_single_finalizer_when_its_callback_interrupts_close(strategy: Strategy):
    """{sequential,parallel}: completes a single finalizer when its callback
    interrupts close"""
    scope = CloseableScope(strategy)
    cleaned: list[bool] = []

    async def main() -> None:
        task: asyncio.Task[Any] | None = None

        def finalizer(_: fx.Exit[Any, Any]) -> fx.Effect[None]:
            assert task is not None
            task.cancel()
            return fx.sync(lambda: cleaned.append(True))

        fx.run_sync(scope.add_finalizer(finalizer))
        task = asyncio.ensure_future(
            fx.run_async_exit(fx.yield_now().and_then(scope.close(fx.Success(None))))
        )
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(main())
    assert cleaned == [True]


@pytest.mark.parametrize("strategy", STRATEGIES)
@testing.effect
def test_completes_direct_close_after_interruption(strategy: Strategy):
    """{sequential,parallel}: completes direct close after interruption"""
    scope = CloseableScope(strategy)
    started = yield from fx.Deferred[None].make()
    release = yield from fx.Deferred[None].make()
    other_started = yield from fx.Deferred[None].make()
    ran: list[str] = []

    @fx.gen
    def second():
        if strategy == "parallel":
            yield from other_started.succeed(None)
            yield from release.wait()
        ran.append("second")

    @fx.gen
    def first():
        yield from started.succeed(None)
        yield from release.wait()
        ran.append("first")

    yield from scope.add_finalizer(lambda _: second)
    yield from scope.add_finalizer(lambda _: first)

    closing = yield from scope.close(fx.Success(None)).fork(start_immediately=True)
    yield from started.wait()
    if strategy == "parallel":
        yield from other_started.wait()
    interrupting = yield from closing.interrupt().fork(start_immediately=True)
    yield from fx.yield_now()
    assert interrupting.poll_unsafe() is None
    yield from release.succeed(None)
    yield from interrupting.join()
    yield from closing.await_exit()
    yield from scope.close(fx.Success(None))
    if strategy == "parallel":
        ran.sort()
    assert ran == ["first", "second"]


@testing.effect
def test_close_unsafe_runs_finalizers_when_its_returned_effect_is_masked_by_the_caller():
    """closeUnsafe runs finalizers when its returned effect is masked by the caller"""
    scope = CloseableScope()
    started = yield from fx.Deferred[None].make()
    release = yield from fx.Deferred[None].make()
    ran: list[str] = []

    @fx.gen
    def first():
        yield from started.succeed(None)
        yield from release.wait()
        ran.append("first")

    yield from scope.add_finalizer(lambda _: fx.sync(lambda: ran.append("second")))
    yield from scope.add_finalizer(lambda _: first)

    finalizers = scope.close_unsafe(fx.Success(None))
    assert finalizers is not None
    closing = yield from finalizers.uninterruptible().fork(start_immediately=True)
    yield from started.wait()
    interrupting = yield from closing.interrupt().fork(start_immediately=True)
    yield from release.succeed(None)
    yield from interrupting.join()
    assert ran == ["first", "second"]


def test_close_unsafe_of_a_closed_or_empty_scope_has_nothing_to_run():
    """Effect's ``scopeCloseUnsafe`` returns ``undefined`` for a closed or an
    empty scope, but still closes the empty one."""
    empty = CloseableScope()
    assert empty.close_unsafe(fx.Success(None)) is None
    assert empty.is_closed
    assert empty.close_unsafe(fx.Success(None)) is None


@pytest.mark.parametrize("strategy", STRATEGIES)
@testing.effect
def test_continues_and_awaits_remaining_finalizers_after_a_throw(strategy: Strategy):
    """{sequential,parallel}: continues and awaits remaining finalizers after a throw"""
    scope = CloseableScope(strategy)
    log: list[str] = []

    def throwing(_: fx.Exit[Any, Any]) -> fx.Effect[None]:
        log.append("throwing")
        raise ValueError("release")

    yield from scope.add_finalizer(
        lambda _: fx.yield_now().and_then(fx.sync(lambda: log.append("remaining")))
    )
    yield from scope.add_finalizer(throwing)
    ex = yield from scope.close(fx.Success(None)).exit()
    assert log == ["throwing", "remaining"]
    assert _reasons(ex) == ["die:release"]


@testing.effect
def test_closing_a_child_removes_it_from_the_parent():
    """closing a child removes it from the parent"""
    parent = CloseableScope()
    child = parent._fork_now()
    assert child.is_empty
    assert parent.finalizer_count == 1
    yield from child.close(fx.Success(None))
    assert parent.finalizer_count == 0
    assert not child.is_empty


@testing.effect
def test_a_throwing_child_finalizer_does_not_leave_the_child_in_its_parent():
    """a throwing child finalizer does not leave the child in its parent"""
    parent = CloseableScope()
    child = parent._fork_now()

    def boom(_: fx.Exit[Any, Any]) -> fx.Effect[None]:
        raise RuntimeError("boom")

    yield from child.add_finalizer(boom)
    result = yield from child.close(fx.Success(None)).exit()
    assert isinstance(result, fx.Failure)
    assert child.is_closed
    assert parent.finalizer_count == 0 and not parent.is_closed


@testing.effect
def test_an_interrupted_close_does_not_leave_the_child_in_its_parent():
    """an interrupted close does not leave the child in its parent"""
    parent = CloseableScope()
    child = parent._fork_now()
    entered = yield from fx.Deferred[None].make()
    release = yield from fx.Deferred[None].make()
    yield from child.add_finalizer(lambda _: entered.succeed(None).and_then(release.wait()))
    fiber = yield from child.close(fx.Success(None)).fork(start_immediately=True)
    yield from entered.wait()
    interrupting = yield from fiber.interrupt().fork(start_immediately=True)
    yield from release.succeed(None)
    yield from interrupting.join()
    assert child.is_closed
    assert parent.finalizer_count == 0 and not parent.is_closed


@testing.effect
def test_closing_the_parent_closes_the_child_with_the_parents_exit_only_once():
    """closing the parent closes the child with the parent's exit only once"""
    parent = CloseableScope()
    child = parent._fork_now()
    exits: list[fx.Exit[Any, Any]] = []
    yield from child.add_finalizer(lambda ex: fx.sync(lambda: exits.append(ex)))
    failure = fx.exit.fail("parent failed")
    yield from parent.close(failure)
    yield from child.close(fx.Success(None))
    assert exits == [failure]


@pytest.mark.parametrize("budget", range(1, 12))
@pytest.mark.parametrize("strategy", STRATEGIES)
def test_an_interrupt_landing_anywhere_in_close_never_skips_the_finalizers(
    strategy: Strategy, budget: int
):
    """Effect's ``scopeClose`` makes the fiber uninterruptible before it marks
    the scope closed, so an interrupt arriving during close can't leave a
    closed scope whose finalizers never ran."""
    scope = CloseableScope(strategy)
    ran: list[str] = []

    @fx.gen
    def program():
        yield from scope.add_finalizer(lambda _: fx.sync(lambda: ran.append("a")))
        yield from scope.add_finalizer(lambda _: fx.sync(lambda: ran.append("b")))
        closing = yield from (
            fx.void.map(lambda _: None)
            .and_then(scope.close(fx.Success(None)))
            .pipe(fx.provide_service(fx.MaxOpsBeforeYield, budget))
            .fork(start_immediately=True)
        )
        yield from closing.interrupt()

    testing.run_test(program)
    if scope.is_closed:
        assert sorted(ran) == ["a", "b"]
    else:
        assert ran == []
