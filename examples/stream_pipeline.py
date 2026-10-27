"""A streaming ingest pipeline: NDJSON orders in, priced batches out.

Orders arrive as newline-delimited JSON in byte chunks that split records
anywhere, as an HTTP body would. The pipeline

1. decodes the bytes into JSON values (``ndjson.decode``) and keeps the
   well-formed orders (``filter_map``),
2. prices each order with a flaky pricing service, four calls at a time
   (``map_effect(concurrency=4)``, which keeps the input order), retrying
   each failed call with exponential backoff,
3. lets pricing run at most ``BUFFER`` orders ahead of the batching
   (``buffer``): the warehouse is slower than pricing, so the buffer fills
   and pricing waits, and memory stays bounded however long the input is,
4. groups priced orders into batches of ``BATCH`` (``grouped``),
5. writes each batch to the warehouse with a sink (``sink.for_each``).

Run with: uv run examples/stream_pipeline.py
"""

import json
from dataclasses import dataclass

import pyfect as fx
from pyfect import schedule, sink, stream
from pyfect.encoding import Json, ndjson

CONCURRENCY = 4
BUFFER = 3
BATCH = 5
BOUND = CONCURRENCY + BUFFER + 2 * BATCH
"""The most orders that can be priced but not yet written: those finished
by the pricing calls, the buffer, a batch being filled and the batch being
written."""

# --- the input: NDJSON split at arbitrary byte boundaries ----------------------------

SKUS = ["apple", "pear", "fig", "plum", "kiwi"]
PRICES = {"apple": 30, "pear": 45, "fig": 80, "plum": 25, "kiwi": 60}


def body() -> fx.Stream[bytes]:
    """Thirty orders as one request body in 17-byte chunks, so records span
    chunks. Order 13 has no quantity."""
    records: list[dict[str, object]] = [
        {"id": n, "sku": SKUS[n % 5], "quantity": n % 4 + 1} for n in range(1, 31)
    ]
    del records[12]["quantity"]
    data = "\r\n".join(json.dumps(record) for record in records).encode()
    return stream.from_iterable([data[i : i + 17] for i in range(0, len(data), 17)])


@dataclass(frozen=True)
class Order:
    id: int
    sku: str
    quantity: int


def parse_order(value: Json) -> fx.Result[Order, Json]:
    match value:
        case {"id": int(id), "sku": str(sku), "quantity": int(quantity)}:
            return fx.Ok(Order(id, sku, quantity))
        case _:
            return fx.Err(value)


# --- a flaky pricing service and a slow warehouse ------------------------------------


@dataclass
class PricingUnavailable(fx.TaggedError):
    order_id: int


@dataclass(frozen=True)
class Priced:
    order: Order
    cents: int


class Pricing:
    """Fails the first call for every seventh order, as a busy service would."""

    def __init__(self) -> None:
        self.calls: dict[int, int] = {}
        self.priced = 0

    def price(self, order: Order) -> fx.Effect[Priced, PricingUnavailable]:
        def call() -> fx.Effect[Priced, PricingUnavailable]:
            attempt = self.calls[order.id] = self.calls.get(order.id, 0) + 1
            if order.id % 7 == 0 and attempt == 1:
                return fx.fail(PricingUnavailable(order.id))
            self.priced += 1
            return fx.succeed(Priced(order, PRICES[order.sku] * order.quantity))

        return fx.sleep(0.001).flat_map(lambda _: fx.suspend(call))


class Warehouse:
    def __init__(self, pricing: Pricing) -> None:
        self.pricing = pricing
        self.written = 0
        self.batches = 0
        self.most_waiting = 0  # priced orders not yet written, at its peak

    def write(self, batch: tuple[Priced, ...]) -> fx.Effect[None]:
        def store() -> None:
            self.most_waiting = max(self.most_waiting, self.pricing.priced - self.written)
            self.batches += 1
            self.written += len(batch)
            ids = ", ".join(str(priced.order.id) for priced in batch)
            total = sum(priced.cents for priced in batch) / 100
            print(f"batch {self.batches}: orders {ids}, ${total:.2f}")

        return fx.sleep(0.01).flat_map(lambda _: fx.sync(store))


# --- the pipeline ---------------------------------------------------------------------

type PipelineError = PricingUnavailable | ndjson.NdjsonError


def pipeline(pricing: Pricing, warehouse: Warehouse) -> fx.Effect[None, PipelineError]:
    def price(order: Order) -> fx.Effect[Priced, PricingUnavailable]:
        return pricing.price(order).retry(schedule=schedule.exponential(0.001), times=3)

    return (
        body()
        .pipe_through_channel(ndjson.decode())
        .filter_map(parse_order)
        .map_effect(price, concurrency=CONCURRENCY)
        .buffer(capacity=BUFFER)
        .grouped(BATCH)
        .run(sink.for_each(warehouse.write))
    )


def main() -> None:
    pricing = Pricing()
    warehouse = Warehouse(pricing)

    def failed(error: PipelineError) -> fx.Effect[None]:
        # A bad record, or an order still unpriced after every retry, stops
        # the run; the batches before it are already in the warehouse.
        return fx.sync(lambda: print(f"pipeline stopped: {error!r}"))

    fx.run_sync(pipeline(pricing, warehouse).catch_all(failed))
    retried = sorted(order_id for order_id, calls in pricing.calls.items() if calls > 1)
    print(f"{warehouse.written} orders written; retried {retried}")
    print(f"backpressure held: {warehouse.most_waiting <= BOUND}")


if __name__ == "__main__":
    main()
