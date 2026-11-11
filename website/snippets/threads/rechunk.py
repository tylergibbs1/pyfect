import pyfect as fx
from pyfect import stream
from pyfect.stream import Stream


def per_key(items: Stream[int]) -> fx.Effect[int]:
    """Groups ``items`` into four keys and counts what the groups read back."""
    groups = items.group_by_key(lambda n: n % 4)
    return groups.flat_map(lambda group: group[1], concurrency="unbounded").run_count()


def chunks(items: Stream[int]) -> int:
    return fx.run_blocking(items.chunks().run_count())


# Items that arrive one at a time, as from a queue fed one item at a time.
arriving = stream.range(1, 1000, chunk_size=1)
print("chunks as they arrive:", chunks(arriving))
print("after rechunk(64):", chunks(arriving.rechunk(64)))
# Same result, but group_by_key now pays its per-chunk cost 16 times instead of 1000.
print(
    "items grouped:",
    fx.run_blocking(per_key(arriving)),
    fx.run_blocking(per_key(arriving.rechunk(64))),
)
# On a live source, rechunk holds items until it has 64; grouped_within also lets a
# partial batch go after 10 ms.
live = arriving.grouped_within(64, "10 millis").flatten_iterable()
print("grouped_within(64, ...):", chunks(live))
