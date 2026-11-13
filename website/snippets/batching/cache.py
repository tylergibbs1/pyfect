from collections.abc import Sequence
from dataclasses import dataclass

import pyfect as fx
from pyfect.batching import Entry

batches: list[list[str]] = []


@dataclass(frozen=True)
class GetStock(fx.Request[int]):
    sku: str


def run_all(entries: Sequence[Entry[GetStock]]) -> fx.Effect[None]:
    def answer() -> None:
        batches.append([entry.request.sku for entry in entries])
        for entry in entries:
            entry.complete_unsafe(fx.Success(len(entry.request.sku)))

    return fx.sync(answer)


@fx.fn
def program():
    stock = fx.RequestResolver(run_all)

    def lookup(skus: list[str]) -> fx.Effect[list[int]]:
        return fx.for_each(skus, lambda sku: fx.request(GetStock(sku), stock), concurrency=4)

    # Without a cache, equal requests are separate entries in the batch.
    yield from lookup(["apple", "apple", "pear"])
    print(batches)

    # with_cache remembers outcomes by request: an equal request made while one is
    # pending waits for it, and a later one is answered without a batch.
    batches.clear()
    cached = yield from stock.with_cache(capacity=100)

    def cached_lookup(skus: list[str]) -> fx.Effect[list[int]]:
        return fx.for_each(skus, lambda sku: fx.request(GetStock(sku), cached), concurrency=4)

    yield from cached_lookup(["apple", "apple", "pear"])
    yield from cached_lookup(["pear", "plum"])
    print(batches)


fx.run_blocking(program())
