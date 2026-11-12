"""What a fiber keeps track of besides its result: runtime metrics, the
``contextvars`` context it resumes in, and how long the runtime keeps the
context of a fiber that is done."""

import contextvars
import gc
import weakref

import pyfect as fx
from pyfect import metric


def test_runtime_metrics_count_the_fibers_forked_inside():
    @fx.gen
    def body():
        child = yield from fx.void.fork()
        yield from child.await_exit()
        return {s.id: s.state for s in (yield from metric.snapshot)}

    states = fx.run_blocking(
        metric.enable_runtime_metrics(body).pipe(fx.provide_service(metric.MetricRegistry, {}))
    )
    assert states["child_fibers_started"] == metric.CounterState(1, True)
    assert states["child_fiber_successes"] == metric.CounterState(1, True)


_where: contextvars.ContextVar[str] = contextvars.ContextVar("where", default="unset")


def test_a_fiber_resumed_by_another_resumes_in_its_own_contextvars():
    @fx.gen
    def program():
        yield from fx.sync(lambda: _where.set("parent"))
        gate = yield from fx.Deferred[None].make()

        @fx.gen
        def child():
            yield from fx.sync(lambda: _where.set("child"))
            yield from gate.succeed(None)

        yield from child.fork()
        # Parks the root fiber of run_sync; the child resumes it from its
        # own copy of the context.
        yield from gate.wait()
        return _where.get()

    assert contextvars.copy_context().run(fx.run_sync, program) == "parent"


class _Held:
    pass


class _Service(fx.Tag[_Held]):
    pass


class _Other(fx.Tag[int]):
    pass


def _child_ending_in_a_context_its_parent_left(held: _Held) -> fx.Effect[None]:
    @fx.gen
    def run():
        # The child is forked in the service's context, which the parent
        # leaves before the child runs; the child switches contexts and
        # ends in it.
        child = yield from (
            fx.void.pipe(fx.provide_service(_Other, 1))
            .fork()
            .pipe(fx.provide_service(_Service, held))
        )
        yield from child.await_exit()

    return run


def test_the_context_of_a_child_that_ends_after_its_parent_left_it_is_not_kept():
    held = _Held()
    ref = weakref.ref(held)
    program = _child_ending_in_a_context_its_parent_left(held)
    del held
    fx.run_blocking(program)
    del program
    gc.collect()
    assert ref() is None


def test_a_daemon_fiber_does_not_keep_the_fiber_that_forked_it():
    @fx.gen
    def program():
        gate = yield from fx.Deferred[None].make()
        parent = yield from gate.wait().fork_daemon().fork()
        daemon = yield from parent.join()
        parent_ref = weakref.ref(parent)
        del parent
        # Out of the parent's run, which resumed this fiber when it ended.
        yield from fx.yield_now()
        gc.collect()
        released = parent_ref() is None
        yield from gate.succeed(None)
        yield from daemon.await_exit()
        return released

    assert fx.run_blocking(program)


def test_the_context_a_run_was_given_is_not_kept_after_it():
    held = _Held()
    ref = weakref.ref(held)
    fx.run_blocking(fx.void, context=fx.Context.make(_Service, held))
    del held
    gc.collect()
    assert ref() is None
