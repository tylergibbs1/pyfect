from collections.abc import Sequence
from dataclasses import dataclass

import pyfect as fx
from pyfect.batching import Entry, UncompletedRequestError


@dataclass
class DatabaseDown(fx.TaggedError):
    pass


@dataclass(frozen=True)
class GetPrice(fx.Request[int]):
    sku: str


PRICES = {"apple": 30, "pear": 45}


@dataclass
class Database:
    up: bool = True


database = Database()


@fx.fn
def run_all(entries: Sequence[Entry[GetPrice]]):
    if not database.up:
        # The run fails: every request it has not completed fails with this.
        return (yield from DatabaseDown())
    for entry in entries:
        if entry.request.sku in PRICES:
            yield from entry.succeed(PRICES[entry.request.sku])
        # Any other SKU is left uncompleted.


prices = fx.RequestResolver[GetPrice, DatabaseDown](run_all)


def price(sku: str) -> fx.Effect[int, DatabaseDown]:
    return fx.request(GetPrice(sku), prices)


@fx.fn
def program():
    both = fx.all(price("apple"), price("pear"), concurrency="unbounded")
    assert (yield from both) == (30, 45)

    database.up = False
    failed = yield from both.result()
    assert isinstance(failed, fx.Err) and isinstance(failed.error, DatabaseDown)

    # A request the run leaves uncompleted dies: that is a bug in the resolver.
    database.up = True
    lost = yield from price("plum").exit()
    assert isinstance(lost, fx.Failure)
    [defect] = lost.cause.defects
    assert isinstance(defect, UncompletedRequestError)


fx.run_blocking(program().or_die())
