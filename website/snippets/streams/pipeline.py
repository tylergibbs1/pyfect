"""NDJSON in, a flaky service called four at a time, batches out."""

from dataclasses import dataclass

import pyfect as fx
from pyfect import schedule, sink, stream
from pyfect.encoding import Json, ndjson


@dataclass
class Unavailable(fx.TaggedError):
    order_id: int


calls: dict[int, int] = {}


def price(order: Json) -> fx.Effect[int, Unavailable]:
    """Fails the first call for order 3, as a busy service would."""
    assert isinstance(order, dict) and isinstance(order["id"], int)
    order_id = order["id"]

    def call() -> fx.Effect[int, Unavailable]:
        calls[order_id] = calls.get(order_id, 0) + 1
        if order_id == 3 and calls[order_id] == 1:
            return fx.fail(Unavailable(order_id))
        return fx.sleep(0.001).as_(order_id * 100)

    # suspend: each retry calls the service again, instead of reusing one result
    return fx.suspend(call)


written: list[tuple[int, ...]] = []

# Byte chunks that split records anywhere, as an HTTP body would.
body = stream.from_iterable([b'{"id": 1}\n{"id"', b': 2}\n{"id": 3}\n{"id": 4}\n{"id": 5}\n'])

pipeline = (
    body.pipe_through_channel(ndjson.decode())
    .map_effect(
        lambda o: price(o).retry(schedule=schedule.exponential(0.001), times=3), concurrency=4
    )
    .buffer(capacity=8)  # pricing runs at most 8 ahead of the writer: bounded memory
    .grouped(2)
    .run(sink.for_each(lambda batch: fx.sync(lambda: written.append(batch))))
)

assert fx.run_blocking_exit(pipeline) == fx.Success(None)
assert written == [(100, 200), (300, 400), (500,)]
assert calls[3] == 2  # retried once
