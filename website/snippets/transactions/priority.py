from dataclasses import dataclass

import pyfect as fx


@dataclass(frozen=True)
class Run:
    job: str
    priority: int  # 0 runs first


@fx.fn
def program():
    # `key=` orders the queue, smallest first, as `sorted(key=...)` would.
    # Runs with the same key come out in the order they went in.
    queue = yield from fx.TxPriorityQueue[Run].empty(key=lambda run: run.priority)

    @fx.fn
    def enqueue_due():
        # Offered in one transaction: a taker sees all of them or none.
        yield from queue.offer(Run("report", 2))
        yield from queue.offer(Run("backup", 0))
        yield from queue.offer(Run("mirror", 1))
        yield from queue.offer(Run("cleanup", 2))

    yield from fx.tx(enqueue_due())
    taken = yield from fx.for_each(range(4), lambda _: queue.take())
    print([run.job for run in taken])


fx.run_sync(program())
