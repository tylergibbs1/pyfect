from collections.abc import Callable

import pyfect as fx
from pyfect import schedule, sink, stream


class Broken(fx.TaggedError):
    pass


def add(acc: int, n: int) -> fx.Effect[int]:
    return fx.succeed(acc + n)


# A sum that never ends on its own: only the schedule ends a run.
total = sink.fold(lambda: 0, lambda _: True, add)


def show(label: str) -> Callable[[object], fx.Effect[None]]:
    return lambda value: fx.sync(lambda: print(label, value))


@fx.gen
def program():
    # transduce runs the sink again and again, each run starting where the last stopped.
    pairs = stream.make(1, 2, 3, 4, 5).transduce(sink.take(2))
    print("pairs", (yield from pairs.run_collect()))
    # aggregate does the same, folding on a fiber of its own while downstream is busy.
    triples = stream.make(1, 2, 3, 4, 5, 6).aggregate(sink.fold_until(lambda: 0, 3, add))
    print("triples", (yield from triples.run_collect()))

    # aggregate_within flushes a run when the schedule says so: spaced is a flush timer.
    events = yield from fx.Queue[int, fx.Done].unbounded()
    rollups = stream.from_queue(events).aggregate_within(total, schedule.spaced("100 millis"))
    fiber = yield from rollups.run_for_each(show("rollup")).fork()
    yield from events.offer_all([1, 2, 3])
    yield from fx.sleep("300 millis")
    yield from events.offer_all([10, 20])
    yield from fx.sleep("300 millis")
    yield from events.end()
    yield from fiber.join()

    # An upstream failure: transduce emits the partial run first, aggregate_within drops it.
    failing = stream.make(1, 2, 3).concat(stream.fail(Broken()))
    transduced = failing.transduce(sink.take(2)).run_for_each(show("transduce"))
    print("transduce ended", (yield from transduced.result()))
    within = failing.aggregate_within(total, schedule.spaced("1 second"))
    aggregated = within.run_for_each(show("aggregate_within"))
    print("aggregate_within ended", (yield from aggregated.result()))


fx.run_blocking(program)
