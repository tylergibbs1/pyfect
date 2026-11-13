import pyfect as fx


@fx.fn
def program():
    stock = yield from fx.TxSubscriptionRef.make(10)
    alerts = yield from fx.TxPubSub[str].unbounded()

    @fx.fn
    def sell(n: int):
        left = yield from stock.update_and_get(lambda s: s - n)
        if left < 5:
            # Published in the same transaction: a rolled-back sale alerts nobody.
            yield from alerts.publish(f"low stock: {left}")

    @fx.fn
    def watch():
        # Subscriptions last as long as the scope; changes() starts with the
        # current value.
        changes = yield from stock.changes()
        low = yield from alerts.subscribe()
        yield from fx.tx(sell(3))
        yield from fx.tx(sell(4))
        print((yield from changes.take_all()), (yield from low.take_all()))

    yield from fx.scoped(watch())


fx.run_blocking(program())
