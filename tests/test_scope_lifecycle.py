"""Scope bookkeeping: finalizers leave a scope when what they guard ends,
fork_scoped and closed scopes, parallel close."""

import pyfect as fx
from pyfect.scope import CloseableScope
from pyfect.testing import run_test as run


def in_scope[A, E](eff: fx.Effect[A, E, fx.Scope], scope: CloseableScope) -> fx.Effect[A, E]:
    return eff.pipe(fx.provide_service(fx.Scope, scope))


def test_closing_a_child_removes_it_from_the_parent():
    """Scope.test.ts: fork > closing a child removes it from the parent."""
    parent = CloseableScope()

    @fx.gen
    def program():
        child = yield from parent.fork()
        assert parent.finalizer_count == 1
        yield from child.close(fx.Success(None))

    run(program)
    assert parent.finalizer_count == 0


def test_a_throwing_child_finalizer_does_not_leave_the_child_in_its_parent():
    """Scope.test.ts: fork > a throwing child finalizer does not leave the
    child in its parent."""
    parent = CloseableScope()

    def boom(_: object) -> fx.Effect[None]:
        raise RuntimeError("boom")

    @fx.gen
    def program():
        child = yield from parent.fork()
        yield from child.add_finalizer(boom)
        return (yield from child.close(fx.Success(None)).exit())

    assert isinstance(run(program), fx.Failure)
    assert parent.finalizer_count == 0


def test_forking_a_closed_scope_gives_a_closed_child():
    parent = CloseableScope()
    log: list[str] = []

    @fx.gen
    def program():
        yield from parent.close(fx.Success(None))
        child = yield from parent.fork()
        yield from child.add_finalizer(lambda _: fx.sync(lambda: log.append("ran at once")))

    run(program)
    assert log == ["ran at once"]


def test_finished_fork_scoped_fibers_leave_the_scope():
    """internal/effect.ts forkIn: the fiber's finalizer is removed by an exit
    observer."""
    scope = CloseableScope()

    @fx.gen
    def program():
        for _ in range(100):
            fiber = yield from in_scope(fx.succeed(1).fork_scoped(), scope)
            yield from fiber.join()

    run(program)
    assert scope.finalizer_count == 0


def test_ten_thousand_fork_scoped_fibers_return_the_scope_to_baseline():
    scope = CloseableScope()

    @fx.gen
    def program():
        yield from scope.add_finalizer(lambda _: fx.void)
        baseline = scope.finalizer_count
        gate = yield from fx.Deferred[None].make()
        fork_one = in_scope(gate.wait().fork_scoped(), scope)
        fibers = yield from fx.for_each(range(10_000), lambda _: fork_one)
        assert scope.finalizer_count == baseline + 10_000
        yield from gate.succeed(None)
        for fiber in fibers:
            yield from fiber.join()
        return baseline

    baseline = run(program)
    assert scope.finalizer_count == baseline


def test_a_fork_scoped_fiber_can_close_its_own_scope():
    """internal/effect.ts fiberScopeFinalizer: the closing fiber skips its own
    finalizer instead of interrupting and awaiting itself."""
    scope = CloseableScope()
    log: list[str] = []

    @fx.gen
    def worker():
        yield from fx.yield_now()
        yield from scope.close(fx.Success(None))
        log.append("after")

    @fx.gen
    def program():
        fiber = yield from in_scope(worker.fork_scoped(), scope)
        return (yield from fiber.await_exit())

    assert run(program) == fx.Success(None)
    assert log == ["after"]


def test_fork_scoped_into_a_closed_scope_does_not_run_the_work():
    """Effect.test.ts: forkScoped > does not run work in an already-closed
    scope."""
    scope = CloseableScope()
    ran: list[int] = []

    @fx.gen
    def program():
        yield from scope.close(fx.Success(None))
        fiber = yield from in_scope(fx.sync(lambda: ran.append(1)).fork_scoped(), scope)
        return (yield from fiber.await_exit())

    ex = run(program)
    assert ran == []
    assert isinstance(ex, fx.Failure) and ex.cause.is_interrupted


def test_a_parallel_scope_runs_its_finalizers_concurrently():
    """internal/effect.ts scopeCloseFinalizers: a parallel scope forks every
    finalizer and awaits them all. The last-registered finalizer waits for
    the first, which a sequential close would only run afterwards."""
    log: list[str] = []

    @fx.gen
    def program():
        gate = yield from fx.Deferred[None].make()
        scope = CloseableScope("parallel")
        yield from scope.add_finalizer(lambda _: gate.succeed(None))
        yield from scope.add_finalizer(
            lambda _: gate.wait().timeout(1.0).result().map(lambda r: log.append(repr(r)))
        )
        yield from scope.close(fx.Success(None))

    fx.run_sync(program)
    assert log == ["Ok(value=None)"]


def test_a_fork_scoped_fiber_can_close_its_own_parallel_scope():
    """Effect.test.ts: forkIn > does not wait for the fiber that closes a
    parallel scope."""
    scope = CloseableScope("parallel")

    @fx.gen
    def program():
        sibling = yield from in_scope(fx.never.fork_scoped(), scope)
        closer = yield from in_scope(
            scope.close(fx.Success(None)).as_("closed").fork_scoped(), scope
        )
        closed = yield from closer.await_exit()
        sibling_exit = yield from sibling.await_exit()
        return closed, sibling_exit

    closed, sibling_exit = run(program)
    assert closed == fx.Success("closed")
    assert isinstance(sibling_exit, fx.Failure) and sibling_exit.cause.is_interrupted
