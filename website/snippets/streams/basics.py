import pyfect as fx
from pyfect import stream

# A stream is a description too: nothing is pulled until it runs.
evens = stream.range(0, 99).filter(lambda n: n % 2 == 0).map(lambda n: n * n).take(4)

squares = fx.run_blocking(evens.run_collect())
print(squares)
assert squares == [0, 4, 16, 36]


def lookup(n: int) -> fx.Effect[str]:
    return fx.sleep("10 millis").as_(f"item {n}")


# map_effect runs an effect per item, here three at a time, keeping the order.
items = stream.from_iterable([1, 2, 3, 4]).map_effect(lookup, concurrency=3)
pairs = fx.run_blocking(items.grouped(2).run_collect())
print(pairs)
assert pairs == [("item 1", "item 2"), ("item 3", "item 4")]
