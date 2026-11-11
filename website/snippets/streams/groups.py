import pyfect as fx
from pyfect import stream
from pyfect.stream import Stream

type Reading = tuple[str, int]

# Sensor "a" sends eight readings, then sensor "b" its second one.
readings: Stream[Reading] = stream.from_iterable(
    [("a", 1), ("b", 1), *[("a", n) for n in range(2, 9)], ("b", 2)]
).rechunk(1)


def read_for_300_millis(*, buffer_a: bool) -> list[Reading]:
    def handle(group: tuple[str, Stream[Reading]]) -> Stream[Reading]:
        key, values = group
        if key != "a":
            return values
        if buffer_a:  # pull a's readings ahead, dropping what doesn't fit
            values = values.buffer(capacity=1, strategy="dropping")
        return values.tap(lambda _: fx.sleep("1 second"))  # a slow reader

    out = (
        readings.group_by_key(lambda reading: reading[0], buffer_size=2)
        .flat_map(handle, concurrency="unbounded")
        .interrupt_when(fx.sleep("300 millis"))
    )
    return list(fx.run_blocking(out.run_collect()))


print(read_for_300_millis(buffer_a=False))  # b's second reading waits behind a's full group
print(read_for_300_millis(buffer_a=True))
