import pyfect as fx
from pyfect import stream
from pyfect.stream import Stream


@fx.fn
def both_readers(source: Stream[int]):
    # Two streams of the same chunks; "sliding" keeps the newest chunk for a slow reader.
    fast, slow = yield from source.broadcast_n(2, capacity=1, strategy="sliding")
    slowed = slow.tap(lambda _: fx.sleep("10 millis"))
    return (yield from fx.all(fast.run_collect(), slowed.run_collect(), concurrency="unbounded"))


# Capacity counts chunks: one chunk of six items fits in a capacity of 1.
print(fx.run_blocking(fx.scoped(both_readers(stream.make(0, 1, 2, 3, 4, 5)))))
# Six chunks of one item don't: the slow reader sees the first and the newest.
print(fx.run_blocking(fx.scoped(both_readers(stream.make(0, 1, 2, 3, 4, 5).rechunk(1)))))
