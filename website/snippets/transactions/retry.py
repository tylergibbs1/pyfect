import pyfect as fx

stock = fx.TxRef(0)


@fx.fn
def take(n: int):
    available = yield from stock.get()
    if available < n:
        # Roll back and wait: the transaction runs again once a ref it read changes.
        return (yield from fx.tx_retry)
    yield from stock.set(available - n)
    return n


@fx.fn
def program():
    buyer = yield from fx.tx(take(3)).fork()
    for _ in range(3):
        yield from fx.sleep("10 millis")
        yield from stock.update(lambda n: n + 1)
        print("restocked to", (yield from stock.get()))
    print("bought", (yield from buyer.join()), "left", (yield from stock.get()))


fx.run_blocking(program())
