"""A fiber paused for its step budget waits its turn like a ``yield_now``:
at priority 0, behind tasks queued before it and ahead of those after."""

import pyfect as fx


def test_a_fiber_paused_for_its_budget_resumes_before_a_later_yield():
    order: list[str] = []

    @fx.gen
    def steps():
        for _ in range(200):
            yield from fx.sync(lambda: order.append("a"))

    @fx.gen
    def program():
        long = yield from steps.fork(start_immediately=True)
        # ``long`` paused for its budget before the fork returned.
        order.append("paused")
        later = yield from (
            fx.yield_now().and_then(fx.sync(lambda: order.append("b"))).fork(start_immediately=True)
        )
        yield from long.await_exit()
        yield from later.await_exit()

    fx.run_blocking(program.pipe(fx.provide_service(fx.MaxOpsBeforeYield, 32)))
    paused = order.index("paused")
    assert 0 < paused < 200
    assert order[paused + 1] == "a"
    assert "b" in order
