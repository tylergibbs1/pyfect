"""Every fiber has its own dispatcher, as in Effect (``fiber.currentDispatcher``).

A fiber's tasks (the children it forks without starting them, its yields, the
wakes it makes) wait in its dispatcher, which runs them all in one task of the
run, queued when the first of them arrives. So a task joins its fiber's batch
if one is pending, ahead of tasks other fibers queued since. Expected orders
printed by Effect 4.1.2 under Node. Found by tests/runtime_diff.
"""

from collections.abc import Callable

import pyfect as fx


def _logger() -> tuple[list[str], Callable[[str], fx.Effect[None]]]:
    log: list[str] = []
    return log, lambda s: fx.sync(lambda: log.append(s))


def test_a_fork_joins_its_parents_pending_batch():
    """Node: [ 'A', 'B', 'X' ]: B waits with A in main's batch, which was
    queued before the batch of the child started at once, where X waits."""
    log, say = _logger()

    @fx.gen
    def main():
        yield from say("A").fork()
        yield from say("X").fork().and_then(fx.never).fork(start_immediately=True)
        b = yield from say("B").fork()
        yield from b.join()
        yield from fx.sleep("5 millis")

    fx.run_blocking(main)
    assert log == ["A", "B", "X"]


def test_a_batch_outlives_the_fiber_run_that_queued_it():
    """Node: main's batch holds the start of a fiber it interrupted before it
    ran; interrupting it ends it at once, so main never waits, and B joins
    that batch, ahead of the daemon's, where its grandchild A waits."""
    log, say = _logger()

    @fx.gen
    def daemon():
        yield from say("D start")
        yield from say("A: grandchild").fork()
        yield from say("D forked A")
        yield from fx.never

    @fx.gen
    def main():
        p1 = yield from say("p1 ran").fork()
        yield from p1.interrupt()
        yield from say("main resumed")
        yield from daemon.fork_daemon(start_immediately=True)
        yield from say("main forked D")
        b = yield from say("B: later child").fork_daemon()
        yield from b.join()
        yield from fx.sleep("5 millis")

    fx.run_blocking(main)
    assert log == [
        "main resumed",
        "D start",
        "D forked A",
        "main forked D",
        "B: later child",
        "A: grandchild",
    ]
