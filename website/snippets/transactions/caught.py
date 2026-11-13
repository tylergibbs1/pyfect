from dataclasses import dataclass

import pyfect as fx


@dataclass
class OutOfStock(fx.TaggedError):
    short: int


@fx.fn
def take(stock: fx.TxRef[int], amount: int):
    # Writes first, then checks: the write is in the journal when the failure happens.
    yield from stock.update(lambda left: left - amount)
    left = yield from stock.get()
    if left < 0:
        return (yield from OutOfStock(-left))


def ignore_out_of_stock(eff: fx.Effect[None, OutOfStock]) -> fx.Effect[None]:
    return eff.pipe(fx.catch_tag(OutOfStock, lambda _: fx.void))


@fx.fn
def program():
    # Caught outside tx: the transaction failed, so nothing it wrote commits.
    outside = fx.TxRef(1)
    yield from ignore_out_of_stock(fx.tx(take(outside, 3)))
    print("caught outside:", (yield from outside.get()))

    # Caught inside tx: the transaction succeeds and commits the write made before
    # the failure.
    inside = fx.TxRef(1)
    yield from fx.tx(ignore_out_of_stock(take(inside, 3)))
    print("caught inside:", (yield from inside.get()))


fx.run_blocking(program())
