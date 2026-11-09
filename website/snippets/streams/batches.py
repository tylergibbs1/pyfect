import pyfect as fx
from pyfect import sink, stream


def deliver(batch: list[int]) -> fx.Effect[None]:
    return fx.sync(lambda: print("posted", batch))


@fx.gen
def program():
    events = yield from fx.Queue[int, fx.Done].unbounded()
    # Up to three items per batch, and a batch waits at most 50ms for more:
    # a burst goes out in full batches, a straggler without waiting forever.
    delivery = stream.from_queue(events).grouped_within(3, "50 millis").run(sink.for_each(deliver))
    fiber = yield from delivery.fork()
    yield from events.offer_all(range(7))  # a burst
    yield from fx.sleep("200 millis")
    yield from events.offer(7)  # a straggler
    yield from fx.sleep("200 millis")
    yield from events.end()
    yield from fiber.join()


fx.run_blocking(program)
