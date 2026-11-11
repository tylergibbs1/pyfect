"""How deep fiber runs nest on one thread. A fork with ``start_immediately``
runs the child before the fork returns, however deep the chain; a resume
runs the woken fiber nested in the resumer up to 16 runs deep
(``_MAX_NESTED_RUNS``), past which it runs right after the innermost run."""

import pytest

import pyfect as fx

_MAX_NESTED_RUNS = 16


def test_a_chain_of_immediate_forks_runs_each_child_before_its_fork_returns():
    order: list[str] = []
    links = _MAX_NESTED_RUNS + 4

    def link(i: int) -> fx.Effect[None]:
        @fx.gen
        def body():
            order.append(f"start {i}")
            if i < links:
                yield from link(i + 1).fork(start_immediately=True)
            order.append(f"after {i}")

        return body

    fx.run_blocking(link(0))
    starts = [f"start {i}" for i in range(links + 1)]
    afters = [f"after {i}" for i in reversed(range(links + 1))]
    assert order == starts + afters


def test_a_cascade_of_resumes_nests_up_to_the_limit_then_runs_after_the_innermost_run():
    order: list[str] = []
    links = _MAX_NESTED_RUNS + 4

    @fx.gen
    def program():
        gates = yield from fx.for_each(range(links + 1), lambda _: fx.Deferred[None].make())

        def link(k: int) -> fx.Effect[None]:
            @fx.gen
            def body():
                yield from gates[k].wait()
                order.append(f"resumed {k}")
                yield from gates[k + 1].succeed(None)
                order.append(f"woke next {k}")

            return body

        fibers = yield from fx.for_each(
            range(links), lambda k: link(k).fork(start_immediately=True)
        )
        yield from gates[0].succeed(None)
        yield from fx.for_each(fibers, lambda f: f.await_exit())

    fx.run_blocking(program)
    nested = _MAX_NESTED_RUNS
    expected = [f"resumed {k}" for k in range(nested)]
    for k in range(nested - 1, links):
        # Too deep to nest: each woken fiber runs once its waker's run is over.
        expected += [f"woke next {k}"] + ([f"resumed {k + 1}"] if k + 1 < links else [])
    expected += [f"woke next {k}" for k in reversed(range(nested - 1))]
    assert order == expected


def test_ctrl_c_in_a_nested_run_loses_no_run_queued_behind_it():
    finalized: list[int] = []
    links = _MAX_NESTED_RUNS + 2
    # The deepest nested run: the fiber it wakes is queued behind it.
    deepest = _MAX_NESTED_RUNS - 1

    def ctrl_c() -> None:
        raise KeyboardInterrupt

    @fx.gen
    def program():
        gates = yield from fx.for_each(range(links + 1), lambda _: fx.Deferred[None].make())

        def link(k: int) -> fx.Effect[None]:
            @fx.gen
            def body():
                yield from gates[k].wait()
                yield from gates[k + 1].succeed(None)
                if k == deepest:
                    yield from fx.sync(ctrl_c)
                yield from fx.never

            return body.ensuring(fx.sync(lambda: finalized.append(k)))

        yield from fx.for_each(range(links), lambda k: link(k).fork(start_immediately=True))
        yield from gates[0].succeed(None)
        yield from fx.never

    with pytest.raises(KeyboardInterrupt):
        fx.run_blocking(program)
    assert sorted(finalized) == list(range(links))
